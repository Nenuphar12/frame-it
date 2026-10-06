"""Application-wide service container, stored on `app.state.ctx`."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from frame_it.auth.ratelimit import RateLimiter
from frame_it.config import Settings
from frame_it.db.session import Database
from frame_it.events import EventBroker
from frame_it.jobs.gate import RenderGate
from frame_it.jobs.queue import JobQueue
from frame_it.services.geocode import Geocoder
from frame_it.storage import Storage

if TYPE_CHECKING:
    from frame_it.db.models import DisplayTarget
    from frame_it.localsend.runner import LocalSendRunner
    from frame_it.services.localsend import LocalSendHub
    from frame_it.tv import TvClient
    from frame_it.tv.discovery import Discover


@dataclass(slots=True)
class AppContext:
    settings: Settings
    storage: Storage
    db: Database
    broker: EventBroker
    jobs: JobQueue
    geocoder: Geocoder
    auth_limiter: RateLimiter
    localsend: LocalSendHub
    render_gate: RenderGate
    localsend_runner: LocalSendRunner | None = None
    """Set while the LocalSend receiver runs (app lifespan)."""
    tv_factory: Callable[[DisplayTarget], TvClient] | None = None
    """How `services/display.py` reaches a TV; tests put a `FakeTv` here."""
    tv_discovery: Discover | None = None
    """How TVs are found on the LAN (`tv/discovery.py`); tests and `fake_tv` replace it."""
    tv_pairer: Callable[[str], str] | None = None
    """host → token (`tv.pair_with_tv`, which needs the TV's prompt accepted); idem."""
