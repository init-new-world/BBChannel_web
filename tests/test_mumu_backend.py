import ctypes
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from webapp.core.errors import AppError, ErrorCode
from webapp.devices.mumu import (
    CtypesMumuNativeApi,
    MumuBackend,
    MumuNativeCallError,
    MumuNativeFrame,
)


class FakeNativeApi:
    def __init__(
        self,
        ready: bool = True,
        frame: MumuNativeFrame | None = None,
    ) -> None:
        self.ready = ready
        self.frame = frame
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
        if self.frame is not None:
            return self.frame
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


class FakeDllFunction:
    def __init__(self, result=0, callback=None) -> None:
        self.result = result
        self.callback = callback
        self.calls: list[tuple] = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        if self.callback is not None:
            return self.callback(*args)
        return self.result


class FakeDll:
    def __init__(self) -> None:
        self.nemu_connect = FakeDllFunction(result=42)
        self.nemu_disconnect = FakeDllFunction(result=None)
        self.nemu_capture_display = FakeDllFunction(callback=self._capture)
        self.nemu_input_event_touch_down = FakeDllFunction()
        self.nemu_input_event_touch_up = FakeDllFunction()

    @staticmethod
    def _capture(handle, display_id, buffer_size, width, height, pixels):
        width._obj.value = 2
        height._obj.value = 1
        if buffer_size:
            for index, value in enumerate(b"\x01\x02\x03\x04\x05\x06\x07\x08"):
                pixels[index] = value
        return 0


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
    native = FakeNativeApi(
        frame=MumuNativeFrame(
            width=200,
            height=100,
            pixels=b"\x00" * (200 * 100 * 4),
        )
    )
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
        (100, 0, 80, 10),
        (100, 0, 100, 0),
        (100, 0, 70, 15),
        (100, 0, 40, 30),
    ]
    assert native.touch_up_calls == [(100, 0), (100, 0)]
    assert delays == [0.1, 0.1, 0.1]
    assert native.capture_calls == [(100, 0)]


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


def test_mumu_current_layout_connects_with_top_level_install_path(tmp_path: Path):
    dll = tmp_path / "nx_device" / "12.0" / "shell" / "sdk" / "external_renderer_ipc.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"dll")
    native = FakeNativeApi()
    backend = MumuBackend(
        platform_name="Windows",
        install_paths=[tmp_path],
        native_api=native,
    )

    backend.snapshot("mumu:0")

    assert native.connect_calls == [(tmp_path, 0)]


def test_ctypes_api_binds_verified_exports_and_calls_connect(tmp_path: Path):
    dll_path = _create_dll(tmp_path)
    dll = FakeDll()
    loaded_paths: list[str] = []

    api = CtypesMumuNativeApi(
        dll_path,
        platform_name="Windows",
        load_library=lambda path: loaded_paths.append(path) or dll,
    )

    handle = api.connect(tmp_path, 3)

    assert api.is_ready() is True
    assert loaded_paths == [str(dll_path)]
    assert dll.nemu_connect.calls == [(str(tmp_path), 3)]
    assert dll.nemu_connect.argtypes == [ctypes.c_wchar_p, ctypes.c_int]
    assert dll.nemu_connect.restype is ctypes.c_int
    assert dll.nemu_disconnect.argtypes == [ctypes.c_int]
    assert dll.nemu_capture_display.argtypes[0:3] == [
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_int,
    ]
    assert handle == 42


def test_ctypes_api_captures_dimensions_then_rgba_pixels(tmp_path: Path):
    dll = FakeDll()
    api = CtypesMumuNativeApi(
        _create_dll(tmp_path),
        platform_name="Windows",
        load_library=lambda path: dll,
    )

    frame = api.capture_display(42, 0)

    assert frame == MumuNativeFrame(
        width=2,
        height=1,
        pixels=b"\x01\x02\x03\x04\x05\x06\x07\x08",
        bottom_up=True,
    )
    assert [call[2] for call in dll.nemu_capture_display.calls] == [0, 8]


def test_ctypes_api_rejects_failed_native_operation(tmp_path: Path):
    dll = FakeDll()
    dll.nemu_input_event_touch_down.result = -7
    api = CtypesMumuNativeApi(
        _create_dll(tmp_path),
        platform_name="Windows",
        load_library=lambda path: dll,
    )

    with pytest.raises(MumuNativeCallError) as exc_info:
        api.touch_down(42, 0, 10, 20)

    assert exc_info.value.function == "nemu_input_event_touch_down"
    assert exc_info.value.result == -7


def test_ctypes_api_reports_missing_exports_without_invocation(tmp_path: Path):
    dll = FakeDll()
    del dll.nemu_input_event_touch_up

    api = CtypesMumuNativeApi(
        _create_dll(tmp_path),
        platform_name="Windows",
        load_library=lambda path: dll,
    )

    diagnostics = api.diagnostics()
    assert api.is_ready() is False
    assert diagnostics["library_loaded"] is True
    assert diagnostics["exports_complete"] is False
    assert diagnostics["missing_exports"] == ["nemu_input_event_touch_up"]


def test_ctypes_api_does_not_load_windows_dll_on_other_platforms(tmp_path: Path):
    load_calls: list[str] = []

    api = CtypesMumuNativeApi(
        _create_dll(tmp_path),
        platform_name="Linux",
        load_library=lambda path: load_calls.append(path),
    )

    assert api.is_ready() is False
    assert load_calls == []
    assert "Windows" in api.diagnostics()["native_error"]


def test_ctypes_api_rejects_unreasonable_frame_allocation(tmp_path: Path):
    dll = FakeDll()

    def huge_capture(handle, display_id, buffer_size, width, height, pixels):
        width._obj.value = 100_000
        height._obj.value = 100_000
        return 0

    dll.nemu_capture_display.callback = huge_capture
    api = CtypesMumuNativeApi(
        _create_dll(tmp_path),
        platform_name="Windows",
        load_library=lambda path: dll,
        max_frame_bytes=1024,
    )

    with pytest.raises(MumuNativeCallError) as exc_info:
        api.capture_display(42, 0)

    assert "frame size" in str(exc_info.value)
