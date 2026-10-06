"""Server renderer (authoritative): artwork document → 3840×2160 sRGB image. Spec:
docs/rendering-spec.md §8.1.

The pipeline is lazy (libvips): a region render computes only the pixels it needs. `scale` renders
the same document on a smaller canvas (golden tests, previews); `scale = 1` is the TV render.
Bump `RENDERER_VERSION` whenever output pixels change: it is part of the render hash.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pyvips

from frame_it.domain.document import (
    ArtworkDocument,
    Band,
    Caption,
    EdgeShadow,
    Shadow,
    Slot,
)
from frame_it.domain.geometry import CANVAS_HEIGHT, CANVAS_WIDTH, Rect, round_half_even
from frame_it.imaging.assets import AssetCatalog, FontAsset, catalog
from frame_it.imaging.decode import DecodeError, load_srgb, pixel_count

RENDERER_VERSION = "3"
"""Bump when the **same document** renders to different pixels. A new optional document field is
not that: it changes the document, hence the hash, of the artworks that use it and of no other
(`ArtworkDocument.render_identity`).

2: the shadows of unrotated layers are built from 1-D profiles (`_blurred_box`) — within one
rounding of the 2-D blur they replace, which is still a different pixel here and there.
3: a bevel's right and bottom faces are in shade too (`BEVEL_SHADES`)."""
BEVEL_SHADES = {"top": -0.30, "left": -0.12, "right": -0.12, "bottom": -0.05}
"""How a bevelled band shades its four faces (rendering-spec.md §8.1, step 3.5): a negative value
mixes the band colour towards black, a positive one towards white. Light from above, straight on:
the top face is the darkest, the two sides share one lighter shade and the bottom is barely
shaded — the cut edge of a mat window, as a Frame draws it."""
MIN_BLUR_AMPLITUDE = 0.005
"""Gaussian kernels are truncated below this amplitude (libvips' default 0.2 is visibly clipped)."""
TEXT_MARKER = "|"
_BICUBIC = pyvips.Interpolate.new("bicubic")


class RenderError(Exception):
    """The document cannot be rendered (e.g. a photo file is missing). `code` is a problem code."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(slots=True)
class Rendered:
    image: Any
    """3-band uchar sRGB, lazy (evaluated when saved)."""
    text_boxes: list[Rect] = field(default_factory=list)
    """Canvas-px boxes of rendered captions (golden tests allow larger differences there)."""


PhotoResolver = Callable[[str], Path | None]


# ---- decoded originals (§8.4) ------------------------------------------------------------------
DECODED_CACHE_BYTES = 512 * 1024 * 1024
DECODE_WORKERS = 4
#: Source pixels one render may hold at once, summed over its *distinct* photos.
#:
#: pyvips builds a lazy pipeline, so every decoded original stays resident until the image is
#: written — the 512 MB cache bounds what is *kept*, not what one render holds. Measured on 24 MP
#: JPEGs (`scripts/bench_render.py`): 6 slots peak at 1.6 GB RSS, 9 slots at 2.3 GB. A document may
#: carry 32 slots, which at 48 MP each would ask for roughly 14 GB and be killed rather than
#: refused. 320 Mpx ≈ 1 GB of decoded pixels ≈ 2.5 GB peak, which covers every realistic artwork
#: (13 × 24 MP) and stops the pathological ones with a problem code.
MAX_RENDER_PIXELS = 320_000_000


class _DecodedCache:
    """Recently decoded originals, bounded by memory (render and loupe reuse them)."""

    def __init__(self, max_bytes: int = DECODED_CACHE_BYTES) -> None:
        self._max_bytes = max_bytes
        self._items: OrderedDict[tuple[str, int], Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, path: Path) -> Any:
        """Full-resolution EXIF-oriented sRGB pixels, in memory."""
        try:
            key = (str(path), path.stat().st_mtime_ns)
        except OSError as exc:
            raise RenderError("photo_file_missing", str(path)) from exc
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        try:
            image = load_srgb(path).copy_memory()
        except DecodeError as exc:
            # A corrupt original must leave as a code the UI can translate: a `DecodeError`
            # escaping here reached the activity centre as a raw traceback carrying a server path.
            raise RenderError(exc.code, str(exc)) from exc
        with self._lock:
            self._items[key] = image
            total = sum(i.width * i.height * i.bands for i in self._items.values())
            while total > self._max_bytes and len(self._items) > 1:
                _, evicted = self._items.popitem(last=False)
                total -= evicted.width * evicted.height * evicted.bands
        return image

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


decoded_originals = _DecodedCache()


# ---- helpers ------------------------------------------------------------------------------------
def rgb(color: str) -> list[int]:
    return [int(color[i : i + 2], 16) for i in (1, 3, 5)]


def _solid(width: int, height: int, color: list[int]) -> Any:
    return (
        (pyvips.Image.black(width, height, bands=3) + color)
        .cast("uchar")
        .copy(interpretation="srgb")
    )


def _colored_alpha(alpha: Any, color: str) -> Any:
    """RGBA layer of `color` with the given alpha band (float or uchar)."""
    base = _solid(alpha.width, alpha.height, rgb(color))
    return base.bandjoin(alpha.rint().cast("uchar")).copy(interpretation="srgb")


def _over(base: Any, layer: Any, x: int, y: int) -> Any:
    """Composite `layer` (RGBA) over `base` (RGBA) at (x, y); clipped to `base`."""
    if x >= base.width or y >= base.height or x + layer.width <= 0 or y + layer.height <= 0:
        return base
    return base.composite2(layer, "over", x=x, y=y, compositing_space="srgb")


def _blur(image: Any, sigma: float) -> Any:
    if sigma <= 0:
        return image.cast("float")
    return image.gaussblur(sigma, min_ampl=MIN_BLUR_AMPLITUDE, precision="float")


def _scaled(value: float, scale: float) -> int:
    return int(value) if scale == 1 else round_half_even(value * scale)


def _rotate(
    layer: Any, left: float, top: float, pivot: tuple[float, float], degrees: float
) -> tuple[Any, int, int]:
    """Rotate an RGBA layer whose top-left is at canvas (left, top) around `pivot` (canvas px).

    Continuous coordinates, pixel centres at +0.5; bicubic on premultiplied alpha. Returns the
    rotated layer and its integer canvas position.
    """
    radians = math.radians(degrees)
    cos, sin = math.cos(radians), math.sin(radians)
    px, py = pivot
    corners = [
        (left, top),
        (left + layer.width, top),
        (left, top + layer.height),
        (left + layer.width, top + layer.height),
    ]
    xs = [px + cos * (x - px) - sin * (y - py) for x, y in corners]
    ys = [py + sin * (x - px) + cos * (y - py) for x, y in corners]
    out_left, out_top = math.floor(min(xs)) - 1, math.floor(min(ys)) - 1
    out_w = math.ceil(max(xs)) + 1 - out_left
    out_h = math.ceil(max(ys)) + 1 - out_top
    rotated = layer.premultiply().affine(
        [cos, -sin, sin, cos],
        oarea=[out_left, out_top, out_w, out_h],
        idx=0.5 + left - px,
        idy=0.5 + top - py,
        odx=px - 0.5,
        ody=py - 0.5,
        interpolate=_BICUBIC,
        background=[0, 0, 0, 0],
        extend="background",
    )
    rotated = rotated.unpremultiply().rint().cast("uchar").copy(interpretation="srgb")
    return rotated, out_left, out_top


# ---- pipeline steps -----------------------------------------------------------------------------
def _mat(doc: ArtworkDocument, width: int, height: int, scale: float, assets: AssetCatalog) -> Any:
    """Mat colour plus optional texture: `out = clamp(floor(mat + strength × (t − 128) + 0.5))`."""
    color = rgb(doc.mat.color)
    texture = doc.mat.texture
    if texture is None or texture.strength == 0:
        return _solid(width, height, color)
    asset = assets.textures.get(texture.id)
    if asset is None:
        raise RenderError("unknown_texture", texture.id)
    tile = _texture_tile(str(asset.path))
    if scale != 1:
        tile = tile.resize(scale, kernel="lanczos3")
    tiled = tile.replicate(math.ceil(width / tile.width), math.ceil(height / tile.height))
    delta = (tiled.crop(0, 0, width, height).cast("float") - 128) * texture.strength
    out = ((delta + color) + 0.5).floor()
    return out.clamp(min=0, max=255).cast("uchar").copy(interpretation="srgb")


_tiles: dict[str, Any] = {}
_tiles_lock = threading.Lock()


def _texture_tile(path: str) -> Any:
    with _tiles_lock:
        tile = _tiles.get(path)
        if tile is None:
            tile = pyvips.Image.new_from_file(path).extract_band(0).copy_memory()
            _tiles[path] = tile
        return tile


def _slot_size(slot: Slot, scale: float) -> tuple[int, int]:
    return max(1, _scaled(slot.rect.w, scale)), max(1, _scaled(slot.rect.h, scale))


def _decode_all(doc: ArtworkDocument, resolve: PhotoResolver) -> dict[str, Any]:
    """Decode every original the document needs, in parallel (photo id → pixels).

    Decoding dominates collage renders; all decoded photos are held until the render completes
    (memory ≈ 3 bytes per source pixel per distinct photo).
    """
    paths: dict[str, Path] = {}
    for slot in doc.slots:
        if slot.photo_id is None or slot.photo_id in paths:
            continue
        path = resolve(slot.photo_id)
        if path is None:
            raise RenderError("photo_missing", slot.photo_id)
        paths[slot.photo_id] = path
    if not paths:
        return {}
    try:
        total = sum(pixel_count(path) for path in paths.values())
    except DecodeError as exc:
        # The budget is read before anything is decoded, so this is the first thing to touch the
        # file: a missing or unreadable source has to leave as the `RenderError` the cache would
        # have raised, not as a decode error the renderer's callers do not catch.
        raise RenderError("photo_file_missing", str(exc)) from exc
    if total > MAX_RENDER_PIXELS:
        raise RenderError(
            "render_too_large",
            f"{len(paths)} photos totalling {total / 1e6:.0f} Mpx "
            f"(limit {MAX_RENDER_PIXELS / 1e6:.0f} Mpx)",
        )
    with ThreadPoolExecutor(max_workers=min(DECODE_WORKERS, len(paths))) as pool:
        images = list(pool.map(decoded_originals.get, paths.values()))
    return dict(zip(paths, images, strict=True))


def _slot_photo(slot: Slot, image: Any, scale: float) -> Any:
    """Oriented, cropped (exact integers) and resized photo pixels."""
    orient = slot.source.orient
    if orient.rotate:
        image = image.rot(f"d{orient.rotate}")
    if orient.flip_h:
        image = image.fliphor()
    crop = slot.source.crop
    if crop.x + crop.w > image.width or crop.y + crop.h > image.height:
        raise RenderError("crop_out_of_bounds", slot.id)
    image = image.crop(crop.x, crop.y, crop.w, crop.h)
    width = max(1, _scaled(slot.rect.w, scale))
    height = max(1, _scaled(slot.rect.h, scale))
    if (width, height) != (crop.w, crop.h):
        image = image.resize(width / crop.w, vscale=height / crop.h, kernel="lanczos3")
        image = _force_size(image, width, height)
    return image


def _force_size(image: Any, width: int, height: int) -> Any:
    """Resize rounding can differ by a pixel: crop or extend (copying edges) to the exact size."""
    if (image.width, image.height) == (width, height):
        return image
    image = image.crop(0, 0, min(image.width, width), min(image.height, height))
    if (image.width, image.height) != (width, height):
        image = image.embed(0, 0, width, height, extend="copy")
    return image


def shade(color: str, amount: float) -> list[int]:
    """`color` mixed towards black (`amount < 0`) or white (`amount > 0`), rounded half up."""
    target = 255 if amount > 0 else 0
    share = abs(amount)
    return [math.floor(c + (target - c) * share + 0.5) for c in rgb(color)]


def _bevel(image: Any, width: int, band: Band) -> Any:
    """`image` grown by a bevelled band: four mitred faces, each one flat shade of `band.color`.

    A band pixel belongs to the face whose **outer** edge is nearest. On a diagonal (two edges
    equally near) the top or bottom face wins, so the mitre is one exact pixel staircase and the
    client can draw the same four trapezoids.
    """
    full_w, full_h = image.width + 2 * width, image.height + 2 * width
    xyz = pyvips.Image.xyz(full_w, full_h)
    left, top = xyz[0], xyz[1]
    right, bottom = (full_w - 1) - left, (full_h - 1) - top
    side = (left < right).ifthenelse(left, right)
    faces = (left < right).ifthenelse(
        shade(band.color, BEVEL_SHADES["left"]), shade(band.color, BEVEL_SHADES["right"])
    )
    faces = (bottom <= side).ifthenelse(shade(band.color, BEVEL_SHADES["bottom"]), faces)
    faces = (top <= side).ifthenelse(shade(band.color, BEVEL_SHADES["top"]), faces)
    frame = faces.cast("uchar").copy(interpretation="srgb")
    return frame.insert(image, width, width)


def _blurred_box(
    width: int, height: int, box: tuple[int, int, int, int], sigma: float, crop: Rect | None = None
) -> Any:
    """A box of 1 on a `width × height` field of 0, Gaussian-blurred: float, in [0, 1].

    "Inside a rectangle" is the product of a row and a column, and a Gaussian blur keeps that
    product — so two 1-D blurs and a multiplication give what a 2-D blur of the whole field gives,
    to within a rounding (`tests/unit/test_render.py`). A full-canvas blur costs 0.3 s at
    `blur = 28` and 7 s at 200; this costs milliseconds whatever the radius. `box` is
    `(left, top, w, h)`; `crop` keeps only that part of the field.
    """
    left, top, box_w, box_h = box
    row = pyvips.Image.black(width, 1).draw_rect(255, left, 0, box_w, 1, fill=True)
    column = pyvips.Image.black(1, height).draw_rect(255, 0, top, 1, box_h, fill=True)
    across, down = _blur(row, sigma) / 255, _blur(column, sigma) / 255
    if crop is not None:
        across = across.crop(crop.x, 0, crop.w, 1)
        down = down.crop(0, crop.y, 1, crop.h)
        width, height = crop.w, crop.h
    return across.replicate(1, height) * down.replicate(width, 1)


def _inner_shadow(layer: Any, shadow: Shadow, scale: float) -> Any:
    """Recessed look: blurred inverse mask, shifted by the offset, drawn over photo and bands.

    The mask is 255 outside the layer and 0 inside: one minus a blurred box (`_blurred_box`).
    """
    sigma = shadow.blur * scale / 2
    ox, oy = _scaled(shadow.offset_x, scale), _scaled(shadow.offset_y, scale)
    pad = math.ceil(3 * sigma) + max(abs(ox), abs(oy)) + 1
    width, height = layer.width, layer.height
    inside = _blurred_box(
        width + 2 * pad,
        height + 2 * pad,
        (pad + ox, pad + oy, width, height),
        sigma,
        Rect(pad, pad, width, height),
    )
    alpha = (1 - inside) * (255 * shadow.opacity)
    return layer.composite2(
        _colored_alpha(alpha, shadow.color), "over", compositing_space="srgb"
    ).cast("uchar")


def _drop_shadow(
    canvas: Any, layer: Any, x: int, y: int, shadow: Shadow, scale: float, *, rotated: bool
) -> Any:
    """Raised look: the layer's alpha, blurred and offset, drawn onto the mat.

    An unrotated layer is an opaque rectangle, so its blurred alpha is a blurred box; a rotated
    one has a real alpha band (a tilted rectangle with soft edges) and takes the 2-D blur.
    """
    sigma = shadow.blur * scale / 2
    ox, oy = _scaled(shadow.offset_x, scale), _scaled(shadow.offset_y, scale)
    pad = math.ceil(3 * sigma) + 1
    width, height = layer.width + 2 * pad, layer.height + 2 * pad
    if rotated:
        alpha = _blur(layer.extract_band(3).embed(pad, pad, width, height), sigma) * shadow.opacity
    else:
        box = (pad, pad, layer.width, layer.height)
        alpha = _blurred_box(width, height, box, sigma) * (255 * shadow.opacity)
    return _over(canvas, _colored_alpha(alpha, shadow.color), x - pad + ox, y - pad + oy)


def _draw_slot(canvas: Any, slot: Slot, photo: Any, scale: float) -> Any:
    image = _slot_photo(slot, photo, scale)
    band_total = 0
    for band in slot.bands:
        width = max(1, _scaled(band.width, scale))
        if band.bevel:
            image = _bevel(image, width, band)
        else:
            image = image.embed(
                width,
                width,
                image.width + 2 * width,
                image.height + 2 * width,
                extend="background",
                background=rgb(band.color),
            )
        band_total += width
    layer = image.bandjoin_const(255).copy(interpretation="srgb")
    shadow = slot.shadow
    if shadow is not None and shadow.type == "inner" and shadow.opacity > 0:
        layer = _inner_shadow(layer, shadow, scale)
    if slot.rotation == 0:
        x = _scaled(slot.rect.x, scale) - band_total
        y = _scaled(slot.rect.y, scale) - band_total
    else:
        cx = (slot.rect.x + slot.rect.w / 2) * scale
        cy = (slot.rect.y + slot.rect.h / 2) * scale
        left, top = cx - layer.width / 2, cy - layer.height / 2
        layer, x, y = _rotate(layer, left, top, (cx, cy), slot.rotation)
    if shadow is not None and shadow.type == "drop" and shadow.opacity > 0:
        canvas = _drop_shadow(canvas, layer, x, y, shadow, scale, rotated=slot.rotation != 0)
    return _over(canvas, layer, x, y)


def _edge_shadow(canvas: Any, shadow: EdgeShadow, scale: float) -> Any:
    """The frame's shadow: the inner shadow of the whole canvas, over everything already drawn."""
    as_inner = Shadow(
        type="inner",
        offset_x=shadow.offset_x,
        offset_y=shadow.offset_y,
        blur=shadow.blur,
        color=shadow.color,
        opacity=shadow.opacity,
    )
    return _inner_shadow(canvas, as_inner, scale)


def text_width(markup: str, font_path: str, description: str, spacing_px: float) -> int:
    """Logical advance width of a single line (kerning and letter spacing included).

    libvips crops text images to their ink; rendering the text followed by a marker glyph gives the
    marker's position, hence the advance of the text.
    """
    marker = pyvips.Image.text(TEXT_MARKER, fontfile=font_path, font=description, dpi=72)
    both = pyvips.Image.text(
        markup.replace("</span>", f"{TEXT_MARKER}</span>"),
        fontfile=font_path,
        font=description,
        dpi=72,
    )
    marker_right = marker.get("xoffset") + marker.width
    return int(both.get("xoffset") + both.width - marker_right - round(spacing_px))


def _draw_caption(
    canvas: Any, caption: Caption, scale: float, assets: AssetCatalog
) -> tuple[Any, Rect | None]:
    font: FontAsset | None = assets.fonts.get(caption.font)
    if font is None or caption.weight not in font.weights:
        raise RenderError("unknown_font", f"{caption.font} {caption.weight}")
    size = caption.size * scale
    font_path = str(font.path(caption.weight))
    description = f"{FontAsset.family(caption.font, caption.weight)} {size:.2f}px"
    spacing_units = round(caption.letter_spacing * size * 1024)
    markup = f'<span letter_spacing="{spacing_units}">{escape(caption.text)}</span>'
    ink = pyvips.Image.text(markup, fontfile=font_path, font=description, dpi=72, rgba=True)
    if ink.width <= 1 and ink.height <= 1 and not caption.text.strip():
        return canvas, None
    metrics = font.metrics[caption.weight]
    ascent = math.floor(metrics.ascender * size / metrics.units_per_em + 0.5)
    width = text_width(markup, font_path, description, spacing_units / 1024)
    anchor_offset = {"start": 0.0, "middle": width / 2, "end": float(width)}[caption.anchor]
    pivot = (caption.x * scale, caption.y * scale)
    left = pivot[0] - anchor_offset + ink.get("xoffset")
    top = pivot[1] - ascent + ink.get("yoffset")
    layer = _colored_alpha(ink.extract_band(3), caption.color)
    if caption.rotation == 0:
        x, y = round_half_even(left), round_half_even(top)
    else:
        layer, x, y = _rotate(layer, left, top, pivot, caption.rotation)
    return _over(canvas, layer, x, y), Rect(x, y, layer.width, layer.height)


# ---- entry points -------------------------------------------------------------------------------
def render_document(
    doc: ArtworkDocument,
    resolve: PhotoResolver,
    *,
    scale: float = 1.0,
    region: Rect | None = None,
    assets: AssetCatalog | None = None,
) -> Rendered:
    """Render `doc`; `resolve(photo_id)` gives the original file (None = missing photo).

    Empty slots draw nothing. `region` (output px) crops the result; only that area is computed.
    """
    assets = assets or catalog()
    width = CANVAS_WIDTH if scale == 1 else max(1, round_half_even(CANVAS_WIDTH * scale))
    height = CANVAS_HEIGHT if scale == 1 else max(1, round_half_even(CANVAS_HEIGHT * scale))
    decoded = _decode_all(doc, resolve)
    canvas = _mat(doc, width, height, scale, assets).bandjoin_const(255).copy(interpretation="srgb")
    for slot in doc.slots:
        if slot.photo_id is not None:
            canvas = _draw_slot(canvas, slot, decoded[slot.photo_id], scale)
    boxes: list[Rect] = []
    for caption in doc.captions:
        canvas, box = _draw_caption(canvas, caption, scale, assets)
        if box is not None:
            boxes.append(box)
    if doc.edge_shadow is not None and doc.edge_shadow.opacity > 0:
        canvas = _edge_shadow(canvas, doc.edge_shadow, scale)
    image = canvas.extract_band(0, n=3).cast("uchar").copy(interpretation="srgb")
    assert (image.width, image.height) == (width, height)
    if region is not None:
        left, top = max(0, region.x), max(0, region.y)
        right = min(width, region.x + region.w)
        bottom = min(height, region.y + region.h)
        if right <= left or bottom <= top:
            raise RenderError("region_out_of_canvas")
        image = image.crop(left, top, right - left, bottom - top)
    return Rendered(image, boxes)


def save_png(image: Any, path: Path) -> None:
    """PNG master: compression 6, embedded sRGB profile."""
    image.pngsave(str(path), compression=6, profile="srgb", keep="icc")


def save_jpeg(image: Any, path: Path, quality: int) -> None:
    """JPEG derivative: 4:4:4, optimized Huffman tables, sRGB profile only."""
    image.jpegsave(
        str(path),
        Q=quality,
        subsample_mode="off",
        optimize_coding=True,
        profile="srgb",
        keep="icc",
    )


def png_bytes(image: Any, compression: int = 1) -> bytes:
    data: bytes = image.pngsave_buffer(compression=compression, profile="srgb", keep="icc")
    return data
