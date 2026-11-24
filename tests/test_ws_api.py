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
        self.swipes: list[tuple[str, int, int, int, int, int]] = []
        self.touch_events: list[tuple[str, str, int, int]] = []

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
        self.swipes.append((device_id, x1, y1, x2, y2, duration_ms))
        self.frame = _make_png((50, 180, 90))
        return OperationResult(ok=True, action="swipe", message="swipe")

    def touch_down(self, device_id: str, x: int, y: int) -> OperationResult:
        self.touch_events.append(("down", device_id, x, y))
        self.frame = _make_png((180, 140, 40))
        return OperationResult(ok=True, action="touch_down", message=f"down {x},{y}")

    def touch_move(self, device_id: str, x: int, y: int) -> OperationResult:
        self.touch_events.append(("move", device_id, x, y))
        return OperationResult(ok=True, action="touch_move", message=f"move {x},{y}")

    def touch_up(self, device_id: str, x: int, y: int) -> OperationResult:
        self.touch_events.append(("up", device_id, x, y))
        self.frame = _make_png((90, 90, 200))
        return OperationResult(ok=True, action="touch_up", message=f"up {x},{y}")

    def touch_cancel(self, device_id: str, x: int, y: int) -> OperationResult:
        self.touch_events.append(("cancel", device_id, x, y))
        return OperationResult(ok=True, action="touch_cancel", message=f"cancel {x},{y}")


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
                assert snapshot["connection"]["connected"] is True
                assert snapshot["connection"]["backend"] == "fake"
                assert snapshot["connection"]["device_id"] == "dev-ws"
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


def test_ws_events_snapshot_reflects_device_disconnect_and_reconnect(tmp_path: Path):
    app, _event_log, _backend, device_service, manager = _build_env(tmp_path)
    with manager:
        with create_test_client(app) as client:
            with client.websocket_connect("/api/ws/events?events_limit=10&jobs_limit=10") as ws:
                initial = ws.receive_json()
                assert initial["type"] == "snapshot"
                assert initial["connection"]["connected"] is False
                assert initial["connection"]["backend"] is None
                assert initial["connection"]["device_id"] is None

                device_service.connect("fake", "dev-ws")
                ws.send_json({"type": "refresh"})
                refreshed = None
                for _ in range(10):
                    msg = ws.receive_json()
                    if msg["type"] == "snapshot":
                        refreshed = msg
                        break
                assert refreshed is not None
                assert refreshed["connection"]["connected"] is True
                assert refreshed["connection"]["backend"] == "fake"
                assert refreshed["connection"]["device_id"] == "dev-ws"


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


def test_ws_screen_jpeg_format_and_passive_follow_during_active_job(tmp_path: Path):
    app, _event_log, backend, device_service, manager = _build_env(tmp_path)
    started = threading.Event()
    release = threading.Event()

    with manager:
        device_service.connect("fake", "dev-ws")
        with create_test_client(app) as client:
            # Verify JPEG encoding in idle stream
            with client.websocket_connect("/api/ws/screen?interval_ms=5000&format=jpeg") as ws:
                jpg_frame = ws.receive_bytes()
                assert jpg_frame.startswith(b"\xff\xd8")

            # Verify zero-overhead passive broadcast during active job when follow_jobs=true
            def job_worker(_context, _payload):
                started.set()
                assert release.wait(timeout=3)
                device_service.snapshot()
                return {"done": True}

            manager.register("ws.follow", job_worker)
            job_id = client.post("/api/jobs", json={"kind": "ws.follow"}).json()["job"]["job_id"]
            assert started.wait(timeout=2)
            snaps_before = backend.snapshots
            try:
                with client.websocket_connect("/api/ws/screen?interval_ms=500&format=jpeg&follow_jobs=true") as ws:
                    release.set()
                    broadcast = ws.receive_bytes()
                    assert broadcast.startswith(b"\xff\xd8")
                    assert backend.snapshots == snaps_before + 1
            finally:
                release.set()
                manager.wait(job_id, timeout=2)


def test_ws_screen_keeps_streaming_via_non_blocking_preview_when_active_job_sleeps(tmp_path: Path):
    app, event_log, backend, device_service, manager = _build_env(tmp_path)
    started = threading.Event()
    release = threading.Event()

    with manager:
        device_service.connect("fake", "dev-ws")

        def sleeping_worker(_context, _payload):
            started.set()
            release.wait(timeout=3)
            return {"done": True}

        manager.register("ws.sleep", sleeping_worker)
        with create_test_client(app) as client:
            job_id = client.post("/api/jobs", json={"kind": "ws.sleep"}).json()["job"]["job_id"]
            assert started.wait(timeout=2)
            events_before = len(event_log.recent(limit=200))
            try:
                with client.websocket_connect(
                    "/api/ws/screen?interval_ms=100&format=jpeg&follow_jobs=true"
                ) as ws:
                    frame = ws.receive_bytes()
                    assert frame.startswith(b"\xff\xd8")
                    assert backend.snapshots >= 1
                    # Preview captures must not spam the EventLog.
                    assert len(event_log.recent(limit=200)) == events_before
            finally:
                release.set()
                manager.wait(job_id, timeout=2)


def test_ws_screen_executes_swipe_and_realtime_touch_with_disconnect_cleanup(tmp_path: Path):
    import json

    app, _event_log, backend, device_service, manager = _build_env(tmp_path)
    with manager:
        device_service.connect("fake", "dev-ws")
        with create_test_client(app) as client:
            # Verify HTTP /api/touch endpoint as well
            resp = client.post("/api/touch", json={"action": "down", "x": 10, "y": 12})
            assert resp.status_code == 200
            assert resp.json()["action"] == "touch_down"
            resp_up = client.post("/api/touch", json={"action": "up", "x": 10, "y": 12})
            assert resp_up.status_code == 200
            assert client.post("/api/touch", json={"action": "bogus", "x": 1, "y": 1}).status_code == 422

            backend.touch_events.clear()
            with client.websocket_connect("/api/ws/screen?interval_ms=5000") as ws:
                first_frame = ws.receive_bytes()
                assert first_frame.startswith(b"\x89PNG\r\n\x1a\n")

                # 1. Swipe over WS
                ws.send_json({"type": "swipe", "x1": 10, "y1": 20, "x2": 50, "y2": 20, "duration_ms": 240})
                got_swipe = False
                for _ in range(6):
                    packet = ws.receive()
                    if packet.get("text") is not None:
                        payload = json.loads(packet["text"])
                        if payload.get("type") == "swipe_result":
                            assert payload["result"]["ok"] is True
                            got_swipe = True
                            break
                assert got_swipe is True
                assert backend.swipes == [("dev-ws", 10, 20, 50, 20, 240)]

                # 2. Live touch_down -> touch_up at a different point (fast flick auto-inserts touch_move!)
                ws.send_json({"type": "touch_down", "x": 12, "y": 15})
                ws.send_json({"type": "touch_up", "x": 44, "y": 18})
                got_down = False
                got_up = False
                for _ in range(10):
                    packet = ws.receive()
                    if packet.get("text") is not None:
                        payload = json.loads(packet["text"])
                        if payload.get("type") == "touch_result" and payload.get("action") == "down":
                            got_down = True
                        elif payload.get("type") == "touch_result" and payload.get("action") == "up":
                            got_up = True
                    if got_down and got_up:
                        break
                assert got_down is True and got_up is True
                assert backend.touch_events == [
                    ("down", "dev-ws", 12, 15),
                    ("move", "dev-ws", 44, 18),
                    ("up", "dev-ws", 44, 18),
                ]

                # 3. Safety net: leave finger held down and abruptly close WS -> server must auto-cancel!
                backend.touch_events.clear()
                ws.send_json({"type": "touch_down", "x": 30, "y": 25})
                for _ in range(6):
                    packet = ws.receive()
                    if packet.get("text") is not None:
                        payload = json.loads(packet["text"])
                        if payload.get("type") == "touch_result" and payload.get("action") == "down":
                            break

            assert ("down", "dev-ws", 30, 25) in backend.touch_events
            assert ("cancel", "dev-ws", 30, 25) in backend.touch_events
