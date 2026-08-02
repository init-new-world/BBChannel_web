from webapp.automation.expball_store_all import (
    EXPBALL_STORE_ALL_JOB_KIND,
    create_expball_store_all_handler,
    register_expball_store_all_job,
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


def _storage_report(*names):
    centers = {
        "in_store": [310, 120],
        "storeAll": [720, 310],
        "zxStore": [980, 620],
        "decide": [900, 650],
    }
    confirmation = "decide" in names
    return {
        "server": "CH",
        "state": names[0],
        "flow": "confirmation" if confirmation else "storage",
        "status": "observed",
        "reason": None,
        "recommended_action": None,
        "matches": [
            {"name": name, "center": centers[name], "size": [120, 60]}
            for name in names
        ],
    }


def test_expball_store_all_navigates_then_stores_inventory():
    navigation_reports = iter(
        (
            _navigation_report("menu_available"),
            _navigation_report("menu_expanded"),
            _navigation_report("storage_menu"),
            _navigation_report("storage_page"),
        )
    )
    storage_reports = iter(
        (
            _storage_report("in_store", "storeAll", "zxStore"),
            _storage_report("in_store", "storeAll", "zxStore"),
            _storage_report("decide"),
            _storage_report("in_store"),
        )
    )

    class Recognizer:
        def recognize_navigation(self, *_args, **_kwargs):
            return next(navigation_reports)

        def recognize(self, *_args, **_kwargs):
            return next(storage_reports)

    device = _Device()
    result = create_expball_store_all_handler(
        _ScriptData(), device, Recognizer()
    )(
        _Context(),
        {
            "setting_name": "demo",
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["reason"] == "stored"
    assert [stage["stage"] for stage in result["stages"]] == [
        "navigate_storage",
        "storage",
    ]
    assert device.taps == [
        (1183, 650),
        (303, 597),
        (1127, 587),
        (720, 310),
        (980, 620),
        (900, 650),
    ]


def test_expball_store_all_stops_before_storage_when_navigation_fails():
    reports = iter(
        (
            _navigation_report("unknown"),
            _navigation_report("unknown"),
        )
    )

    class Recognizer:
        def recognize_navigation(self, *_args, **_kwargs):
            return next(reports)

        def recognize(self, *_args, **_kwargs):
            raise AssertionError("storage must not start")

    result = create_expball_store_all_handler(
        _ScriptData(), _Device(), Recognizer()
    )(
        _Context(),
        {
            "setting_name": "demo",
            "max_idle_polls": 2,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is False
    assert result["reason"] == "no_actionable_navigation_state"
    assert [stage["stage"] for stage in result["stages"]] == [
        "navigate_storage"
    ]


def test_expball_store_all_job_requires_connected_device(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_expball_store_all_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )

        assert manager.has_kind(EXPBALL_STORE_ALL_JOB_KIND)
        assert manager.requires_device(EXPBALL_STORE_ALL_JOB_KIND) is True
