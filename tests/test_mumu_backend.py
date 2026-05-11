from pathlib import Path

from webapp.devices.mumu import MumuBackend


def test_mumu_unavailable_on_non_windows(tmp_path: Path):
    backend = MumuBackend(platform_name="Linux", install_paths=[tmp_path])

    capability = backend.capability()

    assert capability.available is False
    assert "Windows" in capability.reason


def test_mumu_available_when_windows_dll_exists(tmp_path: Path):
    dll = tmp_path / "shell" / "sdk" / "external_renderer_ipc.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"dll")

    backend = MumuBackend(platform_name="Windows", install_paths=[tmp_path])

    capability = backend.capability()
    assert capability.available is True
    assert capability.reason is None
    assert backend.dll_path == dll


def test_mumu_reports_missing_dll_on_windows(tmp_path: Path):
    backend = MumuBackend(platform_name="Windows", install_paths=[tmp_path])

    capability = backend.capability()

    assert capability.available is False
    assert "external_renderer_ipc.dll" in capability.reason
