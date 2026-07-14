from pathlib import Path

from webapp.runtime import JobDatabase, JobStatus


def test_database_applies_schema_and_persists_job(tmp_path: Path):
    path = tmp_path / "runtime.db"
    database = JobDatabase(path)

    job = database.create_job(
        "job-1",
        "diagnostic",
        {"template": "battle/CH/attack.png"},
        "adb:emulator-5554",
    )

    assert database.schema_version() == 1
    assert job.status == JobStatus.QUEUED
    assert job.payload == {"template": "battle/CH/attack.png"}
    assert job.device_key == "adb:emulator-5554"
    assert JobDatabase(path).get_job("job-1") == job


def test_database_transitions_job_and_sets_lifecycle_timestamps(tmp_path: Path):
    database = JobDatabase(tmp_path / "runtime.db")
    database.create_job("job-1", "diagnostic", {})

    running = database.transition_job(
        "job-1",
        JobStatus.RUNNING,
        current_step="capture",
        progress=0.25,
    )
    succeeded = database.transition_job(
        "job-1",
        JobStatus.SUCCEEDED,
        current_step="complete",
        progress=1.0,
        result={"matched": True},
    )

    assert running.started_at is not None
    assert running.finished_at is None
    assert succeeded.started_at == running.started_at
    assert succeeded.finished_at is not None
    assert succeeded.result == {"matched": True}


def test_database_lists_jobs_and_incremental_events(tmp_path: Path):
    database = JobDatabase(tmp_path / "runtime.db")
    database.create_job("job-1", "diagnostic", {})
    database.create_job("job-2", "battle", {})
    first = database.append_event("job-1", "step", "Captured screenshot.")
    second = database.append_event(
        "job-1",
        "match",
        "Template matched.",
        data={"confidence": 0.95},
    )

    assert [job.job_id for job in database.list_jobs()] == ["job-2", "job-1"]
    assert database.list_events("job-1", after_id=first.event_id) == [second]


def test_database_recovers_jobs_left_active_by_restart(tmp_path: Path):
    database = JobDatabase(tmp_path / "runtime.db")
    database.create_job("queued", "diagnostic", {})
    database.create_job("running", "diagnostic", {})
    database.transition_job("running", JobStatus.RUNNING)
    database.create_job("complete", "diagnostic", {})
    database.transition_job("complete", JobStatus.SUCCEEDED)

    recovered = JobDatabase(tmp_path / "runtime.db")

    assert recovered.recover_incomplete_jobs() == 2
    assert recovered.get_job("queued").status == JobStatus.FAILED
    assert recovered.get_job("running").error["code"] == "SERVER_RESTARTED"
    assert recovered.get_job("complete").status == JobStatus.SUCCEEDED
    assert recovered.list_events("running")[0].event_type == "job_interrupted"
