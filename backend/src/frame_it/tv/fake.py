"""A Frame that behaves like the real one, without the Frame.

Every rule here was measured on a 2025 unit (`docs/research/tv-display.md`), including the ones
that cost us a round of testing:

- `select_image` **stops** a running slideshow;
- setting a slideshow does **not** move the panel;
- the slideshow covers a whole category — `content_list` is reported, never accepted;
- intervals outside `SLIDESHOW_MINUTES` are refused;
- items are listed **newest first**.

Tests drive this through the same `TvClient` protocol the real client implements, so a push that
works here is a push that works there.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from frame_it.tv.client import (
    MY_PICTURES,
    SLIDESHOW_MINUTES,
    STORE,
    ArtItem,
    FileType,
    TvArtUnavailableError,
    TvInfo,
    TvRejectedError,
    TvUnauthorizedError,
    TvUnreachableError,
)
from frame_it.tv.discovery import DiscoveredTv


@dataclass
class FakeTv:
    """In-memory TV. `uploads` keeps the bytes so tests can assert what was sent."""

    host: str = "192.0.2.10"
    token: str | None = "fake-token"  # noqa: S105 - a fake TV, not a secret
    name: str = '55" The Frame'
    model: str = "QE55LS03FAU"
    model_code: str = "25_PTM_FTV"
    mac: str = "02:00:5e:00:53:10"
    api_version: str = "5.0.1.0"
    reachable: bool = True
    authorized: bool = True
    art_mode: bool = True
    #: False = the TV is off: it takes the connection, its art app never answers.
    art_ready: bool = True
    #: Content ids in the order the TV would list them (newest first).
    items_: list[ArtItem] = field(default_factory=list)
    uploads: dict[str, bytes] = field(default_factory=dict)
    slideshow_minutes: int | None = None
    slideshow_ordered: bool = True
    current_content_id: str | None = None
    #: Every call made, in order — the push sequence is part of the contract.
    calls: list[str] = field(default_factory=list)
    #: Seconds an upload takes (the real one takes 4 to 6 s): lets a browser check see progress.
    upload_delay: float = 0.0
    #: Fail every call after this many uploads (a TV going to sleep mid-push), None = never.
    unreachable_after_uploads: int | None = None
    _next: int = 100
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ---- helpers used by tests ---------------------------------------------------------------
    def with_existing(self, count: int, *, category: str = MY_PICTURES) -> FakeTv:
        """Pretend somebody already put `count` photos on the TV (as our user had 64)."""
        for _ in range(count):
            self._next += 1
            self.items_.insert(
                0,
                ArtItem(
                    content_id=f"MY_F{self._next:04d}",
                    category_id=category,
                    width=3840,
                    height=2160,
                ),
            )
        if self.current_content_id is None and self.items_:
            self.current_content_id = self.items_[0].content_id
        return self

    def my_ids(self) -> list[str]:
        return [i.content_id for i in self.items_ if i.category_id == MY_PICTURES]

    def describe(self) -> DiscoveredTv:
        """What this TV's REST endpoint would answer to a discovery sweep."""
        return DiscoveredTv(
            host=self.host,
            name=self.name,
            model=self.model,
            model_code=self.model_code,
            frame_support=True,
            token_auth=True,
            mac=self.mac,
            power_state="on",
        )

    def _guard(self) -> None:
        if not self.reachable:
            raise TvUnreachableError("fake TV is unreachable")
        if not self.art_ready:
            raise TvArtUnavailableError("fake TV is off")
        if not self.authorized:
            raise TvUnauthorizedError("fake TV has forgotten the token")

    # ---- TvClient ----------------------------------------------------------------------------
    def info(self) -> TvInfo:
        self._guard()
        self.calls.append("info")
        return TvInfo(
            model=self.model,
            model_code=self.model_code,
            name=self.name,
            mac=self.mac,
            api_version=self.api_version,
            frame_support=True,
            token_auth=True,
            art_mode=self.art_mode,
            my_pictures=sum(1 for i in self.items_ if i.category_id == MY_PICTURES),
            store_items=sum(1 for i in self.items_ if i.category_id == STORE),
            slideshow_minutes=self.slideshow_minutes,
            slideshow_ordered=self.slideshow_ordered,
            current_content_id=self.current_content_id,
        )

    def items(self, category: str | None = MY_PICTURES) -> list[ArtItem]:
        self._guard()
        self.calls.append("items")
        if category is None:
            return list(self.items_)
        return [i for i in self.items_ if i.category_id == category]

    def upload(self, data: bytes, file_type: FileType, image_date: str | None = None) -> str:
        self._guard()
        if self.upload_delay:
            time.sleep(self.upload_delay)
        with self._lock:
            self._next += 1
            content_id = f"MY_F{self._next:04d}"
            self.calls.append(f"upload:{content_id}")
            self.uploads[content_id] = bytes(data)
            # Newest first, like the real one.
            self.items_.insert(
                0,
                ArtItem(
                    content_id=content_id,
                    category_id=MY_PICTURES,
                    width=3840,
                    height=2160,
                    image_date=image_date or datetime.now(UTC).strftime("%Y:%m:%d %H:%M:%S"),
                    matte_id="none",
                ),
            )
            if (
                self.unreachable_after_uploads is not None
                and len(self.uploads) >= self.unreachable_after_uploads
            ):
                self.reachable = False
        return content_id

    def delete(self, content_ids: list[str]) -> None:
        self._guard()
        if not content_ids:
            return
        self.calls.append(f"delete:{','.join(content_ids)}")
        doomed = set(content_ids)
        with self._lock:
            self.items_ = [i for i in self.items_ if i.content_id not in doomed]
        if self.current_content_id in doomed:
            self.current_content_id = self.items_[0].content_id if self.items_ else None

    def select(self, content_id: str) -> None:
        self._guard()
        if content_id not in {i.content_id for i in self.items_}:
            raise TvRejectedError(f"no such content id {content_id}")
        self.calls.append(f"select:{content_id}")
        self.current_content_id = content_id
        # Measured: selecting an image stops the slideshow.
        self.slideshow_minutes = None

    def stop_slideshow(self) -> None:
        self._guard()
        self.calls.append("stop_slideshow")
        self.slideshow_minutes = None

    def start_slideshow(self, minutes: int, ordered: bool = True) -> None:
        self._guard()
        if minutes not in SLIDESHOW_MINUTES:
            raise TvRejectedError(f"error number -7 ({minutes} min is not accepted)")
        self.calls.append(f"start_slideshow:{minutes}:{'ordered' if ordered else 'shuffle'}")
        self.slideshow_minutes = minutes
        self.slideshow_ordered = ordered
        # Measured: starting a slideshow does not move the panel.

    def close(self) -> None:
        self.calls.append("close")
