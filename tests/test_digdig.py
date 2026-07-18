from webapp.automation.digdig import (
    DIGDIG_EXECUTE_JOB_KIND,
    DIGDIG_INSPECT_JOB_KIND,
    create_digdig_execute_handler,
    create_digdig_inspect_handler,
    register_digdig_execute_job,
    register_digdig_inspect_job,
)
from webapp.core.models import MatchResult, OperationResult
from webapp.runtime import JobDatabase, JobManager
from webapp.services.digdig import DigdigRecognizer


def _match(template_path, matched, confidence):
    return MatchResult(
        template_path=template_path,
        matched=matched,
        confidence=confidence,
        threshold=0.82,
        top_left=[300, 200],
        size=[60, 50],
        center=[330, 225],
        scale=2 / 3,
    )


class _Resources:
    def template_index(self, *, prefix, limit):
        assert prefix == "digdig/CH"
        assert limit == 100
        return {
            "entries": [
                {"path": "digdig/CH/freeDig.png"},
                {"path": "digdig/CH/execute.png"},
                {"path": "digdig/CH/hammer_claw.png"},
                {"path": "digdig/CH/shovel_bone.png"},
                {"path": "digdig/CH/reward.png"},
            ]
        }


def test_digdig_recognizer_reports_board_state_and_visible_piece_tools():
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
    report = DigdigRecognizer(_Resources(), recognition).recognize(
        b"screen",
        "ch",
    )

    assert [candidate["template_path"] for candidate in recognition.candidates] == [
        "digdig/CH/execute.png",
        "digdig/CH/freeDig.png",
        "digdig/CH/reward.png",
        "digdig/CH/hammer_claw.png",
        "digdig/CH/shovel_bone.png",
    ]
    assert report["server"] == "CH"
    assert report["state"] == "execute"
    assert report["status"] == "actionable"
    assert report["recommended_action"] == "execute_dig"
    assert [(piece["name"], piece["tool"]) for piece in report["pieces"]] == [
        ("hammer_claw", "hammer"),
        ("shovel_bone", "shovel"),
    ]
    assert report["suggested_tool"] == "hammer"


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
        return b"dig-screen"

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


def test_digdig_inspect_handler_reports_current_board():
    class Recognizer:
        def recognize(self, screenshot, server, *, threshold):
            assert screenshot == b"dig-screen"
            assert server == "CH"
            assert threshold == 0.9
            return {
                "server": server,
                "state": "freeDig",
                "status": "observed",
                "recommended_action": None,
                "matches": [],
                "pieces": [],
                "suggested_tool": None,
            }

    context = _Context()
    result = create_digdig_inspect_handler(
        _ScriptData(),
        _Device(),
        Recognizer(),
    )(context, {"setting_name": "demo", "threshold": 0.9})

    assert result["state"] == "freeDig"
    assert [event[0] for event in context.events] == [
        "checkpoint",
        "digdig_state",
        "checkpoint",
    ]


def test_digdig_inspect_job_requires_connected_device(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_digdig_inspect_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )

        assert manager.has_kind(DIGDIG_INSPECT_JOB_KIND)
        assert manager.requires_device(DIGDIG_INSPECT_JOB_KIND) is True


def _report(state, status, *, action=None, center=(760, 590)):
    matches = []
    if state != "unknown":
        matches.append(
            {
                "name": state,
                "status": status,
                "recommended_action": action,
                "center": list(center),
                "size": [120, 60],
            }
        )
    return {
        "server": "CH",
        "state": state,
        "status": status,
        "recommended_action": action,
        "matches": matches,
        "pieces": [],
        "suggested_tool": None,
    }


def test_digdig_execute_taps_selection_and_waits_for_result():
    reports = iter(
        (
            _report("execute", "actionable", action="execute_dig"),
            _report("digResult", "observed"),
        )
    )

    class Recognizer:
        def recognize(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.82
            return next(reports)

    device = _Device()
    context = _Context()
    result = create_digdig_execute_handler(
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
    assert result["reason"] == "dig_result"
    assert result["actions"] == ["execute_dig"]
    assert device.taps == [(760, 590)]
    assert context.events[-1][0:2] == ("checkpoint", "complete")


def test_digdig_execute_refuses_to_tap_without_execute_state():
    class Recognizer:
        def recognize(self, _screenshot, _server, *, threshold):
            assert threshold == 0.82
            return _report("freeDig", "observed")

    device = _Device()
    result = create_digdig_execute_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(_Context(), {"setting_name": "demo"})

    assert result["completed"] is False
    assert result["reason"] == "no_actionable_selection"
    assert result["actions"] == []
    assert device.taps == []


def test_digdig_execute_job_requires_connected_device(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_digdig_execute_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )

        assert manager.has_kind(DIGDIG_EXECUTE_JOB_KIND)
        assert manager.requires_device(DIGDIG_EXECUTE_JOB_KIND) is True
