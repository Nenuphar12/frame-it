"""Placement modes and native linking. Spec: docs/geometry-and-quality.md §7.4.

Mirrored by `frontend/src/editor/core/placement.ts` (conformance fixtures `placement.json`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from the_frame_v2.domain.geometry import CANVAS, Margins, Rect, Size, parse_ratio, round_half_even

QualityLock = Literal["native", "no_upscale", "free"]


@dataclass(frozen=True, slots=True)
class SlotPlacement:
    rect: Rect
    crop: Rect
    quality_lock: QualityLock
    """May be relaxed to `free` when the requested lock cannot be honoured (see callers)."""


def available_area(margins: Margins, canvas: Size = CANVAS) -> Rect:
    """Canvas minus margins (at least 1×1)."""
    return Rect(
        margins.left,
        margins.top,
        max(1, canvas.w - margins.left - margins.right),
        max(1, canvas.h - margins.top - margins.bottom),
    )


def fit_rect(area: Rect, content: Size, lock: QualityLock) -> Rect:
    """Largest rect with `content`'s aspect inside `area`, limited by the lock, centred."""
    scale = min(area.w / content.w, area.h / content.h)
    if lock == "no_upscale":
        scale = min(scale, 1.0)
    elif lock == "native":
        scale = 1.0
    w = content.w if scale == 1.0 else max(1, round_half_even(content.w * scale))
    h = content.h if scale == 1.0 else max(1, round_half_even(content.h * scale))
    return Rect(
        area.x + round_half_even((area.w - w) / 2),
        area.y + round_half_even((area.h - h) / 2),
        w,
        h,
    )


def largest_crop(
    bounds: Size, ratio: float | None, center: tuple[float, float] | None = None
) -> Rect:
    """Largest crop with `ratio` (w/h; None = any) in `bounds`, centred on `center`, clamped."""
    if ratio is None:
        w, h = bounds.w, bounds.h
    elif bounds.w / bounds.h > ratio:
        h = bounds.h
        w = min(bounds.w, max(1, round_half_even(h * ratio)))
    else:
        w = bounds.w
        h = min(bounds.h, max(1, round_half_even(w / ratio)))
    cx, cy = center if center is not None else (bounds.w / 2, bounds.h / 2)
    x = min(max(0, round_half_even(cx - w / 2)), bounds.w - w)
    y = min(max(0, round_half_even(cy - h / 2)), bounds.h - h)
    return Rect(x, y, w, h)


def crop_center(crop: Rect) -> tuple[float, float]:
    return crop.x + crop.w / 2, crop.y + crop.h / 2


def native_crop_for_area(area: Size, source: Size, crop_ratio: str, previous: Rect) -> Rect:
    """Native linking, margins edited: the crop takes the available area's size.

    `free` ratio: crop = area clamped to the source. Otherwise the largest crop with the ratio
    fitting the area, clamped to the source. Centred on the previous crop centre, kept inside
    the source.
    """
    bounds = Size(min(area.w, source.w), min(area.h, source.h))
    ratio = parse_ratio(crop_ratio, source)
    size = largest_crop(bounds, ratio)
    cx, cy = crop_center(previous)
    x = min(max(0, round_half_even(cx - size.w / 2)), source.w - size.w)
    y = min(max(0, round_half_even(cy - size.h / 2)), source.h - size.h)
    return Rect(x, y, size.w, size.h)


def margins_for_slot(slot: Size, previous: Margins, linked: bool, canvas: Size = CANVAS) -> Margins:
    """Native linking, crop edited: redistribute the free space around a slot of size `slot`.

    Per-side proportions of `previous` are preserved (equal split when both sides were 0). When
    `linked`, all four margins take the smallest half of the free space (margins are minimums).
    """
    extra_x = max(0, canvas.w - slot.w)
    extra_y = max(0, canvas.h - slot.h)
    if linked:
        uniform = math.floor(min(extra_x, extra_y) / 2)
        return Margins(uniform, uniform, uniform, uniform)
    left = _share(extra_x, previous.left, previous.right)
    top = _share(extra_y, previous.top, previous.bottom)
    return Margins(top=top, right=extra_x - left, bottom=extra_y - top, left=left)


def _share(extra: int, first: int, second: int) -> int:
    total = first + second
    return round_half_even(extra / 2) if total == 0 else round_half_even(extra * first / total)


def fit_in_mat(
    source: Size, crop: Rect, crop_ratio: str, margins: Margins, lock: QualityLock
) -> SlotPlacement:
    """`fit_in_mat` placement for a single slot (margins are minimums).

    `native`: the slot is the crop size; when the crop does not fit the available area, the crop is
    reduced by native linking first.
    """
    area = available_area(margins)
    if lock == "native":
        if crop.w > area.w or crop.h > area.h:
            crop = native_crop_for_area(Size(area.w, area.h), source, crop_ratio, crop)
        return SlotPlacement(fit_rect(area, Size(crop.w, crop.h), "native"), crop, "native")
    return SlotPlacement(fit_rect(area, Size(crop.w, crop.h), lock), crop, lock)


def centered_crop(source: Size, size: Size) -> Rect:
    """Crop of exactly `size` centred in `source` (caller ensures it fits)."""
    return Rect(
        round_half_even((source.w - size.w) / 2),
        round_half_even((source.h - size.h) / 2),
        size.w,
        size.h,
    )


def fill(source: Size, lock: QualityLock, canvas: Size = CANVAS) -> SlotPlacement:
    """`fill` placement: slot = canvas, crop = largest centred crop with the canvas ratio.

    `native` uses a canvas-sized centred crop when the source is large enough. A lock that the
    source cannot honour becomes `free` (the editor then offers alternatives, §7.6).
    """
    return fill_slot(Rect(0, 0, canvas.w, canvas.h), source, lock)


def fill_slot(rect: Rect, source: Size, lock: QualityLock) -> SlotPlacement:
    """Slot kept as is, photo cropped to the slot ratio (centred). Used by `fill` and layouts."""
    target = Size(rect.w, rect.h)
    if lock == "native" and source.w >= rect.w and source.h >= rect.h:
        return SlotPlacement(rect, centered_crop(source, target), "native")
    crop = largest_crop(source, rect.w / rect.h)
    upscaled = rect.w > crop.w or rect.h > crop.h
    if lock == "native" or (lock == "no_upscale" and upscaled):
        return SlotPlacement(rect, crop, "free")
    return SlotPlacement(rect, crop, lock)


def fit_slot(rect: Rect, source: Size, lock: QualityLock) -> SlotPlacement:
    """Layout slot in `fit` mode: whole photo, slot shrunk to the photo ratio inside the rect."""
    crop = Rect(0, 0, source.w, source.h)
    if lock == "native" and (source.w > rect.w or source.h > rect.h):
        lock = "no_upscale"
    return SlotPlacement(fit_rect(rect, source, lock), crop, lock)


def ratio_label(w: int, h: int) -> str:
    """`w:h` reduced by their greatest common divisor (crop ratio of a layout slot)."""
    divisor = math.gcd(w, h)
    return f"{w // divisor}:{h // divisor}"
