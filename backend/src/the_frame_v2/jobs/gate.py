"""Concurrency bounds for renders (shared by render jobs and on-demand API renders)."""

from __future__ import annotations

import threading


class RenderGate:
    """Per-artwork locks (one render of an artwork at a time) + a global bound on full renders."""

    def __init__(self, workers: int) -> None:
        self.slots = threading.BoundedSemaphore(max(1, workers))
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def artwork_lock(self, artwork_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(artwork_id, threading.Lock())
