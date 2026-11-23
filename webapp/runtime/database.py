from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterable

from webapp.runtime.models import JobEvent, JobRecord, JobStatus


SCHEMA_VERSION = 1

MIGRATIONS = {
    1: """
        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            device_key TEXT,
            current_step TEXT,
            progress REAL,
            result_json TEXT,
            error_json TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX jobs_status_created_idx ON jobs(status, created_at DESC);

        CREATE TABLE job_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            data_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX job_events_job_id_idx ON job_events(job_id, event_id);
    """,
}


class JobDatabase:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._subscriber_lock = RLock()
        self._job_subscribers: list[Callable[[JobRecord], None]] = []
        self._event_subscribers: list[Callable[[JobEvent], None]] = []
        self._migrate()

    def _ensure_subscribers(self) -> RLock:
        lock = getattr(self, "_subscriber_lock", None)
        if lock is None:
            lock = RLock()
            self._subscriber_lock = lock
            self._job_subscribers = []
            self._event_subscribers = []
        return lock

    def subscribe_jobs(self, callback: Callable[[JobRecord], None]) -> Callable[[], None]:
        lock = self._ensure_subscribers()
        with lock:
            self._job_subscribers.append(callback)

        def unsubscribe() -> None:
            with lock:
                try:
                    self._job_subscribers.remove(callback)
                except ValueError:
                    pass

        return unsubscribe

    def subscribe_events(self, callback: Callable[[JobEvent], None]) -> Callable[[], None]:
        lock = self._ensure_subscribers()
        with lock:
            self._event_subscribers.append(callback)

        def unsubscribe() -> None:
            with lock:
                try:
                    self._event_subscribers.remove(callback)
                except ValueError:
                    pass

        return unsubscribe

    def _notify_job(self, record: JobRecord) -> None:
        lock = self._ensure_subscribers()
        with lock:
            subscribers = list(self._job_subscribers)
        for subscriber in subscribers:
            try:
                subscriber(record)
            except Exception:
                pass

    def _notify_event(self, event: JobEvent) -> None:
        lock = self._ensure_subscribers()
        with lock:
            subscribers = list(self._event_subscribers)
        for subscriber in subscribers:
            try:
                subscriber(event)
            except Exception:
                pass

    def schema_version(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
        return int(row["version"])

    def create_job(
        self,
        job_id: str,
        kind: str,
        payload: dict[str, Any],
        device_key: str | None = None,
    ) -> JobRecord:
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, kind, status, payload_json, device_key,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    kind,
                    JobStatus.QUEUED.value,
                    _dump_json(payload),
                    device_key,
                    now,
                    now,
                ),
            )
        record = self.get_job(job_id)
        self._notify_job(record)
        return record

    def get_job(self, job_id: str) -> JobRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return _job_from_row(row)

    def list_jobs(
        self,
        limit: int = 100,
        statuses: Iterable[JobStatus] | None = None,
    ) -> list[JobRecord]:
        bounded_limit = max(1, min(limit, 1000))
        status_values = [status.value for status in statuses or []]
        query = "SELECT * FROM jobs"
        parameters: list[Any] = []
        if status_values:
            placeholders = ",".join("?" for _ in status_values)
            query += f" WHERE status IN ({placeholders})"
            parameters.extend(status_values)
        query += " ORDER BY created_at DESC LIMIT ?"
        parameters.append(bounded_limit)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_job_from_row(row) for row in rows]

    def transition_job(
        self,
        job_id: str,
        status: JobStatus,
        *,
        current_step: str | None = None,
        progress: float | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> JobRecord:
        now = _utc_now()
        updates = [
            "status = ?",
            "current_step = ?",
            "progress = ?",
            "result_json = ?",
            "error_json = ?",
            "updated_at = ?",
        ]
        parameters: list[Any] = [
            status.value,
            current_step,
            progress,
            _dump_json(result) if result is not None else None,
            _dump_json(error) if error is not None else None,
            now,
        ]
        if status == JobStatus.RUNNING:
            updates.append("started_at = COALESCE(started_at, ?)")
            parameters.append(now)
        if status.terminal:
            updates.append("finished_at = ?")
            parameters.append(now)
        parameters.append(job_id)

        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE jobs SET {', '.join(updates)} WHERE job_id = ?",
                parameters,
            )
            if cursor.rowcount != 1:
                raise KeyError(job_id)
        record = self.get_job(job_id)
        self._notify_job(record)
        return record

    def update_progress(
        self,
        job_id: str,
        current_step: str,
        progress: float | None = None,
    ) -> JobRecord:
        now = _utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET current_step = ?, progress = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (current_step, progress, now, job_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(job_id)
        record = self.get_job(job_id)
        self._notify_job(record)
        return record

    def append_event(
        self,
        job_id: str,
        event_type: str,
        message: str,
        *,
        level: str = "info",
        data: dict[str, Any] | None = None,
    ) -> JobEvent:
        now = _utc_now()
        event_data = dict(data) if data else {}
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO job_events (
                    job_id, event_type, level, message, data_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (job_id, event_type, level, message, _dump_json(event_data), now),
            )
            event_id = int(cursor.lastrowid)
        event = JobEvent(
            event_id=event_id,
            job_id=job_id,
            event_type=event_type,
            level=level,
            message=message,
            data=event_data,
            created_at=now,
        )
        self._notify_event(event)
        return event

    def get_event(self, event_id: int) -> JobEvent:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM job_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        if row is None:
            raise KeyError(event_id)
        return _event_from_row(row)

    def list_events(
        self,
        job_id: str,
        *,
        after_id: int = 0,
        limit: int = 200,
    ) -> list[JobEvent]:
        bounded_limit = max(1, min(limit, 1000))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM job_events
                WHERE job_id = ? AND event_id > ?
                ORDER BY event_id ASC
                LIMIT ?
                """,
                (job_id, after_id, bounded_limit),
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def list_recent_events(
        self,
        job_id: str,
        *,
        limit: int = 5,
        exclude_types: set[str] | frozenset[str] | tuple[str, ...] = (),
    ) -> list[JobEvent]:
        """Return up to `limit` newest events for `job_id` in chronological order."""
        bounded_limit = max(1, min(limit, 1000))
        excluded = tuple(sorted({str(item) for item in exclude_types if item}))
        with self._connect() as connection:
            if excluded:
                placeholders = ",".join("?" for _ in excluded)
                rows = connection.execute(
                    f"""
                    SELECT * FROM job_events
                    WHERE job_id = ? AND event_type NOT IN ({placeholders})
                    ORDER BY event_id DESC
                    LIMIT ?
                    """,
                    (job_id, *excluded, bounded_limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM job_events
                    WHERE job_id = ?
                    ORDER BY event_id DESC
                    LIMIT ?
                    """,
                    (job_id, bounded_limit),
                ).fetchall()
        return [_event_from_row(row) for row in reversed(rows)]

    def recover_incomplete_jobs(self) -> int:
        active_statuses = (
            JobStatus.QUEUED.value,
            JobStatus.RUNNING.value,
            JobStatus.PAUSED.value,
            JobStatus.CANCELLING.value,
        )
        now = _utc_now()
        error = _dump_json(
            {
                "code": "SERVER_RESTARTED",
                "message": "The server stopped before the job completed.",
            }
        )
        placeholders = ",".join("?" for _ in active_statuses)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT job_id FROM jobs WHERE status IN ({placeholders})",
                active_statuses,
            ).fetchall()
            if not rows:
                return 0
            connection.execute(
                f"""
                UPDATE jobs
                SET status = ?, error_json = ?, finished_at = ?, updated_at = ?
                WHERE status IN ({placeholders})
                """,
                (JobStatus.FAILED.value, error, now, now, *active_statuses),
            )
            connection.executemany(
                """
                INSERT INTO job_events (
                    job_id, event_type, level, message, data_json, created_at
                ) VALUES (?, 'job_interrupted', 'error', ?, ?, ?)
                """,
                [
                    (
                        row["job_id"],
                        "Job interrupted by server restart.",
                        error,
                        now,
                    )
                    for row in rows
                ],
            )
        return len(rows)

    def _migrate(self) -> None:
        with self._connect(configure_wal=True) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            rows = connection.execute("SELECT version FROM schema_migrations").fetchall()
            applied = {int(row["version"]) for row in rows}
            for version in range(1, SCHEMA_VERSION + 1):
                if version in applied:
                    continue
                connection.executescript(MIGRATIONS[version])
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version, _utc_now()),
                )

    def _connect(self, *, configure_wal: bool = False) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA synchronous = NORMAL")
        if configure_wal:
            connection.execute("PRAGMA journal_mode = WAL")
        return connection


def _job_from_row(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        job_id=row["job_id"],
        kind=row["kind"],
        status=JobStatus(row["status"]),
        payload=_load_json(row["payload_json"], {}),
        device_key=row["device_key"],
        current_step=row["current_step"],
        progress=row["progress"],
        result=_load_json(row["result_json"], None),
        error=_load_json(row["error_json"], None),
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        updated_at=row["updated_at"],
    )


def _event_from_row(row: sqlite3.Row) -> JobEvent:
    return JobEvent(
        event_id=int(row["event_id"]),
        job_id=row["job_id"],
        event_type=row["event_type"],
        level=row["level"],
        message=row["message"],
        data=_load_json(row["data_json"], {}),
        created_at=row["created_at"],
    )


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load_json(value: str | None, default: Any) -> Any:
    return default if value is None else json.loads(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
