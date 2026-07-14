from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from webapp.core.errors import AppError, ErrorCode
from webapp.devices.mumu import MumuBackend, MumuNativeFrame


class FakeNativeApi:
    def __init__(self, ready: bool = True) -> None:
        self.ready = ready
        self.connect_calls: list[tuple[Path, int]] = []
        self.disconnect_calls: list[int] = []
        self.capture_calls: list[tuple[int, int]] = []
        self.touch_down_calls: list[tuple[int, int, int, int]] = []
        self.touch_up_calls: list[tuple[int, int]] = []

    def is_ready(self) -> bool:
        return self.ready

    def diagnostics(self) -> dict[str, object]:
        return {
            "library_loaded": self.ready,
            "exports_complete": self.ready,
            "invocation_ready": self.ready,
            "missing_exports": [],
        }

    def connect(self, install_path: Path, instance_index: int) -> int:
        self.connect_calls.append((install_path, instance_index))
        return 100 + instance_index

    def disconnect(self, handle: int) -> None:
        self.disconnect_calls.append(handle)

    def capture_display(self, handle: int, display_id: int) -> MumuNativeFrame:
        self.capture_calls.append((handle, display_id))
        # Native MuMu frames are bottom-up RGBA rows.
        return MumuNativeFrame(
            width=2,
            height=2,
            pixels=(
                b"\x00\x00\xff\xff" b"\xff\xff\xff\xff"
                b"\xff\x00\x00\xff" b"\x00\xff\x00\xff"
            ),
            bottom_up=True,
        )

    def touch_down(self, handle: int, display_id: int, x: int, y: int) -> None:
        self.touch_down_calls.append((handle, display_id, x, y))

    def touch_up(self, handle: int, display_id: int) -> None:
        self.touch_up_calls.append((handle, display_id))


def _create_dll(root: Path) -> Path:
    dll = root / "shell" / "sdk" / "external_renderer_ipc.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"dll")
    return dll


def test_mumu_unavailable_on_non_windows(tmp_path: Path):
    backend = MumuBackend(platform_name="Linux", install_paths=[tmp_path])

    capability = backend.capability()

    assert capability.available is False
    assert "Windows" in capability.reason


def test_mumu_dll_alone_does_not_claim_native_operations_are_available(tmp_path: Path):
    _create_dll(tmp_path)

    backend = MumuBackend(platform_name="Windows", install_paths=[tmp_path])

    capability = backend.capability()
    assert capability.available is False
    assert "native adapter" in capability.reason


def test_mumu_available_when_native_api_is_ready(tmp_path: Path):
    dll = _create_dll(tmp_path)
    backend = MumuBackend(
        platform_name="Windows",
        install_paths=[tmp_path],
        native_api=FakeNativeApi(),
        instance_indices=(0, 2),
    )

    assert backend.capability().available is True
    assert backend.dll_path == dll
    assert [device.device_id for device in backend.list_devices()] == ["mumu:0", "mumu:2"]


def test_mumu_snapshot_reuses_connection_and_converts_bottom_up_rgba_to_png(tmp_path: Path):
    _create_dll(tmp_path)
    native = FakeNativeApi()
    backend = MumuBackend(
        platform_name="Windows",
        install_paths=[tmp_path],
        native_api=native,
    )

    first = backend.snapshot("mumu:0")
    second = backend.snapshot("mumu:0")

    assert first == second
    assert native.connect_calls == [(tmp_path, 0)]
    assert native.capture_calls == [(100, 0), (100, 0)]
    with Image.open(BytesIO(first)) as image:
        assert image.format == "PNG"
        assert image.size == (2, 2)
        assert image.getpixel((0, 0)) == (255, 0, 0, 255)
        assert image.getpixel((0, 1)) == (0, 0, 255, 255)


def test_mumu_tap_and_swipe_delegate_touch_events(tmp_path: Path):
    _create_dll(tmp_path)
    native = FakeNativeApi()
    delays: list[float] = []
    backend = MumuBackend(
        platform_name="Windows",
        install_paths=[tmp_path],
        native_api=native,
        sleep=delays.append,
        swipe_steps=3,
    )

    tap = backend.tap("mumu:0", 10, 20)
    swipe = backend.swipe("mumu:0", 0, 0, 30, 60, 300)

    assert tap.ok is True
    assert swipe.ok is True
    assert native.touch_down_calls == [
        (100, 0, 10, 20),
        (100, 0, 0, 0),
        (100, 0, 15, 30),
        (100, 0, 30, 60),
    ]
    assert native.touch_up_calls == [(100, 0), (100, 0)]
    assert delays == [0.1, 0.1, 0.1]


def test_mumu_close_disconnects_cached_sessions(tmp_path: Path):
    _create_dll(tmp_path)
    native = FakeNativeApi()
    backend = MumuBackend(
        platform_name="Windows",
        install_paths=[tmp_path],
        native_api=native,
        instance_indices=(0, 2),
    )
    backend.snapshot("mumu:0")
    backend.snapshot("mumu:2")

    backend.close()

    assert native.disconnect_calls == [100, 102]


def test_mumu_rejects_unconfigured_instance_id(tmp_path: Path):
    _create_dll(tmp_path)
    backend = MumuBackend(
        platform_name="Windows",
        install_paths=[tmp_path],
        native_api=FakeNativeApi(),
    )

    with pytest.raises(AppError) as exc_info:
        backend.snapshot("mumu:9")

    assert exc_info.value.code == ErrorCode.DEVICE_NOT_FOUND


def test_mumu_diagnostics_separates_dll_and_native_readiness(tmp_path: Path):
    dll = _create_dll(tmp_path)
    backend = MumuBackend(
        platform_name="Windows",
        install_paths=[tmp_path],
        native_api=FakeNativeApi(ready=False),
    )

    diagnostics = backend.diagnostics()

    assert diagnostics["dll_found"] is True
    assert diagnostics["dll_path"] == str(dll)
    assert diagnostics["library_loaded"] is False
    assert diagnostics["invocation_ready"] is False


def test_mumu_finds_current_mumu_12_layout(tmp_path: Path):
    dll = tmp_path / "nx_device" / "12.0" / "shell" / "sdk" / "external_renderer_ipc.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"dll")

    backend = MumuBackend(platform_name="Windows", install_paths=[tmp_path])

    assert backend.dll_path == dll
