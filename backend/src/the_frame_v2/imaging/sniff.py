"""File type detection from magic bytes (never trust extensions or client mime types)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SupportedFormat = Literal["jpeg", "png", "avif"]

_HEVC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs"}
_AVIF_BRANDS = {b"avif", b"avis"}


@dataclass(frozen=True, slots=True)
class Sniffed:
    kind: str
    """jpeg | png | avif | heic | heif | webp | tiff | gif | unknown"""

    @property
    def supported(self) -> bool:
        return self.kind in ("jpeg", "png", "avif")

    @property
    def ext(self) -> str:
        return {"jpeg": "jpg"}.get(self.kind, self.kind)

    @property
    def mime(self) -> str:
        return {
            "jpeg": "image/jpeg",
            "png": "image/png",
            "avif": "image/avif",
            "heic": "image/heic",
            "heif": "image/heif",
            "webp": "image/webp",
            "tiff": "image/tiff",
            "gif": "image/gif",
        }.get(self.kind, "application/octet-stream")


def sniff_bytes(head: bytes) -> Sniffed:
    if head.startswith(b"\xff\xd8\xff"):
        return Sniffed("jpeg")
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return Sniffed("png")
    if len(head) >= 12 and head[4:8] == b"ftyp":
        box_size = int.from_bytes(head[0:4], "big")
        end = min(max(box_size, 16), len(head))
        brands = {head[8:12]} | {head[i : i + 4] for i in range(16, end - 3, 4)}
        if brands & _AVIF_BRANDS:
            return Sniffed("avif")
        if brands & _HEVC_BRANDS:
            return Sniffed("heic")
        if b"mif1" in brands or b"msf1" in brands:
            return Sniffed("heif")
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return Sniffed("webp")
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return Sniffed("tiff")
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return Sniffed("gif")
    return Sniffed("unknown")


def sniff_file(path: Path) -> Sniffed:
    with path.open("rb") as fh:
        return sniff_bytes(fh.read(256))
