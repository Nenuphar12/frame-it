"""Application-wide service container, stored on `app.state.ctx`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from the_frame_v2.auth.ratelimit import RateLimiter
from the_frame_v2.config import Settings
from the_frame_v2.db.session import Database
from the_frame_v2.events import EventBroker
from the_frame_v2.jobs.queue import JobQueue
from the_frame_v2.services.geocode import Geocoder
from the_frame_v2.storage import Storage

if TYPE_CHECKING:
    from the_frame_v2.localsend.runner import LocalSendRunner
    from the_frame_v2.services.localsend import LocalSendHub


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
    localsend_runner: LocalSendRunner | None = None
    """Set while the LocalSend receiver runs (app lifespan)."""
