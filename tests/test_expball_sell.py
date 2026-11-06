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


def test_expball_sell_selects_cards_by_rarity_before_submitting():
    reports = iter(
        (
            _report(
                "autoSell",
                "sell",
                "actionable",
                "autoSell",
                action="open_auto_sell",
            ),
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

        def recognize_storage_grid(self, _screenshot, *, threshold):
            assert threshold == 0.8
            return {
                "rows": 3,
                "columns": 7,
                "recognized_count": 2,
                "slots": [
                    {"slot": 0, "star": 3, "center": [136, 248]},
                    {"slot": 1, "star": 5, "center": [269, 248]},
                ],
            }

    device = _Device()
    result = create_expball_sell_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "stars": [3],
            "grid_threshold": 0.8,
            "action_wait_seconds": 0,
        },
    )

    assert result["completed"] is True
    assert result["reason"] == "sold"
    assert result["selected_slots"] == [0]
    assert result["selected_count"] == 1
    assert result["actions"] == [
        "select_sell_card",
        "submit_sell_selection",
        "execute_sell",
        "close_sell_result",
    ]
    assert device.taps == [(136, 248), (1120, 650), (980, 620), (640, 610)]


def test_expball_sell_job_requires_connected_device(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_expball_sell_job(manager, _ScriptData(), _Device(), object())

        assert manager.has_kind(EXPBALL_SELL_JOB_KIND)
        assert manager.requires_device(EXPBALL_SELL_JOB_KIND) is True


def test_expball_sell_servant_locks_non_fp_gold_and_sells_eligible_servants():
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
            _report(
                "autoSell",
                "sell",
                "actionable",
                "autoSell",
                "jd",
                action="open_auto_sell",
            ),
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

        def recognize_servant_sale_grid(self, _screenshot, *, fp_gold_threshold):
            assert fp_gold_threshold == 0.85
            return {
                "rows": 3,
                "columns": 7,
                "need_lock_slots": [0],
                "need_lock_count": 1,
                "fp_gold_slots": [1],
                "fp_gold_count": 1,
                "slots": [
                    {
                        "slot": 0,
                        "frame_type": "gold_unlocked",
                        "fp_gold": None,
                        "need_lock": True,
                        "center": [136, 248],
                    },
                    {
                        "slot": 1,
                        "frame_type": "gold_unlocked",
                        "fp_gold": "lily",
                        "need_lock": False,
                        "center": [269, 248],
                    },
                    {
                        "slot": 2,
                        "frame_type": "silver",
                        "fp_gold": None,
                        "need_lock": False,
                        "center": [403, 248],
                    },
                ],
            }

    device = _Device()
    result = create_expball_sell_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "sell_target": "servant",
            "lock_gold_servants": True,
            "include_fp_gold": True,
            "select_servant_cards": True,
            "action_wait_seconds": 0,
        },
    )

    assert result["completed"] is True
    assert result["sell_target"] == "servant"
    assert result["locked_slots"] == [0]
    assert result["locked_count"] == 1
    assert result["selected_slots"] == [1, 2]
    assert result["selected_count"] == 2
    assert result["actions"] == [
        "enable_unified_lock",
        "lock_gold_servant",
        "disable_unified_lock",
        "select_sell_servant_card",
        "select_sell_servant_card",
        "submit_sell_selection",
        "execute_sell",
        "close_sell_result",
    ]
    assert device.taps == [
        (32, 368),
        (136, 248),
        (32, 368),
        (269, 248),
        (403, 248),
        (1120, 650),
        (980, 620),
        (640, 610),
    ]


def test_expball_sell_command_code_locks_inscribed_and_sells():
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
            _report(
                "autoSell",
                "sell",
                "actionable",
                "autoSell",
                "jd",
                action="open_auto_sell",
            ),
            _report(
                "autoSell",
                "sell",
                "actionable",
                "autoSell",
                "jd",
                action="open_auto_sell",
            ),
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
    cc_grids = iter(
        (
            {
                "server": "CH",
                "rows": 3,
                "columns": 7,
                "empty": False,
                "first_slot_locked": False,
                "inscribed_slots": [0],
                "inscribed_count": 1,
                "slots": [
                    {
                        "slot": 0,
                        "inscribed": True,
                        "center": [136, 248],
                    },
                    {
                        "slot": 1,
                        "inscribed": False,
                        "center": [269, 248],
                    },
                ],
            },
            {
                "server": "CH",
                "rows": 3,
                "columns": 7,
                "empty": False,
                "first_slot_locked": False,
                "inscribed_slots": [],
                "inscribed_count": 0,
                "slots": [
                    {
                        "slot": 0,
                        "inscribed": False,
                        "center": [136, 248],
                    },
                ],
            },
        )
    )

    class Recognizer:
        def recognize(self, _screenshot, _server, *, threshold):
            assert threshold == 0.84
            return next(reports)

        def recognize_command_code_sale_grid(
            self,
            _screenshot,
            server,
            *,
            inscribed_threshold,
            empty_threshold,
            locker_threshold,
        ):
            assert server == "CH"
            assert inscribed_threshold == 0.7
            assert empty_threshold == 0.8
            assert locker_threshold == 0.7
            return next(cc_grids)

    device = _Device()
    result = create_expball_sell_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "sell_target": "command_code",
            "lock_inscribed_command_codes": True,
            "switch_command_code_tab": True,
            "auto_select": True,
            "action_wait_seconds": 0,
        },
    )

    assert result["completed"] is True
    assert result["sell_target"] == "command_code"
    assert result["locked_slots"] == [0]
    assert result["locked_count"] == 1
    assert result["actions"] == [
        "switch_command_code_tab",
        "enable_unified_lock",
        "lock_inscribed_command_code",
        "disable_unified_lock",
        "auto_select_sell_cards",
        "submit_sell_selection",
        "execute_sell",
        "close_sell_result",
    ]
    assert device.taps == [
        (475, 128),
        (32, 368),
        (136, 248),
        (32, 368),
        (320, 610),
        (1120, 650),
        (980, 620),
        (640, 610),
    ]


