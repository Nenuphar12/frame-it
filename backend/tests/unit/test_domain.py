from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from the_frame_v2.domain.document import (
    ArtworkDocument,
    migrate,
    parse_document,
    validate_references,
)
from the_frame_v2.domain.geometry import Size
from the_frame_v2.domain.templates import (
    FrameStyleDocument,
    LayoutDocument,
    PhotoInput,
    build_composition_document,
    layout_of_document,
    relayout,
    restyle,
    style_of_document,
)
from the_frame_v2.services import recipes
from the_frame_v2.services.templates import PRESETS_DIR


def slot(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "s1",
        "photo_id": "p1",
        "rect": {"x": 645, "y": 200, "w": 2550, "h": 1700},
        "source": {"crop": {"x": 0, "y": 0, "w": 6000, "h": 4000}},
    }
    base.update(overrides)
    return base


def doc(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"schema": 1, "slots": [slot()]}
    base.update(overrides)
    return base


def errors(raw: dict[str, Any]) -> list[tuple[tuple[Any, ...], str]]:
    with pytest.raises(ValidationError) as info:
        ArtworkDocument.model_validate(raw)
    return [(tuple(e["loc"]), e["msg"]) for e in info.value.errors()]


def test_round_trip_is_stable() -> None:
    parsed = parse_document(
        doc(
            captions=[
                {"id": "c1", "text": "Kyoto", "font": "inter", "size": 48, "x": 1920, "y": 2040}
            ]
        )
    )
    dumped = parsed.canonical()
    assert dumped["schema"] == 1
    assert "schema_version" not in dumped
    again = ArtworkDocument.model_validate(json.loads(json.dumps(dumped)))
    assert again == parsed
    assert again.canonical() == dumped


@pytest.mark.parametrize(
    ("raw", "loc", "fragment"),
    [
        (doc(slots=[slot(rect={"x": 0, "y": 0, "w": 2000, "h": 1700})]), ("slots", 0), "aspect"),
        (
            doc(slots=[slot(rect={"x": 0, "y": 0, "w": 2550.5, "h": 1700})]),
            ("slots", 0, "rect", "w"),
            "integer",
        ),
        (doc(slots=[slot(quality_lock="native")]), ("slots", 0), "native lock"),
        (
            doc(slots=[slot(rect={"x": 0, "y": 0, "w": 7500, "h": 5000})]),
            ("slots", 0),
            "no_upscale",
        ),
        (
            doc(slots=[slot(bands=[{"width": 1, "color": "#fff"}])]),
            ("slots", 0, "bands", 0, "color"),
            "pattern",
        ),
        (
            doc(slots=[slot(bands=[{"width": 1, "color": "#FFFFFF"}] * 4)]),
            ("slots", 0, "bands"),
            "at most 3",
        ),
        (doc(slots=[slot(), slot()], placement="manual"), (), "unique"),
        (doc(slots=[slot(), slot(id="s2")]), (), "exactly one slot"),
        (doc(margins={"top": 1100, "bottom": 1100}), ("margins",), "no room"),
        (doc(canvas={"width": 1920, "height": 1080}), ("canvas", "width"), "3840"),
        (doc(extra=True), ("extra",), "Extra"),
        (
            doc(
                captions=[{"id": "c", "text": "a\nb", "font": "inter", "size": 20, "x": 0, "y": 0}]
            ),
            ("captions", 0),
            "single-line",
        ),
        (
            doc(
                slots=[
                    slot(
                        source={
                            "crop": {"x": 0, "y": 0, "w": 6000, "h": 4000},
                            "crop_ratio": "wide",
                        }
                    )
                ]
            ),
            ("slots", 0, "source", "crop_ratio"),
            "pattern",
        ),
        (
            doc(slots=[slot(shadow={"type": "inner", "blur": 500})]),
            ("slots", 0, "shadow", "blur"),
            "less than or equal",
        ),
    ],
)
def test_invalid_documents_have_precise_errors(
    raw: dict[str, Any], loc: tuple[Any, ...], fragment: str
) -> None:
    found = errors(raw)
    assert any(where == loc and fragment in msg for where, msg in found), found


def test_rotation_is_rounded_and_native_requires_exact_size() -> None:
    parsed = ArtworkDocument.model_validate(doc(placement="manual", slots=[slot(rotation=-7.04)]))
    assert parsed.slots[0].rotation == -7.0
    native = slot(
        rect={"x": 0, "y": 0, "w": 3840, "h": 2160},
        source={"crop": {"x": 5, "y": 5, "w": 3840, "h": 2160}},
        quality_lock="native",
    )
    assert ArtworkDocument.model_validate(doc(slots=[native])).quality().worst_tier == "native"


def test_references_are_checked_against_library() -> None:
    parsed = parse_document(
        doc(
            mat={"color": "#FFFFFF", "texture": {"id": "velvet", "strength": 0.5}},
            placement="manual",
            slots=[
                slot(),
                slot(id="s2", photo_id="gone"),
                slot(
                    id="s3",
                    source={
                        "orient": {"rotate": 90},
                        "crop": {"x": 0, "y": 0, "w": 6000, "h": 4000},
                    },
                ),
            ],
            captions=[
                {"id": "c1", "text": "x", "font": "comic", "size": 20, "x": 0, "y": 0},
                {
                    "id": "c2",
                    "text": "x",
                    "font": "inter",
                    "weight": 900,
                    "size": 20,
                    "x": 0,
                    "y": 0,
                },
            ],
        )
    )
    issues = validate_references(
        parsed,
        {"p1": Size(6000, 4000)},
        lambda font: frozenset({400, 500}) if font == "inter" else None,
        lambda texture: texture == "paper-01",
    )
    assert [(i.loc, i.type) for i in issues] == [
        (("mat", "texture", "id"), "unknown_texture"),
        (("slots", 1, "photo_id"), "unknown_photo"),
        (("slots", 2, "source", "crop"), "crop_out_of_bounds"),
        (("captions", 0, "font"), "unknown_font"),
        (("captions", 1, "weight"), "unknown_font_weight"),
    ]


def test_migrate_rejects_unknown_schema() -> None:
    assert migrate({"schema": 1})["schema"] == 1
    with pytest.raises(ValueError, match="unsupported"):
        migrate({"schema": 2})


STYLE = FrameStyleDocument.model_validate(
    {
        "mat": {"color": "#101010", "texture": None},
        "margins": {"top": 200, "right": 200, "bottom": 260, "left": 200},
        "slot_defaults": {
            "bands": [{"width": 12, "color": "#FFFFFF"}],
            "shadow": {"type": "drop", "blur": 20, "opacity": 0.3},
        },
        "caption_defaults": {"font": "inter", "weight": 400, "size": 60, "color": "#222222"},
    }
)
LAYOUT = LayoutDocument.model_validate(
    {
        "recipe": "two-side-by-side",
        "outer": {"x": 200, "y": 180},
        "gutter": {"x": 100, "y": 100},
        "format": "1:1",
        "caption_place": "below",
    }
)


def built(photos: list[PhotoInput | None], layout: LayoutDocument = LAYOUT) -> ArtworkDocument:
    recipe = recipes.find(layout.recipe)
    assert recipe is not None
    return build_composition_document(STYLE, recipe, layout.block(), photos)


def test_build_from_a_layout_is_the_solver_dressed_by_the_style() -> None:
    doc = built([PhotoInput("p1", Size(6000, 4000)), PhotoInput("p2", Size(3000, 4000))])
    first, second = doc.slots
    # two 1:1 footprints side by side, 100 px apart — the gap between the *printed* edges, so
    # the photo rects sit gutter + 2 × border apart (§3.2)
    assert first.rect.w == first.rect.h == second.rect.w == second.rect.h
    assert second.rect.x - (first.rect.x + first.rect.w) == 100 + 2 * 12
    assert first.rect.y == second.rect.y
    assert doc.placement == "manual"  # a composition is always manual (§3.7)
    assert doc.mat.color == "#101010"
    assert [slot.shadow.type for slot in doc.slots] == ["drop", "drop"]  # type: ignore[union-attr]
    assert doc.composition is not None and doc.composition.format == "1:1"
    # the style's band became the block's border: the solver owns the bands from then on (§3.2)
    assert doc.composition.border is not None and doc.composition.border.width == 12
    assert [band.width for band in first.bands] == [12]
    # margins are the insets of the footprint bbox, so they sit a border outside the photo rect
    assert doc.margins.top == first.rect.y - 12 and doc.margins.left == first.rect.x - 12


def test_build_leaves_an_empty_slot_a_placeholder() -> None:
    doc = built([PhotoInput("p1", Size(6000, 4000)), None])
    empty = doc.slots[1]
    assert empty.photo_id is None and empty.quality_lock == "free"
    assert (empty.source.crop.w, empty.source.crop.h) == (empty.rect.w, empty.rect.h)
    assert doc.quality().is_incomplete


def test_restyle_redresses_without_moving_a_photo() -> None:
    doc = built([PhotoInput("p1", Size(6000, 4000)), PhotoInput("p2", Size(3000, 4000))])
    rects = [(s.rect.x, s.rect.y, s.rect.w, s.rect.h) for s in doc.slots]
    plain = FrameStyleDocument.model_validate(
        {"mat": {"color": "#FFFFFF"}, "slot_defaults": {"bands": [], "shadow": None}}
    )
    recipe = recipes.find(LAYOUT.recipe)
    assert recipe is not None
    sizes = {"p1": Size(6000, 4000), "p2": Size(3000, 4000)}
    redressed = restyle(doc, plain, recipe, sizes)
    assert redressed.mat.color == "#FFFFFF"
    assert [s.shadow for s in redressed.slots] == [None, None]
    assert redressed.composition is not None and redressed.composition.border is None
    # dropping the border grows the photo rects into the freed space but keeps the layout
    assert [(s.rect.x, s.rect.y, s.rect.w, s.rect.h) for s in redressed.slots] != rects
    assert redressed.slots[0].rect.w == redressed.slots[0].rect.h
    assert redressed.margins.top == redressed.slots[0].rect.y  # no border left to inset


def test_relayout_keeps_the_photos_and_the_caption_text() -> None:
    doc = built([PhotoInput("p1", Size(6000, 4000)), PhotoInput("p2", Size(3000, 4000))])
    assert doc.composition is not None
    doc.composition.caption.text = "Kyoto"
    stacked = LayoutDocument.model_validate(
        {"recipe": "two-stacked", "outer": {"x": 300, "y": 120}, "gutter": {"x": 60, "y": 60}}
    )
    recipe = recipes.find("two-stacked")
    assert recipe is not None
    moved = relayout(doc, stacked, recipe, {"p1": Size(6000, 4000), "p2": Size(3000, 4000)})
    assert moved.composition is not None
    assert moved.composition.recipe == "two-stacked"
    assert moved.composition.caption.text == "Kyoto"  # the text is the artwork's, not the layout's
    assert moved.composition.caption.place == "none"  # the side is the layout's
    assert [s.photo_id for s in moved.slots] == ["p1", "p2"]
    top, bottom = moved.slots
    assert top.rect.x == bottom.rect.x and bottom.rect.y > top.rect.y


def test_save_as_style_and_layout_read_the_document_back() -> None:
    doc = built([PhotoInput("p1", Size(6000, 4000)), PhotoInput("p2", Size(3000, 4000))])
    assert doc.composition is not None
    doc.composition.border = doc.composition.border or None
    style = style_of_document(doc)
    assert style.mat.color == "#101010"
    assert style.slot_defaults.shadow is not None and style.slot_defaults.shadow.type == "drop"
    layout = layout_of_document(doc)
    assert layout is not None
    assert (layout.recipe, layout.format, layout.caption_place) == (
        "two-side-by-side",
        "1:1",
        "below",
    )
    assert layout.outer.x == 200 and layout.gutter.x == 100


def test_save_as_layout_needs_an_attached_composition() -> None:
    doc = built([PhotoInput("p1", Size(6000, 4000)), PhotoInput("p2", Size(3000, 4000))])
    assert doc.composition is not None
    doc.composition.detached = True
    assert layout_of_document(doc) is None


@pytest.mark.parametrize("name", ["frame_styles.json", "layouts.json"])
def test_builtin_presets_are_valid(name: str) -> None:
    data = json.loads((PRESETS_DIR / name).read_text())
    items = data["styles"] if "styles" in data else data["layouts"]
    model = FrameStyleDocument if "styles" in data else LayoutDocument
    ids = [item["id"] for item in items]
    assert len(set(ids)) == len(ids)
    for item in items:
        model.model_validate(item["document"])
