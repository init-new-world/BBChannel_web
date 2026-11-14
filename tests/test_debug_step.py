from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import time

from PIL import Image, ImageDraw
import pytest

from tests.test_client import create_test_client
from webapp.app import create_app
from webapp.core.models import Capability, DeviceInfo, OperationResult
from webapp.devices.coordinates import FrameNormalizer
from webapp.runtime import JobDatabase, JobManager, JobStatus
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog


def _make_scene_and_template() -> tuple[bytes, bytes]:
    scene = Image.new("RGB", (2560, 1440), (24, 30, 42))
    draw = ImageDraw.Draw(scene)
    draw.rectangle([400, 300, 560, 420], fill=(220, 90, 40), outline=(255, 240, 180), width=6)

    normalized_scene = scene.resize((1280, 720), Image.Resampling.BILINEAR)
    template = normalized_scene.crop((200, 150, 280, 210))

    scene_buf = BytesIO()
    scene.save(scene_buf, format="PNG")
    tpl_buf = BytesIO()
    template.save(tpl_buf, format="PNG")
    return scene_buf.getvalue(), tpl_buf.getvalue()


class _FakeDebugBackend:
    def __init__(self, frame: bytes) -> None:
        self.name = "fake"
        self.device_id = "dev-debug"
        self.frame = frame
        self.taps: list[tuple[str, int, int]] = []

    def capability(self) -> Capability:
        return Capability(name=self.name, available=True)

    def list_devices(self) -> list[DeviceInfo]:
        return [
            DeviceInfo(
                backend=self.name,
                device_id=self.device_id,
                name="Fake 2K Device",
                details={"display_size": {"width": 2560, "height": 1440}},
            )
        ]

    def snapshot(self, device_id: str) -> bytes:
        assert device_id == self.device_id
        return self.frame

    def tap(self, device_id: str, x: int, y: int) -> OperationResult:
        self.taps.append((device_id, x, y))
        return OperationResult(ok=True, action="tap", message=f"tap {x},{y}")

    def swipe(self, device_id: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> OperationResult:
        return OperationResult(ok=True, action="swipe", message="swipe")


def _wait_for_paused(manager: JobManager, job_id: str, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if manager.get(job_id).status == JobStatus.PAUSED:
            return
        time.sleep(0.02)
    raise AssertionError(f"Job {job_id} did not enter PAUSED state in time.")


def test_debug_step_pauses_before_tap_writes_bundle_and_resumes_or_cancels(tmp_path: Path):
    pytest.importorskip("cv2")
    scene_png, tpl_png = _make_scene_and_template()
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    (assets / "target.png").write_bytes(tpl_png)

    backend = _FakeDebugBackend(scene_png)
    devices = DeviceService([backend], EventLog(), frame_normalizer=FrameNormalizer())
    devices.connect("fake", "dev-debug")

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        app = create_app(assets, data, device_service=devices, job_manager=manager)
        with create_test_client(app) as client:
            resp = client.post(
                "/api/jobs",
                json={
                    "kind": "diagnostic.template-tap",
                    "payload": {
                        "template_path": "target.png",
                        "threshold": 0.8,
                        "tap_on_match": True,
                        "debug_step": True,
                    },
                },
            )
            assert resp.status_code == 202
            job_id = resp.json()["job"]["job_id"]
            _wait_for_paused(manager, job_id)

            # While paused, no tap has reached the device yet!
            assert backend.taps == []

            debug_dir = tmp_path / "debug" / job_id
            latest = json.loads((debug_dir / "latest.json").read_text(encoding="utf-8"))
            assert latest["step_index"] == 1
            assert latest["paused"] is True
            assert latest["action"]["action"] == "tap"
            assert latest["action"]["logical"] == [240, 180]
            assert latest["action"]["mapped"] == [480, 360]
            assert latest["recognition"]["matched"][0]["template_path"] == "target.png"
            assert Path(latest["raw_screenshot"]).is_file()
            assert Path(latest["annotated_screenshot"]).is_file()

            # Resume allows the pending tap to execute and finish.
            assert client.post(f"/api/jobs/{job_id}/resume").status_code == 200
            completed = manager.wait(job_id, timeout=3)
            assert completed.status == JobStatus.SUCCEEDED
            assert backend.taps == [("dev-debug", 480, 360)]

            # Starting a second job and cancelling while paused never taps the device.
            backend.taps.clear()
            resp2 = client.post(
                "/api/jobs",
                json={
                    "kind": "diagnostic.template-tap",
                    "payload": {
                        "template_path": "target.png",
                        "threshold": 0.8,
                        "tap_on_match": True,
                        "debug_step": True,
                    },
                },
            )
            job2_id = resp2.json()["job"]["job_id"]
            _wait_for_paused(manager, job2_id)
            assert backend.taps == []
            assert client.post(f"/api/jobs/{job2_id}/cancel").status_code == 200
            cancelled = manager.wait(job2_id, timeout=3)
            assert cancelled.status == JobStatus.CANCELLED
            assert backend.taps == []


def test_debug_step_log_mode_writes_bundle_without_pausing(tmp_path: Path):
    pytest.importorskip("cv2")
    scene_png, tpl_png = _make_scene_and_template()
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    (assets / "target.png").write_bytes(tpl_png)

    backend = _FakeDebugBackend(scene_png)
    devices = DeviceService([backend], EventLog(), frame_normalizer=FrameNormalizer())
    devices.connect("fake", "dev-debug")

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        app = create_app(assets, data, device_service=devices, job_manager=manager)
        with create_test_client(app) as client:
            resp = client.post(
                "/api/jobs",
                json={
                    "kind": "diagnostic.template-tap",
                    "payload": {
                        "template_path": "target.png",
                        "threshold": 0.8,
                        "tap_on_match": True,
                        "debug_step": "log",
                    },
                },
            )
            job_id = resp.json()["job"]["job_id"]
            completed = manager.wait(job_id, timeout=3)
            assert completed.status == JobStatus.SUCCEEDED
            assert backend.taps == [("dev-debug", 480, 360)]

            lines = (tmp_path / "debug" / job_id / "steps.jsonl").read_text(encoding="utf-8").splitlines()
            assert len(lines) == 1
            record = json.loads(lines[0])
            assert record["paused"] is False
            assert Path(record["annotated_screenshot"]).is_file()
