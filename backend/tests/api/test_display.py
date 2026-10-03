"""Pushing a set to a TV (`docs/tv-display.md`), driven against `FakeTv`.

The fake encodes what the real 2025 Frame does, so these tests are about the rules that cost us a
round of hardware testing: the push order (stop → select → start), reverse upload order, never
deleting somebody else's photos, and idempotence.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.api.test_artworks import create, photo
from tests.conftest import ctx_of, pair
from the_frame_v2.app import use_fake_tv
from the_frame_v2.db.models import DisplayTarget, DisplayTargetItem, Job
from the_frame_v2.events import Event
from the_frame_v2.services import display
from the_frame_v2.tv import DiscoveredTv, FakeTv

API = "/api/v1"


def use_fake(client: TestClient, tv: FakeTv | None = None) -> FakeTv:
    """Point the app's display service at an in-memory TV."""
    fake = tv or FakeTv()
    ctx_of(client).tv_factory = lambda _target: fake
    return fake


def make_target(
    local: TestClient, host: str = "192.0.2.10", mac: str | None = None
) -> dict[str, Any]:
    payload = {"name": "Living room", "host": host, **({"mac": mac} if mac else {})}
    res = local.post(f"{API}/display/targets", json=payload)
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


def test_a_tv_that_is_off_says_so_and_is_not_looked_for(local: TestClient) -> None:
    # Off, a Frame still takes the connection: "is it on the network?" would be the wrong hint,
    # and so would scanning the LAN for a TV that answered at its own address.
    fake = FakeTv(art_ready=False)
    asked = moving_tv(local, fake)
    target = make_target(local, host=fake.host, mac=fake.mac)
    set_of(local, target["id"], artworks(local, 1))

    job = push(local, target["id"])
    assert job["state"] == "failed"
    assert job["code"] == "tv_art_unavailable"
    assert not fake.uploads
    assert asked == []
    listed = local.get(f"{API}/display/targets").json()["targets"][0]
    assert listed["last_error"] == "tv_art_unavailable"
    assert listed["progress"] is None

    status = local.get(f"{API}/display/targets/{target['id']}/status")
    assert status.status_code == 502
    assert status.json()["code"] == "tv_art_unavailable"

    dry = local.post(f"{API}/display/targets/{target['id']}/plan", json={})
    assert dry.status_code == 200, dry.text
    assert dry.json()["tv_error"] == "tv_art_unavailable"


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


# ---- "Don't change" (slideshow_minutes = 0) -------------------------------------------------------


def items_of(local: TestClient, target_id: str) -> list[DisplayTargetItem]:
    with ctx_of(local).db.session() as s:
        return list(
            s.scalars(
                select(DisplayTargetItem).where(DisplayTargetItem.target_id == target_id)
            ).all()
        )


def deletes(fake: FakeTv) -> list[str]:
    return [c for c in fake.calls if c.startswith("delete:")]


def test_dont_change_is_an_accepted_interval(local: TestClient) -> None:
    use_fake(local)
    target = make_target(local)
    res = local.patch(f"{API}/display/targets/{target['id']}", json={"slideshow_minutes": 0})
    assert res.status_code == 200, res.text
    assert res.json()["slideshow_minutes"] == 0
    caps = local.get(f"{API}/display/capabilities").json()
    assert caps["static_display"] is True


def test_dont_change_deletes_nothing_at_all(local: TestClient) -> None:
    fake = use_fake(local, FakeTv().with_existing(3))
    strangers = set(fake.my_ids())
    target = make_target(local)
    first_set = artworks(local, 2)
    set_of(local, target["id"], first_set)
    assert push(local, target["id"], slideshow_minutes=15)["state"] == "done"
    ours_before = set(fake.my_ids()) - strangers
    assert len(ours_before) == 2

    fake.calls.clear()
    single = artworks(local, 1)
    set_of(local, target["id"], single)
    # Even with permission to delete foreign photos, "Don't change" deletes nothing.
    job = push(local, target["id"], slideshow_minutes=0, allow_delete_foreign=True)
    assert job["state"] == "done", job

    assert deletes(fake) == []
    on_tv = set(fake.my_ids())
    assert strangers <= on_tv and ours_before <= on_tv
    assert len(on_tv) == 3 + 2 + 1
    # The new image is shown, and nothing rotates.
    assert fake.slideshow_minutes is None
    assert not [c for c in fake.calls if c.startswith("start_slideshow")]
    shown = fake.current_content_id
    assert shown is not None and shown not in ours_before | strangers

    # The earlier uploads are still ours: never counted as somebody else's.
    rows = items_of(local, target["id"])
    assert len(rows) == 3
    assert sorted(r.position for r in rows if r.position is not None) == [0]
    status = local.get(f"{API}/display/targets/{target['id']}/status").json()
    assert status["foreign"] == 3
    assert status["ours"] == 3

    result = local.get(f"{API}/display/targets").json()["targets"][0]["last_result"]
    assert result["mode"] == "static"
    assert result["left_ours"] == 2
    assert result["foreign_on_tv"] == 3
    assert result["deleted_ours"] == result["deleted_foreign"] == 0
    assert result["warnings"] == []


def test_dont_change_twice_uploads_nothing(local: TestClient) -> None:
    fake = use_fake(local)
    target = make_target(local)
    set_of(local, target["id"], artworks(local, 2))
    push(local, target["id"], slideshow_minutes=0)
    fake.calls.clear()
    push(local, target["id"], slideshow_minutes=0)
    assert not [c for c in fake.calls if c.startswith(("upload:", "delete:"))]


def test_the_map_never_loses_an_upload_static_mirror_static(local: TestClient) -> None:
    fake = use_fake(local, FakeTv().with_existing(2))
    strangers = set(fake.my_ids())
    target = make_target(local)
    set_a, set_b = artworks(local, 2), artworks(local, 2)

    def foreign() -> int:
        body = local.get(f"{API}/display/targets/{target['id']}/status").json()
        return int(body["foreign"])

    set_of(local, target["id"], set_a)
    push(local, target["id"], slideshow_minutes=0)
    assert foreign() == 2

    # Slideshow mode: A leaves the TV (ours, out of the set), the strangers stay.
    set_of(local, target["id"], set_b)
    push(local, target["id"], slideshow_minutes=3)
    assert foreign() == 2
    assert len(set(fake.my_ids()) - strangers) == 2
    assert fake.slideshow_minutes == 3

    # "Don't change" back to A: B stays on the TV — and stays ours.
    set_of(local, target["id"], set_a)
    push(local, target["id"], slideshow_minutes=0)
    assert foreign() == 2
    assert len(set(fake.my_ids()) - strangers) == 4
    assert {r.artwork_id for r in items_of(local, target["id"])} == set(set_a) | set(set_b)

    # And the next slideshow push of A cleans B up, without touching the strangers.
    push(local, target["id"], slideshow_minutes=3)
    assert set(fake.my_ids()) - strangers == {r.content_id for r in items_of(local, target["id"])}
    assert {r.artwork_id for r in items_of(local, target["id"])} == set(set_a)
    assert strangers <= set(fake.my_ids())


# ---- slideshow order -----------------------------------------------------------------------------


def our_order(fake: FakeTv, local: TestClient, target_id: str) -> list[str]:
    """Artwork ids in the order the TV lists them (newest first = the order it plays)."""
    by_content = {r.content_id: r.artwork_id for r in items_of(local, target_id)}
    return [by_content[c] for c in fake.my_ids() if c in by_content]


def test_reordering_a_set_plays_the_new_order_and_loses_nothing(local: TestClient) -> None:
    fake = use_fake(local, FakeTv().with_existing(1))
    target = make_target(local)
    a, b, c = artworks(local, 3)
    set_of(local, target["id"], [a, b, c])
    push(local, target["id"], slideshow_minutes=3)
    assert our_order(fake, local, target["id"]) == [a, b, c]

    set_of(local, target["id"], [b, a, c])
    push(local, target["id"])
    assert our_order(fake, local, target["id"]) == [b, a, c]
    # The old upload of b left the TV instead of turning into a "foreign" photo.
    status = local.get(f"{API}/display/targets/{target['id']}/status").json()
    assert status["ours"] == 3
    assert status["foreign"] == 1


def test_a_changed_middle_artwork_keeps_the_order(local: TestClient) -> None:
    fake = use_fake(local)
    target = make_target(local)
    a, b, c = artworks(local, 3)
    set_of(local, target["id"], [a, b, c])
    push(local, target["id"], slideshow_minutes=3)

    artwork = local.get(f"{API}/artworks/{b}").json()
    document = artwork["document"]
    document["mat"]["color"] = "#204060"
    res = local.put(
        f"{API}/artworks/{b}/document",
        json=document,
        headers={"If-Match": f'"{artwork["document_version"]}"'},
    )
    assert res.status_code == 200, res.text

    fake.calls.clear()
    push(local, target["id"])
    # b and everything before it go up again (newest first), c stays.
    assert len([x for x in fake.calls if x.startswith("upload:")]) == 2
    assert our_order(fake, local, target["id"]) == [a, b, c]
    assert len(fake.my_ids()) == 3


def test_image_dates_always_increase(local: TestClient) -> None:
    fake = use_fake(local)
    target = make_target(local)
    a, b = artworks(local, 2)
    set_of(local, target["id"], [a, b])
    push(local, target["id"], slideshow_minutes=3)
    set_of(local, target["id"], [b, a])
    push(local, target["id"])
    # Newest first, by date too: a TV that sorts on image_date plays the same order.
    dates = [i.image_date or "" for i in fake.items_ if i.category_id == "MY-C0002"]
    assert dates == sorted(dates, reverse=True)
    assert len(set(dates)) == len(dates)


def test_an_interrupted_push_keeps_track_of_what_it_uploaded(local: TestClient) -> None:
    fake = use_fake(local, FakeTv(unreachable_after_uploads=2))
    target = make_target(local)
    ids = artworks(local, 4)
    set_of(local, target["id"], ids)

    job = push(local, target["id"], slideshow_minutes=3)
    assert job["state"] == "failed" and job["code"] == "tv_unreachable"
    # Two images reached the TV before it dropped off: both are in the map, so they are ours.
    assert len(items_of(local, target["id"])) == 2
    listed = local.get(f"{API}/display/targets").json()["targets"][0]
    assert listed["state"] == "error"
    assert listed["last_error"] == "tv_unreachable"
    assert listed["progress"] is None

    fake.reachable = True
    fake.unreachable_after_uploads = None
    fake.calls.clear()
    assert push(local, target["id"])["state"] == "done"
    # The two that made it are reused (they are the tail of the set), the other two go up.
    assert len([x for x in fake.calls if x.startswith("upload:")]) == 2
    assert our_order(fake, local, target["id"]) == ids
    assert deletes(fake) == []


# ---- following a TV that moved --------------------------------------------------------------------


def moving_tv(local: TestClient, fake: FakeTv) -> list[str | None]:
    """The fake answers only at its own address; discovery finds it there. Returns the prefixes
    discovery was asked about."""
    asked: list[str | None] = []
    ctx = ctx_of(local)
    ctx.tv_factory = lambda target: fake if target.host == fake.host else FakeTv(reachable=False)

    def discover(prefix: str | None) -> list[DiscoveredTv]:
        asked.append(prefix)
        return [fake.describe()]

    ctx.tv_discovery = discover
    return asked


def test_a_push_follows_the_tv_to_its_new_address(local: TestClient) -> None:
    fake = FakeTv(host="192.0.2.80")
    asked = moving_tv(local, fake)
    target = make_target(local, host="192.0.2.10", mac=fake.mac.upper())
    set_of(local, target["id"], artworks(local, 1))

    assert push(local, target["id"], slideshow_minutes=3)["state"] == "done"
    assert len(asked) == 1
    listed = local.get(f"{API}/display/targets").json()["targets"][0]
    assert listed["host"] == "192.0.2.80"
    assert listed["last_result"]["moved_from"] == "192.0.2.10"
    assert listed["last_result"]["moved_to"] == "192.0.2.80"
    assert "tv_moved" in listed["last_result"]["warnings"]
    assert len(fake.uploads) == 1


def test_status_follows_the_tv_too(local: TestClient) -> None:
    fake = FakeTv(host="192.0.2.80")
    moving_tv(local, fake)
    target = make_target(local, host="192.0.2.10", mac=fake.mac)
    status = local.get(f"{API}/display/targets/{target['id']}/status")
    assert status.status_code == 200, status.text
    assert status.json()["moved_from"] == "192.0.2.10"
    assert status.json()["target"]["host"] == "192.0.2.80"


def test_without_a_mac_an_unreachable_tv_is_not_looked_for(local: TestClient) -> None:
    fake = FakeTv(host="192.0.2.80")
    asked = moving_tv(local, fake)
    target = make_target(local, host="192.0.2.10")
    set_of(local, target["id"], artworks(local, 1))
    job = push(local, target["id"], slideshow_minutes=3)
    assert job["state"] == "failed" and job["code"] == "tv_unreachable"
    assert asked == []


def test_status_learns_the_mac(local: TestClient) -> None:
    fake = use_fake(local)
    target = make_target(local)
    assert target["mac"] is None
    status = local.get(f"{API}/display/targets/{target['id']}/status").json()
    assert status["target"]["mac"] == fake.mac


# ---- discovery -----------------------------------------------------------------------------------


def test_discover_lists_tvs_and_recommends_the_first_new_frame(local: TestClient) -> None:
    frame = FakeTv(host="192.0.2.71", mac="04:cb:88:1a:2b:3c")
    other = DiscoveredTv(host="192.0.2.5", name="Kitchen", frame_support=False)
    ctx_of(local).tv_discovery = lambda _prefix: [frame.describe(), other]

    found = local.get(f"{API}/display/discover").json()
    assert [(tv["host"], tv["recommended"]) for tv in found["tvs"]] == [
        ("192.0.2.71", True),
        ("192.0.2.5", False),
    ]
    assert found["tvs"][0]["mac"] == "04:cb:88:1a:2b:3c"
    assert found["tvs"][0]["target_id"] is None

    # Added (with its MAC): recognised, no longer recommended.
    added = make_target(local, host="192.0.2.71", mac="04:CB:88:1A:2B:3C")
    assert added["mac"] == "04:cb:88:1a:2b:3c"
    again = local.get(f"{API}/display/discover").json()
    assert again["tvs"][0]["target_id"] == added["id"]
    assert not any(tv["recommended"] for tv in again["tvs"])


# ---- the dry run and the cached counts ------------------------------------------------------------


def plan(local: TestClient, target_id: str, **body: Any) -> dict[str, Any]:
    res = local.post(f"{API}/display/targets/{target_id}/plan", json=body)
    assert res.status_code == 200, res.text
    result: dict[str, Any] = res.json()
    return result


def test_plan_states_what_a_push_will_do(local: TestClient) -> None:
    fake = use_fake(local, FakeTv().with_existing(2))
    target = make_target(local)
    a, b, c = artworks(local, 3)
    set_of(local, target["id"], [a, b, c])
    calls_before = len(fake.calls)

    first = plan(local, target["id"], slideshow_minutes=3)
    assert first["mode"] == "slideshow"
    assert (first["set_count"], first["to_upload"], first["already_there"]) == (3, 3, 0)
    assert first["foreign"] == 2 and first["tv_error"] is None
    assert first["ours_to_remove"] == 0
    # A dry run touches nothing.
    assert not [x for x in fake.calls[calls_before:] if x.split(":")[0] not in {"items", "close"}]

    push(local, target["id"], slideshow_minutes=3)
    again = plan(local, target["id"])
    assert (again["to_upload"], again["already_there"]) == (0, 3)

    # Another set: in slideshow mode the three leave, in "Don't change" they stay.
    d = artworks(local, 1)[0]
    other = {"artwork_ids": [d, c]}
    mirror = plan(local, target["id"], source=other, slideshow_minutes=3)
    assert (mirror["to_upload"], mirror["already_there"], mirror["ours_to_remove"]) == (1, 1, 2)
    static = plan(local, target["id"], source=other, slideshow_minutes=0)
    assert static["mode"] == "static"
    assert (static["to_upload"], static["already_there"], static["ours_left"]) == (1, 1, 2)
    assert static["ours_to_remove"] == 0
    # Planning a different source does not change what the TV is set to show.
    assert local.get(f"{API}/display/targets").json()["targets"][0]["source"]["artwork_ids"] == [
        a,
        b,
        c,
    ]


def test_plan_counts_drafts_and_leaves_them_out_on_request(local: TestClient) -> None:
    use_fake(local)
    target = make_target(local)
    a, b, c = artworks(local, 3)
    assert local.post(f"{API}/artworks/{a}/validate").status_code == 200
    everything = plan(local, target["id"], source={"artwork_ids": [a, b, c]})
    assert everything["drafts"] == 2 and everything["drafts_left_out"] == 0
    assert everything["set_count"] == 3
    finished = plan(local, target["id"], source={"artwork_ids": [a, b, c], "status": "ready"})
    assert finished["drafts"] == 2 and finished["drafts_left_out"] == 2
    assert finished["set_count"] == 1

    # The push honours it too.
    set_of(local, target["id"], [a, b, c], status="ready")
    push(local, target["id"], slideshow_minutes=3)
    assert [r.artwork_id for r in items_of(local, target["id"])] == [a]


def test_plan_without_the_tv_uses_the_map_and_the_cache(local: TestClient) -> None:
    fake = use_fake(local, FakeTv().with_existing(4))
    target = make_target(local)
    set_of(local, target["id"], artworks(local, 2))
    push(local, target["id"], slideshow_minutes=3)

    fake.reachable = False
    offline = plan(local, target["id"])
    assert offline["tv_error"] == "tv_unreachable"
    assert offline["already_there"] == 2
    assert offline["foreign"] == 4  # cached by the push
    assert offline["foreign_checked_at"] is not None


def test_counts_are_cached_by_status_and_push(local: TestClient) -> None:
    use_fake(local, FakeTv().with_existing(3))
    target = make_target(local)
    assert target["foreign_count"] is None and target["checked_at"] is None
    local.get(f"{API}/display/targets/{target['id']}/status")
    listed = local.get(f"{API}/display/targets").json()["targets"][0]
    assert (listed["foreign_count"], listed["ours_count"]) == (3, 0)
    assert listed["checked_at"] is not None

    set_of(local, target["id"], artworks(local, 2))
    push(local, target["id"], slideshow_minutes=3, allow_delete_foreign=True)
    listed = local.get(f"{API}/display/targets").json()["targets"][0]
    assert (listed["foreign_count"], listed["ours_count"]) == (0, 2)
    assert (listed["item_count"], listed["set_count"]) == (2, 2)


def test_a_set_too_large_is_refused_not_cut(
    local: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_fake(local)
    target = make_target(local)
    ids = artworks(local, 3)
    for artwork_id in ids:
        local.patch(f"{API}/artworks/{artwork_id}", json={"favorite": True})
    monkeypatch.setattr(display, "MAX_SET", 2)
    res = local.post(
        f"{API}/display/targets/{target['id']}/plan", json={"source": {"favorite": True}}
    )
    assert res.status_code == 422
    assert res.json()["code"] == "set_too_large"


# ---- progress ------------------------------------------------------------------------------------


def record_events(local: TestClient) -> list[Event]:
    events: list[Event] = []
    broker = ctx_of(local).broker
    original = broker.publish

    def publish(event: Event) -> None:
        events.append(event)
        original(event)

    broker.publish = publish  # type: ignore[method-assign]
    return events


def test_progress_is_published_phase_by_phase(local: TestClient) -> None:
    use_fake(local)
    target = make_target(local)
    set_of(local, target["id"], artworks(local, 3))
    events = record_events(local)

    push(local, target["id"], slideshow_minutes=3)
    progress = [e.data for e in events if e.name == "display.progress"]
    assert progress[0]["phase"] == "queued"
    phases = [p["phase"] for p in progress]
    assert phases.index("rendering") < phases.index("uploading") < phases.index("starting")
    # Each phase reports its end, so the bar reaches the right numbers.
    assert {"phase": "rendering", "done": 3, "total": 3} in [
        {k: p[k] for k in ("phase", "done", "total")} for p in progress
    ]
    assert {"phase": "uploading", "done": 3, "total": 3} in [
        {k: p[k] for k in ("phase", "done", "total")} for p in progress
    ]
    assert all(p["target_id"] == target["id"] for p in progress)
    assert len({p["job_id"] for p in progress}) == 1

    pushed = [e.data for e in events if e.name == "display.pushed"]
    assert len(pushed) == 1 and pushed[0]["uploaded"] == 3 and pushed[0]["mode"] == "slideshow"
    # The running state is gone once it is done; the result stays for the next reload.
    listed = local.get(f"{API}/display/targets").json()["targets"][0]
    assert listed["progress"] is None
    assert listed["state"] == "ready"
    assert listed["last_result"]["uploaded"] == 3
    assert listed["last_result"]["finished_at"] is not None


def test_push_saves_the_rotation_it_was_given(local: TestClient) -> None:
    fake = use_fake(local)
    target = make_target(local)
    set_of(local, target["id"], artworks(local, 1))
    push(local, target["id"], slideshow_minutes=15, slideshow_ordered=False)
    listed = local.get(f"{API}/display/targets").json()["targets"][0]
    assert (listed["slideshow_minutes"], listed["slideshow_ordered"]) == (15, False)
    assert fake.slideshow_minutes == 15 and fake.slideshow_ordered is False
    res = local.post(f"{API}/display/targets/{target['id']}/push", json={"slideshow_minutes": 10})
    assert res.status_code == 422 and res.json()["code"] == "invalid_interval"


# ---- the development switch -------------------------------------------------------------------------


def test_fake_tv_switch_reaches_no_real_tv(local: TestClient) -> None:
    ctx = ctx_of(local)
    use_fake_tv(ctx)
    found = local.get(f"{API}/display/discover").json()["tvs"]
    assert len(found) == 1 and found[0]["recommended"]
    target = local.post(
        f"{API}/display/targets", json={"name": "Fake", "host": found[0]["host"]}
    ).json()
    paired = local.post(f"{API}/display/targets/{target['id']}/pair")
    assert paired.status_code == 200 and paired.json()["paired"] is True
    status = local.get(f"{API}/display/targets/{target['id']}/status").json()
    assert status["foreign"] == 3


def test_a_push_that_fails_before_the_tv_clears_its_progress(local: TestClient) -> None:
    fake = use_fake(local)
    target = make_target(local)
    ids = artworks(local, 1)
    set_of(local, target["id"], ids)
    local.delete(f"{API}/artworks/{ids[0]}")  # the set is now empty

    job = push(local, target["id"], slideshow_minutes=3)
    assert job["state"] == "failed" and job["code"] == "empty_set"
    listed = local.get(f"{API}/display/targets").json()["targets"][0]
    # The "queued" progress is gone, or a reload would show a push waiting forever.
    assert listed["progress"] is None
    assert (listed["state"], listed["last_error"]) == ("error", "empty_set")
    assert not fake.uploads
