"""Editor constraint solver: keeps a slot valid while the user resizes it or its crop.

Spec: docs/geometry-and-quality.md §7.3. Mirrored by `frontend/src/editor/core/constraints.ts`
(conformance fixtures `constraints.json`).

Two invariants are never broken, whatever the user drags:

* **aspect consistency** — `rect` and `crop` always describe the same rectangle
  (`geometry.aspect_consistent`), so one of the two always follows the other;
* **the quality lock** — `native` ⇒ `rect` size = `crop` size, `no_upscale` ⇒ `rect` ≤ `crop`.

Slot resizing uses *cover* semantics: the requested size is a box the slot must cover, so
dragging a single edge outwards grows the slot even though the other axis did not move.
"""

from __future__ import annotations

from dataclasses import dataclass

from the_frame_v2.domain.geometry import Rect, Size, aspect_consistent, round_half_even
from the_frame_v2.domain.placement import QualityLock, SlotPlacement, crop_center, largest_crop

MIN_SIZE = 1
CENTER = (0.5, 0.5)


@dataclass(frozen=True, slots=True)
class SlotState:
    """The part of a slot the solver reasons about."""

    rect: Rect
    crop: Rect

    @property
    def scale(self) -> float:
        return max(self.rect.w / self.crop.w, self.rect.h / self.crop.h)


def _anchored(rect: Rect, size: Size, anchor: tuple[float, float]) -> Rect:
    """`size` placed so that the anchor point of `rect` stays where it is."""
    ax, ay = anchor
    return Rect(
        round_half_even(rect.x + ax * (rect.w - size.w)),
        round_half_even(rect.y + ay * (rect.h - size.h)),
        size.w,
        size.h,
    )


def _cover(requested: Size, content: Size) -> Size:
    """Smallest size with `content`'s aspect that covers `requested` (at least 1×1)."""
    scale = max(requested.w / content.w, requested.h / content.h)
    return Size(
        max(MIN_SIZE, round_half_even(content.w * scale)),
        max(MIN_SIZE, round_half_even(content.h * scale)),
    )


def _crop_of_size(size: Size, source: Size, around: Rect) -> Rect:
    """Crop of (at most) `size`, centred on `around`'s centre and kept inside the source."""
    w = max(MIN_SIZE, min(size.w, source.w))
    h = max(MIN_SIZE, min(size.h, source.h))
    cx, cy = crop_center(around)
    x = min(max(0, round_half_even(cx - w / 2)), source.w - w)
    y = min(max(0, round_half_even(cy - h / 2)), source.h - h)
    return Rect(x, y, w, h)


def clamp_crop(crop: Rect, source: Size) -> Rect:
    """Crop kept inside the source, at least 1×1 (size is reduced before the position moves)."""
    w = max(MIN_SIZE, min(crop.w, source.w))
    h = max(MIN_SIZE, min(crop.h, source.h))
    return Rect(min(max(0, crop.x), source.w - w), min(max(0, crop.y), source.h - h), w, h)


def resize_slot(
    state: SlotState,
    requested: Size,
    source: Size,
    lock: QualityLock,
    anchor: tuple[float, float] = CENTER,
) -> SlotPlacement:
    """Resolve a slot resize (drag of a slot handle) under `lock`.

    `anchor` is the point of the current rect that stays fixed (`(0, 0)` = top-left corner,
    `(0.5, 0.5)` = growth centred on the slot).
    """
    crop = state.crop
    wanted = _cover(requested, Size(crop.w, crop.h))
    if lock == "native":
        # The crop follows the slot size, centred on the current crop; a too-small source clamps
        # the slot instead (rect size = crop size is mandatory under `native`).
        crop = _crop_of_size(wanted, source, crop)
        return SlotPlacement(_anchored(state.rect, Size(crop.w, crop.h), anchor), crop, "native")
    if lock == "no_upscale" and (wanted.w > crop.w or wanted.h > crop.h):
        # Grow the crop (same aspect, around its centre) as far as the source allows, then clamp.
        grown = largest_crop(
            Size(min(wanted.w, source.w), min(wanted.h, source.h)), crop.w / crop.h
        )
        crop = _crop_of_size(Size(grown.w, grown.h), source, crop)
        wanted = Size(min(wanted.w, crop.w), min(wanted.h, crop.h))
    return SlotPlacement(_anchored(state.rect, wanted, anchor), crop, lock)


def resize_crop(
    state: SlotState, requested: Rect, source: Size, lock: QualityLock
) -> SlotPlacement:
    """Resolve a crop change (crop handles, pan, zoom) under `lock`.

    The crop is clamped into the source. The slot follows only when it has to: under `native`
    always (the scale stays exactly 1), under `no_upscale` the crop is clamped so it never becomes
    smaller than the slot (the photo never starts being enlarged), and under any lock when the
    crop's aspect changed (`crop_ratio = free`) — the current scale is then preserved.
    """
    crop = clamp_crop(requested, source)
    if lock == "native":
        return SlotPlacement(_anchored(state.rect, Size(crop.w, crop.h), CENTER), crop, "native")
    if lock == "no_upscale" and (crop.w < state.rect.w or crop.h < state.rect.h):
        wanted = _cover(Size(state.rect.w, state.rect.h), Size(crop.w, crop.h))
        crop = _crop_of_size(wanted, source, crop)
        if crop.w < state.rect.w or crop.h < state.rect.h:  # source too small: shrink the slot
            return SlotPlacement(_anchored(state.rect, Size(crop.w, crop.h), CENTER), crop, lock)
        return SlotPlacement(state.rect, crop, lock)
    if aspect_consistent(state.rect.w, state.rect.h, crop.w, crop.h):
        return SlotPlacement(state.rect, crop, lock)
    scale = state.scale
    size = Size(
        max(MIN_SIZE, round_half_even(crop.w * scale)),
        max(MIN_SIZE, round_half_even(crop.h * scale)),
    )
    return SlotPlacement(_anchored(state.rect, size, CENTER), crop, lock)


def pan_crop(state: SlotState, dx: int, dy: int, source: Size) -> Rect:
    """Move the crop inside the source (the slot never moves): the photo pans inside the slot."""
    crop = state.crop
    return clamp_crop(Rect(crop.x + dx, crop.y + dy, crop.w, crop.h), source)


def zoom_crop(state: SlotState, factor: float, source: Size, lock: QualityLock) -> SlotPlacement:
    """Zoom the photo inside the slot: `factor > 1` shows more of it, `< 1` crops tighter.

    The crop keeps the **rect's** aspect, whatever the factor: the width is scaled and the height
    derived from it. Rounding the two sides on their own drifts, and so does re-deriving the aspect
    from the rounded crop at every step — the rect is the one reference that does not move. A crop
    whose aspect has drifted away from its rect's makes `resize_crop` resize the *slot* to match,
    which is the "zoom out and the frame changes size" bug. The bound is `largest_crop`, the widest
    crop of that aspect inside the photo, so zooming out lands exactly on the whole photo instead
    of clamping each axis against an edge.

    A zoom always moves by at least one pixel when it can: `round_half_even(8 * 1.06) == 8` left a
    crop that had been zoomed in far enough stuck at its size for ever, with no way back out.
    """
    ratio = state.rect.w / state.rect.h
    full = largest_crop(source, ratio)
    width = max(MIN_SIZE, min(full.w, round_half_even(state.crop.w * factor)))
    if width == state.crop.w and factor > 1:
        width = min(full.w, width + 1)
    elif width == state.crop.w and factor < 1:
        width = max(MIN_SIZE, width - 1)
    height = max(MIN_SIZE, min(full.h, round_half_even(width / ratio)))
    center_x, center_y = crop_center(state.crop)
    requested = Rect(
        min(max(0, round_half_even(center_x - width / 2)), source.w - width),
        min(max(0, round_half_even(center_y - height / 2)), source.h - height),
        width,
        height,
    )
    return resize_crop(state, requested, source, lock)


def apply_lock(state: SlotState, lock: QualityLock, source: Size) -> SlotPlacement:
    """Repair a slot after the user switched its quality lock, preserving the framing.

    `native` takes the crop at the slot's size (scale 1, same framing, clamped to the source);
    `no_upscale` shrinks an enlarged slot to its crop size around its centre; `free` changes
    nothing.
    """
    if lock == "native":
        crop = _crop_of_size(Size(state.rect.w, state.rect.h), source, state.crop)
        return SlotPlacement(_anchored(state.rect, Size(crop.w, crop.h), CENTER), crop, "native")
    if lock == "no_upscale" and (state.rect.w > state.crop.w or state.rect.h > state.crop.h):
        size = Size(state.crop.w, state.crop.h)
        return SlotPlacement(_anchored(state.rect, size, CENTER), state.crop, lock)
    return SlotPlacement(state.rect, state.crop, lock)


def apply_crop_ratio(
    state: SlotState, ratio: float | None, source: Size, lock: QualityLock
) -> SlotPlacement:
    """Re-crop to a new ratio (`ratio` = w/h, `None` for `free`), centred on the current crop.

    The new crop is the largest rect with that ratio inside the current crop; the lock then
    resolves the slot (`no_upscale` may grow the crop back, `native` follows it).
    """
    if ratio is None:
        return SlotPlacement(state.rect, state.crop, lock)
    size = largest_crop(Size(state.crop.w, state.crop.h), ratio)
    crop = _crop_of_size(Size(size.w, size.h), source, state.crop)
    return resize_crop(state, crop, source, lock)
