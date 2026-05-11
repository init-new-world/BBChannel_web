from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from webapp.core.errors import AppError, ErrorCode
from webapp.core.models import Capability, DeviceInfo, OperationResult


DEFAULT_TIMEOUT_SECONDS = 15


def default_adb_candidates() -> list[Path]:
    project_root = Path(__file__).resolve().parents[2]
    package_root = project_root.parent
    candidates = [
        package_root / "adb" / "33.0.2" / "adb.exe",
        package_root / "adb" / "airtest_adb" / "adb.exe",
        package_root / "adb" / "leidian_adb" / "adb.exe",
        package_root / "adb" / "nox_adb" / "adb.exe",
    ]
    path_adb = shutil.which("adb")
    if path_adb:
        candidates.append(Path(path_adb))
    return candidates


def parse_adb_devices(output: str) -> list[DeviceInfo]:
    devices: list[DeviceInfo] = []
    for raw_line in output.splitlines()[1:]:
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        devices.append(
            DeviceInfo(
                backend="adb",
                device_id=parts[0],
                name=parts[0],
                status=parts[1],
            )
        )
    return devices


class AdbBackend:
    name = "adb"

    def __init__(
        self,
        adb_candidates: list[Path] | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.adb_path = self._find_adb(adb_candidates or default_adb_candidates())

    def capability(self) -> Capability:
        if self.adb_path is None:
            return Capability(
                name=self.name,
                available=False,
                reason="ADB executable was not found.",
            )
        return Capability(name=self.name, available=True, reason=None)

    def list_devices(self) -> list[DeviceInfo]:
        output = self._run(["devices"], text=True).stdout
        return parse_adb_devices(output)

    def snapshot(self, device_id: str) -> bytes:
        return self._run(["-s", device_id, "exec-out", "screencap", "-p"]).stdout

    def tap(self, device_id: str, x: int, y: int) -> OperationResult:
        self._run(["-s", device_id, "shell", "input", "tap", str(x), str(y)], text=True)
        return OperationResult(ok=True, action="tap", message=f"Tapped {x},{y}")

    def swipe(
        self,
        device_id: str,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int,
    ) -> OperationResult:
        self._run(
            [
                "-s",
                device_id,
                "shell",
                "input",
                "swipe",
                str(x1),
                str(y1),
                str(x2),
                str(y2),
                str(duration_ms),
            ],
            text=True,
        )
        return OperationResult(ok=True, action="swipe", message="Swipe sent")

    def _run(self, args: list[str], text: bool = False) -> subprocess.CompletedProcess:
        if self.adb_path is None:
            raise AppError(ErrorCode.ADB_NOT_FOUND, "ADB executable was not found.")
        try:
            return subprocess.run(
                [str(self.adb_path), *args],
                check=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                text=text,
            )
        except subprocess.TimeoutExpired as exc:
            raise AppError(
                ErrorCode.ADB_TIMEOUT,
                "ADB command timed out.",
                {"args": args},
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            raise AppError(
                ErrorCode.SNAPSHOT_FAILED if "screencap" in args else ErrorCode.ADB_NOT_FOUND,
                stderr or "ADB command failed.",
                {"args": args, "returncode": exc.returncode},
            ) from exc

    @staticmethod
    def _find_adb(candidates: list[Path]) -> Path | None:
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None
