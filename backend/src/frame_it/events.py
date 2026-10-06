"""In-process event broker feeding the SSE endpoint. `publish` is thread-safe."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

Audience = Literal["admin", "all"]


@dataclass(frozen=True, slots=True)
class Event:
    name: str
    data: dict[str, Any]
    audience: Audience = "admin"
    device_key: str | None = None
    """When set, uploaders only receive the event if it concerns their own device."""


@dataclass(slots=True, eq=False)
class _Subscriber:
    queue: asyncio.Queue[Event]
    is_admin: bool
    device_key: str | None
    dropped: int = field(default=0)


class EventBroker:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[_Subscriber] = set()
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, event: Event) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        with contextlib.suppress(RuntimeError):  # loop shutting down
            loop.call_soon_threadsafe(self._dispatch, event)

    def _dispatch(self, event: Event) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for sub in subscribers:
            if not self._visible(sub, event):
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                sub.dropped += 1

    @staticmethod
    def _visible(sub: _Subscriber, event: Event) -> bool:
        if sub.is_admin:
            return True
        if event.audience == "all":
            return True
        return event.device_key is not None and event.device_key == sub.device_key

    async def subscribe(self, *, is_admin: bool, device_key: str | None) -> AsyncIterator[Event]:
        sub = _Subscriber(asyncio.Queue(maxsize=256), is_admin, device_key)
        with self._lock:
            self._subscribers.add(sub)
        try:
            while True:
                yield await sub.queue.get()
        finally:
            with self._lock:
                self._subscribers.discard(sub)
