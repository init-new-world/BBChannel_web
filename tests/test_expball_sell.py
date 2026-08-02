from webapp.automation.expball_sell import (
    EXPBALL_SELL_JOB_KIND,
    create_expball_sell_handler,
    register_expball_sell_job,
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
        return b"sell-screen"

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


def _report(state, flow, status, *matches, action=None, reason=None):
    centers = {
        "autoSell": (320, 610),
        "jd": (1120, 650),
        "destroy": (980, 620),
        "ljbhclose": (640, 610),
        "qpfull": (640, 320),
    }
    return {
        "server": "CH",
        "state": state,
        "flow": flow,
        "status": status,
        "reason": reason,
        "recommended_action": action,
        "matches": [
            {
                "name": name,
                "center": list(centers[name]),
                "size": [140, 70],
            }
            for name in matches
        ],
    }


def test_expball_sell_executes_current_selection_and_confirms():
    reports = iter(
        (
            _report(
                "autoSell",
                "sell",
                "actionable",
                "autoSell",
                "jd",
                action="open_auto_sell",
            ),
            _report("destroy", "sell", "actionable", "destroy"),
            _report(
                "ljbhclose",
                "confirmation",
                "actionable",
                "ljbhclose",
            ),
            _report(
                "autoSell",
                "sell",
                "actionable",
                "autoSell",
                action="open_auto_sell",
            ),
        )
    )

    class Recognizer:
        def recognize(self, _screenshot, _server, *, threshold):
            assert threshold == 0.84
            return next(reports)

    device = _Device()
    context = _Context()
    result = create_expball_sell_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        context,
        {"setting_name": "demo", "action_wait_seconds": 0},
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "sold"
    assert result["actions"] == [
        "submit_sell_selection",
        "execute_sell",
        "close_sell_result",
    ]
    assert device.taps == [(1120, 650), (980, 620), (640, 610)]
    assert context.events[-1][0:2] == ("checkpoint", "complete")


def test_expball_sell_stops_before_confirmation_when_qp_is_full():
    reports = iter(
        (
            _report(
                "autoSell",
                "sell",
                "actionable",
                "autoSell",
                "jd",
                action="open_auto_sell",
            ),
            _report("destroy", "sell", "actionable", "destroy"),
            _report("qpfull", "confirmation", "observed", "qpfull"),
        )
    )

    class Recognizer:
        def recognize(self, _screenshot, _server, *, threshold):
            assert threshold == 0.84
            return next(reports)

    device = _Device()
    result = create_expball_sell_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(_Context(), {"setting_name": "demo", "action_wait_seconds": 0})

    assert result["completed"] is False
    assert result["reason"] == "qp_full"
    assert result["actions"] == ["submit_sell_selection", "execute_sell"]
    assert device.taps == [(1120, 650), (980, 620)]


def test_expball_sell_refuses_to_start_outside_sell_flow():
    class Recognizer:
        def recognize(self, _screenshot, _server, *, threshold):
            assert threshold == 0.84
            return _report("callfree", "summon", "actionable")

    device = _Device()
    result = create_expball_sell_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(_Context(), {"setting_name": "demo"})

    assert result["reason"] == "outside_sell_flow"
    assert result["actions"] == []
    assert device.taps == []


def test_expball_sell_job_requires_connected_device(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_expball_sell_job(manager, _ScriptData(), _Device(), object())

        assert manager.has_kind(EXPBALL_SELL_JOB_KIND)
        assert manager.requires_device(EXPBALL_SELL_JOB_KIND) is True
