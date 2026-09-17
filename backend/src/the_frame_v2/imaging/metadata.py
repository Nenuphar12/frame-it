"""EXIF / ICC metadata extraction.

Pixel-independent: reads the EXIF blob exposed by libvips and parses it with Pillow's `Exif`
(works identically for JPEG, PNG and AVIF).
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from PIL import Image, ImageCms

log = logging.getLogger(__name__)

_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
_TAG_MAKE = 0x010F
_TAG_MODEL = 0x0110
_TAG_DATETIME = 0x0132
_TAG_DATETIME_ORIGINAL = 0x9003
_TAG_LENS_MODEL = 0xA434
_WIDE_GAMUT_MARKERS = ("p3", "adobe rgb", "2020", "prophoto", "wide gamut", "rommrgb")


@dataclass(slots=True)
class PhotoMetadata:
    taken_at: datetime | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    lens: str | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None
    icc_description: str | None = None
    is_wide_gamut: bool = False
    location_removed: bool = False
    """GPS block present but zeroed (Android redacts it for apps without media-location access)."""

    @property
    def has_capture_info(self) -> bool:
        return self.taken_at is not None or self.camera_make is not None


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    text = str(value).replace("\x00", "").strip()
    return text[:128] or None


def _parse_datetime(value: Any) -> datetime | None:
    """Capture time as the camera's local wall-clock time.

    Stored with a UTC marker by convention ("floating" time): photo apps show when a photo was
    taken in the local time of the place, so no timezone conversion is ever applied (see
    docs/data-model.md).
    """
    text = _clean_str(value)
    if not text:
        return None
    try:
        naive = datetime.strptime(text[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=UTC)


def _dms_to_degrees(dms: Any, ref: Any) -> float | None:
    try:
        d, m, s = (float(x) for x in dms)
    except TypeError, ValueError, ZeroDivisionError:
        return None
    value = d + m / 60.0 + s / 3600.0
    ref_text = _clean_str(ref) or ""
    if ref_text.upper() in ("S", "W"):
        value = -value
    return value


def parse_exif(blob: bytes | None) -> PhotoMetadata:
    meta = PhotoMetadata()
    if not blob:
        return meta
    exif = Image.Exif()
    try:
        exif.load(blob)
    except Exception:  # malformed EXIF must never fail an import
        log.warning("unparseable EXIF blob", exc_info=True)
        return meta
    meta.camera_make = _clean_str(exif.get(_TAG_MAKE))
    meta.camera_model = _clean_str(exif.get(_TAG_MODEL))
    try:
        exif_ifd = exif.get_ifd(_EXIF_IFD)
    except Exception:
        exif_ifd = {}
    meta.lens = _clean_str(exif_ifd.get(_TAG_LENS_MODEL))
    meta.taken_at = _parse_datetime(exif_ifd.get(_TAG_DATETIME_ORIGINAL) or exif.get(_TAG_DATETIME))
    try:
        gps = exif.get_ifd(_GPS_IFD)
    except Exception:
        gps = {}
    if gps:
        lat = _dms_to_degrees(gps.get(2), gps.get(1))
        lon = _dms_to_degrees(gps.get(4), gps.get(3))
        valid = lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180
        if valid and not (lat == 0.0 and lon == 0.0):  # (0, 0) is a common "no fix" placeholder
            meta.gps_lat, meta.gps_lon = lat, lon
        else:
            meta.location_removed = _is_blank(gps.get(0)) and _is_blank(gps.get(1))
    return meta


def _is_blank(value: Any) -> bool:
    """True for a missing tag or one overwritten with NUL bytes."""
    if value is None:
        return True
    if isinstance(value, str):
        value = value.encode()
    return isinstance(value, bytes) and not value.strip(b"\x00")


def icc_description(icc: bytes | None) -> str | None:
    if not icc:
        return None
    try:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        desc = ImageCms.getProfileDescription(profile)
    except Exception:
        return None
    return _clean_str(desc)


def is_wide_gamut(description: str | None) -> bool:
    if not description:
        return False
    lowered = description.lower()
    return any(marker in lowered for marker in _WIDE_GAMUT_MARKERS)
