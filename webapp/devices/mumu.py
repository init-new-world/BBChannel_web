from __future__ import annotations

import platform
from pathlib import Path

from webapp.core.errors import AppError, ErrorCode
from webapp.core.models import Capability, DeviceInfo, OperationResult


DLL_RELATIVE_PATH = Path("shell") / "sdk" / "external_renderer_ipc.dll"


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
    ) -> None:
        self.platform_name = platform_name or platform.system()
        self.install_paths = install_paths or default_mumu_install_paths()
        self.dll_path = self._find_dll()

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
        return Capability(name=self.name, available=True, reason=None)

    def list_devices(self) -> list[DeviceInfo]:
        capability = self.capability()
        if not capability.available:
            return []
        return [DeviceInfo(backend=self.name, device_id="mumu", name="MuMu", status="device")]

    def snapshot(self, device_id: str) -> bytes:
        raise AppError(
            ErrorCode.MUMU_DLL_NOT_FOUND,
            "MuMu direct screenshot is not implemented in this PoC.",
            {"device_id": device_id},
        )

    def tap(self, device_id: str, x: int, y: int) -> OperationResult:
        raise AppError(
            ErrorCode.MUMU_DLL_NOT_FOUND,
            "MuMu direct tap is not implemented in this PoC.",
            {"device_id": device_id, "x": x, "y": y},
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
        raise AppError(
            ErrorCode.MUMU_DLL_NOT_FOUND,
            "MuMu direct swipe is not implemented in this PoC.",
            {"device_id": device_id},
        )

    def _find_dll(self) -> Path | None:
        for install_path in self.install_paths:
            candidate = install_path / DLL_RELATIVE_PATH
            if candidate.exists():
                return candidate
        return None
