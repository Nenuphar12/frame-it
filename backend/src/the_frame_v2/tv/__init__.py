"""Samsung Frame art-mode client (Phase 12, `docs/tv-display.md`).

The protocol lives behind `TvClient` so the services never import `samsungtvws`, and so the whole
display feature is testable against `FakeTv` — which encodes what the real 2025 firmware does,
including the parts that surprised us (`docs/research/tv-display.md` §2b).
"""

from the_frame_v2.tv.client import (
    SLIDESHOW_MINUTES,
    ArtItem,
    SamsungTvClient,
    TvClient,
    TvError,
    TvInfo,
    TvRejectedError,
    TvUnauthorizedError,
    TvUnreachableError,
    normalize_mac,
    pair_with_tv,
)
from the_frame_v2.tv.discovery import DiscoveredTv
from the_frame_v2.tv.fake import FakeTv

__all__ = [
    "SLIDESHOW_MINUTES",
    "ArtItem",
    "DiscoveredTv",
    "FakeTv",
    "SamsungTvClient",
    "TvClient",
    "TvError",
    "TvInfo",
    "TvRejectedError",
    "TvUnauthorizedError",
    "TvUnreachableError",
    "normalize_mac",
    "pair_with_tv",
]
