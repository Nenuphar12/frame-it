"""Renderer properties (docs/rendering-spec.md §8.1). Pixel-level references: tests/golden."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
import pyvips

from frame_it.domain.document import ArtworkDocument, EdgeShadow, Shadow
from frame_it.domain.geometry import Rect
from frame_it.imaging.decode import load_srgb
from frame_it.imaging.render import (
    BEVEL_SHADES,
    _blur,
    _colored_alpha,
    _drop_shadow,
    _edge_shadow,
    _inner_shadow,
    decoded_originals,
    render_document,
    rgb,
    shade,
)


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
        str(Path(__file__).resolve().parents[2] / "src/frame_it/assets/textures/paper-01.png")
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


def test_a_bevelled_band_is_four_mitred_faces(tmp_path: Path) -> None:
    """Each face one flat shade of the band's colour; the top and bottom ones own the mitres."""
    photo = synthetic(tmp_path / "p.png", 100, 60)
    doc = single(
        (100, 60),
        rect={"x": 200, "y": 300, "w": 100, "h": 60},
        quality_lock="native",
        bands=[{"width": 10, "color": "#C0C0C0", "bevel": True}],
    )
    image = render_document(doc, {"p": photo}.get).image
    face = {name: shade("#C0C0C0", amount) for name, amount in BEVEL_SHADES.items()}
    assert face["top"] < face["left"] == face["right"] < face["bottom"] < rgb("#C0C0C0")
    assert image(250, 295) == face["top"]
    assert image(250, 365) == face["bottom"]
    assert image(195, 330) == face["left"]
    assert image(305, 330) == face["right"]
    # the corners: on the diagonal and above it the top face, below it the side one
    assert image(193, 293) == face["top"]
    assert image(194, 293) == face["top"]
    assert image(193, 294) == face["left"]
    assert image(306, 293) == face["top"]
    assert image(193, 366) == face["bottom"]
    assert image(306, 365) == face["right"]
    # the band grows outwards: the photo is where it was, the mat starts 10 px out
    assert image(200, 300) == load_srgb(photo)(0, 0)
    assert image(189, 330) == rgb("#F2EFE8")


def test_a_flat_band_is_unchanged_by_the_bevel_option(tmp_path: Path) -> None:
    photo = synthetic(tmp_path / "p.png", 100, 60)
    rect = {"x": 200, "y": 300, "w": 100, "h": 60}
    plain = single((100, 60), rect=rect, bands=[{"width": 10, "color": "#C0C0C0"}])
    explicit = single(
        (100, 60), rect=rect, bands=[{"width": 10, "color": "#C0C0C0", "bevel": False}]
    )
    resolve = {"p": photo}.get
    assert pixels(render_document(plain, resolve).image) == pixels(
        render_document(explicit, resolve).image
    )


def test_the_edge_shadow_falls_from_the_frame_onto_everything(uhd: Path) -> None:
    """The inner shadow of the whole canvas, drawn last: it darkens a full-bleed photo too."""
    base = single((3840, 2160), quality_lock="native")
    edge = {"offset_x": 0, "offset_y": 12, "blur": 40, "color": "#000000", "opacity": 0.5}
    shaded = ArtworkDocument.model_validate({**base.canonical(), "edge_shadow": edge})
    resolve = {"p": uhd}.get
    plain, dark = render_document(base, resolve).image, render_document(shaded, resolve).image
    for x in (400, 1920, 3400):
        assert sum(dark(x, 2)) < sum(plain(x, 2)) * 0.7  # the top edge, under the frame
        assert dark(x, 1080) == plain(x, 1080)  # the middle of the picture is untouched
    # light from above: the bottom edge keeps far more of its light than the top one
    top = sum(dark(1920, 1)) / sum(plain(1920, 1))
    bottom = sum(dark(1920, 2158)) / sum(plain(1920, 2158))
    assert bottom > top + 0.2
    # an invisible shadow costs nothing and changes nothing
    off = ArtworkDocument.model_validate(
        {**base.canonical(), "edge_shadow": {**edge, "opacity": 0}}
    )
    region = Rect(0, 0, 600, 300)
    assert pixels(render_document(off, resolve, region=region).image) == pixels(
        render_document(base, resolve, region=region).image
    )


SHADOW_SHAPES = [
    {"offset_x": 0, "offset_y": 10, "blur": 60, "color": "#000000", "opacity": 0.22},
    {"offset_x": -30, "offset_y": 45, "blur": 24, "color": "#402000", "opacity": 0.8},
    {"offset_x": 7, "offset_y": 0, "blur": 0, "color": "#000000", "opacity": 1.0},
    {"offset_x": 0, "offset_y": 6, "blur": 28, "color": "#000000", "opacity": 0.45},
]


def _layer(width: int, height: int) -> Any:
    image = (pyvips.Image.black(width, height, bands=3) + [200, 180, 160]).cast("uchar")
    return image.copy(interpretation="srgb").bandjoin_const(255)


@pytest.mark.parametrize("shape", SHADOW_SHAPES)
def test_an_inner_shadow_is_the_2d_blur_of_its_mask(shape: dict[str, Any]) -> None:
    """`_blurred_box` — two 1-D profiles — against the 2-D blur the spec describes (§8.1, 3.6)."""
    layer = _layer(640, 360)
    shadow = Shadow(type="inner", **shape)
    sigma = shadow.blur / 2
    pad = math.ceil(3 * sigma) + max(abs(shadow.offset_x), abs(shadow.offset_y)) + 1
    mask = pyvips.Image.black(640 + 2 * pad, 360 + 2 * pad) + 255
    mask = mask.draw_rect(0, pad + shadow.offset_x, pad + shadow.offset_y, 640, 360, fill=True)
    alpha = _blur(mask, sigma).crop(pad, pad, 640, 360) * shadow.opacity
    reference = layer.composite2(
        _colored_alpha(alpha, shadow.color), "over", compositing_space="srgb"
    ).cast("uchar")
    fast = _inner_shadow(layer, shadow, 1.0)
    assert (fast.cast("int") - reference.cast("int")).abs().max() <= 1
    # the frame's shadow is the same thing with the canvas as the layer
    edge = _edge_shadow(layer, EdgeShadow(**shape), 1.0)
    assert pixels(edge) == pixels(fast)


@pytest.mark.parametrize("shape", SHADOW_SHAPES)
def test_a_drop_shadow_takes_the_fast_path_only_for_a_plain_rectangle(
    shape: dict[str, Any],
) -> None:
    """An unrotated layer's alpha is a box, so both paths must give the same shadow (3.8)."""
    canvas = _layer(900, 600)
    layer = _layer(400, 240)
    shadow = Shadow(type="drop", **shape)
    slow = _drop_shadow(canvas, layer, 250, 180, shadow, 1.0, rotated=True)
    fast = _drop_shadow(canvas, layer, 250, 180, shadow, 1.0, rotated=False)
    assert (fast.cast("int") - slow.cast("int")).abs().max() <= 1


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
    from frame_it.imaging.render import RenderError

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
