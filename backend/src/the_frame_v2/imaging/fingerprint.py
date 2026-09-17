"""Content fingerprint: identifies the same photo across copies whose EXIF differs.

Android zeroes GPS tags for apps without media-location access (browsers), so a web upload and a
USB/LocalSend copy of one photo have different SHA-256 but identical image data. For JPEG the
fingerprint is the SHA-256 of the file with its EXIF APP1 segments skipped (XMP, ICC, MPF and the
Motion Photo payload are kept). Other formats: the file SHA-256. Spec: docs/data-model.md.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO

_READ = 4 * 1024 * 1024
_EXIF_HEADER = b"Exif\x00\x00"
_SOS = 0xDA
_EOI = 0xD9
_STANDALONE = {0x01, *range(0xD0, 0xD8)}  # TEM, RSTn: no length field


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        _copy(fh, digest)
    return digest.hexdigest()


def content_fingerprint(path: Path, kind: str) -> str:
    if kind != "jpeg":
        return file_sha256(path)
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        if not _hash_jpeg_headers(fh, digest):
            fh.seek(0)
            return _whole(fh)
        _copy(fh, digest)
    return digest.hexdigest()


def _hash_jpeg_headers(fh: BinaryIO, digest: hashlib._Hash) -> bool:
    """Hash marker segments up to SOS, skipping EXIF APP1. False if the stream is not a JPEG."""
    if fh.read(2) != b"\xff\xd8":
        return False
    digest.update(b"\xff\xd8")
    while True:
        marker = fh.read(2)
        if len(marker) < 2 or marker[0] != 0xFF:
            return False
        code = marker[1]
        if code == 0xFF:  # fill byte: step one byte forward
            fh.seek(-1, 1)
            continue
        if code in _STANDALONE:
            digest.update(marker)
            continue
        if code == _EOI:
            digest.update(marker)
            return True
        length_bytes = fh.read(2)
        if len(length_bytes) < 2:
            return False
        length = int.from_bytes(length_bytes, "big")
        if length < 2:
            return False
        payload = fh.read(length - 2)
        if len(payload) < length - 2:
            return False
        if code == 0xE1 and payload.startswith(_EXIF_HEADER):
            continue
        digest.update(marker + length_bytes + payload)
        if code == _SOS:
            return True  # entropy-coded data and anything after it is hashed verbatim


def _whole(fh: BinaryIO) -> str:
    digest = hashlib.sha256()
    _copy(fh, digest)
    return digest.hexdigest()


def _copy(fh: BinaryIO, digest: hashlib._Hash) -> None:
    while chunk := fh.read(_READ):
        digest.update(chunk)
