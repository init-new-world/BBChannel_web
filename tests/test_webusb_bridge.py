from __future__ import annotations

import asyncio
from io import BytesIO
import json
from pathlib import Path
import shutil
import socket
import struct
import threading
import time

from PIL import Image
import pytest

from tests.test_client import create_test_client
from webapp.app import create_app
from webapp.core.models import Capability, DeviceInfo, OperationResult
from webapp.devices.adb import AdbBackend, AdbDiscoveryConfig
from webapp.devices.webusb import (
    ADB_HEADER_SIZE,
    AUTH_RSAPUBLICKEY,
    CMD_CNXN,
    parse_adb_header,
    read_adb_packet_from_stream,
    validate_adb_packet,
)
from webapp.runtime import JobDatabase, JobManager
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog


def _pack_adb(cmd_str: str, arg0: int = 0, arg1: int = 0, payload: bytes = b"") -> bytes:
    cmd = int.from_bytes(cmd_str.encode("ascii"), "little")
    checksum = sum(payload) & 0xFFFFFFFF
    magic = (cmd ^ 0xFFFFFFFF) & 0xFFFFFFFF
    return struct.pack("<6I", cmd, arg0, arg1, len(payload), checksum, magic) + payload


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        piece = sock.recv(size - len(chunks))
        if not piece:
            raise EOFError("Socket closed")
        chunks.extend(piece)
    return bytes(chunks)


def _recv_adb(sock: socket.socket) -> tuple[str, int, int, bytes]:
    hdr = parse_adb_header(_recv_exact(sock, ADB_HEADER_SIZE))
    payload = _recv_exact(sock, hdr.data_length) if hdr.data_length else b""
    cmd_str = hdr.command.to_bytes(4, "little").decode("ascii", errors="replace")
    return cmd_str, hdr.arg0, hdr.arg1, payload


def _make_png(color: tuple[int, int, int] = (40, 90, 160)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (1280, 720), color=color).save(buf, format="PNG")
    return buf.getvalue()


class _FakeBridgeAdbBackend:
    name = "adb"

    def __init__(self, *, available: bool = True, require_auth_prompt: bool = False) -> None:
        self._available = available
        self._require_auth_prompt = require_auth_prompt
        self._devices: dict[str, DeviceInfo] = {}
        self.disconnected_endpoints: list[str] = []
        self._sockets: list[socket.socket] = []
        self._lock = threading.Lock()

    def capability(self) -> Capability:
        return Capability(
            name=self.name,
            available=self._available,
            reason=None if self._available else "ADB missing",
        )

    def list_devices(self) -> list[DeviceInfo]:
        with self._lock:
            return list(self._devices.values())

    def find_device(self, device_id: str, *, enrich: bool = True) -> DeviceInfo | None:
        with self._lock:
            return self._devices.get(device_id)

    def connect_endpoint(self, endpoint: str) -> DeviceInfo:
        host, port_str = endpoint.rsplit(":", 1)
        sock = socket.create_connection((host, int(port_str)), timeout=3.0)
        self._sockets.append(sock)

        sock.sendall(_pack_adb("CNXN", 0x01000001, 256 * 1024, b"host::features=cmd\x00"))
        cmd, arg0, _arg1, _token = _recv_adb(sock)
        assert cmd == "AUTH" and arg0 == 1
        sock.sendall(_pack_adb("AUTH", 2, 0, b"S" * 256))

        if not self._require_auth_prompt:
            cmd2, _v, _max, banner = _recv_adb(sock)
            assert cmd2 == "CNXN"
            info = DeviceInfo(
                backend="adb",
                device_id=endpoint,
                name="Pixel 8 WebUSB",
                status="device",
                details={"banner": banner.decode("utf-8", errors="ignore")},
            )
            with self._lock:
                self._devices[endpoint] = info
            return info

        # Simulate untrusted key -> phone asks again -> host sends AUTH(3, pubkey)
        cmd_retry, arg0_retry, _, _ = _recv_adb(sock)
        assert cmd_retry == "AUTH" and arg0_retry == 1
        sock.sendall(_pack_adb("AUTH", AUTH_RSAPUBLICKEY, 0, b"ssh-rsa-adb-pubkey\x00"))
        pending_info = DeviceInfo(
            backend="adb",
            device_id=endpoint,
            name=endpoint,
            status="unauthorized",
        )
        with self._lock:
            self._devices[endpoint] = pending_info

        def _wait_for_approval() -> None:
            try:
                cmd_final, _, _, _ = _recv_adb(sock)
                if cmd_final == "CNXN":
                    with self._lock:
                        self._devices[endpoint] = DeviceInfo(
                            backend="adb",
                            device_id=endpoint,
                            name="Authorized Pixel",
                            status="device",
                        )
            except Exception:
                pass

        threading.Thread(target=_wait_for_approval, daemon=True).start()
        return pending_info

    def disconnect_endpoint(self, endpoint: str) -> None:
        self.disconnected_endpoints.append(endpoint)
        with self._lock:
            self._devices.pop(endpoint, None)
        for sock in self._sockets:
            try:
                sock.close()
            except OSError:
                pass
        self._sockets.clear()

    def snapshot(self, device_id: str) -> bytes:
        return _make_png()

    def tap(self, device_id: str, x: int, y: int) -> OperationResult:
        return OperationResult(ok=True, action="tap", message=f"tap {x},{y}")

    def swipe(
        self,
        device_id: str,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int,
    ) -> OperationResult:
        return OperationResult(ok=True, action="swipe", message="swipe")


def test_adb_packet_framing_and_stream_reassembly():
    valid = _pack_adb("CNXN", 0x01000001, 4096, b"host::\x00")
    hdr = validate_adb_packet(valid)
    assert hdr.command == CMD_CNXN
    assert hdr.data_length == 7

    with pytest.raises(ValueError, match="24 bytes"):
        parse_adb_header(b"short")

    bad_magic = struct.pack("<6I", CMD_CNXN, 0, 0, 0, 0, 0x12345678)
    with pytest.raises(ValueError, match="magic"):
        parse_adb_header(bad_magic)

    with pytest.raises(ValueError, match="mismatch"):
        validate_adb_packet(valid + b"extra")

    async def _exercise_stream() -> None:
        reader = asyncio.StreamReader()
        # CNXN with zero checksum should have checksum populated for legacy USB adbd safety
        raw_zero_chk = (
            struct.pack("<6I", CMD_CNXN, 0x01000001, 4096, 4, 0, CMD_CNXN ^ 0xFFFFFFFF)
            + b"host"
        )
        second = _pack_adb("OKAY", 1, 2)
        reader.feed_data(raw_zero_chk[:10])
        reader.feed_data(raw_zero_chk[10:] + second)
        reader.feed_eof()

        h1, p1 = await read_adb_packet_from_stream(reader)
        assert h1.command == CMD_CNXN
        assert h1.data_check == sum(b"host")
        assert p1.endswith(b"host")

        h2, p2 = await read_adb_packet_from_stream(reader)
        assert len(p2) == ADB_HEADER_SIZE
        assert h2.arg0 == 1 and h2.arg1 == 2

    asyncio.run(_exercise_stream())


def test_ws_webusb_reports_error_when_adb_unavailable(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    event_log = EventLog()
    backend = _FakeBridgeAdbBackend(available=False)
    service = DeviceService([backend], event_log)
    manager = JobManager(JobDatabase(tmp_path / "runtime.db"))
    app = create_app(assets, data, event_log=event_log, device_service=service, job_manager=manager)

    with manager, create_test_client(app) as client:
        with client.websocket_connect("/api/ws/webusb") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert msg["error"]["code"] == "adb_not_found"


def test_ws_webusb_handshake_connects_session_and_cleans_up_on_close(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    event_log = EventLog()
    closed_signal = threading.Event()
    event_log.subscribe(
        lambda evt: closed_signal.set() if evt.get("action") == "webusb_bridge_closed" else None
    )
    backend = _FakeBridgeAdbBackend(available=True, require_auth_prompt=False)
    service = DeviceService([backend], event_log)
    manager = JobManager(JobDatabase(tmp_path / "runtime.db"))
    app = create_app(assets, data, event_log=event_log, device_service=service, job_manager=manager)

    with manager, create_test_client(app) as client:
        with client.websocket_connect("/api/ws/webusb?device_name=Pixel_8&serial=SER1") as ws:
            ready = ws.receive_json()
            assert ready["type"] == "ready"
            endpoint = ready["endpoint"]
            assert endpoint.startswith("127.0.0.1:")

            ws.send_json({"type": "ping"})

            # Expect CNXN binary packet from fake host adb (interleaved with pong)
            seen_pong = False
            cnxn_bytes = None
            for _ in range(4):
                frame = ws.receive()
                if frame.get("text"):
                    parsed = json.loads(frame["text"])
                    if parsed.get("type") == "pong":
                        seen_pong = True
                elif frame.get("bytes"):
                    cnxn_bytes = frame["bytes"]
                    if seen_pong:
                        break
            if not seen_pong:
                assert ws.receive_json()["type"] == "pong"
            assert cnxn_bytes is not None
            assert validate_adb_packet(cnxn_bytes).command == CMD_CNXN

            # Device challenges with AUTH(1, token)
            ws.send_bytes(_pack_adb("AUTH", 1, 0, b"T" * 20))
            auth_sig = ws.receive_bytes()
            sig_hdr = validate_adb_packet(auth_sig)
            assert sig_hdr.arg0 == 2

            # Device accepts and replies CNXN
            ws.send_bytes(_pack_adb("CNXN", 0x01000001, 256 * 1024, b"device::model=Pixel_8\x00"))
            connected = ws.receive_json()
            assert connected["type"] == "connected"
            assert connected["endpoint"] == endpoint
            assert connected["connection"]["connected"] is True
            assert service.state().connected is True
            assert service.state().device_id == endpoint

        assert closed_signal.wait(timeout=3.0)
        assert service.state().connected is False
        assert backend.disconnected_endpoints == [endpoint]


def test_ws_webusb_emits_authorizing_when_phone_prompts_user(tmp_path: Path):
    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    event_log = EventLog()
    closed_signal = threading.Event()
    event_log.subscribe(
        lambda evt: closed_signal.set() if evt.get("action") == "webusb_bridge_closed" else None
    )
    backend = _FakeBridgeAdbBackend(available=True, require_auth_prompt=True)
    service = DeviceService([backend], event_log)
    manager = JobManager(JobDatabase(tmp_path / "runtime.db"))
    app = create_app(assets, data, event_log=event_log, device_service=service, job_manager=manager)

    with manager, create_test_client(app) as client:
        with client.websocket_connect("/api/ws/webusb") as ws:
            ready = ws.receive_json()
            endpoint = ready["endpoint"]

            cnxn = ws.receive_bytes()
            assert validate_adb_packet(cnxn).command == CMD_CNXN

            # Challenge 1 -> host sends signature -> reject with Challenge 2 -> host sends RSAPUBLICKEY!
            ws.send_bytes(_pack_adb("AUTH", 1, 0, b"1" * 20))
            _sig = ws.receive_bytes()
            ws.send_bytes(_pack_adb("AUTH", 1, 0, b"2" * 20))

            saw_authorizing = False
            saw_pubkey = False
            for _ in range(4):
                frame = ws.receive()
                if frame.get("text"):
                    msg = json.loads(frame["text"])
                    if msg.get("type") == "authorizing":
                        saw_authorizing = True
                elif frame.get("bytes"):
                    hdr = validate_adb_packet(frame["bytes"])
                    if hdr.arg0 == AUTH_RSAPUBLICKEY:
                        saw_pubkey = True
                if saw_authorizing and saw_pubkey:
                    break
            assert saw_authorizing is True
            assert saw_pubkey is True

            # User taps "Allow" on phone -> phone sends CNXN
            ws.send_bytes(_pack_adb("CNXN", 0x01000001, 256 * 1024, b"device::\x00"))
            connected = ws.receive_json()
            assert connected["type"] == "connected"
            assert connected["endpoint"] == endpoint
            assert service.state().connected is True

        assert closed_signal.wait(timeout=3.0)
        assert service.state().connected is False


@pytest.mark.skipif(shutil.which("adb") is None, reason="System adb executable not installed.")
def test_ws_webusb_end_to_end_with_real_adb_binary_snapshot_and_tap(tmp_path: Path):
    """Proves real Google `adb` server speaks seamlessly through /api/ws/webusb to a USB adbd."""
    adb_path = Path(shutil.which("adb") or "")
    png_payload = _make_png((25, 120, 75))
    tapped_commands: list[str] = []

    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()
    event_log = EventLog()
    closed_signal = threading.Event()
    event_log.subscribe(
        lambda evt: closed_signal.set() if evt.get("action") == "webusb_bridge_closed" else None
    )
    adb_backend = AdbBackend(
        adb_candidates=[adb_path],
        discovery_config=AdbDiscoveryConfig(auto_connect=False, enrich_details=False),
    )
    adb_backend._fast_capture = False
    adb_backend._droidcast_enabled = False
    adb_backend._fast_input = False

    service = DeviceService([adb_backend], event_log)
    manager = JobManager(JobDatabase(tmp_path / "runtime.db"))
    app = create_app(assets, data, event_log=event_log, device_service=service, job_manager=manager)

    with manager, create_test_client(app) as client:
        with client.websocket_connect("/api/ws/webusb?device_name=RealAdbTest") as ws:
            ready = ws.receive_json()
            endpoint = ready["endpoint"]
            connected_ready = threading.Event()
            pump_stop = threading.Event()

            def _simulated_usb_phone() -> None:
                local_stream_id = 100
                while not pump_stop.is_set():
                    try:
                        frame = ws.receive()
                    except Exception:
                        return
                    if frame.get("type") == "websocket.disconnect":
                        return
                    if frame.get("text"):
                        msg = json.loads(frame["text"])
                        if msg.get("type") == "connected":
                            connected_ready.set()
                        continue
                    raw = frame.get("bytes")
                    if not raw:
                        continue
                    hdr = validate_adb_packet(raw)
                    body = raw[ADB_HEADER_SIZE:]
                    cmd_name = hdr.command.to_bytes(4, "little").decode("ascii")
                    if cmd_name == "CNXN":
                        ws.send_bytes(_pack_adb("AUTH", 1, 0, b"R" * 20))
                    elif cmd_name == "AUTH":
                        ws.send_bytes(
                            _pack_adb(
                                "CNXN",
                                0x01000001,
                                256 * 1024,
                                b"device::ro.product.name=bb;ro.product.model=WebUSB_Phone;ro.product.device=bb;\x00",
                            )
                        )
                    elif cmd_name == "OPEN":
                        remote_id = hdr.arg0
                        local_stream_id += 1
                        my_id = local_stream_id
                        service_str = body.rstrip(b"\x00").decode("utf-8", errors="replace")
                        ws.send_bytes(_pack_adb("OKAY", my_id, remote_id))
                        if "screencap" in service_str:
                            ws.send_bytes(_pack_adb("WRTE", my_id, remote_id, png_payload))
                            ws.send_bytes(_pack_adb("CLSE", my_id, remote_id))
                        elif "input tap" in service_str:
                            tapped_commands.append(service_str)
                            ws.send_bytes(_pack_adb("CLSE", my_id, remote_id))
                        else:
                            ws.send_bytes(_pack_adb("WRTE", my_id, remote_id, b"\n"))
                            ws.send_bytes(_pack_adb("CLSE", my_id, remote_id))
                    elif cmd_name == "CLSE":
                        ws.send_bytes(_pack_adb("CLSE", hdr.arg1, hdr.arg0))

            phone_thread = threading.Thread(target=_simulated_usb_phone, daemon=True)
            phone_thread.start()
            try:
                assert connected_ready.wait(timeout=8.0)
                assert service.state().connected is True
                assert service.state().device_id == endpoint

                snap = service.snapshot()
                assert snap == png_payload

                tap_res = service.tap(640, 360)
                assert tap_res.ok is True
                assert any("input tap 640 360" in cmd for cmd in tapped_commands)
            finally:
                pump_stop.set()
                ws.send_json({"type": "close"})
                time.sleep(0.05)

        assert closed_signal.wait(timeout=5.0)
        assert service.state().connected is False
