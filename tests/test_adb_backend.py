from pathlib import Path
from subprocess import CompletedProcess

import pytest

from webapp.core.errors import AppError, ErrorCode
from webapp.devices.adb import (
    AdbBackend,
    AdbDiscoveryConfig,
    candidate_adb_endpoints,
    detect_wsl_host_ip,
    normalize_adb_endpoint,
    parse_adb_devices,
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


def test_find_adb_prefers_existing_candidate(tmp_path: Path):
    candidate = tmp_path / "adb"
    candidate.write_text("", encoding="utf-8")

    backend = AdbBackend(adb_candidates=[candidate])

    assert backend.adb_path == candidate
