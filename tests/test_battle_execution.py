import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from webapp.app import create_app
from webapp.automation.battle import register_battle_jobs
from webapp.devices.coordinates import FrameNormalizer
from webapp.devices.replay import ReplayBackend
from webapp.runtime import JobDatabase, JobManager, JobStatus
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog
from webapp.services.script_data import ScriptDataService


def _write_image(path: Path, image) -> None:
    assert cv2.imwrite(str(path), image)


def test_execute_skills_job_recognizes_battle_and_taps_skill_target(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    session = tmp_path / "replays" / "skills"
    (assets / "battle" / "CH").mkdir(parents=True)
    (data / "settings").mkdir(parents=True)
    session.mkdir(parents=True)

    attack = np.zeros((28, 34, 3), dtype=np.uint8)
    attack[2:26, 2:32] = (30, 180, 240)
    attack[8:20, 12:22] = (255, 255, 255)
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame[560:588, 1100:1134] = attack
    _write_image(assets / "battle" / "CH" / "attack.png", attack)
    for index in range(3):
        _write_image(session / f"{index}.png", frame)

    (session / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "device_id": "skills",
                "frames": [
                    {"file": "0.png", "expect": {"type": "tap", "x": 474, "y": 590}},
                    {"file": "1.png", "expect": {"type": "tap", "x": 640, "y": 440}},
                    {"file": "2.png"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Servant A": {"other_name": []}}),
        encoding="utf-8",
    )
    (data / "settings" / "demo.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Servant A",
                "round1_turns": 1,
                "round1_turn0_skill": [[5, 2]],
            }
        ),
        encoding="utf-8",
    )

    event_log = EventLog()
    devices = DeviceService(
        [ReplayBackend(tmp_path / "replays")],
        event_log,
        frame_normalizer=FrameNormalizer(),
    )
    devices.connect("replay", "skills")
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        app = create_app(
            assets,
            data,
            device_service=devices,
            event_log=event_log,
            job_manager=manager,
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/jobs",
                json={
                    "kind": "battle.execute-skills",
                    "payload": {
                        "setting_name": "demo",
                        "timeout_seconds": 1,
                        "poll_interval": 0.01,
                        "tap_interval_seconds": 0,
                    },
                },
            )
            assert response.status_code == 202
            job_id = response.json()["job"]["job_id"]
            result = manager.wait(job_id, timeout=2)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result == {
        "setting_name": "demo",
        "action_count": 1,
        "tap_count": 2,
    }
    events = manager.database.list_events(job_id)
    assert [event.data["role"] for event in events if event.event_type == "device_action"] == [
        "servant_skill_5",
        "skill_target_2",
    ]


def test_execute_skills_rejects_np_before_snapshot_or_tap(tmp_path: Path):
    data = tmp_path / "data"
    (data / "settings").mkdir(parents=True)
    (data / "servant_info_CH.json").write_text(
        json.dumps({"Servant A": {"other_name": []}}),
        encoding="utf-8",
    )
    (data / "settings" / "np.json").write_text(
        json.dumps(
            {
                "server": "CH",
                "servant_0_name": "Servant A",
                "round1_turns": 1,
                "round1_turn0_np": [1],
            }
        ),
        encoding="utf-8",
    )
    device_calls = []

    class NoActionDevice:
        def snapshot(self):
            device_calls.append("snapshot")
            raise AssertionError("snapshot must not be called")

        def tap(self, _x, _y):
            device_calls.append("tap")
            raise AssertionError("tap must not be called")

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_battle_jobs(
            manager,
            ScriptDataService(data),
            NoActionDevice(),
            object(),
        )
        job = manager.start(
            "battle.execute-skills",
            {"setting_name": "np"},
            device_key="replay:unused",
        )
        result = manager.wait(job.job_id, timeout=2)

    assert result.status == JobStatus.FAILED
    assert result.error["message"] == "Program contains non-skill actions."
    assert device_calls == []
