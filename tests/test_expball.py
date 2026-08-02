from webapp.automation.expball import (
    EXPBALL_INSPECT_JOB_KIND,
    EXPBALL_STORAGE_GRID_INSPECT_JOB_KIND,
    EXPBALL_STORAGE_JOB_KIND,
    EXPBALL_SUMMON_JOB_KIND,
    create_expball_inspect_handler,
    create_expball_storage_grid_inspect_handler,
    create_expball_storage_handler,
    create_expball_summon_handler,
    register_expball_inspect_job,
    register_expball_storage_grid_inspect_job,
    register_expball_storage_job,
    register_expball_summon_job,
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

    def snapshot(self):
        return b"expball-screen"

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
