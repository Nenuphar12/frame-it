"""Application-wide service container, stored on `app.state.ctx`."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from the_frame_v2.auth.ratelimit import RateLimiter
from the_frame_v2.config import Settings
from the_frame_v2.db.session import Database
from the_frame_v2.events import EventBroker
from the_frame_v2.jobs.gate import RenderGate
from the_frame_v2.jobs.queue import JobQueue
from the_frame_v2.services.geocode import Geocoder
from the_frame_v2.storage import Storage

if TYPE_CHECKING:
    from the_frame_v2.db.models import DisplayTarget
    from the_frame_v2.localsend.runner import LocalSendRunner
    from the_frame_v2.services.localsend import LocalSendHub
    from the_frame_v2.tv import TvClient
    from the_frame_v2.tv.discovery import Discover


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
