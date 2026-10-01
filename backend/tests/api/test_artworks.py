from __future__ import annotations

import io
from typing import Any

import pyvips
from fastapi.testclient import TestClient
from PIL import Image

from tests.conftest import ctx_of, make_jpeg, pair, sha256, upload_bytes

API = "/api/v1"


def photo(local: TestClient, width: int = 1200, height: int = 800, **meta: Any) -> str:
    color = (width % 256, height % 256, (width + height) % 256)
    data = make_jpeg(width, height, color)
    upload_bytes(local, data, f"IMG_{width}x{height}.jpg", **meta)
    photo_id = local.post(f"{API}/uploads/check", json={"sha256": [sha256(data)]}).json()[
        "results"
    ][0]["photo_id"]
    assert isinstance(photo_id, str)
    return photo_id


def create(local: TestClient, photo_ids: list[str], **extra: Any) -> dict[str, Any]:
    res = local.post(f"{API}/artworks", json={"photo_ids": photo_ids, **extra})
    assert res.status_code == 201, res.text
    body: dict[str, Any] = res.json()
    return body


def put_document(
    local: TestClient, artwork: dict[str, Any], document: dict[str, Any], version: int | None = None
) -> Any:
    headers = {"If-Match": f'"{artwork["document_version"] if version is None else version}"'}
    return local.put(f"{API}/artworks/{artwork['id']}/document", json=document, headers=headers)


def test_builtin_templates_and_assets(local: TestClient) -> None:
    styles = local.get(f"{API}/frame-styles").json()
    layouts = local.get(f"{API}/layouts").json()
    assert {s["name"] for s in styles} >= {
        "None",
        "Gallery recessed",
        "Float mount",
        "Thin black",
        "Linen",
        "Museum white",
    }
    assert {layout["name"] for layout in layouts} >= {
        "Single",
        "Full bleed",
        "2 × 2",
        "3 × 2",
        "1 + 2",
    }
    assert all(s["builtin"] for s in styles)
    # a layout is a recipe and its parameters since Phase 8 (docs/templates.md §2)
    single = next(layout for layout in layouts if layout["name"] == "Single")
    assert single["slot_count"] == 1 and single["document"]["recipe"] == "single"
    fonts = local.get(f"{API}/fonts").json()
    inter = next(f for f in fonts if f["id"] == "inter")
    font = local.get(f"{API}/fonts/inter/{inter['weights'][0]}.ttf")
    assert font.status_code == 200 and font.headers["content-type"] == "font/ttf"
    assert local.get(f"{API}/fonts/inter/950.ttf").status_code == 404
    textures = local.get(f"{API}/textures").json()
    tile = local.get(f"{API}/textures/{textures[0]['id']}.png")
    assert tile.status_code == 200 and tile.content.startswith(b"\x89PNG")


def test_create_single_artwork_with_defaults(local: TestClient) -> None:
    pid = photo(local, 3000, 2000, favorite=True)
    artwork = create(local, [pid])
    doc = artwork["document"]
    assert artwork["status"] == "draft"
    assert artwork["title"] == "IMG_3000x2000"
    assert artwork["favorite"] is True  # pending upload metadata applied
    assert artwork["origin_style_id"] == "builtin-style-gallery-recessed"
    assert artwork["origin_layout_id"] is None  # parametric: a recipe, not a layout (§7)
    assert doc["schema"] == 1 and doc["placement"] == "manual" and len(doc["slots"]) == 1
    assert doc["composition"]["recipe"] == "single"
    assert doc["composition"]["format"] == "original"  # the whole photo in the mat
    assert doc["slots"][0]["rect"] == {"x": 480, "y": 120, "w": 2880, "h": 1920}
    assert artwork["worst_tier"] == "downscaled" and artwork["photo_count"] == 1
    assert not artwork["is_incomplete"]
    # A draft keeps its photo in the inbox: it leaves when the artwork is marked ready.
    in_inbox = local.get(f"{API}/photos/{pid}").json()
    assert in_inbox["inbox_state"] == "inbox"
    assert in_inbox["draft_artwork_ids"] == [artwork["id"]]
    listed = local.get(f"{API}/artworks", params={"photo_id": pid}).json()["items"]
    assert [a["id"] for a in listed] == [artwork["id"]]
    # the pending metadata is consumed: a second artwork is not favourite
    assert create(local, [pid])["favorite"] is False


def test_create_collage_and_errors(local: TestClient) -> None:
    ids = [photo(local, 1200, 800), photo(local, 800, 1200), photo(local, 900, 900)]
    collage = create(
        local, ids, layout_id="builtin-layout-one-plus-two", style_id="builtin-style-float-mount"
    )
    assert collage["document"]["placement"] == "manual"
    assert [s["photo_id"] for s in collage["document"]["slots"]] == ids
    # a layout carries a recipe: the artwork is parametric and remembers where it came from
    assert collage["document"]["composition"]["recipe"] == "three-hero-left"
    assert collage["origin_layout_id"] == "builtin-layout-one-plus-two"
    assert collage["origin_layout_revision"] == 1
    float_slot = collage["document"]["slots"][0]
    assert float_slot["bands"] == [] and float_slot["shadow"]["type"] == "drop"
    auto = create(local, ids[:2])  # no layout and no composition → the first 2-photo recipe
    assert auto["origin_layout_id"] is None
    assert auto["document"]["composition"]["recipe"] == "two-side-by-side"
    # fewer photos than cells is allowed: the rest are placeholders to fill in the editor
    partial = create(local, ids[:1], layout_id="builtin-layout-grid-2x2")
    assert partial["is_incomplete"] and partial["photo_count"] == 1
    assert len(partial["document"]["slots"]) == 4

    wrong_count = local.post(
        f"{API}/artworks", json={"photo_ids": ids, "layout_id": "builtin-layout-single"}
    )
    assert wrong_count.status_code == 422 and wrong_count.json()["code"] == "layout_slot_count"
    unknown = local.post(f"{API}/artworks", json={"photo_ids": ["nope"]})
    assert unknown.json()["code"] == "unknown_photo"
    bad_style = local.post(f"{API}/artworks", json={"photo_ids": ids[:1], "style_id": "nope"})
    assert bad_style.json()["code"] == "unknown_style"


def test_document_versioning_and_validation(local: TestClient) -> None:
    artwork = create(local, [photo(local, 2000, 1500)])
    doc = artwork["document"]
    assert local.put(f"{API}/artworks/{artwork['id']}/document", json=doc).status_code == 428

    doc["mat"]["color"] = "#101010"
    saved = put_document(local, artwork, doc)
    assert saved.status_code == 200, saved.text
    assert saved.json()["document_version"] == 2
    assert saved.headers["ETag"] == '"2"'
    assert saved.json()["document"]["mat"]["color"] == "#101010"

    stale = put_document(local, artwork, doc, version=1)
    assert stale.status_code == 409
    assert stale.json()["code"] == "version_conflict"
    assert stale.json()["extra"]["current_version"] == 2

    broken = {**doc, "slots": [{**doc["slots"][0], "rect": {**doc["slots"][0]["rect"], "w": 10}}]}
    res = put_document(local, saved.json(), broken)
    assert res.status_code == 422
    assert any(
        e["loc"][-2:] == ["slots", 0] and "aspect" in e["msg"]
        for e in res.json()["extra"]["errors"]
    )

    out_of_bounds = {
        **doc,
        "slots": [
            {
                **doc["slots"][0],
                "source": {"crop": {"x": 1000, "y": 0, "w": 2000, "h": 1500}},
                "quality_lock": "free",
            }
        ],
    }
    res = put_document(local, saved.json(), out_of_bounds)
    assert res.status_code == 422 and res.json()["code"] == "invalid_document"
    assert res.json()["extra"]["errors"][0] == {
        "loc": ["slots", 0, "source", "crop"],
        "msg": "crop exceeds the 2000×1500 oriented photo",
        "type": "crop_out_of_bounds",
    }
    assert local.get(f"{API}/artworks/{artwork['id']}").json()["document_version"] == 2


def test_render_endpoints_and_job(local: TestClient) -> None:
    artwork = create(local, [photo(local, 1600, 1200)])
    ctx = ctx_of(local)
    assert ctx.jobs.run_pending_sync() == 1  # render job queued by the creation
    current = local.get(f"{API}/artworks/{artwork['id']}").json()
    render_hash = current["render_hash"]
    assert render_hash and current["rendered_at"]

    png = local.get(f"{API}/artworks/{artwork['id']}/render.png", params={"v": render_hash})
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert "immutable" in png.headers["cache-control"]
    assert png.headers["x-render-hash"] == render_hash
    image = pyvips.Image.new_from_buffer(png.content, "")
    assert (image.width, image.height, image.bands) == (3840, 2160, 3)
    assert image.get_typeof("icc-profile-data") != 0

    jpg = local.get(f"{API}/artworks/{artwork['id']}/render.jpg")
    assert jpg.status_code == 200 and "no-cache" in jpg.headers["cache-control"]
    with Image.open(io.BytesIO(jpg.content)) as im:
        assert im.size == (3840, 2160)
    thumb = local.get(f"{API}/artworks/{artwork['id']}/thumb/256")
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/webp"

    # a new document gets a new render; the old files are pruned
    doc = current["document"]
    doc["mat"]["texture"] = None
    put_document(local, current, doc)
    ctx.jobs.run_pending_sync()
    updated = local.get(f"{API}/artworks/{artwork['id']}").json()
    assert updated["render_hash"] != render_hash
    files = sorted(p.name for p in ctx.storage.render_dir(artwork["id"]).iterdir())
    assert files == [f"{updated['render_hash']}.png"]


def test_jpeg_is_444(local: TestClient) -> None:
    artwork = create(local, [photo(local, 1600, 1200)])
    jpg = local.get(f"{API}/artworks/{artwork['id']}/render.jpg").content
    image = pyvips.Image.new_from_buffer(jpg, "")
    assert image.get("jpeg-chroma-subsample") == "4:4:4"


def test_region_render(local: TestClient) -> None:
    artwork = create(local, [photo(local, 1600, 1200)])
    rect = {"x": 1000, "y": 500, "w": 512, "h": 256}
    res = local.post(f"{API}/render/region", json={"document": artwork["document"], "rect": rect})
    assert res.status_code == 200 and res.headers["content-type"] == "image/png"
    image = pyvips.Image.new_from_buffer(res.content, "")
    assert (image.width, image.height) == (512, 256)
    too_big = local.post(
        f"{API}/render/region", json={"document": artwork["document"], "rect": {**rect, "w": 2048}}
    )
    assert too_big.status_code == 422
    invalid = local.post(
        f"{API}/render/region", json={"document": {"schema": 1, "slots": []}, "rect": rect}
    )
    assert invalid.status_code == 422 and invalid.json()["code"] == "invalid_document"


def test_snapshots_duplicate_validate_trash(local: TestClient) -> None:
    pid = photo(local, 1600, 1200)
    artwork = create(local, [pid])
    aid = artwork["id"]
    snap = local.post(f"{API}/artworks/{aid}/snapshots", json={"reason": "opened"})
    assert snap.status_code == 201 and snap.json()["document_version"] == 1

    original_color = artwork["document"]["mat"]["color"]
    doc = {**artwork["document"], "mat": {**artwork["document"]["mat"], "color": "#222222"}}
    assert put_document(local, artwork, doc).status_code == 200
    restored = local.post(f"{API}/artworks/{aid}/snapshots/{snap.json()['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["document_version"] == 3
    assert restored.json()["document"]["mat"]["color"] == original_color
    reasons = [s["reason"] for s in local.get(f"{API}/artworks/{aid}/snapshots").json()]
    assert reasons == ["pre_restore", "opened"]

    copy = local.post(f"{API}/artworks/{aid}/duplicate")
    assert copy.status_code == 201 and copy.json()["id"] != aid
    assert copy.json()["document"] == restored.json()["document"]

    ready = local.post(f"{API}/artworks/{aid}/validate")
    assert ready.status_code == 200 and ready.json()["status"] == "ready"
    incomplete = create(local, [pid], layout_id="builtin-layout-grid-2x2")
    res = local.post(f"{API}/artworks/{incomplete['id']}/validate")
    assert res.status_code == 422 and res.json()["code"] == "artwork_incomplete"

    patched = local.patch(
        f"{API}/artworks/{aid}", json={"title": "  Evening  ", "favorite": True, "status": "draft"}
    )
    assert (
        patched.json()["title"] == "Evening"
        and patched.json()["favorite"]
        and patched.json()["status"] == "draft"
    )

    assert local.delete(f"{API}/artworks/{aid}").status_code == 204
    assert local.get(f"{API}/artworks/{aid}").status_code == 404
    assert aid not in [a["id"] for a in local.get(f"{API}/artworks").json()["items"]]


def test_snapshots_are_capped(local: TestClient) -> None:
    artwork = create(local, [photo(local)])
    for _ in range(23):
        local.post(f"{API}/artworks/{artwork['id']}/snapshots", json={})
    assert len(local.get(f"{API}/artworks/{artwork['id']}/snapshots").json()) == 20


def test_roles(local: TestClient) -> None:
    artwork = create(local, [photo(local)])
    uploader = pair(local, "uploader")
    assert uploader.get(f"{API}/artworks").status_code == 200
    assert uploader.get(f"{API}/artworks/{artwork['id']}").status_code == 200
    assert uploader.get(f"{API}/artworks/{artwork['id']}/thumb/256").status_code == 200
    assert uploader.post(f"{API}/artworks", json={"photo_ids": ["x"]}).status_code == 403
    assert (
        uploader.put(
            f"{API}/artworks/{artwork['id']}/document",
            json=artwork["document"],
            headers={"If-Match": "1"},
        ).status_code
        == 403
    )
    assert (
        uploader.patch(f"{API}/artworks/{artwork['id']}", json={"favorite": True}).status_code
        == 403
    )
    assert uploader.delete(f"{API}/artworks/{artwork['id']}").status_code == 403
    assert uploader.get(f"{API}/frame-styles").status_code == 403
    assert (
        uploader.post(
            f"{API}/render/region",
            json={"document": artwork["document"], "rect": {"x": 0, "y": 0, "w": 10, "h": 10}},
        ).status_code
        == 403
    )


def test_trashed_photo_makes_render_fail_cleanly(local: TestClient) -> None:
    pid = photo(local)
    artwork = create(local, [pid])
    from the_frame_v2.db.models import Photo
    from the_frame_v2.ids import utcnow

    with ctx_of(local).db.session() as s:
        row = s.get(Photo, pid)
        assert row is not None
        row.deleted_at = utcnow()
    res = local.get(f"{API}/artworks/{artwork['id']}/render.png")
    assert res.status_code == 422 and res.json()["code"] == "photo_missing"


def test_recipe_catalogue(local: TestClient) -> None:
    recipes = local.get(f"{API}/recipes").json()
    assert {r["count"] for r in recipes} == {1, 2, 3, 4, 5, 6}
    by_id = {r["id"]: r for r in recipes}
    assert by_id["single"]["tree"] == {"cell": "auto"}
    hero = by_id["three-hero-left"]
    assert hero["name_key"] == "recipes.three-hero-left"
    assert hero["balance"] == {"min": 0.4, "max": 0.75, "default": 0.62}
    assert hero["tree"]["split"] == "row" and len(hero["tree"]["children"]) == 2
    assert by_id["four-grid"]["balance"] is None


def test_document_accepts_a_composition_block(local: TestClient) -> None:
    artwork = create(local, [photo(local, 2000, 1500)], layout_id="builtin-layout-single")
    doc = artwork["document"]
    # the layout *is* a composition (Phase 8): the artwork starts from its parameters
    assert doc["composition"]["recipe"] == "single"
    assert doc["composition"]["outer"] == {"x": 300, "y": 280}

    doc["composition"] = {
        "recipe": "single",
        "outer": {"x": 120, "y": 120},
        "gutter": {"x": 80, "y": 80},
        "format": "fill",
        "caption": {"text": "Kyoto", "place": "below"},
    }
    saved = put_document(local, artwork, doc)
    assert saved.status_code == 200, saved.text
    stored = saved.json()["document"]["composition"]
    assert stored["recipe"] == "single" and stored["detached"] is False
    assert stored["balance"] is None and stored["border"] is None


def test_composition_is_checked_against_the_catalogue(local: TestClient) -> None:
    artwork = create(local, [photo(local, 2000, 1500)])
    doc = artwork["document"]
    block = {"recipe": "single", "outer": {"x": 0, "y": 0}, "gutter": {"x": 0, "y": 0}}

    unknown = put_document(local, artwork, {**doc, "composition": {**block, "recipe": "nope"}})
    assert unknown.status_code == 422
    assert unknown.json()["extra"]["errors"][0]["type"] == "unknown_recipe"

    too_many = put_document(
        local, artwork, {**doc, "composition": {**block, "recipe": "four-grid"}}
    )
    assert too_many.status_code == 422
    assert too_many.json()["extra"]["errors"][0]["type"] == "recipe_slot_count"

    out_of_range = put_document(
        local, artwork, {**doc, "composition": {**block, "recipe": "two-hero-left", "balance": 0.9}}
    )
    assert out_of_range.status_code == 422
    assert {e["type"] for e in out_of_range.json()["extra"]["errors"]} == {
        "recipe_slot_count",
        "balance_out_of_range",
    }

    no_balance = put_document(local, artwork, {**doc, "composition": {**block, "balance": 0.5}})
    assert no_balance.status_code == 422
    assert no_balance.json()["extra"]["errors"][0]["type"] == "balance_not_supported"


def test_a_detached_composition_may_hold_any_slot_count(local: TestClient) -> None:
    """While detached the slots are the truth, so the recipe's count no longer has to match (§5)."""
    artwork = create(local, [photo(local, 2000, 1500)])
    doc = artwork["document"]
    doc["composition"] = {
        "recipe": "four-grid",
        "outer": {"x": 0, "y": 0},
        "gutter": {"x": 0, "y": 0},
        "detached": True,
    }
    saved = put_document(local, artwork, doc)
    assert saved.status_code == 200, saved.text
    assert saved.json()["document"]["composition"]["detached"] is True


def test_put_document_re_solves_the_composition(local: TestClient) -> None:
    """Server authority (§7): the block decides the rects, whatever the payload claims."""
    ids = [photo(local, 3000, 2000), photo(local, 3000, 2000)]
    artwork = create(local, ids)
    doc = artwork["document"]
    assert doc["composition"]["recipe"] == "two-side-by-side"
    assert [s["rect"] for s in doc["slots"]] == [
        {"x": 120, "y": 120, "w": 1760, "h": 1920},
        {"x": 1960, "y": 120, "w": 1760, "h": 1920},
    ]

    # a client sending nonsense: half-size rects at the origin, and a reframed first photo
    doc["slots"][0]["rect"] = {"x": 0, "y": 0, "w": 880, "h": 960}
    doc["slots"][0]["source"]["crop"] = {"x": 500, "y": 300, "w": 900, "h": 982}
    doc["slots"][0]["quality_lock"] = "free"
    doc["slots"][1]["rect"] = {"x": 0, "y": 0, "w": 880, "h": 960}
    doc["slots"][1]["source"]["crop"] = {"x": 583, "y": 0, "w": 1833, "h": 2000}
    saved = put_document(local, artwork, doc)
    assert saved.status_code == 200, saved.text
    slots = saved.json()["document"]["slots"]
    assert [s["rect"] for s in slots] == [
        {"x": 120, "y": 120, "w": 1760, "h": 1920},
        {"x": 1960, "y": 120, "w": 1760, "h": 1920},
    ]
    # the reframe survives the overwrite: same centre, same zoom (§4.1) — and it now upscales
    assert slots[0]["source"]["crop"] == {"x": 500, "y": 300, "w": 900, "h": 982}
    assert slots[0]["quality_lock"] == "free"
    assert slots[1]["source"]["crop"] == {"x": 583, "y": 0, "w": 1833, "h": 2000}
    assert slots[1]["quality_lock"] == "no_upscale"
    assert saved.json()["document"]["margins"]["left"] == 120


def test_put_document_lays_out_the_per_split_weights(local: TestClient) -> None:
    """`composition.weights` (§3.4): each split's own shares, checked against the recipe's shape."""
    ids = [photo(local, 3000, 2000 + index) for index in range(3)]
    artwork = create(local, ids, composition={"recipe": "three-hero-left"})
    doc = artwork["document"]
    assert doc["composition"]["weights"] == []
    before = [s["rect"] for s in doc["slots"]]

    doc["composition"]["weights"] = [None, [3, 1]]
    saved = put_document(local, artwork, doc)
    assert saved.status_code == 200, saved.text
    after = [s["rect"] for s in saved.json()["document"]["slots"]]
    assert after[0] == before[0]
    assert (after[1]["h"], after[2]["h"]) == (1380, 460)
    assert saved.json()["document"]["composition"]["weights"] == [None, [3.0, 1.0]]

    artwork = saved.json()
    for bad in ([None, [1, 1, 1]], [None, None, [1, 1]]):
        doc["composition"]["weights"] = bad
        refused = put_document(local, artwork, doc)
        assert refused.status_code == 422, bad
        assert refused.json()["extra"]["errors"][0]["type"] == "weights_shape"


def test_put_document_aligns_the_caption_with_the_block(local: TestClient) -> None:
    ids = [photo(local, 3000, 2000), photo(local, 3000, 2000)]
    artwork = create(local, ids)
    doc = artwork["document"]
    doc["composition"]["caption"] = {"text": "Kyoto", "place": "below", "align": "right"}
    saved = put_document(local, artwork, doc)
    assert saved.status_code == 200, saved.text
    caption = saved.json()["document"]["captions"][0]
    assert (caption["x"], caption["anchor"]) == (3720, "end")


def test_put_document_leaves_a_detached_composition_alone(local: TestClient) -> None:
    """Detached: the slots are the truth, so the payload is stored verbatim (§5)."""
    artwork = create(local, [photo(local, 3000, 2000), photo(local, 3000, 2000)])
    doc = artwork["document"]
    doc["composition"]["detached"] = True
    doc["slots"][0]["rect"] = {"x": 0, "y": 0, "w": 880, "h": 960}
    doc["slots"][0]["source"]["crop"] = {"x": 500, "y": 300, "w": 900, "h": 982}
    doc["slots"][0]["quality_lock"] = "free"
    doc["slots"][0]["rotation"] = 7.5
    saved = put_document(local, artwork, doc)
    assert saved.status_code == 200, saved.text
    slot = saved.json()["document"]["slots"][0]
    assert slot["rect"] == {"x": 0, "y": 0, "w": 880, "h": 960}
    assert slot["rotation"] == 7.5


def test_create_with_a_composition(local: TestClient) -> None:
    ids = [photo(local, 3000, 2000), photo(local, 2000, 3000), photo(local, 2400, 2400)]
    artwork = create(
        local,
        ids,
        composition={
            "recipe": "three-hero-left",
            "format": "3:2",
            "balance": 0.5,
            "border": {"width": 24, "color": "#FFFFFF"},
            "caption": {"text": "Kyoto", "place": "below"},
        },
    )
    doc = artwork["document"]
    assert artwork["origin_layout_id"] is None
    assert doc["placement"] == "manual" and doc["composition"]["format"] == "3:2"
    assert [s["photo_id"] for s in doc["slots"]] == ids
    # every cell carries the border as a band and none of them is rotated
    band = {"width": 24, "color": "#FFFFFF", "bevel": False}
    assert all(s["bands"] == [band] for s in doc["slots"])
    assert all(s["rotation"] == 0 for s in doc["slots"])
    # the hero is 3:2 like the two small cells (§3.5), to within the rounding of both edges
    for slot in doc["slots"]:
        rect = slot["rect"]
        assert abs(rect["w"] - 1.5 * rect["h"]) <= 2.5
    caption = doc["captions"][0]
    assert caption["text"] == "Kyoto" and caption["anchor"] == "middle" and caption["x"] == 1920
    assert caption["font"] == "cormorant-garamond"  # the style's caption defaults
    assert doc["slots"][0]["rect"]["y"] + doc["slots"][0]["rect"]["h"] < caption["y"]


def test_create_composition_errors(local: TestClient) -> None:
    ids = [photo(local, 1200, 800), photo(local, 800, 1200)]
    unknown = local.post(
        f"{API}/artworks", json={"photo_ids": ids, "composition": {"recipe": "nope"}}
    )
    assert unknown.status_code == 422 and unknown.json()["code"] == "unknown_recipe"

    wrong_count = local.post(
        f"{API}/artworks", json={"photo_ids": ids, "composition": {"recipe": "four-grid"}}
    )
    assert wrong_count.status_code == 422 and wrong_count.json()["code"] == "recipe_slot_count"

    seven = [photo(local) for _ in range(7)]
    none_for_count = local.post(f"{API}/artworks", json={"photo_ids": seven})
    assert none_for_count.status_code == 422 and none_for_count.json()["code"] == "no_recipe"

    both = local.post(
        f"{API}/artworks",
        json={"photo_ids": ids, "layout_id": "builtin-layout-single", "composition": {}},
    )
    assert both.status_code == 422 and both.json()["code"] == "layout_and_composition"

    bad_balance = local.post(
        f"{API}/artworks",
        json={"photo_ids": ids, "composition": {"recipe": "two-hero-left", "balance": 3}},
    )
    assert bad_balance.status_code == 422
