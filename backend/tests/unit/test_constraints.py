"""Constraint solver and alternatives (§7.3, §7.6) — behaviour, not fixtures.

The shared Python/TypeScript values live in `conformance/geometry/{constraints,alternatives}.json`
(`test_conformance.py`); this file asserts the rules those values must obey.
"""

from __future__ import annotations

import pytest

from frame_it.domain.alternatives import alternatives
from frame_it.domain.constraints import (
    SlotState,
    apply_crop_ratio,
    apply_lock,
    pan_crop,
    resize_crop,
    resize_slot,
    zoom_crop,
)
from frame_it.domain.geometry import Margins, Rect, Size, aspect_consistent
from frame_it.domain.placement import SlotPlacement, fit_in_mat, margins_for_slot
from frame_it.domain.quality import SlotGeometry, slot_quality

SRC = Size(6000, 4000)
SMALL = Size(1000, 800)
FIT = SlotState(Rect(645, 200, 2550, 1700), Rect(0, 0, 6000, 4000))
NATIVE = SlotState(Rect(920, 580, 2000, 1333), Rect(2000, 1300, 2000, 1333))
UPSCALED = SlotState(Rect(400, 200, 2000, 1600), Rect(0, 0, 1000, 800))


def check(result: SlotPlacement, source: Size = SRC) -> SlotPlacement:
    """Every solver result must produce a document the server would accept."""
    rect, crop = result.rect, result.crop
    assert rect.w >= 1 and rect.h >= 1 and crop.w >= 1 and crop.h >= 1
    assert aspect_consistent(rect.w, rect.h, crop.w, crop.h), f"aspect broken: {result}"
    assert crop.x >= 0 and crop.y >= 0
    assert crop.x + crop.w <= source.w and crop.y + crop.h <= source.h
    if result.quality_lock == "native":
        assert (rect.w, rect.h) == (crop.w, crop.h)
    if result.quality_lock == "no_upscale":
        assert rect.w <= crop.w and rect.h <= crop.h
    return result


def scale(result: SlotPlacement) -> float:
    return slot_quality(
        SlotGeometry(result.rect.w, result.rect.h, result.crop.w, result.crop.h, 0, True)
    ).scale


# ---- slot resizing ------------------------------------------------------------------------------
def test_free_resize_keeps_the_crop_and_covers_the_request() -> None:
    result = check(resize_slot(FIT, Size(3000, 1000), SRC, "free"))
    assert result.crop == FIT.crop
    assert result.rect.w >= 3000 and result.rect.h >= 1000


def test_anchor_decides_which_corner_stays() -> None:
    centred = resize_slot(FIT, Size(3000, 2000), SRC, "free")
    corner = resize_slot(FIT, Size(3000, 2000), SRC, "free", anchor=(0.0, 0.0))
    assert (corner.rect.x, corner.rect.y) == (FIT.rect.x, FIT.rect.y)
    assert centred.rect.x < corner.rect.x and centred.rect.y < corner.rect.y


def test_no_upscale_grows_the_crop_before_clamping() -> None:
    zoomed = SlotState(Rect(645, 200, 2550, 1700), Rect(2000, 1000, 3000, 2000))
    grown = check(resize_slot(zoomed, Size(3000, 2000), SRC, "no_upscale"))
    assert (grown.crop.w, grown.crop.h) == (3000, 2000)
    assert scale(grown) == pytest.approx(1.0)

    # The source cannot give more: the slot is clamped instead of upscaling the photo.
    clamped = check(
        resize_slot(
            SlotState(Rect(0, 0, 1000, 800), Rect(0, 0, 1000, 800)),
            Size(2000, 1600),
            SMALL,
            "no_upscale",
        ),
        SMALL,
    )
    assert (clamped.rect.w, clamped.rect.h) == (1000, 800)


def test_native_resize_keeps_scale_exactly_one() -> None:
    for requested in (Size(2000, 1400), Size(500, 400), Size(9000, 9000)):
        result = check(resize_slot(NATIVE, requested, SRC, "native"))
        assert (result.rect.w, result.rect.h) == (result.crop.w, result.crop.h)
        assert scale(result) == 1.0


# ---- crop editing -------------------------------------------------------------------------------
def test_crop_change_keeps_the_slot_when_the_aspect_holds() -> None:
    result = check(resize_crop(FIT, Rect(500, 400, 3000, 2000), SRC, "free"))
    assert result.rect == FIT.rect
    assert result.crop == Rect(500, 400, 3000, 2000)


def test_no_upscale_never_lets_the_crop_fall_below_the_slot() -> None:
    result = check(resize_crop(FIT, Rect(500, 400, 1200, 800), SRC, "no_upscale"))
    assert result.crop.w >= FIT.rect.w and result.crop.h >= FIT.rect.h
    assert scale(result) <= 1.0


def test_native_crop_edit_keeps_scale_exactly_one() -> None:
    result = check(resize_crop(NATIVE, Rect(100, 100, 1600, 1200), SRC, "native"))
    assert (result.rect.w, result.rect.h) == (1600, 1200)
    assert scale(result) == 1.0


def test_changing_the_crop_aspect_moves_the_slot_at_the_same_scale() -> None:
    before = scale(SlotPlacement(FIT.rect, FIT.crop, "free"))
    result = check(resize_crop(FIT, Rect(0, 0, 4000, 4000), SRC, "free"))
    assert result.rect.w != FIT.rect.w or result.rect.h != FIT.rect.h
    assert scale(result) == pytest.approx(before, rel=1e-3)


def test_crops_are_clamped_into_the_source() -> None:
    result = check(resize_crop(FIT, Rect(5500, 3800, 3000, 2000), SRC, "free"))
    assert result.crop.x + result.crop.w <= SRC.w
    assert result.crop.y + result.crop.h <= SRC.h
    assert pan_crop(FIT, -9000, 9000, SRC) == Rect(0, 0, 6000, 4000)


def test_zoom_respects_the_lock() -> None:
    zoomed = SlotState(Rect(645, 200, 2550, 1700), Rect(2000, 1000, 3000, 2000))
    out = check(zoom_crop(zoomed, 1.25, SRC, "free"))
    assert out.crop.w > zoomed.crop.w
    blocked = check(zoom_crop(FIT, 0.25, SRC, "no_upscale"))
    assert scale(blocked) <= 1.0


# ---- lock and ratio switches --------------------------------------------------------------------
def test_switching_to_native_keeps_the_framing_at_scale_one() -> None:
    result = check(apply_lock(FIT, "native", SRC))
    assert (result.crop.w, result.crop.h) == (FIT.rect.w, FIT.rect.h)
    assert scale(result) == 1.0


def test_switching_to_no_upscale_shrinks_an_enlarged_slot() -> None:
    result = check(apply_lock(UPSCALED, "no_upscale", SMALL), SMALL)
    assert (result.rect.w, result.rect.h) == (UPSCALED.crop.w, UPSCALED.crop.h)
    assert scale(result) == 1.0


def test_free_lock_changes_nothing() -> None:
    result = apply_lock(UPSCALED, "free", SMALL)
    assert (result.rect, result.crop) == (UPSCALED.rect, UPSCALED.crop)


def test_crop_ratio_recrops_around_the_centre() -> None:
    square = check(apply_crop_ratio(FIT, 1.0, SRC, "no_upscale"))
    assert square.crop.w == square.crop.h
    assert apply_crop_ratio(FIT, None, SRC, "no_upscale").crop == FIT.crop


# ---- alternatives -------------------------------------------------------------------------------
def test_no_alternatives_when_the_slot_is_not_upscaled() -> None:
    assert alternatives(FIT, SRC, "no_upscale", "fit_in_mat", Margins(200, 200, 260, 200)) == []


def test_alternatives_are_all_applicable() -> None:
    options = alternatives(UPSCALED, SRC, "no_upscale", "manual", Margins(0, 0, 0, 0))
    assert [o.id for o in options] == ["keep_framing", "show_more", "shrink"]
    for option in options:
        check(SlotPlacement(option.rect, option.crop, option.quality_lock))
    show_more = next(o for o in options if o.id == "show_more")
    assert (show_more.crop.w, show_more.crop.h) == (UPSCALED.rect.w, UPSCALED.rect.h)
    shrink = next(o for o in options if o.id == "shrink")
    assert (shrink.rect.w, shrink.rect.h) == (UPSCALED.crop.w, UPSCALED.crop.h)


def test_show_more_is_dropped_when_the_source_is_too_small() -> None:
    options = alternatives(UPSCALED, SMALL, "free", "manual", Margins(0, 0, 0, 0))
    assert [o.id for o in options] == ["keep_framing", "shrink"]


def test_fit_in_mat_shrink_grows_the_margins() -> None:
    margins = Margins(200, 200, 260, 200)
    state = SlotState(Rect(858, 200, 2125, 1700), Rect(0, 0, 1000, 800))
    shrink = next(
        o for o in alternatives(state, SMALL, "free", "fit_in_mat", margins) if o.id == "shrink"
    )
    assert shrink.margins is not None
    assert shrink.margins.left > margins.left and shrink.margins.top > margins.top
    assert (shrink.rect.w, shrink.rect.h) == (1000, 800)


def test_fill_offers_leaving_fill() -> None:
    state = SlotState(Rect(0, 0, 3840, 2160), Rect(0, 119, 1000, 562))
    options = alternatives(state, SMALL, "free", "fill", Margins(200, 200, 260, 200))
    switch = next(o for o in options if o.id == "fit_in_mat")
    assert switch.placement == "fit_in_mat"
    assert switch.rect.w <= 1000 and switch.rect.h <= 562


def test_native_margins_are_reversible() -> None:
    """Growing then shrinking the margins under `native` gives the photo back (§7.4).

    The crop used to be re-derived only when it *overflowed* the available area, so the detour
    through wide margins left a small photo in a big mat for good.
    """
    source = Size(3072, 4080)
    wide = Margins(top=280, right=1333, bottom=320, left=1332)
    narrow = Margins(top=700, right=1333, bottom=320, left=1332)
    start = fit_in_mat(source, Rect(0, 0, source.w, source.h), "original", wide, "native")
    assert (start.crop.w, start.crop.h) == (start.rect.w, start.rect.h) == (1175, 1560)

    shrunk = fit_in_mat(source, start.crop, "original", narrow, "native")
    assert (shrunk.crop.w, shrunk.crop.h) == (858, 1140)  # 2160 − 700 − 320 = 1140 tall

    back = fit_in_mat(source, shrunk.crop, "original", wide, "native")
    assert back.crop == start.crop and back.rect == start.rect


def test_mirrored_margins_keep_both_sides_equal() -> None:
    """Native linking splits a mirrored axis evenly instead of by the previous proportions."""
    previous = Margins(top=100, right=500, bottom=300, left=100)
    mirrored = margins_for_slot(Size(3000, 1500), previous, False, mirror_x=True, mirror_y=True)
    assert mirrored.left == mirrored.right == 420  # (3840 − 3000) // 2
    assert mirrored.top == mirrored.bottom == 330  # (2160 − 1500) // 2

    one_axis = margins_for_slot(Size(3000, 1500), previous, False, mirror_x=True)
    assert one_axis.left == one_axis.right == 420
    assert (one_axis.top, one_axis.bottom) == (165, 495)  # 660 shared 100 : 300
