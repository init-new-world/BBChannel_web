from __future__ import annotations

import os
import socket
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from time import monotonic

from webapp.core.errors import AppError, ErrorCode
from webapp.core.models import Capability, DeviceInfo, OperationResult


DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_DISCOVERY_PORTS = (5555, 16384, 7555, 62001)
DEFAULT_SCAN_HOSTS = ("auto",)
DEFAULT_PROBE_TIMEOUT_SECONDS = 0.3
DEFAULT_DISCOVERY_TTL_SECONDS = 10.0
DEFAULT_DETAILS_TIMEOUT_SECONDS = 2.0

CommandRunner = Callable[[list[str], bool, float], subprocess.CompletedProcess]
TcpProbe = Callable[[str, int, float], bool]


@dataclass(frozen=True)
class AdbDiscoveryConfig:
    auto_connect: bool = True
    scan_hosts: tuple[str, ...] = DEFAULT_SCAN_HOSTS
    scan_ports: tuple[int, ...] = DEFAULT_DISCOVERY_PORTS
    probe_timeout_seconds: float = DEFAULT_PROBE_TIMEOUT_SECONDS
    discovery_ttl_seconds: float = DEFAULT_DISCOVERY_TTL_SECONDS
    enrich_details: bool = True
    details_timeout_seconds: float = DEFAULT_DETAILS_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AdbDiscoveryConfig":
        values = os.environ if env is None else env
        return cls(
            auto_connect=_env_bool(values.get("BBCHANNEL_ADB_AUTO_CONNECT"), default=True),
            scan_hosts=_split_csv(values.get("BBCHANNEL_ADB_SCAN_HOSTS"), DEFAULT_SCAN_HOSTS),
            scan_ports=_parse_ports(
                values.get("BBCHANNEL_ADB_SCAN_PORTS"),
                DEFAULT_DISCOVERY_PORTS,
            ),
            probe_timeout_seconds=_env_milliseconds(
                values.get("BBCHANNEL_ADB_CONNECT_TIMEOUT_MS"),
                DEFAULT_PROBE_TIMEOUT_SECONDS,
            ),
            discovery_ttl_seconds=float(
                values.get("BBCHANNEL_ADB_DISCOVERY_TTL_SECONDS", DEFAULT_DISCOVERY_TTL_SECONDS)
            ),
            enrich_details=_env_bool(values.get("BBCHANNEL_ADB_ENRICH_DETAILS"), default=True),
        )


def _env_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _split_csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    entries = tuple(entry.strip() for entry in value.split(",") if entry.strip())
    return entries or default


def _parse_ports(value: str | None, default: tuple[int, ...]) -> tuple[int, ...]:
    if value is None:
        return default
    ports: list[int] = []
    for entry in value.split(","):
        entry = entry.strip()
        if not entry:
            continue
        port = int(entry)
        if 0 < port < 65536 and port not in ports:
            ports.append(port)
    return tuple(ports) or default


def _env_milliseconds(value: str | None, default_seconds: float) -> float:
    if value is None:
        return default_seconds
    return max(int(value), 1) / 1000


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


def is_wsl(env: Mapping[str, str] | None = None, version_path: Path | str = "/proc/version") -> bool:
    values = os.environ if env is None else env
    if values.get("WSL_DISTRO_NAME") or values.get("WSL_INTEROP"):
        return True
    try:
        version = Path(version_path).read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return "microsoft" in version or "wsl" in version


def detect_wsl_host_ip(
    resolv_conf: Path | str = "/etc/resolv.conf",
    env: Mapping[str, str] | None = None,
    version_path: Path | str = "/proc/version",
) -> str | None:
    if not is_wsl(env=env, version_path=version_path):
        return None
    try:
        lines = Path(resolv_conf).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    for line in lines:
        parts = line.split()
        if len(parts) == 2 and parts[0] == "nameserver":
            try:
                ip_address(parts[1])
            except ValueError:
                continue
            return parts[1]
    return None


def candidate_adb_endpoints(
    config: AdbDiscoveryConfig,
    wsl_host_ip: str | None = None,
) -> list[tuple[str, int]]:
    hosts: list[str] = []
    for host in config.scan_hosts:
        if host == "auto":
            for candidate in [wsl_host_ip, "127.0.0.1", "localhost"]:
                if candidate and candidate not in hosts:
                    hosts.append(candidate)
            continue
        if host not in hosts:
            hosts.append(host)

    endpoints: list[tuple[str, int]] = []
    for host in hosts:
        for port in config.scan_ports:
            endpoint = (host, port)
            if endpoint not in endpoints:
                endpoints.append(endpoint)
    return endpoints


def probe_tcp(host: str, port: int, timeout_seconds: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def parse_adb_devices(output: str) -> list[DeviceInfo]:
    devices: list[DeviceInfo] = []
    for raw_line in output.splitlines()[1:]:
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        details = _parse_device_details(parts[2:])
        devices.append(
            DeviceInfo(
                backend="adb",
                device_id=parts[0],
                name=details.get("model", parts[0]),
                status=parts[1],
                source="adb-devices",
                details=details,
            )
        )
    return devices


def _parse_device_details(parts: list[str]) -> dict[str, str]:
    details: dict[str, str] = {}
    for part in parts:
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        if key and value:
            details[key] = value
    return details


class AdbBackend:
    name = "adb"

    def __init__(
        self,
        adb_candidates: list[Path] | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        discovery_config: AdbDiscoveryConfig | None = None,
        probe_tcp: TcpProbe = probe_tcp,
        run_command: CommandRunner | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.adb_path = self._find_adb(adb_candidates or default_adb_candidates())
        self.discovery_config = discovery_config or AdbDiscoveryConfig.from_env()
        self._probe_tcp = probe_tcp
        self._run_command = run_command
        self._last_discovery_at = 0.0

    def capability(self) -> Capability:
        if self.adb_path is None:
            return Capability(
                name=self.name,
                available=False,
                reason="ADB executable was not found.",
            )
        return Capability(name=self.name, available=True, reason=None)

    def list_devices(self) -> list[DeviceInfo]:
        devices = self._list_devices_once()
        if self.discovery_config.auto_connect and self._should_discover():
            self._auto_connect({device.device_id for device in devices})
            self._last_discovery_at = monotonic()
            devices = self._list_devices_once()
        enriched_devices = self._enrich_devices(_dedupe_devices(devices))
        return _dedupe_device_aliases(enriched_devices)

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

    def _list_devices_once(self) -> list[DeviceInfo]:
        output = self._run(["devices", "-l"], text=True).stdout
        return parse_adb_devices(output)

    def _should_discover(self) -> bool:
        if self.discovery_config.discovery_ttl_seconds <= 0:
            return True
        return monotonic() - self._last_discovery_at >= self.discovery_config.discovery_ttl_seconds

    def _auto_connect(self, known_device_ids: set[str]) -> None:
        wsl_host_ip = detect_wsl_host_ip()
        for host, port in candidate_adb_endpoints(self.discovery_config, wsl_host_ip=wsl_host_ip):
            serial = f"{host}:{port}"
            if serial in known_device_ids:
                continue
            if not self._probe_tcp(host, port, self.discovery_config.probe_timeout_seconds):
                continue
            try:
                self._run(["connect", serial], text=True)
            except AppError:
                continue

    def _enrich_devices(self, devices: list[DeviceInfo]) -> list[DeviceInfo]:
        if not self.discovery_config.enrich_details:
            return devices
        return [self._enrich_device(device) for device in devices]

    def _enrich_device(self, device: DeviceInfo) -> DeviceInfo:
        if device.status != "device":
            return device

        details = dict(device.details)
        property_map = {
            "brand": "ro.product.brand",
            "manufacturer": "ro.product.manufacturer",
            "android": "ro.build.version.release",
            "sdk": "ro.build.version.sdk",
            "abi": "ro.product.cpu.abi",
        }
        for key, prop_name in property_map.items():
            if key not in details:
                value = self._try_shell(device.device_id, ["getprop", prop_name])
                if value:
                    details[key] = value

        wm_size = self._try_shell(device.device_id, ["wm", "size"])
        if wm_size and "wm_size" not in details:
            details["wm_size"] = wm_size.replace("Physical size:", "").strip()
        wm_density = self._try_shell(device.device_id, ["wm", "density"])
        if wm_density and "wm_density" not in details:
            details["wm_density"] = wm_density.replace("Physical density:", "").strip()

        android_id = self._try_shell(device.device_id, ["settings", "get", "secure", "android_id"])
        if android_id and android_id not in {"null", "unknown"}:
            details["android_id"] = android_id

        ip_output = self._try_shell(device.device_id, ["ip", "-o", "-4", "addr", "show"])
        android_ip = _parse_android_ip(ip_output or "")
        if android_ip:
            details["android_ip"] = android_ip

        root_output = self._try_shell(device.device_id, ["su", "-c", "id"])
        if root_output:
            details["root"] = "uid=0" in root_output

        name = _device_display_name(details, fallback=device.name or device.device_id)
        return DeviceInfo(
            backend=device.backend,
            device_id=device.device_id,
            name=name,
            status=device.status,
            source=device.source,
            details=details,
        )

    def _try_shell(self, device_id: str, shell_args: list[str]) -> str | None:
        try:
            result = self._run(
                ["-s", device_id, "shell", *shell_args],
                text=True,
                timeout_seconds=self.discovery_config.details_timeout_seconds,
            )
        except AppError:
            return None
        return result.stdout.strip()

    def _run(
        self,
        args: list[str],
        text: bool = False,
        timeout_seconds: float | None = None,
    ) -> subprocess.CompletedProcess:
        if self.adb_path is None:
            raise AppError(ErrorCode.ADB_NOT_FOUND, "ADB executable was not found.")
        command = [str(self.adb_path), *args]
        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        if self._run_command is not None:
            return self._run_command(command, text, timeout)
        try:
            return subprocess.run(
                command,
                check=True,
                capture_output=True,
                timeout=timeout,
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


def _dedupe_devices(devices: list[DeviceInfo]) -> list[DeviceInfo]:
    deduped: dict[str, DeviceInfo] = {}
    for device in devices:
        deduped[device.device_id] = device
    return list(deduped.values())


def _dedupe_device_aliases(devices: list[DeviceInfo]) -> list[DeviceInfo]:
    deduped: list[DeviceInfo] = []
    seen_identities: set[str] = set()
    for device in devices:
        identity = str(device.details.get("android_id") or "").strip()
        if identity:
            if identity in seen_identities:
                continue
            seen_identities.add(identity)
        deduped.append(device)
    return deduped


def _parse_android_ip(output: str) -> str | None:
    for line in output.splitlines():
        parts = line.split()
        if "inet" not in parts:
            continue
        value = parts[parts.index("inet") + 1]
        if value.startswith("127."):
            continue
        return value.split("/", 1)[0]
    return None


def _device_display_name(details: dict[str, object], fallback: str) -> str:
    brand = str(details.get("brand") or "").strip()
    model = str(details.get("model") or "").strip()
    if brand and model and brand.lower() not in model.lower():
        return f"{brand} {model}"
    return model or fallback
