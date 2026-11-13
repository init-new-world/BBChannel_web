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
        stuck_restart: bool = False,
        check_stuck_interval: float = 30,
        screen_rotation: int | None = None,
    ) -> None:
        self.before = before
        self.after = after
        self.clear_ap = clear_ap
        self.first_battle_set = first_battle_set
        self.game_crash_restart = game_crash_restart
        self.stuck_restart = stuck_restart
        self.check_stuck_interval = check_stuck_interval
        self.screen_rotation = screen_rotation

    def get_setting_plan(self, _name: str):
        return {
            "screen_rotation": self.screen_rotation,
            "run": {
                "interval_before_fight": self.before,
                "interval_after_fight": self.after,
                "clear_ap": self.clear_ap,
                "first_battle_set": self.first_battle_set,
                "game_crash_restart": self.game_crash_restart,
                "stuck_restart": self.stuck_restart,
                "check_stuck_interval": self.check_stuck_interval,
            },
        }


class _Context:
    def __init__(self) -> None:
        self.trace: list[str | tuple[str, float]] = []

    def checkpoint(self, step, **_options):
        self.trace.append(step)

    def sleep(self, seconds):
        self.trace.append(("sleep", seconds))


def test_full_run_rejects_invalid_script_before_starting_a_stage():
    class InvalidScript:
        def get_setting_plan(self, name):
            return {"run": {}, "validation": {"ok": False, "errors": [
                {"code": "missing_assist_tag", "message": "Missing tag"},
            ]}}

    calls = []

    def stage(*args):
        calls.append(args)

    handler = create_full_run_handler(InvalidScript(), stage, stage, stage, stage)
    with pytest.raises(ValueError, match="validation"):
        handler(_Context(), {"setting_name": "demo"})
    assert calls == []


@pytest.mark.parametrize("special_filter,mode", [("unknown", "仅从者"), ("arts", "仅礼装")])
def test_full_run_validates_assist_filter_before_any_stage(special_filter, mode):
    class ScriptData:
        def get_setting_plan(self, name):
            return {"run": {}, "assist": {"mode": mode}}

    calls = []

    def stage(*args):
        calls.append(args)

    handler = create_full_run_handler(ScriptData(), stage, stage, stage, stage)
    with pytest.raises(ValueError, match="special_filter"):
        handler(_Context(), {"setting_name": "demo", "assist": {"special_filter": special_filter}})
    assert calls == []


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


def test_full_run_does_not_apply_operation_delays_at_battle_boundaries():
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
        "run.execute_battle",
        "battle",
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


def test_full_run_stops_clear_ap_when_assist_reports_ap_empty():
    assist_payloads: list[dict] = []
    prepare_calls = 0

    def assist(_context, payload):
        assist_payloads.append(dict(payload))
        if len(assist_payloads) == 2:
            return {"ready": False, "reason": "ap_empty"}
        return {"selected": "support"}

    def prepare(_context, _payload):
        nonlocal prepare_calls
        prepare_calls += 1
        return {"ready": True}

    handler = create_full_run_handler(
        _ScriptData(clear_ap=True),
        assist,
        prepare,
        lambda _context, _payload: {"executed": True},
        lambda _context, payload: {
            "complete": True,
            "repeated": payload["repeat"],
            "drop_count": 0,
        },
    )

    result = handler(
        _Context(),
        {
            "setting_name": "demo",
            "max_runs": 1,
            "max_clear_runs": 2,
            "assist": {"recover_ap": True},
            "prepare": {"apple": "silver"},
        },
    )

    assert [payload["recover_ap"] for payload in assist_payloads] == [True, False]
    assert [payload["apple"] for payload in assist_payloads] == ["silver", "silver"]
    assert prepare_calls == 1
    assert result["runs_completed"] == 1
    assert result["cleared_ap"] is True
    assert result["stopped"] is False
    assert result["reason"] == "ap_cleared"


@pytest.mark.parametrize("max_clear_runs", [1, 2])
def test_clear_ap_obeys_additional_run_bound_without_recovery(max_clear_runs):
    assist_payloads = []
    prepare_payloads = []
    completion_payloads = []

    def assist(_context, payload):
        assist_payloads.append(dict(payload))
        return {"ready": True}

    def prepare(_context, payload):
        prepare_payloads.append(dict(payload))
        return {"ready": True}

    def complete(_context, payload):
        completion_payloads.append(dict(payload))
        return {"complete": True}

    handler = create_full_run_handler(
        _ScriptData(clear_ap=True), assist, prepare,
        lambda _context, _payload: {"executed": True}, complete,
    )
    result = handler(_Context(), {"setting_name": "demo", "max_runs": 1, "max_clear_runs": max_clear_runs})

    assert result["runs_completed"] == max_clear_runs + 1
    assert result["stopped"] is True
    assert result["cleared_ap"] is False
    assert result["reason"] == "clear_ap_limit"
    assert [payload["recover_ap"] for payload in assist_payloads] == [True, *[False] * max_clear_runs]
    assert [payload["recover_ap"] for payload in prepare_payloads] == [True, *[False] * max_clear_runs]
    assert [payload["repeat"] for payload in completion_payloads] == [*[True] * max_clear_runs, False]


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


def test_full_run_enters_main_story_before_starting_battle_flow(tmp_path: Path):
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
            enter_main_story=stage(
                "enter_main_story",
                {"entered": True, "stage": "prepare", "reason": None},
            ),
        )
        job = manager.start(
            FULL_RUN_JOB_KIND,
            {
                "setting_name": "demo",
                "max_runs": 1,
                "entry_mode": "main_story",
                "entry": {"max_map_swipes": 6},
            },
            device_key="replay:demo",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["runs_completed"] == 1
    assert result.result["entry"]["stage"] == "prepare"
    assert [name for name, _payload in calls] == [
        "enter_main_story",
        "prepare",
        "battle",
        "complete",
    ]
    assert calls[0][1] == {"max_map_swipes": 6, "setting_name": "demo"}


def test_full_run_enters_interlude_before_starting_battle_flow(tmp_path: Path):
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
            enter_interlude=stage(
                "enter_interlude",
                {"entered": True, "stage": "assist", "reason": None},
            ),
        )
        job = manager.start(
            FULL_RUN_JOB_KIND,
            {
                "setting_name": "demo",
                "max_runs": 1,
                "entry_mode": "interlude",
                "entry": {"max_map_swipes": 4},
            },
            device_key="replay:demo",
        )
        result = manager.wait(job.job_id, timeout=3)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["runs_completed"] == 1
    assert result.result["entry"]["stage"] == "assist"
    assert [name for name, _payload in calls] == [
        "enter_interlude",
        "assist",
        "prepare",
        "battle",
        "complete",
    ]
    assert calls[0][1] == {"max_map_swipes": 4, "setting_name": "demo"}



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
    battle_payloads: list[dict] = []
    battle_attempts = 0

    def ordinary(name: str, result=None):
        def execute(_context, _payload):
            calls.append(name)
            return dict(result or {})

        return execute

    def battle(_context, payload):
        nonlocal battle_attempts
        calls.append("battle")
        battle_payloads.append(dict(payload))
        battle_attempts += 1
        if battle_attempts == 1:
            raise TimeoutError("battle controls did not recover")
        return {"executed": True}

    handler = create_full_run_handler(
        _ScriptData(first_battle_set=True, game_crash_restart=True),
        ordinary("assist", {"selected": "support"}),
        ordinary("prepare", {"ready": True, "team": "checked"}),
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
    assert [payload["initialize_settings"] for payload in battle_payloads] == [
        True,
        False,
    ]
    assert result["runs"][0]["assist"] == {"selected": "support"}
    assert result["runs"][0]["prepare"] == {
        "ready": True,
        "team": "checked",
    }
    assert result["runs"][0]["battle"] == {"executed": True}
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


def test_full_run_recovers_timeout_when_stuck_watchdog_confirms_freeze():
    calls: list[str] = []
    checked_intervals: list[float] = []
    battle_attempts = 0

    def battle(_context, _payload):
        nonlocal battle_attempts
        calls.append("battle")
        battle_attempts += 1
        if battle_attempts == 1:
            raise TimeoutError("battle frame stopped changing")
        return {"executed": True}

    def recover(_context, _payload):
        calls.append("recover")
        return {"recovered": True, "stage": "battle"}

    def screen_is_stuck(interval: float) -> bool:
        checked_intervals.append(interval)
        return True

    handler = create_full_run_handler(
        _ScriptData(stuck_restart=True, check_stuck_interval=45),
        lambda _context, _payload: calls.append("assist") or {},
        lambda _context, _payload: calls.append("prepare") or {"ready": True},
        battle,
        lambda _context, _payload: calls.append("complete") or {"complete": True},
        recover_game=recover,
        screen_is_stuck=screen_is_stuck,
    )

    result = handler(_Context(), {"setting_name": "demo", "max_restarts": 1})

    assert checked_intervals == [45.0]
    assert calls == ["assist", "prepare", "battle", "recover", "battle", "complete"]
    assert result["restart_count"] == 1
    assert result["recoveries"][0]["trigger_reason"] == "screen_stuck"


def test_full_run_does_not_recover_stuck_timeout_when_frames_changed():
    recovery_calls = 0

    def recover(_context, _payload):
        nonlocal recovery_calls
        recovery_calls += 1
        return {"recovered": True, "stage": "battle"}

    handler = create_full_run_handler(
        _ScriptData(stuck_restart=True, check_stuck_interval=20),
        lambda _context, _payload: {},
        lambda _context, _payload: {"ready": True},
        lambda _context, _payload: (_ for _ in ()).throw(TimeoutError("battle timeout")),
        lambda _context, _payload: {"complete": True},
        recover_game=recover,
        screen_is_stuck=lambda interval: interval == 999,
    )

    with pytest.raises(TimeoutError, match="battle timeout"):
        handler(_Context(), {"setting_name": "demo", "max_restarts": 1})

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


def test_full_run_enters_ooku_and_re_enters_after_main_story_navigation():
    calls: list[tuple[str, dict]] = []
    entry_stages = iter(("assist", "prepare"))

    def enter_main_story(_context, payload):
        calls.append(("enter_main_story", dict(payload)))
        return {"entered": True, "stage": next(entry_stages), "reason": None}

    def stage(name: str):
        def execute(_context, payload):
            calls.append((name, dict(payload)))
            if name == "complete":
                return {
                    "complete": True,
                    "repeated": False,
                    "stopped": True,
                    "reason": "main_story_navigation",
                    "drop_count": 0,
                }
            return {"ready": True, "stage": name}

        return execute

    handler = create_full_run_handler(
        _ScriptData(),
        stage("assist"),
        stage("prepare"),
        stage("battle"),
        stage("complete"),
        enter_main_story=enter_main_story,
    )
    result = handler(
        _Context(),
        {
            "setting_name": "demo",
            "max_runs": 2,
            "entry_mode": "ooku",
            "entry": {"max_map_swipes": 4},
        },
    )

    assert result["runs_completed"] == 2
    assert result["stopped"] is False
    assert [name for name, _payload in calls] == [
        "enter_main_story",
        "assist",
        "prepare",
        "battle",
        "complete",
        "enter_main_story",
        "prepare",
        "battle",
        "complete",
    ]
    assert calls[0][1] == {"max_map_swipes": 4, "setting_name": "demo", "ooku": True}
    assert calls[5][1] == {"max_map_swipes": 4, "setting_name": "demo", "ooku": True}


def test_full_run_propagates_crawl_tower_mode_and_friendship_suppression():
    calls: list[tuple[str, dict]] = []

    def stage(name: str):
        def execute(_context, payload):
            calls.append((name, dict(payload)))
            if name == "complete":
                return {"complete": True, "repeated": False, "drop_count": 0}
            return {"ready": True, "stage": name}

        return execute

    handler = create_full_run_handler(
        _ScriptData(),
        stage("assist"),
        stage("prepare"),
        stage("battle"),
        stage("complete"),
    )
    result = handler(
        _Context(),
        {
            "setting_name": "demo",
            "crawl_tower_mode": "autonomous",
        },
    )

    assert result["runs_completed"] == 1
    by_stage = dict(calls)
    assert by_stage["prepare"]["crawl_tower"] is True
    assert by_stage["battle"]["crawl_tower_mode"] == "autonomous"
    assert by_stage["complete"]["ignore_full_friendship"] is True


def test_full_run_resumes_at_prepare_when_completion_returns_prepare_next_stage():
    calls: list[str] = []

    def stage(name: str):
        def execute(_context, _payload):
            calls.append(name)
            if name == "complete":
                return {
                    "complete": True,
                    "repeated": True,
                    "next_stage": "prepare",
                    "drop_count": 0,
                }
            return {"ready": True, "stage": name}

        return execute

    handler = create_full_run_handler(
        _ScriptData(),
        stage("assist"),
        stage("prepare"),
        stage("battle"),
        stage("complete"),
    )
    result = handler(
        _Context(),
        {
            "setting_name": "demo",
            "max_runs": 2,
        },
    )

    assert result["runs_completed"] == 2
    assert calls == [
        "assist",
        "prepare",
        "battle",
        "complete",
        "prepare",
        "battle",
        "complete",
    ]


def test_full_run_applies_configured_screen_rotation_before_execution():
    applied: list[int | None] = []

    def stage(_context, _payload):
        return {"complete": True, "repeated": False, "drop_count": 0}

    handler = create_full_run_handler(
        _ScriptData(screen_rotation=180),
        stage,
        stage,
        stage,
        stage,
        apply_screen_rotation=applied.append,
    )
    handler(_Context(), {"setting_name": "demo"})

    handler_without_rotation = create_full_run_handler(
        _ScriptData(screen_rotation=None),
        stage,
        stage,
        stage,
        stage,
        apply_screen_rotation=applied.append,
    )
    handler_without_rotation(_Context(), {"setting_name": "demo"})

    assert applied == [180]



