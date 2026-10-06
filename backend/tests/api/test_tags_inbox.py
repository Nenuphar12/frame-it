"""Tags carried through photos, bulk tagging, categories, Places, the inbox rule and undo.

docs/organization.md §1 (tags), §6 (the inbox); docs/archive-format.md (categories travel).
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from frame_it.domain import archive
from frame_it.services import search
from tests.api.test_archive import apply, export_archive, receive, report_of
from tests.api.test_archive import other_library as other_library  # the fixture
from tests.api.test_artworks import create, photo
from tests.api.test_organization import collection, query, tag
from tests.conftest import ctx_of, make_jpeg, upload_bytes

API = "/api/v1"


def tag_photo(local: TestClient, photo_id: str, *tag_ids: str) -> None:
    res = local.patch(f"{API}/photos/{photo_id}", json={"tag_ids": list(tag_ids)})
    assert res.status_code == 200, res.text


def tags_by_name(local: TestClient, **params: Any) -> dict[str, dict[str, Any]]:
    return {t["name"]: t for t in local.get(f"{API}/tags", params=params).json()}


def ids(items: list[dict[str, Any]]) -> set[str]:
    return {item["id"] for item in items}


def tag_clause(op: str, *tag_ids: str) -> dict[str, Any]:
    return {"op": "and", "clauses": [{"field": "tag", "op": op, "value": list(tag_ids)}]}


# ---- inheritance --------------------------------------------------------------------------------
def test_an_artwork_carries_its_photos_tags(local: TestClient) -> None:
    alice, sea = tag(local, "Alice"), tag(local, "Sea")
    with_alice = photo(local, 1000, 700)
    plain = photo(local, 1100, 700)
    tag_photo(local, with_alice, alice["id"])
    pair = create(local, [with_alice, plain])
    other = create(local, [photo(local, 1200, 700)])
    local.patch(f"{API}/artworks/{other['id']}", json={"tag_ids": [sea["id"]]})

    detail = local.get(f"{API}/artworks/{pair['id']}").json()
    assert detail["tags"] == [] and [t["name"] for t in detail["inherited_tags"]] == ["Alice"]
    listed = {a["id"]: a for a in query(local)}
    assert [t["name"] for t in listed[pair["id"]]["inherited_tags"]] == ["Alice"]

    assert ids(query(local, filter=tag_clause("has_any", alice["id"]))) == {pair["id"]}
    assert ids(query(local, filter=tag_clause("has_any", alice["id"], sea["id"]))) == {
        pair["id"],
        other["id"],
    }
    assert ids(query(local, filter=tag_clause("none", alice["id"]))) == {other["id"]}
    # has_all mixes the two kinds: Alice through a photo, Sea of its own
    local.patch(f"{API}/artworks/{pair['id']}", json={"tag_ids": [sea["id"]]})
    assert ids(query(local, filter=tag_clause("has_all", alice["id"], sea["id"]))) == {pair["id"]}
    # a tag both owned and inherited is listed once, as its own
    local.patch(f"{API}/artworks/{pair['id']}", json={"tag_ids": [alice["id"]]})
    detail = local.get(f"{API}/artworks/{pair['id']}").json()
    assert [t["name"] for t in detail["tags"]] == ["Alice"] and detail["inherited_tags"] == []


def test_tagging_a_photo_later_reaches_search_counts_and_smart_collections(
    local: TestClient,
) -> None:
    kyoto = photo(local, 1000, 700)
    artwork = create(local, [kyoto])
    bob = tag(local, "Bobby")
    smart = collection(local, "Bobby", kind="smart", filter=tag_clause("has_any", bob["id"]))
    assert query(local, q="bobby") == []

    tag_photo(local, kyoto, bob["id"])

    assert ids(query(local, q="bobby")) == {artwork["id"]}  # FTS re-indexed the artwork
    rows = {c["id"]: c for c in local.get(f"{API}/collections").json()}
    assert rows[smart["id"]]["item_count"] == 1
    usage = tags_by_name(local)["Bobby"]
    assert (usage["photo_count"], usage["artwork_count"], usage["own_artwork_count"]) == (1, 1, 0)
    assert (
        smart["id"] in local.get(f"{API}/artworks/{artwork['id']}").json()["smart_collection_ids"]
    )


def test_a_photo_leaving_the_artwork_takes_its_tags_with_it(local: TestClient) -> None:
    alice = tag(local, "Alice")
    first, second = photo(local, 1000, 700), photo(local, 1100, 700)
    tag_photo(local, first, alice["id"])
    artwork = create(local, [first, second])
    trashed = local.post(
        f"{API}/trash/photos", json={"photo_ids": [first], "cascade": "empty_slots"}
    )
    assert trashed.status_code == 200, trashed.text
    assert local.get(f"{API}/artworks/{artwork['id']}").json()["inherited_tags"] == []
    assert query(local, filter=tag_clause("has_any", alice["id"])) == []
    assert tags_by_name(local)["Alice"]["artwork_count"] == 0


def test_renaming_a_photo_tag_reindexes_the_artworks_using_it(local: TestClient) -> None:
    holiday = tag(local, "Holiday")
    pid = photo(local)
    tag_photo(local, pid, holiday["id"])
    artwork = create(local, [pid])
    assert ids(query(local, q="holiday")) == {artwork["id"]}
    local.patch(f"{API}/tags/{holiday['id']}", json={"name": "Vacation"})
    assert query(local, q="holiday") == []
    assert ids(query(local, q="vacation")) == {artwork["id"]}


def test_the_search_index_is_rebuilt_once_when_its_rules_changed(local: TestClient) -> None:
    create(local, [photo(local)])
    ctx = ctx_of(local)
    with ctx.db.session() as s:
        assert not search.needs_rebuild(s)  # startup wrote the marker, writers kept it filled
        # An index written before tag inheritance has no marker: it is rebuilt once.
        s.execute(text("DELETE FROM search_index WHERE entity_type = 'meta'"))
        assert search.needs_rebuild(s)
        assert search.reindex_all(s) == 2  # the photo and the artwork, not the marker
        assert not search.needs_rebuild(s)


# ---- bulk tagging -------------------------------------------------------------------------------
def test_bulk_photo_tags_add_and_remove_without_touching_the_rest(local: TestClient) -> None:
    keep, add, drop = tag(local, "Keep"), tag(local, "Add"), tag(local, "Drop")
    first, second = photo(local, 1000, 700), photo(local, 1100, 700)
    tag_photo(local, first, keep["id"], drop["id"])
    artwork = create(local, [second])

    res = local.post(
        f"{API}/photos/tags",
        json={"photo_ids": [first, second, "missing"], "add": [add["id"]], "remove": [drop["id"]]},
    )
    assert res.status_code == 200 and res.json()["count"] == 2
    names = {
        pid: sorted(t["name"] for t in local.get(f"{API}/photos/{pid}").json()["tags"])
        for pid in (first, second)
    }
    assert names == {first: ["Add", "Keep"], second: ["Add"]}
    # the artwork made of the second photo carries the new tag, and finds it by search
    assert [
        t["name"] for t in local.get(f"{API}/artworks/{artwork['id']}").json()["inherited_tags"]
    ] == ["Add"]
    assert ids(query(local, q="add")) == {artwork["id"]}
    # adding twice is idempotent
    again = local.post(f"{API}/photos/tags", json={"photo_ids": [first], "add": [add["id"]]})
    assert again.status_code == 200
    assert [t["name"] for t in local.get(f"{API}/photos/{first}").json()["tags"]].count("Add") == 1


def test_bulk_tagging_refuses_unknown_and_contradictory_tags(local: TestClient) -> None:
    sea = tag(local, "Sea")
    pid = photo(local)
    unknown = local.post(f"{API}/photos/tags", json={"photo_ids": [pid], "add": ["nope"]})
    assert unknown.status_code == 422 and unknown.json()["code"] == "unknown_tag"
    both = local.post(
        f"{API}/photos/tags", json={"photo_ids": [pid], "add": [sea["id"]], "remove": [sea["id"]]}
    )
    assert both.status_code == 422 and both.json()["code"] == "tag_conflict"


def test_bulk_artwork_tags_only_reach_their_own_tags(local: TestClient) -> None:
    alice, print_ = tag(local, "Alice"), tag(local, "Print")
    pid = photo(local)
    tag_photo(local, pid, alice["id"])
    first, second = create(local, [pid]), create(local, [photo(local, 1300, 800)])

    res = local.post(
        f"{API}/artworks/tags",
        json={"artwork_ids": [first["id"], second["id"]], "add": [print_["id"]]},
    )
    assert res.status_code == 200 and res.json()["count"] == 2
    removed = local.post(
        f"{API}/artworks/tags", json={"artwork_ids": [first["id"]], "remove": [alice["id"]]}
    )
    assert removed.status_code == 200
    detail = local.get(f"{API}/artworks/{first['id']}").json()
    assert [t["name"] for t in detail["tags"]] == ["Print"]
    assert [t["name"] for t in detail["inherited_tags"]] == ["Alice"]  # it belongs to the photo
    usage = tags_by_name(local)["Print"]
    assert (usage["artwork_count"], usage["own_artwork_count"]) == (2, 2)


# ---- recent, unused, categories -----------------------------------------------------------------
def test_recent_order_puts_the_last_attached_tag_first(local: TestClient) -> None:
    old, new = tag(local, "Old"), tag(local, "New")
    pid = photo(local)
    tag_photo(local, pid, old["id"])
    tag_photo(local, pid, old["id"], new["id"])
    names = [t["name"] for t in local.get(f"{API}/tags", params={"sort": "recent"}).json()]
    assert names.index("New") < names.index("Old")
    unused = tag(local, "Unused")
    assert local.get(f"{API}/tags", params={"sort": "recent"}).json()[-1]["id"] == unused["id"]


def test_unused_tags_ignore_nothing_a_trashed_photo_still_carries(local: TestClient) -> None:
    lonely, kept = tag(local, "Lonely"), tag(local, "OnlyInTrash")
    pid = photo(local)
    tag_photo(local, pid, kept["id"])
    local.post(f"{API}/trash/photos", json={"photo_ids": [pid]})
    assert [t["name"] for t in local.get(f"{API}/tags/unused").json()] == ["Lonely"]
    assert local.post(f"{API}/tags/delete-unused").json()["count"] == 1
    names = set(tags_by_name(local))
    assert "Lonely" not in names and "OnlyInTrash" in names
    assert lonely["id"] not in {t["id"] for t in local.get(f"{API}/tags").json()}


def test_categories_crud_and_tags_moving_between_them(local: TestClient) -> None:
    defaults = local.get(f"{API}/tag-categories").json()
    assert [c["name"] for c in defaults] == ["People", "Events", "Themes"]
    people = defaults[0]

    trips = local.post(f"{API}/tag-categories", json={"name": "Trips", "color": "#3B82F6"})
    assert trips.status_code == 201 and trips.json()["color"] == "#3b82f6"
    clash = local.post(f"{API}/tag-categories", json={"name": "trips"})
    assert clash.status_code == 409 and clash.json()["code"] == "category_exists"

    alice = local.post(f"{API}/tags", json={"name": "Alice", "category_id": people["id"]})
    assert alice.status_code == 201 and alice.json()["category_id"] == people["id"]
    # an existing tag keeps its category whatever the picker it was "created" from
    same = local.post(f"{API}/tags", json={"name": "alice", "category_id": trips.json()["id"]})
    assert same.status_code == 200 and same.json()["category_id"] == people["id"]

    japan, rome = tag(local, "Japan"), tag(local, "Rome")
    moved = local.post(
        f"{API}/tags/categorize",
        json={"tag_ids": [japan["id"], rome["id"]], "category_id": trips.json()["id"]},
    )
    assert moved.json()["count"] == 2
    # a PATCH without `category_id` leaves it alone; `null` sends the tag to "Other"
    local.patch(f"{API}/tags/{japan['id']}", json={"color": "#22c55e"})
    assert tags_by_name(local)["Japan"]["category_id"] == trips.json()["id"]
    local.patch(f"{API}/tags/{japan['id']}", json={"category_id": None})
    assert tags_by_name(local)["Japan"]["category_id"] is None
    unknown = local.patch(f"{API}/tags/{japan['id']}", json={"category_id": "nope"})
    assert unknown.status_code == 404

    counts = {c["name"]: c["tag_count"] for c in local.get(f"{API}/tag-categories").json()}
    assert counts["Trips"] == 1 and counts["People"] == 1
    renamed = local.patch(
        f"{API}/tag-categories/{trips.json()['id']}", json={"name": "Travel", "color": ""}
    )
    assert renamed.json()["name"] == "Travel" and renamed.json()["color"] is None
    deleted = local.delete(f"{API}/tag-categories/{trips.json()['id']}")
    assert deleted.json()["count"] == 1
    assert tags_by_name(local)["Rome"]["category_id"] is None  # back to "Other", not deleted


def test_categories_travel_in_an_archive(
    local: TestClient, other_library: Callable[[], TestClient]
) -> None:
    trips = local.post(f"{API}/tag-categories", json={"name": "Trips", "color": "#3b82f6"}).json()
    people = local.get(f"{API}/tag-categories").json()[0]
    japan = local.post(f"{API}/tags", json={"name": "Japan", "category_id": trips["id"]}).json()
    alice = local.post(f"{API}/tags", json={"name": "Alice", "category_id": people["id"]}).json()
    pid = photo(local)
    tag_photo(local, pid, japan["id"], alice["id"])
    create(local, [pid])
    path = export_archive(local)
    with zipfile.ZipFile(path) as zf:
        rows = zf.read(archive.TAG_CATEGORIES.path).decode().splitlines()
    assert len(rows) == 4  # the three defaults and Trips

    other = other_library()
    session = receive(other, path)
    report = report_of(other, session["import_id"])
    # the defaults exist on both sides under other ids: matched by name, never duplicated
    assert report["tag_category"]["matched"] == 3 and report["tag_category"]["new"] == 1
    apply(other, session["import_id"])
    categories = {c["name"]: c for c in other.get(f"{API}/tag-categories").json()}
    assert sorted(categories) == ["Events", "People", "Themes", "Trips"]
    theirs = tags_by_name(other)
    assert theirs["Japan"]["category_id"] == categories["Trips"]["id"]
    assert theirs["Alice"]["category_id"] == categories["People"]["id"]
    # imported photo tags reach the imported artwork (inheritance, search)
    assert ids(query(other, q="japan"))

    again = receive(other, path)
    report = report_of(other, again["import_id"])
    assert report["tag_category"]["conflicting"] == 0 and report["tag"]["conflicting"] == 0


def test_an_archive_without_categories_still_imports(
    local: TestClient, other_library: Callable[[], TestClient], tmp_path: Path
) -> None:
    """Archives written before categories have no `tag_categories.jsonl` and no `category_id`."""
    pid = photo(local)
    tag_photo(local, pid, tag(local, "Old")["id"])
    path = export_archive(local)
    older = tmp_path / "older.tfarchive"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(older, "w") as dst:
        for item in src.infolist():
            if item.filename == archive.TAG_CATEGORIES.path:
                continue
            body = src.read(item.filename)
            if item.filename == archive.CHECKSUMS_NAME:
                body = b"".join(
                    line + b"\n"
                    for line in body.splitlines()
                    if not line.endswith(archive.TAG_CATEGORIES.path.encode())
                )
            dst.writestr(item, body)
    other = other_library()
    session = receive(other, older)
    assert session["state"] == "ready", session
    apply(other, session["import_id"])
    assert tags_by_name(other)["Old"]["category_id"] is None


# ---- places -------------------------------------------------------------------------------------
def test_places_count_photos_and_artworks_per_level(local: TestClient) -> None:
    kyoto = make_jpeg(1000, 700, (10, 20, 30), gps=(35.0116, 135.7681))
    osaka = make_jpeg(1100, 700, (40, 50, 60), gps=(34.6937, 135.5023))
    for name, data in (("kyoto.jpg", kyoto), ("osaka.jpg", osaka)):
        upload_bytes(local, data, name)
    placed = {p["original_filename"]: p for p in local.get(f"{API}/photos").json()["items"]}
    create(local, [placed["kyoto.jpg"]["id"], placed["osaka.jpg"]["id"]])
    photo(local)  # no GPS

    body = local.get(f"{API}/places").json()
    assert body["unplaced_photos"] == 1
    [japan] = body["countries"]
    # one artwork made of photos from two cities counts once for the country
    assert (japan["name"], japan["photo_count"], japan["artwork_count"]) == ("Japan", 2, 1)
    cities = {c["name"] for region in japan["children"] for c in region["children"]}
    assert cities == {placed[n]["place_name"] for n in ("kyoto.jpg", "osaka.jpg")}
    assert sum(r["photo_count"] for r in japan["children"]) == 2


# ---- the inbox rule -----------------------------------------------------------------------------
def inbox_state(local: TestClient, photo_id: str) -> str:
    state: str = local.get(f"{API}/photos/{photo_id}").json()["inbox_state"]
    return state


def test_a_photo_leaves_the_inbox_only_when_its_artwork_is_ready(local: TestClient) -> None:
    pid = photo(local)
    artwork = create(local, [pid])
    assert inbox_state(local, pid) == "inbox"
    inbox = local.get(f"{API}/photos", params={"inbox_state": "inbox"}).json()["items"]
    assert [p["draft_artwork_ids"] for p in inbox] == [[artwork["id"]]]

    assert local.post(f"{API}/artworks/{artwork['id']}/validate").status_code == 200
    assert inbox_state(local, pid) == "processed"
    assert local.get(f"{API}/photos/{pid}").json()["draft_artwork_ids"] == []

    # one-way: back to draft does not bring it back, nor does trashing the artwork
    local.patch(f"{API}/artworks/{artwork['id']}", json={"status": "draft"})
    assert inbox_state(local, pid) == "processed"
    local.post(f"{API}/trash/artworks", json={"artwork_ids": [artwork["id"]]})
    assert inbox_state(local, pid) == "processed"
    # …but the user can, by hand
    assert local.post(f"{API}/inbox/restore", json={"photo_ids": [pid]}).json()["count"] == 1
    assert inbox_state(local, pid) == "inbox"


def test_ready_through_patch_moves_photos_too_and_dismissed_stays_dismissed(
    local: TestClient,
) -> None:
    kept, dismissed = photo(local, 1000, 700), photo(local, 1100, 700)
    local.post(f"{API}/inbox/dismiss", json={"photo_ids": [dismissed]})
    artwork = create(local, [kept, dismissed])
    res = local.patch(f"{API}/artworks/{artwork['id']}", json={"status": "ready"})
    assert res.status_code == 200 and res.json()["status"] == "ready"
    assert inbox_state(local, kept) == "processed"
    assert inbox_state(local, dismissed) == "dismissed"


def test_an_incomplete_artwork_cannot_take_photos_out_of_the_inbox(local: TestClient) -> None:
    first, second = photo(local, 1000, 700), photo(local, 1100, 700)
    artwork = create(local, [first, second])
    local.post(f"{API}/trash/photos", json={"photo_ids": [second], "cascade": "empty_slots"})
    res = local.post(f"{API}/artworks/{artwork['id']}/validate")
    assert res.status_code == 422 and res.json()["code"] == "artwork_incomplete"
    assert inbox_state(local, first) == "inbox"


# ---- duplicates keep the batch's meta -----------------------------------------------------------
def test_a_duplicate_upload_keeps_the_batch_tags_collections_and_favourite(
    local: TestClient,
) -> None:
    data = make_jpeg(1500, 1000, (90, 80, 70))
    upload_bytes(local, data, "first.jpg")
    pid = local.get(f"{API}/photos").json()["items"][0]["id"]
    trip, existing = tag(local, "Trip"), tag(local, "Existing")
    tag_photo(local, pid, existing["id"])
    box = collection(local, "Wall")

    again = upload_bytes(
        local,
        data,
        "first.jpg",
        tag_ids=[trip["id"]],
        collection_ids=[box["id"]],
        favorite=True,
    )
    assert again["status"] == "exists"
    names = sorted(t["name"] for t in local.get(f"{API}/photos/{pid}").json()["tags"])
    assert names == ["Existing", "Trip"]  # added, not replaced
    artwork = create(local, [pid])
    assert artwork["favorite"] is True
    assert box["id"] in local.get(f"{API}/artworks/{artwork['id']}").json()["collection_ids"]


# ---- undo ---------------------------------------------------------------------------------------
def test_undo_restores_exactly_the_trashed_batch(local: TestClient) -> None:
    first, second = create(local, [photo(local, 1000, 700)]), create(local, [photo(local)])
    res = local.post(f"{API}/trash/artworks", json={"artwork_ids": [first["id"]]})
    batch = res.json()["batch_id"]
    local.post(f"{API}/trash/artworks", json={"artwork_ids": [second["id"]]})
    restored = local.post(f"{API}/trash/restore", json={"batch_ids": [batch]})
    assert restored.json()["artworks"] == 1
    assert ids(query(local)) == {first["id"]}
