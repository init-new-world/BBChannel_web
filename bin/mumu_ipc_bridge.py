#!/usr/bin/env python3
"""Windows-side MuMu external_renderer_ipc.dll TCP bridge for WSL/remote hosts.

Run natively on Windows (requires zero third-party packages):
    python web\\bin\\mumu_ipc_bridge.py --host 0.0.0.0 --port 17555

Then point WSL / Linux BBChannel Web at the Windows host IP:
    BBCHANNEL_MUMU_BRIDGE=172.25.208.1:17555 uvicorn webapp.app:app
"""

from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path
import platform
import socketserver
import struct
import sys
from threading import Lock

DLL_NAME = "external_renderer_ipc.dll"
DLL_LAYOUTS = (
    Path("nx_main") / "sdk" / DLL_NAME,
    Path("shell") / "sdk" / DLL_NAME,
    Path("nx_device") / "12.0" / "shell" / "sdk" / DLL_NAME,
)
DEFAULT_INSTALL_PATHS = (
    Path(r"C:\Program Files\Netease\MuMu"),
    Path(r"C:\Program Files\Netease\MuMuPlayer-12.0"),
    Path(r"D:\Program Files\Netease\MuMuPlayer-12.0"),
    Path(r"F:\Program Files\Netease\MuMuPlayer-12.0"),
)


def discover_mumu_dll(explicit_install: str | None = None) -> tuple[Path | None, Path | None]:
    candidates: list[Path] = []
    if explicit_install:
        candidates.append(Path(explicit_install))
    saved = Path(__file__).resolve().parents[2] / "MuMuInstallPath.txt"
    if saved.exists():
        raw = saved.read_text(encoding="utf-8", errors="ignore").strip()
        if raw:
            candidates.append(Path(raw))
    candidates.extend(DEFAULT_INSTALL_PATHS)
    for root in candidates:
        for rel in DLL_LAYOUTS:
            dll = root / rel
            if dll.exists():
                return root, dll
    return None, None


class NativeMumuRuntime:
    REQUIRED_EXPORTS = (
        "nemu_connect",
        "nemu_disconnect",
        "nemu_capture_display",
        "nemu_input_event_touch_down",
        "nemu_input_event_touch_up",
    )

    def __init__(self, install_path: Path | None, dll_path: Path | None) -> None:
        self.install_path = install_path
        self.dll_path = dll_path
        self._lock = Lock()
        self._dll = None
        self._error: str | None = None
        self._buf_type = None
        self._buf = None
        self._buf_size = 0
        if platform.system() != "Windows":
            self._error = "mumu_ipc_bridge.py must be executed with Windows python.exe."
            return
        if dll_path is None:
            self._error = "MuMu external_renderer_ipc.dll was not found."
            return
        try:
            dll = ctypes.CDLL(str(dll_path))
            missing = [name for name in self.REQUIRED_EXPORTS if not hasattr(dll, name)]
            if missing:
                self._error = f"Missing exports: {missing}"
                return
            dll.nemu_connect.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
            dll.nemu_connect.restype = ctypes.c_int
            dll.nemu_disconnect.argtypes = [ctypes.c_int]
            dll.nemu_disconnect.restype = None
            dll.nemu_capture_display.argtypes = [
                ctypes.c_int,
                ctypes.c_uint,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_ubyte),
            ]
            dll.nemu_capture_display.restype = ctypes.c_int
            dll.nemu_input_event_touch_down.argtypes = [
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
            ]
            dll.nemu_input_event_touch_down.restype = ctypes.c_int
            dll.nemu_input_event_touch_up.argtypes = [ctypes.c_int, ctypes.c_int]
            dll.nemu_input_event_touch_up.restype = ctypes.c_int
            self._dll = dll
        except Exception as exc:
            self._error = str(exc)

    def is_ready(self) -> bool:
        return self._dll is not None and self._error is None

    def diagnostics(self) -> dict[str, object]:
        return {
            "library_loaded": self._dll is not None,
            "exports_complete": self._dll is not None,
            "invocation_ready": self.is_ready(),
            "missing_exports": [],
            "native_error": self._error,
            "install_path": str(self.install_path) if self.install_path else None,
            "dll_path": str(self.dll_path) if self.dll_path else None,
        }

    def handle_op(self, req: dict[str, object]) -> tuple[dict[str, object], bytes]:
        op = str(req.get("op", ""))
        if op == "ping":
            return {"ok": True, "ready": self.is_ready()}, b""
        if op == "diagnostics":
            return {"ok": True, "diagnostics": self.diagnostics()}, b""
        if not self.is_ready() or self._dll is None:
            return {"ok": False, "code": -1, "error": self._error or "Not ready"}, b""
        with self._lock:
            dll = self._dll
            if op == "connect":
                raw_install = str(req.get("install_path") or "")
                target = Path(raw_install) if raw_install and Path(raw_install).exists() else self.install_path
                assert target is not None
                handle = int(dll.nemu_connect(str(target.absolute()), int(req["instance_index"])))
                if handle <= 0:
                    return {"ok": False, "code": handle, "error": f"nemu_connect failed ({handle})"}, b""
                return {"ok": True, "handle": handle}, b""
            if op == "disconnect":
                dll.nemu_disconnect(int(req["handle"]))
                return {"ok": True}, b""
            if op == "capture_display":
                handle = int(req["handle"])
                display_id = int(req.get("display_id", 0))
                width = ctypes.c_int(0)
                height = ctypes.c_int(0)
                empty = (ctypes.c_ubyte * 0)()
                rc = int(dll.nemu_capture_display(handle, display_id, 0, ctypes.byref(width), ctypes.byref(height), empty))
                if rc != 0:
                    return {"ok": False, "code": rc, "error": f"nemu_capture_display size query failed ({rc})"}, b""
                size = width.value * height.value * 4
                if self._buf is None or self._buf_size != size:
                    self._buf = (ctypes.c_ubyte * size)()
                    self._buf_size = size
                rc = int(dll.nemu_capture_display(handle, display_id, size, ctypes.byref(width), ctypes.byref(height), self._buf))
                if rc != 0:
                    return {"ok": False, "code": rc, "error": f"nemu_capture_display failed ({rc})"}, b""
                blob = ctypes.string_at(self._buf, size)
                return {
                    "ok": True,
                    "width": width.value,
                    "height": height.value,
                    "bottom_up": True,
                    "blob_len": len(blob),
                }, blob
            if op == "touch_down":
                rc = int(
                    dll.nemu_input_event_touch_down(
                        int(req["handle"]),
                        int(req.get("display_id", 0)),
                        int(req["x"]),
                        int(req["y"]),
                    )
                )
                if rc != 0:
                    return {"ok": False, "code": rc, "error": f"touch_down failed ({rc})"}, b""
                return {"ok": True}, b""
            if op == "touch_up":
                rc = int(dll.nemu_input_event_touch_up(int(req["handle"]), int(req.get("display_id", 0))))
                if rc != 0:
                    return {"ok": False, "code": rc, "error": f"touch_up failed ({rc})"}, b""
                return {"ok": True}, b""
            return {"ok": False, "code": -2, "error": f"Unknown op: {op}"}, b""


def _recv_exact(conn, size: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < size:
        chunk = conn.recv(size - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def main() -> int:
    parser = argparse.ArgumentParser(description="MuMu IPC high-speed bridge server.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=17555)
    parser.add_argument("--install-path", default=None)
    args = parser.parse_args()

    install_path, dll_path = discover_mumu_dll(args.install_path)
    runtime = NativeMumuRuntime(install_path, dll_path)
    print(f"[mumu-bridge] diagnostics={runtime.diagnostics()}", flush=True)

    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            self.request.setsockopt(socketserver.socket.IPPROTO_TCP, socketserver.socket.TCP_NODELAY, 1)
            while True:
                hdr = _recv_exact(self.request, 4)
                if hdr is None:
                    return
                (req_len,) = struct.unpack("<I", hdr)
                raw = _recv_exact(self.request, req_len)
                if raw is None:
                    return
                req = json.loads(raw.decode("utf-8"))
                resp_hdr, blob = runtime.handle_op(req)
                resp_hdr.setdefault("blob_len", len(blob))
                encoded_hdr = json.dumps(resp_hdr).encode("utf-8")
                self.request.sendall(struct.pack("<I", len(encoded_hdr)) + encoded_hdr + blob)

    class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with Server((args.host, args.port), Handler) as srv:
        print(f"[mumu-bridge] listening on {args.host}:{args.port}", flush=True)
        srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
