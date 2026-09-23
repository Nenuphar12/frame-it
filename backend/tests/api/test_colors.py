"""Editor colour tools: photo palettes, curated presets, swatches, artwork defaults (§11.3)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api.test_artworks import photo
from tests.conftest import ctx_of, pair

API = "/api/v1"


def test_photo_palette_is_cached_and_deterministic(local: TestClient) -> None:
    photo_id = photo(local, 400, 300)
    first = local.get(f"{API}/photos/{photo_id}/palette")
    assert first.status_code == 200, first.text
    entries = first.json()
    assert entries, "a palette always has at least one colour"
    assert {e["kind"] for e in entries} <= {"dominant", "muted", "complementary"}
    assert all(len(e["color"]) == 7 and e["color"].startswith("#") for e in entries)
    assert entries[0]["kind"] == "dominant"
    # A flat test image gives one dominant colour close to the fill colour.
    assert entries[0]["weight"] > 0.9

    sha = local.get(f"{API}/photos/{photo_id}").json()["sha256"]
    cached = ctx_of(local).storage.palette_path(sha)
    assert cached.exists()
    assert local.get(f"{API}/photos/{photo_id}/palette").json() == entries


def test_palette_requires_admin(local: TestClient) -> None:
    photo_id = photo(local)
    uploader = pair(local, "uploader")
    assert uploader.get(f"{API}/photos/{photo_id}/palette").status_code == 403


def test_color_presets(local: TestClient) -> None:
    presets = local.get(f"{API}/presets/colors").json()
    assert {p["name"] for p in presets} >= {"Museum white", "Linen", "Charcoal", "Black"}
    assert all(p["color"].startswith("#") for p in presets)


def test_swatches_crud_and_reorder(local: TestClient) -> None:
    assert local.get(f"{API}/swatches").json() == []
    first = local.post(f"{API}/swatches", json={"color": "#aabbcc", "name": "Sky"})
    assert first.status_code == 201, first.text
    assert first.json()["color"] == "#AABBCC"
    second = local.post(f"{API}/swatches", json={"color": "#112233"}).json()

    # Saving the same colour again returns the existing swatch instead of duplicating it.
    again = local.post(f"{API}/swatches", json={"color": "#AABBCC"})
    assert again.json()["id"] == first.json()["id"]
    assert len(local.get(f"{API}/swatches").json()) == 2

    renamed = local.patch(f"{API}/swatches/{second['id']}", json={"name": "Navy"})
    assert renamed.json()["name"] == "Navy"

    reordered = local.post(f"{API}/swatches/reorder", json={"ids": [second["id"]]}).json()
    assert [s["id"] for s in reordered] == [second["id"], first.json()["id"]]

    assert local.delete(f"{API}/swatches/{second['id']}").status_code == 204
    assert [s["id"] for s in local.get(f"{API}/swatches").json()] == [first.json()["id"]]
    assert local.delete(f"{API}/swatches/{second['id']}").status_code == 404


def test_swatches_reject_unknown_ids_and_non_admins(local: TestClient) -> None:
    bad = local.post(f"{API}/swatches/reorder", json={"ids": ["nope"]})
    assert bad.status_code == 422 and bad.json()["code"] == "unknown_swatch"
    uploader = pair(local, "uploader")
    assert uploader.get(f"{API}/swatches").status_code == 403
    assert uploader.post(f"{API}/swatches", json={"color": "#000000"}).status_code == 403


def test_artwork_defaults_roundtrip(local: TestClient) -> None:
    defaults = local.get(f"{API}/artwork-defaults").json()
    assert defaults == {
        "style_id": "builtin-style-gallery-recessed",
        "recipe_id": None,
        "format": None,
    }
    updated = local.put(
        f"{API}/artwork-defaults",
        json={"style_id": "builtin-style-linen", "recipe_id": "two-stacked", "format": "1:1"},
    )
    assert updated.status_code == 200, updated.text
    assert local.get(f"{API}/artwork-defaults").json()["recipe_id"] == "two-stacked"

    # The defaults are what creating an artwork without an explicit choice starts from: the
    # recipe when it fits the selection (docs/templates.md §5), the style and format always.
    artwork = local.post(f"{API}/artworks", json={"photo_ids": [photo(local)]}).json()
    assert artwork["origin_style_id"] == "builtin-style-linen"
    assert artwork["document"]["composition"]["recipe"] == "single"  # one photo, not two
    assert artwork["document"]["composition"]["format"] == "1:1"
    pair_of_photos = [photo(local), photo(local)]
    stacked = local.post(f"{API}/artworks", json={"photo_ids": pair_of_photos}).json()
    assert stacked["document"]["composition"]["recipe"] == "two-stacked"

    unknown = local.put(f"{API}/artwork-defaults", json={"style_id": "nope"})
    assert unknown.status_code == 422 and unknown.json()["code"] == "unknown_style"
    bad_recipe = local.put(
        f"{API}/artwork-defaults",
        json={"style_id": "builtin-style-linen", "recipe_id": "nope"},
    )
    assert bad_recipe.status_code == 422 and bad_recipe.json()["code"] == "unknown_recipe"
