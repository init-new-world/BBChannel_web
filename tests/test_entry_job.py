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
from webapp.services.team import TeamRecognizer


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


@pytest.mark.parametrize("preferred", ["gold", "silver", "blue", "copper"])
def test_apple_fallback_exhausts_only_apples_and_never_uses_saint_quartz(preferred):
    recognition = _AppleRecognition("stone")
    assert _available_apple(
        recognition,
        b"screen",
        "CH",
        preferred=preferred,
        allow_other=True,
    ) is None
    assert recognition.checked == [
        preferred, *[name for name in ("gold", "silver", "blue", "copper") if name != preferred],
    ]


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


def test_battle_prepare_crawl_tower_triggers_auto_formation_from_team_screen():
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
            self.frames = iter((b"team", b"formation", b"team", b"battle"))
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
                screenshot == b"team"
                and template_path == "battle/CH/teamDecide.png"
            ) or (
                screenshot == b"formation"
                and template_path == "battle/CrawlTower/CH/zdbc.png"
            ) or (
                screenshot == b"battle"
                and template_path == "battle/CH/attack.png"
            )
            center = [600, 430] if template_path.endswith("zdbc.png") else [640, 520]
            return MatchResult(
                template_path=template_path,
                matched=matched,
                confidence=1.0 if matched else 0.0,
                threshold=0.85,
                top_left=[center[0] - 40, center[1] - 20],
                size=[80, 40],
                center=center,
            )

    class TeamRecognizerStub:
        def recognize(self, *_args, **_kwargs):
            raise AssertionError("CrawlTower must skip team verification")

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
        TeamRecognizerStub(),
    )(
        ContextStub(),
        {
            "setting_name": "tower",
            "crawl_tower": True,
            "team_check_mode": "strict",
            "timeout_seconds": 1,
            "poll_interval": 0,
            "action_wait_seconds": 0,
        },
    )

    assert result["ready"] is True
    assert result["actions"] == [
        "auto_formation_trigger",
        "auto_formation",
        "team_decide",
    ]
    assert device.taps == [(297, 677), (600, 430), (640, 520)]


def test_battle_prepare_does_not_treat_team_screen_as_phase_one():
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
            self.frames = iter((b"team", b"battle"))
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
        def match_template(self, screenshot, template_path, **options):
            confidence = 0.0
            if screenshot == b"team" and template_path.endswith("phase_1.png"):
                confidence = 0.879
            if screenshot == b"team" and template_path.endswith("start_task.png"):
                confidence = 0.845
            if screenshot == b"battle" and template_path.endswith("attack.png"):
                confidence = 1.0
            return MatchResult(
                template_path=template_path,
                matched=confidence >= options["threshold"],
                confidence=confidence,
                threshold=options["threshold"],
                top_left=[1080, 620],
                size=[120, 50],
                center=[1140, 645],
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
            "setting_name": "demo",
            "timeout_seconds": 1,
            "poll_interval": 0,
            "action_wait_seconds": 0,
        },
    )

    assert result["ready"] is True
    assert result["actions"] == ["start_task"]
    assert device.taps == [(1140, 645)]


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


def test_available_apple_skips_darkened_zero_count_icon_and_scrolls_for_copper(tmp_path: Path):
    pytest.importorskip("cv2")
    import io

    assets = tmp_path / "assets"
    data = tmp_path / "data"
    battle_assets = assets / "battle" / "CH"
    battle_assets.mkdir(parents=True)

    def make_icon(scale_brightness: float, outline_rgb: tuple[int, int, int]) -> Image.Image:
        image = Image.new(
            "RGB",
            (48, 48),
            tuple(round(c * scale_brightness) for c in (210, 160, 45)),
        )
        draw = ImageDraw.Draw(image)
        draw.rectangle(
            (4, 4, 43, 43),
            outline=tuple(round(c * scale_brightness) for c in outline_rgb),
            width=3,
        )
        draw.line(
            (6, 41, 41, 6),
            fill=tuple(round(c * scale_brightness) for c in (250, 240, 120)),
            width=3,
        )
        return image

    gold_template = make_icon(1.0, (255, 220, 60))
    copper_template = make_icon(1.0, (190, 95, 50))
    gold_template.save(battle_assets / "gold.png")
    copper_template.save(battle_assets / "copper.png")

    top_screen = Image.new("RGB", (1280, 720), (18, 24, 32))
    # Darkened gold icon (0 remaining: 0.4x brightness still matches template correlation >= 0.99)
    top_screen.paste(make_icon(0.4, (255, 220, 60)), (400, 220))
    top_buf = io.BytesIO()
    top_screen.save(top_buf, format="PNG")
    top_bytes = top_buf.getvalue()

    bottom_screen = Image.new("RGB", (1280, 720), (18, 24, 32))
    bottom_screen.paste(copper_template, (400, 480))
    bottom_buf = io.BytesIO()
    bottom_screen.save(bottom_buf, format="PNG")
    bottom_bytes = bottom_buf.getvalue()

    resources = ResourceService(assets, data)
    recognition = RecognitionService(resources)

    # Without allow_other, darkened gold is rejected by halfMode color check
    assert (
        _available_apple(
            recognition,
            top_bytes,
            "CH",
            preferred="gold",
            allow_other=False,
        )
        is None
    )

    swipes: list[tuple[int, int, int, int, int]] = []

    class ScrollDevice:
        def swipe(self, x1, y1, x2, y2, duration_ms):
            swipes.append((x1, y1, x2, y2, duration_ms))

            class Operation:
                def to_dict(self):
                    return {"ok": True}

            return Operation()

        def snapshot(self):
            return bottom_bytes

    matched = _available_apple(
        recognition,
        top_bytes,
        "CH",
        preferred="gold",
        allow_other=True,
        device_service=ScrollDevice(),
    )
    assert matched is not None
    assert matched[0] == "copper"
    assert swipes == [(1014, 453, 1014, 620, 200)]


def test_battle_prepare_job_waits_for_ce_card_flip_and_skips_prebattle_story(tmp_path: Path):
    pytest.importorskip("cv2")
    import io

    assets = tmp_path / "assets"
    data = tmp_path / "data"
    battle_assets = assets / "battle" / "CH"
    public_assets = assets / "battle" / "public"
    servant_faces = assets / "servantface"
    settings = data / "settings"
    battle_assets.mkdir(parents=True)
    public_assets.mkdir(parents=True)
    servant_faces.mkdir(parents=True)
    settings.mkdir(parents=True)

    def pattern(size: tuple[int, int], color: tuple[int, int, int]) -> Image.Image:
        image = Image.new("RGB", size, color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((2, 2, size[0] - 3, size[1] - 3), outline=(245, 220, 70), width=2)
        draw.line((3, size[1] - 4, size[0] - 4, 3), fill=(40, 220, 235), width=2)
        return image

    def png_bytes(img: Image.Image) -> bytes:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    team_decide = pattern((80, 40), (80, 65, 150))
    gold_back = Image.new("RGB", (60, 80), (195, 165, 45))
    gold_draw = ImageDraw.Draw(gold_back)
    gold_draw.polygon([(30, 5), (55, 40), (30, 75), (5, 40)], outline=(255, 240, 120), fill=(160, 120, 25))
    first_servant = Image.new("RGB", (60, 60), (65, 130, 180))
    first_draw = ImageDraw.Draw(first_servant)
    first_draw.ellipse((8, 8, 52, 52), outline=(240, 220, 90), width=4)
    second_servant = Image.new("RGB", (60, 60), (160, 70, 120))
    second_draw = ImageDraw.Draw(second_servant)
    second_draw.line((8, 8, 52, 52), fill=(90, 240, 180), width=5)
    second_draw.line((8, 52, 52, 8), fill=(240, 180, 90), width=5)
    need_skip = pattern((40, 36), (185, 65, 55))
    skip_confirm = pattern((70, 36), (50, 150, 95))
    tips_icon = Image.new("RGB", (64, 44), (130, 110, 180))
    tips_draw = ImageDraw.Draw(tips_icon)
    tips_draw.ellipse((6, 6, 58, 38), outline=(250, 210, 80), width=3)
    tips_draw.line((32, 6, 32, 38), fill=(80, 240, 210), width=3)
    attack = pattern((90, 45), (150, 55, 80))

    team_decide.save(battle_assets / "teamDecide.png")
    gold_back.save(public_assets / "goldBack.png")
    first_servant.save(servant_faces / "First_1.png")
    second_servant.save(servant_faces / "Second_1.png")
    need_skip.save(battle_assets / "needSkip.png")
    skip_confirm.save(battle_assets / "listupdate.png")
    tips_icon.save(battle_assets / "tips.png")
    attack.save(battle_assets / "attack.png")

    base = Image.new("RGB", (1280, 720), (18, 24, 32))
    # Frame 0: team_decide visible, but slot 0 shows goldBack (CE flip) -> no tap, waits
    frame_flip = base.copy()
    frame_flip.paste(team_decide, (600, 500))
    frame_flip.paste(gold_back, (80, 220))
    # Frame 1: team_decide visible, both slots mid-transition (2 mismatches -> triggers 1 retry)
    frame_mid_anim = base.copy()
    frame_mid_anim.paste(team_decide, (600, 500))
    # Frame 2: retry snapshot shows both servants matched -> taps team_decide (640, 520)
    frame_team_ok = base.copy()
    frame_team_ok.paste(team_decide, (600, 500))
    frame_team_ok.paste(first_servant, (80, 220))
    frame_team_ok.paste(second_servant, (280, 220))
    # Frame 3: pre-battle story needSkip in STORY_SKIP_ROI (1193, 573, 67, 80) -> taps (1197, 40)
    frame_need_skip = base.copy()
    frame_need_skip.paste(need_skip, (1205, 590))
    # Frame 4: story skip confirm (listupdate.png) in STORY_SKIP_CONFIRM_ROI (767, 533, 113, 60) -> taps center (815, 563)
    frame_skip_confirm = base.copy()
    frame_skip_confirm.paste(skip_confirm, (780, 545))
    # Frame 5: loading screen with tips.png -> taps LOADING_TIPS_POINT (917, 257)
    frame_tips = base.copy()
    frame_tips.paste(tips_icon, (100, 600))
    # Frame 6: battle ready (attack.png)
    frame_battle = base.copy()
    frame_battle.paste(attack, (1100, 600))

    frames = [
        png_bytes(frame)
        for frame in (
            frame_flip,
            frame_mid_anim,
            frame_team_ok,
            frame_need_skip,
            frame_skip_confirm,
            frame_tips,
            frame_battle,
        )
    ]
    (data / "servant_info_CH.json").write_text(
        json.dumps({"First": {}, "Second": {}}),
        encoding="utf-8",
    )
    (settings / "flip_and_skip.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "First",
                "servant_1_name": "Second",
                "usedServant": [0, 1],
            }
        ),
        encoding="utf-8",
    )

    class SequenceDevice:
        def __init__(self) -> None:
            self.index = 0
            self.taps: list[tuple[int, int]] = []

        def snapshot(self) -> bytes:
            frame = frames[min(self.index, len(frames) - 1)]
            self.index += 1
            return frame

        def tap(self, x: int, y: int):
            self.taps.append((x, y))

            class Operation:
                def to_dict(self):
                    return {"x": x, "y": y}

            return Operation()

    class ContextStub:
        def checkpoint(self, *_args, **_kwargs):
            pass

        def emit(self, *_args, **_kwargs):
            pass

        def sleep(self, _seconds):
            pass

    resources = ResourceService(assets, data)
    recognition = RecognitionService(resources)
    team_recognizer = TeamRecognizer(resources, recognition)
    device = SequenceDevice()
    handler = create_battle_entry_handler(
        ScriptDataService(data),
        device,
        recognition,
        team_recognizer,
    )
    result = handler(
        ContextStub(),
        {
            "setting_name": "flip_and_skip",
            "timeout_seconds": 5,
            "poll_interval": 0,
            "action_wait_seconds": 0,
            "team_check_mode": "strict",
        },
    )

    assert result["ready"] is True
    assert result["team_verification"]["ok"] is True
    assert result["team_verification"]["retried"] is True
    assert result["actions"] == [
        "team_card_flip_wait",
        "team_decide",
        "story_skip",
        "story_skip_confirm",
        "loading_tips",
    ]
    assert device.taps == [
        (640, 520),
        (1197, 40),
        (815, 563),
        (917, 257),
    ]
