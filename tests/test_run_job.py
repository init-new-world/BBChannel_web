from pathlib import Path

from webapp.automation.run import FULL_RUN_JOB_KIND, register_full_run_job
from webapp.runtime import JobDatabase, JobManager, JobStatus


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
