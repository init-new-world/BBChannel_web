from webapp.automation.expball import (
    EXPBALL_INSPECT_JOB_KIND,
    EXPBALL_SUMMON_JOB_KIND,
    create_expball_inspect_handler,
    create_expball_summon_handler,
    register_expball_inspect_job,
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


def test_expball_summon_runs_until_inventory_is_full():
    reports = iter(
        (
            _report(
                "callfree",
                "summon",
                "actionable",
                action="summon_free_ten",
                center=(820, 600),
            ),
            _report(
                "again10",
                "summon",
                "actionable",
                action="summon_again",
                center=(850, 620),
            ),
            _report(
                "boxfull",
                "summon",
                "actionable",
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
    assert result["summons"] == 2
    assert result["actions"] == ["summon_free_ten", "summon_again"]
    assert device.taps == [(820, 600), (850, 620)]
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
