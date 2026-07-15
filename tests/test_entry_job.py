import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from webapp.automation.entry import (
    BATTLE_PREPARE_JOB_KIND,
    _available_apple,
    register_battle_entry_job,
)
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
    team_decide.save(battle_assets / "teamDecide.png")
    start_task.save(battle_assets / "start_task.png")
    attack.save(battle_assets / "attack.png")
    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    team_frame = base.copy()
    team_frame.paste(team_decide, (600, 500))
    start_frame = base.copy()
    start_frame.paste(start_task, (1050, 620))
    battle_frame = base.copy()
    battle_frame.paste(attack, (1100, 600))
    for index, frame in enumerate((team_frame, start_frame, battle_frame)):
        frame.save(session / f"{index}.png")
    (session / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "device_id": "prepare",
                "frames": [
                    {
                        "file": "0.png",
                        "expect": {"type": "tap", "x": 640, "y": 520},
                    },
                    {
                        "file": "1.png",
                        "expect": {"type": "tap", "x": 1110, "y": 642},
                    },
                    {"file": "2.png"},
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
                "timeout_seconds": 2,
                "poll_interval": 0,
                "action_wait_seconds": 0,
            },
            device_key="replay:prepare",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["setting_name"] == "prepare"
    assert result.result["ready"] is True
    assert result.result["actions"] == ["team_decide", "start_task"]
    assert result.result["attempts"] == 3


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
                "clearAP": 1,
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
            },
            device_key="replay:apple",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["ready"] is True
    assert result.result["actions"] == ["apple_gold", "apple_decide"]
