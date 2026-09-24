"""Decoding originals into oriented 8-bit sRGB. Spec: docs/rendering-spec.md §8.3.

All pixel access to originals goes through this module (single seam for future formats).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyvips

from the_frame_v2.imaging.metadata import PhotoMetadata, icc_description, is_wide_gamut, parse_exif
from the_frame_v2.imaging.sniff import Sniffed, sniff_file

PROXY_LONG_EDGE = 2560
THUMB_SIZES = (256, 768)
_ROTATING_ORIENTATIONS = {5, 6, 7, 8}


class DecodeError(Exception):
    """Unreadable or unsupported image. `code` is a stable problem code."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(slots=True)
class ProbeResult:
    sniffed: Sniffed
    width: int
    """Width after EXIF orientation."""
    height: int
    orientation: int
    bit_depth: int
    has_alpha: bool
    has_gain_map: bool
    metadata: PhotoMetadata = field(default_factory=PhotoMetadata)


def _get_optional(image: Any, name: str) -> Any:
    return image.get(name) if image.get_typeof(name) != 0 else None


def probe(path: Path, max_pixels: int) -> ProbeResult:
    """Read headers and metadata only (no full decode)."""
    sniffed = sniff_file(path)
    if sniffed.kind in ("heic", "heif"):
        raise DecodeError("unsupported_format_heic", "HEIC/HEIF photos are not supported")
    if not sniffed.supported:
        raise DecodeError("unsupported_format", f"Unsupported format: {sniffed.kind}")
    try:
        image = pyvips.Image.new_from_file(str(path), access="sequential")
    except pyvips.Error as exc:
        raise DecodeError("corrupt_image", str(exc).splitlines()[0]) from exc
    width, height = int(image.width), int(image.height)
    if width * height > max_pixels:
        raise DecodeError("image_too_large", f"{width}x{height} exceeds the pixel limit")
    orientation = _get_optional(image, "orientation") or 1
    if orientation in _ROTATING_ORIENTATIONS:
        width, height = height, width
    fmt = str(image.format)
    bit_depth = 16 if fmt in ("ushort", "short") else 8
    bits_per_sample = _get_optional(image, "bits-per-sample")
    if isinstance(bits_per_sample, int) and bits_per_sample > 8:
        bit_depth = bits_per_sample
    fields = image.get_fields()
    meta = parse_exif(_get_optional(image, "exif-data"))
    meta.icc_description = icc_description(_get_optional(image, "icc-profile-data"))
    meta.is_wide_gamut = is_wide_gamut(meta.icc_description)
    return ProbeResult(
        sniffed=sniffed,
        width=width,
        height=height,
        orientation=int(orientation),
        bit_depth=bit_depth,
        has_alpha=bool(image.hasalpha()),
        has_gain_map=any("gainmap" in f for f in fields),
        metadata=meta,
    )


def _to_srgb8(image: Any) -> Any:
    """Colour-manage to sRGB, drop alpha (flatten on white) and cast to 8-bit, 3 bands."""
    if image.get_typeof("icc-profile-data") != 0:
        try:
            image = image.icc_transform("srgb", embedded=True, intent="perceptual")
        except pyvips.Error:
            image = image.colourspace("srgb")
    elif image.interpretation == "cmyk":
        image = image.icc_transform("srgb", input_profile="cmyk", intent="perceptual")
    if image.hasalpha():
        max_alpha = 65535 if image.format == "ushort" else 255
        image = image.flatten(background=[max_alpha] * (image.bands - 1))
    if image.interpretation != "srgb" or image.format != "uchar":
        image = image.colourspace("srgb")
    if image.bands == 1:
        image = image.bandjoin([image, image])
    elif image.bands > 3:
        image = image.extract_band(0, n=3)
    return image.cast("uchar")


def pixel_count(path: Path) -> int:
    """Source pixels, read from the header — no pixels are decoded.

    A renderer holding every original of a document at once needs to know the bill before it runs
    up: this is what lets it refuse rather than be killed (`imaging/render.py`, §8.5).
    """
    try:
        image = pyvips.Image.new_from_file(str(path), access="sequential")
        return int(image.width) * int(image.height)
    except pyvips.Error as exc:
        raise DecodeError("corrupt_image", str(exc).splitlines()[0]) from exc


def load_srgb(path: Path) -> Any:
    """Full-resolution original, EXIF-oriented, 8-bit sRGB, 3 bands (for rendering)."""
    try:
        image = pyvips.Image.new_from_file(str(path), fail_on="error").autorot()
        return _to_srgb8(image)
    except pyvips.Error as exc:
        raise DecodeError("corrupt_image", str(exc).splitlines()[0]) from exc


def make_proxy(path: Path, long_edge: int = PROXY_LONG_EDGE) -> Any:
    """Downsized oriented sRGB image (shrink-on-load when the format allows it). Never upsizes."""
    try:
        image = pyvips.Image.thumbnail(str(path), long_edge, height=long_edge, size="down")
        return _to_srgb8(image)
    except pyvips.Error as exc:
        raise DecodeError("corrupt_image", str(exc).splitlines()[0]) from exc


def resize_long_edge(image: Any, long_edge: int) -> Any:
    scale = long_edge / max(image.width, image.height)
    if scale >= 1:
        return image
    return image.resize(scale, kernel="lanczos3")


def write_proxy_and_thumbs(path: Path, proxy_path: Path, thumb_paths: dict[int, Path]) -> None:
    proxy_path.parent.mkdir(parents=True, exist_ok=True)
    proxy = make_proxy(path).copy_memory()
    proxy.jpegsave(str(proxy_path), Q=90, optimize_coding=True, keep="none")
    for size, thumb_path in thumb_paths.items():
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        resize_long_edge(proxy, size).webpsave(str(thumb_path), Q=82, keep="none")
