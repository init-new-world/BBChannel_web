from __future__ import annotations

import logging
import os
import re
import socket
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import http.client
from ipaddress import ip_address
from pathlib import Path
from queue import Empty, Queue
import struct
from threading import Lock, Thread
from time import monotonic, sleep as system_sleep

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
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdbRetryConfig:
    snapshot_attempts: int = 3
    control_attempts: int = 2
    initial_delay_seconds: float = 0.1
    max_delay_seconds: float = 0.5

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AdbRetryConfig":
        values = os.environ if env is None else env
        return cls(
            snapshot_attempts=_positive_int(values.get("BBCHANNEL_ADB_SNAPSHOT_ATTEMPTS"), 3),
            control_attempts=_positive_int(values.get("BBCHANNEL_ADB_CONTROL_ATTEMPTS"), 2),
            initial_delay_seconds=_non_negative_float(
                values.get("BBCHANNEL_ADB_RETRY_DELAY_SECONDS"),
                0.1,
            ),
            max_delay_seconds=_non_negative_float(
                values.get("BBCHANNEL_ADB_RETRY_MAX_DELAY_SECONDS"),
                0.5,
            ),
        )


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


def _positive_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return max(int(value), 1)
    except ValueError:
        return default


def _non_negative_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return max(float(value), 0.0)
    except ValueError:
        return default


EMBEDDED_ADB_SUBDIRS = ("33.0.2", "airtest_adb", "leidian_adb", "nox_adb")


def embedded_adb_dir(project_root: Path | None = None) -> Path:
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    return root / "bin" / "adb"


def default_adb_candidates(
    project_root: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    os_name: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> list[Path]:
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    package_root = root.parent
    values = os.environ if env is None else env
    active_os = os.name if os_name is None else os_name

    candidates: list[Path] = []
    configured = (values.get("BBCHANNEL_ADB_PATH") or "").strip()
    if configured:
        candidates.append(Path(configured))

    embedded_root = embedded_adb_dir(root)
    windows_bundles = [
        *(embedded_root / subdir / "adb.exe" for subdir in EMBEDDED_ADB_SUBDIRS),
        *(package_root / "adb" / subdir / "adb.exe" for subdir in EMBEDDED_ADB_SUBDIRS),
    ]
    path_adb = which("adb")

    if active_os == "nt":
        candidates.extend(windows_bundles)
        if path_adb:
            candidates.append(Path(path_adb))
    else:
        candidates.append(embedded_root / "adb")
        if path_adb:
            candidates.append(Path(path_adb))
        candidates.extend(windows_bundles)

    deduped: list[Path] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


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


def parse_adb_display_size(output: str) -> tuple[int, int] | None:
    sizes: dict[str, tuple[int, int]] = {}
    fallback: tuple[int, int] | None = None
    for match in re.finditer(
        r"(?:(Physical|Override)\s+size:\s*)?(\d+)\s*x\s*(\d+)",
        output,
        flags=re.IGNORECASE,
    ):
        width = int(match.group(2))
        height = int(match.group(3))
        if width <= 0 or height <= 0:
            continue
        size = (width, height)
        label = match.group(1)
        if label is None:
            fallback = size
        else:
            sizes[label.casefold()] = size
    return sizes.get("override") or sizes.get("physical") or fallback


def normalize_adb_endpoint(value: str) -> str:
    endpoint = value.strip()
    host, separator, port_value = endpoint.rpartition(":")
    if not separator:
        raise _invalid_adb_endpoint(value)

    host = host.strip()
    port_value = port_value.strip()
    if not host or not port_value:
        raise _invalid_adb_endpoint(value)
    try:
        port = int(port_value, 10)
    except ValueError as exc:
        raise _invalid_adb_endpoint(value) from exc
    if port <= 0 or port > 65535:
        raise _invalid_adb_endpoint(value)
    if any(character.isspace() for character in host):
        raise _invalid_adb_endpoint(value)
    return f"{host}:{port}"


def _invalid_adb_endpoint(value: str) -> AppError:
    return AppError(
        ErrorCode.ADB_CONNECT_FAILED,
        "ADB endpoint must use host:port.",
        {"endpoint": value},
    )


def _parse_device_details(parts: list[str]) -> dict[str, str]:
    details: dict[str, str] = {}
    for part in parts:
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        if key and value:
            details[key] = value
    return details


class _PersistentAdbShell:
    """Keeps one `adb -s <id> shell` open and uses C++ Binder `cmd input`."""

    def __init__(self, adb_path: Path, device_id: str, timeout_seconds: float = 5.0) -> None:
        self.adb_path = adb_path
        self.device_id = device_id
        self.timeout_seconds = max(timeout_seconds, 1.0)
        self._lock = Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._lines: Queue[str | None] = Queue()

    def _ensure_open(self) -> subprocess.Popen[str]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        self._close_locked()
        self._lines = Queue()
        proc = subprocess.Popen(
            [str(self.adb_path), "-s", self.device_id, "shell"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )
        self._proc = proc
        q = self._lines

        def _reader() -> None:
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    q.put(line)
            except Exception:
                pass
            finally:
                q.put(None)

        Thread(target=_reader, daemon=True, name=f"adb-shell-{self.device_id}").start()
        return proc

    def execute(self, command: str, token: str) -> bool:
        marker = f"__BB_DONE_{token}__:"
        with self._lock:
            try:
                proc = self._ensure_open()
                assert proc.stdin is not None
                while not self._lines.empty():
                    try:
                        self._lines.get_nowait()
                    except Empty:
                        break
                proc.stdin.write(f"{command}; echo {marker}$?\n")
                proc.stdin.flush()
                deadline = monotonic() + self.timeout_seconds
                while True:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        self._close_locked()
                        return False
                    try:
                        line = self._lines.get(timeout=remaining)
                    except Empty:
                        self._close_locked()
                        return False
                    if line is None:
                        self._close_locked()
                        return False
                    idx = line.find(marker)
                    if idx != -1:
                        rc = line[idx + len(marker) :].strip()
                        return rc == "0"
            except Exception:
                self._close_locked()
                return False

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=0.5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _default_droidcast_apk() -> Path | None:
    root = Path(__file__).resolve().parents[2]
    for candidate in (
        root / "bin" / "DroidCast-debug-1.2.1.apk",
        root.parent / "apks" / "DroidCast-debug-1.2.1.apk",
    ):
        if candidate.is_file():
            return candidate
    return None


def _decoded_image_size(data: bytes) -> tuple[int, int] | None:
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return struct.unpack_from(">II", data, 16)
    if len(data) >= 12 and data.startswith(b"\xff\xd8"):
        pos = 2
        length = len(data)
        while pos + 4 <= length:
            if data[pos] != 0xFF:
                break
            while pos < length and data[pos] == 0xFF:
                pos += 1
            if pos >= length:
                break
            marker = data[pos]
            pos += 1
            if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
                continue
            if pos + 2 > length:
                break
            segment_len = (data[pos] << 8) | data[pos + 1]
            if segment_len < 2 or pos + segment_len > length:
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if segment_len >= 7:
                    height = (data[pos + 3] << 8) | data[pos + 4]
                    width = (data[pos + 5] << 8) | data[pos + 6]
                    return (width, height)
                break
            pos += segment_len
    return None


class _DroidCastSession:
    """Resident Airtest DroidCast HTTP capture stream (~30ms 720p GPU-scaled frames)."""

    REMOTE_APK = "/data/local/tmp/bbchannel_droidcast.apk"
    REMOTE_PORT = 53516
    PRESCALED_MAGIC = b"BBDC720\x00"
    ENDPOINT_CANDIDATES = (
        "/screenshot?width=720&height=1280&format=jpeg",
        "/screenshot?width=1280&height=720&format=jpeg",
    )

    def __init__(
        self,
        adb_path: Path,
        device_id: str,
        apk_path: Path,
        raw_size: tuple[int, int],
    ) -> None:
        self.adb_path = adb_path
        self.device_id = device_id
        self.apk_path = apk_path
        self.raw_width, self.raw_height = raw_size
        self._lock = Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._local_port: int | None = None
        self._conn: http.client.HTTPConnection | None = None
        self._endpoint: str | None = None
        self._failed = False

    def _start_locked(self) -> bool:
        if self._failed:
            return False
        if (
            self._local_port is not None
            and self._endpoint is not None
            and self._proc is not None
            and self._proc.poll() is None
        ):
            return True
        self._cleanup_locked()
        try:
            subprocess.run(
                [str(self.adb_path), "-s", self.device_id, "push", str(self.apk_path), self.REMOTE_APK],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10.0,
                check=True,
            )
            subprocess.run(
                [str(self.adb_path), "-s", self.device_id, "shell", "pkill -f com.rayworks.droidcast.Main || true"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3.0,
                check=False,
            )
            self._proc = subprocess.Popen(
                [
                    str(self.adb_path),
                    "-s",
                    self.device_id,
                    "shell",
                    f"CLASSPATH={self.REMOTE_APK}",
                    "app_process",
                    "/",
                    "com.rayworks.droidcast.Main",
                    f"--port={self.REMOTE_PORT}",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            fwd = subprocess.run(
                [str(self.adb_path), "-s", self.device_id, "forward", "tcp:0", f"tcp:{self.REMOTE_PORT}"],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=True,
            )
            self._local_port = int(fwd.stdout.strip())
            for _ in range(10):
                system_sleep(0.15)
                for endpoint in self.ENDPOINT_CANDIDATES:
                    body = self._fetch_once_locked(endpoint)
                    if body is not None and _decoded_image_size(body) == (1280, 720):
                        self._endpoint = endpoint
                        return True
            self._failed = True
            self._cleanup_locked()
            return False
        except Exception:
            self._failed = True
            self._cleanup_locked()
            return False

    def _fetch_once_locked(self, endpoint: str | None = None) -> bytes | None:
        if self._local_port is None:
            return None
        target = endpoint or self._endpoint or self.ENDPOINT_CANDIDATES[0]
        for attempt in range(2):
            try:
                if self._conn is None:
                    self._conn = http.client.HTTPConnection("127.0.0.1", self._local_port, timeout=2.5)
                self._conn.request("GET", target)
                resp = self._conn.getresponse()
                data = resp.read()
                if resp.status == 200 and data:
                    return data
            except Exception:
                if self._conn is not None:
                    try:
                        self._conn.close()
                    except Exception:
                        pass
                    self._conn = None
                if attempt == 1:
                    return None
        return None

    def capture_prescaled_720p(self) -> bytes | None:
        if self.raw_width <= self.raw_height or abs(self.raw_width / self.raw_height - 16 / 9) >= 0.02:
            return None
        with self._lock:
            if not self._start_locked():
                return None
            frame = self._fetch_once_locked()
            if frame is None or _decoded_image_size(frame) != (1280, 720):
                return None
            return self.PRESCALED_MAGIC + struct.pack("<II", self.raw_width, self.raw_height) + frame

    def close(self) -> None:
        with self._lock:
            self._cleanup_locked()

    def _cleanup_locked(self) -> None:
        self._endpoint = None
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        if self._local_port is not None:
            try:
                subprocess.run(
                    [str(self.adb_path), "-s", self.device_id, "forward", "--remove", f"tcp:{self._local_port}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2.0,
                    check=False,
                )
            except Exception:
                pass
            self._local_port = None
        proc = self._proc
        self._proc = None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=0.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


def _is_valid_raw_screencap(payload: bytes) -> bool:
    if len(payload) < 16:
        return False
    width, height, pixel_format = struct.unpack_from("<III", payload, 0)
    if not (1 <= width <= 16384 and 1 <= height <= 16384) or pixel_format not in {1, 2, 5}:
        return False
    header_size = len(payload) - (width * height * 4)
    return header_size in {12, 16}


class AdbBackend:
    name = "adb"

    def __init__(
        self,
        adb_candidates: list[Path] | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        discovery_config: AdbDiscoveryConfig | None = None,
        probe_tcp: TcpProbe = probe_tcp,
        run_command: CommandRunner | None = None,
        retry_config: AdbRetryConfig | None = None,
        sleep: Callable[[float], None] = system_sleep,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.adb_path = self._find_adb(adb_candidates or default_adb_candidates())
        self.discovery_config = discovery_config or AdbDiscoveryConfig.from_env()
        self._probe_tcp = probe_tcp
        self._run_command = run_command
        self.retry_config = retry_config or AdbRetryConfig.from_env()
        self._sleep = sleep
        self._last_discovery_at = 0.0
        self._fast_capture = _env_bool(os.environ.get("BBCHANNEL_ADB_FAST_CAPTURE"), default=True)
        self._droidcast_enabled = _env_bool(os.environ.get("BBCHANNEL_ADB_DROIDCAST"), default=True)
        self._fast_input = _env_bool(os.environ.get("BBCHANNEL_ADB_FAST_INPUT"), default=True)
        self._shells_lock = Lock()
        self._shells: dict[str, _PersistentAdbShell] = {}
        self._droidcast_sessions: dict[str, _DroidCastSession] = {}
        self._shell_seq = 0

    def capability(self) -> Capability:
        if self.adb_path is None:
            return Capability(
                name=self.name,
                available=False,
                reason="ADB executable was not found.",
            )
        return Capability(name=self.name, available=True, reason=None)

    def _is_embedded_adb(self) -> bool:
        if self.adb_path is None:
            return False
        try:
            self.adb_path.resolve().relative_to(embedded_adb_dir())
            return True
        except ValueError:
            return False

    def diagnostics(self) -> dict[str, object]:
        details: dict[str, object] = {
            "backend": self.name,
            "available": self.adb_path is not None,
            "path": str(self.adb_path) if self.adb_path is not None else None,
            "embedded": self._is_embedded_adb(),
            "retry": {
                "snapshot_attempts": self.retry_config.snapshot_attempts,
                "control_attempts": self.retry_config.control_attempts,
                "initial_delay_seconds": self.retry_config.initial_delay_seconds,
                "max_delay_seconds": self.retry_config.max_delay_seconds,
            },
        }
        if self.adb_path is None:
            details["error"] = "ADB executable was not found."
            return details
        try:
            version = self._run(["version"], text=True, timeout_seconds=3.0).stdout
            devices = parse_adb_devices(
                self._run(["devices", "-l"], text=True, timeout_seconds=3.0).stdout
            )
        except AppError as exc:
            details["server_reachable"] = False
            details["error"] = exc.to_response()["error"]
            return details
        status_counts: dict[str, int] = {}
        for device in devices:
            status_counts[device.status] = status_counts.get(device.status, 0) + 1
        details.update(
            {
                "server_reachable": True,
                "version": version.splitlines()[0].strip() if version else "",
                "device_count": len(devices),
                "device_statuses": status_counts,
            }
        )
        return details

    def list_devices(self) -> list[DeviceInfo]:
        devices = self._list_devices_once()
        if self.discovery_config.auto_connect and self._should_discover():
            self._auto_connect({device.device_id for device in devices})
            self._last_discovery_at = monotonic()
            devices = self._list_devices_once()
        enriched_devices = self._enrich_devices(_dedupe_devices(devices))
        return _dedupe_device_aliases(enriched_devices)

    def connect_endpoint(self, endpoint: str) -> DeviceInfo:
        serial = normalize_adb_endpoint(endpoint)
        try:
            self._run(["connect", serial], text=True)
        except AppError as exc:
            if exc.code == ErrorCode.ADB_NOT_FOUND and self.adb_path is None:
                raise
            raise AppError(
                ErrorCode.ADB_CONNECT_FAILED,
                "ADB endpoint could not be connected.",
                {"endpoint": serial, "reason": exc.message},
            ) from exc

        devices = self._enrich_devices(_dedupe_devices(self._list_devices_once()))
        device = next((candidate for candidate in devices if candidate.device_id == serial), None)
        if device is None:
            raise AppError(
                ErrorCode.ADB_NO_DEVICES,
                "ADB endpoint did not appear in adb devices.",
                {"endpoint": serial},
            )
        return device

    def snapshot(self, device_id: str) -> bytes:
        result, _attempts = self._run_with_retry(
            ["-s", device_id, "exec-out", "screencap", "-p"],
            attempts=self.retry_config.snapshot_attempts,
        )
        return result.stdout

    def snapshot_raw(self, device_id: str) -> bytes:
        if self._run_command is not None or not self._fast_capture:
            return self.snapshot(device_id)
        with self._shells_lock:
            dc_session = self._droidcast_sessions.get(device_id)
        if dc_session is not None:
            prescaled = dc_session.capture_prescaled_720p()
            if prescaled is not None:
                return prescaled
        try:
            result, _attempts = self._run_with_retry(
                ["-s", device_id, "exec-out", "screencap"],
                attempts=1,
            )
            if _is_valid_raw_screencap(result.stdout):
                if (
                    dc_session is None
                    and self._droidcast_enabled
                    and self.adb_path is not None
                ):
                    apk = _default_droidcast_apk()
                    if apk is not None:
                        raw_w, raw_h = struct.unpack_from("<II", result.stdout, 0)
                        if raw_w > raw_h and abs(raw_w / raw_h - 16 / 9) < 0.02:
                            with self._shells_lock:
                                dc_session = self._droidcast_sessions.setdefault(
                                    device_id,
                                    _DroidCastSession(self.adb_path, device_id, apk, (raw_w, raw_h)),
                                )
                            prescaled = dc_session.capture_prescaled_720p()
                            if prescaled is not None:
                                return prescaled
                return result.stdout
        except AppError:
            pass
        return self.snapshot(device_id)

    def _fast_shell_exec(self, device_id: str, command: str) -> bool:
        if self._run_command is not None or not self._fast_input or self.adb_path is None:
            return False
        with self._shells_lock:
            self._shell_seq += 1
            token = str(self._shell_seq)
            shell = self._shells.get(device_id)
            if shell is None:
                shell = _PersistentAdbShell(
                    self.adb_path,
                    device_id,
                    timeout_seconds=min(float(self.timeout_seconds), 5.0),
                )
                self._shells[device_id] = shell
        return shell.execute(command, token)

    def close(self) -> None:
        with self._shells_lock:
            shells = list(self._shells.values())
            self._shells.clear()
            dc_sessions = list(self._droidcast_sessions.values())
            self._droidcast_sessions.clear()
        for shell in shells:
            shell.close()
        for dc in dc_sessions:
            dc.close()

    def tap(self, device_id: str, x: int, y: int) -> OperationResult:
        if self._fast_shell_exec(
            device_id,
            f"cmd input tap {int(x)} {int(y)} >/dev/null 2>&1 || input tap {int(x)} {int(y)}",
        ):
            return OperationResult(
                ok=True,
                action="tap",
                message=f"Tapped {x},{y}",
                data={"attempts": 1, "mode": "fast_shell"},
            )
        _result, attempts = self._run_with_retry(
            ["-s", device_id, "shell", "input", "tap", str(x), str(y)],
            text=True,
            attempts=self.retry_config.control_attempts,
        )
        return OperationResult(
            ok=True,
            action="tap",
            message=f"Tapped {x},{y}",
            data={"attempts": attempts},
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
        if self._fast_shell_exec(
            device_id,
            f"cmd input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)} >/dev/null 2>&1 || "
            f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}",
        ):
            return OperationResult(
                ok=True,
                action="swipe",
                message="Swipe sent",
                data={"attempts": 1, "mode": "fast_shell"},
            )
        _result, attempts = self._run_with_retry(
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
            attempts=self.retry_config.control_attempts,
        )
        return OperationResult(
            ok=True,
            action="swipe",
            message="Swipe sent",
            data={"attempts": attempts},
        )

    def _motionevent(
        self,
        device_id: str,
        event: str,
        x: int,
        y: int,
        action: str,
    ) -> OperationResult:
        ix, iy = int(x), int(y)
        fallback_cmd = (
            f"cmd input motionevent {event} {ix} {iy} >/dev/null 2>&1 || "
            f"input motionevent {event} {ix} {iy}"
        )
        if event == "CANCEL":
            fallback_cmd = (
                f"cmd input motionevent CANCEL {ix} {iy} >/dev/null 2>&1 || "
                f"cmd input motionevent UP {ix} {iy} >/dev/null 2>&1 || "
                f"input motionevent UP {ix} {iy}"
            )
        if self._fast_shell_exec(device_id, fallback_cmd):
            return OperationResult(
                ok=True,
                action=action,
                message=f"Touch {event.lower()} {ix},{iy}",
                data={"attempts": 1, "mode": "fast_shell"},
            )
        _result, attempts = self._run_with_retry(
            [
                "-s",
                device_id,
                "shell",
                "input",
                "motionevent",
                "UP" if event == "CANCEL" else event,
                str(ix),
                str(iy),
            ],
            text=True,
            attempts=self.retry_config.control_attempts,
        )
        return OperationResult(
            ok=True,
            action=action,
            message=f"Touch {event.lower()} {ix},{iy}",
            data={"attempts": attempts},
        )

    def touch_down(self, device_id: str, x: int, y: int) -> OperationResult:
        return self._motionevent(device_id, "DOWN", x, y, "touch_down")

    def touch_move(self, device_id: str, x: int, y: int) -> OperationResult:
        return self._motionevent(device_id, "MOVE", x, y, "touch_move")

    def touch_up(self, device_id: str, x: int, y: int) -> OperationResult:
        return self._motionevent(device_id, "UP", x, y, "touch_up")

    def touch_cancel(self, device_id: str, x: int, y: int) -> OperationResult:
        return self._motionevent(device_id, "CANCEL", x, y, "touch_cancel")

    def restart_game(
        self,
        device_id: str,
        package_name: str | None = None,
    ) -> OperationResult:
        package = package_name.strip() if isinstance(package_name, str) else ""
        if not package:
            result, _attempts = self._run_with_retry(
                ["-s", device_id, "shell", "pm", "list", "packages"],
                text=True,
                attempts=self.retry_config.control_attempts,
            )
            packages = sorted(
                line.partition(":")[2].strip()
                for line in result.stdout.splitlines()
                if line.startswith("package:")
                and _looks_like_fgo_package(line.partition(":")[2].strip())
            )
            if len(packages) != 1:
                raise AppError(
                    ErrorCode.ADB_COMMAND_FAILED,
                    "Unable to identify one installed FGO package.",
                    {"device_id": device_id, "packages": packages},
                )
            package = packages[0]

        _result, attempts = self._run_with_retry(
            [
                "-s",
                device_id,
                "shell",
                "monkey",
                "-p",
                package,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ],
            text=True,
            attempts=self.retry_config.control_attempts,
        )
        return OperationResult(
            ok=True,
            action="restart_game",
            message=f"Started {package}",
            data={"package": package, "attempts": attempts},
        )

    def _run_with_retry(
        self,
        args: list[str],
        *,
        attempts: int,
        text: bool = False,
    ) -> tuple[subprocess.CompletedProcess, int]:
        delay = min(
            self.retry_config.initial_delay_seconds,
            self.retry_config.max_delay_seconds,
        )
        last_error: AppError | None = None
        for attempt in range(1, max(attempts, 1) + 1):
            try:
                return self._run(args, text=text), attempt
            except AppError as exc:
                last_error = exc
                if attempt >= attempts or exc.code not in _retryable_codes(args):
                    break
                logger.warning(
                    "Retrying ADB command after failure.",
                    extra={
                        "adb_args": args,
                        "attempt": attempt,
                        "max_attempts": attempts,
                        "error_code": exc.code.value,
                    },
                )
                if delay > 0:
                    self._sleep(delay)
                delay = min(delay * 2, self.retry_config.max_delay_seconds)
        assert last_error is not None
        raise AppError(
            last_error.code,
            last_error.message,
            {**last_error.details, "attempts": max(attempts, 1)},
        ) from last_error

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
            display_size = parse_adb_display_size(wm_size)
            details["wm_size"] = (
                f"{display_size[0]}x{display_size[1]}" if display_size else wm_size
            )
            if display_size:
                details["display_size"] = {
                    "width": display_size[0],
                    "height": display_size[1],
                }
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
        try:
            if self._run_command is not None:
                result = self._run_command(command, text, timeout)
                if result.returncode != 0:
                    raise subprocess.CalledProcessError(
                        result.returncode,
                        command,
                        output=result.stdout,
                        stderr=result.stderr,
                    )
                return result
            return subprocess.run(command, check=True, capture_output=True, timeout=timeout, text=text)
        except subprocess.TimeoutExpired as exc:
            raise AppError(
                ErrorCode.ADB_TIMEOUT,
                "ADB command timed out.",
                {"args": args},
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr = _decode_output(exc.stderr)
            raise AppError(
                _command_error_code(args),
                stderr or "ADB command failed.",
                {"args": args, "returncode": exc.returncode},
            ) from exc
        except OSError as exc:
            raise AppError(
                _command_error_code(args),
                str(exc) or "ADB executable could not be started.",
                {"args": args},
            ) from exc

    @staticmethod
    def _find_adb(candidates: list[Path]) -> Path | None:
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None


def _dedupe_devices(devices: list[DeviceInfo]) -> list[DeviceInfo]:
    deduped: dict[str, DeviceInfo] = {}
    for device in devices:
        deduped[device.device_id] = device
    return list(deduped.values())


def _looks_like_fgo_package(package: str) -> bool:
    normalized = package.casefold()
    return "fategrandorder" in normalized or normalized.endswith(".fatego")


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


def _command_error_code(args: list[str]) -> ErrorCode:
    if "screencap" in args:
        return ErrorCode.SNAPSHOT_FAILED
    if "input" in args and "tap" in args:
        return ErrorCode.TAP_FAILED
    if "input" in args and "swipe" in args:
        return ErrorCode.SWIPE_FAILED
    return ErrorCode.ADB_COMMAND_FAILED


def _retryable_codes(args: list[str]) -> set[ErrorCode]:
    return {ErrorCode.ADB_TIMEOUT, _command_error_code(args)}


def _decode_output(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return value.strip() if isinstance(value, str) else ""
