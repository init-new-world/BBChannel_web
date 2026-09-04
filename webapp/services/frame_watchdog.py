from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from time import monotonic


class FrameStabilityTracker:
    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._digest: bytes | None = None
        self._unchanged_since: float | None = None
        self._last_observed_at: float | None = None
        self._sample_count = 0

    def reset(self) -> None:
        with self._lock:
            self._digest = None
            self._unchanged_since = None
            self._last_observed_at = None
            self._sample_count = 0

    def observe(self, frame: bytes) -> None:
        digest = hashlib.sha256(frame).digest()
        observed_at = self._clock()
        with self._lock:
            if digest != self._digest:
                self._digest = digest
                self._unchanged_since = observed_at
                self._sample_count = 1
            else:
                self._sample_count += 1
            self._last_observed_at = observed_at

    def is_stuck(self, minimum_seconds: float) -> bool:
        if minimum_seconds <= 0:
            return False
        observed_at = self._clock()
        with self._lock:
            if (
                self._sample_count < 2
                or self._unchanged_since is None
                or self._last_observed_at is None
            ):
                return False
            unchanged_seconds = observed_at - self._unchanged_since
            observation_age = observed_at - self._last_observed_at
        recent_limit = max(2.0, min(15.0, minimum_seconds / 2))
        return unchanged_seconds >= minimum_seconds and observation_age <= recent_limit
