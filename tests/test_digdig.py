from webapp.automation.digdig import (
    DIGDIG_INSPECT_JOB_KIND,
    create_digdig_inspect_handler,
    register_digdig_inspect_job,
)
from webapp.core.models import MatchResult
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
        return {"server": "CH"}


class _Device:
    def snapshot(self):
        return b"dig-screen"


class _Context:
    def __init__(self):
        self.events = []

    def checkpoint(self, step, **options):
        self.events.append(("checkpoint", step, options))

    def emit(self, event_type, message, **options):
        self.events.append((event_type, message, options))


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
