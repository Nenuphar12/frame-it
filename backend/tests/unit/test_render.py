"""Renderer properties (docs/rendering-spec.md §8.1). Pixel-level references: tests/golden."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import pyvips

from the_frame_v2.domain.document import ArtworkDocument
from the_frame_v2.domain.geometry import Rect
from the_frame_v2.imaging.decode import load_srgb
from the_frame_v2.imaging.render import decoded_originals, render_document, rgb


def synthetic(path: Path, width: int, height: int) -> Path:
    """Deterministic colourful PNG (no JPEG: encoders differ between libvips builds)."""
    xy = pyvips.Image.xyz(width, height)
    r = xy[0] * 255 / max(1, width - 1)
    g = xy[1] * 255 / max(1, height - 1)
    b = (xy[0] * 7 + xy[1] * 13) % 256
    image = r.bandjoin([g, b]).cast("uchar").copy(interpretation="srgb")
    image.pngsave(str(path))
    decoded_originals.clear()
    return path


def pixels(image: Any) -> bytes:
    data: bytes = image.write_to_memory()
    return data


def single(photo_size: tuple[int, int], **slot: Any) -> ArtworkDocument:
    w, h = photo_size
    base: dict[str, Any] = {
        "id": "s1",
        "photo_id": "p",
        "rect": {"x": 0, "y": 0, "w": w, "h": h},
        "source": {"crop": {"x": 0, "y": 0, "w": w, "h": h}},
        "quality_lock": "free",
    }
    base.update(slot)
    return ArtworkDocument.model_validate({"schema": 1, "placement": "manual", "slots": [base]})


@pytest.fixture
def uhd(tmp_path: Path) -> Path:
    return synthetic(tmp_path / "uhd.png", 3840, 2160)


def test_native_uhd_photo_is_bit_identical_to_its_decode(uhd: Path) -> None:
    doc = single((3840, 2160), quality_lock="native")
    assert doc.quality().worst_tier == "native"
    rendered = render_document(doc, {"p": uhd}.get).image
    assert (rendered.width, rendered.height, rendered.bands) == (3840, 2160, 3)
    assert pixels(rendered) == pixels(load_srgb(uhd))


def test_region_render_equals_crop_of_full_render(tmp_path: Path) -> None:
    photo = synthetic(tmp_path / "p.png", 1200, 900)
    doc = single(
        (1200, 900),
        rect={"x": 1000, "y": 500, "w": 1600, "h": 1200},
        rotation=8,
        bands=[{"width": 20, "color": "#FFFFFF"}],
        shadow={"type": "drop", "offset_x": 10, "offset_y": 20, "blur": 30, "opacity": 0.4},
    )
    full = render_document(doc, {"p": photo}.get).image
    region = Rect(900, 1500, 512, 512)
    part = render_document(doc, {"p": photo}.get, region=region).image
    assert pixels(part) == pixels(full.crop(900, 1500, 512, 512))


def test_rotation_by_180_equals_flipped_slot(tmp_path: Path) -> None:
    photo = synthetic(tmp_path / "p.png", 400, 300)
    rect = {"x": 1000, "y": 700, "w": 400, "h": 300}
    straight = render_document(single((400, 300), rect=rect), {"p": photo}.get).image
    turned = render_document(single((400, 300), rect=rect, rotation=180), {"p": photo}.get).image
    area = (1000, 700, 400, 300)
    assert pixels(turned.crop(*area)) == pixels(straight.crop(*area).rot("d180"))
    assert pixels(turned.crop(0, 0, 900, 900)) == pixels(straight.crop(0, 0, 900, 900))


def test_orient_rotate_and_flip(tmp_path: Path) -> None:
    photo = synthetic(tmp_path / "p.png", 300, 200)
    doc = single(
        (200, 300),
        rect={"x": 0, "y": 0, "w": 200, "h": 300},
        source={
            "orient": {"rotate": 90, "flip_h": True},
            "crop": {"x": 0, "y": 0, "w": 200, "h": 300},
        },
        quality_lock="native",
    )
    rendered = render_document(doc, {"p": photo}.get).image.crop(0, 0, 200, 300)
    expected = load_srgb(photo).rot("d90").fliphor()
    assert pixels(rendered) == pixels(expected)


def test_texture_formula_and_bands(tmp_path: Path) -> None:
    photo = synthetic(tmp_path / "p.png", 100, 100)
    doc = ArtworkDocument.model_validate(
        {
            "schema": 1,
            "placement": "manual",
            "mat": {"color": "#808080", "texture": {"id": "paper-01", "strength": 0.5}},
            "slots": [
                {
                    "id": "s",
                    "photo_id": "p",
                    "rect": {"x": 200, "y": 200, "w": 100, "h": 100},
                    "source": {"crop": {"x": 0, "y": 0, "w": 100, "h": 100}},
                    "quality_lock": "native",
                    "bands": [{"width": 3, "color": "#FF0000"}, {"width": 2, "color": "#0000FF"}],
                }
            ],
        }
    )
    image = render_document(doc, {"p": photo}.get).image
    tile = pyvips.Image.new_from_file(
        str(Path(__file__).resolve().parents[2] / "src/the_frame_v2/assets/textures/paper-01.png")
    )
    for x, y in ((0, 0), (17, 1023), (1030, 5)):
        t = tile(x % 1024, y % 1024)[0]
        expected = min(255, max(0, int((128 + 0.5 * (t - 128) + 0.5) // 1)))
        assert image(x, y) == [expected] * 3
    assert image(197, 250) == rgb("#FF0000")  # inner band: 3 px around the photo
    assert image(195, 250) == rgb("#0000FF")  # outer band: 2 more px
    assert image(200, 200) == load_srgb(photo)(0, 0)


def test_shadows_darken_expected_sides(tmp_path: Path) -> None:
    photo = synthetic(tmp_path / "p.png", 10, 10)
    white = pyvips.Image.black(400, 400, bands=3) + 255
    white.cast("uchar").copy(interpretation="srgb").pngsave(str(photo))
    decoded_originals.clear()
    rect = {"x": 1000, "y": 800, "w": 400, "h": 400}
    crop = {"x": 0, "y": 0, "w": 400, "h": 400}
    inner = render_document(
        single(
            (400, 400),
            rect=rect,
            source={"crop": crop},
            shadow={"type": "inner", "offset_y": 10, "blur": 20, "opacity": 0.5},
        ),
        {"p": photo}.get,
    ).image
    top, bottom = inner(1200, 801)[0], inner(1200, 1198)[0]
    assert top < 200  # top edge shaded (light from above, recessed)
    assert bottom > top + 30  # the offset moves the shadow away from the bottom edge
    assert inner(1200, 1000)[0] == 255  # centre untouched
    drop = render_document(
        single(
            (400, 400),
            rect=rect,
            source={"crop": crop},
            shadow={"type": "drop", "offset_y": 20, "blur": 20, "opacity": 0.5},
        ),
        {"p": photo}.get,
    ).image
    mat = rgb("#F2EFE8")
    assert drop(1200, 1210)[0] < mat[0] - 20  # below the slot: shadow on the mat
    assert drop(1200, 790) == mat  # above: nothing
    assert drop(1200, 1000) == [255, 255, 255]


def test_caption_sits_on_its_baseline() -> None:
    doc = ArtworkDocument.model_validate(
        {
            "schema": 1,
            "placement": "manual",
            "mat": {"color": "#FFFFFF"},
            "captions": [
                {
                    "id": "c",
                    "text": "HHHH",
                    "font": "inter",
                    "weight": 500,
                    "size": 100,
                    "color": "#000000",
                    "x": 1920,
                    "y": 1000,
                    "anchor": "middle",
                }
            ],
        }
    )
    rendered = render_document(doc, lambda _: None)
    (box,) = rendered.text_boxes
    ink = rendered.image.extract_band(0) < 128
    rows = [y for y in range(box.y, box.y + box.h) if ink.crop(box.x, y, box.w, 1).max() > 0]
    assert abs(rows[-1] - 999) <= 1  # flat glyph bottoms end on the baseline row
    assert abs((box.x + box.x + box.w) / 2 - 1920) <= 6  # centred on the anchor (side bearings)
    cap_height = rows[-1] - rows[0] + 1
    assert 70 <= cap_height <= 75  # Inter cap height ≈ 0.727 em


def test_missing_photo_fails_cleanly(tmp_path: Path) -> None:
    from the_frame_v2.imaging.render import RenderError

    doc = single((10, 10))
    with pytest.raises(RenderError) as info:
        render_document(doc, lambda _: None)
    assert info.value.code == "photo_missing"
    with pytest.raises(RenderError):
        render_document(doc, {"p": tmp_path / "nope.png"}.get)


def test_scaled_render_size(tmp_path: Path) -> None:
    photo = synthetic(tmp_path / "p.png", 600, 400)
    image = render_document(
        single((600, 400), rect={"x": 0, "y": 0, "w": 3840, "h": 2560}),
        {"p": photo}.get,
        scale=0.25,
    ).image
    assert (image.width, image.height) == (960, 540)
