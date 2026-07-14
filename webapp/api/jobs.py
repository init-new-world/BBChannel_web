from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from webapp.runtime import JobManager, JobStateError, UnknownJobKindError


class StartJobRequest(BaseModel):
    kind: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    device_key: str | None = None


def create_job_router(job_manager: JobManager) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["jobs"])

    @router.get("/job-kinds")
    def job_kinds() -> dict[str, list[str]]:
        return {"kinds": job_manager.registered_kinds()}

    @router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
    def start_job(request: StartJobRequest) -> dict[str, Any]:
        try:
            job = job_manager.start(
                request.kind,
                request.payload,
                device_key=request.device_key,
            )
        except UnknownJobKindError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "UNKNOWN_JOB_KIND", "kind": request.kind},
            ) from exc
        return {"job": job.to_dict()}

    @router.get("/jobs")
    def list_jobs(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, list[dict]]:
        return {"jobs": [job.to_dict() for job in job_manager.list(limit)]}

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        return {"job": _get_job(job_manager, job_id).to_dict()}

    @router.post("/jobs/{job_id}/pause")
    def pause_job(job_id: str) -> dict[str, Any]:
        return {"job": _control_job(job_manager, "pause", job_id).to_dict()}

    @router.post("/jobs/{job_id}/resume")
    def resume_job(job_id: str) -> dict[str, Any]:
        return {"job": _control_job(job_manager, "resume", job_id).to_dict()}

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        return {"job": _control_job(job_manager, "cancel", job_id).to_dict()}

    @router.get("/jobs/{job_id}/events")
    def job_events(
        job_id: str,
        after_id: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict[str, list[dict]]:
        _get_job(job_manager, job_id)
        events = job_manager.database.list_events(job_id, after_id=after_id, limit=limit)
        return {"events": [event.to_dict() for event in events]}

    @router.get("/jobs/{job_id}/events/stream")
    async def stream_job_events(
        request: Request,
        job_id: str,
        after_id: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        _get_job(job_manager, job_id)
        header_id = request.headers.get("last-event-id")
        if header_id is not None:
            try:
                after_id = max(after_id, int(header_id))
            except ValueError:
                pass
        return StreamingResponse(
            _event_stream(request, job_manager, job_id, after_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


def _get_job(job_manager: JobManager, job_id: str):
    try:
        return job_manager.get(job_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "JOB_NOT_FOUND", "job_id": job_id},
        ) from exc


def _control_job(job_manager: JobManager, action: str, job_id: str):
    try:
        return getattr(job_manager, action)(job_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "JOB_NOT_FOUND", "job_id": job_id},
        ) from exc
    except JobStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVALID_JOB_STATE", "message": str(exc)},
        ) from exc


async def _event_stream(
    request: Request,
    job_manager: JobManager,
    job_id: str,
    after_id: int,
) -> AsyncIterator[str]:
    cursor = after_id
    idle_polls = 0
    while not await request.is_disconnected():
        events = job_manager.database.list_events(job_id, after_id=cursor, limit=200)
        for event in events:
            cursor = event.event_id
            yield _format_sse(event.event_id, "job_event", event.to_dict())
        if events:
            idle_polls = 0
            continue
        if job_manager.get(job_id).status.terminal:
            return
        idle_polls += 1
        if idle_polls >= 60:
            yield ": keep-alive\n\n"
            idle_polls = 0
        await asyncio.sleep(0.25)


def _format_sse(event_id: int, event_type: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event_type}\ndata: {payload}\n\n"
