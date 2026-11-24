from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import struct
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from webapp.core.errors import AppError, ErrorCode
from webapp.core.models import DeviceInfo
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog


ADB_HEADER_SIZE = 24
ADB_MAX_PAYLOAD = 4 * 1024 * 1024
CMD_CNXN = int.from_bytes(b"CNXN", "little")
CMD_AUTH = int.from_bytes(b"AUTH", "little")
AUTH_RSAPUBLICKEY = 3


@dataclass(frozen=True)
class AdbPacketHeader:
    command: int
    arg0: int
    arg1: int
    data_length: int
    data_check: int
    magic: int


def parse_adb_header(header_bytes: bytes) -> AdbPacketHeader:
    if len(header_bytes) != ADB_HEADER_SIZE:
        raise ValueError(f"ADB header must be {ADB_HEADER_SIZE} bytes, got {len(header_bytes)}.")
    command, arg0, arg1, data_length, data_check, magic = struct.unpack("<6I", header_bytes)
    if ((command ^ 0xFFFFFFFF) & 0xFFFFFFFF) != magic:
        raise ValueError("Invalid ADB packet header magic.")
    if data_length > ADB_MAX_PAYLOAD:
        raise ValueError(f"ADB packet payload length {data_length} exceeds limit {ADB_MAX_PAYLOAD}.")
    return AdbPacketHeader(
        command=command,
        arg0=arg0,
        arg1=arg1,
        data_length=data_length,
        data_check=data_check,
        magic=magic,
    )


def validate_adb_packet(packet: bytes) -> AdbPacketHeader:
    if len(packet) < ADB_HEADER_SIZE:
        raise ValueError(f"ADB packet shorter than {ADB_HEADER_SIZE} bytes.")
    header = parse_adb_header(packet[:ADB_HEADER_SIZE])
    expected_len = ADB_HEADER_SIZE + header.data_length
    if len(packet) != expected_len:
        raise ValueError(
            f"ADB packet length mismatch: expected {expected_len} bytes, got {len(packet)}."
        )
    return header


async def read_adb_packet_from_stream(reader: asyncio.StreamReader) -> tuple[AdbPacketHeader, bytes]:
    header_bytes = await reader.readexactly(ADB_HEADER_SIZE)
    header = parse_adb_header(header_bytes)
    payload = await reader.readexactly(header.data_length) if header.data_length > 0 else b""
    if header.command == CMD_CNXN and payload and header.data_check == 0:
        checksum = sum(payload) & 0xFFFFFFFF
        header_bytes = struct.pack(
            "<6I",
            header.command,
            header.arg0,
            header.arg1,
            header.data_length,
            checksum,
            header.magic,
        )
        header = parse_adb_header(header_bytes)
    return header, header_bytes + payload


def _lookup_connected_device(device_service: DeviceService, endpoint: str) -> DeviceInfo | None:
    for item in device_service.list_devices():
        if item.backend == "adb" and item.device_id == endpoint:
            return item
    return None


async def run_webusb_adb_bridge(
    websocket: WebSocket,
    *,
    device_service: DeviceService,
    event_log: EventLog,
    usb_device_name: str | None = None,
    usb_serial: str | None = None,
    auth_timeout_seconds: float = 60.0,
    ready_poll_timeout_seconds: float = 5.0,
) -> None:
    await websocket.accept()
    send_lock = asyncio.Lock()
    stop_event = asyncio.Event()
    tcp_connected = asyncio.Event()
    cnxn_received = asyncio.Event()
    writer_holder: list[asyncio.StreamWriter] = []

    async def send_json_locked(payload: dict[str, Any]) -> None:
        if stop_event.is_set():
            return
        async with send_lock:
            await websocket.send_json(payload)

    async def send_bytes_locked(data: bytes) -> None:
        if stop_event.is_set():
            return
        async with send_lock:
            await websocket.send_bytes(data)

    async def close_ws_locked() -> None:
        async with send_lock:
            try:
                await websocket.close()
            except Exception:
                pass

    adb_available = any(
        cap.name == "adb" and cap.available for cap in device_service.capabilities()
    )
    if not adb_available:
        await send_json_locked(
            {
                "type": "error",
                "error": {
                    "code": ErrorCode.ADB_NOT_FOUND.value,
                    "message": "ADB executable was not found on the server.",
                },
            }
        )
        stop_event.set()
        await close_ws_locked()
        return

    endpoint = ""
    authorizing_notified = False
    tcp_handler_tasks: set[asyncio.Task[Any]] = set()

    async def handle_adb_tcp(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal authorizing_notified
        current = asyncio.current_task()
        if current is not None:
            tcp_handler_tasks.add(current)
        if writer_holder:
            prev = writer_holder.pop()
            try:
                prev.close()
            except Exception:
                pass
        writer_holder.append(writer)
        tcp_connected.set()
        try:
            while not stop_event.is_set():
                header, packet = await read_adb_packet_from_stream(reader)
                if header.command == CMD_AUTH and header.arg0 == AUTH_RSAPUBLICKEY and not authorizing_notified:
                    authorizing_notified = True
                    event_log.info(
                        "webusb_auth_prompt",
                        "Waiting for USB debugging authorization on device.",
                        {"endpoint": endpoint, "usb_device_name": usb_device_name},
                    )
                    await send_json_locked({"type": "authorizing", "endpoint": endpoint})
                await send_bytes_locked(packet)
        except asyncio.IncompleteReadError as exc:
            if exc.partial:
                event_log.error(
                    "webusb_protocol_error",
                    "Truncated ADB packet from local ADB server.",
                    {"endpoint": endpoint, "partial_bytes": len(exc.partial)},
                )
        except ValueError as exc:
            event_log.error(
                "webusb_protocol_error",
                str(exc),
                {"endpoint": endpoint},
            )
        except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
            pass
        finally:
            if current is not None:
                tcp_handler_tasks.discard(current)
            stop_event.set()
            try:
                writer.close()
            except Exception:
                pass

    tcp_server = await asyncio.start_server(handle_adb_tcp, host="127.0.0.1", port=0)
    sockets = tcp_server.sockets or ()
    if not sockets:
        tcp_server.close()
        await tcp_server.wait_closed()
        await send_json_locked(
            {
                "type": "error",
                "error": {
                    "code": "webusb_bind_failed",
                    "message": "Failed to bind local loopback bridge port.",
                },
            }
        )
        stop_event.set()
        await close_ws_locked()
        return

    port = int(sockets[0].getsockname()[1])
    endpoint = f"127.0.0.1:{port}"
    clean_name = (usb_device_name or "").strip() or None
    clean_serial = (usb_serial or "").strip() or None
    event_log.info(
        "webusb_bridge_open",
        "WebUSB ADB bridge opened.",
        {
            "endpoint": endpoint,
            "usb_device_name": clean_name,
            "usb_serial": clean_serial,
        },
    )

    client_disconnected = False

    async def ws_receiver() -> None:
        nonlocal client_disconnected
        try:
            while not stop_event.is_set():
                message = await websocket.receive()
                msg_type = message.get("type")
                if msg_type == "websocket.disconnect":
                    client_disconnected = True
                    stop_event.set()
                    return
                text_data = message.get("text")
                if text_data is not None:
                    try:
                        payload = json.loads(text_data)
                    except ValueError:
                        await send_json_locked(
                            {
                                "type": "error",
                                "error": {"code": "invalid_json", "message": "Invalid JSON message."},
                            }
                        )
                        continue
                    if not isinstance(payload, dict):
                        continue
                    kind = payload.get("type")
                    if kind == "ping":
                        await send_json_locked({"type": "pong"})
                    elif kind == "close":
                        stop_event.set()
                        return
                    continue

                raw_bytes = message.get("bytes")
                if raw_bytes is None:
                    continue
                try:
                    header = validate_adb_packet(raw_bytes)
                except ValueError as exc:
                    await send_json_locked(
                        {
                            "type": "error",
                            "error": {"code": "invalid_adb_packet", "message": str(exc)},
                        }
                    )
                    stop_event.set()
                    return

                try:
                    await asyncio.wait_for(tcp_connected.wait(), timeout=10.0)
                except TimeoutError:
                    await send_json_locked(
                        {
                            "type": "error",
                            "error": {
                                "code": ErrorCode.ADB_CONNECT_FAILED.value,
                                "message": "Timed out waiting for local ADB server connection.",
                            },
                        }
                    )
                    stop_event.set()
                    return

                if not writer_holder or stop_event.is_set():
                    return
                writer = writer_holder[0]
                writer.write(raw_bytes)
                await writer.drain()
                if header.command == CMD_CNXN:
                    cnxn_received.set()
        except WebSocketDisconnect:
            client_disconnected = True
            stop_event.set()
        except (RuntimeError, ConnectionError, asyncio.CancelledError):
            stop_event.set()

    async def attach_session() -> None:
        loop = asyncio.get_running_loop()
        auth_deadline = loop.time() + max(auth_timeout_seconds, 0.5)
        connect_future = asyncio.create_task(
            asyncio.to_thread(device_service.connect_adb_endpoint, endpoint)
        )
        stop_wait = asyncio.create_task(stop_event.wait())
        cnxn_wait = asyncio.create_task(cnxn_received.wait())
        try:
            active_waits: set[asyncio.Task[Any]] = {connect_future, cnxn_wait, stop_wait}
            while not cnxn_wait.done() and not stop_event.is_set():
                remaining = auth_deadline - loop.time()
                if remaining <= 0:
                    break
                done, _ = await asyncio.wait(
                    active_waits,
                    timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    break
                if connect_future in done:
                    active_waits.discard(connect_future)
                    exc = connect_future.exception()
                    if exc is not None:
                        raise exc

            if stop_event.is_set():
                return
            if not cnxn_wait.done():
                await send_json_locked(
                    {
                        "type": "error",
                        "error": {
                            "code": "adb_auth_timeout",
                            "message": "Timed out waiting for USB debugging authorization on the device.",
                        },
                    }
                )
                stop_event.set()
                return

            initial_device = await connect_future
            deadline = loop.time() + max(ready_poll_timeout_seconds, 0.2)
            last_error: AppError | None = None
            conn_state = None
            while not stop_event.is_set():
                try:
                    conn_state = await asyncio.to_thread(device_service.connect, "adb", endpoint)
                    break
                except AppError as exc:
                    last_error = exc
                    if (
                        exc.code not in {ErrorCode.DEVICE_OFFLINE, ErrorCode.DEVICE_NOT_FOUND}
                        or loop.time() >= deadline
                    ):
                        await send_json_locked({"type": "error", "error": exc.to_response()["error"]})
                        stop_event.set()
                        return
                    await asyncio.sleep(0.1)

            if conn_state is None or stop_event.is_set():
                if last_error is not None and not stop_event.is_set():
                    await send_json_locked({"type": "error", "error": last_error.to_response()["error"]})
                return

            ready_device = await asyncio.to_thread(_lookup_connected_device, device_service, endpoint)
            device_dict = (ready_device or initial_device).to_dict()
            await send_json_locked(
                {
                    "type": "connected",
                    "endpoint": endpoint,
                    "device": device_dict,
                    "connection": conn_state.to_dict(),
                }
            )
        except AppError as exc:
            if not stop_event.is_set():
                await send_json_locked({"type": "error", "error": exc.to_response()["error"]})
                stop_event.set()
        except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
            return
        finally:
            for helper in (stop_wait, cnxn_wait):
                if not helper.done():
                    helper.cancel()
            if not connect_future.done():
                connect_future.cancel()
            await asyncio.gather(stop_wait, cnxn_wait, connect_future, return_exceptions=True)

    recv_task: asyncio.Task[None] | None = None
    attach_task: asyncio.Task[None] | None = None
    stop_task: asyncio.Task[bool] | None = None
    try:
        await send_json_locked({"type": "ready", "endpoint": endpoint})
        recv_task = asyncio.create_task(ws_receiver())
        attach_task = asyncio.create_task(attach_session())
        stop_task = asyncio.create_task(stop_event.wait())
        await asyncio.wait(
            {recv_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_event.is_set() and not client_disconnected:
            await close_ws_locked()
    except WebSocketDisconnect:
        pass
    finally:
        stop_event.set()
        helper_tasks = [
            task
            for task in (attach_task, recv_task, stop_task, *tcp_handler_tasks)
            if task is not None
        ]
        for task in helper_tasks:
            if not task.done():
                task.cancel()
        tcp_server.close()
        for writer in list(writer_holder):
            try:
                writer.close()
            except Exception:
                pass
        writer_holder.clear()

        if helper_tasks:
            try:
                await asyncio.gather(*helper_tasks, return_exceptions=True)
            except BaseException:
                pass

        disconnected_cleanly = False
        try:
            await asyncio.to_thread(
                device_service.disconnect_adb_endpoint,
                endpoint,
                clear_session_if_active=True,
            )
            disconnected_cleanly = True
        except BaseException:
            if not disconnected_cleanly:
                try:
                    device_service.disconnect_adb_endpoint(
                        endpoint,
                        clear_session_if_active=True,
                    )
                except Exception:
                    pass

        try:
            await asyncio.wait_for(tcp_server.wait_closed(), timeout=1.0)
        except BaseException:
            pass

        event_log.info(
            "webusb_bridge_closed",
            "WebUSB ADB bridge closed.",
            {"endpoint": endpoint},
        )
