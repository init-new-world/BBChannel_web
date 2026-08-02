import pytest

from webapp.automation.expball_navigation import (
    EXPBALL_NAVIGATE_JOB_KIND,
    create_expball_navigate_handler,
    register_expball_navigate_job,
)
from webapp.core.models import MatchResult, OperationResult
from webapp.runtime import JobDatabase, JobManager
from webapp.services.expball import ExpBallRecognizer


class _ScriptData:
    def get_setting_plan(self, name):
        assert name == "demo"
        return {
            "server": "CH",
            "run": {"random_touch": False, "random_time": 0},
        }


class _Device:
    def __init__(self):
        self.taps = []

    def snapshot(self):
        return b"screen"

    def tap(self, x, y):
        self.taps.append((x, y))
        return OperationResult(ok=True, action="tap", data={"x": x, "y": y})


class _Context:
    def __init__(self):
        self.events = []
        self.sleeps = []

    def checkpoint(self, step, **options):
        self.events.append(("checkpoint", step, options))

    def emit(self, event_type, message, **options):
        self.events.append((event_type, message, options))

    def sleep(self, seconds):
        self.sleeps.append(seconds)


def _navigation_report(state):
    return {
        "server": "CH",
        "state": state,
        "status": "actionable" if state != "unknown" else "unknown",
        "reason": None,
        "matches": [],
    }


def test_expball_navigation_recognizer_prioritizes_destination_pages():
    names = [
        "friendpointcall",
        "ljbh",
        "in_store",
        "ljbhfm",
        "ljbg",
        "menu",
        "shop",
    ]

    class Resources:
        def template_index(self, *, prefix, limit):
            assert prefix == "expball/CH"
            assert limit == 200
            return {
                "entries": [{"path": f"expball/CH/{name}.png"} for name in names]
            }

    class Recognition:
        def __init__(self):
            self.candidates = None

        def match_templates(self, _screenshot, candidates):
            self.candidates = candidates
            return [
                MatchResult(
                    template_path=candidate["template_path"],
                    matched=True,
                    confidence=0.95,
                    threshold=0.84,
                    top_left=[10, 20],
                    size=[30, 40],
                    center=[25, 40],
                    scale=1,
                )
                for candidate in candidates
            ]

    recognition = Recognition()
    report = ExpBallRecognizer(Resources(), recognition).recognize_navigation(
        b"screen",
        "ch",
    )

    assert [candidate["template_path"] for candidate in recognition.candidates] == [
        "expball/CH/friendpointcall.png",
        "expball/CH/ljbh.png",
        "expball/CH/in_store.png",
        "expball/CH/ljbhfm.png",
        "expball/CH/ljbg.png",
        "expball/CH/shop.png",
        "expball/CH/menu.png",
    ]
    assert all("roi" in candidate for candidate in recognition.candidates)
    assert report["state"] == "summon_page"
    assert [match["name"] for match in report["matches"]] == [
        "summon_page",
        "sell_page",
        "storage_page",
        "sell_menu",
        "storage_menu",
        "menu_expanded",
        "menu_available",
    ]


def test_expball_navigate_enters_storage_from_regular_menu():
    reports = iter(
        (
            _navigation_report("menu_available"),
            _navigation_report("menu_expanded"),
            _navigation_report("storage_menu"),
            _navigation_report("storage_page"),
        )
    )

    class Recognizer:
        def recognize_navigation(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.84
            return next(reports)

    device = _Device()
    result = create_expball_navigate_handler(
        _ScriptData(), device, Recognizer()
    )(
        _Context(),
        {
            "setting_name": "demo",
            "destination": "storage",
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["reason"] == "destination_reached"
    assert result["destination"] == "storage"
    assert result["actions"] == [
        "open_menu",
        "open_formation",
        "open_storage",
    ]
    assert device.taps == [(1183, 650), (303, 597), (1127, 587)]


def test_expball_navigate_switches_banner_until_summon_page_is_found():
    reports = iter(
        (
            _navigation_report("menu_available"),
            _navigation_report("menu_expanded"),
            _navigation_report("summon_picker"),
            _navigation_report("summon_picker"),
            _navigation_report("summon_page"),
        )
    )

    class Recognizer:
        def recognize_navigation(self, *_args, **_kwargs):
            return next(reports)

    device = _Device()
    result = create_expball_navigate_handler(
        _ScriptData(), device, Recognizer()
    )(
        _Context(),
        {
            "setting_name": "demo",
            "destination": "summon",
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["actions"] == [
        "open_menu",
        "open_summon",
        "previous_summon_banner",
        "previous_summon_banner",
    ]
    assert device.taps == [(1183, 650), (640, 615), (30, 360), (30, 360)]


def test_expball_navigate_stops_when_device_action_fails():
    class Recognizer:
        def recognize_navigation(self, *_args, **_kwargs):
            return _navigation_report("menu_available")

    class Device(_Device):
        def tap(self, x, y):
            self.taps.append((x, y))
            return OperationResult(ok=False, action="tap", message="disconnected")

    result = create_expball_navigate_handler(
        _ScriptData(), Device(), Recognizer()
    )(_Context(), {"setting_name": "demo", "destination": "sell"})

    assert result["completed"] is False
    assert result["reason"] == "device_action_failed"
    assert result["actions"] == []


def test_expball_navigate_rejects_unknown_destination():
    handler = create_expball_navigate_handler(_ScriptData(), _Device(), object())

    with pytest.raises(ValueError, match="destination"):
        handler(
            _Context(),
            {"setting_name": "demo", "destination": "lottery"},
        )


def test_expball_navigate_job_requires_connected_device(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_expball_navigate_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )

        assert manager.has_kind(EXPBALL_NAVIGATE_JOB_KIND)
        assert manager.requires_device(EXPBALL_NAVIGATE_JOB_KIND) is True
