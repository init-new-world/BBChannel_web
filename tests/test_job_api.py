import threading
from pathlib import Path

from fastapi.testclient import TestClient

from webapp.app import create_app
from webapp.runtime import JobDatabase, JobManager, JobStatus


def _app(tmp_path: Path, manager: JobManager):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    return create_app(assets, data, job_manager=manager)


def test_job_api_starts_lists_and_reads_completed_job(tmp_path: Path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        manager.register("echo", lambda _context, payload: {"echo": payload["value"]})
        with TestClient(_app(tmp_path, manager)) as client:
            response = client.post("/api/jobs", json={"kind": "echo", "payload": {"value": 9}})
            assert response.status_code == 202
            job_id = response.json()["job"]["job_id"]
            completed = manager.wait(job_id, timeout=2)

            assert client.get("/api/job-kinds").json() == {"kinds": ["echo"]}
            assert client.get(f"/api/jobs/{job_id}").json()["job"]["status"] == "succeeded"
            assert client.get("/api/jobs").json()["jobs"][0]["job_id"] == job_id
            assert completed.result == {"echo": 9}


def test_job_api_controls_running_job_and_reports_events(tmp_path: Path):
    started = threading.Event()

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:

        def loop(context, _payload):
            started.set()
            while True:
                context.sleep(0.05)

        manager.register("loop", loop)
        with TestClient(_app(tmp_path, manager)) as client:
            job_id = client.post("/api/jobs", json={"kind": "loop"}).json()["job"]["job_id"]
            assert started.wait(timeout=2)
            assert client.post(f"/api/jobs/{job_id}/pause").json()["job"]["status"] == "paused"
            assert client.post(f"/api/jobs/{job_id}/resume").json()["job"]["status"] == "running"
            assert client.post(f"/api/jobs/{job_id}/cancel").json()["job"]["status"] == "cancelling"
            assert manager.wait(job_id, timeout=2).status == JobStatus.CANCELLED

            events = client.get(f"/api/jobs/{job_id}/events").json()["events"]
            assert events[-1]["event_type"] == "job_cancelled"


def test_job_api_returns_structured_errors(tmp_path: Path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        with TestClient(_app(tmp_path, manager)) as client:
            unknown = client.post("/api/jobs", json={"kind": "missing"})
            missing = client.get("/api/jobs/not-found")

    assert unknown.status_code == 400
    assert unknown.json()["detail"]["code"] == "UNKNOWN_JOB_KIND"
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "JOB_NOT_FOUND"


def test_job_event_stream_replays_terminal_job_and_closes(tmp_path: Path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        manager.register("instant", lambda context, _payload: context.emit("note", "hello"))
        with TestClient(_app(tmp_path, manager)) as client:
            job_id = client.post("/api/jobs", json={"kind": "instant"}).json()["job"]["job_id"]
            manager.wait(job_id, timeout=2)
            response = client.get(f"/api/jobs/{job_id}/events/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: job_event" in response.text
    assert '\"event_type\":\"note\"' in response.text
