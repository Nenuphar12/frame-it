"""Samsung Frame art-mode client (Phase 12, `docs/tv-display.md`).

The protocol lives behind `TvClient` so the services never import `samsungtvws`, and so the whole
display feature is testable against `FakeTv` — which encodes what the real 2025 firmware does,
including the parts that surprised us (`docs/research/tv-display.md` §2b).
"""

from frame_it.tv.client import (
    SLIDESHOW_MINUTES,
    ArtItem,
    SamsungTvClient,
    TvArtUnavailableError,
    TvClient,
    TvError,
    TvInfo,
    TvRejectedError,
    TvUnauthorizedError,
    TvUnreachableError,
    normalize_mac,
    pair_with_tv,
)
from frame_it.tv.discovery import DiscoveredTv
from frame_it.tv.fake import FakeTv

__all__ = [
    "SLIDESHOW_MINUTES",
    "ArtItem",
    "DiscoveredTv",
    "FakeTv",
    "SamsungTvClient",
    "TvArtUnavailableError",
    "TvClient",
    "TvError",
    "TvInfo",
    "TvRejectedError",
    "TvUnauthorizedError",
    "TvUnreachableError",
    "normalize_mac",
    "pair_with_tv",
]
