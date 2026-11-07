from webapp.automation.expball import (
    EXPBALL_CE_BOMB_GRID_INSPECT_JOB_KIND,
    EXPBALL_COMMAND_CODE_GRID_INSPECT_JOB_KIND,
    EXPBALL_ENHANCE_JOB_KIND,
    EXPBALL_INSPECT_JOB_KIND,
    EXPBALL_SERVANT_GRID_INSPECT_JOB_KIND,
    EXPBALL_SERVANT_LEVEL_INSPECT_JOB_KIND,
    EXPBALL_SERVANT_TARGET_INSPECT_JOB_KIND,
    EXPBALL_STORAGE_GRID_INSPECT_JOB_KIND,
    EXPBALL_STORAGE_JOB_KIND,
    EXPBALL_SUMMON_JOB_KIND,
    EXPBALL_SUMMON_LOCK_INSPECT_JOB_KIND,
    create_expball_ce_bomb_grid_inspect_handler,
    create_expball_command_code_grid_inspect_handler,
    create_expball_enhance_handler,
    create_expball_inspect_handler,
    create_expball_servant_grid_inspect_handler,
    create_expball_servant_level_inspect_handler,
    create_expball_servant_target_inspect_handler,
    create_expball_storage_grid_inspect_handler,
    create_expball_storage_handler,
    create_expball_summon_handler,
    create_expball_summon_lock_inspect_handler,
    register_expball_ce_bomb_grid_inspect_job,
    register_expball_command_code_grid_inspect_job,
    register_expball_enhance_job,
    register_expball_inspect_job,
    register_expball_servant_grid_inspect_job,
    register_expball_servant_level_inspect_job,
    register_expball_servant_target_inspect_job,
    register_expball_storage_grid_inspect_job,
    register_expball_storage_job,
    register_expball_summon_job,
    register_expball_summon_lock_inspect_job,
)
from webapp.core.models import MatchResult, OperationResult
from webapp.runtime import JobDatabase, JobManager
from webapp.services.expball import ExpBallRecognizer


def _match(template_path, matched, confidence):
    return MatchResult(
        template_path=template_path,
        matched=matched,
        confidence=confidence,
        threshold=0.84,
        top_left=[700, 500],
        size=[180, 60],
        center=[790, 530],
        scale=2 / 3,
    )


class _Resources:
    def template_index(self, *, prefix, limit):
        assert prefix == "expball/CNTW"
        assert limit == 200
        return {
            "entries": [
                {"path": "expball/CNTW/friendpointcall.png"},
                {"path": "expball/CNTW/callfree.png"},
                {"path": "expball/CNTW/again10.png"},
                {"path": "expball/CNTW/boxfull.png"},
                {"path": "expball/CNTW/noSucai.png"},
            ]
        }


def test_expball_recognizer_prioritizes_terminal_state_over_summon_actions():
    class Recognition:
        def __init__(self):
            self.candidates = None

        def match_templates(self, _screenshot, candidates):
            self.candidates = candidates
            return [
                _match(candidate["template_path"], True, 0.95 - index * 0.01)
                for index, candidate in enumerate(candidates)
            ]

    recognition = Recognition()
    report = ExpBallRecognizer(_Resources(), recognition).recognize(
        b"screen",
        "cntw",
    )

    assert [candidate["template_path"] for candidate in recognition.candidates] == [
        "expball/CNTW/noSucai.png",
        "expball/CNTW/callfree.png",
        "expball/CNTW/again10.png",
        "expball/CNTW/boxfull.png",
        "expball/CNTW/friendpointcall.png",
    ]
    assert report["server"] == "CNTW"
    assert report["state"] == "noSucai"
    assert report["flow"] == "enhancement"
    assert report["status"] == "blocked"
    assert report["reason"] == "materials_exhausted"
    assert report["recommended_action"] is None
    assert [match["name"] for match in report["matches"]] == [
        "noSucai",
        "callfree",
        "again10",
        "boxfull",
        "friendpointcall",
    ]


def test_expball_recognizer_supports_jp_assets():
    class Resources:
        def template_index(self, *, prefix, limit):
            assert prefix == "expball/JP"
            assert limit == 200
            return {"entries": [{"path": "expball/JP/callfree.png"}]}

    class Recognition:
        def match_templates(self, _screenshot, candidates):
            assert candidates[0]["template_path"] == "expball/JP/callfree.png"
            return [_match("expball/JP/callfree.png", True, 0.96)]

    report = ExpBallRecognizer(Resources(), Recognition()).recognize(
        b"jp-screen",
        "jp",
    )

    assert report["server"] == "JP"
    assert report["state"] == "callfree"
    assert report["recommended_action"] == "summon_free_ten"


def test_expball_recognizer_prioritizes_storage_full_over_storage_actions():
    class Resources:
        def template_index(self, *, prefix, limit):
            assert prefix == "expball/CH"
            assert limit == 200
            return {
                "entries": [
                    {"path": "expball/CH/store_full.png"},
                    {"path": "expball/CH/zxStore.png"},
                    {"path": "expball/CH/in_store.png"},
                ]
            }

    class Recognition:
        def match_templates(self, _screenshot, candidates):
            return [
                _match(candidate["template_path"], True, 0.99 - index * 0.01)
                for index, candidate in enumerate(candidates)
            ]

    report = ExpBallRecognizer(Resources(), Recognition()).recognize(
        b"storage-screen",
        "CH",
    )

    assert report["state"] == "store_full"
    assert report["flow"] == "storage"
    assert report["status"] == "blocked"
    assert report["reason"] == "storage_full"
    assert report["recommended_action"] is None
    assert [match["name"] for match in report["matches"]] == [
        "store_full",
        "zxStore",
        "in_store",
    ]


def test_expball_recognizer_exposes_selection_and_result_controls():
    class Resources:
        def template_index(self, *, prefix, limit):
            assert prefix == "expball/CH"
            assert limit == 200
            return {
                "entries": [
                    {"path": "expball/CH/jd.png"},
                    {"path": "expball/CH/ljbhclose.png"},
                ]
            }

    class Recognition:
        def match_templates(self, _screenshot, candidates):
            return [
                _match(candidate["template_path"], True, 0.99 - index * 0.01)
                for index, candidate in enumerate(candidates)
            ]

    report = ExpBallRecognizer(Resources(), Recognition()).recognize(
        b"controls",
        "CH",
    )

    assert [match["name"] for match in report["matches"]] == [
        "jd",
        "ljbhclose",
    ]
    assert report["matches"][0]["recommended_action"] == "submit_selection"
    assert report["matches"][1]["recommended_action"] == "close_result"


def test_expball_recognizer_distinguishes_summon_confirmation_and_result():
    names = ["decide", "bianhuan", "again10_0", "again10_1", "close"]

    class Resources:
        def template_index(self, *, prefix, limit):
            assert prefix == "expball/CH"
            assert limit == 200
            return {
                "entries": [
                    {"path": f"expball/CH/{name}.png"}
                    for name in names
                ]
            }

    class Recognition:
        def match_templates(self, _screenshot, candidates):
            return [
                _match(candidate["template_path"], True, 0.99 - index * 0.01)
                for index, candidate in enumerate(candidates)
            ]

    report = ExpBallRecognizer(Resources(), Recognition()).recognize(
        b"summon-result",
        "CH",
    )
    matches = {match["name"]: match for match in report["matches"]}

    assert matches["decide"]["recommended_action"] == "confirm_summon"
    assert matches["bianhuan"]["status"] == "observed"
    assert matches["again10_0"]["status"] == "observed"
    assert matches["again10_0"]["recommended_action"] is None
    assert matches["again10_1"]["recommended_action"] == "summon_again"
    assert matches["close"]["recommended_action"] == "close_summon_result"


def test_expball_recognizer_scans_visible_storage_grid_by_slot():
    class Resources:
        def template_index(self, *, prefix, limit):
            assert prefix == "expball/FPgold"
            assert limit == 20
            return {
                "entries": [
                    {"path": f"expball/FPgold/{star}jyz.png"}
                    for star in (3, 4, 5)
                ]
            }

    class Recognition:
        def __init__(self):
            self.candidates = None

        def match_templates(self, _screenshot, candidates):
            self.candidates = candidates
            results = []
            for index, candidate in enumerate(candidates):
                slot = index // 3
                star = 3 + index % 3
                confidence = 0.1
                matched = False
                if slot == 0 and star in {3, 4}:
                    confidence = 0.88 if star == 3 else 0.96
                    matched = True
                if slot == 8 and star == 5:
                    confidence = 0.93
                    matched = True
                results.append(
                    MatchResult(
                        template_path=candidate["template_path"],
                        matched=matched,
                        confidence=confidence,
                        threshold=0.75,
                        top_left=[100, 200],
                        size=[40, 30],
                        center=[120, 215],
                        scale=2 / 3,
                        roi=list(candidate["roi"]),
                    )
                )
            return results

    recognition = Recognition()
    report = ExpBallRecognizer(Resources(), recognition).recognize_storage_grid(
        b"storage-grid",
        threshold=0.75,
    )

    assert len(recognition.candidates) == 63
    assert recognition.candidates[0] == {
        "template_path": "expball/FPgold/3jyz.png",
        "threshold": 0.75,
        "roi": (75, 181, 123, 134),
        "scales": (1.0, 0.75, 2 / 3, 0.5),
    }
    assert report["recognized_count"] == 2
    assert len(report["slots"]) == 21
    assert report["slots"][0]["star"] == 4
    assert report["slots"][0]["confidence"] == 0.96
    assert report["slots"][1]["star"] is None
    assert report["slots"][8]["star"] == 5
    assert report["slots"][8]["row"] == 1
    assert report["slots"][8]["column"] == 1


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
        self.swipes = []

    def snapshot(self):
        return b"expball-screen"

    def tap(self, x, y):
        self.taps.append((x, y))
        return OperationResult(ok=True, action="tap", data={"x": x, "y": y})

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.swipes.append((x1, y1, x2, y2, duration_ms))
        return OperationResult(
            ok=True,
            action="swipe",
            data={
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "duration_ms": duration_ms,
            },
        )


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


def test_expball_inspect_handler_reports_current_subflow():
    class Recognizer:
        def recognize(self, screenshot, server, *, threshold):
            assert screenshot == b"expball-screen"
            assert server == "CH"
            assert threshold == 0.91
            return {
                "server": server,
                "state": "callfree",
                "flow": "summon",
                "status": "actionable",
                "reason": None,
                "recommended_action": "summon_free_ten",
                "matches": [],
            }

    context = _Context()
    result = create_expball_inspect_handler(
        _ScriptData(),
        _Device(),
        Recognizer(),
    )(context, {"setting_name": "demo", "threshold": 0.91})

    assert result["flow"] == "summon"
    assert result["recommended_action"] == "summon_free_ten"
    assert [event[0] for event in context.events] == [
        "checkpoint",
        "expball_state",
        "checkpoint",
    ]


def test_expball_inspect_job_requires_connected_device(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_expball_inspect_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )

        assert manager.has_kind(EXPBALL_INSPECT_JOB_KIND)
        assert manager.requires_device(EXPBALL_INSPECT_JOB_KIND) is True


def test_expball_storage_grid_inspect_reports_visible_cards():
    class Recognizer:
        def recognize_storage_grid(self, screenshot, *, threshold):
            assert screenshot == b"expball-screen"
            assert threshold == 0.78
            return {
                "rows": 3,
                "columns": 7,
                "recognized_count": 2,
                "slots": [{"slot": 0, "star": 4}, {"slot": 1, "star": 5}],
            }

    context = _Context()
    result = create_expball_storage_grid_inspect_handler(
        _ScriptData(),
        _Device(),
        Recognizer(),
    )(context, {"setting_name": "demo", "threshold": 0.78})

    assert result["setting_name"] == "demo"
    assert result["server"] == "CH"
    assert result["recognized_count"] == 2
    assert context.events[-1][0:2] == ("checkpoint", "complete")


def test_expball_storage_grid_inspect_job_requires_connected_device(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_expball_storage_grid_inspect_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )

        assert manager.has_kind(EXPBALL_STORAGE_GRID_INSPECT_JOB_KIND)
        assert manager.requires_device(EXPBALL_STORAGE_GRID_INSPECT_JOB_KIND) is True


def _report(state, flow, status, *, action=None, reason=None, center=(790, 530)):
    matches = []
    if state != "unknown":
        matches.append(
            {
                "name": state,
                "flow": flow,
                "status": status,
                "reason": reason,
                "recommended_action": action,
                "center": list(center),
                "size": [180, 60],
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


def _summon_report(state, *names, action=None, status="actionable"):
    centers = {
        "callfree": (820, 600),
        "call10": (800, 610),
        "decide": (830, 570),
        "bianhuan": (350, 480),
        "again10": (760, 680),
        "again10_1": (760, 680),
        "close": (90, 55),
        "boxfull": (790, 530),
    }
    flow = "confirmation" if state == "decide" else "summon"
    return {
        "server": "CH",
        "state": state,
        "flow": flow,
        "status": status,
        "reason": None,
        "recommended_action": action,
        "matches": [
            {
                "name": name,
                "center": list(centers[name]),
                "size": [180, 60],
            }
            for name in names
        ],
    }


def _storage_report(*names):
    centers = {
        "in_store": (310, 120),
        "storeAll": (720, 310),
        "jd": (1120, 650),
        "zxStore": (980, 620),
        "ljbhclose": (640, 610),
    }
    matches = [
        {
            "name": name,
            "center": list(centers[name]),
            "size": [120, 60],
        }
        for name in names
    ]
    confirmation = "ljbhclose" in names
    return {
        "server": "CH",
        "state": names[0] if names else "unknown",
        "flow": "confirmation" if confirmation else "storage",
        "status": "observed",
        "reason": None,
        "recommended_action": None,
        "matches": matches,
    }


def test_expball_summon_runs_until_inventory_is_full():
    reports = iter(
        (
            _summon_report(
                "callfree",
                "callfree",
                action="summon_free_ten",
            ),
            _summon_report(
                "decide",
                "decide",
                action="confirm_summon",
            ),
            _summon_report(
                "bianhuan",
                "bianhuan",
                "close",
                status="observed",
            ),
            _summon_report(
                "call10",
                "call10",
                action="summon_ten",
            ),
            _summon_report(
                "boxfull",
                "boxfull",
                action="handle_full_box",
            ),
        )
    )

    class Recognizer:
        def recognize(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.84
            return next(reports)

    device = _Device()
    context = _Context()
    result = create_expball_summon_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        context,
        {
            "setting_name": "demo",
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is False
    assert result["stopped"] is True
    assert result["reason"] == "box_full"
    assert result["summons"] == 1
    assert result["actions"] == [
        "summon_free_ten",
        "confirm_summon",
        "close_summon_result",
        "summon_ten",
    ]
    assert device.taps == [(820, 600), (830, 570), (90, 55), (800, 610)]
    assert context.events[-1][0:2] == ("checkpoint", "complete")


def test_expball_summon_stops_outside_summon_flow_without_tapping():
    class Recognizer:
        def recognize(self, _screenshot, _server, *, threshold):
            assert threshold == 0.9
            return _report(
                "destroy",
                "sell",
                "actionable",
                action="execute_sell",
            )

    device = _Device()
    result = create_expball_summon_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(_Context(), {"setting_name": "demo", "threshold": 0.9})

    assert result["reason"] == "outside_summon_flow"
    assert result["actions"] == []
    assert device.taps == []


def test_expball_summon_stops_when_device_rejects_tap():
    class Recognizer:
        def recognize(self, _screenshot, _server, *, threshold):
            assert threshold == 0.84
            return _report(
                "call10",
                "summon",
                "actionable",
                action="summon_ten",
                center=(800, 610),
            )

    class Device(_Device):
        def tap(self, x, y):
            self.taps.append((x, y))
            return OperationResult(
                ok=False,
                action="tap",
                message="control channel disconnected",
            )

    device = Device()
    result = create_expball_summon_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(_Context(), {"setting_name": "demo"})

    assert result["completed"] is False
    assert result["stopped"] is True
    assert result["reason"] == "device_action_failed"
    assert result["summons"] == 0
    assert result["actions"] == []
    assert device.taps == [(800, 610)]


def test_expball_summon_defaults_to_ten_batches():
    reports = [
        _summon_report("call10", "call10", action="summon_ten"),
        _summon_report("decide", "decide", action="confirm_summon"),
    ]
    for batch in range(1, 11):
        reports.append(
            _summon_report(
                "again10_1",
                "bianhuan",
                "again10_1",
                action="summon_again",
            )
        )
        if batch < 10:
            reports.append(
                _summon_report("decide", "decide", action="confirm_summon")
            )
    reports = iter(reports)

    class Recognizer:
        def recognize(self, _screenshot, _server, *, threshold):
            assert threshold == 0.84
            return next(reports)

    device = _Device()
    result = create_expball_summon_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "action_wait_seconds": 0,
        },
    )

    assert result["completed"] is True
    assert result["reason"] == "summon_limit"
    assert result["summons"] == 10
    assert len(device.taps) == 20
    assert result["actions"].count("confirm_summon") == 10
    assert result["actions"].count("summon_again") == 9


def test_expball_summon_closes_a_previous_result_without_counting_it():
    reports = iter(
        (
            _summon_report(
                "bianhuan",
                "bianhuan",
                "close",
                status="observed",
            ),
            _summon_report("call10", "call10", action="summon_ten"),
            _summon_report("decide", "decide", action="confirm_summon"),
            _summon_report(
                "again10_1",
                "bianhuan",
                "again10_1",
                action="summon_again",
            ),
        )
    )

    class Recognizer:
        def recognize(self, *_args, **_kwargs):
            return next(reports)

    device = _Device()
    result = create_expball_summon_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "max_summons": 1,
            "action_wait_seconds": 0,
        },
    )

    assert result["completed"] is True
    assert result["summons"] == 1
    assert result["actions"] == [
        "recover_summon_page",
        "summon_ten",
        "confirm_summon",
    ]
    assert device.taps == [(90, 55), (800, 610), (830, 570)]


def test_expball_storage_executes_current_selection_and_confirms():
    reports = iter(
        (
            _storage_report("in_store", "jd"),
            _storage_report("zxStore"),
            _storage_report("ljbhclose"),
            _storage_report("in_store"),
        )
    )

    class Recognizer:
        def recognize(self, _screenshot, _server, *, threshold):
            assert threshold == 0.84
            return next(reports)

    device = _Device()
    context = _Context()
    result = create_expball_storage_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        context,
        {
            "setting_name": "demo",
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "stored"
    assert result["actions"] == [
        "submit_storage_selection",
        "execute_storage",
        "close_storage_result",
    ]
    assert device.taps == [(1120, 650), (980, 620), (640, 610)]
    assert context.events[-1][0:2] == ("checkpoint", "complete")


def test_expball_storage_refuses_to_start_outside_storage_screen():
    class Recognizer:
        def recognize(self, _screenshot, _server, *, threshold):
            assert threshold == 0.84
            return _report(
                "callfree",
                "summon",
                "actionable",
                action="summon_free_ten",
            )

    device = _Device()
    result = create_expball_storage_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(_Context(), {"setting_name": "demo"})

    assert result["completed"] is False
    assert result["stopped"] is True
    assert result["reason"] == "outside_storage_flow"
    assert result["actions"] == []
    assert device.taps == []


def test_expball_storage_stops_when_a_storage_action_fails():
    class Recognizer:
        def recognize(self, _screenshot, _server, *, threshold):
            assert threshold == 0.84
            return _storage_report("in_store", "jd")

    class Device(_Device):
        def tap(self, x, y):
            self.taps.append((x, y))
            return OperationResult(ok=False, action="tap", message="rejected")

    device = Device()
    result = create_expball_storage_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(_Context(), {"setting_name": "demo"})

    assert result["reason"] == "device_action_failed"
    assert result["actions"] == []
    assert device.taps == [(1120, 650)]


def test_expball_storage_refuses_to_store_without_current_selection():
    class Recognizer:
        def recognize(self, *_args, **_kwargs):
            return _storage_report("in_store", "storeAll")

    result = create_expball_storage_handler(
        _ScriptData(),
        _Device(),
        Recognizer(),
    )(
        _Context(),
        {"setting_name": "demo", "max_idle_polls": 1},
    )

    assert result["completed"] is False
    assert result["reason"] == "no_actionable_selection"
    assert result["actions"] == []


def test_expball_storage_stops_when_storage_is_full_without_tapping():
    class Recognizer:
        def recognize(self, *_args, **_kwargs):
            return _report(
                "store_full",
                "storage",
                "blocked",
                reason="storage_full",
            )

    device = _Device()
    result = create_expball_storage_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(_Context(), {"setting_name": "demo"})

    assert result["completed"] is False
    assert result["stopped"] is True
    assert result["reason"] == "storage_full"
    assert result["actions"] == []
    assert device.taps == []


def test_expball_storage_selects_cards_by_rarity_before_submitting():
    reports = iter(
        (
            _storage_report("in_store"),
            _storage_report("in_store", "jd"),
            _storage_report("zxStore"),
            _storage_report("ljbhclose"),
            _storage_report("in_store"),
        )
    )

    class Recognizer:
        def recognize(self, _screenshot, _server, *, threshold):
            assert threshold == 0.84
            return next(reports)

        def recognize_storage_grid(self, _screenshot, *, threshold):
            assert threshold == 0.78
            return {
                "rows": 3,
                "columns": 7,
                "recognized_count": 3,
                "slots": [
                    {"slot": 0, "star": 3, "center": [136, 248]},
                    {"slot": 1, "star": 4, "center": [269, 248]},
                    {"slot": 2, "star": 5, "center": [402, 248]},
                ],
            }

    device = _Device()
    context = _Context()
    result = create_expball_storage_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        context,
        {
            "setting_name": "demo",
            "stars": [4, 5],
            "grid_threshold": 0.78,
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["reason"] == "stored"
    assert result["selected_slots"] == [1, 2]
    assert result["selected_count"] == 2
    assert result["actions"] == [
        "select_storage_card",
        "select_storage_card",
        "submit_storage_selection",
        "execute_storage",
        "close_storage_result",
    ]
    assert device.taps == [
        (269, 248),
        (402, 248),
        (1120, 650),
        (980, 620),
        (640, 610),
    ]


def test_expball_storage_stops_when_no_grid_cards_match_requested_stars():
    class Recognizer:
        def recognize(self, *_args, **_kwargs):
            return _storage_report("in_store")

        def recognize_storage_grid(self, *_args, **_kwargs):
            return {
                "rows": 3,
                "columns": 7,
                "recognized_count": 1,
                "slots": [{"slot": 0, "star": 3, "center": [136, 248]}],
            }

    device = _Device()
    result = create_expball_storage_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(_Context(), {"setting_name": "demo", "stars": [5]})

    assert result["completed"] is False
    assert result["stopped"] is True
    assert result["reason"] == "no_matching_cards"
    assert result["selected_slots"] == []
    assert device.taps == []


def test_expball_storage_job_requires_connected_device(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_expball_storage_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )

        assert manager.has_kind(EXPBALL_STORAGE_JOB_KIND)
        assert manager.requires_device(EXPBALL_STORAGE_JOB_KIND) is True


def test_expball_summon_job_requires_connected_device(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_expball_summon_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )

        assert manager.has_kind(EXPBALL_SUMMON_JOB_KIND)
        assert manager.requires_device(EXPBALL_SUMMON_JOB_KIND) is True


def test_expball_recognizer_recognizes_servant_level_and_grail_levels():
    class Resources:
        def template_index(self, *, prefix, limit):
            assert prefix == "expball/digits"
            assert limit == 20
            return {
                "entries": [
                    {"path": f"expball/digits/{digit}.png"}
                    for digit in range(10)
                ]
            }

    class Recognition:
        def __init__(self, slot_digits):
            self.slot_digits = slot_digits
            self.candidates = None

        def match_templates(self, _screenshot, candidates):
            self.candidates = candidates
            results = []
            for index, candidate in enumerate(candidates):
                slot_index = index // 10
                digit = index % 10
                expected = self.slot_digits.get(slot_index)
                matched = expected == digit
                confidence = 0.96 if matched else 0.12
                results.append(
                    MatchResult(
                        template_path=candidate["template_path"],
                        matched=matched,
                        confidence=confidence,
                        threshold=0.6,
                        top_left=[candidate["roi"][0], candidate["roi"][1]],
                        size=[22, 33],
                        center=[
                            candidate["roi"][0] + 11,
                            candidate["roi"][1] + 16,
                        ],
                        scale=2 / 3,
                        roi=list(candidate["roi"]),
                    )
                )
            return results

    grail_recognition = Recognition({0: 2, 1: 0, 2: 1, 3: 2, 4: 0})
    grail_report = ExpBallRecognizer(
        Resources(), grail_recognition
    ).recognize_servant_level(b"servant-level", threshold=0.6)

    assert len(grail_recognition.candidates) == 50
    assert grail_recognition.candidates[0]["use_alpha_mask"] is False
    assert grail_report["current_level"] == 120
    assert grail_report["max_level"] == 120
    assert grail_report["is_max_level"] is True

    normal_recognition = Recognition({0: 8, 1: 0, 2: 9, 3: 0})
    normal_report = ExpBallRecognizer(
        Resources(), normal_recognition
    ).recognize_servant_level(b"servant-level", threshold=0.6)

    assert normal_report["current_level"] == 80
    assert normal_report["max_level"] == 90
    assert normal_report["is_max_level"] is False


def test_expball_servant_level_inspect_handler_and_job_registration(tmp_path):
    class Recognizer:
        def recognize_servant_level(self, screenshot, *, threshold):
            assert screenshot == b"expball-screen"
            assert threshold == 0.65
            return {
                "threshold": threshold,
                "current_level": 100,
                "max_level": 100,
                "is_max_level": True,
                "left_digits": [],
                "right_digits": [],
            }

    context = _Context()
    result = create_expball_servant_level_inspect_handler(
        _ScriptData(),
        _Device(),
        Recognizer(),
    )(context, {"setting_name": "demo", "threshold": 0.65})

    assert result["setting_name"] == "demo"
    assert result["server"] == "CH"
    assert result["current_level"] == 100
    assert result["max_level"] == 100
    assert result["is_max_level"] is True

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_expball_servant_level_inspect_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )
        assert manager.has_kind(EXPBALL_SERVANT_LEVEL_INSPECT_JOB_KIND)
        assert (
            manager.requires_device(EXPBALL_SERVANT_LEVEL_INSPECT_JOB_KIND)
            is True
        )


def _enhance_report(*names, reason=None):
    centers = {
        "exlevel": (197, 157),
        "xzdx": (300, 80),
        "slot": (823, 283),
        "help": (1180, 110),
        "feedjd": (830, 593),
        "cssd": (227, 635),
        "sure": (640, 520),
        "tysd": (420, 80),
        "qhjd": (1153, 670),
        "qhjd2": (830, 593),
        "noSucai": (640, 360),
        "sbzl": (1050, 557),
        "ljzl": (1050, 557),
        "qdjqh": (500, 120),
        "gotoqhcz": (1047, 285),
    }
    return {
        "server": "CH",
        "state": names[0] if names else "unknown",
        "flow": "enhancement",
        "status": "blocked" if reason else "actionable",
        "reason": reason,
        "recommended_action": None,
        "matches": [
            {
                "name": name,
                "center": list(centers[name]),
                "size": [120, 50],
            }
            for name in names
            if name in centers
        ],
    }


def test_expball_enhance_auto_selects_and_stops_when_target_servant_level_reached():
    reports = iter(
        (
            _enhance_report("exlevel", "help"),
            _enhance_report("xzdx"),
            _enhance_report("slot", "help"),
            _enhance_report("feedjd", "help"),
            _enhance_report("help"),
            _enhance_report("qhjd2"),
            _enhance_report("unknown"),
            _enhance_report("slot", "help"),
        )
    )
    levels = iter(
        (
            {
                "current_level": 80,
                "max_level": 90,
                "is_max_level": False,
            },
            {
                "current_level": 90,
                "max_level": 90,
                "is_max_level": True,
            },
        )
    )

    class Recognizer:
        def recognize(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.84
            return next(reports)

        def recognize_servant_level(self, _screenshot, *, threshold):
            assert threshold == 0.6
            return next(levels)

    device = _Device()
    context = _Context()
    result = create_expball_enhance_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        context,
        {
            "setting_name": "demo",
            "target": "servant",
            "material_select_mode": "auto",
            "select_base_first": True,
            "target_level": 90,
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "target_level_reached"
    assert result["batches_completed"] == 1
    assert result["servant_level"]["current_level"] == 90
    assert result["actions"] == [
        "open_base_selection",
        "select_base_card",
        "auto_select_materials",
        "confirm_auto_select",
        "execute_enhancement",
        "confirm_enhancement",
        "skip_enhancement_animation",
    ]
    assert device.taps == [
        (197, 157),
        (135, 243),
        (1217, 167),
        (830, 593),
        (1140, 670),
        (830, 593),
        (823, 498),
    ]


def test_expball_enhance_supports_rarity_filtered_grid_equipment_enhancement(tmp_path):
    reports = iter(
        (
            _enhance_report("slot", "help"),
            _enhance_report("tysd", "qhjd"),
            _enhance_report("help"),
            _enhance_report("qhjd2"),
            _enhance_report("slot", "help"),
        )
    )

    class Recognizer:
        def recognize(self, *_args, **_kwargs):
            return next(reports)

        def recognize_storage_grid(self, _screenshot, *, threshold):
            assert threshold == 0.75
            return {
                "rows": 3,
                "columns": 7,
                "recognized_count": 2,
                "slots": [
                    {"slot": 0, "star": 3, "center": [136, 248]},
                    {"slot": 1, "star": 4, "center": [269, 248]},
                ],
            }

    device = _Device()
    result = create_expball_enhance_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "target": "equipment",
            "material_select_mode": "grid",
            "stars": [3, 4],
            "max_batches": 1,
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["reason"] == "batch_limit"
    assert result["batches_completed"] == 1
    assert result["selected_slots"] == [0, 1]
    assert result["actions"] == [
        "open_material_slots",
        "select_material_card",
        "select_material_card",
        "confirm_material_selection",
        "execute_enhancement",
        "confirm_enhancement",
    ]

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_expball_enhance_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )
        assert manager.has_kind(EXPBALL_ENHANCE_JOB_KIND)
        assert manager.requires_device(EXPBALL_ENHANCE_JOB_KIND) is True


def test_expball_enhance_closes_empty_materials_modal_and_stops():
    reports = iter(
        (
            _enhance_report("slot", "help"),
            _enhance_report("sure", "slot", "help"),
        )
    )

    class Recognizer:
        def recognize(self, *_args, **_kwargs):
            return next(reports)

    device = _Device()
    result = create_expball_enhance_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "target": "equipment",
            "material_select_mode": "auto",
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "materials_exhausted"
    assert result["actions"] == [
        "auto_select_materials",
        "close_empty_materials_dialog",
    ]
    assert device.taps == [(1090, 163), (640, 520)]


def test_expball_enhance_performs_servant_limit_break_and_resumes_to_target_level():
    reports = iter(
        (
            _enhance_report("sbzl", "help"),
            _enhance_report("qdjqh", "help"),
            _enhance_report("qhjd2"),
            _enhance_report("unknown"),
            _enhance_report("gotoqhcz", "help"),
            _enhance_report("slot", "help"),
            _enhance_report("feedjd", "help"),
            _enhance_report("help"),
            _enhance_report("qhjd2"),
            _enhance_report("slot", "help"),
        )
    )
    levels = iter(
        (
            {
                "valid": True,
                "current_level": 70,
                "max_level": 70,
                "is_max_level": True,
            },
            {
                "valid": True,
                "current_level": 70,
                "max_level": 80,
                "is_max_level": False,
            },
            {
                "valid": True,
                "current_level": 80,
                "max_level": 80,
                "is_max_level": True,
            },
        )
    )

    class Recognizer:
        def recognize(self, *_args, **_kwargs):
            return next(reports)

        def recognize_servant_level(self, *_args, **_kwargs):
            return next(levels)

    device = _Device()
    result = create_expball_enhance_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "target": "servant",
            "material_select_mode": "auto",
            "target_level": 80,
            "max_batches": 2,
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "target_level_reached"
    assert result["limit_breaks_completed"] == 1
    assert result["batches_completed"] == 1
    assert result["actions"] == [
        "open_limit_break",
        "execute_limit_break",
        "confirm_limit_break",
        "skip_limit_break_animation",
        "return_to_servant_enhancement",
        "auto_select_materials",
        "confirm_auto_select",
        "execute_enhancement",
        "confirm_enhancement",
    ]
    assert device.taps == [
        (1050, 557),
        (1140, 670),
        (830, 593),
        (633, 257),
        (1047, 285),
        (1217, 167),
        (830, 593),
        (1140, 670),
        (830, 593),
    ]


def test_expball_enhance_stops_at_limit_break_when_auto_limit_break_disabled():
    class Recognizer:
        def recognize(self, *_args, **_kwargs):
            return _enhance_report("ljzl", "help")

    device = _Device()
    result = create_expball_enhance_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "target": "servant",
            "auto_limit_break": False,
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is False
    assert result["stopped"] is True
    assert result["reason"] == "grail_limit"
    assert result["limit_breaks_completed"] == 0
    assert device.taps == []


def test_expball_recognizer_recognizes_servant_sale_grid_and_fp_gold():
    import cv2
    import numpy as np
    from webapp.services.expball import _STORAGE_CARD_ROIS

    image = np.zeros((720, 1280, 3), dtype=np.uint8)

    def paint_slot_frame(slot_idx: int, rgb: tuple[int, int, int]) -> None:
        rx, ry, rw, rh = _STORAGE_CARD_ROIS[slot_idx]
        x1 = rx + round(rw * 10 / 185)
        x2 = rx + round(rw * 50 / 185)
        y1 = ry + round(rh * 180 / 201)
        y2 = ry + round(rh * 190 / 201)
        bgr = (rgb[2], rgb[1], rgb[0])
        image[y1:y2, x1:x2] = bgr

    # Slot 0: unlocked gold servant, NOT FP gold -> need_lock=True
    paint_slot_frame(0, (226, 181, 34))
    # Slot 1: unlocked gold servant, FP gold (lily) -> need_lock=False
    paint_slot_frame(1, (226, 181, 34))
    # Slot 2: locked gold servant -> need_lock=False
    paint_slot_frame(2, (120, 97, 18))
    # Slot 3: silver 3-star servant -> need_lock=False
    paint_slot_frame(3, (181, 181, 181))
    # Slot 4: bronze 1-2 star servant -> need_lock=False
    paint_slot_frame(4, (145, 128, 98))

    ok, encoded = cv2.imencode(".png", image)
    assert ok
    screenshot = encoded.tobytes()

    class Resources:
        def template_index(self, *, prefix, limit):
            assert prefix == "expball/FPgold"
            return {
                "entries": [
                    {"path": "expball/FPgold/lily.png"},
                    {"path": "expball/FPgold/habe.png"},
                ]
            }

    class Recognition:
        def match_templates(self, _screenshot, candidates):
            results = []
            for candidate in candidates:
                is_slot_1_lily = (
                    candidate["roi"] == _STORAGE_CARD_ROIS[1]
                    and candidate["template_path"] == "expball/FPgold/lily.png"
                )
                results.append(
                    MatchResult(
                        template_path=candidate["template_path"],
                        matched=is_slot_1_lily,
                        confidence=0.92 if is_slot_1_lily else 0.12,
                        threshold=candidate["threshold"],
                        top_left=[208, 181],
                        size=[80, 80],
                        center=[248, 221],
                        scale=2 / 3,
                        roi=list(candidate["roi"]),
                    )
                )
            return results

    report = ExpBallRecognizer(Resources(), Recognition()).recognize_servant_sale_grid(
        screenshot,
        fp_gold_threshold=0.85,
    )

    assert report["need_lock_slots"] == [0]
    assert report["need_lock_count"] == 1
    assert report["fp_gold_slots"] == [1]
    assert report["fp_gold_count"] == 1
    assert report["slots"][0]["frame_type"] == "gold_unlocked"
    assert report["slots"][0]["need_lock"] is True
    assert report["slots"][1]["frame_type"] == "gold_unlocked"
    assert report["slots"][1]["fp_gold"] == "lily"
    assert report["slots"][1]["need_lock"] is False
    assert report["slots"][2]["frame_type"] == "gold_locked"
    assert report["slots"][2]["locked"] is True
    assert report["slots"][3]["frame_type"] == "silver"
    assert report["slots"][4]["frame_type"] == "bronze"


def test_expball_servant_grid_inspect_job_emits_report(tmp_path):
    class Recognizer:
        def recognize_servant_sale_grid(self, _screenshot, *, fp_gold_threshold):
            assert fp_gold_threshold == 0.85
            return {
                "rows": 3,
                "columns": 7,
                "fp_gold_threshold": 0.85,
                "need_lock_slots": [2],
                "need_lock_count": 1,
                "fp_gold_slots": [0],
                "fp_gold_count": 1,
                "slots": [],
            }

    context = _Context()
    handler = create_expball_servant_grid_inspect_handler(
        _ScriptData(),
        _Device(),
        Recognizer(),
    )
    result = handler(context, {"setting_name": "demo"})

    assert result["setting_name"] == "demo"
    assert result["server"] == "CH"
    assert result["need_lock_slots"] == [2]
    assert result["fp_gold_slots"] == [0]

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_expball_servant_grid_inspect_job(
            manager,
            _ScriptData(),
            _Device(),
            Recognizer(),
        )
        assert manager.has_kind(EXPBALL_SERVANT_GRID_INSPECT_JOB_KIND)
        assert manager.requires_device(EXPBALL_SERVANT_GRID_INSPECT_JOB_KIND) is True


def test_expball_recognizer_recognizes_command_code_sale_grid():
    from webapp.services.expball import (
        _COMMAND_CODE_CARD_ROIS,
        _FIRST_CARD_LOCKER_ROI,
    )

    class Resources:
        def template_index(self, *, prefix, limit):
            assert prefix == "expball/CH"
            return {
                "entries": [
                    {"path": "expball/CH/no_wenzhang.png"},
                    {"path": "expball/CH/locker.png"},
                    {"path": "expball/CH/kyz.png"},
                ]
            }

    class Recognition:
        def match_templates(self, _screenshot, candidates):
            results = []
            for candidate in candidates:
                is_inscribed = (
                    candidate["template_path"] == "expball/CH/kyz.png"
                    and candidate["roi"] in {
                        _COMMAND_CODE_CARD_ROIS[0],
                        _COMMAND_CODE_CARD_ROIS[4],
                    }
                )
                is_locker = (
                    candidate["template_path"] == "expball/CH/locker.png"
                    and candidate["roi"] == _FIRST_CARD_LOCKER_ROI
                )
                results.append(
                    MatchResult(
                        template_path=candidate["template_path"],
                        matched=is_inscribed or is_locker,
                        confidence=0.91 if (is_inscribed or is_locker) else 0.1,
                        threshold=candidate["threshold"],
                        top_left=[80, 184],
                        size=[80, 40],
                        center=[120, 204],
                        scale=2 / 3,
                        roi=list(candidate["roi"]),
                    )
                )
            return results

    report = ExpBallRecognizer(
        Resources(),
        Recognition(),
    ).recognize_command_code_sale_grid(b"cc-grid", "CH")

    assert report["server"] == "CH"
    assert report["empty"] is False
    assert report["first_slot_locked"] is True
    assert report["inscribed_slots"] == [0, 4]
    assert report["inscribed_count"] == 2
    assert report["slots"][0]["inscribed"] is True
    assert report["slots"][1]["inscribed"] is False
    assert report["slots"][4]["inscribed"] is True


def test_expball_command_code_grid_inspect_job_emits_report(tmp_path):
    class Recognizer:
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
            return {
                "server": "CH",
                "rows": 3,
                "columns": 7,
                "empty": False,
                "first_slot_locked": False,
                "inscribed_slots": [1],
                "inscribed_count": 1,
                "slots": [],
            }

    context = _Context()
    handler = create_expball_command_code_grid_inspect_handler(
        _ScriptData(),
        _Device(),
        Recognizer(),
    )
    result = handler(context, {"setting_name": "demo"})

    assert result["setting_name"] == "demo"
    assert result["server"] == "CH"
    assert result["inscribed_slots"] == [1]

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_expball_command_code_grid_inspect_job(
            manager,
            _ScriptData(),
            _Device(),
            Recognizer(),
        )
        assert manager.has_kind(EXPBALL_COMMAND_CODE_GRID_INSPECT_JOB_KIND)
        assert (
            manager.requires_device(EXPBALL_COMMAND_CODE_GRID_INSPECT_JOB_KIND)
            is True
        )


def test_expball_recognizer_recognizes_ce_bomb_grid():
    import cv2
    import numpy as np
    from webapp.services.expball import (
        _CE_BOMB_CARD_ROIS,
        _CE_BOMB_LOCK_ROIS,
        _CE_BOMB_MARK_ROIS,
    )

    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    for idx in range(len(_CE_BOMB_CARD_ROIS)):
        rx, ry, rw, rh = _CE_BOMB_CARD_ROIS[idx]
        x1 = rx + round(rw * 30 / 206)
        x2 = rx + round(rw * 70 / 206)
        y1 = ry + round(rh * 185 / 211)
        y2 = ry + round(rh * 195 / 211)
        rgb = (60, 54, 41) if idx in {0, 1, 2} else (147, 130, 100)
        image[y1:y2, x1:x2] = (rgb[2], rgb[1], rgb[0])

    ok, encoded = cv2.imencode(".png", image)
    assert ok
    screenshot = encoded.tobytes()

    class Resources:
        def template_index(self, *, prefix, limit):
            assert prefix == "expball/CH"
            return {
                "entries": [
                    {"path": "expball/CH/locker.png"},
                    {"path": "expball/CH/biaoji.png"},
                ]
            }

    class Recognition:
        def match_templates(self, _screenshot, candidates):
            results = []
            for candidate in candidates:
                is_locked = (
                    candidate["template_path"] == "expball/CH/locker.png"
                    and candidate["roi"] in {
                        _CE_BOMB_LOCK_ROIS[0],
                        _CE_BOMB_LOCK_ROIS[1],
                    }
                )
                is_marked = (
                    candidate["template_path"] == "expball/CH/biaoji.png"
                    and candidate["roi"] == _CE_BOMB_MARK_ROIS[0]
                )
                matched = is_locked or is_marked
                results.append(
                    MatchResult(
                        template_path=candidate["template_path"],
                        matched=matched,
                        confidence=0.92 if matched else 0.1,
                        threshold=candidate["threshold"],
                        top_left=[60, 220],
                        size=[34, 40],
                        center=[77, 240],
                        scale=2 / 3,
                        roi=list(candidate["roi"]),
                    )
                )
            return results

    report = ExpBallRecognizer(
        Resources(),
        Recognition(),
    ).recognize_ce_bomb_grid(screenshot, "CH")

    assert report["server"] == "CH"
    assert report["full_level_slots"] == [0, 1, 2]
    assert report["full_level_count"] == 3
    assert report["need_lock_slots"] == [2]
    assert report["need_lock_count"] == 1
    assert report["need_mark_slots"] == [1, 2]
    assert report["need_mark_count"] == 2
    assert report["need_store_slots"] == [0]
    assert report["need_store_count"] == 1
    assert report["slots"][0]["need_store"] is True
    assert report["slots"][1]["need_mark"] is True
    assert report["slots"][2]["need_lock"] is True


def test_expball_ce_bomb_grid_inspect_job_emits_report(tmp_path):
    class Recognizer:
        def recognize_ce_bomb_grid(
            self,
            _screenshot,
            server,
            *,
            locker_threshold,
            mark_threshold,
        ):
            assert server == "CH"
            assert locker_threshold == 0.7
            assert mark_threshold == 0.6
            return {
                "server": "CH",
                "rows": 3,
                "columns": 7,
                "full_level_slots": [0],
                "full_level_count": 1,
                "need_lock_slots": [],
                "need_lock_count": 0,
                "need_mark_slots": [],
                "need_mark_count": 0,
                "need_store_slots": [0],
                "need_store_count": 1,
                "slots": [],
            }

    context = _Context()
    handler = create_expball_ce_bomb_grid_inspect_handler(
        _ScriptData(),
        _Device(),
        Recognizer(),
    )
    result = handler(context, {"setting_name": "demo"})

    assert result["setting_name"] == "demo"
    assert result["server"] == "CH"
    assert result["need_store_slots"] == [0]

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_expball_ce_bomb_grid_inspect_job(
            manager,
            _ScriptData(),
            _Device(),
            Recognizer(),
        )
        assert manager.has_kind(EXPBALL_CE_BOMB_GRID_INSPECT_JOB_KIND)
        assert (
            manager.requires_device(EXPBALL_CE_BOMB_GRID_INSPECT_JOB_KIND)
            is True
        )


def test_expball_storage_stores_locked_and_marked_ce_bombs():
    reports = iter(
        (
            _storage_report("in_store", "jd"),
            _storage_report("in_store", "jd"),
            _storage_report("zxStore"),
            _storage_report("ljbhclose"),
            _storage_report("in_store", "jd"),
        )
    )

    class Recognizer:
        def recognize(self, *_args, **_kwargs):
            return next(reports)

        def recognize_ce_bomb_grid(self, *_args, **_kwargs):
            return {
                "server": "CH",
                "slots": [
                    {
                        "slot": 1,
                        "center": [128, 254],
                        "full_level": True,
                        "locked": True,
                        "marked": True,
                        "need_store": True,
                    },
                    {
                        "slot": 2,
                        "center": [262, 254],
                        "full_level": True,
                        "locked": True,
                        "marked": False,
                        "need_store": False,
                    },
                ],
            }

    device = _Device()
    result = create_expball_storage_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "storage_target": "ce_bomb",
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "stored"
    assert result["storage_target"] == "ce_bomb"
    assert result["selected_slots"] == [1]
    assert result["actions"] == [
        "select_ce_bomb_storage_card",
        "submit_storage_selection",
        "execute_storage",
        "close_storage_result",
    ]


def test_expball_enhance_locks_and_marks_full_level_ce_bombs():
    reports = iter(
        (
            _enhance_report("tysd", "qhjd"),
            _enhance_report("help"),
            _enhance_report("qhjd2"),
            _enhance_report("slot", "help"),
        )
    )

    class Recognizer:
        def recognize(self, *_args, **_kwargs):
            return next(reports)

        def recognize_ce_bomb_grid(self, *_args, **_kwargs):
            return {
                "server": "CH",
                "slots": [
                    {
                        "slot": 1,
                        "center": [128, 254],
                        "full_level": True,
                        "locked": False,
                        "marked": False,
                        "need_lock": True,
                        "need_mark": True,
                        "need_store": False,
                    },
                    {
                        "slot": 2,
                        "center": [262, 254],
                        "full_level": False,
                        "locked": False,
                        "marked": False,
                        "need_lock": False,
                        "need_mark": False,
                        "need_store": False,
                    },
                ],
            }

    device = _Device()
    result = create_expball_enhance_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "target": "equipment",
            "lock_full_ce_bombs": True,
            "mark_full_ce_bombs": True,
            "max_batches": 1,
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "batch_limit"
    assert result["locked_ce_bomb_slots"] == [1]
    assert result["marked_ce_bomb_slots"] == [1]
    assert result["actions"] == [
        "enable_ce_unified_lock",
        "lock_full_ce_bomb",
        "enable_ce_unified_mark",
        "mark_full_ce_bomb",
        "disable_ce_unified_mark",
        "select_material_card",
        "confirm_material_selection",
        "execute_enhancement",
        "confirm_enhancement",
    ]
    assert device.taps[:6] == [
        (32, 358),
        (128, 254),
        (32, 477),
        (128, 254),
        (32, 477),
        (262, 254),
    ]


def test_expball_recognizer_detects_summon_lock_targets_and_deduplicates_overlaps():
    class LockResources:
        def template_index(self, *, prefix, limit):
            if prefix == "expball/needLock":
                assert limit == 200
                return {
                    "entries": [
                        {"path": "expball/needLock/1.png"},
                        {"path": "expball/needLock/Servant004.jpg"},
                    ]
                }
            assert prefix == "expball/FPgold"
            return {
                "entries": [
                    {"path": "expball/FPgold/lily.png"},
                    {"path": "expball/FPgold/habe.png"},
                    {"path": "expball/FPgold/hakuno_0.png"},
                    {"path": "expball/FPgold/hakuno_1.png"},
                ]
            }

        def resolve_template(self, template_path):
            raise FileNotFoundError(template_path)

    class LockRecognition:
        def __init__(self):
            self.calls = []

        def match_template_all(
            self,
            screenshot,
            template_path,
            *,
            threshold,
            scales,
        ):
            assert screenshot == b"png"
            assert threshold == 0.82
            self.calls.append((template_path, scales))
            if template_path == "expball/needLock/1.png":
                return [
                    MatchResult(
                        template_path=template_path,
                        matched=True,
                        confidence=0.95,
                        threshold=threshold,
                        top_left=[200, 150],
                        size=[164, 176],
                        center=[282, 238],
                        scale=1.0,
                    )
                ]
            if template_path == "expball/FPgold/hakuno_0.png":
                return [
                    MatchResult(
                        template_path=template_path,
                        matched=True,
                        confidence=0.89,
                        threshold=threshold,
                        top_left=[205, 155],
                        size=[164, 176],
                        center=[287, 243],
                        scale=1.0,
                    ),
                    MatchResult(
                        template_path=template_path,
                        matched=True,
                        confidence=0.91,
                        threshold=threshold,
                        top_left=[450, 320],
                        size=[164, 176],
                        center=[532, 408],
                        scale=1.0,
                    ),
                ]
            return []

    recognition = LockRecognition()
    recognizer = ExpBallRecognizer(LockResources(), recognition)
    report = recognizer.recognize_summon_lock_targets(
        b"png",
        targets=["1", "hakuno"],
        threshold=0.82,
    )

    assert report["threshold"] == 0.82
    assert report["available_targets"] == ["1.png", "Servant004.jpg"]
    assert report["requested_targets"] == ["1", "hakuno"]
    assert report["target_count"] == 2
    assert report["match_count"] == 2
    assert [m["target"] for m in report["matches"]] == ["1", "hakuno"]
    assert [m["center"] for m in report["matches"]] == [
        [282, 238],
        [532, 408],
    ]
    assert [path for path, _scales in recognition.calls] == [
        "expball/needLock/1.png",
        "expball/FPgold/hakuno_0.png",
        "expball/FPgold/hakuno_1.png",
    ]


def test_expball_summon_lock_inspect_job_emits_report(tmp_path):
    class Recognizer:
        def recognize_summon_lock_targets(
            self,
            screenshot,
            *,
            targets=None,
            threshold=0.8,
        ):
            assert screenshot == b"expball-screen"
            assert targets == ["lily"]
            assert threshold == 0.85
            return {
                "threshold": threshold,
                "available_targets": ["1.png"],
                "requested_targets": ["lily"],
                "target_count": 1,
                "match_count": 1,
                "matches": [
                    {
                        "target": "lily",
                        "template_path": "expball/FPgold/lily.png",
                        "center": [310, 240],
                        "top_left": [228, 152],
                        "size": [164, 176],
                        "confidence": 0.93,
                    }
                ],
            }

    context = _Context()
    handler = create_expball_summon_lock_inspect_handler(
        _ScriptData(),
        _Device(),
        Recognizer(),
    )
    result = handler(
        context,
        {"setting_name": "demo", "targets": ["lily"], "threshold": 0.85},
    )

    assert result["setting_name"] == "demo"
    assert result["server"] == "CH"
    assert result["match_count"] == 1
    assert any(
        event[0] == "expball_summon_lock_targets" for event in context.events
    )

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_expball_summon_lock_inspect_job(
            manager,
            _ScriptData(),
            _Device(),
            Recognizer(),
        )
        assert manager.has_kind(EXPBALL_SUMMON_LOCK_INSPECT_JOB_KIND)
        assert (
            manager.requires_device(EXPBALL_SUMMON_LOCK_INSPECT_JOB_KIND)
            is True
        )


def test_expball_summon_locks_matched_target_cards_and_stops_when_enough():
    reports = iter(
        (
            _summon_report(
                "call10",
                "call10",
                action="summon_ten",
            ),
            _summon_report(
                "decide",
                "decide",
                action="confirm_summon",
            ),
            _summon_report(
                "again10",
                "again10",
                "bianhuan",
                action="summon_again",
            ),
        )
    )

    class Recognizer:
        def recognize(self, *_args, **_kwargs):
            return next(reports)

        def recognize_summon_lock_targets(
            self,
            _screenshot,
            *,
            targets=None,
            threshold=0.8,
        ):
            assert targets == ["lily"]
            assert threshold == 0.82
            return {
                "threshold": threshold,
                "available_targets": ["1.png"],
                "requested_targets": ["lily"],
                "target_count": 1,
                "match_count": 1,
                "matches": [
                    {
                        "target": "lily",
                        "template_path": "expball/FPgold/lily.png",
                        "center": [310, 240],
                        "size": [164, 176],
                    }
                ],
            }

    device = _Device()
    result = create_expball_summon_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "max_summons": 5,
            "lock_targets": [{"target": "lily", "count": 1}],
            "lock_enough_stop": True,
            "lock_threshold": 0.82,
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
            "target": "lily",
            "center": [310, 240],
            "template_path": "expball/FPgold/lily.png",
        }
    ]
    assert result["lock_targets"] == [
        {"target": "lily", "count": 1, "remaining": 0, "locked": 1}
    ]
    assert result["actions"] == [
        "summon_ten",
        "confirm_summon",
        "open_summon_card_detail",
        "lock_summon_card",
        "close_summon_card_detail",
    ]
    assert device.taps == [
        (800, 610),
        (830, 570),
        (310, 240),
        (32, 178),
        (43, 43),
    ]


def test_expball_recognizer_recognizes_servant_target_and_scroll_end(tmp_path):
    from PIL import Image

    face_path = tmp_path / "BB(SSR)_1.png"
    Image.new("RGBA", (130, 130), (200, 100, 50, 255)).save(face_path)

    class Resources:
        def template_index(self, *, prefix, limit):
            if prefix == "expball/levelupServant":
                return {
                    "entries": [
                        {"path": "expball/levelupServant/custom_svt.png"}
                    ]
                }
            if prefix == "servantface":
                return {"entries": [{"path": "servantface/BB(SSR)_1.png"}]}
            if prefix == "expball/CH":
                return {"entries": [{"path": "expball/CH/scrollEnd.png"}]}
            raise AssertionError(f"Unexpected prefix {prefix}")

        def resolve_template(self, path):
            assert path == "servantface/BB(SSR)_1.png"
            return face_path

    class Recognition:
        def __init__(self):
            self.candidates = None

        def match_templates(self, _screenshot, candidates):
            self.candidates = candidates
            return [
                MatchResult(
                    template_path=candidates[0]["template_path"],
                    matched=True,
                    confidence=0.91,
                    threshold=candidates[0]["threshold"],
                    top_left=[220, 260],
                    size=[83, 53],
                    center=[261, 286],
                    scale=candidates[0]["scales"][0],
                    roi=list(candidates[0]["roi"]),
                ),
                MatchResult(
                    template_path=candidates[1]["template_path"],
                    matched=False,
                    confidence=0.22,
                    threshold=candidates[1]["threshold"],
                    top_left=[995, 678],
                    size=[20, 16],
                    center=[1005, 686],
                    scale=2 / 3,
                    roi=list(candidates[1]["roi"]),
                ),
            ]

    recognition = Recognition()
    report = ExpBallRecognizer(
        Resources(),
        recognition,
    ).recognize_servant_target(
        b"xzdx-screen",
        "CH",
        target="BB(SSR)_1",
        threshold=0.85,
    )

    assert report["server"] == "CH"
    assert report["target"] == "BB(SSR)_1"
    assert report["template_path"] == "servantface/BB(SSR)_1.png"
    assert report["custom"] is False
    assert report["matched"] is True
    assert report["center"] == [261, 286]
    assert report["scroll_end"] is False
    assert report["available_custom_targets"] == ["custom_svt"]
    assert recognition.candidates[0]["crop"] == (27, 23, 95, 61)
    assert recognition.candidates[0]["roi"] == (60, 173, 953, 547)
    assert recognition.candidates[1]["roi"] == (993, 675, 40, 26)


def test_expball_servant_target_inspect_job_emits_report(tmp_path):
    class Recognizer:
        def recognize_servant_target(
            self,
            screenshot,
            server,
            *,
            target=None,
            threshold=0.85,
            scroll_end_threshold=0.8,
        ):
            assert screenshot == b"expball-screen"
            assert server == "CH"
            assert target == "BB(SSR)_1"
            assert threshold == 0.86
            assert scroll_end_threshold == 0.8
            return {
                "server": server,
                "target": target,
                "template_path": "servantface/BB(SSR)_1.png",
                "custom": False,
                "threshold": threshold,
                "scroll_end_threshold": scroll_end_threshold,
                "roi": [60, 173, 953, 547],
                "available_custom_targets": [],
                "matched": True,
                "confidence": 0.92,
                "center": [261, 286],
                "match": {"center": [261, 286]},
                "scroll_end": False,
                "scroll_end_match": None,
            }

    context = _Context()
    handler = create_expball_servant_target_inspect_handler(
        _ScriptData(),
        _Device(),
        Recognizer(),
    )
    result = handler(
        context,
        {"setting_name": "demo", "target": "BB(SSR)_1", "threshold": 0.86},
    )

    assert result["setting_name"] == "demo"
    assert result["matched"] is True
    assert result["center"] == [261, 286]
    assert any(
        event[0] == "expball_servant_target" for event in context.events
    )

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_expball_servant_target_inspect_job(
            manager,
            _ScriptData(),
            _Device(),
            Recognizer(),
        )
        assert manager.has_kind(EXPBALL_SERVANT_TARGET_INSPECT_JOB_KIND)
        assert (
            manager.requires_device(EXPBALL_SERVANT_TARGET_INSPECT_JOB_KIND)
            is True
        )


def test_expball_enhance_handler_scrolls_and_selects_target_servant():
    reports = iter(
        (
            _enhance_report("exlevel"),
            _enhance_report("xzdx"),
            _enhance_report("xzdx"),
            _enhance_report("slot", "help"),
            _enhance_report("feedjd", "help"),
            _enhance_report("help"),
            _enhance_report("qhjd2"),
            _enhance_report(),
            _enhance_report("slot", "help"),
        )
    )
    target_reports = iter(
        (
            {
                "server": "CH",
                "target": "BB(SSR)_1",
                "template_path": "servantface/BB(SSR)_1.png",
                "custom": False,
                "matched": False,
                "confidence": 0.35,
                "center": None,
                "scroll_end": False,
            },
            {
                "server": "CH",
                "target": "BB(SSR)_1",
                "template_path": "servantface/BB(SSR)_1.png",
                "custom": False,
                "matched": True,
                "confidence": 0.92,
                "center": [420, 380],
                "scroll_end": False,
            },
        )
    )

    class Recognizer:
        def recognize(self, *_args, **_kwargs):
            return next(reports)

        def recognize_servant_target(
            self,
            _screenshot,
            server,
            *,
            target=None,
            threshold=0.85,
            scroll_end_threshold=0.8,
        ):
            assert server == "CH"
            assert target == "BB(SSR)_1"
            assert threshold == 0.85
            assert scroll_end_threshold == 0.84
            return next(target_reports)

    device = _Device()
    result = create_expball_enhance_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "target": "servant",
            "servant_target": "BB(SSR)_1",
            "max_batches": 1,
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "batch_limit"
    assert result["servant_target"] == "BB(SSR)_1"
    assert result["selected_servant_targets"] == ["BB(SSR)_1"]
    assert result["actions"] == [
        "open_base_selection",
        "scroll_servant_list",
        "select_base_card",
        "auto_select_materials",
        "confirm_auto_select",
        "execute_enhancement",
        "confirm_enhancement",
        "skip_enhancement_animation",
    ]
    assert device.swipes == [(527, 617, 527, 190, 500)]
    assert device.taps[1] == (420, 380)


def test_expball_enhance_handler_stops_when_target_servant_not_found_at_scroll_end():
    reports = iter(
        (
            _enhance_report("xzdx"),
            _enhance_report("xzdx"),
        )
    )
    target_reports = iter(
        (
            {
                "server": "CH",
                "target": "BB(SSR)_1",
                "template_path": "servantface/BB(SSR)_1.png",
                "custom": False,
                "matched": False,
                "confidence": 0.25,
                "center": None,
                "scroll_end": True,
            },
            {
                "server": "CH",
                "target": "BB(SSR)_1",
                "template_path": "servantface/BB(SSR)_1.png",
                "custom": False,
                "matched": False,
                "confidence": 0.24,
                "center": None,
                "scroll_end": True,
            },
        )
    )

    class Recognizer:
        def recognize(self, *_args, **_kwargs):
            return next(reports)

        def recognize_servant_target(self, *_args, **_kwargs):
            return next(target_reports)

    device = _Device()
    result = create_expball_enhance_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "target": "servant",
            "servant_target": "BB(SSR)_1",
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is False
    assert result["stopped"] is True
    assert result["reason"] == "servant_not_found"
    assert result["missing_servant_targets"] == ["BB(SSR)_1"]
    assert result["actions"] == ["scroll_servant_list"]
    assert device.swipes == [(527, 617, 527, 190, 500)]


def test_expball_summon_handler_supports_hundred_roll_and_rejects_cntw():
    import pytest

    reports = iter(
        (
            _summon_report(
                "call10",
                "call10",
                action="summon_ten",
            ),
            _summon_report(
                "decide",
                "decide",
                action="confirm_summon",
            ),
            _summon_report(
                "again10_1",
                "again10_1",
                "bianhuan",
                action="summon_again",
            ),
        )
    )

    class Recognizer:
        def recognize(self, *_args, **_kwargs):
            return next(reports)

    device = _Device()
    result = create_expball_summon_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "draw_100": True,
            "max_summons": 1,
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["draw_100"] is True
    assert result["summons"] == 1
    assert result["actions"] == ["summon_hundred", "confirm_summon"]
    assert device.taps == [(880, 520), (830, 570)]

    class CntwScriptData:
        def get_setting_plan(self, name):
            assert name == "cntw"
            return {
                "server": "CNTW",
                "run": {"random_touch": False, "random_time": 0},
            }

    with pytest.raises(ValueError, match="draw_100"):
        create_expball_summon_handler(
            CntwScriptData(),
            _Device(),
            Recognizer(),
        )(
            _Context(),
            {"setting_name": "cntw", "draw_100": True},
        )


def test_expball_enhance_handler_configures_auto_select_stars_and_high_star_modal():
    reports = iter(
        (
            _enhance_report("slot"),
            _enhance_report("cssd"),
            {
                "server": "CH",
                "state": "feedjd",
                "flow": "enhancement",
                "status": "actionable",
                "reason": None,
                "recommended_action": "confirm_auto_select",
                "available_template_count": 10,
                "matches": [
                    {
                        "name": "feedjd",
                        "flow": "enhancement",
                        "status": "actionable",
                        "reason": None,
                        "recommended_action": "confirm_auto_select",
                        "template_path": "expball/CH/feedjd.png",
                        "matched": True,
                        "confidence": 0.94,
                        "threshold": 0.84,
                        "top_left": [780, 540],
                        "size": [120, 46],
                        "center": [840, 563],
                        "scale": 2 / 3,
                    }
                ],
            },
            _enhance_report("help"),
            _enhance_report("qhjd2"),
            _enhance_report("slot"),
        )
    )

    class Recognizer:
        def recognize(self, *_args, **_kwargs):
            return next(reports)

    device = _Device()
    result = create_expball_enhance_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "target": "equipment",
            "eat_3star": True,
            "eat_4star": True,
            "max_batches": 1,
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["eat_3star"] is True
    assert result["eat_4star"] is True
    assert result["actions"] == [
        "auto_select_materials",
        "reset_auto_select_settings",
        "reset_auto_select_settings",
        "reset_auto_select_settings",
        "toggle_eat_3star",
        "toggle_eat_4star",
        "confirm_auto_select_settings",
        "confirm_high_star_materials",
        "execute_enhancement",
        "confirm_enhancement",
    ]
    assert device.taps[:8] == [
        (1090, 163),
        (227, 635),
        (227, 635),
        (227, 635),
        (707, 363),
        (881, 363),
        (1053, 635),
        (840, 563),
    ]


def test_expball_enhance_handler_stops_when_ce_bomb_grid_is_full():
    reports = iter(
        (
            _enhance_report("slot"),
            _enhance_report("tysd", "qhjd"),
        )
    )

    class Recognizer:
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
                "need_lock_slots": [20],
                "need_lock_count": 1,
                "need_mark_slots": [20],
                "need_mark_count": 1,
                "need_store_slots": list(range(20)),
                "need_store_count": 20,
                "slots": [
                    {
                        "slot": idx,
                        "center": [135 + (idx % 7) * 133, 254 + (idx // 7) * 142],
                        "full_level": True,
                        "locked": idx < 20,
                        "marked": idx < 20,
                        "need_lock": idx == 20,
                        "need_mark": idx == 20,
                        "need_store": idx < 20,
                    }
                    for idx in range(21)
                ],
            }

    device = _Device()
    result = create_expball_enhance_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        _Context(),
        {
            "setting_name": "demo",
            "target": "equipment",
            "lock_full_ce_bombs": True,
            "mark_full_ce_bombs": True,
            "stop_when_ce_grid_full": True,
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "ce_bomb_grid_full"
    assert result["locked_ce_bomb_slots"] == [20]
    assert result["marked_ce_bomb_slots"] == [20]
    assert result["actions"] == [
        "open_material_slots",
        "enable_ce_unified_lock",
        "lock_full_ce_bomb",
        "enable_ce_unified_mark",
        "mark_full_ce_bomb",
        "disable_ce_unified_mark",
    ]








