import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from webapp.app import create_app
from webapp.automation.diagnostic import DIAGNOSTIC_JOB_KIND, register_diagnostic_job
from webapp.devices.replay import ReplayBackend
from webapp.runtime import JobDatabase, JobManager, JobStatus
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService


def _write_image(path: Path, image) -> None:
    assert cv2.imwrite(str(path), image)


def _fixture(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    replay_root = tmp_path / "replays"
    session = replay_root / "recording-1"
    assets.mkdir()
    data.mkdir()
    session.mkdir(parents=True)

    target = np.zeros((8, 8, 3), dtype=np.uint8)
    target[1:7, 1:7] = (30, 180, 240)
    target[3:5, :] = (255, 255, 255)
    verified = np.zeros((6, 10, 3), dtype=np.uint8)
    verified[:, 2:8] = (180, 60, 210)
    verified[2:4, :] = (255, 255, 255)

    first = np.zeros((40, 50, 3), dtype=np.uint8)
    first[10:18, 12:20] = target
    second = np.zeros((40, 50, 3), dtype=np.uint8)
    second[22:28, 30:40] = verified

    _write_image(assets / "target.png", target)
    _write_image(assets / "verified.png", verified)
    _write_image(session / "0.png", first)
    _write_image(session / "1.png", second)
    (session / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "device_id": "recording-1",
                "name": "Diagnostic recording",
                "frames": [
                    {
                        "file": "0.png",
                        "expect": {"type": "tap", "x": 16, "y": 14},
                    },
                    {"file": "1.png"},
                ],
            }
        ),
        encoding="utf-8",
    )

    event_log = EventLog()
    device_service = DeviceService([ReplayBackend(replay_root)], event_log)
    device_service.connect("replay", "recording-1")
    resources = ResourceService(assets, data)
    return assets, data, device_service, RecognitionService(resources)


def test_diagnostic_job_matches_taps_and_verifies_next_frame(tmp_path: Path):
    _assets, _data, device_service, recognition = _fixture(tmp_path)
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_diagnostic_job(manager, device_service, recognition)
        job = manager.start(
            DIAGNOSTIC_JOB_KIND,
            {
                "template_path": "target.png",
                "verify_template_path": "verified.png",
                "poll_interval": 0.05,
            },
            device_key="replay:recording-1",
        )
        result = manager.wait(job.job_id, timeout=2)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["tapped"] is True
    assert result.result["match"]["center"] == [16, 14]
    assert result.result["verification"]["matched"] is True
    event_types = [event.event_type for event in manager.database.list_events(job.job_id)]
    assert event_types.count("recognition") == 2
    assert "device_action" in event_types


def test_diagnostic_api_binds_job_to_connected_device(tmp_path: Path):
    assets, data, device_service, _recognition = _fixture(tmp_path)
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        app = create_app(
            assets,
            data,
            device_service=device_service,
            job_manager=manager,
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/jobs",
                json={
                    "kind": DIAGNOSTIC_JOB_KIND,
                    "payload": {"template_path": "target.png"},
                },
            )
            assert response.status_code == 202
            job_id = response.json()["job"]["job_id"]
            result = manager.wait(job_id, timeout=2)

    assert result.device_key == "replay:recording-1"
    assert result.status == JobStatus.SUCCEEDED
