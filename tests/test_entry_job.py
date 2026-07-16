import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from webapp.automation.entry import (
    BATTLE_PREPARE_JOB_KIND,
    _available_apple,
    create_battle_entry_handler,
    register_battle_entry_job,
)
from webapp.core.models import MatchResult
from webapp.devices.coordinates import FrameNormalizer
from webapp.devices.replay import ReplayBackend
from webapp.runtime import JobDatabase, JobManager, JobStatus
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService
from webapp.services.script_data import ScriptDataService


class _AppleMatch:
    def __init__(self, matched: bool) -> None:
        self.matched = matched


class _AppleRecognition:
    def __init__(self, available: str) -> None:
        self.available = available
        self.checked: list[str] = []

    def match_template(self, _screenshot, template_path, **_options):
        apple_name = template_path.rsplit("/", 1)[-1].removesuffix(".png")
        self.checked.append(apple_name)
        return _AppleMatch(apple_name == self.available)


def test_battle_prepare_strict_team_check_stops_before_confirmation():
    class ScriptDataStub:
        def get_setting_plan(self, _name):
            return {
                "server": "CH",
                "run": {
                    "random_touch": False,
                    "random_time": 0,
                    "allow_other_apple": False,
                },
                "servants": [],
                "master": {"equip": None, "name": None},
            }

    class DeviceStub:
        def __init__(self):
            self.taps = []

        def snapshot(self):
            return b"team"

        def tap(self, x, y):
            self.taps.append((x, y))
            raise AssertionError("strict team mismatch must not confirm the team")

    class RecognitionStub:
        def match_template(self, _screenshot, template_path, **_options):
            matched = template_path.endswith("teamDecide.png")
            return MatchResult(
                template_path=template_path,
                matched=matched,
                confidence=1.0 if matched else 0.0,
                threshold=0.85,
                top_left=[600, 500],
                size=[80, 40],
                center=[640, 520],
            )

    report = {
        "ok": False,
        "mismatch_count": 1,
        "unverified_count": 0,
        "servants": [],
        "master": {"status": "mismatch"},
    }

    class TeamRecognizerStub:
        def recognize(self, screenshot, plan):
            assert screenshot == b"team"
            assert plan["server"] == "CH"
            return report

    class ContextStub:
        def __init__(self):
            self.events = []

        def checkpoint(self, *_args, **_kwargs):
            pass

        def emit(self, event_type, message, *, data=None):
            self.events.append((event_type, message, data))

        def sleep(self, _seconds):
            pass

    device = DeviceStub()
    context = ContextStub()
    result = create_battle_entry_handler(
        ScriptDataStub(),
        device,
        RecognitionStub(),
        TeamRecognizerStub(),
    )(
        context,
        {
            "setting_name": "demo",
            "team_check_mode": "strict",
            "timeout_seconds": 1,
            "poll_interval": 0,
        },
    )

    assert result["ready"] is False
    assert result["reason"] == "team_mismatch"
    assert result["team_verification"] == report
    assert device.taps == []
    assert context.events[-1][0] == "team_verification"


def test_available_apple_only_falls_back_when_enabled():
    restricted = _AppleRecognition("silver")
    assert _available_apple(
        restricted,
        b"screen",
        "CH",
        preferred="gold",
        allow_other=False,
    ) is None
    assert restricted.checked == ["gold"]

    fallback = _AppleRecognition("silver")
    result = _available_apple(
        fallback,
        b"screen",
        "CH",
        preferred="gold",
        allow_other=True,
    )
    assert result is not None
    assert result[0] == "silver"
    assert fallback.checked == ["gold", "silver"]


def test_battle_prepare_uses_crawl_tower_auto_formation():
    class ScriptDataStub:
        def get_setting_plan(self, _name):
            return {
                "server": "CH",
                "run": {
                    "random_touch": False,
                    "random_time": 0,
                    "allow_other_apple": False,
                },
            }

    class DeviceStub:
        def __init__(self):
            self.frames = iter((b"formation", b"battle"))
            self.taps = []

        def snapshot(self):
            return next(self.frames)

        def tap(self, x, y):
            self.taps.append((x, y))

            class Operation:
                def to_dict(self):
                    return {"ok": True}

            return Operation()

    class RecognitionStub:
        def match_template(self, screenshot, template_path, **_options):
            matched = (
                screenshot == b"formation"
                and template_path == "battle/CrawlTower/CH/zdbc.png"
            ) or (
                screenshot == b"battle"
                and template_path == "battle/CH/attack.png"
            )
            return MatchResult(
                template_path=template_path,
                matched=matched,
                confidence=1.0 if matched else 0.0,
                threshold=0.85,
                top_left=[500, 400],
                size=[200, 60],
                center=[600, 430],
            )

    class ContextStub:
        def checkpoint(self, *_args, **_kwargs):
            pass

        def emit(self, *_args, **_kwargs):
            pass

        def sleep(self, _seconds):
            pass

    device = DeviceStub()
    result = create_battle_entry_handler(
        ScriptDataStub(),
        device,
        RecognitionStub(),
    )(
        ContextStub(),
        {
            "setting_name": "tower",
            "timeout_seconds": 1,
            "poll_interval": 0,
            "action_wait_seconds": 0,
        },
    )

    assert result["ready"] is True
    assert result["actions"] == ["auto_formation"]
    assert device.taps == [(600, 430)]


def test_battle_prepare_job_confirms_team_starts_quest_and_waits_for_battle(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    session = tmp_path / "replays" / "prepare"
    battle_assets = assets / "battle" / "CH"
    settings = data / "settings"
    battle_assets.mkdir(parents=True)
    settings.mkdir(parents=True)
    session.mkdir(parents=True)

    def pattern(size: tuple[int, int], color: tuple[int, int, int]) -> Image.Image:
        image = Image.new("RGB", size, color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((2, 2, size[0] - 3, size[1] - 3), outline=(245, 220, 70), width=2)
        draw.line((3, size[1] - 4, size[0] - 4, 3), fill=(40, 220, 235), width=2)
        return image

    team_decide = pattern((80, 40), (80, 65, 150))
    start_task = pattern((120, 45), (35, 120, 170))
    attack = pattern((90, 45), (150, 55, 80))
    reconnect = Image.new("RGB", (114, 53), (25, 35, 45))
    reconnect_draw = ImageDraw.Draw(reconnect)
    reconnect_draw.ellipse((8, 5, 48, 45), outline=(235, 195, 55), width=4)
    reconnect_draw.ellipse((65, 5, 105, 45), outline=(55, 205, 235), width=4)
    reconnect_draw.line((30, 26, 84, 26), fill=(230, 75, 125), width=5)
    team_decide.save(battle_assets / "teamDecide.png")
    start_task.save(battle_assets / "start_task.png")
    attack.save(battle_assets / "attack.png")
    reconnect.save(battle_assets / "reconnect.png")
    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    reconnect_frame = base.copy()
    reconnect_frame.paste(reconnect, (580, 380))
    team_frame = base.copy()
    team_frame.paste(team_decide, (600, 500))
    start_frame = base.copy()
    start_frame.paste(start_task, (1050, 620))
    battle_frame = base.copy()
    battle_frame.paste(attack, (1100, 600))
    for index, frame in enumerate(
        (reconnect_frame, team_frame, start_frame, battle_frame)
    ):
        frame.save(session / f"{index}.png")
    (session / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "device_id": "prepare",
                "frames": [
                    {
                        "file": "0.png",
                        "expect": {"type": "tap", "x": 637, "y": 406},
                    },
                    {
                        "file": "1.png",
                        "expect": {"type": "tap", "x": 640, "y": 520},
                    },
                    {
                        "file": "2.png",
                        "expect": {"type": "tap", "x": 1110, "y": 642},
                    },
                    {"file": "3.png"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (data / "servant_info_CH.json").write_text("{}", encoding="utf-8")
    (settings / "prepare.json").write_text(
        json.dumps({"server": "CH"}),
        encoding="utf-8",
    )

    resources = ResourceService(assets, data)
    recognition = RecognitionService(resources)
    devices = DeviceService(
        [ReplayBackend(tmp_path / "replays")],
        EventLog(),
        frame_normalizer=FrameNormalizer(),
    )
    devices.connect("replay", "prepare")
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_battle_entry_job(
            manager,
            ScriptDataService(data),
            devices,
            recognition,
        )
        job = manager.start(
            BATTLE_PREPARE_JOB_KIND,
            {
                "setting_name": "prepare",
                "timeout_seconds": 5,
                "poll_interval": 0,
                "action_wait_seconds": 0,
            },
            device_key="replay:prepare",
        )
        result = manager.wait(job.job_id, timeout=8)

    assert result.status == JobStatus.SUCCEEDED, result.error
    assert result.result["setting_name"] == "prepare"
    assert result.result["ready"] is True
    assert result.result["actions"] == ["reconnect", "team_decide", "start_task"]
    assert result.result["attempts"] == 4


def test_battle_prepare_job_consumes_available_apple_when_ap_is_empty(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    session = tmp_path / "replays" / "apple"
    battle_assets = assets / "battle" / "CH"
    settings = data / "settings"
    battle_assets.mkdir(parents=True)
    settings.mkdir(parents=True)
    session.mkdir(parents=True)

    def pattern(size: tuple[int, int], color: tuple[int, int, int]) -> Image.Image:
        image = Image.new("RGB", size, color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((2, 2, size[0] - 3, size[1] - 3), outline=(245, 220, 70), width=2)
        draw.line((3, size[1] - 4, size[0] - 4, 3), fill=(40, 220, 235), width=2)
        return image

    apple_close = pattern((80, 40), (90, 55, 135))
    apple_decide = pattern((85, 42), (45, 125, 165))
    gold = pattern((45, 45), (175, 125, 35))
    attack = pattern((90, 45), (150, 55, 80))
    apple_close.save(battle_assets / "apple_close.png")
    apple_decide.save(battle_assets / "apple_decide.png")
    gold.save(battle_assets / "gold.png")
    attack.save(battle_assets / "attack.png")
    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    apple_frame = base.copy()
    apple_frame.paste(apple_close, (800, 600))
    apple_frame.paste(gold, (400, 300))
    decide_frame = base.copy()
    decide_frame.paste(apple_decide, (700, 580))
    battle_frame = base.copy()
    battle_frame.paste(attack, (1100, 600))
    for index, frame in enumerate((apple_frame, decide_frame, battle_frame)):
        frame.save(session / f"{index}.png")
    (session / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "device_id": "apple",
                "frames": [
                    {
                        "file": "0.png",
                        "expect": {"type": "tap", "x": 422, "y": 322},
                    },
                    {
                        "file": "1.png",
                        "expect": {"type": "tap", "x": 742, "y": 601},
                    },
                    {"file": "2.png"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (data / "servant_info_CH.json").write_text("{}", encoding="utf-8")
    (settings / "apple.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "clearAP": 0,
                "allowOtherApple": 1,
            }
        ),
        encoding="utf-8",
    )

    resources = ResourceService(assets, data)
    recognition = RecognitionService(resources)
    devices = DeviceService(
        [ReplayBackend(tmp_path / "replays")],
        EventLog(),
        frame_normalizer=FrameNormalizer(),
    )
    devices.connect("replay", "apple")
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_battle_entry_job(
            manager,
            ScriptDataService(data),
            devices,
            recognition,
        )
        job = manager.start(
            BATTLE_PREPARE_JOB_KIND,
            {
                "setting_name": "apple",
                "timeout_seconds": 2,
                "poll_interval": 0,
                "action_wait_seconds": 0,
                "recover_ap": True,
            },
            device_key="replay:apple",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["ready"] is True
    assert result.result["actions"] == ["apple_gold", "apple_decide"]
