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

from the_frame_v2.domain import alternatives, constraints, geometry, placement, quality
from the_frame_v2.domain.constraints import SlotState
from the_frame_v2.domain.geometry import Margins, Orient, Rect, Size
from the_frame_v2.domain.quality import SlotGeometry

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


def _q(rw: int, rh: int, cw: int, ch: int, rot: float = 0, photo: bool = True) -> dict[str, Any]:
    return {
        "rect_w": rw,
        "rect_h": rh,
        "crop_w": cw,
        "crop_h": ch,
        "rotation": rot,
        "has_photo": photo,
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
