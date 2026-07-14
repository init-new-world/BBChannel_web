import threading
from pathlib import Path

import pytest

from webapp.runtime import JobDatabase, JobManager, JobStateError, JobStatus


def _manager(tmp_path: Path, max_workers: int = 4) -> JobManager:
    return JobManager(JobDatabase(tmp_path / "runtime.db"), max_workers=max_workers)


def test_job_manager_runs_registered_handler_and_persists_result(tmp_path: Path):
    with _manager(tmp_path) as manager:
        def handler(context, payload):
            context.checkpoint("capture", progress=0.5, message="Captured screenshot.")
            return {"echo": payload["value"]}

        manager.register("diagnostic", handler)
        queued = manager.start("diagnostic", {"value": 7})
        result = manager.wait(queued.job_id, timeout=2)

    assert result.status == JobStatus.SUCCEEDED
    assert result.current_step == "capture"
    assert result.result == {"echo": 7}
    assert [event.event_type for event in manager.database.list_events(result.job_id)] == [
        "job_queued",
        "job_started",
        "step",
        "job_succeeded",
    ]


def test_job_manager_marks_handler_exception_as_failed(tmp_path: Path):
    with _manager(tmp_path) as manager:
        def handler(_context, _payload):
            raise ValueError("bad input")

        manager.register("failure", handler)
        job = manager.start("failure")
        result = manager.wait(job.job_id, timeout=2)

    assert result.status == JobStatus.FAILED
    assert result.error == {"type": "ValueError", "message": "bad input"}


def test_job_manager_pauses_and_resumes_cooperative_job(tmp_path: Path):
    reached_checkpoint = threading.Event()
    allow_next_checkpoint = threading.Event()

    with _manager(tmp_path) as manager:
        def handler(context, _payload):
            context.checkpoint("first")
            reached_checkpoint.set()
            assert allow_next_checkpoint.wait(timeout=2)
            context.checkpoint("second")
            return {"done": True}

        manager.register("pausable", handler)
        job = manager.start("pausable")
        assert reached_checkpoint.wait(timeout=2)
        paused = manager.pause(job.job_id)
        allow_next_checkpoint.set()
        assert paused.status == JobStatus.PAUSED
        assert manager.get(job.job_id).status == JobStatus.PAUSED
        resumed = manager.resume(job.job_id)
        result = manager.wait(job.job_id, timeout=2)

    assert resumed.status == JobStatus.RUNNING
    assert result.status == JobStatus.SUCCEEDED


def test_job_manager_cancels_job_waiting_at_checkpoint(tmp_path: Path):
    started = threading.Event()

    with _manager(tmp_path) as manager:
        def handler(context, _payload):
            started.set()
            while True:
                context.sleep(0.05)

        manager.register("loop", handler)
        job = manager.start("loop")
        assert started.wait(timeout=2)
        cancelling = manager.cancel(job.job_id)
        result = manager.wait(job.job_id, timeout=2)

    assert cancelling.status == JobStatus.CANCELLING
    assert result.status == JobStatus.CANCELLED


def test_jobs_with_same_device_key_are_serialized(tmp_path: Path):
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()

    with _manager(tmp_path, max_workers=2) as manager:
        def handler(context, payload):
            if payload["number"] == 1:
                first_started.set()
                assert release_first.wait(timeout=2)
            else:
                second_started.set()
            context.checkpoint("done")

        manager.register("lease", handler)
        first = manager.start("lease", {"number": 1}, device_key="adb:one")
        assert first_started.wait(timeout=2)
        second = manager.start("lease", {"number": 2}, device_key="adb:one")
        assert not second_started.wait(timeout=0.2)
        release_first.set()
        assert second_started.wait(timeout=2)
        assert manager.wait(first.job_id, timeout=2).status == JobStatus.SUCCEEDED
        assert manager.wait(second.job_id, timeout=2).status == JobStatus.SUCCEEDED


def test_queued_job_can_be_cancelled_before_device_lease(tmp_path: Path):
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()

    with _manager(tmp_path, max_workers=2) as manager:
        def handler(_context, payload):
            if payload["number"] == 1:
                first_started.set()
                assert release_first.wait(timeout=2)
            else:
                second_started.set()

        manager.register("lease", handler)
        first = manager.start("lease", {"number": 1}, device_key="adb:one")
        assert first_started.wait(timeout=2)
        second = manager.start("lease", {"number": 2}, device_key="adb:one")
        manager.cancel(second.job_id)
        assert manager.wait(second.job_id, timeout=2).status == JobStatus.CANCELLED
        assert not second_started.is_set()
        release_first.set()
        assert manager.wait(first.job_id, timeout=2).status == JobStatus.SUCCEEDED


def test_job_manager_rejects_unknown_kind_and_invalid_transition(tmp_path: Path):
    with _manager(tmp_path) as manager:
        with pytest.raises(KeyError):
            manager.start("missing")

        manager.register("instant", lambda _context, _payload: None)
        job = manager.start("instant")
        manager.wait(job.job_id, timeout=2)
        with pytest.raises(JobStateError):
            manager.pause(job.job_id)
