"""Golden images (very light, docs/PLAN.md §13.4).

Seven references at canvas scale 0.25 plus one at full size. Tolerances: mean absolute error ≤ 0.5 and max
channel difference ≤ 8 (≤ 32 inside caption boxes). Regenerate after an intended rendering change with
`make golden-update`, look at the new PNGs, and bump `RENDERER_VERSION`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import pyvips

from frame_it.domain.document import ArtworkDocument
from frame_it.domain.geometry import Rect
from frame_it.imaging.render import decoded_originals, render_document

REFS = Path(__file__).parent / "refs"
UPDATE = bool(os.environ.get("GOLDEN_UPDATE"))
MAX_MAE = 0.5
MAX_DIFF = 8
MAX_TEXT_DIFF = 32


def _photo(path: Path, width: int, height: int, hue: int) -> Path:
    """Smooth gradients + a checkerboard (edges reveal resampling changes). Lossless PNG."""
    xy = pyvips.Image.xyz(width, height)
    x, y = xy[0], xy[1]
    r = x * 200 / width + 30
    g = y * 180 / height + 40
    b = (x + y) * 120 / (width + height) + hue
    checker = (((x / 80).floor() + (y / 80).floor()) % 2) * 40
    image = (r + checker).bandjoin([g + checker, b]).clamp(min=0, max=255).cast("uchar")
    image.copy(interpretation="srgb").pngsave(str(path))
    return path


@pytest.fixture(scope="module")
def photos(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("golden")
    decoded_originals.clear()
    return {
        "land": _photo(root / "land.png", 1500, 1000, 60),
        "port": _photo(root / "port.png", 900, 1200, 100),
        "square": _photo(root / "square.png", 800, 800, 20),
        "uhd": _photo(root / "uhd.png", 3840, 2160, 80),
    }


def _slot(
    slot_id: str,
    photo: str,
    rect: tuple[int, int, int, int],
    crop: tuple[int, int, int, int],
    **extra: Any,
) -> dict[str, Any]:
    x, y, w, h = rect
    cx, cy, cw, ch = crop
    return {
        "id": slot_id,
        "photo_id": photo,
        "rect": {"x": x, "y": y, "w": w, "h": h},
        "source": {"crop": {"x": cx, "y": cy, "w": cw, "h": ch}},
        "quality_lock": "free",
        **extra,
    }


CASES: dict[str, tuple[float, dict[str, Any]]] = {
    "native_single": (
        1.0,
        {
            "placement": "fit_in_mat",
            "mat": {"color": "#000000"},
            "slots": [
                _slot("s1", "uhd", (0, 0, 3840, 2160), (0, 0, 3840, 2160), quality_lock="native")
            ],
        },
    ),
    "fit_in_mat_texture": (
        0.25,
        {
            "placement": "fit_in_mat",
            "mat": {"color": "#E4DCCD", "texture": {"id": "linen-01", "strength": 0.55}},
            "margins": {"top": 260, "right": 280, "bottom": 300, "left": 280},
            "slots": [
                _slot(
                    "s1",
                    "land",
                    (675, 260, 2490, 1660),
                    (0, 0, 1500, 1000),
                    bands=[{"width": 12, "color": "#F6F2EA"}],
                )
            ],
        },
    ),
    "recessed": (
        0.25,
        {
            "placement": "fit_in_mat",
            "mat": {"color": "#F2EFE8", "texture": {"id": "paper-01", "strength": 0.35}},
            "slots": [
                _slot(
                    "s1",
                    "port",
                    (1245, 280, 1200, 1600),
                    (0, 0, 900, 1200),
                    shadow={
                        "type": "inner",
                        "offset_x": 0,
                        "offset_y": 6,
                        "blur": 28,
                        "color": "#000000",
                        "opacity": 0.45,
                    },
                )
            ],
        },
    ),
    "raised": (
        0.25,
        {
            "placement": "fit_in_mat",
            "mat": {"color": "#E9E6DF"},
            "slots": [
                _slot(
                    "s1",
                    "land",
                    (820, 380, 2200, 1467),
                    (0, 0, 1500, 1000),
                    bands=[{"width": 20, "color": "#FBFAF7"}, {"width": 4, "color": "#222222"}],
                    shadow={
                        "type": "drop",
                        "offset_x": 0,
                        "offset_y": 14,
                        "blur": 44,
                        "color": "#000000",
                        "opacity": 0.32,
                    },
                )
            ],
        },
    ),
    "rotated_collage": (
        0.25,
        {
            "placement": "manual",
            "mat": {"color": "#D8D2C6"},
            "slots": [
                _slot(
                    "s1",
                    "land",
                    (240, 500, 1800, 1200),
                    (0, 0, 1500, 1000),
                    rotation=-7,
                    bands=[{"width": 30, "color": "#FFFFFF"}],
                    shadow={
                        "type": "drop",
                        "offset_x": 6,
                        "offset_y": 16,
                        "blur": 40,
                        "opacity": 0.35,
                    },
                ),
                _slot(
                    "s2",
                    "port",
                    (2100, 250, 1200, 1600),
                    (0, 0, 900, 1200),
                    rotation=5,
                    bands=[{"width": 30, "color": "#FFFFFF"}],
                    shadow={
                        "type": "drop",
                        "offset_x": 6,
                        "offset_y": 16,
                        "blur": 40,
                        "opacity": 0.35,
                    },
                ),
                _slot(
                    "s3",
                    "square",
                    (1400, 700, 1300, 1300),
                    (0, 0, 800, 800),
                    rotation=-2.5,
                    bands=[{"width": 30, "color": "#FFFFFF"}],
                    shadow={
                        "type": "drop",
                        "offset_x": 6,
                        "offset_y": 16,
                        "blur": 40,
                        "opacity": 0.35,
                    },
                    source={
                        "orient": {"rotate": 90, "flip_h": True},
                        "crop": {"x": 0, "y": 0, "w": 800, "h": 800},
                    },
                ),
            ],
        },
    ),
    "bevelled_mat": (
        0.25,
        {
            "placement": "fit_in_mat",
            "mat": {"color": "#EFF1EF", "texture": {"id": "canvas-01", "strength": 0.3}},
            "margins": {"top": 300, "right": 340, "bottom": 300, "left": 340},
            "slots": [
                _slot(
                    "s1",
                    "land",
                    (750, 300, 2340, 1560),
                    (0, 0, 1500, 1000),
                    bands=[{"width": 12, "color": "#EFF1EF", "bevel": True}],
                )
            ],
            "edge_shadow": {
                "offset_x": 0,
                "offset_y": 10,
                "blur": 60,
                "color": "#000000",
                "opacity": 0.22,
            },
        },
    ),
    "edge_shadow_full_bleed": (
        0.25,
        {
            "placement": "manual",
            "mat": {"color": "#000000"},
            "slots": [_slot("s1", "uhd", (0, 0, 3840, 2160), (0, 0, 3840, 2160))],
            "edge_shadow": {
                "offset_x": 24,
                "offset_y": 40,
                "blur": 160,
                "color": "#1A0E00",
                "opacity": 0.6,
            },
        },
    ),
    "caption": (
        0.25,
        {
            "placement": "manual",
            "mat": {"color": "#F7F7F4"},
            "slots": [_slot("s1", "square", (1370, 200, 1100, 1100), (0, 0, 800, 800))],
            "captions": [
                {
                    "id": "c1",
                    "text": "Kyoto — April 2026",
                    "font": "cormorant-garamond",
                    "weight": 500,
                    "size": 120,
                    "color": "#3A3A3A",
                    "letter_spacing": 0.05,
                    "x": 1920,
                    "y": 1560,
                    "anchor": "middle",
                },
                {
                    "id": "c2",
                    "text": "Arashiyama",
                    "font": "inter",
                    "weight": 300,
                    "size": 80,
                    "color": "#6B5B4B",
                    "letter_spacing": 0.2,
                    "x": 3600,
                    "y": 2000,
                    "anchor": "end",
                    "rotation": -8,
                },
            ],
        },
    ),
}


def _compare(name: str, image: Any, text_boxes: list[Rect]) -> None:
    ref_path = REFS / f"{name}.png"
    if UPDATE:
        REFS.mkdir(parents=True, exist_ok=True)
        image.pngsave(str(ref_path), compression=9, keep="none")
        pytest.skip(f"updated {ref_path.name}")
    assert ref_path.exists(), f"missing reference {ref_path.name}: run `make golden-update`"
    ref = pyvips.Image.new_from_file(str(ref_path))
    assert (ref.width, ref.height, ref.bands) == (image.width, image.height, image.bands)
    diff = (image.cast("int") - ref.cast("int")).abs()
    mae = diff.avg()
    mask = pyvips.Image.black(image.width, image.height)
    for box in text_boxes:
        mask = mask.draw_rect(255, box.x - 2, box.y - 2, box.w + 4, box.h + 4, fill=True)
    outside_text = (mask == 0).ifthenelse(diff, 0).max()
    inside_text = (mask > 0).ifthenelse(diff, 0).max()
    assert mae <= MAX_MAE, f"{name}: mean absolute error {mae:.3f}"
    assert outside_text <= MAX_DIFF, f"{name}: max difference {outside_text}"
    assert inside_text <= MAX_TEXT_DIFF, f"{name}: max difference in text {inside_text}"


@pytest.mark.parametrize("name", list(CASES))
def test_golden(name: str, photos: dict[str, Path]) -> None:
    scale, document = CASES[name]
    doc = ArtworkDocument.model_validate({"schema": 1, **document})
    rendered = render_document(doc, photos.get, scale=scale)
    _compare(name, rendered.image.copy_memory(), rendered.text_boxes)
