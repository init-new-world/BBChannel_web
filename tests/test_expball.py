from webapp.automation.expball import (
    EXPBALL_INSPECT_JOB_KIND,
    create_expball_inspect_handler,
    register_expball_inspect_job,
)
from webapp.core.models import MatchResult
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
        return {"server": "CH"}


class _Device:
    def snapshot(self):
        return b"expball-screen"


class _Context:
    def __init__(self):
        self.events = []

    def checkpoint(self, step, **options):
        self.events.append(("checkpoint", step, options))

    def emit(self, event_type, message, **options):
        self.events.append((event_type, message, options))


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
