#!/usr/bin/env python3
"""Library budgets on a seeded library (docs/PLAN.md §14 phase 11, §8.5 "grid scroll, 10k items").

The grid is virtualized, so "no jank" is a statement about the **server**: every page the grid
asks for while scrolling has to come back inside a frame's worth of time, filter bar and search
included. This times the requests the three grids actually make, through the real app (routers,
auth, serialization), against a library seeded by `scripts/seed_library.py`.

Usage:
    cd backend && uv run python ../scripts/seed_library.py --data-dir /tmp/seed11 --artworks 10000
    cd backend && uv run python ../scripts/bench_library.py --data-dir /tmp/seed11
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from the_frame_v2.app import create_app
from the_frame_v2.config import Settings

#: A page the grid asks for while the user drags the scrollbar has one frame to answer.
BUDGET_MS = 16.7 * 4  # four frames: the budget is "no visible stall", not "instant"


def timed(fn: Callable[[], Any], *, runs: int = 12) -> tuple[float, float, Any]:
    """Median and p95 in ms, plus the last result. One warm-up run is discarded."""
    fn()
    samples = []
    result = None
    for _ in range(runs):
        start = time.perf_counter()
        result = fn()
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    return statistics.median(samples), samples[int(len(samples) * 0.95) - 1], result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args()

    settings = Settings(data_dir=args.data_dir, allowed_hosts=["testserver"])
    app = create_app(settings, start_workers=False)
    with TestClient(app, client=("127.0.0.1", 50000), headers={"X-TF-Client": "1"}) as client:

        def get(path: str, **params: Any) -> Callable[[], Any]:
            return lambda: client.get(path, params=params).json()

        def post(path: str, body: dict[str, Any]) -> Callable[[], Any]:
            return lambda: client.post(path, json=body).json()

        def walk(path: str, pages: int = 8, **params: Any) -> Callable[[], Any]:
            """Scroll the grid: page after page through the cursor, as the UI does."""

            def run() -> Any:
                cursor: str | None = None
                last: dict[str, Any] = {}
                for _ in range(pages):
                    query = dict(params)
                    if cursor:
                        query["cursor"] = cursor
                    last = client.get(path, params=query).json()
                    cursor = last.get("next_cursor")
                    if not cursor:
                        break
                return last

            return run

        cases: list[tuple[str, Callable[[], Any], int]] = [
            ("artworks first page", get("/api/v1/artworks", limit=60), 1),
            ("artworks 8 pages (scroll)", walk("/api/v1/artworks", limit=60), 8),
            ("artworks sorted by title", get("/api/v1/artworks", limit=60, sort="title_asc"), 1),
            ("favorites first page", get("/api/v1/artworks", limit=60, favorite=True), 1),
            ("search 'kyoto'", get("/api/v1/artworks", limit=60, q="kyoto"), 1),
            ("photos first page", get("/api/v1/photos", limit=60), 1),
            ("photos 8 pages (scroll)", walk("/api/v1/photos", limit=60), 8),
            ("collections tree", get("/api/v1/collections"), 1),
            ("tags with counts", get("/api/v1/tags", limit=100), 1),
            (
                "filter: tier + favorite",
                post(
                    "/api/v1/artworks/query",
                    {
                        "limit": 60,
                        "filter": {
                            "op": "and",
                            "clauses": [
                                {"field": "worst_tier", "op": "in", "value": ["native"]},
                                {"field": "favorite", "op": "eq", "value": True},
                            ],
                        },
                    },
                ),
                1,
            ),
            ("library stats (sidebar)", get("/api/v1/photos/stats"), 1),
        ]

        report: dict[str, Any] = {"budget_ms": round(BUDGET_MS, 1), "cases": {}}
        worst = 0.0
        for label, fn, pages in cases:
            median, p95, _ = timed(fn)
            # A multi-page case is judged per page: that is what one scroll gesture costs.
            per_page, p95_page = median / pages, p95 / pages
            report["cases"][label] = {
                "median_ms": round(median, 1),
                "p95_ms": round(p95, 1),
                "per_page_ms": round(per_page, 1),
            }
            worst = max(worst, p95_page)
            if not args.json:
                flag = "ok  " if p95_page <= BUDGET_MS else "SLOW"
                page = f"  ({per_page:5.1f} ms/page)" if pages > 1 else ""
                print(f"  {flag} {label:<28} {median:6.1f} ms  (p95 {p95:6.1f}){page}")

        report["worst_p95_per_page_ms"] = round(worst, 1)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"\nbudget {BUDGET_MS:.0f} ms per page · worst p95 {worst:.1f} ms")


if __name__ == "__main__":
    main()
