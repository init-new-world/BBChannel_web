from __future__ import annotations

import threading
from io import BytesIO
from pathlib import Path

from PIL import Image

from tests.test_client import create_test_client
from webapp.app import create_app
from webapp.core.models import Capability, DeviceInfo, OperationResult
from webapp.runtime import JobDatabase, JobManager, JobStatus
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog


def _make_png(color: tuple[int, int, int] = (32, 64, 128)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (64, 36), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeScreenBackend:
    def __init__(self) -> None:
        self.name = "fake"
        self.device_id = "dev-ws"
        self.frame = _make_png((20, 40, 80))
        self.snapshots = 0
        self.taps: list[tuple[str, int, int]] = []

    def capability(self) -> Capability:
        return Capability(name=self.name, available=True)

    def list_devices(self) -> list[DeviceInfo]:
        return [DeviceInfo(backend=self.name, device_id=self.device_id, name="Fake WS Device")]

    def snapshot(self, device_id: str) -> bytes:
        assert device_id == self.device_id
        self.snapshots += 1
        return self.frame

    def tap(self, device_id: str, x: int, y: int) -> OperationResult:
        self.taps.append((device_id, x, y))
        self.frame = _make_png((180, 50, 50))
        return OperationResult(ok=True, action="tap", message=f"tap {x},{y}")

    def swipe(self, device_id: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> OperationResult:
        return OperationResult(ok=True, action="swipe", message="swipe")


def _build_env(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    event_log = EventLog()
    backend = _FakeScreenBackend()
    device_service = DeviceService([backend], event_log)
    manager = JobManager(JobDatabase(tmp_path / "runtime.db"))
    app = create_app(
        assets,
        data,
        event_log=event_log,
        device_service=device_service,
        job_manager=manager,
    )
    return app, event_log, backend, device_service, manager


def test_ws_events_streams_snapshot_logs_and_job_updates(tmp_path: Path):
    app, event_log, _backend, device_service, manager = _build_env(tmp_path)
    with manager:
        def echo_worker(context, payload):
            context.checkpoint("step_1", progress=1.0)
            context.emit("worker_step", "Running step", data={"value": payload["value"]})
            return {"doubled": payload["value"] * 2}

        manager.register("ws.echo", echo_worker)
        device_service.connect("fake", "dev-ws")

        with create_test_client(app) as client:
            with client.websocket_connect("/api/ws/events?events_limit=20&jobs_limit=10") as ws:
                snapshot = ws.receive_json()
                assert snapshot["type"] == "snapshot"
                assert any(item["action"] == "connect" for item in snapshot["events"])
                assert snapshot["jobs"] == []

                ws.send_json({"type": "ping"})
                assert ws.receive_json() == {"type": "pong"}

                event_log.info("custom", "live push", {"ok": True})
                live_event = ws.receive_json()
                assert live_event["type"] == "event"
                assert live_event["event"]["action"] == "custom"
                assert live_event["event"]["message"] == "live push"

                response = client.post("/api/jobs", json={"kind": "ws.echo", "payload": {"value": 21}})
                assert response.status_code == 202
                job_id = response.json()["job"]["job_id"]
                completed = manager.wait(job_id, timeout=2)
                assert completed.status == JobStatus.SUCCEEDED

                ws.send_json({"type": "subscribe_job", "job_id": job_id, "after_id": 0})
                seen_subscribed = False
                seen_succeeded = False
                for _ in range(20):
                    msg = ws.receive_json()
                    if msg["type"] == "job_updated" and msg["job"]["job_id"] == job_id:
                        if msg["job"]["status"] == "succeeded":
                            seen_succeeded = True
                    elif msg["type"] == "job_subscribed" and msg["job"]["job_id"] == job_id:
                        seen_subscribed = True
                        event_types = [evt["event_type"] for evt in msg["events"]]
                        assert "worker_step" in event_types
                        assert "job_succeeded" in event_types
                    if seen_subscribed and seen_succeeded:
                        break

                assert seen_subscribed is True
                assert seen_succeeded is True

                ws.send_json({"type": "unsubscribe_job"})
                for _ in range(10):
                    msg = ws.receive_json()
                    if msg["type"] == "job_unsubscribed":
                        break
                else:
                    raise AssertionError("Expected job_unsubscribed message")


def test_ws_events_pushes_live_job_events_for_subscribed_job(tmp_path: Path):
    app, _event_log, _backend, _device_service, manager = _build_env(tmp_path)
    started = threading.Event()
    release = threading.Event()

    with manager:
        def gated_worker(context, _payload):
            started.set()
            assert release.wait(timeout=2)
            context.emit("custom_marker", "Hello over WS", data={"n": 7})
            return {"ok": True}

        manager.register("ws.gated", gated_worker)
        with create_test_client(app) as client:
            job_id = client.post("/api/jobs", json={"kind": "ws.gated"}).json()["job"]["job_id"]
            assert started.wait(timeout=2)

            with client.websocket_connect(f"/api/ws/events?job_id={job_id}&after_id=0") as ws:
                snapshot = ws.receive_json()
                assert snapshot["type"] == "snapshot"
                assert snapshot["job_id"] == job_id

                release.set()
                assert manager.wait(job_id, timeout=2).status == JobStatus.SUCCEEDED

                pushed_types: list[str] = []
                saw_terminal_update = False
                for _ in range(20):
                    msg = ws.receive_json()
                    if msg["type"] == "job_event" and msg["job_id"] == job_id:
                        pushed_types.append(msg["event"]["event_type"])
                    elif (
                        msg["type"] == "job_updated"
                        and msg["job"]["job_id"] == job_id
                        and msg["job"]["status"] == "succeeded"
                    ):
                        saw_terminal_update = True
                    if "custom_marker" in pushed_types and saw_terminal_update:
                        break

                assert "custom_marker" in pushed_types
                assert saw_terminal_update is True


def test_ws_screen_streams_binary_png_frames_and_executes_tap(tmp_path: Path):
    app, _event_log, backend, device_service, manager = _build_env(tmp_path)
    with manager:
        device_service.connect("fake", "dev-ws")
        with create_test_client(app) as client:
            with client.websocket_connect("/api/ws/screen?interval_ms=5000") as ws:
                first_frame = ws.receive_bytes()
                assert first_frame.startswith(b"\x89PNG\r\n\x1a\n")
                assert backend.snapshots >= 1

                ws.send_json({"type": "refresh"})
                second_frame = ws.receive_bytes()
                assert second_frame.startswith(b"\x89PNG\r\n\x1a\n")
                assert backend.snapshots >= 2

                ws.send_json({"type": "tap", "x": 32, "y": 18})
                got_tap_result = False
                got_updated_frame = False
                for _ in range(6):
                    packet = ws.receive()
                    if packet.get("bytes") is not None:
                        assert packet["bytes"].startswith(b"\x89PNG\r\n\x1a\n")
                        if packet["bytes"] != first_frame:
                            got_updated_frame = True
                    elif packet.get("text") is not None:
                        import json

                        payload = json.loads(packet["text"])
                        if payload.get("type") == "tap_result":
                            assert payload["result"]["ok"] is True
                            got_tap_result = True
                    if got_tap_result and got_updated_frame:
                        break

                assert backend.taps == [("dev-ws", 32, 18)]
                assert got_tap_result is True
                assert got_updated_frame is True


def test_ws_screen_reports_error_when_disconnected_and_pauses_during_active_job(tmp_path: Path):
    app, _event_log, _backend, device_service, manager = _build_env(tmp_path)
    started = threading.Event()
    release = threading.Event()

    with manager:
        with create_test_client(app) as client:
            with client.websocket_connect("/api/ws/screen?interval_ms=500") as ws:
                error_msg = ws.receive_json()
                assert error_msg["type"] == "error"
                assert error_msg["error"]["code"] == "device_not_connected"

            device_service.connect("fake", "dev-ws")

            def hold_worker(_context, _payload):
                started.set()
                release.wait(timeout=2)
                return {"done": True}

            manager.register("ws.hold", hold_worker)
            job_id = client.post("/api/jobs", json={"kind": "ws.hold"}).json()["job"]["job_id"]
            assert started.wait(timeout=2)
            try:
                with client.websocket_connect("/api/ws/screen?interval_ms=500") as ws:
                    paused_msg = ws.receive_json()
                    assert paused_msg == {"type": "paused", "reason": "job_running"}
            finally:
                release.set()
                manager.wait(job_id, timeout=2)
