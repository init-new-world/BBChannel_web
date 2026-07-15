from pathlib import Path

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
            {"setting_name": "demo", "max_runs": 2},
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
