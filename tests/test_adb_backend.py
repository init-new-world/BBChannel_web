from pathlib import Path
from subprocess import CompletedProcess

import pytest

from webapp.core.errors import AppError, ErrorCode
from webapp.devices.adb import (
    AdbBackend,
    AdbDiscoveryConfig,
    AdbRetryConfig,
    candidate_adb_endpoints,
    detect_wsl_host_ip,
    normalize_adb_endpoint,
    parse_adb_devices,
    parse_adb_display_size,
)


def test_parse_adb_devices_returns_empty_for_no_devices():
    output = "List of devices attached\n\n"

    assert parse_adb_devices(output) == []


def test_parse_adb_devices_returns_online_device():
    output = "List of devices attached\nemulator-5554\tdevice\n"

    devices = parse_adb_devices(output)

    assert len(devices) == 1
    assert devices[0].device_id == "emulator-5554"
    assert devices[0].status == "device"
    assert devices[0].backend == "adb"


def test_parse_adb_devices_keeps_offline_device_status():
    output = "List of devices attached\n127.0.0.1:7555\toffline\n"

    devices = parse_adb_devices(output)

    assert devices[0].status == "offline"


def test_parse_adb_devices_handles_multiple_devices_and_ignores_blanks():
    output = (
        "List of devices attached\n"
        "\n"
        "emulator-5554\tdevice\n"
        "127.0.0.1:7555\tdevice product:foo model:bar\n"
    )

    devices = parse_adb_devices(output)

    assert [device.device_id for device in devices] == ["emulator-5554", "127.0.0.1:7555"]


def test_parse_adb_devices_keeps_device_details_from_long_output():
    output = (
        "List of devices attached\n"
        "172.25.208.1:16384 device product:aurora model:24031PN0DC "
        "device:aurora transport_id:1\n"
    )

    devices = parse_adb_devices(output)

    assert devices[0].device_id == "172.25.208.1:16384"
    assert devices[0].name == "24031PN0DC"
    assert devices[0].source == "adb-devices"
    assert devices[0].details == {
        "product": "aurora",
        "model": "24031PN0DC",
        "device": "aurora",
        "transport_id": "1",
    }


def test_parse_adb_display_size_prefers_active_override():
    output = "Physical size: 2560x1440\nOverride size: 1920x1080\n"

    assert parse_adb_display_size(output) == (1920, 1080)


def test_detect_wsl_host_ip_reads_first_nameserver(tmp_path: Path):
    resolv_conf = tmp_path / "resolv.conf"
    resolv_conf.write_text("nameserver 172.25.208.1\nnameserver 1.1.1.1\n", encoding="utf-8")

    assert detect_wsl_host_ip(resolv_conf, env={"WSL_DISTRO_NAME": "Ubuntu"}) == "172.25.208.1"


def test_candidate_adb_endpoints_expands_auto_hosts_without_duplicates():
    config = AdbDiscoveryConfig(scan_hosts=("auto", "172.25.208.1"), scan_ports=(5555, 16384))

    assert candidate_adb_endpoints(config, wsl_host_ip="172.25.208.1") == [
        ("172.25.208.1", 5555),
        ("172.25.208.1", 16384),
        ("127.0.0.1", 5555),
        ("127.0.0.1", 16384),
        ("localhost", 5555),
        ("localhost", 16384),
    ]


def test_discovery_config_reads_environment_overrides():
    config = AdbDiscoveryConfig.from_env(
        {
            "BBCHANNEL_ADB_AUTO_CONNECT": "0",
            "BBCHANNEL_ADB_SCAN_HOSTS": "auto,192.168.1.5",
            "BBCHANNEL_ADB_SCAN_PORTS": "16384,7555",
            "BBCHANNEL_ADB_CONNECT_TIMEOUT_MS": "450",
        }
    )

    assert config.auto_connect is False
    assert config.scan_hosts == ("auto", "192.168.1.5")
    assert config.scan_ports == (16384, 7555)
    assert config.probe_timeout_seconds == 0.45


def test_normalize_adb_endpoint_accepts_host_port():
    assert normalize_adb_endpoint(" 172.25.208.1:16384 ") == "172.25.208.1:16384"


def test_normalize_adb_endpoint_rejects_missing_or_invalid_port():
    with pytest.raises(AppError) as exc:
        normalize_adb_endpoint("172.25.208.1")

    assert exc.value.code == ErrorCode.ADB_CONNECT_FAILED


def test_connect_endpoint_runs_adb_connect_and_returns_matching_device(tmp_path: Path):
    candidate = tmp_path / "adb"
    candidate.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    def run_command(command: list[str], text: bool, timeout_seconds: float):
        calls.append(command[1:])
        args = command[1:]
        if args == ["connect", "172.25.208.1:16384"]:
            return CompletedProcess(command, 0, stdout="connected to 172.25.208.1:16384\n", stderr="")
        if args == ["devices", "-l"]:
            return CompletedProcess(
                command,
                0,
                stdout=(
                    "List of devices attached\n"
                    "172.25.208.1:16384 device product:aurora model:24031PN0DC device:aurora\n"
                ),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {args}")

    backend = AdbBackend(
        adb_candidates=[candidate],
        discovery_config=AdbDiscoveryConfig(auto_connect=False, enrich_details=False),
        run_command=run_command,
    )

    device = backend.connect_endpoint(" 172.25.208.1:16384 ")

    assert device.device_id == "172.25.208.1:16384"
    assert device.name == "24031PN0DC"
    assert calls == [["connect", "172.25.208.1:16384"], ["devices", "-l"]]


def test_restart_game_discovers_and_launches_installed_fgo_package(tmp_path: Path):
    candidate = tmp_path / "adb"
    candidate.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    def run_command(command: list[str], text: bool, timeout_seconds: float):
        calls.append(command[1:])
        args = command[1:]
        if args[-4:] == ["shell", "pm", "list", "packages"]:
            return CompletedProcess(
                command,
                0,
                stdout="package:com.android.settings\npackage:com.bilibili.fatego\n",
                stderr="",
            )
        if "monkey" in args:
            return CompletedProcess(command, 0, stdout="Events injected: 1\n", stderr="")
        raise AssertionError(f"unexpected command: {args}")

    backend = AdbBackend(adb_candidates=[candidate], run_command=run_command)

    result = backend.restart_game("emulator-5554")

    assert result.ok is True
    assert result.action == "restart_game"
    assert result.data["package"] == "com.bilibili.fatego"
    assert calls == [
        ["-s", "emulator-5554", "shell", "pm", "list", "packages"],
        [
            "-s",
            "emulator-5554",
            "shell",
            "monkey",
            "-p",
            "com.bilibili.fatego",
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        ],
    ]


def test_restart_game_rejects_ambiguous_fgo_packages(tmp_path: Path):
    candidate = tmp_path / "adb"
    candidate.write_text("", encoding="utf-8")

    def run_command(command: list[str], _text: bool, _timeout_seconds: float):
        return CompletedProcess(
            command,
            0,
            stdout=(
                "package:com.bilibili.fatego\n"
                "package:com.aniplex.fategrandorder\n"
            ),
            stderr="",
        )

    backend = AdbBackend(adb_candidates=[candidate], run_command=run_command)

    with pytest.raises(AppError) as exc:
        backend.restart_game("emulator-5554")

    assert exc.value.code == ErrorCode.ADB_COMMAND_FAILED
    assert exc.value.details["packages"] == [
        "com.aniplex.fategrandorder",
        "com.bilibili.fatego",
    ]


def test_list_devices_auto_connects_open_candidate_once(tmp_path: Path):
    candidate = tmp_path / "adb"
    candidate.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    def run_command(command: list[str], text: bool, timeout_seconds: float):
        calls.append(command[1:])
        args = command[1:]
        if args == ["devices", "-l"] and len([call for call in calls if call == args]) == 1:
            return CompletedProcess(command, 0, stdout="List of devices attached\n", stderr="")
        if args == ["connect", "172.25.208.1:16384"]:
            return CompletedProcess(command, 0, stdout="connected to 172.25.208.1:16384\n", stderr="")
        if args == ["devices", "-l"]:
            return CompletedProcess(
                command,
                0,
                stdout=(
                    "List of devices attached\n"
                    "172.25.208.1:16384 device product:aurora model:24031PN0DC device:aurora\n"
                ),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {args}")

    backend = AdbBackend(
        adb_candidates=[candidate],
        discovery_config=AdbDiscoveryConfig(
            scan_hosts=("172.25.208.1",),
            scan_ports=(16384,),
            enrich_details=False,
        ),
        probe_tcp=lambda host, port, timeout: host == "172.25.208.1" and port == 16384,
        run_command=run_command,
    )

    devices = backend.list_devices()

    assert [device.device_id for device in devices] == ["172.25.208.1:16384"]
    assert ["connect", "172.25.208.1:16384"] in calls


def test_list_devices_deduplicates_aliases_by_android_id(tmp_path: Path):
    candidate = tmp_path / "adb"
    candidate.write_text("", encoding="utf-8")

    def run_command(command: list[str], text: bool, timeout_seconds: float):
        args = command[1:]
        if args == ["devices", "-l"]:
            return CompletedProcess(
                command,
                0,
                stdout=(
                    "List of devices attached\n"
                    "172.25.208.1:16384 device product:aurora model:24031PN0DC device:aurora\n"
                    "172.25.208.1:7555 device product:aurora model:24031PN0DC device:aurora\n"
                ),
                stderr="",
            )
        if len(args) >= 3 and args[0] == "-s" and args[2] == "shell":
            shell_args = args[3:]
            if shell_args == ["settings", "get", "secure", "android_id"]:
                return CompletedProcess(command, 0, stdout="cedc10406839cb1\n", stderr="")
            if shell_args == ["su", "-c", "id"]:
                return CompletedProcess(command, 0, stdout="uid=0(root)\n", stderr="")
            return CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {args}")

    backend = AdbBackend(
        adb_candidates=[candidate],
        discovery_config=AdbDiscoveryConfig(auto_connect=False),
        run_command=run_command,
    )

    devices = backend.list_devices()

    assert [device.device_id for device in devices] == ["172.25.208.1:16384"]
    assert devices[0].details["android_id"] == "cedc10406839cb1"


def test_list_devices_exposes_effective_adb_display_size(tmp_path: Path):
    candidate = tmp_path / "adb"
    candidate.write_text("", encoding="utf-8")

    def run_command(command: list[str], text: bool, timeout_seconds: float):
        args = command[1:]
        if args == ["devices", "-l"]:
            return CompletedProcess(
                command,
                0,
                stdout="List of devices attached\nemulator-5554 device model:Demo\n",
                stderr="",
            )
        if args[-3:] == ["shell", "wm", "size"]:
            return CompletedProcess(
                command,
                0,
                stdout="Physical size: 2560x1440\nOverride size: 1920x1080\n",
                stderr="",
            )
        if len(args) >= 3 and args[0] == "-s" and args[2] == "shell":
            return CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(args)

    backend = AdbBackend(
        adb_candidates=[candidate],
        discovery_config=AdbDiscoveryConfig(auto_connect=False),
        run_command=run_command,
    )

    device = backend.list_devices()[0]

    assert device.details["wm_size"] == "1920x1080"
    assert device.details["display_size"] == {"width": 1920, "height": 1080}


def test_find_adb_prefers_existing_candidate(tmp_path: Path):
    candidate = tmp_path / "adb"
    candidate.write_text("", encoding="utf-8")

    backend = AdbBackend(adb_candidates=[candidate])

    assert backend.adb_path == candidate


def test_snapshot_retries_transient_command_failure(tmp_path: Path):
    candidate = tmp_path / "adb"
    candidate.write_text("", encoding="utf-8")
    attempts = 0
    delays: list[float] = []

    def run_command(command: list[str], text: bool, timeout_seconds: float):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return CompletedProcess(command, 1, stdout=b"", stderr=b"device offline")
        return CompletedProcess(command, 0, stdout=b"png", stderr=b"")

    backend = AdbBackend(
        adb_candidates=[candidate],
        run_command=run_command,
        retry_config=AdbRetryConfig(snapshot_attempts=3, initial_delay_seconds=0.2),
        sleep=delays.append,
    )

    assert backend.snapshot("device-1") == b"png"
    assert attempts == 2
    assert delays == [0.2]


def test_tap_reports_retry_attempt_count(tmp_path: Path):
    candidate = tmp_path / "adb"
    candidate.write_text("", encoding="utf-8")
    attempts = 0

    def run_command(command: list[str], text: bool, timeout_seconds: float):
        nonlocal attempts
        attempts += 1
        return CompletedProcess(
            command,
            0 if attempts == 2 else 1,
            stdout="",
            stderr="transport error",
        )

    backend = AdbBackend(
        adb_candidates=[candidate],
        run_command=run_command,
        retry_config=AdbRetryConfig(control_attempts=2, initial_delay_seconds=0),
    )

    result = backend.tap("device-1", 10, 20)

    assert result.data == {"attempts": 2}


def test_adb_failure_uses_action_specific_error_and_attempts(tmp_path: Path):
    candidate = tmp_path / "adb"
    candidate.write_text("", encoding="utf-8")

    def run_command(command: list[str], text: bool, timeout_seconds: float):
        return CompletedProcess(command, 1, stdout="", stderr="input failed")

    backend = AdbBackend(
        adb_candidates=[candidate],
        run_command=run_command,
        retry_config=AdbRetryConfig(control_attempts=2, initial_delay_seconds=0),
    )

    with pytest.raises(AppError) as exc_info:
        backend.swipe("device-1", 1, 2, 3, 4, 300)

    assert exc_info.value.code == ErrorCode.SWIPE_FAILED
    assert exc_info.value.details["attempts"] == 2


def test_adb_diagnostics_reports_version_and_device_statuses(tmp_path: Path):
    candidate = tmp_path / "adb"
    candidate.write_text("", encoding="utf-8")

    def run_command(command: list[str], text: bool, timeout_seconds: float):
        args = command[1:]
        if args == ["version"]:
            return CompletedProcess(command, 0, stdout="Android Debug Bridge version 1.0.41\n", stderr="")
        if args == ["devices", "-l"]:
            return CompletedProcess(
                command,
                0,
                stdout="List of devices attached\none device\ntwo offline\n",
                stderr="",
            )
        raise AssertionError(args)

    backend = AdbBackend(adb_candidates=[candidate], run_command=run_command)

    diagnostics = backend.diagnostics()

    assert diagnostics["server_reachable"] is True
    assert diagnostics["version"] == "Android Debug Bridge version 1.0.41"
    assert diagnostics["device_count"] == 2
    assert diagnostics["device_statuses"] == {"device": 1, "offline": 1}
