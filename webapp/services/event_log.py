from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any


class EventLog:
    def __init__(self, max_events: int = 200) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)

    def info(
        self,
        action: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.add("info", action, message, data)

    def error(
        self,
        action: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.add("error", action, message, data)

    def add(
        self,
        level: str,
        action: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level,
            "action": action,
            "message": message,
            "data": deepcopy(data or {}),
        }
        self._events.append(event)
        return deepcopy(event)

    def recent(self, limit: int | None = None) -> list[dict[str, Any]]:
        events = list(self._events)
        if limit is not None:
            events = events[-limit:]
        return deepcopy(events)
