"""Runtime detection of image-processing capabilities (used by startup checks and `doctor`)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import cache

import pyvips


@dataclass(frozen=True, slots=True)
class ImagingCapabilities:
    libvips_version: str
    jpeg: bool
    png: bool
    webp_save: bool
    avif: bool
    ultra_hdr: bool
    color_management: bool

    @property
    def missing_required(self) -> list[str]:
        required = {
            "jpeg": self.jpeg,
            "png": self.png,
            "webp_save": self.webp_save,
            "avif": self.avif,
            "color_management": self.color_management,
        }
        return [name for name, ok in required.items() if not ok]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _has_operation(name: str) -> bool:
    try:
        pyvips.Operation.new_from_name(name)
    except pyvips.Error:
        return False
    return True


def _probe(fn: object) -> bool:
    try:
        fn()  # type: ignore[operator]
    except pyvips.Error:
        return False
    return True


@cache
def detect() -> ImagingCapabilities:
    sample = (pyvips.Image.black(16, 16, bands=3) + [180, 120, 60]).cast("uchar")

    def avif_roundtrip() -> None:
        data = sample.heifsave_buffer(compression="av1", Q=80)
        pyvips.Image.new_from_buffer(data, "").avg()

    def icc() -> None:
        sample.icc_transform("srgb", input_profile="p3").avg()

    def webp() -> None:
        sample.webpsave_buffer(Q=80)

    return ImagingCapabilities(
        libvips_version=f"{pyvips.version(0)}.{pyvips.version(1)}.{pyvips.version(2)}",
        jpeg=_has_operation("jpegload") and _has_operation("jpegsave"),
        png=_has_operation("pngload") and _has_operation("pngsave"),
        webp_save=_probe(webp),
        avif=_has_operation("heifload") and _probe(avif_roundtrip),
        ultra_hdr=_has_operation("uhdrload"),
        color_management=_probe(icc),
    )
