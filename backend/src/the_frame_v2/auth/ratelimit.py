"""Small in-memory sliding-window rate limiter for authentication attempts."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limits: list[tuple[int, float]]) -> None:
        """`limits`: list of (max_events, window_seconds); all must hold."""
        self._limits = limits
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._max_window = max(w for _, w in limits)

    def hit(self, key: str, now: float | None = None) -> bool:
        """Record an attempt. Returns False if the key is over any limit (attempt not recorded)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            events = self._events[key]
            while events and now - events[0] > self._max_window:
                events.popleft()
            for max_events, window in self._limits:
                if sum(1 for t in events if now - t <= window) >= max_events:
                    return False
            events.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
