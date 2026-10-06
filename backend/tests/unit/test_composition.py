"""The composition solver (docs/simple-editor.md §3 to §4) — behaviour, not fixtures.

The shared Python/TypeScript values live in `conformance/geometry/composition.json`
(`test_conformance.py`); this file asserts the rules those values must obey.
"""

from __future__ import annotations

from typing import Any

import pytest

from the_frame_v2.domain.composition import (
    CAPTION_BAND_FACTOR,
    MIN_CELL,
    Cell,
    Recipe,
    apply,
    block_area,
    block_margins,
    caption_band,
    cell_format,
    format_ratio,
    leaves,
    refit_crop,
    roomy,
    solve,
    solve_strict,
    split_weights,
    splits,
)
from the_frame_v2.domain.document import ArtworkDocument, Caption, Composition, CropSpec
from the_frame_v2.domain.geometry import CANVAS, Rect, Size
from the_frame_v2.services import recipes

CAPTION_SIZE = 48
PHOTOS = [Size(6000, 4000), Size(3000, 4000), Size(4000, 4000), Size(5000, 2000)]


def composition(recipe: str, **kwargs: Any) -> Composition:
    defaults: dict[str, Any] = {"outer": {"x": 120, "y": 120}, "gutter": {"x": 80, "y": 80}}
    return Composition.model_validate({"recipe": recipe, **defaults, **kwargs})


def cells_of(recipe_id: str, **kwargs: Any) -> list[Cell]:
    recipe = recipes.find(recipe_id)
    assert recipe is not None
    sizes = [PHOTOS[i % len(PHOTOS)] for i in range(recipe.count)]
    return solve(recipe, composition(recipe_id, **kwargs), sizes, CAPTION_SIZE)


ALL_IDS = [r.id for r in recipes.all_recipes()]


# ---- the catalogue ------------------------------------------------------------------------------
def test_catalogue_is_valid_and_covers_one_to_six_photos() -> None:
    counts = {r.count for r in recipes.all_recipes()}
    assert counts == {1, 2, 3, 4, 5, 6}
    for recipe in recipes.all_recipes():
        assert len(leaves(recipe.tree)) == recipe.count
        assert recipe.name_key == f"recipes.{recipe.id}"


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 6])
def test_for_count_finds_a_fallback(count: int) -> None:
    recipe = recipes.for_count(count)
    assert recipe is not None and recipe.count == count


def test_a_recipe_tree_must_hold_its_declared_count() -> None:
    with pytest.raises(ValueError, match="does not hold 3 cells"):
        Recipe.model_validate(
            {"id": "bad", "count": 3, "name_key": "recipes.bad", "tree": {"cell": "auto"}}
        )


def test_balance_needs_a_two_child_root() -> None:
    with pytest.raises(ValueError, match="2-child root split"):
        Recipe.model_validate(
            {
                "id": "bad",
                "count": 1,
                "name_key": "recipes.bad",
                "balance": {"min": 0.3, "max": 0.7, "default": 0.5},
                "tree": {"cell": "auto"},
            }
        )


# ---- fill format (§3.4) -------------------------------------------------------------------------
@pytest.mark.parametrize("recipe_id", ALL_IDS)
def test_fill_cells_tile_the_area_with_exact_gutters(recipe_id: str) -> None:
    """Every cell touches the block's edges or sits exactly one gutter from its neighbour."""
    cells = cells_of(recipe_id)
    area = block_area(composition(recipe_id), CAPTION_SIZE)
    assert min(c.rect.x for c in cells) == area.x
    assert min(c.rect.y for c in cells) == area.y
    assert max(c.rect.x + c.rect.w for c in cells) == area.x + area.w
    assert max(c.rect.y + c.rect.h for c in cells) == area.y + area.h
    _assert_gaps_are_gutters(cells, 80, 80)


def test_fill_gutters_stay_exact_at_an_awkward_size() -> None:
    cells = cells_of("three-row", gutter={"x": 37, "y": 37}, outer={"x": 111, "y": 111})
    _assert_gaps_are_gutters(cells, 37, 37)


def _assert_gaps_are_gutters(cells: list[Cell], gutter_x: int, gutter_y: int) -> None:
    for a in cells:
        for b in cells:
            if a is b:
                continue
            if a.rect.x + a.rect.w <= b.rect.x and _overlap_y(a.rect, b.rect):
                assert b.rect.x - (a.rect.x + a.rect.w) >= gutter_x
            if a.rect.y + a.rect.h <= b.rect.y and _overlap_x(a.rect, b.rect):
                assert b.rect.y - (a.rect.y + a.rect.h) >= gutter_y


def _overlap_x(a: Rect, b: Rect) -> bool:
    return a.x < b.x + b.w and b.x < a.x + a.w


def _overlap_y(a: Rect, b: Rect) -> bool:
    return a.y < b.y + b.h and b.y < a.y + a.h


def test_cells_never_overlap() -> None:
    for recipe_id in ALL_IDS:
        for fmt in ("fill", "3:2", "1:1"):
            cells = cells_of(recipe_id, format=fmt)
            for index, a in enumerate(cells):
                for b in cells[index + 1 :]:
                    assert not (_overlap_x(a.rect, b.rect) and _overlap_y(a.rect, b.rect))


# ---- ratio format (§3.5) ------------------------------------------------------------------------
@pytest.mark.parametrize("recipe_id", ALL_IDS)
@pytest.mark.parametrize("fmt", ["3:2", "1:1", "16:9"])
def test_every_cell_hits_the_target_aspect_within_a_pixel(recipe_id: str, fmt: str) -> None:
    ratio = format_ratio(fmt)
    assert ratio is not None
    for cell in cells_of(recipe_id, format=fmt):
        # Every cell takes the format as written; only `auto` (single) and `square` differ.
        best = min((ratio, 1 / ratio, 1.0), key=lambda a: abs(cell.rect.w - a * cell.rect.h))
        # Both edges of each side are rounded, so w and h are each within 1 px of the ideal
        # rect: |w − a·h| ≤ 1 + a. Anything larger means the affine relations are wrong.
        assert abs(cell.rect.w - best * cell.rect.h) <= 1 + best


@pytest.mark.parametrize("recipe_id", ALL_IDS)
def test_the_block_is_centred_in_the_available_area(recipe_id: str) -> None:
    """Under a ratio, `outer` is a minimum and the slack is shared equally (§3.5)."""
    cells = cells_of(recipe_id, format="3:2")
    area = block_area(composition(recipe_id, format="3:2"), CAPTION_SIZE)
    before_x = min(c.rect.x for c in cells) - area.x
    after_x = area.x + area.w - max(c.rect.x + c.rect.w for c in cells)
    before_y = min(c.rect.y for c in cells) - area.y
    after_y = area.y + area.h - max(c.rect.y + c.rect.h for c in cells)
    assert before_x >= 0 and before_y >= 0
    assert abs(before_x - after_x) <= 1
    assert abs(before_y - after_y) <= 1


def test_a_ratio_carries_its_orientation() -> None:
    """`4:3` and `3:4` are different formats (user feedback)."""
    assert format_ratio("3:2") == 1.5
    assert format_ratio("2:3") == pytest.approx(2 / 3)
    assert format_ratio("fill") is None and format_ratio("original") is None
    landscape = cells_of("three-row", format="3:2")
    portrait = cells_of("three-row", format="2:3")
    assert landscape != portrait
    assert all(cell.rect.w > cell.rect.h for cell in landscape)
    assert all(cell.rect.h > cell.rect.w for cell in portrait)


def test_original_follows_the_photo_and_only_a_single_cell_may_use_it() -> None:
    cell = solve(_recipe("single"), composition("single", format="original"), [Size(4000, 3000)])[0]
    assert (cell.rect.w, cell.rect.h) == (2560, 1920)
    assert cell.ratio_label == "4:3"


def test_an_auto_cell_turns_the_format_the_photo_s_way() -> None:
    """Otherwise picking 1:1 or 3:2 for a single photo would do nothing at all (§3.3)."""
    landscape = solve(_recipe("single"), composition("single", format="3:2"), [Size(6000, 4000)])
    portrait = solve(_recipe("single"), composition("single", format="3:2"), [Size(4000, 6000)])
    assert landscape[0].rect.w > landscape[0].rect.h
    assert portrait[0].rect.h > portrait[0].rect.w
    assert abs(landscape[0].rect.w / landscape[0].rect.h - 1.5) < 0.01
    assert abs(portrait[0].rect.h / portrait[0].rect.w - 1.5) < 0.01


def _recipe(recipe_id: str) -> Recipe:
    recipe = recipes.find(recipe_id)
    assert recipe is not None
    return recipe


# ---- balance (§4.3) -----------------------------------------------------------------------------
def test_balance_moves_the_root_split_monotonically() -> None:
    widths = [
        cells_of("three-hero-left", balance=balance)[0].rect.w
        for balance in (0.40, 0.50, 0.62, 0.75)
    ]
    assert widths == sorted(widths)
    assert widths[0] < widths[-1]


def test_balance_is_the_share_of_the_first_child() -> None:
    cells = cells_of("two-hero-left", balance=0.4)
    free = cells[0].rect.w + cells[1].rect.w
    assert abs(cells[0].rect.w / free - 0.4) < 0.01


def test_balance_is_inert_under_a_ratio_format() -> None:
    assert cells_of("three-hero-left", format="3:2", balance=0.4) == cells_of(
        "three-hero-left", format="3:2", balance=0.75
    )


def test_an_absent_balance_uses_the_recipe_default() -> None:
    recipe = _recipe("three-hero-left")
    assert recipe.balance is not None
    assert cells_of("three-hero-left") == cells_of(
        "three-hero-left", balance=recipe.balance.default
    )


# ---- borders and captions (§3.2, §3.3) ----------------------------------------------------------
def test_a_border_shifts_the_footprint_not_the_aspect() -> None:
    """The aspect a format imposes is the photo's; the border grows around it (§3.2)."""
    plain = cells_of("four-grid", format="1:1")
    bordered = cells_of("four-grid", format="1:1", border={"width": 24, "color": "#FFFFFF"})
    for cell in bordered:
        assert abs(cell.rect.w - cell.rect.h) <= 1
    assert bordered[0].rect.w < plain[0].rect.w
    # The printed edge still starts at `outer`: the footprint's left edge is the plain one.
    assert bordered[0].rect.x - 24 == plain[0].rect.x


def test_a_border_keeps_the_gap_between_printed_edges() -> None:
    cells = cells_of("two-side-by-side", border={"width": 24, "color": "#FFFFFF"})
    printed_gap = (cells[1].rect.x - 24) - (cells[0].rect.x + cells[0].rect.w + 24)
    assert printed_gap == 80


def test_a_caption_reserves_a_band_on_its_side() -> None:
    band = caption_band(CAPTION_SIZE, 80)
    assert band == round(CAPTION_SIZE * CAPTION_BAND_FACTOR) + 80
    plain = block_area(composition("four-grid"), CAPTION_SIZE)
    below = block_area(composition("four-grid", caption={"place": "below"}), CAPTION_SIZE)
    above = block_area(composition("four-grid", caption={"place": "above"}), CAPTION_SIZE)
    assert below.y == plain.y and below.h == plain.h - band
    assert above.y == plain.y + band and above.h == plain.h - band


# ---- totality (§3.6) ----------------------------------------------------------------------------
def test_the_solver_relaxes_instead_of_producing_slivers() -> None:
    cells = cells_of(
        "six-grid-3x2",
        border={"width": 200, "color": "#FFFFFF"},
        outer={"x": 800, "y": 450},
        gutter={"x": 400, "y": 400},
    )
    assert len(cells) == 6
    assert all(c.rect.w >= MIN_CELL and c.rect.h >= MIN_CELL for c in cells)


@pytest.mark.parametrize("recipe_id", ALL_IDS)
@pytest.mark.parametrize("fmt", ["fill", "3:2"])
def test_the_solver_is_total_at_every_extreme(recipe_id: str, fmt: str) -> None:
    for outer in ({"x": 0, "y": 0}, {"x": 800, "y": 450}):
        for gutter in ({"x": 0, "y": 0}, {"x": 400, "y": 400}):
            for border in (None, {"width": 200, "color": "#FFFFFF"}):
                cells = cells_of(recipe_id, format=fmt, outer=outer, gutter=gutter, border=border)
                recipe = _recipe(recipe_id)
                assert len(cells) == recipe.count
                assert all(c.rect.w >= 1 and c.rect.h >= 1 for c in cells)


def test_cells_stay_on_the_canvas() -> None:
    for recipe_id in ALL_IDS:
        for fmt in ("fill", "3:2"):
            for cell in cells_of(recipe_id, format=fmt):
                assert cell.rect.x >= 0 and cell.rect.x + cell.rect.w <= CANVAS.w
                assert cell.rect.y >= 0 and cell.rect.y + cell.rect.h <= CANVAS.h


# ---- writing back (§3.7, §4.1) ------------------------------------------------------------------
def test_block_margins_are_the_footprint_insets() -> None:
    cells = cells_of("three-hero-left", format="3:2")
    margins = block_margins(cells, 0)
    assert margins.left == min(c.rect.x for c in cells)
    assert margins.top == min(c.rect.y for c in cells)
    assert margins.right == CANVAS.w - max(c.rect.x + c.rect.w for c in cells)
    assert margins.bottom == CANVAS.h - max(c.rect.y + c.rect.h for c in cells)


def test_block_margins_include_the_border() -> None:
    cells = cells_of("four-grid", border={"width": 24, "color": "#FFFFFF"})
    assert block_margins(cells, 24).left == 120


def test_refit_keeps_the_crop_centre_and_zoom() -> None:
    previous = Rect(2000, 1000, 3000, 2000)
    refitted = refit_crop(previous, Size(6000, 4000), 1.0)
    assert (refitted.w, refitted.h) == (3000, 3000)
    assert refitted.x + refitted.w / 2 == previous.x + previous.w / 2
    assert refitted.y + refitted.h / 2 == previous.y + previous.h / 2


def test_refit_without_a_previous_crop_is_the_centred_cover() -> None:
    assert refit_crop(None, Size(6000, 4000), 1.5) == Rect(0, 0, 6000, 4000)
    assert refit_crop(None, Size(6000, 4000), 1.0) == Rect(1000, 0, 4000, 4000)


def test_refit_stays_inside_the_source() -> None:
    for ratio in (None, 1.0, 1.5, 0.5):
        crop = refit_crop(Rect(5800, 3900, 200, 100), Size(6000, 4000), ratio)
        assert crop.x >= 0 and crop.y >= 0
        assert crop.x + crop.w <= 6000 and crop.y + crop.h <= 4000


def test_a_cell_ratio_label_matches_its_rect() -> None:
    for cell in cells_of("three-hero-left", format="3:2"):
        width, height = (int(term) for term in cell.ratio_label.split(":"))
        assert cell.rect.w * height == cell.rect.h * width


# ---- the document block (§2) --------------------------------------------------------------------
def _document(**composition_fields: Any) -> dict[str, Any]:
    return {
        "schema": 1,
        "placement": "manual",
        "composition": {
            "recipe": "two-side-by-side",
            "outer": {"x": 120, "y": 120},
            "gutter": {"x": 80, "y": 80},
            **composition_fields,
        },
        "slots": [],
    }


def test_a_document_without_a_composition_stays_valid() -> None:
    doc = ArtworkDocument.model_validate({"schema": 1, "placement": "manual", "slots": []})
    assert doc.composition is None
    assert doc.canonical()["composition"] is None


def test_format_terms_are_bounded() -> None:
    ArtworkDocument.model_validate(_document(format="1000:1000"))
    with pytest.raises(ValueError, match="format terms"):
        ArtworkDocument.model_validate(_document(format="1001:2"))
    with pytest.raises(ValueError, match="String should match"):
        ArtworkDocument.model_validate(_document(format="free"))


def test_original_is_a_format_like_any_other() -> None:
    """Every cell takes its own photo's aspect — the solver has no trouble with several."""
    ArtworkDocument.model_validate(_document(format="original"))
    for recipe_id in ("three-hero-left", "four-grid"):
        cells = cells_of(recipe_id, format="original")
        wanted = [PHOTOS[i % len(PHOTOS)] for i in range(len(cells))]
        for cell, photo in zip(cells, wanted, strict=True):
            aspect = photo.w / photo.h
            # Two rounded edges per side: §3.4's tolerance, not a single pixel.
            assert abs(cell.rect.w - aspect * cell.rect.h) <= 1 + aspect


def test_the_sliders_are_bounded() -> None:
    for field, value in (("outer", {"x": 801, "y": 0}), ("gutter", {"x": 0, "y": 401})):
        with pytest.raises(ValueError, match="less than or equal"):
            ArtworkDocument.model_validate(_document(**{field: value}))


# ---- the write-back (§3.7, §4.1) ------------------------------------------------------------------
def _slot(index: int, photo_id: str | None, crop: Rect, rect: Rect | None = None) -> dict[str, Any]:
    box = rect or Rect(0, 0, max(1, crop.w // 3), max(1, crop.h // 3))
    return {
        "id": f"c{index + 1}",
        "photo_id": photo_id,
        "rect": {"x": box.x, "y": box.y, "w": box.w, "h": box.h},
        "rotation": 15,
        "source": {
            "orient": {"rotate": 0, "flip_h": False},
            "crop": {"x": crop.x, "y": crop.y, "w": crop.w, "h": crop.h},
            "crop_ratio": "free",
        },
        "quality_lock": "free",
        "bands": [],
        "shadow": {
            "type": "drop",
            "offset_x": 8,
            "offset_y": 8,
            "blur": 20,
            "color": "#000000",
            "opacity": 0.4,
        },
    }


def _artwork(recipe_id: str, photos: list[Size | None], **fields: Any) -> ArtworkDocument:
    """A document whose slots are deliberately elsewhere: only the block should decide."""
    slots = [
        _slot(
            index,
            None if size is None else f"p{index}",
            Rect(0, 0, size.w, size.h) if size else Rect(0, 0, 1200, 800),
        )
        for index, size in enumerate(photos)
    ]
    return ArtworkDocument.model_validate(
        {
            "schema": 1,
            "placement": "fit_in_mat" if len(slots) == 1 else "manual",
            "composition": {
                "recipe": recipe_id,
                "outer": {"x": 120, "y": 120},
                "gutter": {"x": 80, "y": 80},
                **fields,
            },
            "slots": slots,
        }
    )


def _sizes(photos: list[Size | None]) -> dict[str, Size]:
    return {f"p{i}": size for i, size in enumerate(photos) if size is not None}


def _applied(recipe_id: str, photos: list[Size | None], **fields: Any) -> ArtworkDocument:
    recipe = _recipe(recipe_id)
    return apply(_artwork(recipe_id, photos, **fields), recipe, _sizes(photos))


@pytest.mark.parametrize("recipe_id", ALL_IDS)
@pytest.mark.parametrize("fmt", ["fill", "3:2", "1:1"])
def test_apply_writes_the_cells_into_the_slots(recipe_id: str, fmt: str) -> None:
    recipe = _recipe(recipe_id)
    if fmt != "fill" and recipe.count == 1:
        pytest.skip("covered by the single-cell cases")
    photos: list[Size | None] = [PHOTOS[i % len(PHOTOS)] for i in range(recipe.count)]
    doc = _applied(recipe_id, photos, format=fmt)
    cells = solve(recipe, doc.composition or composition(recipe_id), photos, CAPTION_SIZE)
    assert [s.rect.geometry() for s in doc.slots] == [c.rect for c in cells]
    assert [s.source.crop_ratio for s in doc.slots] == [c.ratio_label for c in cells]
    assert all(s.rotation == 0 for s in doc.slots)  # rotation stays an Advanced tool
    assert doc.placement == "manual"


@pytest.mark.parametrize("recipe_id", ALL_IDS)
@pytest.mark.parametrize("fmt", ["fill", "3:2", "2:3", "1:1"])
def test_an_applied_document_is_one_the_server_accepts(recipe_id: str, fmt: str) -> None:
    """Invariant 11: every slot stays aspect-consistent and honours its own quality lock."""
    recipe = _recipe(recipe_id)
    if fmt != "fill" and recipe.count == 1:
        pytest.skip("covered by the single-cell cases")
    photos: list[Size | None] = [PHOTOS[i % len(PHOTOS)] for i in range(recipe.count)]
    doc = _applied(recipe_id, photos, format=fmt, border={"width": 24, "color": "#FFFFFF"})
    # re-validating the canonical form is exactly what the API does on the way in
    ArtworkDocument.model_validate(doc.canonical())


def test_apply_keeps_the_framing_and_the_photo_of_each_slot() -> None:
    photos: list[Size | None] = [Size(6000, 4000), Size(6000, 4000)]
    doc = _artwork("two-side-by-side", photos)
    doc.slots[0].source.crop = CropSpec(x=1000, y=500, w=1200, h=800)
    doc.slots[0].quality_lock = "free"
    applied = apply(doc, _recipe("two-side-by-side"), _sizes(photos))
    crop = applied.slots[0].source.crop
    # same centre, same zoom: the reframe survives a margin drag (§4.1). The centre can land
    # half a pixel off when the new height is odd — the crop is integer, the centre is not.
    assert abs(crop.x + crop.w / 2 - 1600) <= 0.5 and abs(crop.y + crop.h / 2 - 900) <= 0.5
    assert crop.w == 1200
    assert applied.slots[0].photo_id == "p0"
    assert applied.slots[0].shadow is not None  # decorations are not the block's business


def test_apply_downgrades_a_lock_the_photo_cannot_honour() -> None:
    photos: list[Size | None] = [Size(400, 300)]
    doc = _applied("single", photos, format="fill")
    assert doc.slots[0].rect.w > doc.slots[0].source.crop.w
    assert doc.slots[0].quality_lock == "free"
    big = _applied("single", [Size(6000, 4000)], format="fill")
    assert big.slots[0].quality_lock == "no_upscale"


def test_apply_leaves_an_empty_slot_a_placeholder() -> None:
    photos: list[Size | None] = [Size(6000, 4000), None]
    doc = _applied("two-side-by-side", photos)
    empty = doc.slots[1]
    assert empty.photo_id is None and empty.quality_lock == "free"
    assert empty.source.crop.geometry() == Rect(0, 0, empty.rect.w, empty.rect.h)
    assert empty.source.crop_ratio == "free"


def test_apply_writes_the_border_as_a_band_and_the_block_margins() -> None:
    photos: list[Size | None] = [Size(6000, 4000), Size(6000, 4000)]
    doc = _applied("two-side-by-side", photos, border={"width": 24, "color": "#101010"})
    assert all(s.bands[0].width == 24 and s.bands[0].color == "#101010" for s in doc.slots)
    assert doc.margins.left == 120 and doc.margins.top == 120  # footprint insets, not photo rects
    assert doc.margins.linked is False


def test_apply_derives_one_caption_and_places_it_in_the_band() -> None:
    photos: list[Size | None] = [Size(6000, 4000), Size(6000, 4000)]
    doc = _applied("two-side-by-side", photos, caption={"text": "Kyoto", "place": "below"})
    caption = doc.captions[0]
    assert caption.text == "Kyoto" and caption.anchor == "middle" and caption.x == 1920
    bottom = max(s.rect.y + s.rect.h for s in doc.slots)
    assert bottom < caption.y < CANVAS.h - 120 + CAPTION_SIZE
    above = _applied("two-side-by-side", photos, caption={"text": "Kyoto", "place": "above"})
    assert above.captions[0].y < min(s.rect.y for s in above.slots)


def test_apply_drops_the_caption_when_it_is_off_or_empty() -> None:
    photos: list[Size | None] = [Size(6000, 4000), Size(6000, 4000)]
    assert _applied("two-side-by-side", photos).captions == []
    empty = _applied("two-side-by-side", photos, caption={"text": " ", "place": "below"})
    assert empty.captions == []


def test_apply_keeps_the_caption_typography_of_the_document() -> None:
    photos: list[Size | None] = [Size(6000, 4000), Size(6000, 4000)]
    doc = _artwork("two-side-by-side", photos, caption={"text": "Kyoto", "place": "below"})
    doc.captions = [Caption(id="legacy", text="old", font="inter", weight=700, size=96, x=0, y=0)]
    applied = apply(doc, _recipe("two-side-by-side"), _sizes(photos))
    caption = applied.captions[0]
    assert (caption.id, caption.font, caption.weight, caption.size) == ("legacy", "inter", 700, 96)
    assert caption.text == "Kyoto"  # the block owns the text, the document owns the typography


def test_apply_returns_a_detached_or_composition_less_document_unchanged() -> None:
    photos: list[Size | None] = [Size(6000, 4000), Size(6000, 4000)]
    doc = _artwork("two-side-by-side", photos, detached=True)
    assert apply(doc, _recipe("two-side-by-side"), _sizes(photos)) is doc
    plain = ArtworkDocument.model_validate({"schema": 1, "placement": "manual", "slots": []})
    assert apply(plain, _recipe("single"), {}) is plain


# ---- the panel's slider bounds (§3.6, §6.2) -------------------------------------------------------
def test_solve_strict_does_not_relax() -> None:
    """What the panel bisects on: `solve` would hide an over-constrained value behind the ladder."""
    recipe = _recipe("six-grid-3x2")
    over = composition(
        "six-grid-3x2",
        border={"width": 200, "color": "#FFFFFF"},
        outer={"x": 800, "y": 450},
        gutter={"x": 400, "y": 400},
    )
    photos = [PHOTOS[i % len(PHOTOS)] for i in range(6)]
    strict = solve_strict(recipe, over, photos, CAPTION_SIZE)
    assert not roomy(strict)  # the honest answer: these parameters leave slivers
    assert roomy(solve(recipe, over, photos, CAPTION_SIZE))  # the ladder rescued the layout
    assert min(cell.rect.w for cell in strict) < min(
        cell.rect.w for cell in solve(recipe, over, photos, CAPTION_SIZE)
    )


def test_solve_strict_matches_solve_when_there_is_room() -> None:
    recipe = _recipe("three-hero-left")
    block = composition("three-hero-left")
    photos = PHOTOS[:3]
    assert solve_strict(recipe, block, photos, CAPTION_SIZE) == solve(
        recipe, block, photos, CAPTION_SIZE
    )


def test_roomy_is_the_min_cell_rule() -> None:
    cell = Cell("c1", Rect(0, 0, MIN_CELL, MIN_CELL), "1:1")
    assert roomy([cell])
    assert not roomy([Cell("c1", Rect(0, 0, MIN_CELL - 1, MIN_CELL), "1:1")])


# ---- per-cell formats (§3.5, user feedback) ---------------------------------------
def test_a_cell_format_overrides_the_block_s() -> None:
    cells = cells_of("three-one-over-two", format="3:2", cell_formats=[None, "1:1", "1:1"])
    assert abs(cells[0].rect.w / cells[0].rect.h - 1.5) < 0.01
    assert all(abs(c.rect.w / c.rect.h - 1.0) < 0.01 for c in cells[1:])


def test_a_cell_format_may_be_the_photo_s_own_aspect() -> None:
    """`original` per cell is how one photo keeps its shape while the others take the format."""
    cells = cells_of("two-side-by-side", format="3:2", cell_formats=[None, "original"])
    assert abs(cells[0].rect.w / cells[0].rect.h - 1.5) < 0.01
    # PHOTOS[1] is 3000×4000, so the second cell comes out portrait
    assert abs(cells[1].rect.w / cells[1].rect.h - 3 / 4) < 0.01


def test_cell_formats_are_inert_under_fill() -> None:
    """`fill` tiles the area exactly: a per-cell aspect has nowhere to go (§3.4)."""
    assert cells_of("two-side-by-side", cell_formats=["1:1", "16:9"]) == cells_of(
        "two-side-by-side"
    )
    assert composition_format("two-side-by-side", 0, fill=True) == "fill"


def composition_format(recipe: str, index: int, *, fill: bool) -> str:
    block = composition(recipe, format="fill" if fill else "3:2", cell_formats=["1:1"])
    return cell_format(block, index)


def test_a_cell_format_list_longer_than_the_slots_is_rejected() -> None:
    with pytest.raises(ValueError, match="more cell formats than slots"):
        ArtworkDocument.model_validate(_document(cell_formats=["1:1", "1:1"]))


def test_fill_is_not_a_cell_format() -> None:
    """`fill` is a property of the whole block, never of one cell."""
    with pytest.raises(ValueError, match="String should match"):
        ArtworkDocument.model_validate(_document(cell_formats=["fill"]))


# ---- per-split weights (§3.4) -------------------------------------------------------------------
def test_splits_are_listed_depth_first() -> None:
    """The index a `weights` entry is read by: the root, then each child's own splits in order."""
    assert [len(s.children) for s in splits(_recipe("four-hero-left").tree)] == [2, 3]
    assert [s.split for s in splits(_recipe("four-grid").tree)] == ["col", "row", "row"]
    assert splits(_recipe("single").tree) == []


def test_a_nested_weight_moves_only_its_own_division() -> None:
    plain = cells_of("three-hero-left")
    weighted = cells_of("three-hero-left", weights=[None, [3, 1]])
    assert weighted[0].rect == plain[0].rect  # the hero does not move
    assert weighted[1].rect.h == 1380 and weighted[2].rect.h == 460
    assert weighted[2].rect.y - (weighted[1].rect.y + weighted[1].rect.h) == 80
    assert weighted[2].rect.y + weighted[2].rect.h == plain[2].rect.y + plain[2].rect.h


@pytest.mark.parametrize("recipe_id", ALL_IDS)
def test_weighted_cells_still_tile_the_area(recipe_id: str) -> None:
    recipe = _recipe(recipe_id)
    weights = [
        [1 + index + child for child in range(len(node.children))]
        for index, node in enumerate(splits(recipe.tree))
    ]
    cells = cells_of(recipe_id, weights=weights)
    area = block_area(composition(recipe_id), CAPTION_SIZE)
    assert min(c.rect.x for c in cells) == area.x
    assert max(c.rect.x + c.rect.w for c in cells) == area.x + area.w
    assert min(c.rect.y for c in cells) == area.y
    assert max(c.rect.y + c.rect.h for c in cells) == area.y + area.h
    _assert_gaps_are_gutters(cells, 80, 80)


def test_balance_stays_the_root_of_a_recipe_that_declares_one() -> None:
    """One name per division: where there is a Balance, a root entry of `weights` is not read."""
    recipe = _recipe("three-hero-left")
    block = composition("three-hero-left", balance=0.5, weights=[[1, 9], [1, 2]])
    assert split_weights(recipe, block) == [[0.5, 0.5], [1, 2]]
    assert cells_of("three-hero-left", balance=0.5, weights=[[1, 9]]) == cells_of(
        "three-hero-left", balance=0.5
    )


def test_a_root_weight_drives_a_recipe_without_a_balance() -> None:
    cells = cells_of("two-side-by-side", weights=[[1, 3]])
    assert cells[0].rect.w == 880 and cells[1].rect.w == 2640


def test_an_entry_of_the_wrong_shape_is_ignored_by_the_solver() -> None:
    """Total, like the rest of it (§3.6): the reference check is what reports the mismatch."""
    assert cells_of("two-side-by-side", weights=[[1, 2, 3]]) == cells_of("two-side-by-side")
    assert cells_of("two-stacked", weights=[None, [1, 5]]) == cells_of("two-stacked")


def test_weights_are_inert_under_a_ratio() -> None:
    assert cells_of("four-grid", format="3:2", weights=[[5, 1], [1, 5]]) == cells_of(
        "four-grid", format="3:2"
    )


def test_weights_are_bounded_like_a_recipe_s() -> None:
    for bad in ([[1]], [[0, 1]], [[1, -1]], [[1] * 9], [[1, 1001]]):
        with pytest.raises(ValueError, match="weights"):
            composition("two-side-by-side", weights=bad)


# ---- caption alignment (§3.7) -------------------------------------------------------------------
def _captioned(recipe_id: str, align: str, **fields: Any) -> ArtworkDocument:
    caption = {"text": "Kyoto", "place": "below", "align": align}
    return _applied(recipe_id, [Size(6000, 4000), Size(3000, 4000)], caption=caption, **fields)


def test_a_caption_is_centred_unless_asked_otherwise() -> None:
    caption = _captioned("two-stacked", "center", format="3:2").captions[0]
    assert (caption.x, caption.anchor) == (CANVAS.w // 2, "middle")


def test_a_caption_lines_up_with_the_block_s_printed_edge() -> None:
    """The edge is the block's, border included — not `outer`, which is only a minimum (§3.5)."""
    border = {"width": 24, "color": "#FFFFFF"}
    left = _captioned("two-stacked", "left", format="3:2", border=border)
    right = _captioned("two-stacked", "right", format="3:2", border=border)
    first = left.slots[0].rect
    assert left.margins.left > 120  # the block is narrower than the area: there is slack
    assert (left.captions[0].x, left.captions[0].anchor) == (first.x - 24, "start")
    assert (right.captions[0].x, right.captions[0].anchor) == (first.x + first.w + 24, "end")
    assert left.captions[0].y == right.captions[0].y
