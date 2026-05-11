from pathlib import Path

from webapp.devices.adb import AdbBackend, parse_adb_devices


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


def test_find_adb_prefers_existing_candidate(tmp_path: Path):
    candidate = tmp_path / "adb"
    candidate.write_text("", encoding="utf-8")

    backend = AdbBackend(adb_candidates=[candidate])

    assert backend.adb_path == candidate
