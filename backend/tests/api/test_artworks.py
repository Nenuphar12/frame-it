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
        "2 × 2",
        "3 × 3",
        "Polaroid pile",
        "1 + 2",
    }
    assert all(s["builtin"] for s in styles)
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
    assert artwork["origin_layout_id"] == "builtin-layout-single"
    assert doc["schema"] == 1 and doc["placement"] == "fit_in_mat" and len(doc["slots"]) == 1
    assert artwork["worst_tier"] == "downscaled" and artwork["photo_count"] == 1
    assert not artwork["is_incomplete"]
    assert local.get(f"{API}/photos/{pid}").json()["inbox_state"] == "processed"
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
    float_slot = collage["document"]["slots"][0]
    assert float_slot["bands"] == [] and float_slot["shadow"]["type"] == "drop"
    auto = create(local, ids[:2])  # default Single has one slot → a built-in 2-slot layout
    assert auto["origin_layout_id"] == "builtin-layout-two-side-by-side"
    partial = create(local, ids[:1], layout_id="builtin-layout-grid-2x2")
    assert partial["is_incomplete"] and partial["photo_count"] == 1

    too_many = local.post(
        f"{API}/artworks", json={"photo_ids": ids, "layout_id": "builtin-layout-single"}
    )
    assert too_many.status_code == 422 and too_many.json()["code"] == "too_many_photos"
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
