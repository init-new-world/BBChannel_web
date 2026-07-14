from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from webapp.runtime.database import JobDatabase
from webapp.runtime.models import JobRecord, JobStatus


JobHandler = Callable[["RunContext", dict[str, Any]], dict[str, Any] | None]


class JobCancelled(Exception):
    pass


class UnknownJobKindError(KeyError):
    pass


class JobStateError(RuntimeError):
    pass


class RunControl:
    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._pause_condition = threading.Condition()
        self._paused = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def pause(self) -> None:
        with self._pause_condition:
            self._paused = True

    def resume(self) -> None:
        with self._pause_condition:
            self._paused = False
            self._pause_condition.notify_all()

    def cancel(self) -> None:
        self._cancelled.set()
        self.resume()

    def checkpoint(self) -> None:
        if self.cancelled:
            raise JobCancelled
        with self._pause_condition:
            while self._paused and not self.cancelled:
                self._pause_condition.wait(timeout=0.25)
        if self.cancelled:
            raise JobCancelled


class RunContext:
    def __init__(self, job_id: str, database: JobDatabase, control: RunControl) -> None:
        self.job_id = job_id
        self._database = database
        self._control = control

    @property
    def cancelled(self) -> bool:
        return self._control.cancelled

    def checkpoint(
        self,
        step: str,
        *,
        progress: float | None = None,
        message: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self._control.checkpoint()
        self._database.update_progress(self.job_id, step, progress)
        if message is not None:
            self.emit("step", message, data=data or {"step": step, "progress": progress})

    def emit(
        self,
        event_type: str,
        message: str,
        *,
        level: str = "info",
        data: dict[str, Any] | None = None,
    ) -> None:
        self._database.append_event(
            self.job_id,
            event_type,
            message,
            level=level,
            data=data,
        )

    def sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            self._control.checkpoint()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._control._cancelled.wait(timeout=min(remaining, 0.1))

    def raise_if_cancelled(self) -> None:
        self._control.checkpoint()


class DeviceLeaseRegistry:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    @contextmanager
    def acquire(self, device_key: str | None, control: RunControl) -> Iterator[None]:
        if device_key is None:
            control.checkpoint()
            yield
            return

        with self._guard:
            lock = self._locks.setdefault(device_key, threading.Lock())
        acquired = False
        try:
            while not acquired:
                control.checkpoint()
                acquired = lock.acquire(timeout=0.1)
            yield
        finally:
            if acquired:
                lock.release()


@dataclass
class _JobExecution:
    control: RunControl
    done: threading.Event
    state_lock: threading.RLock = field(default_factory=threading.RLock)
    future: Future[None] | None = None


class JobManager:
    def __init__(
        self,
        database: JobDatabase,
        *,
        max_workers: int = 4,
        lease_registry: DeviceLeaseRegistry | None = None,
    ) -> None:
        self.database = database
        self.database.recover_incomplete_jobs()
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, max_workers),
            thread_name_prefix="bbchannel-job",
        )
        self._lease_registry = lease_registry or DeviceLeaseRegistry()
        self._handlers: dict[str, JobHandler] = {}
        self._executions: dict[str, _JobExecution] = {}
        self._guard = threading.Lock()
        self._closed = False

    def __enter__(self) -> "JobManager":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def register(self, kind: str, handler: JobHandler) -> None:
        normalized = kind.strip()
        if not normalized:
            raise ValueError("Job kind must not be empty.")
        self._handlers[normalized] = handler

    def registered_kinds(self) -> list[str]:
        return sorted(self._handlers)

    def start(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        device_key: str | None = None,
    ) -> JobRecord:
        if self._closed:
            raise RuntimeError("Job manager is closed.")
        handler = self._handlers.get(kind)
        if handler is None:
            raise UnknownJobKindError(kind)

        job_id = uuid4().hex
        record = self.database.create_job(job_id, kind, payload or {}, device_key)
        self.database.append_event(job_id, "job_queued", "Job queued.")
        execution = _JobExecution(control=RunControl(), done=threading.Event())
        with self._guard:
            self._executions[job_id] = execution
        execution.future = self._executor.submit(
            self._run_job,
            record,
            handler,
            execution,
        )
        return record

    def get(self, job_id: str) -> JobRecord:
        return self.database.get_job(job_id)

    def list(self, limit: int = 100) -> list[JobRecord]:
        return self.database.list_jobs(limit=limit)

    def pause(self, job_id: str) -> JobRecord:
        execution = self._execution(job_id)
        with execution.state_lock:
            record = self.database.get_job(job_id)
            if record.status != JobStatus.RUNNING:
                raise JobStateError(f"Cannot pause job in state {record.status.value}.")
            execution.control.pause()
            updated = self.database.transition_job(
                job_id,
                JobStatus.PAUSED,
                current_step=record.current_step,
                progress=record.progress,
            )
            self.database.append_event(job_id, "job_paused", "Job paused.")
        return updated

    def resume(self, job_id: str) -> JobRecord:
        execution = self._execution(job_id)
        with execution.state_lock:
            record = self.database.get_job(job_id)
            if record.status != JobStatus.PAUSED:
                raise JobStateError(f"Cannot resume job in state {record.status.value}.")
            updated = self.database.transition_job(
                job_id,
                JobStatus.RUNNING,
                current_step=record.current_step,
                progress=record.progress,
            )
            execution.control.resume()
            self.database.append_event(job_id, "job_resumed", "Job resumed.")
        return updated

    def cancel(self, job_id: str) -> JobRecord:
        execution = self._execution(job_id)
        with execution.state_lock:
            record = self.database.get_job(job_id)
            if record.status.terminal:
                return record
            if record.status == JobStatus.CANCELLING:
                return record
            updated = self.database.transition_job(
                job_id,
                JobStatus.CANCELLING,
                current_step=record.current_step,
                progress=record.progress,
            )
            self.database.append_event(job_id, "job_cancelling", "Job cancellation requested.")
            execution.control.cancel()
        return updated

    def wait(self, job_id: str, timeout: float | None = None) -> JobRecord:
        with self._guard:
            execution = self._executions.get(job_id)
        if execution is None:
            record = self.database.get_job(job_id)
            if record.status.terminal:
                return record
            raise JobStateError("Job is not managed by this process.")
        if not execution.done.wait(timeout=timeout):
            raise TimeoutError(job_id)
        return self.database.get_job(job_id)

    def close(self, *, wait: bool = True) -> None:
        if self._closed:
            return
        self._closed = True
        with self._guard:
            executions = list(self._executions.values())
        for execution in executions:
            if not execution.done.is_set():
                execution.control.cancel()
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _run_job(
        self,
        record: JobRecord,
        handler: JobHandler,
        execution: _JobExecution,
    ) -> None:
        context = RunContext(record.job_id, self.database, execution.control)
        try:
            if record.device_key is not None:
                self.database.append_event(
                    record.job_id,
                    "device_wait",
                    "Waiting for exclusive device access.",
                    data={"device_key": record.device_key},
                )
            with self._lease_registry.acquire(record.device_key, execution.control):
                with execution.state_lock:
                    execution.control.checkpoint()
                    self.database.transition_job(
                        record.job_id,
                        JobStatus.RUNNING,
                        current_step="starting",
                        progress=0.0,
                    )
                    self.database.append_event(record.job_id, "job_started", "Job started.")
                result = handler(context, record.payload) or {}
                self._finish_succeeded(record.job_id, result, execution)
        except JobCancelled:
            self._finish_cancelled(record.job_id, execution)
        except Exception as exc:
            if execution.control.cancelled:
                self._finish_cancelled(record.job_id, execution)
            else:
                self._finish_failed(record.job_id, exc, execution)
        finally:
            execution.done.set()

    def _finish_succeeded(
        self,
        job_id: str,
        result: dict[str, Any],
        execution: _JobExecution,
    ) -> None:
        while True:
            execution.control.checkpoint()
            with execution.state_lock:
                latest = self.database.get_job(job_id)
                if latest.status == JobStatus.PAUSED:
                    continue
                if latest.status == JobStatus.CANCELLING:
                    raise JobCancelled
                if latest.status.terminal:
                    return
                self.database.transition_job(
                    job_id,
                    JobStatus.SUCCEEDED,
                    current_step=latest.current_step or "complete",
                    progress=1.0,
                    result=result,
                )
                self.database.append_event(job_id, "job_succeeded", "Job succeeded.")
                return

    def _finish_cancelled(self, job_id: str, execution: _JobExecution) -> None:
        with execution.state_lock:
            latest = self.database.get_job(job_id)
            if latest.status.terminal:
                return
            self.database.transition_job(
                job_id,
                JobStatus.CANCELLED,
                current_step=latest.current_step,
                progress=latest.progress,
            )
            self.database.append_event(job_id, "job_cancelled", "Job cancelled.")

    def _finish_failed(
        self,
        job_id: str,
        exc: Exception,
        execution: _JobExecution,
    ) -> None:
        with execution.state_lock:
            latest = self.database.get_job(job_id)
            if latest.status.terminal:
                return
            error = {"type": type(exc).__name__, "message": str(exc)}
            self.database.transition_job(
                job_id,
                JobStatus.FAILED,
                current_step=latest.current_step,
                progress=latest.progress,
                error=error,
            )
            self.database.append_event(
                job_id,
                "job_failed",
                "Job failed.",
                level="error",
                data=error,
            )

    def _execution(self, job_id: str) -> _JobExecution:
        with self._guard:
            execution = self._executions.get(job_id)
        if execution is None:
            self.database.get_job(job_id)
            raise JobStateError("Job is not active in this process.")
        return execution
