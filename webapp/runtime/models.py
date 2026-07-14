from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        return self in {self.CANCELLED, self.SUCCEEDED, self.FAILED}


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    kind: str
    status: JobStatus
    payload: dict[str, Any]
    device_key: str | None
    current_step: str | None
    progress: float | None
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status.value,
            "payload": self.payload,
            "device_key": self.device_key,
            "current_step": self.current_step,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class JobEvent:
    event_id: int
    job_id: str
    event_type: str
    level: str
    message: str
    data: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "job_id": self.job_id,
            "event_type": self.event_type,
            "level": self.level,
            "message": self.message,
            "data": self.data,
            "created_at": self.created_at,
        }
