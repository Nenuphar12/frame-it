"""Merging copies of one photo that differ only by EXIF / file name (Android redaction)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import ctx_of, make_jpeg, sha256, upload_bytes

LOCATED = make_jpeg(gps=(45.764, 4.8357))  # Lyon
REDACTED = make_jpeg(gps_redacted=True)


def _photos(client: TestClient) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = client.get("/api/v1/photos").json()["items"]
    return items


def test_copies_share_a_fingerprint_but_not_a_hash() -> None:
    assert sha256(LOCATED) != sha256(REDACTED)


def test_located_copy_completes_a_redacted_upload(local: TestClient) -> None:
    upload_bytes(local, REDACTED, "1000125423.jpg")
    [before] = _photos(local)
    assert before["place_name"] is None and "location_removed" in before["quality_warnings"]
    local.patch(f"/api/v1/photos/{before['id']}", json={"inbox_state": "processed"})

    upload_bytes(local, LOCATED, "PXL_20260917_082757358.jpg")

    [after] = _photos(local)
    # Receiving a photo again always brings it back to the inbox (services/photo_copies.py).
    assert after["id"] == before["id"] and after["inbox_state"] == "inbox"
    assert after["sha256"] == sha256(LOCATED)
    assert after["place_name"] == "Lyon"
    assert after["original_filename"] == "PXL_20260917_082757358.jpg"
    assert "location_removed" not in after["quality_warnings"]
    storage = ctx_of(local).storage
    assert storage.original_path(sha256(LOCATED), "jpg").read_bytes() == LOCATED
    assert not storage.original_path(sha256(REDACTED), "jpg").exists()
    assert storage.proxy_path(sha256(LOCATED)).exists()
    assert local.get(f"/api/v1/photos/{after['id']}/thumb/256").status_code == 200

    # The redacted file is now known: re-sending it is an immediate duplicate.
    check = local.post("/api/v1/uploads/check", json={"sha256": [sha256(REDACTED)]}).json()
    assert check["results"][0] == {
        **check["results"][0],
        "status": "exists",
        "photo_id": after["id"],
    }


def test_redacted_copy_after_located_one_is_a_duplicate(local: TestClient) -> None:
    upload_bytes(local, LOCATED, "PXL_1.jpg")
    body = upload_bytes(local, REDACTED, "1000125423.jpg")
    assert body["status"] != "failed"
    [photo] = _photos(local)
    assert photo["sha256"] == sha256(LOCATED) and photo["original_filename"] == "PXL_1.jpg"
    assert photo["place_name"] == "Lyon"
    assert (
        local.post(
            "/api/v1/uploads",
            json={"filename": "x.jpg", "size": len(REDACTED), "sha256": sha256(REDACTED)},
        ).json()["status"]
        == "exists"
    )


def test_real_name_from_a_redacted_copy_is_kept(local: TestClient) -> None:
    other_redacted = make_jpeg(gps_redacted=True, make="OtherCam")  # same pixels, different EXIF
    upload_bytes(local, REDACTED, "1000125423.jpg")
    upload_bytes(local, other_redacted, "PXL_20260917_082757358.jpg")
    [photo] = _photos(local)
    assert photo["original_filename"] == "PXL_20260917_082757358.jpg"
    assert photo["sha256"] == sha256(REDACTED) and photo["place_name"] is None


def test_different_images_are_not_merged(local: TestClient) -> None:
    upload_bytes(local, REDACTED, "1.jpg")
    upload_bytes(local, make_jpeg(color=(10, 20, 30), gps=(45.764, 4.8357)), "2.jpg")
    assert len(_photos(local)) == 2


def test_backfill_computes_missing_fingerprints(local: TestClient) -> None:
    from the_frame_v2.db.models import Photo
    from the_frame_v2.services import photo_copies

    upload_bytes(local, REDACTED, "a.jpg")
    ctx = ctx_of(local)
    with ctx.db.session() as s:
        photo = s.query(Photo).one()
        expected = photo.content_fingerprint
        photo.content_fingerprint = None
    assert photo_copies.needs_backfill(ctx)
    assert photo_copies.backfill_fingerprints(ctx) == 1
    with ctx.db.session() as s:
        assert s.query(Photo).one().content_fingerprint == expected
