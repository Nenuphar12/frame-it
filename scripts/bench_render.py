#!/usr/bin/env python3
"""Render budgets and memory (docs/rendering-spec.md §8.5) on synthetic 24 MP JPEGs.

Usage: cd backend && uv run python ../scripts/bench_render.py
Cold = first render (decodes originals); warm = originals already in the decoded LRU.

Memory matters as much as time here: a render holds every decoded original of the document at
once (parallel decode, §8.1), so a 9-slot collage of 24 MP sources is the worst case the app can
be asked for. Each line reports the peak RSS *added* by the render — what a second concurrent
render would need on top of the process, which is why `render_workers` defaults to 1.
"""

from __future__ import annotations

import json
import resource
import tempfile
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path

import pyvips

from the_frame_v2.domain import composition as composition_domain
from the_frame_v2.domain.document import ArtworkDocument, Composition
from the_frame_v2.domain.geometry import Rect, Size
from the_frame_v2.domain.templates import (
    FrameStyleDocument,
    PhotoInput,
    build_composition_document,
)
from the_frame_v2.imaging.render import decoded_originals, render_document, save_png
from the_frame_v2.services import recipes
from the_frame_v2.services.templates import PRESETS_DIR


def photo(path: Path, seed: int) -> Path:
    w, h = 6000, 4000
    xy = pyvips.Image.xyz(w, h)
    base = (xy[0] * 255 / w).bandjoin([xy[1] * 255 / h, (xy[0] + xy[1]) * 255 / (w + h)])
    noisy = (base + pyvips.Image.gaussnoise(w, h, sigma=18, seed=seed)).clamp(min=0, max=255)
    noisy.cast("uchar").copy(interpretation="srgb").jpegsave(str(path), Q=92)
    return path


def rss_mb() -> float:
    """Resident set size in MB. libvips allocates outside the Python heap, so `tracemalloc`
    alone would report a fraction of what the machine actually needs."""
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return usage / 1024  # Linux reports kilobytes


def timed(label: str, fn: Callable[[], object]) -> None:
    before = rss_mb()
    tracemalloc.start()
    start = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - start
    _, python_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    # `ru_maxrss` is a high-water mark for the whole process: the delta is what this render added
    # beyond anything before it (0.0 once an earlier, larger render has already set the mark).
    print(
        f"{label:<46} {elapsed:6.2f} s"
        f"   peak RSS {rss_mb():7.0f} MB (+{max(0.0, rss_mb() - before):5.0f})"
        f"   python {python_peak / 1024**2:5.0f} MB"
    )


def main() -> None:
    preset = json.loads((PRESETS_DIR / "frame_styles.json").read_text())["styles"]
    styles = {s["id"]: s for s in preset}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        paths = {f"p{i}": photo(root / f"p{i}.jpg", i) for i in range(9)}

        def doc(style: str, count: int) -> ArtworkDocument:
            """A parametric artwork of `count` photos, solved as the server would save it."""
            recipe = recipes.for_count(count)
            assert recipe is not None, f"no recipe holds {count} cells"
            built = build_composition_document(
                FrameStyleDocument.model_validate(styles[style]["document"]),
                recipe,
                Composition(recipe=recipe.id),
                [PhotoInput(f"p{i}", Size(6000, 4000)) for i in range(count)],
            )
            sizes = {f"p{i}": Size(6000, 4000) for i in range(count)}
            return composition_domain.apply(built, recipe, sizes)

        single = doc("builtin-style-float-mount", 1)
        # 6 is the catalogue's largest recipe (past that a composition detaches, §4.4).
        grid = doc("builtin-style-float-mount", 6)
        # 9 slots are only reachable through the Advanced editor, which hand-places them — the
        # §8.5 budget is written for that case, so it is built the way that editor would.
        nine = grid.model_copy(
            deep=True,
            update={
                "composition": None,
                "slots": [
                    slot.model_copy(deep=True, update={"id": f"s{i}", "photo_id": f"p{i}"})
                    for i, slot in enumerate([grid.slots[n % len(grid.slots)] for n in range(9)])
                ],
                "captions": [],
            },
        )
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
        timed("6-slot collage + shadows, cold", lambda: full(grid))
        decoded_originals.clear()
        timed("9-slot collage + shadows, cold (budget < 6 s)", lambda: full(nine))


if __name__ == "__main__":
    main()
