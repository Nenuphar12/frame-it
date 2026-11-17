"""Serving the built frontend: the shell is revalidated, hashed assets are kept and compressed."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from frame_it import app as app_module


@pytest.fixture
def spa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, app_factory: Callable[..., TestClient]
) -> TestClient:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>Frame It</title>")
    (static / "assets" / "index-Ab12Cd34.js").write_text("console.log('frame it');\n" * 200)
    monkeypatch.setattr(app_module, "STATIC_DIR", static)
    return app_factory()


def test_hashed_assets_are_immutable_and_gzipped(spa: TestClient) -> None:
    res = spa.get("/assets/index-Ab12Cd34.js", headers={"Accept-Encoding": "gzip"})
    assert res.status_code == 200
    assert res.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert res.headers["content-encoding"] == "gzip"
    assert res.text.startswith("console.log")
    # The guard's headers still apply to a mounted app.
    assert res.headers["x-content-type-options"] == "nosniff"


def test_the_shell_is_revalidated_on_every_route(spa: TestClient) -> None:
    for path in ("/", "/artworks/some-id"):
        res = spa.get(path)
        assert res.status_code == 200
        assert res.headers["cache-control"] == "no-cache"
        assert "<title>Frame It</title>" in res.text


def test_a_missing_asset_is_not_the_shell(spa: TestClient) -> None:
    # A chunk from an older build must fail loudly, not come back as HTML with a 200.
    res = spa.get("/assets/index-Old00000.js")
    assert res.status_code == 404
    assert "cache-control" not in res.headers or "immutable" not in res.headers["cache-control"]
