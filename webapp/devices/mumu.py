from __future__ import annotations

import ctypes
import platform
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from threading import RLock
from time import sleep as system_sleep
from typing import Protocol

from PIL import Image

from webapp.core.errors import AppError, ErrorCode
from webapp.core.models import Capability, DeviceInfo, OperationResult


DLL_NAME = "external_renderer_ipc.dll"
DLL_LAYOUTS = (
    Path("shell") / "sdk" / DLL_NAME,
    Path("nx_device") / "12.0" / "shell" / "sdk" / DLL_NAME,
    Path("nx_main") / "sdk" / DLL_NAME,
)


@dataclass(frozen=True)
class MumuNativeFrame:
    width: int
    height: int
    pixels: bytes
    bottom_up: bool = True


class MumuNativeApi(Protocol):
    def is_ready(self) -> bool:
        ...

    def diagnostics(self) -> dict[str, object]:
        ...

    def connect(self, install_path: Path, instance_index: int) -> int:
        ...

    def disconnect(self, handle: int) -> None:
        ...

    def capture_display(self, handle: int, display_id: int) -> MumuNativeFrame:
        ...

    def touch_down(self, handle: int, display_id: int, x: int, y: int) -> None:
        ...

    def touch_up(self, handle: int, display_id: int) -> None:
        ...


class MumuNativeCallError(RuntimeError):
    def __init__(self, function: str, result: object, message: str | None = None) -> None:
        self.function = function
        self.result = result
        super().__init__(message or f"{function} failed with result {result}")


class UnavailableMumuNativeApi:
    def is_ready(self) -> bool:
        return False

    def diagnostics(self) -> dict[str, object]:
        return {
            "library_loaded": False,
            "exports_complete": False,
            "invocation_ready": False,
            "missing_exports": [],
            "native_error": "MuMu native adapter is not initialized.",
        }

    def connect(self, install_path: Path, instance_index: int) -> int:
        raise RuntimeError("MuMu native adapter is not initialized.")

    def disconnect(self, handle: int) -> None:
        return None

    def capture_display(self, handle: int, display_id: int) -> MumuNativeFrame:
        raise RuntimeError("MuMu native adapter is not initialized.")

    def touch_down(self, handle: int, display_id: int, x: int, y: int) -> None:
        raise RuntimeError("MuMu native adapter is not initialized.")

    def touch_up(self, handle: int, display_id: int) -> None:
        raise RuntimeError("MuMu native adapter is not initialized.")


class CtypesMumuNativeApi:
    REQUIRED_EXPORTS = (
        "nemu_connect",
        "nemu_disconnect",
        "nemu_capture_display",
        "nemu_input_event_touch_down",
        "nemu_input_event_touch_up",
    )

    def __init__(
        self,
        dll_path: Path,
        platform_name: str | None = None,
        load_library: Callable[[str], object] = ctypes.CDLL,
        max_frame_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        self.dll_path = dll_path
        self.platform_name = platform_name or platform.system()
        self.max_frame_bytes = max(max_frame_bytes, 1)
        self._dll: object | None = None
        self._missing_exports: list[str] = []
        self._native_error: str | None = None

        if self.platform_name != "Windows":
            self._native_error = "MuMu native IPC can only load on Windows."
            return
        try:
            self._dll = load_library(str(dll_path))
        except Exception as exc:
            self._native_error = f"Unable to load MuMu native library: {exc}"
            return

        self._missing_exports = [
            name for name in self.REQUIRED_EXPORTS if not hasattr(self._dll, name)
        ]
        if self._missing_exports:
            self._native_error = "MuMu native library is missing required exports."
            return
        self._bind_signatures()

    def is_ready(self) -> bool:
        return self._dll is not None and not self._missing_exports and self._native_error is None

    def diagnostics(self) -> dict[str, object]:
        return {
            "library_loaded": self._dll is not None,
            "exports_complete": self._dll is not None and not self._missing_exports,
            "invocation_ready": self.is_ready(),
            "required_exports": list(self.REQUIRED_EXPORTS),
            "missing_exports": list(self._missing_exports),
            "native_error": self._native_error,
            "process_bits": ctypes.sizeof(ctypes.c_void_p) * 8,
        }

    def connect(self, install_path: Path, instance_index: int) -> int:
        dll = self._require_ready()
        handle = dll.nemu_connect(str(install_path.absolute()), instance_index)
        if handle <= 0:
            raise MumuNativeCallError("nemu_connect", handle)
        return handle

    def disconnect(self, handle: int) -> None:
        self._require_ready().nemu_disconnect(handle)

    def capture_display(self, handle: int, display_id: int) -> MumuNativeFrame:
        dll = self._require_ready()
        width = ctypes.c_int(0)
        height = ctypes.c_int(0)
        empty_pixels = (ctypes.c_ubyte * 0)()
        result = dll.nemu_capture_display(
            handle,
            display_id,
            0,
            ctypes.byref(width),
            ctypes.byref(height),
            empty_pixels,
        )
        self._check_zero("nemu_capture_display", result)
        frame_size = self._frame_size(width.value, height.value)

        pixels = (ctypes.c_ubyte * frame_size)()
        result = dll.nemu_capture_display(
            handle,
            display_id,
            frame_size,
            ctypes.byref(width),
            ctypes.byref(height),
            pixels,
        )
        self._check_zero("nemu_capture_display", result)
        if self._frame_size(width.value, height.value) != frame_size:
            raise MumuNativeCallError(
                "nemu_capture_display",
                result,
                "MuMu display dimensions changed during capture.",
            )
        return MumuNativeFrame(
            width=width.value,
            height=height.value,
            pixels=bytes(pixels),
            bottom_up=True,
        )

    def touch_down(self, handle: int, display_id: int, x: int, y: int) -> None:
        result = self._require_ready().nemu_input_event_touch_down(
            handle,
            display_id,
            x,
            y,
        )
        self._check_zero("nemu_input_event_touch_down", result)

    def touch_up(self, handle: int, display_id: int) -> None:
        result = self._require_ready().nemu_input_event_touch_up(handle, display_id)
        self._check_zero("nemu_input_event_touch_up", result)

    def _bind_signatures(self) -> None:
        dll = self._require_library()
        dll.nemu_connect.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
        dll.nemu_connect.restype = ctypes.c_int
        dll.nemu_disconnect.argtypes = [ctypes.c_int]
        dll.nemu_disconnect.restype = None
        dll.nemu_capture_display.argtypes = [
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ubyte),
        ]
        dll.nemu_capture_display.restype = ctypes.c_int
        dll.nemu_input_event_touch_down.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ]
        dll.nemu_input_event_touch_down.restype = ctypes.c_int
        dll.nemu_input_event_touch_up.argtypes = [ctypes.c_int, ctypes.c_int]
        dll.nemu_input_event_touch_up.restype = ctypes.c_int

    def _frame_size(self, width: int, height: int) -> int:
        frame_size = width * height * 4
        if width <= 0 or height <= 0 or frame_size > self.max_frame_bytes:
            raise MumuNativeCallError(
                "nemu_capture_display",
                frame_size,
                f"MuMu frame size is invalid: {width}x{height} ({frame_size} bytes).",
            )
        return frame_size

    def _require_library(self):
        if self._dll is None:
            raise MumuNativeCallError(
                "load_library",
                None,
                self._native_error or "MuMu native library is not loaded.",
            )
        return self._dll

    def _require_ready(self):
        if not self.is_ready():
            raise MumuNativeCallError(
                "native_api",
                None,
                self._native_error or "MuMu native API is not ready.",
            )
        return self._require_library()

    @staticmethod
    def _check_zero(function: str, result: int) -> None:
        if result != 0:
            raise MumuNativeCallError(function, result)


def default_mumu_install_paths() -> list[Path]:
    project_root = Path(__file__).resolve().parents[2]
    package_root = project_root.parent
    paths: list[Path] = []
    saved_path = package_root / "MuMuInstallPath.txt"
    if saved_path.exists():
        raw = saved_path.read_text(encoding="utf-8", errors="ignore").strip()
        if raw:
            paths.append(Path(raw))
    paths.extend(
        [
            Path(r"C:\Program Files\Netease\MuMu"),
            Path(r"C:\Program Files\Netease\MuMuPlayer-12.0"),
            Path(r"D:\Program Files\Netease\MuMuPlayer-12.0"),
            Path(r"F:\Program Files\Netease\MuMuPlayer-12.0"),
        ]
    )
    return paths


class MumuBackend:
    name = "mumu"

    def __init__(
        self,
        platform_name: str | None = None,
        install_paths: list[Path] | None = None,
        native_api: MumuNativeApi | None = None,
        instance_indices: tuple[int, ...] = (0,),
        display_id: int = 0,
        swipe_steps: int = 12,
        sleep: Callable[[float], None] = system_sleep,
    ) -> None:
        self.platform_name = platform_name or platform.system()
        self.install_paths = (
            default_mumu_install_paths() if install_paths is None else install_paths
        )
        self.install_path, self.dll_path = self._find_dll()
        if native_api is not None:
            self.native_api = native_api
        elif self.dll_path is not None:
            self.native_api = CtypesMumuNativeApi(
                self.dll_path,
                platform_name=self.platform_name,
            )
        else:
            self.native_api = UnavailableMumuNativeApi()
        self.instance_indices = tuple(dict.fromkeys(instance_indices))
        self.display_id = display_id
        self.swipe_steps = max(swipe_steps, 2)
        self._sleep = sleep
        self._sessions: dict[int, int] = {}
        self._frame_sizes: dict[int, tuple[int, int]] = {}
        self._session_lock = RLock()

    def capability(self) -> Capability:
        if self.platform_name != "Windows":
            return Capability(
                name=self.name,
                available=False,
                reason="MuMu high-speed backend is only available on Windows.",
            )
        if self.dll_path is None:
            return Capability(
                name=self.name,
                available=False,
                reason="MuMu external_renderer_ipc.dll was not found.",
            )
        if not self.native_api.is_ready():
            return Capability(
                name=self.name,
                available=False,
                reason="MuMu native adapter is not ready.",
            )
        return Capability(name=self.name, available=True, reason=None)

    def diagnostics(self) -> dict[str, object]:
        details: dict[str, object] = {
            "backend": self.name,
            "platform": self.platform_name,
            "dll_found": self.dll_path is not None,
            "dll_path": str(self.dll_path) if self.dll_path is not None else None,
            "install_path": str(self.install_path) if self.install_path is not None else None,
            "configured_instances": list(self.instance_indices),
            "connected_instances": sorted(self._sessions),
        }
        details.update(self.native_api.diagnostics())
        details["available"] = self.capability().available
        return details

    def list_devices(self) -> list[DeviceInfo]:
        capability = self.capability()
        if not capability.available:
            return []
        return [
            DeviceInfo(
                backend=self.name,
                device_id=f"mumu:{index}",
                name=f"MuMu {index}",
                status="device",
                source="mumu-ipc",
                details={"instance_index": index, "display_id": self.display_id},
            )
            for index in self.instance_indices
        ]

    def snapshot(self, device_id: str) -> bytes:
        index = self._parse_device_id(device_id)
        try:
            frame = self._capture_frame(index, self._session(index))
            return self._frame_to_png(frame)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                ErrorCode.SNAPSHOT_FAILED,
                "MuMu direct screenshot failed.",
                {"device_id": device_id, "error": str(exc)},
            ) from exc

    def tap(self, device_id: str, x: int, y: int) -> OperationResult:
        index = self._parse_device_id(device_id)
        try:
            handle = self._session(index)
            native_x, native_y = self._native_touch_point(index, handle, x, y)
            self.native_api.touch_down(handle, self.display_id, native_x, native_y)
            self.native_api.touch_up(handle, self.display_id)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                ErrorCode.TAP_FAILED,
                "MuMu direct tap failed.",
                {"device_id": device_id, "x": x, "y": y, "error": str(exc)},
            ) from exc
        return OperationResult(
            ok=True,
            action="tap",
            message="MuMu tap completed.",
            data={"x": x, "y": y, "display_id": self.display_id},
        )

    def swipe(
        self,
        device_id: str,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int,
    ) -> OperationResult:
        index = self._parse_device_id(device_id)
        try:
            handle = self._session(index)
            frame_height = self._frame_height(index, handle)
            delay = max(duration_ms, 0) / self.swipe_steps / 1000
            for step in range(self.swipe_steps):
                fraction = step / (self.swipe_steps - 1)
                x = round(x1 + (x2 - x1) * fraction)
                y = round(y1 + (y2 - y1) * fraction)
                native_x, native_y = frame_height - y, x
                self.native_api.touch_down(
                    handle,
                    self.display_id,
                    native_x,
                    native_y,
                )
                self._sleep(delay)
            self.native_api.touch_up(handle, self.display_id)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                ErrorCode.SWIPE_FAILED,
                "MuMu direct swipe failed.",
                {"device_id": device_id, "error": str(exc)},
            ) from exc
        return OperationResult(
            ok=True,
            action="swipe",
            message="MuMu swipe completed.",
            data={"from": [x1, y1], "to": [x2, y2], "duration_ms": duration_ms},
        )

    def close(self) -> None:
        with self._session_lock:
            sessions = sorted(self._sessions.items())
            self._sessions.clear()
            self._frame_sizes.clear()
        for _, handle in sessions:
            self.native_api.disconnect(handle)

    def _session(self, instance_index: int) -> int:
        if not self.capability().available or self.install_path is None:
            raise AppError(
                ErrorCode.MUMU_DLL_NOT_FOUND,
                self.capability().reason or "MuMu native backend is unavailable.",
                self.diagnostics(),
            )
        with self._session_lock:
            handle = self._sessions.get(instance_index)
            if handle is not None:
                return handle
            handle = self.native_api.connect(self.install_path, instance_index)
            if handle <= 0:
                raise RuntimeError(f"nemu_connect returned invalid handle {handle}")
            self._sessions[instance_index] = handle
            return handle

    def _capture_frame(self, instance_index: int, handle: int) -> MumuNativeFrame:
        frame = self.native_api.capture_display(handle, self.display_id)
        with self._session_lock:
            self._frame_sizes[instance_index] = (frame.width, frame.height)
        return frame

    def _frame_height(self, instance_index: int, handle: int) -> int:
        with self._session_lock:
            frame_size = self._frame_sizes.get(instance_index)
        if frame_size is None:
            frame = self._capture_frame(instance_index, handle)
            return frame.height
        return frame_size[1]

    def _native_touch_point(
        self,
        instance_index: int,
        handle: int,
        x: int,
        y: int,
    ) -> tuple[int, int]:
        # MuMu IPC touch space is rotated relative to its captured landscape frame.
        return self._frame_height(instance_index, handle) - y, x

    def _parse_device_id(self, device_id: str) -> int:
        if device_id == "mumu":
            index = 0
        else:
            prefix, separator, value = device_id.partition(":")
            if prefix != "mumu" or not separator:
                value = ""
            try:
                index = int(value)
            except ValueError:
                index = -1
        if index not in self.instance_indices:
            raise AppError(
                ErrorCode.DEVICE_NOT_FOUND,
                "MuMu instance is not configured.",
                {"device_id": device_id, "configured_instances": list(self.instance_indices)},
            )
        return index

    @staticmethod
    def _frame_to_png(frame: MumuNativeFrame) -> bytes:
        if frame.width <= 0 or frame.height <= 0:
            raise ValueError("MuMu frame dimensions must be positive")
        expected_size = frame.width * frame.height * 4
        if len(frame.pixels) != expected_size:
            raise ValueError(
                f"MuMu frame has {len(frame.pixels)} bytes; expected {expected_size}"
            )
        image = Image.frombytes("RGBA", (frame.width, frame.height), frame.pixels)
        if frame.bottom_up:
            image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    def _find_dll(self) -> tuple[Path | None, Path | None]:
        for install_path in self.install_paths:
            for dll_relative_path in DLL_LAYOUTS:
                candidate = install_path / dll_relative_path
                if candidate.exists():
                    return install_path, candidate
        return None, None
