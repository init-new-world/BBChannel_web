import pytest

from webapp.automation.expball_run import (
    EXPBALL_RUN_JOB_KIND,
    create_expball_run_handler,
    register_expball_run_job,
)
from webapp.core.models import OperationResult
from webapp.runtime import JobDatabase, JobManager


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
        "status": "actionable",
        "reason": None,
        "matches": [],
    }


def _report(state, flow, status, *, action=None, reason=None, matches=None):
    if matches is None:
        matches = []
        if state != "unknown":
            matches.append(
                {
                    "name": state,
                    "center": [800, 600],
                    "size": [120, 60],
                }
            )
    return {
        "server": "CH",
        "state": state,
        "flow": flow,
        "status": status,
        "reason": reason,
        "recommended_action": action,
        "matches": matches,
    }


def _storage_report(*names):
    centers = {
        "in_store": [310, 120],
        "storeAll": [720, 310],
        "zxStore": [980, 620],
        "decide": [900, 650],
    }
    return _report(
        names[0],
        "confirmation" if "decide" in names else "storage",
        "observed",
        matches=[
            {"name": name, "center": centers[name], "size": [120, 60]}
            for name in names
        ],
    )


def test_expball_run_stores_full_inventory_and_resumes_summoning():
    navigation_reports = iter(
        (
            _navigation_report("summon_page"),
            _navigation_report("storage_page"),
            _navigation_report("summon_page"),
        )
    )
    flow_reports = iter(
        (
            _report(
                "boxfull",
                "summon",
                "actionable",
                action="handle_full_box",
            ),
            _storage_report("in_store", "storeAll", "zxStore"),
            _storage_report("in_store", "storeAll", "zxStore"),
            _storage_report("decide"),
            _storage_report("in_store"),
            _report(
                "call10",
                "summon",
                "actionable",
                action="summon_ten",
            ),
        )
    )

    class Recognizer:
        def recognize_navigation(self, *_args, **_kwargs):
            return next(navigation_reports)

        def recognize(self, *_args, **_kwargs):
            return next(flow_reports)

    device = _Device()
    result = create_expball_run_handler(
        _ScriptData(), device, Recognizer()
    )(
        _Context(),
        {
            "setting_name": "demo",
            "max_summons": 1,
            "overflow_action": "storage",
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["reason"] == "summon_limit"
    assert result["summons"] == 1
    assert result["overflow_cycles"] == 1
    assert [stage["stage"] for stage in result["stages"]] == [
        "navigate_summon",
        "summon",
        "navigate_storage",
        "storage",
        "navigate_summon",
        "summon",
    ]
    assert device.taps == [
        (720, 310),
        (980, 620),
        (900, 650),
        (800, 600),
    ]


def test_expball_run_defaults_to_stopping_safely_when_inventory_is_full():
    class Recognizer:
        def recognize_navigation(self, *_args, **_kwargs):
            return _navigation_report("summon_page")

        def recognize(self, *_args, **_kwargs):
            return _report(
                "boxfull",
                "summon",
                "actionable",
                action="handle_full_box",
            )

    result = create_expball_run_handler(
        _ScriptData(), _Device(), Recognizer()
    )(_Context(), {"setting_name": "demo"})

    assert result["completed"] is False
    assert result["stopped"] is True
    assert result["reason"] == "box_full"
    assert result["overflow_action"] == "stop"
    assert [stage["stage"] for stage in result["stages"]] == [
        "navigate_summon",
        "summon",
    ]


def test_expball_run_rejects_unknown_overflow_action():
    handler = create_expball_run_handler(_ScriptData(), _Device(), object())

    with pytest.raises(ValueError, match="overflow_action"):
        handler(
            _Context(),
            {"setting_name": "demo", "overflow_action": "destroy_everything"},
        )


def test_expball_run_does_not_offer_unconfigured_automatic_sale():
    handler = create_expball_run_handler(_ScriptData(), _Device(), object())

    with pytest.raises(ValueError, match="overflow_action"):
        handler(
            _Context(),
            {"setting_name": "demo", "overflow_action": "sell"},
        )


def test_expball_run_job_requires_connected_device(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_expball_run_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )

        assert manager.has_kind(EXPBALL_RUN_JOB_KIND)
        assert manager.requires_device(EXPBALL_RUN_JOB_KIND) is True
