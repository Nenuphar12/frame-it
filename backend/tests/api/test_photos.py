from __future__ import annotations

import shutil

from fastapi.testclient import TestClient

from tests.conftest import ctx_of, make_jpeg, pair, upload_bytes


def _seed(client: TestClient, n: int) -> list[str]:
    for i in range(n):
        upload_bytes(client, make_jpeg(64 + i, 48, color=(i, 0, 0)), f"p{i}.jpg")
    return [p["id"] for p in client.get("/api/v1/photos", params={"limit": 500}).json()["items"]]


def test_keyset_pagination_is_stable(local: TestClient) -> None:
    ids = _seed(local, 5)
    seen: list[str] = []
    cursor = None
    while True:
        params: dict[str, object] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = local.get("/api/v1/photos", params=params).json()
        seen += [p["id"] for p in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == ids and len(set(seen)) == 5


def test_invalid_cursor(local: TestClient) -> None:
    assert local.get("/api/v1/photos", params={"cursor": "@@@"}).status_code == 400


def test_search_and_tag_filter(local: TestClient) -> None:
    upload_bytes(local, make_jpeg(color=(1, 2, 3)), "beach.jpg")
    upload_bytes(local, make_jpeg(color=(4, 5, 6)), "mountain.jpg")
    items = local.get("/api/v1/photos", params={"q": "beach"}).json()["items"]
    assert [p["original_filename"] for p in items] == ["beach.jpg"]
    tag = local.post("/api/v1/tags", json={"name": "Sea"}).json()
    local.patch(f"/api/v1/photos/{items[0]['id']}", json={"tag_ids": [tag["id"]]})
    tagged = local.get("/api/v1/photos", params={"tag_id": tag["id"]}).json()["items"]
    assert [p["id"] for p in tagged] == [items[0]["id"]]
    tags = local.get("/api/v1/tags", params={"q": "se"}).json()
    assert tags[0]["photo_count"] == 1


def test_tag_create_is_case_insensitive(local: TestClient) -> None:
    first = local.post("/api/v1/tags", json={"name": "  Kyoto   trip "})
    assert first.status_code == 201 and first.json()["name"] == "Kyoto trip"
    second = local.post("/api/v1/tags", json={"name": "KYOTO TRIP"})
    assert second.status_code == 200 and second.json()["id"] == first.json()["id"]


def test_dismiss_and_restore(local: TestClient) -> None:
    ids = _seed(local, 2)
    assert local.post("/api/v1/inbox/dismiss", json={"photo_ids": [ids[0]]}).json() == {"count": 1}
    assert local.get("/api/v1/photos/stats").json() == {"inbox": 1, "photos": 2}
    local.post("/api/v1/inbox/restore", json={"photo_ids": [ids[0]]})
    assert local.get("/api/v1/photos/stats").json()["inbox"] == 2


def test_derivatives_regenerate_after_cache_clear(local: TestClient) -> None:
    (photo_id,) = _seed(local, 1)
    ctx = ctx_of(local)
    shutil.rmtree(ctx.storage.cache)
    thumb = local.get(f"/api/v1/photos/{photo_id}/thumb/256")
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/webp"
    proxy = local.get(f"/api/v1/photos/{photo_id}/proxy")
    assert proxy.status_code == 200 and proxy.content[:3] == b"\xff\xd8\xff"
    assert local.get(f"/api/v1/photos/{photo_id}/thumb/999").status_code == 422


def test_original_download_admin_only(local: TestClient) -> None:
    data = make_jpeg()
    upload_bytes(local, data)
    photo_id = local.get("/api/v1/photos").json()["items"][0]["id"]
    assert local.get(f"/api/v1/photos/{photo_id}/original").content == data
    phone = pair(local)
    assert phone.get(f"/api/v1/photos/{photo_id}/original").status_code == 403
    assert phone.get(f"/api/v1/photos/{photo_id}/thumb/768").status_code == 200


def test_unknown_tag_rejected(local: TestClient) -> None:
    (photo_id,) = _seed(local, 1)
    res = local.patch(f"/api/v1/photos/{photo_id}", json={"tag_ids": ["nope"]})
    assert res.status_code == 422 and res.json()["code"] == "unknown_tag"
