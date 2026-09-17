#!/usr/bin/env python3
"""Render budgets (docs/rendering-spec.md §8.5) on synthetic 24 MP JPEGs.

Usage: cd backend && uv run python ../scripts/bench_render.py
Cold = first render (decodes originals); warm = originals already in the decoded LRU.
"""

from __future__ import annotations

import json
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import pyvips

from the_frame_v2.domain.document import ArtworkDocument
from the_frame_v2.domain.geometry import Rect, Size
from the_frame_v2.domain.templates import (
    FrameStyleDocument,
    LayoutDocument,
    PhotoInput,
    build_document,
)
from the_frame_v2.imaging.render import decoded_originals, render_document, save_png
from the_frame_v2.services.templates import PRESETS_DIR


def photo(path: Path, seed: int) -> Path:
    w, h = 6000, 4000
    xy = pyvips.Image.xyz(w, h)
    base = (xy[0] * 255 / w).bandjoin([xy[1] * 255 / h, (xy[0] + xy[1]) * 255 / (w + h)])
    noisy = (base + pyvips.Image.gaussnoise(w, h, sigma=18, seed=seed)).clamp(min=0, max=255)
    noisy.cast("uchar").copy(interpretation="srgb").jpegsave(str(path), Q=92)
    return path


def timed(label: str, fn: Callable[[], object]) -> None:
    start = time.perf_counter()
    fn()
    print(f"{label:<46} {time.perf_counter() - start:6.2f} s")


def main() -> None:
    styles = {s["id"]: s for s in json.loads((PRESETS_DIR / "frame_styles.json").read_text())["styles"]}
    layouts = {s["id"]: s for s in json.loads((PRESETS_DIR / "layouts.json").read_text())["layouts"]}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        paths = {f"p{i}": photo(root / f"p{i}.jpg", i) for i in range(9)}

        def doc(style: str, layout: str, count: int) -> ArtworkDocument:
            return build_document(
                FrameStyleDocument.model_validate(styles[style]["document"]),
                LayoutDocument.model_validate(layouts[layout]["document"]),
                [PhotoInput(f"p{i}", Size(6000, 4000)) for i in range(count)],
            )

        single = doc("builtin-style-float-mount", "builtin-layout-single", 1)
        grid = doc("builtin-style-float-mount", "builtin-layout-grid-3x3", 9)
        out = root / "out.png"
        region = Rect(1500, 800, 512, 512)

        def full(d: ArtworkDocument) -> None:
            save_png(render_document(d, paths.get).image, out)

        def part() -> None:
            render_document(single, paths.get, region=region).image.pngsave_buffer(compression=1)

        decoded_originals.clear()
        timed("single slot 4K PNG, cold (budget < 2 s)", lambda: full(single))
        timed("single slot 4K PNG, warm", lambda: full(single))
        timed("region 512², warm (budget < 700 ms)", part)
        decoded_originals.clear()
        timed("region 512², cold", part)
        decoded_originals.clear()
        timed("9-slot collage + shadows, cold (budget < 6 s)", lambda: full(grid))


if __name__ == "__main__":
    main()
