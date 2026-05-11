import pytest

from webapp.core.errors import AppError, ErrorCode
from webapp.core.models import Capability, DeviceInfo, OperationResult
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog


class FakeBackend:
    name = "fake"

    def __init__(self) -> None:
        self.taps: list[tuple[str, int, int]] = []

    def capability(self):
        return Capability(name=self.name, available=True)

    def list_devices(self):
        return [DeviceInfo(backend=self.name, device_id="dev1", name="Fake Device")]

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
