import sqlite3
from copy import deepcopy
from types import SimpleNamespace

import pytest

from webapp.automation import battle
from webapp.automation.program import compile_battle_program
from webapp.runtime import JobDatabase, JobManager, JobStatus
from webapp.runtime.jobs import RunContext


class _MemoryDatabase(JobDatabase):
    def __init__(self):
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def _connect(self, *, create_schema_table=True):
        return self.connection


class _FakeDevice:
    def __init__(self, trace):
        self.trace = trace
        self.state = b"battle"

    def snapshot(self):
        self.trace.append(("snapshot", self.state.decode()))
        return self.state

    def tap(self, x, y):
        self.trace.append(("tap", x, y))
        if (x, y) == (1150, 600):
            assert self.state == b"battle"
            self.state = b"cards"
        elif (x, y) == (1250, 683):
            assert self.state == b"cards"
            self.state = b"battle"
        elif (x, y) in ((70, 590), (1217, 440)):
            assert self.state == b"battle"
        else:
            assert self.state == b"cards"
        return SimpleNamespace(to_dict=lambda: {"ok": True})


class _Match:
    confidence = 1.0

    def __init__(self, matched):
        self.matched = matched

    def to_dict(self):
        return {"matched": self.matched, "confidence": self.confidence}


class _FakeRecognition:
    def match_template(self, screenshot, template_path, *_args, **_options):
        return _Match(
            template_path.endswith("/attack.png") and screenshot == b"battle"
        )

    def match_templates(self, screenshot, candidates):
        return [_Match(screenshot == b"cards") for _ in candidates]


class _FakeCards:
    def __init__(self, trace):
        self.trace = trace
        self.calls = 0

    def recognize(self, screenshot, server, servants, *, threshold):
        assert screenshot == b"cards"
        assert server == "CH"
        assert threshold == 0.75
        self.calls += 1
        self.trace.append(("recognize",))
        return {
            "complete": True,
            "recognized_count": 5,
            "cards": [
                {
                    "slot": slot,
                    "code": code,
                    "servant_position": int(code[0]),
                    "stars": 0,
                }
                for slot, code in enumerate(
                    ("1B", "2A", "3Q", "1A", "2B"), start=1
                )
            ],
        }


def _run_conditional_job(monkeypatch, *, mode, no_speedup, checks):
    condition = {
        "card1": {
            "type": 1,
            "cards": ["1B"],
            "criticalStar": 0,
            "more_or_less": True,
        },
        "card2": {
            "type": 2,
            "cards": [],
            "criticalStar": 0,
            "more_or_less": True,
        },
        "card3": {
            "type": 2,
            "cards": [],
            "criticalStar": 0,
            "more_or_less": True,
        },
        "colorFirst": True,
    }
    plan = {
        "name": "condition-repro",
        "server": "CH",
        "servants": [{"slot": 0, "name": "One", "active": True, "sn": "100"}],
        "run": {
            "first_battle_set": 0,
            "interval_before_choose_card": 0.037,
            "no_speedup_skill": no_speedup,
            "random_time": 0,
            "random_touch": False,
        },
        "rounds": [
            {
                "round": 1,
                "turns": [
                    {
                        "turn": 0,
                        "nps": [],
                        "strategy": None,
                        "condition": [condition],
                        "actions": [
                            {"type": "skill", "command": command}
                            for command in (
                                ["Start", mode, checks], 1, ["End"]
                            )
                        ],
                    }
                ],
            }
        ],
        "validation": {"ok": True, "errors": []},
    }
    program = compile_battle_program(plan)
    assert program["execution"]["battle"] == {"ready": True, "reason": None}
    trace = []
    cards = _FakeCards(trace)

    def record_sleep(context, seconds):
        context.raise_if_cancelled()
        trace.append(("sleep", seconds))

    monkeypatch.setattr(RunContext, "sleep", record_sleep)
    monkeypatch.setattr(
        battle,
        "_wait_for_battle_transition",
        lambda *_args, **_kwargs: {"state": "finished", "round": None},
    )
    database = _MemoryDatabase()
    try:
        with JobManager(database, max_workers=1) as manager:
            battle.register_battle_jobs(
                manager,
                SimpleNamespace(get_setting_plan=lambda _name: deepcopy(plan)),
                _FakeDevice(trace),
                _FakeRecognition(),
                cards,
            )
            job = manager.start(
                "battle.execute-plan",
                {
                    "setting_name": "condition-repro",
                    "threshold": 0.75,
                    "timeout_seconds": 0.1,
                    "poll_interval": 0.01,
                    "tap_interval_seconds": 0.013,
                    "initialize_settings": False,
                },
                device_key="fake:condition",
            )
            result = manager.wait(job.job_id, timeout=2)
        events = database.list_events(job.job_id)
    finally:
        database.connection.close()
    return SimpleNamespace(
        result=result,
        trace=trace,
        cards=cards,
        roles=[
            event.data["role"]
            for event in events
            if event.event_type == "device_action"
        ],
        condition_events=[
            event for event in events if event.event_type == "skill_condition"
        ],
    )


@pytest.mark.parametrize("mode", [0, 1])
@pytest.mark.parametrize("no_speedup", [False, True])
def test_registered_conditional_job_preserves_hand_check_timing(
    monkeypatch, mode, no_speedup
):
    outcome = _run_conditional_job(
        monkeypatch, mode=mode, no_speedup=no_speedup, checks=[1]
    )

    assert outcome.result.status == JobStatus.SUCCEEDED, outcome.result.error
    skill_roles = []
    if mode:
        skill_roles.append("servant_skill_1")
        if not no_speedup:
            skill_roles.extend(("skill_animation_skip_1", "skill_animation_skip_2"))
    assert outcome.roles == [
        "condition_attack",
        "condition_back",
        *skill_roles,
        "attack",
        "face_card_1",
        "face_card_2",
        "face_card_3",
    ]
    expected_taps = 6 if not mode else 7 if no_speedup else 9
    assert outcome.result.result["tap_count"] == expected_taps
    assert len([entry for entry in outcome.trace if entry[0] == "tap"]) == expected_taps
    assert outcome.cards.calls == 1
    assert len(outcome.condition_events) == 1
    assert outcome.condition_events[0].data["matched"] is True
    assert outcome.trace[:9] == [
        ("snapshot", "battle"),
        ("tap", 1150, 600),
        ("sleep", 0.013),
        ("snapshot", "cards"),
        ("sleep", 0.037),
        ("snapshot", "cards"),
        ("recognize",),
        ("tap", 1250, 683),
        ("sleep", 0.013),
    ]
    if mode:
        assert outcome.trace.index(("tap", 1250, 683)) < outcome.trace.index(
            ("tap", 70, 590)
        )
    else:
        assert ("tap", 70, 590) not in outcome.trace


@pytest.mark.parametrize("checks", [[], [0]], ids=["empty", "all-zero"])
def test_registered_conditional_job_without_card_checks_skips_hand_inspection(
    monkeypatch, checks
):
    outcome = _run_conditional_job(
        monkeypatch, mode=1, no_speedup=True, checks=checks
    )

    assert outcome.result.status == JobStatus.SUCCEEDED, outcome.result.error
    assert outcome.roles == [
        "servant_skill_1",
        "attack",
        "face_card_1",
        "face_card_2",
        "face_card_3",
    ]
    assert outcome.result.result["tap_count"] == 5
    assert outcome.cards.calls == 0
    assert outcome.condition_events == []
    assert ("tap", 1250, 683) not in outcome.trace
    assert ("sleep", 0.037) in outcome.trace
