"""The render memory guard (`docs/rendering-spec.md` §8.5, phase 11).

A render holds every decoded original of a document at once, so a document with many large photos
asks for gigabytes. The guard turns that into a problem code instead of an out-of-memory kill.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from frame_it.domain.document import ArtworkDocument
from frame_it.imaging import render as renderer


def _doc(photo_ids: list[str]) -> ArtworkDocument:
    return ArtworkDocument.model_validate(
        {
            "schema": 1,
            "placement": "manual",
            "slots": [
                {
                    "id": f"s{i}",
                    "photo_id": photo_id,
                    "rect": {"x": 0, "y": 0, "w": 800, "h": 600},
                    "source": {"crop": {"x": 0, "y": 0, "w": 800, "h": 600}},
                    "quality_lock": "free",
                }
                for i, photo_id in enumerate(photo_ids)
            ],
        }
    )


def test_a_document_over_the_pixel_budget_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = {}
    for name in ("a", "b"):
        path = tmp_path / f"{name}.jpg"
        Image.new("RGB", (1200, 900), (10, 20, 30)).save(path, "JPEG")
        paths[name] = path
    # 2 × 1.08 Mpx: under the real budget, over this one.
    monkeypatch.setattr(renderer, "MAX_RENDER_PIXELS", 2_000_000)

    with pytest.raises(renderer.RenderError) as excinfo:
        renderer.render_document(_doc(["a", "b"]), paths.get)
    assert excinfo.value.code == "render_too_large"
    assert "2 photos" in str(excinfo.value)


def test_the_same_photo_twice_is_counted_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "a.jpg"
    Image.new("RGB", (1200, 900), (10, 20, 30)).save(path, "JPEG")
    monkeypatch.setattr(renderer, "MAX_RENDER_PIXELS", 2_000_000)

    # Four slots, one original: the render holds 1.08 Mpx, not 4.3.
    rendered = renderer.render_document(_doc(["a"] * 4), lambda _: path)
    assert rendered.image.width == 3840
