#!/usr/bin/env python3
"""Generate the bundled mat textures (CC0, deterministic, seamless 1024×1024 grayscale tiles).

Usage: cd backend && uv run python ../scripts/generate_textures.py

A tile is neutral around 128: the renderer adds `strength × (t − 128)` to the mat colour
(docs/rendering-spec.md §8.1). Periodic blurs (`extend=repeat`) and integer frequencies keep tiles
seamless. Outputs are committed: regenerating with another libvips version may change the noise, which
is why `manifest.json` carries a version that is part of the render hash.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyvips

SIZE = 1024
OUT = Path(__file__).resolve().parents[1] / "backend/src/frame_it/assets/textures"


def noise(seed: int, sigma: float) -> Any:
    """Zero-mean gaussian noise, blurred periodically with `sigma` (0 = white noise)."""
    image = pyvips.Image.gaussnoise(SIZE, SIZE, mean=0.0, sigma=1.0, seed=seed)
    if sigma > 0:
        pad = SIZE // 2
        image = image.embed(pad, pad, SIZE + 2 * pad, SIZE + 2 * pad, extend="repeat")
        image = image.gaussblur(sigma, min_ampl=0.01, precision="float").crop(pad, pad, SIZE, SIZE)
    return normalized(image)


def normalized(image: Any) -> Any:
    """Scale to zero mean and unit standard deviation."""
    deviation = image.deviate()
    return (image - image.avg()) / (deviation if deviation > 0 else 1.0)


def stretch(image: Any, sx: float, sy: float, seed: int) -> Any:
    """Anisotropic noise (fibres/threads): blur more along one axis, still periodic."""
    base = pyvips.Image.gaussnoise(SIZE, SIZE, mean=0.0, sigma=1.0, seed=seed)
    pad = SIZE // 2
    big = base.embed(pad, pad, SIZE + 2 * pad, SIZE + 2 * pad, extend="repeat")
    if sx > 0:
        mask = pyvips.Image.gaussmat(sx, 0.01, separable=True, precision="float")
        big = big.conv(mask, precision="float")
    if sy > 0:
        mask = pyvips.Image.gaussmat(sy, 0.01, separable=True, precision="float").rot("d90")
        big = big.conv(mask, precision="float")
    return normalized(big.crop(pad, pad, SIZE, SIZE)) * image


def waves(cycles_x: int, cycles_y: int) -> tuple[Any, Any]:
    xy = pyvips.Image.xyz(SIZE, SIZE)
    x = xy.extract_band(0) * (360.0 * cycles_x / SIZE)  # libvips trigonometry uses degrees
    y = xy.extract_band(1) * (360.0 * cycles_y / SIZE)
    return x.sin(), y.sin()


def to_tile(image: Any, deviation: float) -> Any:
    return (normalized(image) * deviation + 128).rint().cast("uchar")


def paper() -> Any:
    return to_tile(noise(11, 0.8) * 0.7 + noise(12, 6.0) * 0.5 + stretch(1.0, 18.0, 1.2, 13) * 0.3, 7.0)


def linen() -> Any:
    wx, wy = waves(256, 256)
    threads_v = stretch((wx * 0.5 + 0.5) ** 2, 0.0, 14.0, 21)
    threads_h = stretch((wy * 0.5 + 0.5) ** 2, 14.0, 0.0, 22)
    slub = stretch(1.0, 40.0, 0.8, 23) * 0.4 + stretch(1.0, 0.8, 40.0, 24) * 0.4
    return to_tile(threads_v + threads_h + slub + noise(25, 0.7) * 0.5, 11.0)


def canvas() -> Any:
    wx, wy = waves(128, 128)
    weave = (wx * wy).abs() ** 0.7
    return to_tile(weave + noise(31, 1.5) * 0.35 + noise(32, 12.0) * 0.25, 9.0)


TEXTURES = [
    ("paper-01", "Paper", paper),
    ("linen-01", "Linen", linen),
    ("canvas-01", "Canvas", canvas),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    entries = []
    for texture_id, name, build in TEXTURES:
        tile = build().copy(interpretation="b-w")
        assert (tile.width, tile.height, tile.bands) == (SIZE, SIZE, 1)
        tile.pngsave(str(OUT / f"{texture_id}.png"), compression=9, keep="none")
        entries.append({"id": texture_id, "name": name, "size": SIZE, "license": "CC0-1.0"})
        print(f"{texture_id}: mean {tile.avg():.2f}, deviation {tile.deviate():.2f}")
    manifest = {"version": 1, "textures": entries}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
