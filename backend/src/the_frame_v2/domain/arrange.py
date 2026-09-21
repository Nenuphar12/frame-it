"""Arranging several slots on the canvas. Spec: docs/geometry-and-quality.md §7.7.

Mirrored by `frontend/src/editor/core/arrange.ts` (conformance fixtures `arrange.json`).

These functions only move and resize *rects*: they never touch a crop, so the caller must run the
result through the constraint solver (§7.3) when a size changes — `same_size` is the only one that
resizes. All of them keep the input order, so a caller can zip the result back onto its slots.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from the_frame_v2.domain.geometry import Rect, Size, round_half_even

Edge = Literal["left", "h_center", "right", "top", "v_center", "bottom"]
Axis = Literal["x", "y"]

NEW_SLOT_FRACTION = 0.45
"""Side of a slot added by the user, as a fraction of the area it is dropped in."""
NEW_SLOT_STEP = 96
"""Cascade offset when a new slot would land exactly on an existing one."""


def bounding_box(rects: Sequence[Rect]) -> Rect:
    """Smallest rect containing them all (1×1 at the origin for an empty sequence)."""
    if not rects:
        return Rect(0, 0, 1, 1)
    left = min(r.x for r in rects)
    top = min(r.y for r in rects)
    right = max(r.x + r.w for r in rects)
    bottom = max(r.y + r.h for r in rects)
    return Rect(left, top, max(1, right - left), max(1, bottom - top))


def align(rects: Sequence[Rect], edge: Edge) -> list[Rect]:
    """Move every rect onto one edge (or centre line) of the group's bounding box.

    Sizes never change, and the reference is the selection itself — aligning twice is a no-op.
    """
    box = bounding_box(rects)
    aligned: list[Rect] = []
    for rect in rects:
        x, y = rect.x, rect.y
        if edge == "left":
            x = box.x
        elif edge == "right":
            x = box.x + box.w - rect.w
        elif edge == "h_center":
            x = box.x + round_half_even((box.w - rect.w) / 2)
        elif edge == "top":
            y = box.y
        elif edge == "bottom":
            y = box.y + box.h - rect.h
        else:
            y = box.y + round_half_even((box.h - rect.h) / 2)
        aligned.append(Rect(x, y, rect.w, rect.h))
    return aligned


def distribute(rects: Sequence[Rect], axis: Axis) -> list[Rect]:
    """Equal gaps along `axis`, the two extreme rects staying where they are.

    Fewer than three rects have no gap to equalise and are returned unchanged. Rects are ordered
    by their current position on the axis, so the visual order is preserved; the result keeps the
    input order. Gaps may be negative (overlapping slots stay overlapping, evenly).
    """
    if len(rects) < 3:
        return list(rects)

    def start(rect: Rect) -> int:
        return rect.x if axis == "x" else rect.y

    def size(rect: Rect) -> int:
        return rect.w if axis == "x" else rect.h

    order = sorted(range(len(rects)), key=lambda i: (start(rects[i]), i))
    first, last = rects[order[0]], rects[order[-1]]
    span = start(last) + size(last) - start(first)
    gap = (span - sum(size(rects[i]) for i in order)) / (len(rects) - 1)
    result = list(rects)
    cursor = float(start(first))
    for position, index in enumerate(order):
        rect = rects[index]
        if position == 0 or position == len(order) - 1:
            cursor = start(rect) + size(rect) + gap
            continue
        value = round_half_even(cursor)
        result[index] = (
            Rect(value, rect.y, rect.w, rect.h)
            if axis == "x"
            else Rect(rect.x, value, rect.w, rect.h)
        )
        cursor += size(rect) + gap
    return result


def same_size(rects: Sequence[Rect], reference: int) -> list[Rect]:
    """Give every rect the size of `rects[reference]`, keeping each one centred where it is."""
    if not rects:
        return []
    model = rects[max(0, min(reference, len(rects) - 1))]
    resized: list[Rect] = []
    for rect in rects:
        cx, cy = rect.x + rect.w / 2, rect.y + rect.h / 2
        resized.append(
            Rect(
                round_half_even(cx - model.w / 2),
                round_half_even(cy - model.h / 2),
                model.w,
                model.h,
            )
        )
    return resized


def new_slot_size(area: Rect, source: Size | None = None) -> Size:
    """Size of a slot the user adds: a fraction of `area`, at the photo's aspect when known."""
    w = max(1, min(area.w, round_half_even(area.w * NEW_SLOT_FRACTION)))
    h = max(1, min(area.h, round_half_even(area.h * NEW_SLOT_FRACTION)))
    if source is None:
        return Size(w, h)
    scale = min(w / source.w, h / source.h)
    return Size(
        max(1, round_half_even(source.w * scale)), max(1, round_half_even(source.h * scale))
    )


def new_slot_rect(existing: Sequence[Rect], area: Rect, size: Size) -> Rect:
    """Where a slot of `size` added by the user lands: centred in `area`, cascaded off the others.

    Two slots added in a row must not hide each other, so a position already taken by an existing
    slot steps aside by `NEW_SLOT_STEP`; the result is then kept inside `area`.
    """
    w, h = max(1, size.w), max(1, size.h)
    x = area.x + round_half_even((area.w - w) / 2)
    y = area.y + round_half_even((area.h - h) / 2)
    taken = {(r.x, r.y) for r in existing}
    for _ in range(len(existing)):
        if (x, y) not in taken:
            break
        x += NEW_SLOT_STEP
        y += NEW_SLOT_STEP
    if w <= area.w:
        x = min(max(area.x, x), area.x + area.w - w)
    if h <= area.h:
        y = min(max(area.y, y), area.y + area.h - h)
    return Rect(x, y, w, h)
