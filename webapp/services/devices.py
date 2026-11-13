from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar

from webapp.core.errors import AppError, ErrorCode
from webapp.core.models import (
    Capability,
    ConnectionState,
    DeviceEndpoint,
    DeviceInfo,
    OperationResult,
)
from webapp.devices.base import DeviceBackend
from webapp.devices.coordinates import FrameNormalizer, ScreenTransform
from webapp.services.event_log import EventLog
from webapp.services.frame_watchdog import FrameStabilityTracker


VALID_SCREEN_ROTATIONS = frozenset({0, 90, 180, 270})


class DeviceService:
    def __init__(
        self,
        backends: list[DeviceBackend],
        event_log: EventLog,
        frame_normalizer: FrameNormalizer | None = None,
        frame_watchdog: FrameStabilityTracker | None = None,
    ) -> None:
        self._backends = {backend.name: backend for backend in backends}
        self._event_log = event_log
        self._capture: DeviceEndpoint | None = None
        self._control: DeviceEndpoint | None = None
        self._frame_normalizer = frame_normalizer
        self._frame_watchdog = frame_watchdog or FrameStabilityTracker()
        self._screen_transform: ScreenTransform | None = None
        self._control_transform: ScreenTransform | None = None
        self._initial_control_transform: ScreenTransform | None = None
        self._state_lock = threading.RLock()
        self._endpoint_locks_guard = threading.Lock()
        self._endpoint_locks: dict[str, threading.RLock] = {}
        self._closed = False
        self._operation_timing: ContextVar[tuple[Callable[[float], None], object, object] | None] = ContextVar(
            "device_operation_timing", default=None,
        )

    @contextmanager
    def operation_timing(
        self, sleep: Callable[[float], None], *, before: object = 0, after: object = 0.1,
    ) -> Iterator[None]:
        token = self._operation_timing.set((sleep, before, after))
        try:
            yield
        finally:
            self._operation_timing.reset(token)

    def operation_timing_active(self) -> bool:
        return self._operation_timing.get() is not None

    def _validated_operation_timing(self) -> tuple[Callable[[float], None], float, float] | None:
        timing = self._operation_timing.get()
        if timing is None:
            return None
        sleep, before, after = timing
        # Read-only inspection must not depend on unused legacy timing values.
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 600
               for value in (before, after)):
            raise ValueError("Device operation delays must be numbers between 0 and 600 seconds.")
        return sleep, float(before), max(float(after), 0.1)

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

    def screen_geometry(self) -> dict | None:
        with self._state_lock:
            transform = self._screen_transform
        return transform.to_dict() if transform is not None else None

    def screen_rotation(self) -> dict[str, object]:
        with self._state_lock:
            rotation = self._frame_normalizer.rotation if self._frame_normalizer is not None else None
            geometry = self._screen_transform.to_dict() if self._screen_transform is not None else None
        return {
            "rotation": rotation,
            "geometry": geometry,
        }

    def set_screen_rotation(self, rotation: int | None) -> dict[str, object]:
        if rotation is not None and (
            isinstance(rotation, bool)
            or not isinstance(rotation, int)
            or rotation not in VALID_SCREEN_ROTATIONS
        ):
            raise ValueError("rotation must be null, 0, 90, 180, or 270.")
        if self._frame_normalizer is None:
            raise AppError(
                ErrorCode.SCREEN_GEOMETRY_UNAVAILABLE,
                "Frame normalization is not configured.",
            )
        with self._state_lock:
            self._frame_normalizer.rotation = rotation
            self._screen_transform = None
            if _same_endpoint(self._capture, self._control):
                self._control_transform = self._initial_control_transform
        self._event_log.info(
            "screen_rotation",
            "Screen rotation updated.",
            {"rotation": rotation},
        )
        return self.screen_rotation()

    def rotate_screen(self, steps: int = 1) -> dict[str, object]:
        if isinstance(steps, bool) or not isinstance(steps, int):
            raise ValueError("steps must be an integer.")
        current = self._frame_normalizer.rotation if self._frame_normalizer is not None else None
        next_degrees = ((current or 0) + steps * 90) % 360
        next_rotation = None if next_degrees == 0 else next_degrees
        return self.set_screen_rotation(next_rotation)

    def capabilities(self) -> list[Capability]:
        return [backend.capability() for backend in self._backends.values()]

    def list_devices(self) -> list[DeviceInfo]:
        devices: list[DeviceInfo] = []
        for backend in self._backends.values():
            devices.extend(backend.list_devices())
        return devices

    def diagnostics(self) -> list[dict]:
        diagnostics: list[dict] = []
        for backend in self._backends.values():
            provider = getattr(backend, "diagnostics", None)
            if callable(provider):
                diagnostics.append(provider())
                continue
            capability = backend.capability()
            diagnostics.append(
                {
                    "backend": backend.name,
                    "available": capability.available,
                    "reason": capability.reason,
                }
            )
        return diagnostics

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
        capture, _capture_info = self._validate_endpoint(capture_backend, capture_device_id)
        control, control_info = self._validate_endpoint(control_backend, control_device_id)
        control_transform = _display_transform(control_info)
        with self._state_lock:
            self._capture = capture
            self._control = control
            self._screen_transform = None
            self._initial_control_transform = control_transform
            self._control_transform = control_transform
        self._frame_watchdog.reset()
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
            self._screen_transform = None
            self._initial_control_transform = None
            self._control_transform = None
        self._frame_watchdog.reset()
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

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        self.disconnect()
        for backend in self._backends.values():
            close_backend = getattr(backend, "close", None)
            if not callable(close_backend):
                continue
            try:
                close_backend()
            except Exception as exc:
                self._event_log.error(
                    "backend_close",
                    "Device backend close failed.",
                    {"backend": backend.name, "error": str(exc)},
                )

    def snapshot(self) -> bytes:
        backend, endpoint = self._require_capture()
        with self._lock_for(endpoint):
            try:
                data = backend.snapshot(endpoint.device_id)
                if self._frame_normalizer is not None:
                    frame = self._frame_normalizer.normalize(data)
                    data = frame.png
                    with self._state_lock:
                        self._screen_transform = frame.transform
                        if _same_endpoint(self._capture, self._control):
                            self._control_transform = frame.transform
            except AppError as exc:
                if self._frame_normalizer is not None:
                    with self._state_lock:
                        self._screen_transform = None
                self._event_log.error("snapshot", exc.message, exc.details)
                raise
        self._frame_watchdog.observe(data)
        self._event_log.info(
            "snapshot",
            "Screenshot captured.",
            {
                "backend": endpoint.backend,
                "device_id": endpoint.device_id,
                "geometry": self.screen_geometry(),
            },
        )
        return data

    def screen_is_stuck(self, minimum_seconds: float) -> bool:
        return self._frame_watchdog.is_stuck(minimum_seconds)

    def tap(self, x: int, y: int) -> OperationResult:
        timing = self._validated_operation_timing()
        if timing is not None:
            timing[0](timing[1])
        backend, endpoint = self._require_control()
        mapped_x, mapped_y = self._map_point(x, y)
        with self._lock_for(endpoint):
            try:
                result = backend.tap(endpoint.device_id, mapped_x, mapped_y)
            except AppError as exc:
                self._event_log.error("tap", exc.message, exc.details)
                raise
        self._event_log.info(
            "tap",
            result.message,
            {
                "backend": endpoint.backend,
                "device_id": endpoint.device_id,
                "requested": [x, y],
                "mapped": [mapped_x, mapped_y],
            },
        )
        if timing is not None:
            timing[0](timing[2])
        return _operation_with_mapping(result, [x, y], [mapped_x, mapped_y])

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> OperationResult:
        timing = self._validated_operation_timing()
        if timing is not None:
            timing[0](timing[1])
        backend, endpoint = self._require_control()
        mapped_start = self._map_point(x1, y1)
        mapped_end = self._map_point(x2, y2)
        with self._lock_for(endpoint):
            try:
                result = backend.swipe(
                    endpoint.device_id,
                    mapped_start[0],
                    mapped_start[1],
                    mapped_end[0],
                    mapped_end[1],
                    duration_ms,
                )
            except AppError as exc:
                self._event_log.error("swipe", exc.message, exc.details)
                raise
        self._event_log.info(
            "swipe",
            result.message,
            {
                "backend": endpoint.backend,
                "device_id": endpoint.device_id,
                "requested": [[x1, y1], [x2, y2]],
                "mapped": [list(mapped_start), list(mapped_end)],
                "duration_ms": duration_ms,
            },
        )
        if timing is not None:
            timing[0](timing[2])
        return _operation_with_mapping(
            result,
            [[x1, y1], [x2, y2]],
            [list(mapped_start), list(mapped_end)],
        )

    def restart_game(self, package_name: str | None = None) -> OperationResult:
        with self._state_lock:
            endpoints = [self._control, self._capture]
        connected = [endpoint for endpoint in endpoints if endpoint is not None]
        if not connected:
            raise AppError(ErrorCode.DEVICE_NOT_CONNECTED, "No device is connected.")

        attempted: set[str] = set()
        for endpoint in connected:
            key = _endpoint_key(endpoint)
            if key in attempted:
                continue
            attempted.add(key)
            backend = self._backend_for(endpoint.backend)
            restart = getattr(backend, "restart_game", None)
            if not callable(restart):
                continue
            with self._lock_for(endpoint):
                result = restart(endpoint.device_id, package_name)
            self._event_log.info(
                "restart_game",
                result.message,
                {
                    "backend": endpoint.backend,
                    "device_id": endpoint.device_id,
                    "package": result.data.get("package"),
                },
            )
            self._frame_watchdog.reset()
            return result

        raise AppError(
            ErrorCode.GAME_RESTART_UNAVAILABLE,
            "Connected device channels do not support restarting the game.",
            {"channels": sorted(attempted)},
        )

    def _validate_endpoint(
        self,
        backend_name: str,
        device_id: str,
    ) -> tuple[DeviceEndpoint, DeviceInfo]:
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
        return DeviceEndpoint(backend_name, device_id, matching_device.name), matching_device

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

    def _map_point(self, x: int, y: int) -> tuple[int, int]:
        with self._state_lock:
            transform = self._control_transform or self._screen_transform
        if transform is None:
            if self._frame_normalizer is not None:
                raise AppError(
                    ErrorCode.SCREEN_GEOMETRY_UNAVAILABLE,
                    "Capture a screenshot before sending mapped device actions.",
                )
            return x, y
        return transform.logical_to_raw(x, y)


def _display_transform(device: DeviceInfo) -> ScreenTransform | None:
    display_size = device.details.get("display_size")
    if not isinstance(display_size, Mapping):
        return None
    width = display_size.get("width")
    height = display_size.get("height")
    if isinstance(width, bool) or isinstance(height, bool):
        return None
    if not isinstance(width, int) or not isinstance(height, int):
        return None
    if width <= 0 or height <= 0:
        return None
    return ScreenTransform.fit(width, height)


def _endpoint_key(endpoint: DeviceEndpoint) -> str:
    return f"{endpoint.backend}:{endpoint.device_id}"


def _same_endpoint(
    first: DeviceEndpoint | None,
    second: DeviceEndpoint | None,
) -> bool:
    return (
        first is not None
        and second is not None
        and _endpoint_key(first) == _endpoint_key(second)
    )


def _operation_with_mapping(
    result: OperationResult,
    requested: list,
    mapped: list,
) -> OperationResult:
    return OperationResult(
        ok=result.ok,
        action=result.action,
        message=result.message,
        data={**result.data, "requested": requested, "mapped": mapped},
    )
