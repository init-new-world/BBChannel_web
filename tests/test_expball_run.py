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


def test_expball_run_does_not_offer_unconfigured_automatic_storage():
    handler = create_expball_run_handler(_ScriptData(), _Device(), object())

    with pytest.raises(ValueError, match="overflow_action"):
        handler(
            _Context(),
            {"setting_name": "demo", "overflow_action": "storage"},
        )


def test_expball_run_handles_full_box_via_configured_storage_and_resumes():
    nav_states = iter(
        (
            _navigation_report("summon_page"),
            _navigation_report("storage_page"),
            _navigation_report("summon_page"),
        )
    )
    reports = iter(
        (
            _report(
                "boxfull",
                "summon",
                "actionable",
                action="handle_full_box",
            ),
            _report(
                "in_store",
                "storage",
                "observed",
                matches=[{"name": "in_store", "center": [310, 120], "size": [120, 60]}],
            ),
            _report(
                "in_store",
                "storage",
                "observed",
                matches=[
                    {"name": "in_store", "center": [310, 120], "size": [120, 60]},
                    {"name": "jd", "center": [1120, 650], "size": [120, 60]},
                ],
            ),
            _report(
                "zxStore",
                "storage",
                "actionable",
                matches=[{"name": "zxStore", "center": [980, 620], "size": [120, 60]}],
            ),
            _report(
                "ljbhclose",
                "confirmation",
                "actionable",
                matches=[{"name": "ljbhclose", "center": [640, 610], "size": [120, 60]}],
            ),
            _report(
                "in_store",
                "storage",
                "observed",
                matches=[{"name": "in_store", "center": [310, 120], "size": [120, 60]}],
            ),
            _report(
                "call10",
                "summon",
                "actionable",
                action="summon_ten",
                matches=[{"name": "call10", "center": [800, 610], "size": [120, 60]}],
            ),
            _report(
                "decide",
                "confirmation",
                "actionable",
                action="confirm_summon",
                matches=[{"name": "decide", "center": [830, 570], "size": [120, 60]}],
            ),
            _report(
                "bianhuan",
                "summon",
                "observed",
                matches=[{"name": "bianhuan", "center": [350, 480], "size": [120, 60]}],
            ),
        )
    )

    class Recognizer:
        def recognize_navigation(self, *_args, **_kwargs):
            return next(nav_states)

        def recognize(self, *_args, **_kwargs):
            return next(reports)

        def recognize_storage_grid(self, *_args, **_kwargs):
            return {
                "rows": 3,
                "columns": 7,
                "recognized_count": 1,
                "slots": [{"slot": 0, "star": 5, "center": [136, 248]}],
            }

    device = _Device()
    result = create_expball_run_handler(
        _ScriptData(), device, Recognizer()
    )(
        _Context(),
        {
            "setting_name": "demo",
            "max_summons": 1,
            "overflow_action": "storage",
            "stars": [4, 5],
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "summon_limit"
    assert result["summons"] == 1
    assert result["overflow_action"] == "storage"
    assert result["overflow_cycles"] == 1
    assert [stage["stage"] for stage in result["stages"]] == [
        "navigate_summon",
        "summon",
        "navigate_storage",
        "storage",
        "navigate_summon",
        "summon",
    ]


def test_expball_run_handles_full_box_via_servant_enhancement_and_completes_at_target_level():
    nav_states = iter(
        (
            _navigation_report("summon_page"),
            _navigation_report("enhancement_page"),
        )
    )
    reports = iter(
        (
            _report(
                "boxfull",
                "summon",
                "actionable",
                action="handle_full_box",
            ),
            _report(
                "slot",
                "enhancement",
                "actionable",
                matches=[
                    {"name": "slot", "center": [823, 283], "size": [120, 60]},
                    {"name": "help", "center": [1180, 110], "size": [120, 60]},
                ],
            ),
        )
    )

    class Recognizer:
        def recognize_navigation(self, *_args, **_kwargs):
            return next(nav_states)

        def recognize(self, *_args, **_kwargs):
            return next(reports)

        def recognize_servant_level(self, *_args, **_kwargs):
            return {
                "current_level": 100,
                "max_level": 100,
                "is_max_level": True,
            }

    device = _Device()
    result = create_expball_run_handler(
        _ScriptData(), device, Recognizer()
    )(
        _Context(),
        {
            "setting_name": "demo",
            "max_summons": 5,
            "overflow_action": "servant_enhancement",
            "target_level": 100,
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "target_level_reached"
    assert [stage["stage"] for stage in result["stages"]] == [
        "navigate_summon",
        "summon",
        "navigate_servant_enhancement",
        "servant_enhancement",
    ]


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


def test_expball_run_forwards_summon_lock_targets_and_stops_when_target_reached():
    nav_states = iter((_navigation_report("summon_page"),))
    reports = iter(
        (
            _report(
                "call10",
                "summon",
                "actionable",
                action="summon_ten",
                matches=[{"name": "call10", "center": [800, 520]}],
            ),
            _report(
                "decide",
                "confirmation",
                "actionable",
                action="confirm_summon",
                matches=[{"name": "decide", "center": [835, 563]}],
            ),
            _report(
                "again10",
                "summon",
                "actionable",
                action="summon_again",
                matches=[
                    {"name": "again10", "center": [760, 673]},
                    {"name": "bianhuan", "center": [1040, 670]},
                ],
            ),
        )
    )

    class Recognizer:
        def recognize_navigation(self, *_args, **_kwargs):
            return next(nav_states)

        def recognize(self, *_args, **_kwargs):
            return next(reports)

        def recognize_summon_lock_targets(
            self,
            _screenshot,
            *,
            targets=None,
            threshold=0.8,
        ):
            assert targets == ["habe"]
            return {
                "threshold": threshold,
                "available_targets": [],
                "requested_targets": ["habe"],
                "target_count": 1,
                "match_count": 1,
                "matches": [
                    {
                        "target": "habe",
                        "template_path": "expball/FPgold/habe.png",
                        "center": [420, 260],
                        "size": [164, 176],
                    }
                ],
            }

    device = _Device()
    result = create_expball_run_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "max_summons": 5,
            "lock_targets": ["habe:1"],
            "lock_enough_stop": True,
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "lock_target_reached"
    assert result["summons"] == 1
    assert result["locked_count"] == 1
    assert result["locked_cards"] == [
        {
            "target": "habe",
            "center": [420, 260],
            "template_path": "expball/FPgold/habe.png",
        }
    ]


def test_expball_run_storage_then_sell_falls_back_when_storage_full():
    nav_states = iter(
        (
            _navigation_report("summon_page"),
            _navigation_report("storage_page"),
            _navigation_report("sell_page"),
            _navigation_report("summon_page"),
        )
    )
    reports = iter(
        (
            _report(
                "boxfull",
                "summon",
                "actionable",
                action="handle_full_box",
            ),
            _report(
                "storefull",
                "storage",
                "blocked",
                reason="storage_full",
                matches=[{"name": "storefull", "center": [640, 360]}],
            ),
            _report(
                "autoSell",
                "sell",
                "actionable",
                action="open_auto_sell",
                matches=[{"name": "autoSell", "center": [320, 610]}],
            ),
            _report(
                "autoSell",
                "sell",
                "actionable",
                action="open_auto_sell",
                matches=[
                    {"name": "autoSell", "center": [320, 610]},
                    {"name": "jd", "center": [1120, 650]},
                ],
            ),
            _report(
                "destroy",
                "sell",
                "actionable",
                matches=[{"name": "destroy", "center": [980, 620]}],
            ),
            _report(
                "ljbhclose",
                "confirmation",
                "actionable",
                matches=[{"name": "ljbhclose", "center": [640, 610]}],
            ),
            _report(
                "autoSell",
                "sell",
                "actionable",
                action="open_auto_sell",
                matches=[{"name": "autoSell", "center": [320, 610]}],
            ),
            _report(
                "call10",
                "summon",
                "actionable",
                action="summon_ten",
                matches=[{"name": "call10", "center": [800, 520]}],
            ),
            _report(
                "decide",
                "confirmation",
                "actionable",
                action="confirm_summon",
                matches=[{"name": "decide", "center": [835, 563]}],
            ),
            _report(
                "again10",
                "summon",
                "actionable",
                action="summon_again",
                matches=[
                    {"name": "again10", "center": [760, 673]},
                    {"name": "bianhuan", "center": [1040, 670]},
                ],
            ),
        )
    )

    class Recognizer:
        def recognize_navigation(self, *_args, **_kwargs):
            return next(nav_states)

        def recognize(self, *_args, **_kwargs):
            return next(reports)

        def recognize_storage_grid(self, *_args, **_kwargs):
            return {
                "rows": 3,
                "columns": 7,
                "recognized_count": 1,
                "slots": [{"slot": 0, "star": 4, "center": [136, 248]}],
            }

    device = _Device()
    result = create_expball_run_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "max_summons": 1,
            "store_first": True,
            "stars": [4],
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "summon_limit"
    assert result["overflow_action"] == "storage_then_sell"
    assert result["storage_full"] is True
    assert result["overflow_cycles"] == 1
    assert [stage["stage"] for stage in result["stages"]] == [
        "navigate_summon",
        "summon",
        "navigate_storage",
        "storage",
        "navigate_sell",
        "sell",
        "navigate_summon",
        "summon",
    ]


def test_expball_run_forwards_draw_100_and_banner_direction():
    nav_states = iter(
        (
            _navigation_report("menu_available"),
            _navigation_report("menu_expanded"),
            _navigation_report("summon_picker"),
            _navigation_report("summon_page"),
        )
    )
    reports = iter(
        (
            _report(
                "call10",
                "summon",
                "actionable",
                action="summon_ten",
                matches=[{"name": "call10", "center": [640, 533]}],
            ),
            _report(
                "decide",
                "confirmation",
                "actionable",
                action="confirm_summon",
                matches=[{"name": "decide", "center": [835, 563]}],
            ),
            _report(
                "again10",
                "summon",
                "actionable",
                action="summon_again",
                matches=[
                    {"name": "again10", "center": [760, 673]},
                    {"name": "bianhuan", "center": [1040, 670]},
                ],
            ),
        )
    )

    class Recognizer:
        def recognize_navigation(self, *_args, **_kwargs):
            return next(nav_states)

        def recognize(self, *_args, **_kwargs):
            return next(reports)

    device = _Device()
    result = create_expball_run_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "max_summons": 1,
            "draw_100": True,
            "banner_direction": "right",
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stages"][0]["result"]["banner_direction"] == "right"
    assert result["stages"][0]["result"]["actions"] == [
        "open_menu",
        "open_summon",
        "next_summon_banner",
    ]
    assert result["stages"][1]["result"]["draw_100"] is True
    assert result["stages"][1]["result"]["actions"] == [
        "summon_hundred",
        "confirm_summon",
    ]


def test_expball_run_auto_stores_full_ce_bombs_when_grid_is_full():
    nav_states = iter(
        (
            _navigation_report("summon_page"),
            _navigation_report("enhancement_page"),
            _navigation_report("storage_page"),
            _navigation_report("enhancement_page"),
            _navigation_report("summon_page"),
        )
    )
    reports = iter(
        (
            _report(
                "boxfull",
                "summon",
                "actionable",
                action="handle_full_box",
            ),
            _report(
                "slot",
                "enhancement",
                "actionable",
                action="open_material_slots",
                matches=[{"name": "slot", "center": [823, 283]}],
            ),
            _report(
                "tysd",
                "selection",
                "actionable",
                action="select_material_card",
                matches=[
                    {"name": "tysd", "center": [420, 80]},
                    {"name": "qhjd", "center": [1153, 670]},
                ],
            ),
            _report(
                "in_store",
                "storage",
                "observed",
                matches=[{"name": "in_store", "center": [310, 120]}],
            ),
            _report(
                "in_store",
                "storage",
                "observed",
                matches=[
                    {"name": "in_store", "center": [310, 120]},
                    {"name": "jd", "center": [1120, 650]},
                ],
            ),
            _report(
                "zxStore",
                "storage",
                "actionable",
                matches=[{"name": "zxStore", "center": [980, 620]}],
            ),
            _report(
                "ljbhclose",
                "confirmation",
                "actionable",
                matches=[{"name": "ljbhclose", "center": [640, 610]}],
            ),
            _report(
                "in_store",
                "storage",
                "observed",
                matches=[{"name": "in_store", "center": [310, 120]}],
            ),
            _report(
                "sure",
                "confirmation",
                "actionable",
                action="confirm_dialog",
                matches=[{"name": "sure", "center": [640, 563]}],
            ),
            _report(
                "call10",
                "summon",
                "actionable",
                action="summon_ten",
                matches=[{"name": "call10", "center": [800, 520]}],
            ),
            _report(
                "decide",
                "confirmation",
                "actionable",
                action="confirm_summon",
                matches=[{"name": "decide", "center": [835, 563]}],
            ),
            _report(
                "again10",
                "summon",
                "actionable",
                action="summon_again",
                matches=[
                    {"name": "again10", "center": [760, 673]},
                    {"name": "bianhuan", "center": [1040, 670]},
                ],
            ),
        )
    )

    class Recognizer:
        def recognize_navigation(self, *_args, **_kwargs):
            return next(nav_states)

        def recognize(self, *_args, **_kwargs):
            return next(reports)

        def recognize_ce_bomb_grid(self, *_args, **_kwargs):
            return {
                "server": "CH",
                "rows": 3,
                "columns": 7,
                "full_level_slots": list(range(21)),
                "full_level_count": 21,
                "all_full_level": True,
                "last_slot_full_level": True,
                "need_lock_slots": [],
                "need_lock_count": 0,
                "need_mark_slots": [],
                "need_mark_count": 0,
                "need_store_slots": [0],
                "need_store_count": 1,
                "slots": [
                    {
                        "slot": idx,
                        "center": [135, 248],
                        "full_level": True,
                        "locked": True,
                        "marked": True,
                        "need_lock": False,
                        "need_mark": False,
                        "need_store": idx == 0,
                    }
                    for idx in range(21)
                ],
            }

    device = _Device()
    result = create_expball_run_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "max_summons": 1,
            "overflow_action": "equipment_enhancement",
            "auto_store_ce_bombs": True,
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["auto_store_ce_bombs"] is True
    assert [stage["stage"] for stage in result["stages"]] == [
        "navigate_summon",
        "summon",
        "navigate_equipment_enhancement",
        "equipment_enhancement",
        "navigate_storage",
        "storage",
        "navigate_equipment_enhancement",
        "equipment_enhancement",
        "navigate_summon",
        "summon",
    ]


def test_expball_run_supports_multi_stage_overflow_actions_pipeline():
    nav_states = iter(
        (
            _navigation_report("summon_page"),
            _navigation_report("storage_page"),
            _navigation_report("sell_page"),
            _navigation_report("enhancement_page"),
            _navigation_report("summon_page"),
        )
    )
    reports = iter(
        (
            _report(
                "boxfull",
                "summon",
                "actionable",
                action="handle_full_box",
            ),
            _report(
                "store_full",
                "storage",
                "blocked",
                reason="storage_full",
                matches=[{"name": "store_full", "center": [640, 360]}],
            ),
            _report(
                "autoSell",
                "sell",
                "actionable",
                action="open_auto_sell",
                matches=[{"name": "autoSell", "center": [320, 610]}],
            ),
            _report(
                "autoSell",
                "sell",
                "actionable",
                action="open_auto_sell",
                matches=[
                    {"name": "autoSell", "center": [320, 610]},
                    {"name": "jd", "center": [1120, 650]},
                ],
            ),
            _report(
                "destroy",
                "sell",
                "actionable",
                matches=[{"name": "destroy", "center": [980, 620]}],
            ),
            _report(
                "ljbhclose",
                "confirmation",
                "actionable",
                matches=[{"name": "ljbhclose", "center": [640, 610]}],
            ),
            _report(
                "autoSell",
                "sell",
                "actionable",
                action="open_auto_sell",
                matches=[{"name": "autoSell", "center": [320, 610]}],
            ),
            _report(
                "sure",
                "confirmation",
                "actionable",
                action="confirm_dialog",
                matches=[{"name": "sure", "center": [640, 563]}],
            ),
            _report(
                "call10",
                "summon",
                "actionable",
                action="summon_ten",
                matches=[{"name": "call10", "center": [800, 520]}],
            ),
            _report(
                "decide",
                "confirmation",
                "actionable",
                action="confirm_summon",
                matches=[{"name": "decide", "center": [835, 563]}],
            ),
            _report(
                "again10",
                "summon",
                "actionable",
                action="summon_again",
                matches=[
                    {"name": "again10", "center": [760, 673]},
                    {"name": "bianhuan", "center": [1040, 670]},
                ],
            ),
        )
    )

    class Recognizer:
        def recognize_navigation(self, *_args, **_kwargs):
            return next(nav_states)

        def recognize(self, *_args, **_kwargs):
            return next(reports)

        def recognize_storage_grid(self, *_args, **_kwargs):
            return {
                "rows": 3,
                "columns": 7,
                "recognized_count": 1,
                "slots": [{"slot": 0, "star": 4, "center": [136, 248]}],
            }

    device = _Device()
    result = create_expball_run_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "max_summons": 1,
            "overflow_actions": ["storage", "sell", "equipment_enhancement"],
            "stars": [4],
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["storage_full"] is True
    assert result["overflow_actions"] == [
        "storage",
        "sell",
        "equipment_enhancement",
    ]
    assert [stage["stage"] for stage in result["stages"]] == [
        "navigate_summon",
        "summon",
        "navigate_storage",
        "storage",
        "navigate_sell",
        "sell",
        "navigate_equipment_enhancement",
        "equipment_enhancement",
        "navigate_summon",
        "summon",
    ]




