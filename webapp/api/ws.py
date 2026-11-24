from __future__ import annotations

import asyncio
from io import BytesIO
import json
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from PIL import Image

from webapp.core.errors import AppError
from webapp.devices.coordinates import get_cached_bgr_frame
from webapp.runtime import JobManager
from webapp.runtime.models import JobEvent, JobRecord
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]


def _encode_stream_frame(frame_bytes: bytes, image_format: str, jpeg_quality: int = 75) -> bytes:
    if image_format != "jpeg":
        return frame_bytes
    if frame_bytes.startswith(b"\xff\xd8"):
        return frame_bytes
    if cv2 is not None and np is not None:
        bgr = get_cached_bgr_frame(frame_bytes)
        if bgr is None:
            bgr = cv2.imdecode(np.frombuffer(frame_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if bgr is not None:
            ok, encoded = cv2.imencode(
                ".jpg",
                bgr,
                [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality],
            )
            if ok:
                return encoded.tobytes()
    with Image.open(BytesIO(frame_bytes)) as img:
        out = BytesIO()
        img.convert("RGB").save(out, format="JPEG", quality=jpeg_quality)
        return out.getvalue()


def create_ws_router(
    event_log: EventLog,
    device_service: DeviceService,
    job_manager: JobManager,
) -> APIRouter:
    router = APIRouter(prefix="/api/ws", tags=["ws"])

    @router.websocket("/events")
    async def ws_events(
        websocket: WebSocket,
        events_limit: int = Query(default=80, ge=1, le=200),
        jobs_limit: int = Query(default=50, ge=1, le=200),
        job_id: str | None = Query(default=None),
        after_id: int = Query(default=0, ge=0),
    ) -> None:
        await websocket.accept()
        loop = asyncio.get_running_loop()
        outbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        subscribed_job_id: str | None = job_id.strip() if job_id and job_id.strip() else None

        def enqueue(payload: dict[str, Any]) -> None:
            if outbound.full():
                try:
                    outbound.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                outbound.put_nowait(payload)
            except asyncio.QueueFull:
                pass

        def enqueue_job_event(event_dict: dict[str, Any]) -> None:
            if subscribed_job_id and event_dict.get("job_id") == subscribed_job_id:
                enqueue({"type": "job_event", "job_id": subscribed_job_id, "event": event_dict})

        def on_log_event(event: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(enqueue, {"type": "event", "event": event})

        def on_job_record(record: JobRecord) -> None:
            loop.call_soon_threadsafe(enqueue, {"type": "job_updated", "job": record.to_dict()})

        def on_job_event(event: JobEvent) -> None:
            loop.call_soon_threadsafe(enqueue_job_event, event.to_dict())

        unsub_events = event_log.subscribe(on_log_event)
        unsub_jobs = job_manager.database.subscribe_jobs(on_job_record)
        unsub_job_events = job_manager.database.subscribe_events(on_job_event)

        def build_snapshot() -> dict[str, Any]:
            nonlocal subscribed_job_id
            initial_job_events: list[dict[str, Any]] = []
            if subscribed_job_id:
                try:
                    job_manager.get(subscribed_job_id)
                    initial_job_events = [
                        item.to_dict()
                        for item in job_manager.database.list_events(
                            subscribed_job_id,
                            after_id=after_id,
                            limit=500,
                        )
                    ]
                except KeyError:
                    subscribed_job_id = None
            return {
                "type": "snapshot",
                "connection": device_service.state().to_dict(),
                "events": event_log.recent(events_limit),
                "jobs": [job.to_dict() for job in job_manager.list(jobs_limit)],
                "job_id": subscribed_job_id,
                "job_events": initial_job_events,
            }

        async def sender() -> None:
            try:
                while True:
                    payload = await outbound.get()
                    await websocket.send_json(payload)
            except (WebSocketDisconnect, RuntimeError):
                return

        async def receiver() -> None:
            nonlocal subscribed_job_id
            try:
                while True:
                    raw = await websocket.receive_text()
                    try:
                        message = json.loads(raw)
                    except ValueError:
                        enqueue({"type": "error", "code": "INVALID_JSON", "message": "Invalid JSON message."})
                        continue
                    if not isinstance(message, dict):
                        continue
                    msg_type = message.get("type")
                    if msg_type == "ping":
                        enqueue({"type": "pong"})
                    elif msg_type == "refresh":
                        enqueue(build_snapshot())
                    elif msg_type == "unsubscribe_job":
                        subscribed_job_id = None
                        enqueue({"type": "job_unsubscribed"})
                    elif msg_type == "subscribe_job":
                        requested = str(message.get("job_id") or "").strip()
                        req_after = message.get("after_id", 0)
                        if isinstance(req_after, bool) or not isinstance(req_after, int) or req_after < 0:
                            req_after = 0
                        if not requested:
                            subscribed_job_id = None
                            enqueue({"type": "job_unsubscribed"})
                            continue
                        try:
                            record = job_manager.get(requested)
                            replay = [
                                item.to_dict()
                                for item in job_manager.database.list_events(
                                    requested,
                                    after_id=req_after,
                                    limit=500,
                                )
                            ]
                            subscribed_job_id = requested
                            enqueue(
                                {
                                    "type": "job_subscribed",
                                    "job": record.to_dict(),
                                    "events": replay,
                                }
                            )
                        except KeyError:
                            enqueue(
                                {
                                    "type": "error",
                                    "code": "JOB_NOT_FOUND",
                                    "job_id": requested,
                                }
                            )
            except (WebSocketDisconnect, RuntimeError):
                return

        send_task: asyncio.Task[None] | None = None
        recv_task: asyncio.Task[None] | None = None
        try:
            await websocket.send_json(build_snapshot())
            send_task = asyncio.create_task(sender())
            recv_task = asyncio.create_task(receiver())
            done, pending = await asyncio.wait(
                {send_task, recv_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(exc, WebSocketDisconnect):
                    raise exc
        except WebSocketDisconnect:
            pass
        finally:
            unsub_events()
            unsub_jobs()
            unsub_job_events()
            for task in (send_task, recv_task):
                if task is not None and not task.done():
                    task.cancel()

    @router.websocket("/screen")
    async def ws_screen(
        websocket: WebSocket,
        interval_ms: int = Query(default=500, ge=50, le=10000),
        format: str = Query(default="png"),
        follow_jobs: bool = Query(default=False),
    ) -> None:
        await websocket.accept()
        loop = asyncio.get_running_loop()
        send_lock = asyncio.Lock()
        wake_event = asyncio.Event()
        stop_event = asyncio.Event()
        wake_event.set()
        interval_seconds = max(0.05, min(interval_ms / 1000.0, 10.0))
        stream_format = "jpeg" if format.strip().lower() in {"jpg", "jpeg"} else "png"
        passive_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2)

        def on_device_frame(frame_bytes: bytes) -> None:
            if stop_event.is_set() or not follow_jobs:
                return
            def _push() -> None:
                if passive_queue.full():
                    try:
                        passive_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    passive_queue.put_nowait(frame_bytes)
                except asyncio.QueueFull:
                    pass
            try:
                loop.call_soon_threadsafe(_push)
            except RuntimeError:
                pass

        unsub_frames = device_service.subscribe_frames(on_device_frame) if follow_jobs else (lambda: None)

        async def send_json_locked(payload: dict[str, Any]) -> None:
            async with send_lock:
                await websocket.send_json(payload)

        async def send_bytes_locked(data: bytes) -> None:
            async with send_lock:
                await websocket.send_bytes(data)

        async def close_locked() -> None:
            async with send_lock:
                try:
                    await websocket.close()
                except Exception:
                    pass

        def has_active_job() -> bool:
            return any(not job.status.terminal for job in job_manager.list(50))

        async def streamer() -> None:
            try:
                while not stop_event.is_set():
                    if has_active_job():
                        if not follow_jobs:
                            await send_json_locked({"type": "paused", "reason": "job_running"})
                            stop_event.set()
                            await close_locked()
                            return
                        # Passive zero-overhead broadcast while the job captures frames,
                        # falling back to a non-blocking preview capture during sleeps / NP animations.
                        idle_timeout = max(0.45, interval_seconds)
                        try:
                            raw_frame = await asyncio.wait_for(passive_queue.get(), timeout=idle_timeout)
                        except TimeoutError:
                            if not device_service.state().connected:
                                await send_json_locked(
                                    {"type": "error", "error": {"code": "device_not_connected", "message": "No device is connected."}}
                                )
                                stop_event.set()
                                await close_locked()
                                return
                            try:
                                raw_frame = await asyncio.to_thread(device_service.preview_snapshot)
                            except AppError as exc:
                                await send_json_locked({"type": "error", "error": exc.to_response()["error"]})
                                stop_event.set()
                                await close_locked()
                                return
                            if raw_frame is None:
                                continue
                        encoded = await asyncio.to_thread(_encode_stream_frame, raw_frame, stream_format)
                        if stop_event.is_set():
                            return
                        await send_bytes_locked(encoded)
                        continue
                    # Drain any stale passive frames when returning to active preview.
                    while not passive_queue.empty():
                        try:
                            passive_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    wake_event.clear()
                    try:
                        frame = await asyncio.to_thread(device_service.snapshot)
                    except AppError as exc:
                        await send_json_locked({"type": "error", "error": exc.to_response()["error"]})
                        stop_event.set()
                        await close_locked()
                        return
                    encoded = await asyncio.to_thread(_encode_stream_frame, frame, stream_format)
                    if stop_event.is_set():
                        return
                    await send_bytes_locked(encoded)
                    try:
                        await asyncio.wait_for(wake_event.wait(), timeout=interval_seconds)
                    except TimeoutError:
                        pass
            except (WebSocketDisconnect, RuntimeError):
                stop_event.set()
                return

        async def receiver() -> None:
            nonlocal interval_seconds
            try:
                while not stop_event.is_set():
                    raw = await websocket.receive_text()
                    try:
                        message = json.loads(raw)
                    except ValueError:
                        await send_json_locked(
                            {"type": "error", "error": {"code": "invalid_json", "message": "Invalid JSON message."}}
                        )
                        continue
                    if not isinstance(message, dict):
                        continue
                    msg_type = message.get("type")
                    if msg_type == "ping":
                        await send_json_locked({"type": "pong"})
                    elif msg_type == "refresh":
                        wake_event.set()
                    elif msg_type == "set_interval":
                        next_ms = message.get("interval_ms")
                        if not isinstance(next_ms, bool) and isinstance(next_ms, (int, float)):
                            clamped = max(80, min(int(next_ms), 10000))
                            interval_seconds = clamped / 1000.0
                            wake_event.set()
                    elif msg_type == "tap":
                        x = message.get("x")
                        y = message.get("y")
                        if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, int) or not isinstance(y, int):
                            await send_json_locked(
                                {"type": "tap_error", "error": {"code": "invalid_tap", "message": "x and y must be integers."}}
                            )
                            continue
                        try:
                            op = await asyncio.to_thread(device_service.tap, x, y)
                            await send_json_locked({"type": "tap_result", "result": op.to_dict()})
                            wake_event.set()
                        except AppError as exc:
                            await send_json_locked({"type": "tap_error", "error": exc.to_response()["error"]})
            except (WebSocketDisconnect, RuntimeError):
                stop_event.set()
                return

        stream_task = asyncio.create_task(streamer())
        recv_task = asyncio.create_task(receiver())
        try:
            done, pending = await asyncio.wait(
                {stream_task, recv_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            stop_event.set()
            wake_event.set()
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(exc, WebSocketDisconnect):
                    raise exc
        except WebSocketDisconnect:
            pass
        finally:
            stop_event.set()
            wake_event.set()
            unsub_frames()
            for task in (stream_task, recv_task):
                if not task.done():
                    task.cancel()

    return router
