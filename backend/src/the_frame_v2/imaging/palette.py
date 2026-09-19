"""Photo palette: mat colours suggested from a photo. Spec: docs/PLAN.md §11.3.

k-means in OKLab on a 64×64 thumbnail, then variants that actually work as a mat: the dominant
colours themselves, desaturated ("muted") versions and the complementary hue. Pure and
deterministic (fixed initialisation, fixed iteration count) so the result can be cached and tested.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

SAMPLE = 64
"""Thumbnail side used for the analysis (§11.3)."""
CLUSTERS = 5
ITERATIONS = 12

Lab = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class PaletteEntry:
    color: str
    """`#RRGGBB`."""
    kind: str
    """`dominant` | `muted` | `complementary`."""
    weight: float
    """Share of the photo the source cluster covers (0 to 1)."""


# ---- sRGB ↔ OKLab (Björn Ottosson's formulation; sRGB values are 0-255) -------------------------
def _to_linear(value: float) -> float:
    v = value / 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _from_linear(value: float) -> float:
    v = value if value > 0 else 0.0
    srgb = 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
    return min(255.0, max(0.0, srgb * 255))


def srgb_to_oklab(rgb: tuple[int, int, int]) -> Lab:
    r, g, b = (_to_linear(c) for c in rgb)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b  # noqa: E741
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in (l, m, s))
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def oklab_to_srgb(lab: Lab) -> tuple[int, int, int]:
    lightness, a, b = lab
    l_ = lightness + 0.3963377774 * a + 0.2158037573 * b
    m_ = lightness - 0.1055613458 * a - 0.0638541728 * b
    s_ = lightness - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = (v**3 for v in (l_, m_, s_))  # noqa: E741
    return (
        round(_from_linear(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s)),
        round(_from_linear(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s)),
        round(_from_linear(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)),
    )


def to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(min(255, max(0, c)) for c in rgb))


# ---- clustering ---------------------------------------------------------------------------------
def _initial_centers(points: list[Lab], k: int) -> list[Lab]:
    """Deterministic k-means++: start at the darkest point, then always the farthest one."""
    centers = [min(points, key=lambda p: (p[0], p[1], p[2]))]
    while len(centers) < k:
        farthest = max(points, key=lambda p: min(_distance(p, c) for c in centers))
        if farthest in centers:
            break
        centers.append(farthest)
    return centers


def _distance(a: Lab, b: Lab) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def kmeans(points: list[Lab], k: int = CLUSTERS) -> list[tuple[Lab, float]]:
    """Cluster centres with their weights, most important first (pure, deterministic)."""
    if not points:
        return []
    centers = _initial_centers(points, min(k, len(points)))
    counts = [0] * len(centers)
    for _ in range(ITERATIONS):
        sums = [[0.0, 0.0, 0.0] for _ in centers]
        counts = [0] * len(centers)
        for point in points:
            index = min(range(len(centers)), key=lambda i: _distance(point, centers[i]))
            for axis in range(3):
                sums[index][axis] += point[axis]
            counts[index] += 1
        moved = False
        for index, count in enumerate(counts):
            if count == 0:
                continue
            updated = (sums[index][0] / count, sums[index][1] / count, sums[index][2] / count)
            moved = moved or updated != centers[index]
            centers[index] = updated
        if not moved:
            break
    total = float(len(points))
    clusters = [(c, counts[i] / total) for i, c in enumerate(centers) if counts[i] > 0]
    return sorted(clusters, key=lambda item: (-item[1], item[0]))


def _chroma(lab: Lab) -> float:
    return math.hypot(lab[1], lab[2])


def _muted(lab: Lab) -> Lab:
    """A mat-friendly version: keep the hue, cut the chroma, lift the lightness."""
    lightness = min(0.96, lab[0] * 0.35 + 0.62)
    factor = 0.18
    return (lightness, lab[1] * factor, lab[2] * factor)


def _complementary(lab: Lab) -> Lab:
    return (min(0.92, max(0.18, lab[0])), -lab[1], -lab[2])


def palette_from_pixels(pixels: list[tuple[int, int, int]]) -> list[PaletteEntry]:
    """Dominant colours of a photo plus muted and complementary variants (deduplicated)."""
    clusters = kmeans([srgb_to_oklab(p) for p in pixels])
    entries: list[PaletteEntry] = []
    seen: set[str] = set()

    def add(lab: Lab, kind: str, weight: float) -> None:
        color = to_hex(oklab_to_srgb(lab))
        if color not in seen:
            seen.add(color)
            entries.append(PaletteEntry(color, kind, round(weight, 4)))

    for lab, weight in clusters:
        add(lab, "dominant", weight)
    for lab, weight in clusters:
        add(_muted(lab), "muted", weight)
    for lab, weight in clusters[:2]:
        if _chroma(lab) > 0.02:
            add(_muted(_complementary(lab)), "complementary", weight)
    return entries


def sample_pixels(image: Any) -> list[tuple[int, int, int]]:
    """64×64 RGB samples of a pyvips image (the only place pixels are read here)."""
    thumb = image.thumbnail_image(SAMPLE, height=SAMPLE, size="force")
    bands = thumb.bands
    raw = bytes(thumb.cast("uchar").write_to_memory())  # pyvips returns a cffi buffer
    return [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw) - bands + 1, bands)]
