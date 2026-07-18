from webapp.automation.chocolate import (
    CHOCOLATE_INSPECT_JOB_KIND,
    create_chocolate_inspect_handler,
    register_chocolate_inspect_job,
)
from webapp.core.models import MatchResult
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
        return {"server": "CNTW"}


class _Device:
    def snapshot(self):
        return b"chocolate-screen"


class _Context:
    def __init__(self):
        self.events = []

    def checkpoint(self, step, **options):
        self.events.append(("checkpoint", step, options))

    def emit(self, event_type, message, **options):
        self.events.append((event_type, message, options))


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
