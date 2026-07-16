from pathlib import Path

from webapp.automation.quest import (
    FREE_QUEST_ENTER_JOB_KIND,
    create_free_quest_entry_handler,
    register_free_quest_entry_job,
)
from webapp.core.models import OperationResult
from webapp.runtime import JobDatabase, JobManager


class _ScriptData:
    def get_setting_plan(self, _name):
        return {"server": "CH"}


class _Device:
    def __init__(self) -> None:
        self.taps = []
        self.snapshots = 0

    def snapshot(self):
        self.snapshots += 1
        return f"screen-{self.snapshots}".encode()

    def tap(self, x, y):
        self.taps.append((x, y))
        return OperationResult(ok=True, action="tap", data={"x": x, "y": y})


class _Context:
    def __init__(self) -> None:
        self.events = []
        self.sleeps = []

    def checkpoint(self, step, **options):
        self.events.append(("checkpoint", step, options))

    def emit(self, event_type, message, **options):
        self.events.append((event_type, message, options))

    def sleep(self, seconds):
        self.sleeps.append(seconds)


def test_free_quest_entry_clicks_map_dot_then_quest_until_assist_is_reached():
    stages = iter(("unknown", "unknown", "assist"))

    def detect(_context, _payload):
        return {"stage": next(stages)}

    class Recognizer:
        def recognize_free_quests(self, screenshot, _server):
            if screenshot == b"screen-1":
                return {"candidate_count": 0, "candidates": [], "selected": None}
            return {
                "candidate_count": 1,
                "candidates": [{"center": [700, 360], "cleared": False}],
                "selected": {"center": [700, 360], "cleared": False},
            }

        def recognize_free_map(self, screenshot):
            assert screenshot == b"screen-1"
            candidate = {"center": [400, 300], "touch": [373, 327]}
            return {
                "candidate_count": 1,
                "candidates": [candidate],
                "selected": candidate,
            }

    device = _Device()
    context = _Context()
    result = create_free_quest_entry_handler(
        _ScriptData(),
        device,
        Recognizer(),
        detect,
    )(
        context,
        {
            "setting_name": "demo",
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result == {
        "setting_name": "demo",
        "entered": True,
        "stage": "assist",
        "reason": None,
        "attempts": 3,
        "actions": ["map_red_dot", "free_quest"],
    }
    assert device.taps == [(373, 327), (700, 360)]
    assert device.snapshots == 2
    assert [event[0] for event in context.events].count("device_action") == 2


def test_free_quest_entry_stops_when_visible_quests_are_all_clear():
    class Recognizer:
        def recognize_free_quests(self, _screenshot, _server):
            return {
                "candidate_count": 2,
                "candidates": [
                    {"center": [700, 180], "cleared": True},
                    {"center": [700, 360], "cleared": True},
                ],
                "selected": None,
            }

        def recognize_free_map(self, _screenshot):
            raise AssertionError("map should not be scanned when quest rows are visible")

    device = _Device()
    result = create_free_quest_entry_handler(
        _ScriptData(),
        device,
        Recognizer(),
        lambda _context, _payload: {"stage": "unknown"},
    )(_Context(), {"setting_name": "demo"})

    assert result["entered"] is False
    assert result["reason"] == "visible_quests_cleared"
    assert result["stage"] == "unknown"
    assert result["actions"] == []
    assert device.taps == []


def test_free_quest_entry_reports_when_no_visible_map_target_exists():
    class Recognizer:
        def recognize_free_quests(self, _screenshot, _server):
            return {"candidate_count": 0, "candidates": [], "selected": None}

        def recognize_free_map(self, _screenshot):
            return {"candidate_count": 0, "candidates": [], "selected": None}

    result = create_free_quest_entry_handler(
        _ScriptData(),
        _Device(),
        Recognizer(),
        lambda _context, _payload: {"stage": "unknown"},
    )(_Context(), {"setting_name": "demo"})

    assert result["entered"] is False
    assert result["reason"] == "no_visible_free_quest"
    assert result["stage"] == "unknown"


def test_free_quest_entry_job_requires_connected_device(tmp_path: Path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_free_quest_entry_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
            lambda _context, _payload: {"stage": "unknown"},
        )

        assert manager.has_kind(FREE_QUEST_ENTER_JOB_KIND)
        assert manager.requires_device(FREE_QUEST_ENTER_JOB_KIND) is True
