import json
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

            assert client.get("/api/job-kinds").json() == {
                "kinds": [
                    "assist.select",
                    "battle.complete",
                    "battle.detect-stage",
                    "battle.dry-run",
                    "battle.execute-plan",
                    "battle.execute-skills",
                    "battle.prepare",
                    "battle.run",
                    "diagnostic.template-tap",
                    "echo",
                ]
            }
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


def test_device_job_requires_active_device(tmp_path: Path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        with TestClient(_app(tmp_path, manager)) as client:
            response = client.post(
                "/api/jobs",
                json={
                    "kind": "diagnostic.template-tap",
                    "payload": {"template_path": "target.png"},
                },
            )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "DEVICE_REQUIRED"


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


def test_battle_dry_run_executes_normalized_setting_actions(tmp_path: Path):
    strategy = {
        "card1": {"type": 0, "cards": [1], "criticalStar": 0, "more_or_less": True},
        "card2": {"type": 2, "cards": [], "criticalStar": 0, "more_or_less": True},
        "card3": {"type": 2, "cards": [], "criticalStar": 0, "more_or_less": True},
        "breakpoint": [False, False],
        "colorFirst": True,
    }
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        app = _app(tmp_path, manager)
        data = Path(app.state.resources.data_dir)
        (data / "servant_info_CH.json").write_text(
            json.dumps({"Servant A": {"other_name": []}}),
            encoding="utf-8",
        )
        settings = data / "settings"
        settings.mkdir()
        (settings / "demo.json").write_text(
            json.dumps(
                {
                    "server": "CH",
                    "servant_0_name": "Servant A",
                    "round1_turns": 1,
                    "round1_turn0_skill": [1],
                    "round1_turn0_np": [1],
                    "round1_turn0_strategy": [strategy],
                }
            ),
            encoding="utf-8",
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/jobs",
                json={
                    "kind": "battle.dry-run",
                    "payload": {"setting_name": "demo"},
                },
            )
            assert response.status_code == 202
            job_id = response.json()["job"]["job_id"]
            result = manager.wait(job_id, timeout=2)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result == {
        "setting_name": "demo",
        "round_count": 1,
        "turn_count": 1,
        "action_count": 3,
    }
    battle_events = [
        event
        for event in manager.database.list_events(job_id)
        if event.event_type == "battle_action"
    ]
    assert [event.data["action"]["type"] for event in battle_events] == [
        "skill",
        "np",
        "strategy",
    ]
