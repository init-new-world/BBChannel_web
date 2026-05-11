from __future__ import annotations

from webapp.core.errors import AppError, ErrorCode
from webapp.core.models import Capability, ConnectionState, DeviceInfo, OperationResult
from webapp.devices.base import DeviceBackend
from webapp.services.event_log import EventLog


class DeviceService:
    def __init__(self, backends: list[DeviceBackend], event_log: EventLog) -> None:
        self._backends = {backend.name: backend for backend in backends}
        self._event_log = event_log
        self._backend_name: str | None = None
        self._device_id: str | None = None

    def state(self) -> ConnectionState:
        return ConnectionState(
            connected=self._backend_name is not None and self._device_id is not None,
            backend=self._backend_name,
            device_id=self._device_id,
        )

    def capabilities(self) -> list[Capability]:
        return [backend.capability() for backend in self._backends.values()]

    def list_devices(self) -> list[DeviceInfo]:
        devices: list[DeviceInfo] = []
        for backend in self._backends.values():
            devices.extend(backend.list_devices())
        return devices

    def connect(self, backend_name: str, device_id: str) -> ConnectionState:
        backend = self._backend_for(backend_name)
        devices = backend.list_devices()
        matching_device = next((device for device in devices if device.device_id == device_id), None)
        if matching_device is None:
            raise AppError(
                ErrorCode.ADB_NO_DEVICES,
                "Device was not found.",
                {"backend": backend_name, "device_id": device_id},
            )
        if matching_device.status != "device":
            raise AppError(
                ErrorCode.ADB_DEVICE_OFFLINE,
                "Device is not online.",
                {
                    "backend": backend_name,
                    "device_id": device_id,
                    "status": matching_device.status,
                },
            )

        self._backend_name = backend_name
        self._device_id = device_id
        self._event_log.info(
            "connect",
            "Device connected.",
            {"backend": backend_name, "device_id": device_id},
        )
        return self.state()

    def disconnect(self) -> ConnectionState:
        previous_state = self.state()
        self._backend_name = None
        self._device_id = None
        if previous_state.connected:
            self._event_log.info(
                "disconnect",
                "Device disconnected.",
                {
                    "backend": previous_state.backend,
                    "device_id": previous_state.device_id,
                },
            )
        return self.state()

    def snapshot(self) -> bytes:
        backend, device_id = self._require_connected()
        try:
            data = backend.snapshot(device_id)
        except AppError as exc:
            self._event_log.error("snapshot", exc.message, exc.details)
            raise
        self._event_log.info("snapshot", "Screenshot captured.", {"device_id": device_id})
        return data

    def tap(self, x: int, y: int) -> OperationResult:
        backend, device_id = self._require_connected()
        try:
            result = backend.tap(device_id, x, y)
        except AppError as exc:
            self._event_log.error("tap", exc.message, exc.details)
            raise
        self._event_log.info("tap", result.message, {"device_id": device_id, "x": x, "y": y})
        return result

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> OperationResult:
        backend, device_id = self._require_connected()
        try:
            result = backend.swipe(device_id, x1, y1, x2, y2, duration_ms)
        except AppError as exc:
            self._event_log.error("swipe", exc.message, exc.details)
            raise
        self._event_log.info(
            "swipe",
            result.message,
            {
                "device_id": device_id,
                "from": [x1, y1],
                "to": [x2, y2],
                "duration_ms": duration_ms,
            },
        )
        return result

    def _backend_for(self, backend_name: str) -> DeviceBackend:
        backend = self._backends.get(backend_name)
        if backend is None:
            raise AppError(
                ErrorCode.ADB_NOT_FOUND,
                "Device backend was not found.",
                {"backend": backend_name},
            )
        return backend

    def _require_connected(self) -> tuple[DeviceBackend, str]:
        state = self.state()
        if not state.connected or state.backend is None or state.device_id is None:
            raise AppError(ErrorCode.DEVICE_NOT_CONNECTED, "No device is connected.")
        return self._backend_for(state.backend), state.device_id
