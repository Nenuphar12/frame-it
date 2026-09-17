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
from the_frame_v2.domain.geometry import Rect, Size
from the_frame_v2.domain.templates import (
    FrameStyleDocument,
    LayoutDocument,
    PhotoInput,
    build_document,
    map_rect_to_area,
)
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


def test_build_single_fit_in_mat_by_hand() -> None:
    style = FrameStyleDocument.model_validate(
        {
            "margins": {"top": 200, "right": 200, "bottom": 260, "left": 200},
            "slot_defaults": {"bands": [{"width": 12, "color": "#FFFFFF"}]},
        }
    )
    layout = LayoutDocument.model_validate(
        {"slots": [{"id": "s1", "rect": {"x": 0, "y": 0, "w": 3840, "h": 2160}}]}
    )
    built = build_document(style, layout, [PhotoInput("p1", Size(6000, 4000))])
    s = built.slots[0]
    # area 3440×1700 at (200, 200); scale min(3440/6000, 1700/4000) = 0.425 → 2550×1700, x = 200 + 445
    assert (s.rect.x, s.rect.y, s.rect.w, s.rect.h) == (645, 200, 2550, 1700)
    assert s.bands[0].width == 12
    assert built.placement == "fit_in_mat"
    small = build_document(style, layout, [PhotoInput("p1", Size(1000, 800))], "fill")
    assert small.slots[0].quality_lock == "free"  # no_upscale cannot be honoured when filling
    assert small.quality().worst_tier == "upscaled"


def test_build_multi_slot_maps_into_margins_and_leaves_empty_slots() -> None:
    style = FrameStyleDocument.model_validate(
        {"margins": {"top": 216, "right": 384, "bottom": 216, "left": 384}}
    )
    layout = LayoutDocument.model_validate(
        {
            "slots": [
                {"id": "a", "rect": {"x": 0, "y": 0, "w": 1920, "h": 2160}},
                {"id": "b", "rect": {"x": 1920, "y": 0, "w": 1920, "h": 2160}, "rotation": 4},
            ]
        }
    )
    built = build_document(style, layout, [PhotoInput("p1", Size(3000, 4000))])
    assert built.placement == "manual"
    first, second = built.slots
    # area = 3072×1728 at (384, 216): each half is 1536 wide
    assert (first.rect.x, first.rect.y, first.rect.w, first.rect.h) == (384, 216, 1536, 1728)
    assert second.photo_id is None and second.rotation == 4
    assert built.quality().is_incomplete
    area = Rect(384, 216, 3072, 1728)
    assert map_rect_to_area(layout.slots[1].rect.geometry(), area) == Rect(1920, 216, 1536, 1728)


@pytest.mark.parametrize("name", ["frame_styles.json", "layouts.json"])
def test_builtin_presets_are_valid(name: str) -> None:
    data = json.loads((PRESETS_DIR / name).read_text())
    items = data["styles"] if "styles" in data else data["layouts"]
    model = FrameStyleDocument if "styles" in data else LayoutDocument
    ids = [item["id"] for item in items]
    assert len(set(ids)) == len(ids)
    for item in items:
        model.model_validate(item["document"])
