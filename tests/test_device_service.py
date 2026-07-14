import threading
from io import BytesIO

import pytest
from PIL import Image

from webapp.core.errors import AppError, ErrorCode
from webapp.core.models import Capability, DeviceInfo, OperationResult
from webapp.devices.coordinates import FrameNormalizer
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog


class FakeBackend:
    def __init__(self, name: str = "fake", device_id: str = "dev1") -> None:
        self.name = name
        self.device_id = device_id
        self.taps: list[tuple[str, int, int]] = []

    def capability(self):
        return Capability(name=self.name, available=True)

    def list_devices(self):
        return [DeviceInfo(backend=self.name, device_id=self.device_id, name="Fake Device")]

    def snapshot(self, device_id):
        return b"png"

    def tap(self, device_id, x, y):
        self.taps.append((device_id, x, y))
        return OperationResult(ok=True, action="tap", message="tap")

    def swipe(self, device_id, x1, y1, x2, y2, duration_ms):
        return OperationResult(ok=True, action="swipe", message="swipe")


def test_device_service_aggregates_capabilities():
    service = DeviceService([FakeBackend()], EventLog())

    assert service.capabilities()[0].to_dict()["name"] == "fake"


def test_device_service_rejects_snapshot_when_disconnected():
    service = DeviceService([FakeBackend()], EventLog())

    with pytest.raises(AppError) as excinfo:
        service.snapshot()

    assert excinfo.value.code == ErrorCode.DEVICE_NOT_CONNECTED


def test_device_service_connects_and_disconnects():
    service = DeviceService([FakeBackend()], EventLog())

    connected = service.connect("fake", "dev1")
    disconnected = service.disconnect()

    assert connected.connected is True
    assert connected.backend == "fake"
    assert disconnected.connected is False


def test_device_service_delegates_tap_to_connected_backend():
    backend = FakeBackend()
    service = DeviceService([backend], EventLog())

    service.connect("fake", "dev1")
    result = service.tap(10, 20)

    assert result.ok is True
    assert backend.taps == [("dev1", 10, 20)]


def test_device_service_can_use_separate_capture_and_control_channels():
    capture = FakeBackend("capture", "screen-1")
    control = FakeBackend("control", "touch-1")
    service = DeviceService([capture, control], EventLog())

    state = service.connect_channels(
        capture_backend="capture",
        capture_device_id="screen-1",
        control_backend="control",
        control_device_id="touch-1",
    )

    assert state.capture.backend == "capture"
    assert state.control.backend == "control"
    assert state.backend == "control"
    assert service.session_key() == "capture=capture:screen-1;control=control:touch-1"
    assert service.snapshot() == b"png"
    service.tap(10, 20)
    assert control.taps == [("touch-1", 10, 20)]
    assert capture.taps == []


def test_same_endpoint_serializes_snapshot_and_tap():
    snapshot_started = threading.Event()
    release_snapshot = threading.Event()
    tap_started = threading.Event()

    class BlockingBackend(FakeBackend):
        def snapshot(self, device_id):
            snapshot_started.set()
            assert release_snapshot.wait(timeout=2)
            return b"png"

        def tap(self, device_id, x, y):
            tap_started.set()
            return super().tap(device_id, x, y)

    backend = BlockingBackend()
    service = DeviceService([backend], EventLog())
    service.connect("fake", "dev1")

    snapshot_thread = threading.Thread(target=service.snapshot)
    tap_thread = threading.Thread(target=lambda: service.tap(1, 2))
    snapshot_thread.start()
    assert snapshot_started.wait(timeout=2)
    tap_thread.start()
    assert not tap_started.wait(timeout=0.2)
    release_snapshot.set()
    snapshot_thread.join(timeout=2)
    tap_thread.join(timeout=2)

    assert tap_started.is_set()
    assert not snapshot_thread.is_alive()
    assert not tap_thread.is_alive()


def test_different_endpoints_allow_snapshot_and_tap_concurrently():
    snapshot_started = threading.Event()
    release_snapshot = threading.Event()
    tap_started = threading.Event()

    class CaptureBackend(FakeBackend):
        def snapshot(self, device_id):
            snapshot_started.set()
            assert release_snapshot.wait(timeout=2)
            return b"png"

    class ControlBackend(FakeBackend):
        def tap(self, device_id, x, y):
            tap_started.set()
            return super().tap(device_id, x, y)

    capture = CaptureBackend("capture", "screen-1")
    control = ControlBackend("control", "touch-1")
    service = DeviceService([capture, control], EventLog())
    service.connect_channels(
        capture_backend="capture",
        capture_device_id="screen-1",
        control_backend="control",
        control_device_id="touch-1",
    )

    snapshot_thread = threading.Thread(target=service.snapshot)
    snapshot_thread.start()
    assert snapshot_started.wait(timeout=2)
    service.tap(1, 2)
    assert tap_started.is_set()
    release_snapshot.set()
    snapshot_thread.join(timeout=2)
    assert not snapshot_thread.is_alive()


def test_device_service_normalizes_frame_and_maps_actions_to_raw_screen():
    class ImageBackend(FakeBackend):
        def __init__(self):
            super().__init__()
            self.swipes = []

        def snapshot(self, device_id):
            image = Image.new("RGB", (2400, 1080), (20, 40, 60))
            output = BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()

        def swipe(self, device_id, x1, y1, x2, y2, duration_ms):
            self.swipes.append((device_id, x1, y1, x2, y2, duration_ms))
            return OperationResult(ok=True, action="swipe", message="swipe")

    backend = ImageBackend()
    service = DeviceService([backend], EventLog(), frame_normalizer=FrameNormalizer())
    service.connect("fake", "dev1")

    with pytest.raises(AppError) as exc_info:
        service.tap(0, 360)
    assert exc_info.value.code == ErrorCode.SCREEN_GEOMETRY_UNAVAILABLE

    screenshot = service.snapshot()
    with Image.open(BytesIO(screenshot)) as image:
        assert image.size == (1280, 720)
    assert service.screen_geometry()["content"] == {
        "x": 240,
        "y": 0,
        "width": 1920,
        "height": 1080,
    }

    tap_result = service.tap(0, 360)
    swipe_result = service.swipe(0, 0, 1280, 720, 300)

    assert backend.taps == [("dev1", 240, 540)]
    assert backend.swipes == [("dev1", 240, 0, 2160, 1079, 300)]
    assert tap_result.data["mapped"] == [240, 540]
    assert swipe_result.data["mapped"] == [[240, 0], [2160, 1079]]
