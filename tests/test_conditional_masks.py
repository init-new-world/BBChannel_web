from copy import deepcopy
from types import SimpleNamespace

import pytest

from tests.test_conditional_execution import (
    _FakeCards,
    _FakeDevice,
    _FakeRecognition,
    _MemoryDatabase,
)
from webapp.automation import battle
from webapp.automation.program import compile_battle_program
from webapp.automation.strategy import select_command_cards
from webapp.runtime import JobManager, JobStatus
from webapp.runtime.jobs import RunContext


def _strategy(card):
    return {
        "card1": {
            "type": 1,
            "cards": [card],
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


def _plan(checks, pool, mode):
    return {
        "name": "conditional-masks",
        "server": "CH",
        "servants": [{"slot": 0, "name": "One", "active": True, "sn": "100"}],
        "run": {
            "first_battle_set": 0,
            "interval_before_choose_card": 0,
            "no_speedup_skill": True,
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
                        "condition": [_strategy(card) for card in pool],
                        "actions": [
                            {"type": "skill", "command": command}
                            for command in (["Start", mode, checks], 1, ["End"])
                        ],
                    }
                ],
            }
        ],
        "validation": {"ok": True, "errors": []},
    }


def _start_control(program):
    return program["rounds"][0]["turns"][0]["actions"][0]["control"]


def _run_mask_job(monkeypatch, *, checks, pool, mode):
    plan = _plan(checks, pool, mode)
    program = compile_battle_program(plan)
    assert program["execution"]["battle"] == {"ready": True, "reason": None}
    trace = []
    cards = _FakeCards(trace)
    selection_batches = []

    def record_selection(strategies, recognized_cards, **options):
        selection_batches.append(
            tuple(strategy["card1"]["cards"][0] for strategy in strategies)
        )
        return select_command_cards(strategies, recognized_cards, **options)

    def record_sleep(context, seconds):
        context.raise_if_cancelled()
        trace.append(("sleep", seconds))

    # Observe the real selector without replacing its selection behavior.
    monkeypatch.setattr(battle, "select_command_cards", record_selection)
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
                    "setting_name": "conditional-masks",
                    "threshold": 0.75,
                    "timeout_seconds": 0.1,
                    "poll_interval": 0.01,
                    "tap_interval_seconds": 0,
                    "initialize_settings": False,
                },
                device_key="fake:conditional-masks",
            )
            result = manager.wait(job.job_id, timeout=2)
        events = database.list_events(job.job_id)
    finally:
        database.connection.close()
    return SimpleNamespace(
        result=result,
        trace=trace,
        cards=cards,
        selection_batches=selection_batches,
        roles=[
            event.data["role"]
            for event in events
            if event.event_type == "device_action"
        ],
        condition_events=[
            event for event in events if event.event_type == "skill_condition"
        ],
    )


def _assert_condition(outcome, *, mode, matched, evaluated, inspected=True):
    assert outcome.result.status == JobStatus.SUCCEEDED, outcome.result.error
    if inspected:
        assert len(outcome.condition_events) == 1
        assert outcome.condition_events[0].data["matched"] is matched
        assert outcome.cards.calls == 1
    else:
        assert outcome.condition_events == []
        assert outcome.cards.calls == 0
    assert outcome.selection_batches == [(card,) for card in evaluated]
    skill_roles = ["servant_skill_1"] if matched == bool(mode) else []
    expected_roles = ["condition_attack", "condition_back"] if inspected else []
    expected_roles.extend(
        [*skill_roles, "attack", "face_card_1", "face_card_2", "face_card_3"]
    )
    assert outcome.roles == expected_roles
    assert outcome.result.result["tap_count"] == len(expected_roles)
    if inspected and skill_roles:
        assert outcome.trace.index(("tap", 1250, 683)) < outcome.trace.index(
            ("tap", 70, 590)
        )


@pytest.mark.parametrize("mode", [0, 1])
@pytest.mark.parametrize(
    ("checks", "pool", "matched", "evaluated"),
    [
        ([0, 1], ["1B", "2A"], True, ["2A"]),
        ([0, 1], ["1B", "1Q"], False, ["1Q"]),
        ([1, 0], ["1Q", "1B"], False, ["1Q"]),
        ([1, 0], ["1B", "2A"], True, ["1B"]),
    ],
    ids=["later-match", "earlier-match-excluded", "later-match-excluded", "first-match"],
)
def test_registered_job_applies_mask_to_original_pool_positions(
    monkeypatch, mode, checks, pool, matched, evaluated
):
    outcome = _run_mask_job(monkeypatch, checks=checks, pool=pool, mode=mode)

    _assert_condition(outcome, mode=mode, matched=matched, evaluated=evaluated)


@pytest.mark.parametrize(
    ("pool", "matched", "evaluated"),
    [
        (["1Q", "2A", "1B"], True, ["1Q", "2A"]),
        (["1B", "2A"], True, ["1B"]),
        (["1Q", "2Q"], False, ["1Q", "2Q"]),
    ],
    ids=["continue-after-miss", "stop-at-first-match", "all-selected-miss"],
)
def test_registered_job_checks_selected_strategies_as_ordered_or(
    monkeypatch, pool, matched, evaluated
):
    outcome = _run_mask_job(
        monkeypatch, checks=[1] * len(pool), pool=pool, mode=1
    )

    _assert_condition(outcome, mode=1, matched=matched, evaluated=evaluated)


@pytest.mark.parametrize(
    "checks",
    [[None, 2], ["", -1], [False, "0"], [[], [0]], [{}, {"enabled": False}]],
    ids=["null-positive", "empty-negative", "false-string-zero", "list", "mapping"],
)
def test_registered_job_uses_legacy_mask_value_truthiness(monkeypatch, checks):
    outcome = _run_mask_job(
        monkeypatch, checks=checks, pool=["1B", "1Q"], mode=1
    )

    _assert_condition(outcome, mode=1, matched=False, evaluated=["1Q"])


@pytest.mark.parametrize("mode", [0, 1])
@pytest.mark.parametrize(
    ("checks", "matched", "evaluated"),
    [([0, 0, 1], False, []), ([0, 1, 0, 1], True, ["2A"])],
    ids=["only-trailing-truthy", "selected-prefix-and-trailing-truthy"],
)
def test_registered_job_ignores_extra_mask_positions_but_preserves_any_gate(
    monkeypatch, mode, checks, matched, evaluated
):
    outcome = _run_mask_job(
        monkeypatch, checks=checks, pool=["1B", "2A"], mode=mode
    )

    _assert_condition(outcome, mode=mode, matched=matched, evaluated=evaluated)


@pytest.mark.parametrize("mode", [0, 1])
@pytest.mark.parametrize(
    "checks",
    [[], [0], [False, None, "", [], {}]],
    ids=["empty", "short-all-zero", "all-falsy"],
)
def test_registered_job_skips_inspection_for_empty_or_all_falsy_mask(
    monkeypatch, mode, checks
):
    outcome = _run_mask_job(
        monkeypatch, checks=checks, pool=["1B", "2A"], mode=mode
    )

    _assert_condition(outcome, mode=mode, matched=True, evaluated=[], inspected=False)


@pytest.mark.parametrize("mode", [0, 1])
def test_registered_job_short_mask_can_match_before_missing_index(monkeypatch, mode):
    outcome = _run_mask_job(
        monkeypatch, checks=[1], pool=["1B", "2A"], mode=mode
    )

    _assert_condition(outcome, mode=mode, matched=True, evaluated=["1B"])


@pytest.mark.parametrize("mode", [0, 1])
def test_registered_job_short_mask_fails_when_missing_index_is_reached(
    monkeypatch, mode
):
    outcome = _run_mask_job(
        monkeypatch, checks=[1], pool=["1Q", "1B"], mode=mode
    )

    assert outcome.result.status == JobStatus.FAILED, outcome.result.result
    assert outcome.result.error["type"] == "IndexError"
    assert outcome.selection_batches == [("1Q",)]
    assert outcome.cards.calls == 1
    assert "servant_skill_1" not in outcome.roles


@pytest.mark.parametrize("mode", [0, 1])
@pytest.mark.parametrize(
    "checks",
    [[], [0], [0, 1], [0, 0, 1], [None, {"legacy": [1]}]],
    ids=["empty", "all-zero", "subset", "trailing-truthy", "nested-legacy"],
)
def test_compiler_preserves_checks_and_existing_check_cards_gate(mode, checks):
    source = _plan(deepcopy(checks), ["1B", "2A"], mode)
    before = deepcopy(source)

    program = compile_battle_program(source)

    assert source == before
    assert program["execution"]["battle"] == {"ready": True, "reason": None}
    control = _start_control(program)
    assert control["type"] == "condition_start"
    assert control["execute_when_matched"] is bool(mode)
    assert control["check_cards"] is (bool(checks) and any(checks))
    assert control["checks"] == checks
    assert control["checks"] is not source["rounds"][0]["turns"][0]["actions"][0]["command"][2]


def test_compiler_deep_copies_nested_legacy_mask_values():
    checks = [0, {"legacy": [1]}]
    source = _plan(checks, ["1B", "2A"], 1)
    program = compile_battle_program(source)
    compiled_checks = _start_control(program)["checks"]

    checks[1]["legacy"].append(2)

    assert compiled_checks == [0, {"legacy": [1]}]
    compiled_checks[1]["legacy"].append(3)
    assert checks == [0, {"legacy": [1, 2]}]
