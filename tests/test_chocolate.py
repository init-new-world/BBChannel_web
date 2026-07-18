from webapp.automation.chocolate import (
    CHOCOLATE_INSPECT_JOB_KIND,
    CHOCOLATE_RUN_JOB_KIND,
    create_chocolate_inspect_handler,
    create_chocolate_run_handler,
    register_chocolate_inspect_job,
    register_chocolate_run_job,
)
from webapp.core.models import MatchResult, OperationResult
from webapp.runtime import JobDatabase, JobManager
from webapp.services.chocolate import ChocolateRecognizer


def _match(template_path: str, matched: bool, confidence: float) -> MatchResult:
    return MatchResult(
        template_path=template_path,
        matched=matched,
        confidence=confidence,
        threshold=0.82,
        top_left=[100, 200],
        size=[80, 40],
        center=[140, 220],
    )


class _Resources:
    def template_index(self, *, prefix, limit):
        assert prefix == "chocolate/CH"
        assert limit == 100
        return {
            "entries": [
                {"path": "chocolate/CH/receive.png"},
                {"path": "chocolate/CH/limit.png"},
                {"path": "chocolate/CH/pay.png"},
            ]
        }


def test_chocolate_recognizer_prioritizes_blocking_state_over_actions():
    class Recognition:
        def __init__(self):
            self.candidates = None

        def match_templates(self, _screenshot, candidates):
            self.candidates = candidates
            return [
                _match(candidate["template_path"], True, confidence)
                for candidate, confidence in zip(
                    candidates,
                    (0.93, 0.88, 0.91),
                    strict=True,
                )
            ]

    recognition = Recognition()
    report = ChocolateRecognizer(_Resources(), recognition).recognize(
        b"screen",
        "ch",
    )

    assert [candidate["template_path"] for candidate in recognition.candidates] == [
        "chocolate/CH/limit.png",
        "chocolate/CH/receive.png",
        "chocolate/CH/pay.png",
    ]
    assert report["server"] == "CH"
    assert report["state"] == "limit"
    assert report["status"] == "blocked"
    assert report["reason"] == "storage_full"
    assert report["recommended_action"] is None
    assert [match["name"] for match in report["matches"]] == [
        "limit",
        "receive",
        "pay",
    ]


class _ScriptData:
    def get_setting_plan(self, name):
        assert name == "demo"
        return {
            "server": "CNTW",
            "run": {"random_touch": False, "random_time": 0},
        }


class _Device:
    def __init__(self):
        self.taps = []

    def snapshot(self):
        return b"chocolate-screen"

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


def test_chocolate_inspect_handler_reports_current_device_state():
    class Recognizer:
        def recognize(self, screenshot, server, *, threshold):
            assert screenshot == b"chocolate-screen"
            assert server == "CNTW"
            assert threshold == 0.9
            return {
                "server": server,
                "state": "makeChoco",
                "status": "actionable",
                "reason": None,
                "recommended_action": "make_chocolate",
                "matches": [],
            }

    context = _Context()
    result = create_chocolate_inspect_handler(
        _ScriptData(),
        _Device(),
        Recognizer(),
    )(context, {"setting_name": "demo", "threshold": 0.9})

    assert result["state"] == "makeChoco"
    assert result["recommended_action"] == "make_chocolate"
    assert [event[0] for event in context.events] == [
        "checkpoint",
        "chocolate_state",
        "checkpoint",
    ]


def test_chocolate_inspect_job_requires_connected_device(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_chocolate_inspect_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )

        assert manager.has_kind(CHOCOLATE_INSPECT_JOB_KIND)
        assert manager.requires_device(CHOCOLATE_INSPECT_JOB_KIND) is True


def _report(
    state,
    status,
    *,
    action=None,
    reason=None,
    center=(140, 220),
):
    matches = []
    if state != "unknown":
        matches.append(
            {
                "name": state,
                "status": status,
                "reason": reason,
                "recommended_action": action,
                "center": list(center),
                "size": [80, 40],
            }
        )
    return {
        "server": "CNTW",
        "state": state,
        "status": status,
        "reason": reason,
        "recommended_action": action,
        "matches": matches,
    }


def test_chocolate_run_executes_actions_until_materials_are_exhausted():
    reports = iter(
        (
            _report(
                "makeChoco",
                "actionable",
                action="make_chocolate",
                center=(300, 400),
            ),
            _report("yes", "actionable", action="confirm", center=(500, 420)),
            _report(
                "notEnough",
                "blocked",
                reason="materials_exhausted",
            ),
        )
    )

    class Recognizer:
        def recognize(self, _screenshot, server, *, threshold):
            assert server == "CNTW"
            assert threshold == 0.82
            return next(reports)

    device = _Device()
    context = _Context()
    result = create_chocolate_run_handler(
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
    assert result["reason"] == "materials_exhausted"
    assert result["actions"] == ["make_chocolate", "confirm"]
    assert result["attempts"] == 3
    assert device.taps == [(300, 400), (500, 420)]
    assert context.events[-1][0:2] == ("checkpoint", "complete")


def test_chocolate_run_stops_without_tapping_when_storage_is_full():
    class Recognizer:
        def recognize(self, _screenshot, _server, *, threshold):
            assert threshold == 0.9
            return _report("limit", "blocked", reason="storage_full")

    device = _Device()
    result = create_chocolate_run_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(_Context(), {"setting_name": "demo", "threshold": 0.9})

    assert result["completed"] is False
    assert result["stopped"] is True
    assert result["reason"] == "storage_full"
    assert result["actions"] == []
    assert device.taps == []


def test_chocolate_run_job_requires_connected_device(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_chocolate_run_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )

        assert manager.has_kind(CHOCOLATE_RUN_JOB_KIND)
        assert manager.requires_device(CHOCOLATE_RUN_JOB_KIND) is True
