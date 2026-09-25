"""Pushing a set to a TV (`docs/tv-display.md`), driven against `FakeTv`.

The fake encodes what the real 2025 Frame does, so these tests are about the rules that cost us a
round of hardware testing: the push order (stop → select → start), reverse upload order, never
deleting somebody else's photos, and idempotence.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.api.test_artworks import create, photo
from tests.conftest import ctx_of, pair
from the_frame_v2.db.models import DisplayTarget, Job
from the_frame_v2.tv import FakeTv

API = "/api/v1"


def use_fake(client: TestClient, tv: FakeTv | None = None) -> FakeTv:
    """Point the app's display service at an in-memory TV."""
    fake = tv or FakeTv()
    ctx_of(client).tv_factory = lambda _target: fake
    return fake


def make_target(local: TestClient, host: str = "192.0.2.10") -> dict[str, Any]:
    res = local.post(f"{API}/display/targets", json={"name": "Living room", "host": host})
    assert res.status_code == 201, res.text
    body: dict[str, Any] = res.json()
    # Pairing talks to a real TV; the tests hand the target a token directly.
    ctx = ctx_of(local)
    with ctx.db.session() as s:
        target = s.get(DisplayTarget, body["id"])
        assert target is not None
        target.token = "test-token"
    return body


def set_of(local: TestClient, target_id: str, artwork_ids: list[str], **extra: Any) -> None:
    res = local.put(
        f"{API}/display/targets/{target_id}/source",
        json={"artwork_ids": artwork_ids, "label": "Test set", **extra},
    )
    assert res.status_code == 200, res.text


def push(local: TestClient, target_id: str, **body: Any) -> dict[str, Any]:
    """Queue a push, run it here, and report how the job ended (`/jobs` only lists failures)."""
    res = local.post(f"{API}/display/targets/{target_id}/push", json=body)
    assert res.status_code == 202, res.text
    ctx = ctx_of(local)
    ctx.jobs.run_pending_sync()
    with ctx.db.session() as s:
        job = s.get(Job, res.json()["job_id"])
        assert job is not None
        return {"id": job.id, "state": job.state, "code": job.code, "error": job.error}


def artworks(local: TestClient, count: int) -> list[str]:
    return [create(local, [photo(local, 1200 + i * 10, 800)])["id"] for i in range(count)]


def test_capabilities_are_what_the_tv_accepts(local: TestClient) -> None:
    caps = local.get(f"{API}/display/capabilities").json()
    # Measured on a 2025 Frame: every other interval answers -7.
    assert caps["slideshow_minutes"] == [3, 15, 60, 720, 1440]
    assert caps["scoped_slideshow"] is False
    assert caps["favourites"] is False


def test_push_uploads_set_and_starts_slideshow(local: TestClient) -> None:
    fake = use_fake(local)
    target = make_target(local)
    ids = artworks(local, 3)
    set_of(local, target["id"], ids)
    local.patch(f"{API}/display/targets/{target['id']}", json={"slideshow_minutes": 3})

    job = push(local, target["id"])
    assert job["state"] == "done", job

    assert len(fake.uploads) == 3
    assert fake.slideshow_minutes == 3
    # Stop → select → start: selecting an image stops a running slideshow, so the order matters.
    sequence = [c.split(":")[0] for c in fake.calls if c.split(":")[0] != "close"]
    assert sequence[-3:] == ["stop_slideshow", "select", "start_slideshow"]
    # The TV lists newest first, so the set's first artwork must be uploaded last.
    uploaded = [c.removeprefix("upload:") for c in fake.calls if c.startswith("upload:")]
    assert fake.current_content_id == uploaded[-1]
    assert fake.my_ids()[0] == uploaded[-1]


def test_second_push_uploads_nothing(local: TestClient) -> None:
    fake = use_fake(local)
    target = make_target(local)
    set_of(local, target["id"], artworks(local, 2))
    push(local, target["id"])
    before = dict(fake.uploads)

    fake.calls.clear()
    push(local, target["id"])
    assert fake.uploads == before
    assert not [c for c in fake.calls if c.startswith("upload:")]


def test_foreign_photos_are_kept_unless_allowed(local: TestClient) -> None:
    fake = use_fake(local, FakeTv().with_existing(4))
    strangers = set(fake.my_ids())
    target = make_target(local)
    set_of(local, target["id"], artworks(local, 2))

    push(local, target["id"])
    # Somebody else's photos are still there, and the app said so.
    assert strangers <= set(fake.my_ids())
    status = local.get(f"{API}/display/targets/{target['id']}/status").json()
    assert status["foreign"] == 4
    assert status["ours"] == 2

    push(local, target["id"], allow_delete_foreign=True)
    assert set(fake.my_ids()) & strangers == set()
    assert len(fake.my_ids()) == 2


def test_changed_artwork_replaces_one_image(local: TestClient) -> None:
    fake = use_fake(local)
    target = make_target(local)
    ids = artworks(local, 2)
    set_of(local, target["id"], ids)
    push(local, target["id"])
    first_ids = set(fake.my_ids())

    artwork = local.get(f"{API}/artworks/{ids[0]}").json()
    document = artwork["document"]
    document["mat"]["color"] = "#123456"
    res = local.put(
        f"{API}/artworks/{ids[0]}/document",
        json=document,
        headers={"If-Match": f'"{artwork["document_version"]}"'},
    )
    assert res.status_code == 200, res.text

    fake.calls.clear()
    push(local, target["id"])
    uploads = [c for c in fake.calls if c.startswith("upload:")]
    assert len(uploads) == 1
    assert len(fake.my_ids()) == 2
    assert set(fake.my_ids()) != first_ids


def test_unreachable_tv_fails_the_job_with_a_code(local: TestClient) -> None:
    fake = use_fake(local, FakeTv(reachable=False))
    target = make_target(local)
    set_of(local, target["id"], artworks(local, 1))

    job = push(local, target["id"])
    assert job["state"] == "failed"
    assert job["code"] == "tv_unreachable"
    assert not fake.uploads

    status = local.get(f"{API}/display/targets/{target['id']}/status")
    assert status.status_code == 502
    assert status.json()["code"] == "tv_unreachable"


def test_interval_the_tv_refuses_is_rejected_here(local: TestClient) -> None:
    use_fake(local)
    target = make_target(local)
    res = local.patch(f"{API}/display/targets/{target['id']}", json={"slideshow_minutes": 10})
    assert res.status_code == 422
    assert res.json()["code"] == "invalid_interval"


def test_display_is_admin_only(local: TestClient) -> None:
    uploader = pair(local, "uploader")
    assert uploader.get(f"{API}/display/targets").status_code == 403
    assert uploader.post(f"{API}/display/targets", json={"host": "192.0.2.10"}).status_code == 403
