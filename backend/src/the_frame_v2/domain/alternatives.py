"""Alternatives offered when a slot ends up upscaled. Spec: docs/geometry-and-quality.md §7.6.

Mirrored by `frontend/src/editor/core/alternatives.ts` (conformance fixtures `alternatives.json`).
Each alternative is a ready-to-apply patch of one slot (plus the document's placement/margins when
they must follow); only feasible ones are returned, in the order they should be offered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from the_frame_v2.domain.constraints import SlotState
from the_frame_v2.domain.geometry import Margins, Rect, Size, round_half_even
from the_frame_v2.domain.placement import QualityLock, crop_center, fit_in_mat, margins_for_slot

Placement = Literal["fit_in_mat", "fill", "manual"]
"""Same values as `domain.document.Placement` (kept here so this module stays dependency-free)."""

ALTERNATIVE_IDS = ("keep_framing", "show_more", "shrink", "fit_in_mat")


@dataclass(frozen=True, slots=True)
class Alternative:
    """A full patch: what the slot becomes, and the document changes it implies."""

    id: str
    rect: Rect
    crop: Rect
    quality_lock: QualityLock
    placement: Placement | None = None
    """`None` when the document's placement does not change."""
    margins: Margins | None = None
    """`None` when the margins do not change."""


def _centred(rect: Rect, size: Size) -> Rect:
    return Rect(
        round_half_even(rect.x + (rect.w - size.w) / 2),
        round_half_even(rect.y + (rect.h - size.h) / 2),
        size.w,
        size.h,
    )


def is_upscaled(state: SlotState) -> bool:
    return state.rect.w > state.crop.w or state.rect.h > state.crop.h


def alternatives(
    state: SlotState,
    source: Size,
    lock: QualityLock,
    placement: Placement,
    margins: Margins,
    linked: bool = False,
    crop_ratio: str = "original",
    mirror_x: bool = False,
    mirror_y: bool = False,
) -> list[Alternative]:
    """Feasible ways out of an upscaled slot (empty when the slot is not upscaled).

    * `keep_framing` — accept the enlargement (the lock becomes `free`).
    * `show_more` — the slot is kept and the crop grows to its size (needs a big enough source).
    * `shrink` — the crop is kept and the slot shrinks to it (under `fit_in_mat` the margins grow
      around the smaller slot, keeping their per-side proportions).
    * `fit_in_mat` — leave `fill` and lay the photo inside the mat instead.
    """
    if not is_upscaled(state):
        return []
    rect, crop = state.rect, state.crop
    result = [Alternative("keep_framing", rect, crop, "free")]

    if source.w >= rect.w and source.h >= rect.h:
        cx, cy = crop_center(crop)
        x = min(max(0, round_half_even(cx - rect.w / 2)), source.w - rect.w)
        y = min(max(0, round_half_even(cy - rect.h / 2)), source.h - rect.h)
        result.append(Alternative("show_more", rect, Rect(x, y, rect.w, rect.h), _kept(lock)))

    size = Size(crop.w, crop.h)
    if placement == "fit_in_mat":
        new_margins = margins_for_slot(size, margins, linked, mirror_x=mirror_x, mirror_y=mirror_y)
        shrunk = fit_in_mat(source, crop, crop_ratio, new_margins, "no_upscale").rect
        result.append(Alternative("shrink", shrunk, crop, _kept(lock), None, new_margins))
    else:
        result.append(Alternative("shrink", _centred(rect, size), crop, _kept(lock)))

    if placement == "fill":
        fitted = fit_in_mat(source, crop, crop_ratio, margins, "no_upscale")
        result.append(
            Alternative("fit_in_mat", fitted.rect, fitted.crop, fitted.quality_lock, "fit_in_mat")
        )
    return result


def _kept(lock: QualityLock) -> QualityLock:
    """`free` was chosen because the photo had to be enlarged: go back to the default lock."""
    return lock if lock != "free" else "no_upscale"
