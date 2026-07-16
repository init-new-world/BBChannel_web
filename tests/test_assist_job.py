import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from webapp.automation.assist import (
    ASSIST_SELECT_JOB_KIND,
    _assist_class_point,
    create_assist_handler,
    register_assist_job,
)
from webapp.devices.coordinates import FrameNormalizer
from webapp.devices.replay import ReplayBackend
from webapp.runtime import JobDatabase, JobManager, JobStatus
from webapp.services.assist import AssistRecognizer
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService
from webapp.services.script_data import ScriptDataService


def test_assist_class_point_uses_standard_and_recommended_tab_layouts():
    assert _assist_class_point("Saber", recommended=False) == (161, 128)
    assert _assist_class_point("Caster", recommended=True) == (453, 128)
    assert _assist_class_point("MoonCancer", recommended=False) == (632, 128)


def test_assist_handler_stops_after_network_reconnect_limit():
    reconnect_checks = 0

    class Operation:
        def to_dict(self):
            return {"ok": True}

    class Device:
        def snapshot(self):
            return b"frame"

        def tap(self, _x, _y):
            return Operation()

    class Match:
        center = (640, 420)
        size = (120, 60)

        def __init__(self, matched):
            self.matched = matched

    class Recognizer:
        def match_reconnect(self, _screenshot, _server):
            nonlocal reconnect_checks
            reconnect_checks += 1
            return Match(reconnect_checks == 1)

        def recognize(self, _screenshot, _assist, *, server):
            return {
                "candidate_count": 1,
                "servant_name": "Support",
                "candidates": [
                    {"anchor": [70, 225], "scale": 1.0, "checks": {}}
                ],
            }

    class ScriptData:
        def get_setting_plan(self, _name):
            return {
                "server": "CH",
                "assist": {"all_not_skip": True},
                "run": {"random_time": 0, "random_touch": False},
            }

    class Context:
        def checkpoint(self, *_args, **_options):
            pass

        def emit(self, *_args, **_options):
            pass

        def sleep(self, _seconds):
            pass

    handler = create_assist_handler(ScriptData(), Device(), Recognizer())

    with pytest.raises(RuntimeError, match="reconnect limit"):
        handler(
            Context(),
            {"setting_name": "demo", "max_reconnects": 0},
        )


def test_assist_handler_rejects_invalid_configured_swipe_interval():
    class ScriptData:
        def get_setting_plan(self, _name):
            return {
                "server": "CH",
                "assist": {
                    "all_not_skip": True,
                    "interval_after_swipe": 11,
                },
                "run": {"random_time": 0, "random_touch": False},
            }

    handler = create_assist_handler(ScriptData(), None, None)

    with pytest.raises(ValueError, match="scroll_wait_seconds"):
        handler(None, {"setting_name": "demo"})


def test_assist_handler_uses_recognized_selection_point():
    taps = []

    class Operation:
        def to_dict(self):
            return {"ok": True}

    class Device:
        def snapshot(self):
            return b"frame"

        def tap(self, x, y):
            taps.append((x, y))
            return Operation()

    class Match:
        matched = False

    class Recognizer:
        def match_reconnect(self, _screenshot, _server):
            return Match()

        def match_not_available(self, _screenshot, _server):
            return Match()

        def recognize(self, _screenshot, _assist, *, server):
            return {
                "candidate_count": 1,
                "servant_name": "Support",
                "candidates": [
                    {
                        "anchor": [10, 20],
                        "scale": 1.0,
                        "selection_point": [900, 123],
                        "checks": {},
                    }
                ],
            }

    class ScriptData:
        def get_setting_plan(self, _name):
            return {
                "server": "CH",
                "assist": {"all_not_skip": True},
                "run": {"random_time": 0, "random_touch": False},
            }

    class Context:
        def checkpoint(self, *_args, **_options):
            pass

        def emit(self, *_args, **_options):
            pass

        def sleep(self, _seconds):
            pass

    result = create_assist_handler(ScriptData(), Device(), Recognizer())(
        Context(),
        {"setting_name": "demo", "tap_wait_seconds": 0},
    )

    assert taps == [(900, 123)]
    assert result["selected"]["tap_point"] == [900, 123]


def test_assist_handler_retries_when_selected_candidate_is_unavailable():
    state = {"screen": "candidate_1"}
    taps = []

    class Operation:
        def to_dict(self):
            return {"ok": True}

    class Device:
        def snapshot(self):
            return state["screen"].encode()

        def tap(self, x, y):
            taps.append((x, y))
            transitions = {
                "candidate_1": "unavailable",
                "unavailable": "candidate_2",
                "candidate_2": "team",
            }
            state["screen"] = transitions[state["screen"]]
            return Operation()

    class Match:
        center = (640, 420)
        size = (160, 60)

        def __init__(self, matched):
            self.matched = matched

    class Recognizer:
        def match_reconnect(self, _screenshot, _server):
            return Match(False)

        def match_not_available(self, screenshot, _server):
            return Match(screenshot == b"unavailable")

        def recognize(self, screenshot, _assist, *, server):
            anchors = {
                b"candidate_1": [70, 225],
                b"candidate_2": [100, 225],
            }
            anchor = anchors[screenshot]
            return {
                "candidate_count": 1,
                "servant_name": "Support",
                "candidates": [
                    {"anchor": anchor, "scale": 1.0, "checks": {}}
                ],
            }

    class ScriptData:
        def get_setting_plan(self, _name):
            return {
                "server": "CH",
                "assist": {"all_not_skip": True},
                "run": {"random_time": 0, "random_touch": False},
            }

    class Context:
        def checkpoint(self, *_args, **_options):
            pass

        def emit(self, *_args, **_options):
            pass

        def sleep(self, _seconds):
            pass

    result = create_assist_handler(ScriptData(), Device(), Recognizer())(
        Context(),
        {
            "setting_name": "demo",
            "tap_wait_seconds": 0,
            "max_unavailable": 2,
        },
    )

    assert taps == [(340, 165), (640, 420), (370, 165)]
    assert result["unavailable"] == 1
    assert result["selected"]["anchor"] == [100, 225]


@pytest.mark.parametrize(
    ("initial_screen", "expected_empty_lists", "expected_scroll_limit_hits"),
    [
        ("empty", 1, 0),
        ("scroll_bottom", 0, 1),
    ],
)
def test_assist_handler_refreshes_immediately_when_list_cannot_scroll_further(
    initial_screen: str,
    expected_empty_lists: int,
    expected_scroll_limit_hits: int,
):
    state = {"screen": initial_screen}
    taps = []

    class Operation:
        def to_dict(self):
            return {"ok": True}

    class Device:
        def snapshot(self):
            return state["screen"].encode()

        def tap(self, x, y):
            taps.append((x, y))
            transitions = {
                "empty": "refresh_confirmation",
                "scroll_bottom": "refresh_confirmation",
                "refresh_confirmation": "candidate",
                "candidate": "team",
            }
            state["screen"] = transitions[state["screen"]]
            return Operation()

    class Match:
        size = (120, 60)

        def __init__(self, matched, center=(640, 420), top_left=(580, 390)):
            self.matched = matched
            self.center = center
            self.top_left = top_left

    class Recognizer:
        def match_reconnect(self, _screenshot, _server):
            return Match(False)

        def match_no_assist(self, screenshot, _server):
            return Match(screenshot == b"empty")

        def match_scrollbar(self, screenshot, _server):
            return Match(
                screenshot == b"scroll_bottom",
                top_left=(1200, 700),
            )

        def match_refresh_button(self, screenshot, _server):
            return Match(
                screenshot in {b"empty", b"scroll_bottom"},
                (1130, 65),
            )

        def match_refresh_confirmation(self, screenshot, _server):
            return Match(screenshot == b"refresh_confirmation", (615, 410))

        def match_not_available(self, _screenshot, _server):
            return Match(False)

        def recognize(self, screenshot, _assist, *, server):
            candidates = (
                [{"anchor": [70, 225], "scale": 1.0, "checks": {}}]
                if screenshot == b"candidate"
                else []
            )
            return {
                "candidate_count": len(candidates),
                "servant_name": "Support",
                "candidates": candidates,
            }

    class ScriptData:
        def get_setting_plan(self, _name):
            return {
                "server": "CH",
                "assist": {"all_not_skip": True, "scroll_limit": 0.96},
                "run": {"random_time": 0, "random_touch": False},
            }

    class Context:
        def checkpoint(self, *_args, **_options):
            pass

        def emit(self, *_args, **_options):
            pass

        def sleep(self, _seconds):
            pass

    result = create_assist_handler(ScriptData(), Device(), Recognizer())(
        Context(),
        {
            "setting_name": "demo",
            "tap_wait_seconds": 0,
            "refresh_wait_seconds": 0,
        },
    )

    assert taps == [(1130, 65), (615, 410), (340, 165)]
    assert result["attempts"] == 2
    assert result["scrolls"] == 0
    assert result["refreshes"] == 1
    assert result["empty_lists"] == expected_empty_lists
    assert result["scroll_limit_hits"] == expected_scroll_limit_hits


def test_assist_handler_refreshes_when_grand_boundary_disappears():
    state = {"screen": "grand_boundary"}
    taps = []

    class Operation:
        def to_dict(self):
            return {"ok": True}

    class Device:
        def snapshot(self):
            return state["screen"].encode()

        def tap(self, x, y):
            taps.append((x, y))
            transitions = {
                "grand_boundary": "refresh_confirmation",
                "refresh_confirmation": "candidate",
                "candidate": "team",
            }
            state["screen"] = transitions[state["screen"]]
            return Operation()

        def swipe(self, *_args):
            raise AssertionError("grand assist boundary must refresh before swiping")

    class Match:
        size = (120, 60)
        top_left = (580, 390)

        def __init__(self, matched, center=(640, 420)):
            self.matched = matched
            self.center = center

    class Recognizer:
        def match_reconnect(self, _screenshot, _server):
            return Match(False)

        def match_no_assist(self, _screenshot, _server):
            return Match(False)

        def match_grand_marker(self, screenshot, _server):
            return Match(screenshot != b"grand_boundary")

        def match_refresh_button(self, screenshot, _server):
            return Match(screenshot == b"grand_boundary", (1130, 65))

        def match_refresh_confirmation(self, screenshot, _server):
            return Match(screenshot == b"refresh_confirmation", (615, 410))

        def match_not_available(self, _screenshot, _server):
            return Match(False)

        def recognize(self, screenshot, _assist, *, server):
            candidates = (
                [{"anchor": [70, 225], "scale": 1.0, "checks": {}}]
                if screenshot == b"candidate"
                else []
            )
            return {
                "candidate_count": len(candidates),
                "servant_name": "Support",
                "candidates": candidates,
            }

    class ScriptData:
        def get_setting_plan(self, _name):
            return {
                "server": "CH",
                "assist": {
                    "mode": "冠位助战",
                    "no_grand_refresh": True,
                    "all_not_skip": True,
                    "scroll_limit": 0.96,
                },
                "run": {"random_time": 0, "random_touch": False},
            }

    class Context:
        def checkpoint(self, *_args, **_options):
            pass

        def emit(self, *_args, **_options):
            pass

        def sleep(self, _seconds):
            pass

    result = create_assist_handler(ScriptData(), Device(), Recognizer())(
        Context(),
        {
            "setting_name": "demo",
            "tap_wait_seconds": 0,
            "refresh_wait_seconds": 0,
        },
    )

    assert taps == [(1130, 65), (615, 410), (340, 165)]
    assert result["scrolls"] == 0
    assert result["refreshes"] == 1
    assert result["grand_boundary_hits"] == 1


def test_assist_handler_selects_configured_class_before_recognition():
    taps = []

    class Operation:
        def to_dict(self):
            return {"ok": True}

    class Device:
        def snapshot(self):
            return b"frame"

        def tap(self, x, y):
            taps.append((x, y))
            return Operation()

    class Match:
        matched = False

    class Recognizer:
        def match_reconnect(self, _screenshot, _server):
            return Match()

        def match_not_available(self, _screenshot, _server):
            return Match()

        def match_recommended_header(self, _screenshot, _server):
            return Match()

        def recognize(self, _screenshot, _assist, *, server):
            return {
                "candidate_count": 1,
                "servant_name": "Support",
                "candidates": [
                    {"anchor": [70, 225], "scale": 1.0, "checks": {}}
                ],
            }

    class ScriptData:
        def get_setting_plan(self, _name):
            return {
                "server": "CH",
                "assist": {
                    "servant_class": "Caster",
                    "all_not_skip": False,
                },
                "run": {"random_time": 0, "random_touch": False},
            }

    class Context:
        def checkpoint(self, *_args, **_kwargs):
            pass

        def emit(self, *_args, **_kwargs):
            pass

        def sleep(self, _seconds):
            pass

    result = create_assist_handler(ScriptData(), Device(), Recognizer())(
        Context(),
        {"setting_name": "demo"},
    )

    assert taps == [(430, 128), (430, 128), (340, 165)]
    assert result["class_selection"] == {
        "class": "Caster",
        "recommended": False,
        "point": [430, 128],
        "operation": {"ok": True},
    }


def test_assist_select_job_taps_first_matching_candidate(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    session = tmp_path / "replays" / "assist"
    servant_faces = assets / "servantface"
    battle_assets = assets / "battle" / "CH"
    settings = data / "settings"
    servant_faces.mkdir(parents=True)
    battle_assets.mkdir(parents=True)
    settings.mkdir(parents=True)
    session.mkdir(parents=True)

    portrait = Image.new("RGB", (60, 60), (40, 70, 100))
    portrait_draw = ImageDraw.Draw(portrait)
    portrait_draw.rectangle((7, 7, 52, 52), fill=(205, 90, 175))
    portrait_draw.line((5, 53, 54, 6), fill=(45, 225, 190), width=4)
    portrait.save(servant_faces / "Support_1.png")
    reconnect = Image.new("RGB", (114, 53), (25, 35, 45))
    reconnect_draw = ImageDraw.Draw(reconnect)
    reconnect_draw.ellipse((8, 5, 48, 45), outline=(235, 195, 55), width=4)
    reconnect_draw.ellipse((65, 5, 105, 45), outline=(55, 205, 235), width=4)
    reconnect_draw.line((30, 26, 84, 26), fill=(230, 75, 125), width=5)
    reconnect.save(battle_assets / "reconnect.png")
    reconnect_frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    reconnect_frame.paste(reconnect, (580, 380))
    candidate_frame = Image.new("RGB", (1280, 720), (18, 24, 32))
    candidate_frame.paste(portrait, (70, 225))
    reconnect_frame.save(session / "0.png")
    candidate_frame.save(session / "1.png")
    (session / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "device_id": "assist",
                "frames": [
                    {
                        "file": "0.png",
                        "expect": {"type": "tap", "x": 637, "y": 406},
                    },
                    {
                        "file": "1.png",
                        "expect": {"type": "tap", "x": 370, "y": 195},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Support": {"other_name": [], "SN": "314"}}),
        encoding="utf-8",
    )
    (settings / "assist.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Support",
                "assistIdx": 0,
                "assistMode": "从者礼装",
                "assistEquip": None,
                "fullEquip": 0,
                "onlyFriendAssist": 0,
                "NPlevel": 1,
                "skillsLevel": [0, 0, 0],
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
    devices.connect("replay", "assist")
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_assist_job(
            manager,
            ScriptDataService(data),
            devices,
            AssistRecognizer(resources, recognition),
        )
        job = manager.start(
            ASSIST_SELECT_JOB_KIND,
            {"setting_name": "assist", "tap_wait_seconds": 0},
            device_key="replay:assist",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["setting_name"] == "assist"
    assert result.result["attempts"] == 1
    assert result.result["reconnects"] == 1
    assert result.result["scrolls"] == 0
    assert result.result["selected"]["anchor"] == [100, 255]
    assert result.result["selected"]["tap_point"] == [370, 195]
    assert result.result["tap"]["ok"] is True


def test_assist_select_job_scrolls_before_retrying_recognition(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    session = tmp_path / "replays" / "assist-scroll"
    servant_faces = assets / "servantface"
    settings = data / "settings"
    servant_faces.mkdir(parents=True)
    settings.mkdir(parents=True)
    session.mkdir(parents=True)

    portrait = Image.new("RGB", (60, 60), (40, 70, 100))
    portrait_draw = ImageDraw.Draw(portrait)
    portrait_draw.rectangle((7, 7, 52, 52), fill=(205, 90, 175))
    portrait_draw.line((5, 53, 54, 6), fill=(45, 225, 190), width=4)
    portrait.save(servant_faces / "Support_1.png")
    blank = Image.new("RGB", (1280, 720), (18, 24, 32))
    matched = blank.copy()
    matched.paste(portrait, (70, 225))
    blank.save(session / "0.png")
    matched.save(session / "1.png")
    (session / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "device_id": "assist-scroll",
                "frames": [
                    {
                        "file": "0.png",
                        "expect": {
                            "type": "swipe",
                            "x1": 1120,
                            "y1": 620,
                            "x2": 1120,
                            "y2": 250,
                            "duration_ms": 500,
                        },
                    },
                    {
                        "file": "1.png",
                        "expect": {"type": "tap", "x": 370, "y": 195},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Support": {"other_name": [], "SN": "314"}}),
        encoding="utf-8",
    )
    (settings / "assist.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Support",
                "assistIdx": 0,
                "assistMode": "从者礼装",
                "NPlevel": 1,
                "skillsLevel": [0, 0, 0],
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
    devices.connect("replay", "assist-scroll")
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_assist_job(
            manager,
            ScriptDataService(data),
            devices,
            AssistRecognizer(resources, recognition),
        )
        job = manager.start(
            ASSIST_SELECT_JOB_KIND,
            {
                "setting_name": "assist",
                "max_scrolls": 1,
                "scroll_wait_seconds": 0,
                "tap_wait_seconds": 0,
            },
            device_key="replay:assist-scroll",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["attempts"] == 2
    assert result.result["scrolls"] == 1
    assert result.result["selected"]["anchor"] == [100, 255]


def test_assist_select_job_refreshes_list_after_scroll_limit(tmp_path: Path):
    pytest.importorskip("cv2")
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    session = tmp_path / "replays" / "assist-refresh"
    servant_faces = assets / "servantface"
    battle_assets = assets / "battle" / "CH"
    settings = data / "settings"
    servant_faces.mkdir(parents=True)
    battle_assets.mkdir(parents=True)
    settings.mkdir(parents=True)
    session.mkdir(parents=True)

    def pattern(size: tuple[int, int], color: tuple[int, int, int]) -> Image.Image:
        image = Image.new("RGB", size, color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((2, 2, size[0] - 3, size[1] - 3), outline=(245, 220, 70), width=2)
        draw.line((3, size[1] - 4, size[0] - 4, 3), fill=(40, 220, 235), width=2)
        return image

    portrait = pattern((60, 60), (145, 65, 115))
    refresh_button = pattern((60, 30), (35, 110, 175))
    refresh_confirm = pattern((30, 20), (70, 145, 85))
    portrait.save(servant_faces / "Support_1.png")
    refresh_button.save(battle_assets / "listupdatebtn.png")
    refresh_confirm.save(battle_assets / "listupdate.png")
    blank = Image.new("RGB", (1280, 720), (18, 24, 32))
    refresh_screen = blank.copy()
    refresh_screen.paste(refresh_button, (1100, 50))
    confirm_screen = blank.copy()
    confirm_screen.paste(refresh_confirm, (600, 400))
    matched_screen = blank.copy()
    matched_screen.paste(portrait, (70, 225))
    for index, frame in enumerate((blank, refresh_screen, confirm_screen, matched_screen)):
        frame.save(session / f"{index}.png")
    (session / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "device_id": "assist-refresh",
                "frames": [
                    {
                        "file": "0.png",
                        "expect": {
                            "type": "swipe",
                            "x1": 1120,
                            "y1": 620,
                            "x2": 1120,
                            "y2": 250,
                            "duration_ms": 500,
                        },
                    },
                    {
                        "file": "1.png",
                        "expect": {"type": "tap", "x": 1130, "y": 65},
                    },
                    {
                        "file": "2.png",
                        "expect": {"type": "tap", "x": 615, "y": 410},
                    },
                    {
                        "file": "3.png",
                        "expect": {"type": "tap", "x": 370, "y": 195},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Support": {"other_name": [], "SN": "314"}}),
        encoding="utf-8",
    )
    (settings / "assist.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Support",
                "assistIdx": 0,
                "assistMode": "从者礼装",
                "NPlevel": 1,
                "skillsLevel": [0, 0, 0],
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
    devices.connect("replay", "assist-refresh")
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_assist_job(
            manager,
            ScriptDataService(data),
            devices,
            AssistRecognizer(resources, recognition),
        )
        job = manager.start(
            ASSIST_SELECT_JOB_KIND,
            {
                "setting_name": "assist",
                "max_scrolls": 1,
                "max_refreshes": 1,
                "scroll_wait_seconds": 0,
                "refresh_wait_seconds": 0,
                "tap_wait_seconds": 0,
            },
            device_key="replay:assist-refresh",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["attempts"] == 3
    assert result.result["scrolls"] == 1
    assert result.result["refreshes"] == 1
