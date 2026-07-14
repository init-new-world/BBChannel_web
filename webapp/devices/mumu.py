from __future__ import annotations

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
    (Path("shell") / "sdk" / DLL_NAME, Path()),
    (Path("nx_device") / "12.0" / "shell" / "sdk" / DLL_NAME, Path("nx_device") / "12.0"),
    (Path("nx_main") / "sdk" / DLL_NAME, Path("nx_main")),
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
        self.native_api = native_api or UnavailableMumuNativeApi()
        self.instance_indices = tuple(dict.fromkeys(instance_indices))
        self.display_id = display_id
        self.swipe_steps = max(swipe_steps, 2)
        self._sleep = sleep
        self._sessions: dict[int, int] = {}
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
            frame = self.native_api.capture_display(self._session(index), self.display_id)
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
            self.native_api.touch_down(handle, self.display_id, x, y)
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
            delay = max(duration_ms, 0) / self.swipe_steps / 1000
            for step in range(self.swipe_steps):
                fraction = step / (self.swipe_steps - 1)
                x = round(x1 + (x2 - x1) * fraction)
                y = round(y1 + (y2 - y1) * fraction)
                self.native_api.touch_down(handle, self.display_id, x, y)
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
            for dll_relative_path, native_root_suffix in DLL_LAYOUTS:
                candidate = install_path / dll_relative_path
                if candidate.exists():
                    return install_path / native_root_suffix, candidate
        return None, None
