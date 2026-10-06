"""Bundled rendering assets: caption fonts and mat textures (manifests in `assets/`).

Fonts: `scripts/build_fonts.py` (OFL). Textures: `scripts/generate_textures.py` (CC0). Their
manifest versions are part of the render hash, so bump them when files change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
TEXTURES_DIR = ASSETS_DIR / "textures"


@dataclass(frozen=True, slots=True)
class FontMetrics:
    units_per_em: int
    ascender: int
    descender: int


@dataclass(frozen=True, slots=True)
class FontAsset:
    id: str
    name: str
    category: str
    weights: tuple[int, ...]
    metrics: dict[int, FontMetrics]

    def path(self, weight: int) -> Path:
        return FONTS_DIR / self.id / f"{weight}.ttf"

    @staticmethod
    def family(font_id: str, weight: int) -> str:
        """Unique family name embedded in the file (see scripts/build_fonts.py)."""
        return f"TF {font_id} {weight}"


@dataclass(frozen=True, slots=True)
class TextureAsset:
    id: str
    name: str
    size: int

    @property
    def path(self) -> Path:
        return TEXTURES_DIR / f"{self.id}.png"


@dataclass(frozen=True, slots=True)
class AssetCatalog:
    fonts: dict[str, FontAsset]
    textures: dict[str, TextureAsset]
    fonts_version: int
    textures_version: int

    def font_weights(self, font_id: str) -> frozenset[int] | None:
        font = self.fonts.get(font_id)
        return frozenset(font.weights) if font else None

    def texture_exists(self, texture_id: str) -> bool:
        return texture_id in self.textures

    @property
    def version_key(self) -> str:
        return f"fonts:{self.fonts_version};textures:{self.textures_version}"


@cache
def catalog() -> AssetCatalog:
    fonts_raw = json.loads((FONTS_DIR / "manifest.json").read_text())
    textures_raw = json.loads((TEXTURES_DIR / "manifest.json").read_text())
    fonts = {
        f["id"]: FontAsset(
            id=f["id"],
            name=f["name"],
            category=f["category"],
            weights=tuple(f["weights"]),
            metrics={int(w): FontMetrics(**m) for w, m in f["metrics"].items()},
        )
        for f in fonts_raw["fonts"]
    }
    textures = {
        t["id"]: TextureAsset(id=t["id"], name=t["name"], size=t["size"])
        for t in textures_raw["textures"]
    }
    return AssetCatalog(fonts, textures, int(fonts_raw["version"]), int(textures_raw["version"]))
