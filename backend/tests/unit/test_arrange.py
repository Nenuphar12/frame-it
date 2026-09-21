"""Arranging several slots (§7.7) — behaviour, not fixtures.

The shared Python/TypeScript values live in `conformance/geometry/arrange.json`
(`test_conformance.py`); this file asserts the rules those values must obey.
"""

from __future__ import annotations

import pytest

from the_frame_v2.domain.arrange import (
    Edge,
    align,
    bounding_box,
    distribute,
    new_slot_rect,
    new_slot_size,
    same_size,
)
from the_frame_v2.domain.geometry import Rect, Size

THREE = [
    Rect(200, 200, 1200, 800),
    Rect(1600, 340, 900, 1200),
    Rect(2750, 180, 1000, 700),
]
AREA = Rect(200, 200, 3440, 1760)

EDGES: list[Edge] = ["left", "h_center", "right", "top", "v_center", "bottom"]


def test_bounding_box_spans_every_rect() -> None:
    box = bounding_box(THREE)
    assert (box.x, box.y, box.w, box.h) == (200, 180, 3550, 1360)


@pytest.mark.parametrize("edge", EDGES)
def test_align_is_idempotent_and_keeps_sizes(edge: Edge) -> None:
    once = align(THREE, edge)
    assert [(r.w, r.h) for r in once] == [(r.w, r.h) for r in THREE]
    assert align(once, edge) == once


@pytest.mark.parametrize("edge", EDGES)
def test_align_stays_inside_the_original_bounding_box(edge: Edge) -> None:
    box = bounding_box(THREE)
    for rect in align(THREE, edge):
        assert box.x <= rect.x and rect.x + rect.w <= box.x + box.w
        assert box.y <= rect.y and rect.y + rect.h <= box.y + box.h


def test_align_left_puts_every_rect_on_the_left_edge() -> None:
    assert [r.x for r in align(THREE, "left")] == [200, 200, 200]


def test_distribute_equalises_the_gaps() -> None:
    result = distribute(THREE, "x")
    gaps = [result[i + 1].x - (result[i].x + result[i].w) for i in range(len(result) - 1)]
    assert gaps == [225, 225]
    # The extremes never move.
    assert result[0] == THREE[0] and result[2] == THREE[2]


def test_distribute_keeps_the_input_order() -> None:
    shuffled = [THREE[2], THREE[0], THREE[1]]
    result = distribute(shuffled, "x")
    assert result[0] == THREE[2] and result[1] == THREE[0]
    assert result[2].x == distribute(THREE, "x")[1].x


def test_distribute_needs_three_rects() -> None:
    assert distribute(THREE[:2], "x") == THREE[:2]
    assert distribute([], "y") == []


def test_distribute_is_idempotent() -> None:
    once = distribute(THREE, "y")
    assert distribute(once, "y") == once


def test_same_size_keeps_centres() -> None:
    result = same_size(THREE, 0)
    assert {(r.w, r.h) for r in result} == {(1200, 800)}
    for before, after in zip(THREE, result, strict=True):
        assert before.x + before.w / 2 == pytest.approx(after.x + after.w / 2, abs=1)
        assert before.y + before.h / 2 == pytest.approx(after.y + after.h / 2, abs=1)


def test_new_slot_size_follows_the_photo_aspect() -> None:
    portrait = new_slot_size(AREA, Size(3000, 4000))
    assert portrait.w / portrait.h == pytest.approx(0.75, abs=0.01)
    assert portrait.w <= AREA.w and portrait.h <= AREA.h
    assert new_slot_size(AREA) == Size(1548, 792)


def test_new_slot_rect_is_centred_then_cascades() -> None:
    size = Size(1500, 800)
    first = new_slot_rect([], AREA, size)
    assert first.x + first.w / 2 == AREA.x + AREA.w / 2
    second = new_slot_rect([first], AREA, size)
    assert (second.x, second.y) == (first.x + 96, first.y + 96)
    # A third one only steps aside from a position that is actually taken.
    assert new_slot_rect([second], AREA, size) == first


def test_new_slot_rect_stays_inside_the_area() -> None:
    rect = new_slot_rect([], AREA, Size(4000, 3000))
    assert (rect.w, rect.h) == (4000, 3000)  # bigger than the area: kept, only centred
    inside = new_slot_rect([], AREA, Size(1000, 600))
    assert AREA.x <= inside.x and inside.x + inside.w <= AREA.x + AREA.w
    assert AREA.y <= inside.y and inside.y + inside.h <= AREA.y + AREA.h
