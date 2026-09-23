"""Geometry conformance fixtures shared with TypeScript (`conformance/geometry/*.json`, §13.3).

The fixtures are the contract: pytest checks the Python domain against them and `pnpm conformance`
checks `frontend/src/editor/core/`. `CONFORMANCE_UPDATE=1 uv run pytest tests/unit/test_conformance.py`
rewrites them from CASES (review the diff: expected values come from the Python implementation;
key values are also asserted by hand in test_domain.py).
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from the_frame_v2.domain import (
    alternatives,
    arrange,
    composition,
    constraints,
    geometry,
    placement,
    quality,
    templates,
)
from the_frame_v2.domain.composition import Cell
from the_frame_v2.domain.constraints import SlotState
from the_frame_v2.domain.document import Composition, parse_document
from the_frame_v2.domain.geometry import Margins, Orient, Rect, Size
from the_frame_v2.domain.quality import SlotGeometry
from the_frame_v2.services import recipes as recipe_catalog

FIXTURES = Path(__file__).resolve().parents[3] / "conformance" / "geometry"


def _size(v: dict[str, int]) -> Size:
    return Size(v["w"], v["h"])


def _rect(v: dict[str, int]) -> Rect:
    return Rect(v["x"], v["y"], v["w"], v["h"])


def _margins(v: dict[str, int]) -> Margins:
    return Margins(v["top"], v["right"], v["bottom"], v["left"])


def _orient(v: dict[str, Any]) -> Orient:
    return Orient(v["rotate"], v["flip_h"])


def _slot(v: dict[str, Any]) -> SlotGeometry:
    return SlotGeometry(**v)


def _center(v: list[float] | None) -> tuple[float, float] | None:
    return None if v is None else (v[0], v[1])


def _state(v: dict[str, Any]) -> SlotState:
    return SlotState(_rect(v["rect"]), _rect(v["crop"]))


def _slot_state(rect: dict[str, int], crop: dict[str, int]) -> dict[str, Any]:
    """A `SlotState` as the fixtures carry it."""
    return {"rect": rect, "crop": crop}


def _recipe(recipe_id: str) -> composition.Recipe:
    recipe = recipe_catalog.find(recipe_id)
    assert recipe is not None, recipe_id
    return recipe


def _composition(v: dict[str, Any]) -> Composition:
    return Composition.model_validate(v)


def _sizes(v: list[dict[str, int] | None]) -> list[Size | None]:
    return [None if s is None else _size(s) for s in v]


def _cells(v: list[dict[str, Any]]) -> list[Cell]:
    return [Cell(c["id"], _rect(c["rect"]), c["ratio_label"]) for c in v]


def _photo_sizes(v: dict[str, dict[str, int]]) -> dict[str, Size]:
    return {photo_id: _size(size) for photo_id, size in v.items()}


def _caption_style(v: dict[str, Any] | None) -> composition.CaptionStyle | None:
    return None if v is None else composition.CaptionStyle(**v)


def _apply(
    doc: dict[str, Any],
    recipe: composition.Recipe,
    photo_sizes: dict[str, Size],
    caption: composition.CaptionStyle | None,
) -> dict[str, Any]:
    """`composition.apply` on a raw document, back to raw — the fixture is JSON on both sides."""
    return composition.apply(parse_document(doc), recipe, photo_sizes, caption).canonical()


def _restyle(
    doc: dict[str, Any],
    style: dict[str, Any],
    recipe: composition.Recipe | None,
    photo_sizes: dict[str, Size],
) -> dict[str, Any]:
    """`templates.restyle` on a raw document (docs/templates.md §3), back to raw."""
    parsed = templates.FrameStyleDocument.model_validate(style)
    return templates.restyle(parse_document(doc), parsed, recipe, photo_sizes).canonical()


def _relayout(
    doc: dict[str, Any],
    layout: dict[str, Any],
    recipe: composition.Recipe,
    photo_sizes: dict[str, Size],
    caption: composition.CaptionStyle | None,
) -> dict[str, Any]:
    """`templates.relayout` on a raw document, back to raw."""
    parsed = templates.LayoutDocument.model_validate(layout)
    return templates.relayout(parse_document(doc), parsed, recipe, photo_sizes, caption).canonical()


def _style_of(doc: dict[str, Any]) -> dict[str, Any]:
    return templates.style_of_document(parse_document(doc)).model_dump(mode="json")


def _layout_of(doc: dict[str, Any]) -> dict[str, Any] | None:
    layout = templates.layout_of_document(parse_document(doc))
    return None if layout is None else layout.model_dump(mode="json")


def _maybe_recipe(recipe_id: str | None) -> composition.Recipe | None:
    return None if recipe_id is None else _recipe(recipe_id)


# name → (function, {argument: converter})
FUNCTIONS: dict[str, tuple[Callable[..., Any], dict[str, Callable[[Any], Any]]]] = {
    "round_half_even": (geometry.round_half_even, {"value": float}),
    "oriented_size": (geometry.oriented_size, {"source": _size, "orient": _orient}),
    "rect_to_oriented": (
        geometry.rect_to_oriented,
        {"rect": _rect, "source": _size, "orient": _orient},
    ),
    "rect_from_oriented": (
        geometry.rect_from_oriented,
        {"rect": _rect, "source": _size, "orient": _orient},
    ),
    "reorient_crop": (
        geometry.reorient_crop,
        {"crop": _rect, "source": _size, "old": _orient, "new": _orient},
    ),
    "crop_within": (geometry.crop_within, {"crop": _rect, "bounds": _size}),
    "aspect_consistent": (
        geometry.aspect_consistent,
        {"rect_w": int, "rect_h": int, "crop_w": int, "crop_h": int},
    ),
    "parse_ratio": (geometry.parse_ratio, {"crop_ratio": str, "source": _size}),
    "rotated_bounds": (
        geometry.rotated_bounds,
        {"rect_x": float, "rect_y": float, "w": float, "h": float, "degrees": float},
    ),
    "slot_quality": (quality.slot_quality, {"slot": _slot}),
    "artwork_quality": (quality.artwork_quality, {"slots": lambda v: [_slot(s) for s in v]}),
    "available_area": (placement.available_area, {"margins": _margins}),
    "fit_rect": (placement.fit_rect, {"area": _rect, "content": _size, "lock": str}),
    "largest_crop": (
        placement.largest_crop,
        {"bounds": _size, "ratio": lambda v: v, "center": _center},
    ),
    "native_crop_for_area": (
        placement.native_crop_for_area,
        {"area": _size, "source": _size, "crop_ratio": str, "previous": _rect},
    ),
    "margins_for_slot": (
        placement.margins_for_slot,
        {
            "slot": _size,
            "previous": _margins,
            "linked": bool,
            "mirror_x": bool,
            "mirror_y": bool,
        },
    ),
    "fit_in_mat": (
        placement.fit_in_mat,
        {"source": _size, "crop": _rect, "crop_ratio": str, "margins": _margins, "lock": str},
    ),
    "fill": (placement.fill, {"source": _size, "lock": str}),
    "fill_slot": (placement.fill_slot, {"rect": _rect, "source": _size, "lock": str}),
    "fit_slot": (placement.fit_slot, {"rect": _rect, "source": _size, "lock": str}),
    "ratio_label": (placement.ratio_label, {"w": int, "h": int}),
    "resize_slot": (
        constraints.resize_slot,
        {
            "state": _state,
            "requested": _size,
            "source": _size,
            "lock": str,
            "anchor": lambda v: (v[0], v[1]),
        },
    ),
    "resize_crop": (
        constraints.resize_crop,
        {"state": _state, "requested": _rect, "source": _size, "lock": str},
    ),
    "pan_crop": (constraints.pan_crop, {"state": _state, "dx": int, "dy": int, "source": _size}),
    "zoom_crop": (
        constraints.zoom_crop,
        {"state": _state, "factor": float, "source": _size, "lock": str},
    ),
    "apply_lock": (constraints.apply_lock, {"state": _state, "lock": str, "source": _size}),
    "apply_crop_ratio": (
        constraints.apply_crop_ratio,
        {"state": _state, "ratio": lambda v: v, "source": _size, "lock": str},
    ),
    "bounding_box": (arrange.bounding_box, {"rects": lambda v: [_rect(r) for r in v]}),
    "align": (arrange.align, {"rects": lambda v: [_rect(r) for r in v], "edge": str}),
    "distribute": (arrange.distribute, {"rects": lambda v: [_rect(r) for r in v], "axis": str}),
    "same_size": (
        arrange.same_size,
        {"rects": lambda v: [_rect(r) for r in v], "reference": int},
    ),
    "new_slot_size": (
        arrange.new_slot_size,
        {"area": _rect, "source": lambda v: None if v is None else _size(v)},
    ),
    "new_slot_rect": (
        arrange.new_slot_rect,
        {"existing": lambda v: [_rect(r) for r in v], "area": _rect, "size": _size},
    ),
    "composition_solve": (
        composition.solve,
        {
            "recipe": _recipe,
            "composition": _composition,
            "photo_sizes": _sizes,
            "caption_size": int,
        },
    ),
    "composition_solve_strict": (
        composition.solve_strict,
        {
            "recipe": _recipe,
            "composition": _composition,
            "photo_sizes": _sizes,
            "caption_size": int,
        },
    ),
    "composition_apply": (
        _apply,
        {
            "doc": lambda v: v,
            "recipe": _recipe,
            "photo_sizes": _photo_sizes,
            "caption": _caption_style,
        },
    ),
    "templates_restyle": (
        _restyle,
        {
            "doc": lambda v: v,
            "style": lambda v: v,
            "recipe": _maybe_recipe,
            "photo_sizes": _photo_sizes,
        },
    ),
    "templates_relayout": (
        _relayout,
        {
            "doc": lambda v: v,
            "layout": lambda v: v,
            "recipe": _recipe,
            "photo_sizes": _photo_sizes,
            "caption": _caption_style,
        },
    ),
    "templates_style_of_document": (_style_of, {"doc": lambda v: v}),
    "templates_layout_of_document": (_layout_of, {"doc": lambda v: v}),
    "composition_block_area": (
        composition.block_area,
        {"composition": _composition, "caption_size": int},
    ),
    "composition_block_margins": (
        composition.block_margins,
        {"cells": _cells, "border": int},
    ),
    "composition_refit_crop": (
        composition.refit_crop,
        {
            "previous": lambda v: None if v is None else _rect(v),
            "source": _size,
            "ratio": lambda v: v,
        },
    ),
    "composition_caption_band": (
        composition.caption_band,
        {"caption_size": int, "gutter_y": int},
    ),
    "composition_format_ratio": (
        composition.format_ratio,
        {"composition_format": str},
    ),
    "alternatives": (
        alternatives.alternatives,
        {
            "state": _state,
            "source": _size,
            "lock": str,
            "placement": str,
            "margins": _margins,
            "linked": bool,
            "crop_ratio": str,
            "mirror_x": bool,
            "mirror_y": bool,
        },
    ),
}

O0 = {"rotate": 0, "flip_h": False}
O90 = {"rotate": 90, "flip_h": False}
O180F = {"rotate": 180, "flip_h": True}
O270 = {"rotate": 270, "flip_h": False}
O90F = {"rotate": 90, "flip_h": True}
SRC = {"w": 6000, "h": 4000}
SMALL = {"w": 1000, "h": 800}
M_DEFAULT = {"top": 200, "right": 200, "bottom": 260, "left": 200}
M_ZERO = {"top": 0, "right": 0, "bottom": 0, "left": 0}

# Slot states for the constraint solver and alternatives (rect/crop always aspect-consistent).
FIT_STATE = {"rect": {"x": 645, "y": 200, "w": 2550, "h": 1700}, "crop": {**SRC, "x": 0, "y": 0}}
"""`fit_in_mat` of the whole 6000×4000 photo inside M_DEFAULT (downscaled 0.425)."""
ZOOMED_STATE = {
    "rect": {"x": 645, "y": 200, "w": 2550, "h": 1700},
    "crop": {"x": 2000, "y": 1000, "w": 3000, "h": 2000},
}
"""Same slot showing a 3000×2000 crop: the crop can still grow inside the source."""
NATIVE_STATE = {
    "rect": {"x": 920, "y": 580, "w": 2000, "h": 1333},
    "crop": {"x": 2000, "y": 1300, "w": 2000, "h": 1333},
}
SMALL_STATE = {"rect": {"x": 0, "y": 0, "w": 1000, "h": 800}, "crop": {**SMALL, "x": 0, "y": 0}}
UPSCALED_STATE = {
    "rect": {"x": 400, "y": 200, "w": 2000, "h": 1600},
    "crop": {"x": 0, "y": 0, "w": 1000, "h": 800},
}
"""Enlarged ×2 (manual placement)."""
UPSCALED_FIT_STATE = {
    "rect": {"x": 858, "y": 200, "w": 2125, "h": 1700},
    "crop": {"x": 0, "y": 0, "w": 1000, "h": 800},
}
FILL_STATE = {
    "rect": {"x": 0, "y": 0, "w": 3840, "h": 2160},
    "crop": {"x": 0, "y": 119, "w": 1000, "h": 562},
}


EDGES = ["left", "h_center", "right", "top", "v_center", "bottom"]
THREE = [
    {"x": 200, "y": 200, "w": 1200, "h": 800},
    {"x": 1600, "y": 340, "w": 900, "h": 1200},
    {"x": 2750, "y": 180, "w": 1000, "h": 700},
]
"""Three slots of a 1+2 collage: different sizes, different positions."""
SHUFFLED = [THREE[2], THREE[0], THREE[1]]
OVERLAPPING = [
    {"x": 200, "y": 200, "w": 1200, "h": 800},
    {"x": 900, "y": 200, "w": 1200, "h": 800},
    {"x": 1400, "y": 200, "w": 1200, "h": 800},
]
AREA = {"x": 200, "y": 200, "w": 3440, "h": 1760}
"""Available area of the default margins (canvas minus M_DEFAULT)."""


def _q(rw: int, rh: int, cw: int, ch: int, rot: float = 0, photo: bool = True) -> dict[str, Any]:
    return {
        "rect_w": rw,
        "rect_h": rh,
        "crop_w": cw,
        "crop_h": ch,
        "rotation": rot,
        "has_photo": photo,
    }


def _comp(
    recipe: str,
    fmt: str = "fill",
    *,
    border: int | None = None,
    caption: str = "none",
    balance: float | None = None,
    outer: tuple[int, int] = (120, 120),
    gutter: tuple[int, int] = (80, 80),
    cell_formats: list[str | None] | None = None,
) -> dict[str, Any]:
    """A complete composition block: fixtures carry every field (the TS mirror has no defaults)."""
    return {
        "recipe": recipe,
        "balance": balance,
        "outer": {"x": outer[0], "y": outer[1]},
        "gutter": {"x": gutter[0], "y": gutter[1]},
        "format": fmt,
        "cell_formats": cell_formats or [],
        "border": None if border is None else {"width": border, "color": "#FFFFFF"},
        "caption": {"text": "" if caption == "none" else "Kyoto - April 2026", "place": caption},
        "detached": False,
    }


RECIPES = recipe_catalog.all_recipes()
PHOTOS: list[dict[str, int] | None] = [
    {"w": 6000, "h": 4000},
    {"w": 3000, "h": 4000},
    {"w": 4000, "h": 4000},
    {"w": 5000, "h": 2000},
    {"w": 4000, "h": 6000},
    {"w": 6000, "h": 3000},
]
"""One per cell of the biggest recipe; `auto` and `original` read the first."""
BALANCED = [r for r in RECIPES if r.balance is not None]
CELLS_3 = [
    {"id": "c1", "rect": {"x": 120, "y": 284, "w": 2387, "h": 1592}, "ratio_label": "2387:1592"},
    {"id": "c2", "rect": {"x": 2587, "y": 284, "w": 1133, "h": 756}, "ratio_label": "1133:756"},
    {"id": "c3", "rect": {"x": 2587, "y": 1120, "w": 1133, "h": 756}, "ratio_label": "1133:756"},
]
"""The `three-hero-left` 3:2 block of docs/simple-editor.md §3.5."""

CAPTION_STYLE = {
    "font": "inter",
    "weight": 400,
    "size": 72,
    "color": "#222222",
    "letter_spacing": 0.05,
}


def _doc_slot(
    index: int,
    photo_id: str | None = None,
    *,
    crop: tuple[int, int, int, int] = (0, 0, 3000, 2000),
    rotate: int = 0,
    shadow: bool = False,
) -> dict[str, Any]:
    """A slot as it reaches the server: deliberately wrong geometry, real framing to preserve.

    The rect is half the crop — valid (the aspects match) but nowhere near the solver's cell, so
    the fixture shows that the composition, not the payload, decides where a slot lands.
    """
    return {
        "id": f"c{index + 1}",
        "photo_id": photo_id,
        "rect": {"x": 100, "y": 100, "w": crop[2] // 2, "h": crop[3] // 2},
        "rotation": 12.5,
        "source": {
            "orient": {"rotate": rotate, "flip_h": False},
            "crop": {"x": crop[0], "y": crop[1], "w": crop[2], "h": crop[3]},
            "crop_ratio": "3:2",
        },
        "quality_lock": "free",
        "bands": [{"width": 9, "color": "#000000"}],
        "shadow": (
            {
                "type": "drop",
                "offset_x": 8,
                "offset_y": 8,
                "blur": 20,
                "color": "#000000",
                "opacity": 0.4,
            }
            if shadow
            else None
        ),
    }


def _doc(
    comp: dict[str, Any],
    slots: list[dict[str, Any]],
    captions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A complete document: fixtures carry every field (the TS mirror has no defaults)."""
    return {
        "schema": 1,
        "canvas": {"width": 3840, "height": 2160},
        "mat": {"color": "#F2EFE8", "texture": None},
        "placement": "manual",
        "margins": {
            "top": 7,
            "right": 7,
            "bottom": 7,
            "left": 7,
            "linked": True,
            "mirror_x": True,
            "mirror_y": True,
        },
        "composition": comp,
        "slots": slots,
        "captions": captions or [],
    }


SIZES_3 = {"p1": {"w": 6000, "h": 4000}, "p2": {"w": 3000, "h": 4000}, "p3": {"w": 4000, "h": 4000}}

DOC_CAPTION = {
    "id": "legacy",
    "text": "Kyoto - April 2026",
    "font": "inter",
    "weight": 600,
    "size": 31,
    "color": "#101010",
    "letter_spacing": -0.01,
    "x": 10,
    "y": 10,
    "anchor": "start",
    "rotation": 3.5,
}


def _style(
    *,
    color: str,
    band: int | None,
    shadow: bool,
    size: int,
) -> dict[str, Any]:
    """A complete frame style document (fixtures carry every field: the TS mirror has none)."""
    return {
        "mat": {"color": color, "texture": {"id": "linen-01", "strength": 0.5}},
        "margins": {
            "top": 200,
            "right": 200,
            "bottom": 260,
            "left": 200,
            "linked": False,
            "mirror_x": False,
            "mirror_y": False,
        },
        "slot_defaults": {
            "bands": [] if band is None else [{"width": band, "color": "#FFFFFF"}],
            "shadow": (
                {
                    "type": "inner",
                    "offset_x": 0,
                    "offset_y": 6,
                    "blur": 28,
                    "color": "#000000",
                    "opacity": 0.45,
                }
                if shadow
                else None
            ),
            "quality_lock": "no_upscale",
        },
        "caption_defaults": {
            "font": "inter",
            "weight": 400,
            "size": size,
            "color": "#222222",
            "letter_spacing": 0.05,
        },
    }


STYLES = {
    "banded": _style(color="#101010", band=18, shadow=True, size=72),
    "plain": _style(color="#FFFFFF", band=None, shadow=False, size=40),
}


def _layout(
    recipe: str,
    fmt: str = "fill",
    *,
    border: int | None = None,
    caption_place: str = "none",
    outer: tuple[int, int] = (200, 180),
    gutter: tuple[int, int] = (90, 90),
    balance: float | None = None,
) -> dict[str, Any]:
    """A complete layout document — a recipe and its parameters (docs/templates.md §2)."""
    return {
        "recipe": recipe,
        "balance": balance,
        "outer": {"x": outer[0], "y": outer[1]},
        "gutter": {"x": gutter[0], "y": gutter[1]},
        "format": fmt,
        "cell_formats": [],
        "border": None if border is None else {"width": border, "color": "#FFFFFF"},
        "caption_place": caption_place,
    }


LAYOUTS = {
    "stacked": _layout("two-stacked", outer=(300, 120), gutter=(60, 60)),
    "squares": _layout("two-side-by-side", "1:1", border=18, caption_place="below"),
}

SAVE_AS_DOCS = {
    "attached": _doc(
        _comp("two-side-by-side", "1:1", border=18, caption="below"),
        [_doc_slot(0, "p1", shadow=True), _doc_slot(1, "p2")],
        [DOC_CAPTION],
    ),
    "detached": _doc(
        {**_comp("two-side-by-side"), "detached": True},
        [_doc_slot(0, "p1", shadow=True), _doc_slot(1, "p2")],
        [],
    ),
}


CASES: dict[str, list[tuple[str, str, dict[str, Any]]]] = {
    "geometry.json": [
        *[
            (f"round {v}", "round_half_even", {"value": v})
            for v in (0.5, 1.5, 2.5, -0.5, -1.5, 2.4999, 2.5001, 1919.5, 3.0, -2.6)
        ],
        ("oriented 90", "oriented_size", {"source": SRC, "orient": O90}),
        ("oriented 180 flip", "oriented_size", {"source": SRC, "orient": O180F}),
        *[
            (
                f"to oriented {o}",
                "rect_to_oriented",
                {"rect": {"x": 100, "y": 200, "w": 3000, "h": 1500}, "source": SRC, "orient": o},
            )
            for o in (O0, O90, O180F, O270, O90F)
        ],
        *[
            (
                f"from oriented {o}",
                "rect_from_oriented",
                {"rect": {"x": 10, "y": 20, "w": 300, "h": 150}, "source": SRC, "orient": o},
            )
            for o in (O0, O90, O180F, O270, O90F)
        ],
        (
            "reorient 0→90",
            "reorient_crop",
            {
                "crop": {"x": 0, "y": 500, "w": 4000, "h": 2250},
                "source": SRC,
                "old": O0,
                "new": O90,
            },
        ),
        (
            "reorient 90→270 flip",
            "reorient_crop",
            {
                "crop": {"x": 100, "y": 0, "w": 2000, "h": 3000},
                "source": SRC,
                "old": O90,
                "new": O90F,
            },
        ),
        (
            "within ok",
            "crop_within",
            {"crop": {"x": 0, "y": 0, "w": 6000, "h": 4000}, "bounds": SRC},
        ),
        (
            "within overflow",
            "crop_within",
            {"crop": {"x": 1, "y": 0, "w": 6000, "h": 4000}, "bounds": SRC},
        ),
        (
            "within oriented",
            "crop_within",
            {"crop": {"x": 0, "y": 0, "w": 4000, "h": 6000}, "bounds": {"w": 4000, "h": 6000}},
        ),
        (
            "aspect exact",
            "aspect_consistent",
            {"rect_w": 2550, "rect_h": 1700, "crop_w": 6000, "crop_h": 4000},
        ),
        (
            "aspect rounded",
            "aspect_consistent",
            {"rect_w": 1541, "rect_h": 1448, "crop_w": 4257, "crop_h": 4000},
        ),
        (
            "aspect upscaled rounded",
            "aspect_consistent",
            {"rect_w": 3840, "rect_h": 2160, "crop_w": 1000, "crop_h": 562},
        ),
        (
            "aspect wrong",
            "aspect_consistent",
            {"rect_w": 2000, "rect_h": 1700, "crop_w": 6000, "crop_h": 4000},
        ),
        ("ratio original", "parse_ratio", {"crop_ratio": "original", "source": SRC}),
        ("ratio 16:9", "parse_ratio", {"crop_ratio": "16:9", "source": SRC}),
        ("ratio free", "parse_ratio", {"crop_ratio": "free", "source": SRC}),
        *[
            (
                f"rotated bounds {d}",
                "rotated_bounds",
                {"rect_x": 100.0, "rect_y": 50.0, "w": 1000.0, "h": 600.0, "degrees": d},
            )
            for d in (0.0, 90.0, -7.0, 45.0, 180.0, 12.3)
        ],
    ],
    "quality.json": [
        ("native", "slot_quality", {"slot": _q(3840, 2160, 3840, 2160)}),
        ("native rotated is resampled", "slot_quality", {"slot": _q(3840, 2160, 3840, 2160, 0.5)}),
        ("downscaled", "slot_quality", {"slot": _q(2550, 1700, 6000, 4000)}),
        ("upscaled", "slot_quality", {"slot": _q(3840, 2160, 1000, 562)}),
        ("upscaled one axis", "slot_quality", {"slot": _q(1001, 500, 1000, 500)}),
        ("percent tie", "slot_quality", {"slot": _q(1005, 2, 1000, 2)}),
        (
            "aggregate",
            "artwork_quality",
            {
                "slots": [
                    _q(3840, 2160, 3840, 2160),
                    _q(500, 500, 1000, 1000),
                    _q(10, 10, 1, 1, 0, False),
                ]
            },
        ),
        (
            "aggregate upscaled",
            "artwork_quality",
            {"slots": [_q(500, 500, 1000, 1000), _q(1200, 900, 800, 600, 3)]},
        ),
        ("aggregate empty", "artwork_quality", {"slots": [_q(10, 10, 10, 10, 0, False)]}),
        ("aggregate none", "artwork_quality", {"slots": []}),
    ],
    "placement.json": [
        ("area", "available_area", {"margins": M_DEFAULT}),
        (
            "fit rect downscale",
            "fit_rect",
            {
                "area": {"x": 200, "y": 200, "w": 3440, "h": 1700},
                "content": SRC,
                "lock": "no_upscale",
            },
        ),
        (
            "fit rect no upscale small",
            "fit_rect",
            {
                "area": {"x": 200, "y": 200, "w": 3440, "h": 1700},
                "content": {"w": 1000, "h": 800},
                "lock": "no_upscale",
            },
        ),
        (
            "fit rect free small",
            "fit_rect",
            {
                "area": {"x": 200, "y": 200, "w": 3440, "h": 1700},
                "content": {"w": 1000, "h": 800},
                "lock": "free",
            },
        ),
        (
            "fit rect native large",
            "fit_rect",
            {"area": {"x": 0, "y": 0, "w": 3840, "h": 2160}, "content": SRC, "lock": "native"},
        ),
        (
            "fit rect odd centring",
            "fit_rect",
            {
                "area": {"x": 0, "y": 0, "w": 3841, "h": 2161},
                "content": {"w": 1000, "h": 1000},
                "lock": "no_upscale",
            },
        ),
        ("largest crop 16:9", "largest_crop", {"bounds": SRC, "ratio": 16 / 9, "center": None}),
        (
            "largest crop portrait",
            "largest_crop",
            {"bounds": {"w": 3000, "h": 4000}, "ratio": 1541 / 1448, "center": None},
        ),
        (
            "largest crop centre clamped",
            "largest_crop",
            {"bounds": SRC, "ratio": 1.0, "center": [100.0, 3900.0]},
        ),
        ("largest crop free", "largest_crop", {"bounds": SRC, "ratio": None, "center": None}),
        (
            "native crop ratio",
            "native_crop_for_area",
            {
                "area": {"w": 3440, "h": 1700},
                "source": SRC,
                "crop_ratio": "original",
                "previous": {"x": 0, "y": 0, "w": 6000, "h": 4000},
            },
        ),
        (
            "native crop free",
            "native_crop_for_area",
            {
                "area": {"w": 3440, "h": 1700},
                "source": SRC,
                "crop_ratio": "free",
                "previous": {"x": 4000, "y": 3000, "w": 2000, "h": 1000},
            },
        ),
        (
            "native crop small source",
            "native_crop_for_area",
            {
                "area": {"w": 3440, "h": 1700},
                "source": {"w": 1000, "h": 800},
                "crop_ratio": "16:9",
                "previous": {"x": 0, "y": 0, "w": 1000, "h": 800},
            },
        ),
        (
            "margins proportional",
            "margins_for_slot",
            {
                "slot": {"w": 3000, "h": 1500},
                "previous": {"top": 200, "right": 300, "bottom": 400, "left": 100},
                "linked": False,
                "mirror_x": False,
                "mirror_y": False,
            },
        ),
        (
            "margins zero",
            "margins_for_slot",
            {
                "slot": {"w": 3001, "h": 1501},
                "previous": M_ZERO,
                "linked": False,
                "mirror_x": False,
                "mirror_y": False,
            },
        ),
        (
            "margins linked",
            "margins_for_slot",
            {
                "slot": {"w": 3000, "h": 1501},
                "previous": M_ZERO,
                "linked": True,
                "mirror_x": False,
                "mirror_y": False,
            },
        ),
        (
            "margins oversized",
            "margins_for_slot",
            {
                "slot": {"w": 4000, "h": 2000},
                "previous": M_DEFAULT,
                "linked": False,
                "mirror_x": False,
                "mirror_y": False,
            },
        ),
        (
            "margins mirrored",
            "margins_for_slot",
            {
                "slot": {"w": 3001, "h": 1501},
                "previous": {"top": 100, "right": 500, "bottom": 300, "left": 100},
                "linked": False,
                "mirror_x": True,
                "mirror_y": True,
            },
        ),
        (
            "margins mirrored on one axis",
            "margins_for_slot",
            {
                "slot": {"w": 3000, "h": 1500},
                "previous": {"top": 100, "right": 500, "bottom": 300, "left": 100},
                "linked": False,
                "mirror_x": True,
                "mirror_y": False,
            },
        ),
        (
            "fit in mat",
            "fit_in_mat",
            {
                "source": SRC,
                "crop": {"x": 0, "y": 0, "w": 6000, "h": 4000},
                "crop_ratio": "original",
                "margins": M_DEFAULT,
                "lock": "no_upscale",
            },
        ),
        (
            "fit in mat native shrinks crop",
            "fit_in_mat",
            {
                "source": SRC,
                "crop": {"x": 0, "y": 0, "w": 6000, "h": 4000},
                "crop_ratio": "original",
                "margins": M_DEFAULT,
                "lock": "native",
            },
        ),
        (
            "fit in mat native grows the crop back",
            "fit_in_mat",
            {
                "source": SRC,
                "crop": {"x": 2500, "y": 1600, "w": 1000, "h": 667},
                "crop_ratio": "original",
                "margins": M_DEFAULT,
                "lock": "native",
            },
        ),
        (
            "fit in mat native fits",
            "fit_in_mat",
            {
                "source": {"w": 1200, "h": 900},
                "crop": {"x": 0, "y": 0, "w": 1200, "h": 900},
                "crop_ratio": "original",
                "margins": M_DEFAULT,
                "lock": "native",
            },
        ),
        ("fill", "fill", {"source": SRC, "lock": "no_upscale"}),
        (
            "fill small becomes free",
            "fill",
            {"source": {"w": 1000, "h": 800}, "lock": "no_upscale"},
        ),
        ("fill native", "fill", {"source": SRC, "lock": "native"}),
        (
            "fill slot",
            "fill_slot",
            {"rect": {"x": 80, "y": 80, "w": 1800, "h": 2000}, "source": SRC, "lock": "no_upscale"},
        ),
        (
            "fill slot native small",
            "fill_slot",
            {
                "rect": {"x": 80, "y": 80, "w": 1800, "h": 2000},
                "source": {"w": 1000, "h": 800},
                "lock": "native",
            },
        ),
        (
            "fit slot",
            "fit_slot",
            {
                "rect": {"x": 240, "y": 300, "w": 1900, "h": 1640},
                "source": {"w": 3000, "h": 4000},
                "lock": "no_upscale",
            },
        ),
        *[
            (f"ratio label {w}x{h}", "ratio_label", {"w": w, "h": h})
            for w, h in ((3840, 2160), (1000, 562), (1200, 800), (997, 613))
        ],
        (
            "fit slot native",
            "fit_slot",
            {
                "rect": {"x": 240, "y": 300, "w": 1900, "h": 1640},
                "source": {"w": 800, "h": 600},
                "lock": "native",
            },
        ),
    ],
    "constraints.json": [
        (
            "resize slot free",
            "resize_slot",
            {
                "state": FIT_STATE,
                "requested": {"w": 3000, "h": 1000},
                "source": SRC,
                "lock": "free",
                "anchor": [0.5, 0.5],
            },
        ),
        (
            "resize slot free anchored corner",
            "resize_slot",
            {
                "state": FIT_STATE,
                "requested": {"w": 3000, "h": 1000},
                "source": SRC,
                "lock": "free",
                "anchor": [0.0, 0.0],
            },
        ),
        (
            "resize slot no upscale grows the crop",
            "resize_slot",
            {
                "state": ZOOMED_STATE,
                "requested": {"w": 3000, "h": 2000},
                "source": SRC,
                "lock": "no_upscale",
                "anchor": [0.5, 0.5],
            },
        ),
        (
            "resize slot no upscale clamps on a small source",
            "resize_slot",
            {
                "state": SMALL_STATE,
                "requested": {"w": 2000, "h": 1600},
                "source": SMALL,
                "lock": "no_upscale",
                "anchor": [0.5, 0.5],
            },
        ),
        (
            "resize slot no upscale shrinking keeps the crop",
            "resize_slot",
            {
                "state": FIT_STATE,
                "requested": {"w": 1200, "h": 800},
                "source": SRC,
                "lock": "no_upscale",
                "anchor": [0.5, 0.5],
            },
        ),
        (
            "resize slot native takes the crop along",
            "resize_slot",
            {
                "state": NATIVE_STATE,
                "requested": {"w": 2000, "h": 1400},
                "source": SRC,
                "lock": "native",
                "anchor": [0.5, 0.5],
            },
        ),
        (
            "resize slot native clamped by the source",
            "resize_slot",
            {
                "state": SMALL_STATE,
                "requested": {"w": 4000, "h": 3200},
                "source": SMALL,
                "lock": "native",
                "anchor": [0.5, 0.5],
            },
        ),
        (
            "resize crop free keeps the slot",
            "resize_crop",
            {
                "state": FIT_STATE,
                "requested": {"x": 500, "y": 400, "w": 3000, "h": 2000},
                "source": SRC,
                "lock": "free",
            },
        ),
        (
            "resize crop no upscale clamps to the slot",
            "resize_crop",
            {
                "state": FIT_STATE,
                "requested": {"x": 500, "y": 400, "w": 1200, "h": 800},
                "source": SRC,
                "lock": "no_upscale",
            },
        ),
        (
            "resize crop no upscale shrinks the slot on a small source",
            "resize_crop",
            {
                "state": SMALL_STATE,
                "requested": {"x": 100, "y": 100, "w": 400, "h": 320},
                "source": SMALL,
                "lock": "no_upscale",
            },
        ),
        (
            "resize crop native follows",
            "resize_crop",
            {
                "state": NATIVE_STATE,
                "requested": {"x": 100, "y": 100, "w": 1600, "h": 1200},
                "source": SRC,
                "lock": "native",
            },
        ),
        (
            "resize crop changing the aspect moves the slot",
            "resize_crop",
            {
                "state": FIT_STATE,
                "requested": {"x": 0, "y": 0, "w": 4000, "h": 4000},
                "source": SRC,
                "lock": "free",
            },
        ),
        (
            "resize crop out of bounds is clamped",
            "resize_crop",
            {
                "state": FIT_STATE,
                "requested": {"x": 5500, "y": 3800, "w": 3000, "h": 2000},
                "source": SRC,
                "lock": "free",
            },
        ),
        (
            "pan crop",
            "pan_crop",
            {"state": ZOOMED_STATE, "dx": -300, "dy": 120, "source": SRC},
        ),
        (
            "pan crop clamped",
            "pan_crop",
            {"state": ZOOMED_STATE, "dx": -5000, "dy": 5000, "source": SRC},
        ),
        (
            "zoom crop out",
            "zoom_crop",
            {"state": ZOOMED_STATE, "factor": 1.25, "source": SRC, "lock": "free"},
        ),
        (
            "zoom crop in blocked by no upscale",
            "zoom_crop",
            {"state": FIT_STATE, "factor": 0.25, "source": SRC, "lock": "no_upscale"},
        ),
        (
            "zoom crop in native",
            "zoom_crop",
            {"state": NATIVE_STATE, "factor": 0.5, "source": SRC, "lock": "native"},
        ),
        (
            "zoom out past the whole photo keeps the crop's aspect",
            "zoom_crop",
            {
                "state": _slot_state(
                    {"x": 0, "y": 0, "w": 1147, "h": 1920},
                    {"x": 1500, "y": 500, "w": 1147, "h": 1920},
                ),
                "factor": 4.0,
                "source": {"w": 4080, "h": 3072},
                "lock": "no_upscale",
            },
        ),
        (
            "zoom out to exactly the whole photo",
            "zoom_crop",
            {
                "state": _slot_state(
                    {"x": 0, "y": 0, "w": 2000, "h": 1000},
                    {"x": 0, "y": 536, "w": 4080, "h": 2040},
                ),
                "factor": 2.0,
                "source": {"w": 4080, "h": 3072},
                "lock": "free",
            },
        ),
        (
            "zoom in keeps the rect's aspect, not the rounded crop's",
            "zoom_crop",
            {
                "state": _slot_state(
                    {"x": 0, "y": 0, "w": 2387, "h": 1592},
                    {"x": 0, "y": 0, "w": 4000, "h": 2668},
                ),
                "factor": 1 / 1.06,
                "source": {"w": 4000, "h": 3000},
                "lock": "free",
            },
        ),
        (
            "a zoom that rounds to nothing still moves a pixel",
            "zoom_crop",
            {
                "state": _slot_state(
                    {"x": 0, "y": 0, "w": 1800, "h": 1200},
                    {"x": 1494, "y": 994, "w": 8, "h": 5},
                ),
                "factor": 1.06,
                "source": {"w": 3000, "h": 2000},
                "lock": "free",
            },
        ),
        (
            "apply lock native",
            "apply_lock",
            {"state": FIT_STATE, "lock": "native", "source": SRC},
        ),
        (
            "apply lock native clamped",
            "apply_lock",
            {"state": UPSCALED_STATE, "lock": "native", "source": SMALL},
        ),
        (
            "apply lock no upscale shrinks",
            "apply_lock",
            {"state": UPSCALED_STATE, "lock": "no_upscale", "source": SMALL},
        ),
        (
            "apply lock free keeps everything",
            "apply_lock",
            {"state": UPSCALED_STATE, "lock": "free", "source": SMALL},
        ),
        (
            "apply crop ratio square",
            "apply_crop_ratio",
            {"state": FIT_STATE, "ratio": 1.0, "source": SRC, "lock": "no_upscale"},
        ),
        (
            "apply crop ratio free keeps the crop",
            "apply_crop_ratio",
            {"state": FIT_STATE, "ratio": None, "source": SRC, "lock": "no_upscale"},
        ),
        (
            "apply crop ratio under native",
            "apply_crop_ratio",
            {"state": NATIVE_STATE, "ratio": 16 / 9, "source": SRC, "lock": "native"},
        ),
    ],
    "arrange.json": [
        ("bounding box", "bounding_box", {"rects": THREE}),
        *[(f"align {e}", "align", {"rects": THREE, "edge": e}) for e in EDGES],
        ("distribute x", "distribute", {"rects": THREE, "axis": "x"}),
        ("distribute y", "distribute", {"rects": THREE, "axis": "y"}),
        ("distribute keeps the input order", "distribute", {"rects": SHUFFLED, "axis": "x"}),
        ("distribute two is a no-op", "distribute", {"rects": THREE[:2], "axis": "x"}),
        ("distribute overlapping", "distribute", {"rects": OVERLAPPING, "axis": "x"}),
        ("same size first", "same_size", {"rects": THREE, "reference": 0}),
        ("same size last", "same_size", {"rects": THREE, "reference": 2}),
        ("new slot size empty", "new_slot_size", {"area": AREA, "source": None}),
        (
            "new slot size portrait",
            "new_slot_size",
            {"area": AREA, "source": {"w": 3000, "h": 4000}},
        ),
        ("new slot size wide", "new_slot_size", {"area": AREA, "source": SRC}),
        (
            "new slot rect first",
            "new_slot_rect",
            {"existing": [], "area": AREA, "size": {"w": 1500, "h": 800}},
        ),
        (
            "new slot rect cascades",
            "new_slot_rect",
            {
                "existing": [{"x": 1170, "y": 680, "w": 1500, "h": 800}],
                "area": AREA,
                "size": {"w": 1500, "h": 800},
            },
        ),
        (
            "new slot rect clamped into the area",
            "new_slot_rect",
            {"existing": [], "area": AREA, "size": {"w": 3600, "h": 2000}},
        ),
    ],
    "alternatives.json": [
        (
            "not upscaled",
            "alternatives",
            {
                "state": FIT_STATE,
                "source": SRC,
                "lock": "no_upscale",
                "placement": "fit_in_mat",
                "margins": M_DEFAULT,
                "linked": False,
                "crop_ratio": "original",
                "mirror_x": False,
                "mirror_y": False,
            },
        ),
        (
            "fit in mat upscaled",
            "alternatives",
            {
                "state": UPSCALED_FIT_STATE,
                "source": SMALL,
                "lock": "free",
                "placement": "fit_in_mat",
                "margins": M_DEFAULT,
                "linked": False,
                "crop_ratio": "original",
                "mirror_x": False,
                "mirror_y": False,
            },
        ),
        (
            "fit in mat upscaled linked margins",
            "alternatives",
            {
                "state": UPSCALED_FIT_STATE,
                "source": SMALL,
                "lock": "free",
                "placement": "fit_in_mat",
                "margins": M_DEFAULT,
                "linked": True,
                "crop_ratio": "original",
                "mirror_x": False,
                "mirror_y": False,
            },
        ),
        (
            "fill upscaled",
            "alternatives",
            {
                "state": FILL_STATE,
                "source": SMALL,
                "lock": "free",
                "placement": "fill",
                "margins": M_DEFAULT,
                "linked": False,
                "crop_ratio": "16:9",
                "mirror_x": False,
                "mirror_y": False,
            },
        ),
        (
            "manual upscaled with a large source",
            "alternatives",
            {
                "state": UPSCALED_STATE,
                "source": SRC,
                "lock": "no_upscale",
                "placement": "manual",
                "margins": M_ZERO,
                "linked": False,
                "crop_ratio": "original",
                "mirror_x": False,
                "mirror_y": False,
            },
        ),
    ],
    "composition.json": [
        *[
            (
                f"solve {recipe.id} {fmt} border={border} caption={caption}",
                "composition_solve",
                {
                    "recipe": recipe.id,
                    "composition": _comp(recipe.id, fmt, border=border, caption=caption),
                    "photo_sizes": PHOTOS[: recipe.count],
                    "caption_size": 48,
                },
            )
            for recipe in RECIPES
            for fmt in ("fill", "3:2")
            for border in (None, 24)
            for caption in ("none", "below")
        ],
        *[
            (
                f"solve {recipe.id} balance {edge}",
                "composition_solve",
                {
                    "recipe": recipe.id,
                    "composition": _comp(
                        recipe.id,
                        balance=getattr(recipe.balance, edge),
                    ),
                    "photo_sizes": PHOTOS[: recipe.count],
                    "caption_size": 48,
                },
            )
            for recipe in BALANCED
            for edge in ("min", "max")
        ],
        *[
            (
                f"solve single {fmt} photo {photo['w']}x{photo['h']}",
                "composition_solve",
                {
                    "recipe": "single",
                    "composition": _comp("single", fmt),
                    "photo_sizes": [photo],
                    "caption_size": 48,
                },
            )
            for fmt in ("original", "fill", "1:1", "16:9")
            for photo in ({"w": 6000, "h": 4000}, {"w": 3000, "h": 4000})
        ],
        (
            "solve single original without a photo",
            "composition_solve",
            {
                "recipe": "single",
                "composition": _comp("single", "original"),
                "photo_sizes": [None],
                "caption_size": 48,
            },
        ),
        (
            "solve caption above",
            "composition_solve",
            {
                "recipe": "two-side-by-side",
                "composition": _comp("two-side-by-side", caption="above"),
                "photo_sizes": PHOTOS[:2],
                "caption_size": 48,
            },
        ),
        (
            "solve portrait format",
            "composition_solve",
            {
                "recipe": "three-row",
                "composition": _comp("three-row", "2:3"),
                "photo_sizes": PHOTOS[:3],
                "caption_size": 48,
            },
        ),
        (
            "solve per-cell formats",
            "composition_solve",
            {
                "recipe": "three-one-over-two",
                "composition": _comp(
                    "three-one-over-two", "3:2", cell_formats=[None, "1:1", "1:1"]
                ),
                "photo_sizes": PHOTOS[:3],
                "caption_size": 48,
            },
        ),
        (
            "solve per-cell original next to a ratio",
            "composition_solve",
            {
                "recipe": "two-side-by-side",
                "composition": _comp("two-side-by-side", "3:2", cell_formats=[None, "original"]),
                "photo_sizes": PHOTOS[:2],
                "caption_size": 48,
            },
        ),
        (
            "solve per-cell formats are inert under fill",
            "composition_solve",
            {
                "recipe": "two-side-by-side",
                "composition": _comp("two-side-by-side", cell_formats=["1:1", "16:9"]),
                "photo_sizes": PHOTOS[:2],
                "caption_size": 48,
            },
        ),
        (
            "solve zero margins",
            "composition_solve",
            {
                "recipe": "four-grid",
                "composition": _comp("four-grid", outer=(0, 0), gutter=(0, 0)),
                "photo_sizes": PHOTOS[:4],
                "caption_size": 48,
            },
        ),
        (
            "solve over-constrained relaxes",
            "composition_solve",
            {
                "recipe": "six-grid-3x2",
                "composition": _comp(
                    "six-grid-3x2", border=200, outer=(800, 450), gutter=(400, 400)
                ),
                "photo_sizes": PHOTOS[:6],
                "caption_size": 48,
            },
        ),
        *[
            (
                f"apply three-hero-left {fmt} border={border} caption={caption}",
                "composition_apply",
                {
                    "doc": _doc(
                        _comp("three-hero-left", fmt, border=border, caption=caption),
                        [
                            _doc_slot(0, "p1", crop=(1200, 800, 3000, 2000)),
                            _doc_slot(1, "p2", crop=(0, 0, 1500, 2000), shadow=True),
                            _doc_slot(2, "p3", crop=(500, 500, 2000, 2000)),
                        ],
                    ),
                    "recipe": "three-hero-left",
                    "photo_sizes": SIZES_3,
                    "caption": None,
                },
            )
            for fmt in ("fill", "3:2")
            for border in (None, 24)
            for caption in ("none", "below")
        ],
        (
            "apply keeps an empty slot a placeholder",
            "composition_apply",
            {
                "doc": _doc(
                    _comp("three-row"),
                    [_doc_slot(0, "p1"), _doc_slot(1), _doc_slot(2, "p3")],
                ),
                "recipe": "three-row",
                "photo_sizes": SIZES_3,
                "caption": None,
            },
        ),
        (
            "apply with an unknown photo",
            "composition_apply",
            {
                "doc": _doc(
                    _comp("two-side-by-side"),
                    [_doc_slot(0, "p1"), _doc_slot(1, "gone")],
                ),
                "recipe": "two-side-by-side",
                "photo_sizes": SIZES_3,
                "caption": None,
            },
        ),
        (
            "apply through a 90 degrees orient",
            "composition_apply",
            {
                "doc": _doc(
                    _comp("two-stacked", "3:2"),
                    [
                        _doc_slot(0, "p1", rotate=90, crop=(0, 0, 2000, 3000)),
                        _doc_slot(1, "p2", rotate=270),
                    ],
                ),
                "recipe": "two-stacked",
                "photo_sizes": SIZES_3,
                "caption": None,
            },
        ),
        (
            "apply caption above with the style typography",
            "composition_apply",
            {
                "doc": _doc(
                    _comp("two-side-by-side", caption="above"),
                    [_doc_slot(0, "p1"), _doc_slot(1, "p2")],
                ),
                "recipe": "two-side-by-side",
                "photo_sizes": SIZES_3,
                "caption": CAPTION_STYLE,
            },
        ),
        (
            "apply keeps the document's own caption typography and id",
            "composition_apply",
            {
                "doc": _doc(
                    _comp("two-side-by-side", caption="below"),
                    [_doc_slot(0, "p1"), _doc_slot(1, "p2")],
                    [
                        {
                            "id": "legacy",
                            "text": "moved and restyled",
                            "font": "inter",
                            "weight": 600,
                            "size": 31,
                            "color": "#101010",
                            "letter_spacing": -0.01,
                            "x": 10,
                            "y": 10,
                            "anchor": "start",
                            "rotation": 3.5,
                        }
                    ],
                ),
                "recipe": "two-side-by-side",
                "photo_sizes": SIZES_3,
                "caption": None,
            },
        ),
        (
            "apply drops a caption whose text is empty",
            "composition_apply",
            {
                "doc": _doc(
                    {
                        **_comp("two-side-by-side", caption="below"),
                        "caption": {
                            "text": "  ",
                            "place": "below",
                        },
                    },
                    [_doc_slot(0, "p1"), _doc_slot(1, "p2")],
                ),
                "recipe": "two-side-by-side",
                "photo_sizes": SIZES_3,
                "caption": None,
            },
        ),
        (
            "apply single original",
            "composition_apply",
            {
                "doc": _doc(_comp("single", "original"), [_doc_slot(0, "p2")]),
                "recipe": "single",
                "photo_sizes": SIZES_3,
                "caption": None,
            },
        ),
        (
            "apply leaves a detached document alone",
            "composition_apply",
            {
                "doc": _doc(
                    {**_comp("two-side-by-side"), "detached": True},
                    [_doc_slot(0, "p1"), _doc_slot(1, "p2")],
                ),
                "recipe": "two-side-by-side",
                "photo_sizes": SIZES_3,
                "caption": None,
            },
        ),
        (
            "apply an over-constrained document",
            "composition_apply",
            {
                "doc": _doc(
                    _comp("six-grid-3x2", border=200, outer=(800, 450), gutter=(400, 400)),
                    [_doc_slot(i, f"p{(i % 3) + 1}") for i in range(6)],
                ),
                "recipe": "six-grid-3x2",
                "photo_sizes": SIZES_3,
                "caption": None,
            },
        ),
        *[
            (
                f"solve strict {label}",
                "composition_solve_strict",
                {
                    "recipe": "six-grid-3x2",
                    "composition": _comp("six-grid-3x2", border=border, gutter=gutter),
                    "photo_sizes": PHOTOS[:6],
                    "caption_size": 48,
                },
            )
            # the second one is over-constrained: `solve` would hide it behind the ladder
            for label, border, gutter in (("roomy", None, (80, 80)), ("slivers", 200, (400, 400)))
        ],
        (
            "block area plain",
            "composition_block_area",
            {"composition": _comp("four-grid"), "caption_size": 48},
        ),
        (
            "block area caption below",
            "composition_block_area",
            {"composition": _comp("four-grid", caption="below"), "caption_size": 48},
        ),
        (
            "block area caption above",
            "composition_block_area",
            {"composition": _comp("four-grid", caption="above"), "caption_size": 72},
        ),
        ("block margins no border", "composition_block_margins", {"cells": CELLS_3, "border": 0}),
        ("block margins border 24", "composition_block_margins", {"cells": CELLS_3, "border": 24}),
        ("block margins empty", "composition_block_margins", {"cells": [], "border": 0}),
        (
            "refit crop fresh",
            "composition_refit_crop",
            {"previous": None, "source": SRC, "ratio": 1.5},
        ),
        (
            "refit crop keeps the zoom",
            "composition_refit_crop",
            {"previous": {"x": 2000, "y": 1000, "w": 3000, "h": 2000}, "source": SRC, "ratio": 1.0},
        ),
        (
            "refit crop clamps into the source",
            "composition_refit_crop",
            {"previous": {"x": 5000, "y": 3500, "w": 900, "h": 600}, "source": SRC, "ratio": 1.5},
        ),
        (
            "refit crop free ratio",
            "composition_refit_crop",
            {"previous": {"x": 100, "y": 100, "w": 3000, "h": 2000}, "source": SRC, "ratio": None},
        ),
        *[
            (
                f"caption band {size}",
                "composition_caption_band",
                {"caption_size": size, "gutter_y": 80},
            )
            for size in (48, 72, 31)
        ],
        *[
            (f"format ratio {fmt}", "composition_format_ratio", {"composition_format": fmt})
            for fmt in ("fill", "original", "3:2", "2:3", "1:1", "16:9")
        ],
    ],
    "templates.json": [
        *[
            (
                f"restyle {style_name} attached={attached} caption={caption}",
                "templates_restyle",
                {
                    "doc": _doc(
                        {
                            **_comp("three-hero-left", "3:2", border=24, caption=caption),
                            "detached": not attached,
                        },
                        [
                            _doc_slot(0, "p1", crop=(1200, 800, 3000, 2000)),
                            _doc_slot(1, "p2", crop=(0, 0, 1500, 2000), shadow=True),
                            _doc_slot(2, "p3", crop=(500, 500, 2000, 2000)),
                        ],
                        [DOC_CAPTION] if caption != "none" else [],
                    ),
                    "style": style,
                    "recipe": "three-hero-left",
                    "photo_sizes": SIZES_3,
                },
            )
            for style_name, style in STYLES.items()
            for attached in (True, False)
            for caption in ("none", "below")
        ],
        (
            "restyle without a recipe leaves the geometry alone",
            "templates_restyle",
            {
                "doc": _doc(
                    _comp("two-side-by-side", border=12),
                    [_doc_slot(0, "p1"), _doc_slot(1, "p2")],
                ),
                "style": STYLES["banded"],
                "recipe": None,
                "photo_sizes": SIZES_3,
            },
        ),
        *[
            (
                f"relayout to {layout_name}",
                "templates_relayout",
                {
                    "doc": _doc(
                        _comp("two-side-by-side", border=12, caption="below"),
                        [
                            _doc_slot(0, "p1", crop=(1200, 800, 3000, 2000)),
                            _doc_slot(1, "p2", crop=(0, 0, 1500, 2000), shadow=True),
                        ],
                        [DOC_CAPTION],
                    ),
                    "layout": layout,
                    "recipe": layout["recipe"],
                    "photo_sizes": SIZES_3,
                    "caption": None,
                },
            )
            for layout_name, layout in LAYOUTS.items()
        ],
        (
            "relayout re-attaches a detached artwork with the style's typography",
            "templates_relayout",
            {
                "doc": _doc(
                    {**_comp("two-side-by-side"), "detached": True},
                    [_doc_slot(0, "p1"), _doc_slot(1, "p2")],
                    [DOC_CAPTION],
                ),
                "layout": LAYOUTS["stacked"],
                "recipe": "two-stacked",
                "photo_sizes": SIZES_3,
                "caption": CAPTION_STYLE,
            },
        ),
        *[
            (
                f"style of a document ({name})",
                "templates_style_of_document",
                {"doc": doc},
            )
            for name, doc in SAVE_AS_DOCS.items()
        ],
        *[
            (
                f"layout of a document ({name})",
                "templates_layout_of_document",
                {"doc": doc},
            )
            for name, doc in SAVE_AS_DOCS.items()
        ],
    ],
}


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def _call(fn_name: str, args: dict[str, Any]) -> Any:
    fn, converters = FUNCTIONS[fn_name]
    assert set(args) == set(converters), f"{fn_name}: arguments {sorted(args)}"
    return _jsonable(fn(**{k: converters[k](v) for k, v in args.items()}))


def _close(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool) or expected is None or isinstance(expected, str):
        return bool(actual == expected)
    if isinstance(expected, int | float):
        return isinstance(actual, int | float) and math.isclose(
            actual, expected, rel_tol=1e-12, abs_tol=1e-12
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _close(a, e) for a, e in zip(actual, expected, strict=True)
        )
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            _close(actual[k], expected[k]) for k in expected
        )
    return bool(actual == expected)


def _load() -> list[tuple[str, dict[str, Any]]]:
    return [
        (f"{path.name}: {case['name']}", case)
        for path in sorted(FIXTURES.glob("*.json"))
        for case in json.loads(path.read_text())["cases"]
    ]


@pytest.mark.skipif(not os.environ.get("CONFORMANCE_UPDATE"), reason="set CONFORMANCE_UPDATE=1")
def test_update_fixtures() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for filename, cases in CASES.items():
        payload = {
            "description": "Generated by backend/tests/unit/test_conformance.py; checked by pytest "
            "and `pnpm conformance`.",
            "cases": [
                {"name": name, "fn": fn, "input": args, "expected": _call(fn, args)}
                for name, fn, args in cases
            ],
        }
        (FIXTURES / filename).write_text(json.dumps(payload, indent=2) + "\n")


def test_fixtures_cover_all_cases() -> None:
    names = {case_id for case_id, _ in _load()}
    expected = {f"{filename}: {name}" for filename, cases in CASES.items() for name, _, _ in cases}
    assert names == expected, "fixtures out of date: run with CONFORMANCE_UPDATE=1"


@pytest.mark.parametrize(("case_id", "case"), _load(), ids=[c for c, _ in _load()])
def test_python_matches_fixture(case_id: str, case: dict[str, Any]) -> None:
    actual = _call(case["fn"], case["input"])
    assert _close(actual, case["expected"]), f"{case_id}: {actual} != {case['expected']}"
