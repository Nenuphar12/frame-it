from __future__ import annotations

import io

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from tests.conftest import ctx_of, make_jpeg, pair, sha256, upload_bytes


def _open(client: TestClient, data: bytes, **extra: object) -> dict[str, object]:
    res = client.post(
        "/api/v1/uploads",
        json={"filename": "a.jpg", "size": len(data), "sha256": sha256(data), **extra},
    )
    assert res.status_code == 200, res.text
    body: dict[str, object] = res.json()
    return body


def _patch(client: TestClient, upload_id: object, offset: int, part: bytes) -> httpx.Response:
    res: httpx.Response = client.patch(
        f"/api/v1/uploads/{upload_id}",
        content=part,
        headers={"Upload-Offset": str(offset), "Content-Type": "application/offset+octet-stream"},
    )
    return res


def test_full_upload_creates_inbox_photo_with_metadata(local: TestClient) -> None:
    data = make_jpeg(4000, 3000, gps=(35.0116, 135.7681))
    tag = local.post("/api/v1/tags", json={"name": "Japan"}).json()
    upload_bytes(local, data, "kyoto.jpg", chunk=50_000, tag_ids=[tag["id"]], favorite=True)

    page = local.get("/api/v1/photos", params={"inbox_state": "inbox"}).json()
    assert len(page["items"]) == 1
    photo = page["items"][0]
    assert photo["sha256"] == sha256(data)
    assert (photo["width"], photo["height"]) == (4000, 3000)
    assert photo["camera_make"] == "TestCam"
    assert photo["taken_at"].startswith("2026-04-12T10:30:00")
    assert photo["place_name"] == "Kyoto" and photo["place_country"] == "Japan"
    assert photo["tags"] == [{"id": tag["id"], "name": "Japan", "color": None}]
    assert photo["quality_warnings"] == []

    ctx = ctx_of(local)
    assert ctx.storage.original_path(photo["sha256"], "jpg").read_bytes() == data
    assert ctx.storage.proxy_path(photo["sha256"]).exists()
    assert not list(ctx.storage.uploads.iterdir())
    assert local.get("/api/v1/photos/stats").json() == {"inbox": 1, "photos": 1}


def test_check_and_duplicate_upload(local: TestClient) -> None:
    data = make_jpeg()
    upload_bytes(local, data)
    res = local.post("/api/v1/uploads/check", json={"sha256": [sha256(data), "a" * 64]}).json()
    statuses = [r["status"] for r in res["results"]]
    assert statuses == ["exists", "new"]
    again = _open(local, data)
    assert again["status"] == "exists" and again["photo_id"]


def test_resume_after_interruption(local: TestClient) -> None:
    data = make_jpeg(2000, 1500)
    body = _open(local, data)
    half = len(data) // 2
    assert _patch(local, body["upload_id"], 0, data[:half]).json()["offset"] == half
    # client restarts: re-opening returns the same session and offset
    resumed = _open(local, data)
    assert resumed["upload_id"] == body["upload_id"] and resumed["offset"] == half
    head = local.head(f"/api/v1/uploads/{body['upload_id']}")
    assert head.headers["upload-offset"] == str(half)
    check = local.post("/api/v1/uploads/check", json={"sha256": [sha256(data)]}).json()
    assert check["results"][0]["status"] == "in_progress"
    done = _patch(local, body["upload_id"], half, data[half:]).json()
    assert done["status"] == "processing"
    ctx_of(local).jobs.run_pending_sync()
    assert local.get("/api/v1/photos/stats").json()["photos"] == 1


def test_offset_mismatch(local: TestClient) -> None:
    data = make_jpeg()
    body = _open(local, data)
    res = _patch(local, body["upload_id"], 10, data[10:20])
    assert res.status_code == 409
    assert res.json()["extra"] == {"offset": 0}


def test_checksum_mismatch(local: TestClient) -> None:
    data = make_jpeg()
    res = local.post(
        "/api/v1/uploads", json={"filename": "a.jpg", "size": len(data), "sha256": "b" * 64}
    ).json()
    bad = _patch(local, res["upload_id"], 0, data)
    assert bad.status_code == 422 and bad.json()["code"] == "checksum_mismatch"


def test_chunk_beyond_size_rejected(local: TestClient) -> None:
    data = make_jpeg()
    body = _open(local, data)
    res = _patch(local, body["upload_id"], 0, data + b"extra")
    assert res.status_code == 413


def test_upload_limit(app_factory: object) -> None:
    client = app_factory(max_upload_bytes=100)  # type: ignore[operator]
    res = client.post("/api/v1/uploads", json={"filename": "a", "size": 101, "sha256": "c" * 64})
    assert res.status_code == 413


def test_heic_rejected_with_code(local: TestClient) -> None:
    data = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64
    upload_bytes(local, data, "IMG.HEIC")
    assert local.get("/api/v1/photos/stats").json()["photos"] == 0
    from the_frame_v2.db.models import UploadSession

    with ctx_of(local).db.session() as s:
        session = s.query(UploadSession).one()
        assert (session.state, session.error) == ("failed", "unsupported_format_heic")


def test_corrupt_jpeg_rejected(local: TestClient) -> None:
    data = make_jpeg()[:200]
    upload_bytes(local, data)
    assert local.get("/api/v1/photos/stats").json()["photos"] == 0


def test_uploader_sessions_are_private(local: TestClient) -> None:
    phone = pair(local)
    data = make_jpeg()
    body = _open(phone, data)
    assert local.get(f"/api/v1/uploads/{body['upload_id']}").status_code == 404
    assert phone.get(f"/api/v1/uploads/{body['upload_id']}").status_code == 200


def test_phone_upload_records_device_and_warnings(local: TestClient) -> None:
    phone = pair(local)
    buf = io.BytesIO()
    Image.new("RGB", (1200, 900), (10, 20, 30)).save(buf, "JPEG")
    upload_bytes(phone, buf.getvalue(), "small.jpg")
    photo = local.get("/api/v1/photos").json()["items"][0]
    assert set(photo["quality_warnings"]) == {"metadata_missing", "possibly_downscaled"}


def test_cancel_upload(local: TestClient) -> None:
    data = make_jpeg()
    body = _open(local, data)
    assert local.delete(f"/api/v1/uploads/{body['upload_id']}").status_code == 204
    assert local.get(f"/api/v1/uploads/{body['upload_id']}").status_code == 404


def test_resume_without_meta_keeps_upload_metadata(local: TestClient) -> None:
    data = make_jpeg()
    tag = local.post("/api/v1/tags", json={"name": "Trip"}).json()
    body = _open(local, data, meta={"tag_ids": [tag["id"]], "favorite": True})
    half = len(data) // 2
    _patch(local, body["upload_id"], 0, data[:half])
    resumed = _open(local, data)  # e.g. a restarted client that lost its form state
    _patch(local, resumed["upload_id"], half, data[half:])
    ctx_of(local).jobs.run_pending_sync()
    photo = local.get("/api/v1/photos").json()["items"][0]
    assert [t["name"] for t in photo["tags"]] == ["Trip"]
