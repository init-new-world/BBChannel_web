from pathlib import Path

import pytest

from webapp.automation.run import (
    FULL_RUN_JOB_KIND,
    create_full_run_handler,
    register_full_run_job,
)
from webapp.runtime import JobDatabase, JobManager, JobStatus


class _ScriptData:
    def __init__(
        self,
        before: float = 0,
        after: float = 0,
        clear_ap: bool = False,
        first_battle_set: bool = False,
        game_crash_restart: bool = False,
    ) -> None:
        self.before = before
        self.after = after
        self.clear_ap = clear_ap
        self.first_battle_set = first_battle_set
        self.game_crash_restart = game_crash_restart

    def get_setting_plan(self, _name: str):
        return {
            "run": {
                "interval_before_fight": self.before,
                "interval_after_fight": self.after,
                "clear_ap": self.clear_ap,
                "first_battle_set": self.first_battle_set,
                "game_crash_restart": self.game_crash_restart,
            }
        }


class _Context:
    def __init__(self) -> None:
        self.trace: list[str | tuple[str, float]] = []

    def checkpoint(self, step, **_options):
        self.trace.append(step)

    def sleep(self, seconds):
        self.trace.append(("sleep", seconds))


def test_full_run_executes_stages_in_order_and_repeats_until_limit(tmp_path: Path):
    calls: list[tuple[str, dict]] = []

    def stage(name: str):
        def execute(_context, payload):
            calls.append((name, dict(payload)))
            if name == "complete":
                return {
                    "complete": True,
                    "repeated": payload["repeat"],
                    "drop_count": 0,
                }
            return {"stage": name}

        return execute

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_full_run_job(
            manager,
            _ScriptData(first_battle_set=True),
            stage("assist"),
            stage("prepare"),
            stage("battle"),
            stage("complete"),
        )
        job = manager.start(
            FULL_RUN_JOB_KIND,
            {
                "setting_name": "demo",
                "max_runs": 2,
                "prepare": {"team_check_mode": "strict"},
            },
            device_key="replay:demo",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["runs_completed"] == 2
    assert result.result["stopped"] is False
    assert [name for name, _payload in calls] == [
        "assist",
        "prepare",
        "battle",
        "complete",
        "assist",
        "prepare",
        "battle",
        "complete",
    ]
    completion_payloads = [payload for name, payload in calls if name == "complete"]
    assert [payload["repeat"] for payload in completion_payloads] == [True, False]
    battle_payloads = [payload for name, payload in calls if name == "battle"]
    assert [payload["initialize_settings"] for payload in battle_payloads] == [True, False]
    prepare_payloads = [payload for name, payload in calls if name == "prepare"]
    assert [payload["team_check_mode"] for payload in prepare_payloads] == [
        "strict",
        "off",
    ]


def test_full_run_stops_when_completion_requests_it(tmp_path: Path):
    calls: list[str] = []

    def ordinary(name: str):
        def execute(_context, _payload):
            calls.append(name)
            return {"stage": name}

        return execute

    completion_count = 0

    def complete(_context, _payload):
        nonlocal completion_count
        calls.append("complete")
        completion_count += 1
        if completion_count == 2:
            return {
                "complete": False,
                "stopped": True,
                "reason": "drop_limit",
                "drop_count": 3,
            }
        return {"complete": True, "repeated": True, "drop_count": 1}

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_full_run_job(
            manager,
            _ScriptData(),
            ordinary("assist"),
            ordinary("prepare"),
            ordinary("battle"),
            complete,
        )
        job = manager.start(
            FULL_RUN_JOB_KIND,
            {"setting_name": "demo", "max_runs": 5},
            device_key="replay:demo",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["runs_completed"] == 2
    assert result.result["stopped"] is True
    assert result.result["reason"] == "drop_limit"
    assert result.result["drop_count"] == 3
    assert calls == [
        "assist",
        "prepare",
        "battle",
        "complete",
        "assist",
        "prepare",
        "battle",
        "complete",
    ]


def test_full_run_applies_configured_before_and_after_fight_intervals():
    context = _Context()

    def stage(name: str):
        def execute(_context, _payload):
            context.trace.append(name)
            return {"complete": True} if name == "complete" else {}

        return execute

    handler = create_full_run_handler(
        _ScriptData(before=0.2, after=0.3),
        stage("assist"),
        stage("prepare"),
        stage("battle"),
        stage("complete"),
    )
    handler(context, {"setting_name": "demo", "max_runs": 1})

    assert context.trace == [
        "run.select_assist",
        "assist",
        "run.prepare_battle",
        "prepare",
        ("sleep", 0.2),
        "run.execute_battle",
        "battle",
        ("sleep", 0.3),
        "run.complete_battle",
        "complete",
        "complete",
    ]


def test_full_run_clears_remaining_ap_without_consuming_more_items(tmp_path: Path):
    prepare_payloads: list[dict] = []
    completion_payloads: list[dict] = []

    def ordinary(_context, _payload):
        return {}

    def prepare(_context, payload):
        prepare_payloads.append(dict(payload))
        if len(prepare_payloads) == 2:
            return {"ready": False, "reason": "ap_empty"}
        return {"ready": True}

    def complete(_context, payload):
        completion_payloads.append(dict(payload))
        return {"complete": True, "repeated": payload["repeat"], "drop_count": 0}

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_full_run_job(
            manager,
            _ScriptData(clear_ap=True),
            ordinary,
            prepare,
            ordinary,
            complete,
        )
        job = manager.start(
            FULL_RUN_JOB_KIND,
            {"setting_name": "demo", "max_runs": 1, "max_clear_runs": 1},
            device_key="replay:demo",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["runs_completed"] == 1
    assert result.result["cleared_ap"] is True
    assert result.result["stopped"] is False
    assert result.result["reason"] == "ap_cleared"
    assert [payload["recover_ap"] for payload in prepare_payloads] == [True, False]
    assert completion_payloads[0]["repeat"] is True


def test_full_run_resumes_from_an_active_battle(tmp_path: Path):
    calls: list[str] = []

    def stage(name: str, result=None):
        def execute(_context, _payload):
            calls.append(name)
            return dict(result or {})

        return execute

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_full_run_job(
            manager,
            _ScriptData(),
            stage("assist"),
            stage("prepare", {"ready": True}),
            stage("battle"),
            stage("complete", {"complete": True, "drop_count": 0}),
            detect_stage=stage("detect", {"stage": "battle"}),
        )
        job = manager.start(
            FULL_RUN_JOB_KIND,
            {"setting_name": "demo", "max_runs": 1},
            device_key="replay:demo",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["runs_completed"] == 1
    assert calls == ["detect", "battle", "complete"]


def test_full_run_recovers_unknown_initial_stage_when_enabled(tmp_path: Path):
    calls: list[str] = []

    def stage(name: str, result=None):
        def execute(_context, _payload):
            calls.append(name)
            return dict(result or {})

        return execute

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_full_run_job(
            manager,
            _ScriptData(game_crash_restart=True),
            stage("assist"),
            stage("prepare", {"ready": True}),
            stage("battle"),
            stage("complete", {"complete": True, "drop_count": 0}),
            detect_stage=stage("detect", {"stage": "unknown"}),
            recover_game=stage("recover", {"recovered": True, "stage": "battle"}),
        )
        job = manager.start(
            FULL_RUN_JOB_KIND,
            {"setting_name": "demo", "max_runs": 1},
            device_key="replay:demo",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["runs_completed"] == 1
    assert calls == ["detect", "recover", "battle", "complete"]


def test_full_run_enters_free_quest_before_starting_battle_flow(tmp_path: Path):
    calls: list[tuple[str, dict]] = []

    def stage(name: str, result=None):
        def execute(_context, payload):
            calls.append((name, dict(payload)))
            return dict(result or {})

        return execute

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_full_run_job(
            manager,
            _ScriptData(),
            stage("assist"),
            stage("prepare", {"ready": True}),
            stage("battle"),
            stage("complete", {"complete": True, "drop_count": 0}),
            detect_stage=stage("detect", {"stage": "unknown"}),
            enter_free_quest=stage(
                "enter_free_quest",
                {"entered": True, "stage": "assist", "reason": None},
            ),
        )
        job = manager.start(
            FULL_RUN_JOB_KIND,
            {
                "setting_name": "demo",
                "max_runs": 1,
                "entry_mode": "free_quest",
                "entry": {"max_actions": 8},
            },
            device_key="replay:demo",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["runs_completed"] == 1
    assert result.result["entry"]["stage"] == "assist"
    assert [name for name, _payload in calls] == [
        "enter_free_quest",
        "assist",
        "prepare",
        "battle",
        "complete",
    ]
    assert calls[0][1] == {"max_actions": 8, "setting_name": "demo"}


def test_full_run_stops_when_free_quest_entry_cannot_find_a_target(tmp_path: Path):
    calls: list[str] = []

    def unused(name: str):
        def execute(_context, _payload):
            calls.append(name)
            return {}

        return execute

    entry_result = {
        "entered": False,
        "stage": "unknown",
        "reason": "no_visible_free_quest",
        "actions": [],
    }
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_full_run_job(
            manager,
            _ScriptData(),
            unused("assist"),
            unused("prepare"),
            unused("battle"),
            unused("complete"),
            enter_free_quest=lambda _context, _payload: dict(entry_result),
        )
        job = manager.start(
            FULL_RUN_JOB_KIND,
            {"setting_name": "demo", "entry_mode": "free_quest"},
            device_key="replay:demo",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["runs_completed"] == 0
    assert result.result["stopped"] is True
    assert result.result["reason"] == "no_visible_free_quest"
    assert result.result["entry"] == entry_result
    assert calls == []


def test_full_run_recovers_timeout_and_resumes_current_battle_stage():
    calls: list[str] = []
    battle_attempts = 0

    def ordinary(name: str, result=None):
        def execute(_context, _payload):
            calls.append(name)
            return dict(result or {})

        return execute

    def battle(_context, _payload):
        nonlocal battle_attempts
        calls.append("battle")
        battle_attempts += 1
        if battle_attempts == 1:
            raise TimeoutError("battle controls did not recover")
        return {"executed": True}

    handler = create_full_run_handler(
        _ScriptData(game_crash_restart=True),
        ordinary("assist"),
        ordinary("prepare", {"ready": True}),
        battle,
        ordinary("complete", {"complete": True, "drop_count": 0}),
        recover_game=ordinary(
            "recover",
            {"recovered": True, "stage": "battle", "attempts": 2},
        ),
    )

    result = handler(_Context(), {"setting_name": "demo", "max_restarts": 2})

    assert calls == [
        "assist",
        "prepare",
        "battle",
        "recover",
        "battle",
        "complete",
    ]
    assert result["runs_completed"] == 1
    assert result["restart_count"] == 1
    assert result["recoveries"] == [
        {
            "trigger_stage": "battle",
            "error": "battle controls did not recover",
            "recovered": True,
            "stage": "battle",
            "attempts": 2,
        }
    ]


def test_full_run_raises_timeout_after_restart_limit_is_exhausted():
    recovery_calls = 0

    def timeout_battle(_context, _payload):
        raise TimeoutError("battle remains stuck")

    def recover(_context, _payload):
        nonlocal recovery_calls
        recovery_calls += 1
        return {"recovered": True, "stage": "battle"}

    handler = create_full_run_handler(
        _ScriptData(game_crash_restart=True),
        lambda _context, _payload: {},
        lambda _context, _payload: {"ready": True},
        timeout_battle,
        lambda _context, _payload: {"complete": True},
        recover_game=recover,
    )

    with pytest.raises(TimeoutError, match="battle remains stuck"):
        handler(_Context(), {"setting_name": "demo", "max_restarts": 1})

    assert recovery_calls == 1


def test_full_run_does_not_recover_timeout_when_restart_is_disabled():
    recovery_calls = 0

    def timeout_assist(_context, _payload):
        raise TimeoutError("assist remains unavailable")

    def recover(_context, _payload):
        nonlocal recovery_calls
        recovery_calls += 1
        return {"recovered": True, "stage": "assist"}

    handler = create_full_run_handler(
        _ScriptData(game_crash_restart=False),
        timeout_assist,
        lambda _context, _payload: {"ready": True},
        lambda _context, _payload: {},
        lambda _context, _payload: {"complete": True},
        recover_game=recover,
    )

    with pytest.raises(TimeoutError, match="assist remains unavailable"):
        handler(_Context(), {"setting_name": "demo", "max_restarts": 2})

    assert recovery_calls == 0


def test_full_run_rejects_recovery_outside_the_battle_flow():
    def timeout_battle(_context, _payload):
        raise TimeoutError("battle timed out")

    handler = create_full_run_handler(
        _ScriptData(game_crash_restart=True),
        lambda _context, _payload: {},
        lambda _context, _payload: {"ready": True},
        timeout_battle,
        lambda _context, _payload: {"complete": True},
        recover_game=lambda _context, _payload: {
            "recovered": True,
            "stage": "unknown",
        },
    )

    with pytest.raises(
        RuntimeError,
        match="Game recovery did not reach the battle flow",
    ):
        handler(_Context(), {"setting_name": "demo", "max_restarts": 1})


@pytest.mark.parametrize("max_restarts", [-1, 21, True, 1.5])
def test_full_run_validates_restart_limit(max_restarts):
    handler = create_full_run_handler(
        _ScriptData(game_crash_restart=True),
        lambda _context, _payload: {},
        lambda _context, _payload: {"ready": True},
        lambda _context, _payload: {},
        lambda _context, _payload: {"complete": True},
    )

    with pytest.raises(
        ValueError,
        match="max_restarts must be between 0 and 20",
    ):
        handler(
            _Context(),
            {"setting_name": "demo", "max_restarts": max_restarts},
        )
