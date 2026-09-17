"""Quality tiers and artwork aggregates. Spec: docs/geometry-and-quality.md §7.2.

Mirrored by `frontend/src/editor/core/quality.ts` (conformance fixtures `quality.json`).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from the_frame_v2.domain.geometry import round_half_even

Tier = Literal["native", "downscaled", "upscaled"]
TIER_ORDER: dict[Tier, int] = {"native": 0, "downscaled": 1, "upscaled": 2}


@dataclass(frozen=True, slots=True)
class SlotGeometry:
    """What quality depends on: slot size (canvas px), crop size (source px), rotation."""

    rect_w: int
    rect_h: int
    crop_w: int
    crop_h: int
    rotation: float = 0.0
    has_photo: bool = True


@dataclass(frozen=True, slots=True)
class SlotQuality:
    tier: Tier
    scale: float
    percent: int
    """Badge value: round(scale × 100)."""


@dataclass(frozen=True, slots=True)
class ArtworkQuality:
    worst_tier: Tier | None
    """None when no slot has a photo."""
    min_scale: float | None
    max_scale: float | None
    photo_count: int
    is_incomplete: bool


def slot_scale(slot: SlotGeometry) -> float:
    return max(slot.rect_w / slot.crop_w, slot.rect_h / slot.crop_h)


def slot_quality(slot: SlotGeometry) -> SlotQuality:
    scale = slot_scale(slot)
    tier: Tier
    if slot.rect_w == slot.crop_w and slot.rect_h == slot.crop_h and slot.rotation == 0:
        tier = "native"
    elif scale <= 1:
        tier = "downscaled"
    else:
        tier = "upscaled"
    return SlotQuality(tier=tier, scale=scale, percent=round_half_even(scale * 100))


def artwork_quality(slots: Iterable[SlotGeometry]) -> ArtworkQuality:
    """Empty slots are ignored for tiers and make the artwork incomplete (as do zero slots)."""
    slots = list(slots)
    filled = [slot_quality(s) for s in slots if s.has_photo]
    if not filled:
        return ArtworkQuality(None, None, None, 0, True)
    return ArtworkQuality(
        worst_tier=max(filled, key=lambda q: TIER_ORDER[q.tier]).tier,
        min_scale=min(q.scale for q in filled),
        max_scale=max(q.scale for q in filled),
        photo_count=len(filled),
        is_incomplete=len(filled) < len(slots),
    )
