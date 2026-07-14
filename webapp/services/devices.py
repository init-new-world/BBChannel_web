from __future__ import annotations

import threading

from webapp.core.errors import AppError, ErrorCode
from webapp.core.models import (
    Capability,
    ConnectionState,
    DeviceEndpoint,
    DeviceInfo,
    OperationResult,
)
from webapp.devices.base import DeviceBackend
from webapp.services.event_log import EventLog


class DeviceService:
    def __init__(self, backends: list[DeviceBackend], event_log: EventLog) -> None:
        self._backends = {backend.name: backend for backend in backends}
        self._event_log = event_log
        self._capture: DeviceEndpoint | None = None
        self._control: DeviceEndpoint | None = None
        self._state_lock = threading.RLock()
        self._endpoint_locks_guard = threading.Lock()
        self._endpoint_locks: dict[str, threading.RLock] = {}

    def state(self) -> ConnectionState:
        with self._state_lock:
            capture = self._capture
            control = self._control
        return ConnectionState(
            connected=capture is not None and control is not None,
            backend=control.backend if control is not None else None,
            device_id=control.device_id if control is not None else None,
            capture=capture,
            control=control,
        )

    def session_key(self) -> str | None:
        state = self.state()
        if not state.connected or state.capture is None or state.control is None:
            return None
        capture_key = _endpoint_key(state.capture)
        control_key = _endpoint_key(state.control)
        if capture_key == control_key:
            return capture_key
        return f"capture={capture_key};control={control_key}"

    def capabilities(self) -> list[Capability]:
        return [backend.capability() for backend in self._backends.values()]

    def list_devices(self) -> list[DeviceInfo]:
        devices: list[DeviceInfo] = []
        for backend in self._backends.values():
            devices.extend(backend.list_devices())
        return devices

    def connect(self, backend_name: str, device_id: str) -> ConnectionState:
        return self.connect_channels(
            capture_backend=backend_name,
            capture_device_id=device_id,
            control_backend=backend_name,
            control_device_id=device_id,
        )

    def connect_channels(
        self,
        *,
        capture_backend: str,
        capture_device_id: str,
        control_backend: str,
        control_device_id: str,
    ) -> ConnectionState:
        capture = self._validate_endpoint(capture_backend, capture_device_id)
        control = self._validate_endpoint(control_backend, control_device_id)
        with self._state_lock:
            self._capture = capture
            self._control = control
        self._event_log.info(
            "connect",
            "Device session connected.",
            {
                "capture": capture.to_dict(),
                "control": control.to_dict(),
            },
        )
        return self.state()

    def connect_adb_endpoint(self, endpoint: str) -> DeviceInfo:
        backend = self._backend_for("adb")
        connect_endpoint = getattr(backend, "connect_endpoint", None)
        if not callable(connect_endpoint):
            raise AppError(
                ErrorCode.ADB_NOT_FOUND,
                "ADB endpoint connection is not supported.",
                {"backend": "adb"},
            )

        device = connect_endpoint(endpoint)
        self._event_log.info(
            "adb_connect_endpoint",
            "ADB endpoint added.",
            {"endpoint": endpoint, "device_id": device.device_id},
        )
        return device

    def disconnect(self) -> ConnectionState:
        previous_state = self.state()
        with self._state_lock:
            self._capture = None
            self._control = None
        if previous_state.capture is not None or previous_state.control is not None:
            self._event_log.info(
                "disconnect",
                "Device session disconnected.",
                {
                    "capture": previous_state.capture.to_dict()
                    if previous_state.capture is not None
                    else None,
                    "control": previous_state.control.to_dict()
                    if previous_state.control is not None
                    else None,
                },
            )
        return self.state()

    def snapshot(self) -> bytes:
        backend, endpoint = self._require_capture()
        with self._lock_for(endpoint):
            try:
                data = backend.snapshot(endpoint.device_id)
            except AppError as exc:
                self._event_log.error("snapshot", exc.message, exc.details)
                raise
        self._event_log.info(
            "snapshot",
            "Screenshot captured.",
            {"backend": endpoint.backend, "device_id": endpoint.device_id},
        )
        return data

    def tap(self, x: int, y: int) -> OperationResult:
        backend, endpoint = self._require_control()
        with self._lock_for(endpoint):
            try:
                result = backend.tap(endpoint.device_id, x, y)
            except AppError as exc:
                self._event_log.error("tap", exc.message, exc.details)
                raise
        self._event_log.info(
            "tap",
            result.message,
            {"backend": endpoint.backend, "device_id": endpoint.device_id, "x": x, "y": y},
        )
        return result

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> OperationResult:
        backend, endpoint = self._require_control()
        with self._lock_for(endpoint):
            try:
                result = backend.swipe(endpoint.device_id, x1, y1, x2, y2, duration_ms)
            except AppError as exc:
                self._event_log.error("swipe", exc.message, exc.details)
                raise
        self._event_log.info(
            "swipe",
            result.message,
            {
                "backend": endpoint.backend,
                "device_id": endpoint.device_id,
                "from": [x1, y1],
                "to": [x2, y2],
                "duration_ms": duration_ms,
            },
        )
        return result

    def _validate_endpoint(self, backend_name: str, device_id: str) -> DeviceEndpoint:
        backend = self._backend_for(backend_name)
        devices = backend.list_devices()
        matching_device = next((device for device in devices if device.device_id == device_id), None)
        if matching_device is None:
            raise AppError(
                ErrorCode.DEVICE_NOT_FOUND,
                "Device was not found.",
                {"backend": backend_name, "device_id": device_id},
            )
        if matching_device.status != "device":
            raise AppError(
                ErrorCode.DEVICE_OFFLINE,
                "Device is not online.",
                {
                    "backend": backend_name,
                    "device_id": device_id,
                    "status": matching_device.status,
                },
            )
        return DeviceEndpoint(backend_name, device_id, matching_device.name)

    def _backend_for(self, backend_name: str) -> DeviceBackend:
        backend = self._backends.get(backend_name)
        if backend is None:
            raise AppError(
                ErrorCode.DEVICE_BACKEND_NOT_FOUND,
                "Device backend was not found.",
                {"backend": backend_name},
            )
        return backend

    def _require_capture(self) -> tuple[DeviceBackend, DeviceEndpoint]:
        with self._state_lock:
            endpoint = self._capture
        if endpoint is None:
            raise AppError(ErrorCode.DEVICE_NOT_CONNECTED, "No capture device is connected.")
        return self._backend_for(endpoint.backend), endpoint

    def _require_control(self) -> tuple[DeviceBackend, DeviceEndpoint]:
        with self._state_lock:
            endpoint = self._control
        if endpoint is None:
            raise AppError(ErrorCode.DEVICE_NOT_CONNECTED, "No control device is connected.")
        return self._backend_for(endpoint.backend), endpoint

    def _lock_for(self, endpoint: DeviceEndpoint) -> threading.RLock:
        key = _endpoint_key(endpoint)
        with self._endpoint_locks_guard:
            return self._endpoint_locks.setdefault(key, threading.RLock())


def _endpoint_key(endpoint: DeviceEndpoint) -> str:
    return f"{endpoint.backend}:{endpoint.device_id}"
