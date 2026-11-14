from __future__ import annotations

from collections import deque
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from threading import RLock
from typing import Any


EventSubscriber = Callable[[dict[str, Any]], None]


class EventLog:
    def __init__(self, max_events: int = 200) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._lock = RLock()
        self._subscribers: list[EventSubscriber] = []

    def subscribe(self, callback: EventSubscriber) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._subscribers.remove(callback)
                except ValueError:
                    pass

        return unsubscribe

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
        with self._lock:
            self._events.append(event)
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber(deepcopy(event))
            except Exception:
                pass
        return deepcopy(event)

    def recent(self, limit: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            events = list(self._events)
        if limit is not None:
            events = events[-limit:]
        return deepcopy(events)
