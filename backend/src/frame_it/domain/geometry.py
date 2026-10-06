"""Pure integer geometry. Spec: docs/geometry-and-quality.md §7.1.

Mirrored by `frontend/src/editor/core/geometry.ts`; parity checked by `conformance/geometry/*.json`.
Rounding rule: compute in floats, round half to even on final integer fields only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

CANVAS_WIDTH = 3840
CANVAS_HEIGHT = 2160


@dataclass(frozen=True, slots=True)
class Size:
    w: int
    h: int


@dataclass(frozen=True, slots=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True, slots=True)
class Margins:
    top: int
    right: int
    bottom: int
    left: int


@dataclass(frozen=True, slots=True)
class Orient:
    rotate: int = 0
    """0, 90, 180 or 270 (clockwise), applied after EXIF orientation."""
    flip_h: bool = False
    """Applied after `rotate`."""


CANVAS = Size(CANVAS_WIDTH, CANVAS_HEIGHT)


def round_half_even(value: float) -> int:
    """Round to the nearest integer, ties to even (same algorithm in TypeScript)."""
    floor = math.floor(value)
    diff = value - floor
    if diff > 0.5:
        return floor + 1
    if diff < 0.5:
        return floor
    return floor if floor % 2 == 0 else floor + 1


def oriented_size(source: Size, orient: Orient) -> Size:
    """Size of the source after `orient` (flip does not change it)."""
    return Size(source.h, source.w) if orient.rotate in (90, 270) else source


def _rotate_cw(rect: Rect, space: Size) -> tuple[Rect, Size]:
    """Rotate `rect` living in `space` by 90° clockwise."""
    return Rect(space.h - rect.y - rect.h, rect.x, rect.h, rect.w), Size(space.h, space.w)


def _flip_h(rect: Rect, space: Size) -> Rect:
    return Rect(space.w - rect.x - rect.w, rect.y, rect.w, rect.h)


def rect_to_oriented(rect: Rect, source: Size, orient: Orient) -> Rect:
    """Map a rect from the (EXIF-oriented) source space into the `orient` space."""
    space = source
    for _ in range(orient.rotate // 90):
        rect, space = _rotate_cw(rect, space)
    return _flip_h(rect, space) if orient.flip_h else rect


def rect_from_oriented(rect: Rect, source: Size, orient: Orient) -> Rect:
    """Inverse of `rect_to_oriented`."""
    space = oriented_size(source, orient)
    if orient.flip_h:
        rect = _flip_h(rect, space)
    for _ in range((360 - orient.rotate) % 360 // 90):
        rect, space = _rotate_cw(rect, space)
    return rect


def reorient_crop(crop: Rect, source: Size, old: Orient, new: Orient) -> Rect:
    """Changing `orient` transforms the existing crop into the new space (not a reset)."""
    return rect_to_oriented(rect_from_oriented(crop, source, old), source, new)


def crop_within(crop: Rect, bounds: Size) -> bool:
    return (
        crop.x >= 0
        and crop.y >= 0
        and crop.w >= 1
        and crop.h >= 1
        and crop.x + crop.w <= bounds.w
        and crop.y + crop.h <= bounds.h
    )


def aspect_consistent(rect_w: int, rect_h: int, crop_w: int, crop_h: int) -> bool:
    """Slot and crop have the same aspect ratio up to integer rounding of either side.

    `|rect.w·crop.h − rect.h·crop.w| ≤ (rect.w + rect.h + crop.w + crop.h) / 2`: rounding the slot
    from the crop (or the crop from the slot) changes each side by at most 0.5.
    """
    return 2 * abs(rect_w * crop_h - rect_h * crop_w) <= rect_w + rect_h + crop_w + crop_h


def parse_ratio(crop_ratio: str, source: Size) -> float | None:
    """Aspect ratio (w/h) imposed by `crop_ratio`; None for `free`."""
    if crop_ratio == "free":
        return None
    if crop_ratio == "original":
        return source.w / source.h
    width, height = crop_ratio.split(":")
    return int(width) / int(height)


def rotated_bounds(rect_x: float, rect_y: float, w: float, h: float, degrees: float) -> Rect:
    """Integer bounding box of a `w×h` box at (rect_x, rect_y) rotated around its centre."""
    cx, cy = rect_x + w / 2, rect_y + h / 2
    radians = math.radians(degrees)
    cos, sin = abs(math.cos(radians)), abs(math.sin(radians))
    half_w = (w * cos + h * sin) / 2
    half_h = (w * sin + h * cos) / 2
    left, top = math.floor(cx - half_w + 1e-9), math.floor(cy - half_h + 1e-9)
    right, bottom = math.ceil(cx + half_w - 1e-9), math.ceil(cy + half_h - 1e-9)
    return Rect(left, top, right - left, bottom - top)
