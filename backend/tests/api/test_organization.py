"""Phase 9 — tags, collections, the filter AST, search and the trash (docs/organization.md)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.api.test_artworks import create, photo
from tests.conftest import ctx_of

API = "/api/v1"


def collection(local: TestClient, name: str, **extra: Any) -> dict[str, Any]:
    res = local.post(f"{API}/collections", json={"name": name, **extra})
    assert res.status_code == 201, res.text
    body: dict[str, Any] = res.json()
    return body


def tag(local: TestClient, name: str) -> dict[str, Any]:
    res = local.post(f"{API}/tags", json={"name": name})
    assert res.status_code in (200, 201), res.text
    body: dict[str, Any] = res.json()
    return body


def query(local: TestClient, **body: Any) -> list[dict[str, Any]]:
    res = local.post(f"{API}/artworks/query", json=body)
    assert res.status_code == 200, res.text
    items: list[dict[str, Any]] = res.json()["items"]
    return items


# ---- tags ---------------------------------------------------------------------------------------
def test_tag_counts_cover_photos_and_artworks(local: TestClient) -> None:
    holiday = tag(local, "Holiday")
    photo_id = photo(local)
    local.patch(f"{API}/photos/{photo_id}", json={"tag_ids": [holiday["id"]]})
    artwork = create(local, [photo(local, 900, 600)])
    local.patch(f"{API}/artworks/{artwork['id']}", json={"tag_ids": [holiday["id"]]})
    rows = local.get(f"{API}/tags").json()
    row = next(t for t in rows if t["id"] == holiday["id"])
    assert (row["photo_count"], row["artwork_count"]) == (1, 1)


def test_rename_refuses_an_existing_name_and_merge_collapses_duplicates(
    local: TestClient,
) -> None:
    sea, ocean = tag(local, "Sea"), tag(local, "Ocean")
    photo_id = photo(local)
    local.patch(f"{API}/photos/{photo_id}", json={"tag_ids": [sea["id"], ocean["id"]]})

    clash = local.patch(f"{API}/tags/{ocean['id']}", json={"name": "sea"})
    assert clash.status_code == 409 and clash.json()["code"] == "tag_exists"

    merged = local.post(f"{API}/tags/{sea['id']}/merge", json={"source_ids": [ocean["id"]]})
    assert merged.status_code == 200
    assert local.get(f"{API}/tags/").status_code in (404, 405, 307)
    names = {t["name"] for t in local.get(f"{API}/tags").json()}
    assert "Ocean" not in names and "Sea" in names
    # the photo kept exactly one link, not two rows pointing at the same tag
    assert [t["name"] for t in local.get(f"{API}/photos/{photo_id}").json()["tags"]] == ["Sea"]


def test_recolor_and_delete(local: TestClient) -> None:
    row = tag(local, "Winter")
    assert local.patch(f"{API}/tags/{row['id']}", json={"color": "#3355FF"}).json()["color"] == (
        "#3355ff"
    )
    assert local.patch(f"{API}/tags/{row['id']}", json={"color": "nope"}).status_code == 422
    photo_id = photo(local)
    local.patch(f"{API}/photos/{photo_id}", json={"tag_ids": [row["id"]]})
    assert local.delete(f"{API}/tags/{row['id']}").status_code == 204
    assert local.get(f"{API}/photos/{photo_id}").json()["tags"] == []


# ---- collections --------------------------------------------------------------------------------
def test_tree_move_and_cycle_prevention(local: TestClient) -> None:
    root = collection(local, "Trips")
    child = collection(local, "Japan", parent_id=root["id"])
    grandchild = collection(local, "Kyoto", parent_id=child["id"])

    cycle = local.post(f"{API}/collections/{root['id']}/move", json={"parent_id": grandchild["id"]})
    assert cycle.status_code == 422 and cycle.json()["code"] == "collection_cycle"

    moved = local.post(f"{API}/collections/{grandchild['id']}/move", json={"parent_id": None})
    assert moved.status_code == 200 and moved.json()["parent_id"] is None


def test_include_nested_counts(local: TestClient) -> None:
    root = collection(local, "Trips")
    child = collection(local, "Japan", parent_id=root["id"])
    first = create(local, [photo(local, 1000, 700)])
    second = create(local, [photo(local, 1100, 700)])
    local.post(f"{API}/collections/{root['id']}/items", json={"artwork_ids": [first["id"]]})
    local.post(f"{API}/collections/{child['id']}/items", json={"artwork_ids": [second["id"]]})

    rows = {c["id"]: c for c in local.get(f"{API}/collections").json()}
    assert (rows[root["id"]]["item_count"], rows[root["id"]]["nested_count"]) == (1, 2)
    assert (rows[child["id"]]["item_count"], rows[child["id"]]["nested_count"]) == (1, 1)

    only_root = query(local, collection_id=root["id"])
    assert [a["id"] for a in only_root] == [first["id"]]
    nested = query(local, collection_id=root["id"], include_nested=True)
    assert {a["id"] for a in nested} == {first["id"], second["id"]}


def test_nested_counts_never_count_an_artwork_twice(local: TestClient) -> None:
    root = collection(local, "Trips")
    left = collection(local, "Spring", parent_id=root["id"])
    right = collection(local, "Autumn", parent_id=root["id"])
    artwork = create(local, [photo(local)])
    for box in (left, right):
        local.post(f"{API}/collections/{box['id']}/items", json={"artwork_ids": [artwork["id"]]})
    rows = {c["id"]: c for c in local.get(f"{API}/collections").json()}
    assert (rows[root["id"]]["item_count"], rows[root["id"]]["nested_count"]) == (0, 1)


def test_manual_order_survives_a_reorder(local: TestClient) -> None:
    box = collection(local, "Wall")
    ids = [create(local, [photo(local, 900 + n, 600)])["id"] for n in range(3)]
    local.post(f"{API}/collections/{box['id']}/items", json={"artwork_ids": ids})
    assert [a["id"] for a in query(local, collection_id=box["id"], sort="manual")] == ids

    res = local.post(
        f"{API}/collections/{box['id']}/reorder",
        json={"artwork_id": ids[2], "before_id": ids[0]},
    )
    assert res.status_code == 204
    assert [a["id"] for a in query(local, collection_id=box["id"], sort="manual")] == [
        ids[2],
        ids[0],
        ids[1],
    ]


def test_removing_items_and_deleting_a_subtree_keeps_the_artworks(local: TestClient) -> None:
    root = collection(local, "Trips")
    child = collection(local, "Japan", parent_id=root["id"])
    artwork = create(local, [photo(local)])
    local.post(f"{API}/collections/{child['id']}/items", json={"artwork_ids": [artwork["id"]]})

    removed = local.post(
        f"{API}/collections/{child['id']}/items/remove", json={"artwork_ids": [artwork["id"]]}
    )
    assert removed.json()["count"] == 1
    local.post(f"{API}/collections/{child['id']}/items", json={"artwork_ids": [artwork["id"]]})

    assert local.delete(f"{API}/collections/{root['id']}").status_code == 204
    assert local.get(f"{API}/collections").json() == []
    assert local.get(f"{API}/artworks/{artwork['id']}").status_code == 200


def test_manual_sort_needs_a_collection(local: TestClient) -> None:
    res = local.post(f"{API}/artworks/query", json={"sort": "manual"})
    assert res.status_code == 422 and res.json()["code"] == "manual_sort"


def test_manual_sort_refuses_include_nested(local: TestClient) -> None:
    """`position` orders one collection's items: across a subtree it would drop the nested ones."""
    root = collection(local, "Trips")
    child = collection(local, "Japan", parent_id=root["id"])
    here = create(local, [photo(local, 1000, 700)], title="Here")
    below = create(local, [photo(local, 1100, 700)], title="Below")
    local.post(f"{API}/collections/{root['id']}/items", json={"artwork_ids": [here["id"]]})
    local.post(f"{API}/collections/{child['id']}/items", json={"artwork_ids": [below["id"]]})

    res = local.post(
        f"{API}/artworks/query",
        json={"collection_id": root["id"], "include_nested": True, "sort": "manual"},
    )
    assert res.status_code == 422 and res.json()["code"] == "manual_sort_nested"
    # the date orders do span the subtree
    both = query(local, collection_id=root["id"], include_nested=True, sort="created_desc")
    assert {a["id"] for a in both} == {here["id"], below["id"]}


def test_an_artwork_knows_its_collections(local: TestClient) -> None:
    first, second = collection(local, "Walls"), collection(local, "Winter")
    artwork = create(local, [photo(local)])
    assert local.get(f"{API}/artworks/{artwork['id']}").json()["collection_ids"] == []
    for box in (first, second):
        local.post(f"{API}/collections/{box['id']}/items", json={"artwork_ids": [artwork["id"]]})
    ids = local.get(f"{API}/artworks/{artwork['id']}").json()["collection_ids"]
    assert set(ids) == {first["id"], second["id"]}
    local.post(
        f"{API}/collections/{first['id']}/items/remove", json={"artwork_ids": [artwork["id"]]}
    )
    assert local.get(f"{API}/artworks/{artwork['id']}").json()["collection_ids"] == [second["id"]]


def test_include_nested_reaches_a_smart_sub_collection(local: TestClient) -> None:
    """Remark 3: a smart child holds artworks through its filter, not through `collection_items`."""
    root = collection(local, "Trips")
    collection(
        local,
        "Loved",
        parent_id=root["id"],
        kind="smart",
        filter={"op": "and", "clauses": [{"field": "favorite", "op": "eq", "value": True}]},
    )
    filed = create(local, [photo(local, 1000, 700)], title="Filed")
    loved = create(local, [photo(local, 1100, 700)], title="Loved one")
    local.post(f"{API}/collections/{root['id']}/items", json={"artwork_ids": [filed["id"]]})
    local.patch(f"{API}/artworks/{loved['id']}", json={"favorite": True})

    assert [a["id"] for a in query(local, collection_id=root["id"])] == [filed["id"]]
    nested = query(local, collection_id=root["id"], include_nested=True)
    assert {a["id"] for a in nested} == {filed["id"], loved["id"]}
    # and the parent's nested count says so
    rows = {c["id"]: c for c in local.get(f"{API}/collections").json()}
    assert (rows[root["id"]]["item_count"], rows[root["id"]]["nested_count"]) == (1, 2)


def test_an_artwork_reports_the_smart_collections_matching_it(local: TestClient) -> None:
    """Remark 5: smart membership is derived, so it is reported apart from the editable one."""
    box = collection(local, "Walls")
    smart = collection(
        local,
        "Favourites",
        kind="smart",
        filter={"op": "and", "clauses": [{"field": "favorite", "op": "eq", "value": True}]},
    )
    artwork = create(local, [photo(local)])
    local.post(f"{API}/collections/{box['id']}/items", json={"artwork_ids": [artwork["id"]]})
    body = local.get(f"{API}/artworks/{artwork['id']}").json()
    assert body["collection_ids"] == [box["id"]] and body["smart_collection_ids"] == []

    local.patch(f"{API}/artworks/{artwork['id']}", json={"favorite": True})
    body = local.get(f"{API}/artworks/{artwork['id']}").json()
    assert body["collection_ids"] == [box["id"]]
    assert body["smart_collection_ids"] == [smart["id"]]


def test_a_collection_can_be_moved_back_to_the_top_level(local: TestClient) -> None:
    """Remark 4: `parent_id: null` is how a sub-collection leaves its parent."""
    root = collection(local, "Trips")
    child = collection(local, "Japan", parent_id=root["id"])
    moved = local.post(f"{API}/collections/{child['id']}/move", json={"parent_id": None})
    assert moved.status_code == 200 and moved.json()["parent_id"] is None
    rows = {c["id"]: c for c in local.get(f"{API}/collections").json()}
    assert rows[root["id"]]["nested_count"] == 0


# ---- smart collections --------------------------------------------------------------------------
def test_smart_collection_is_a_saved_filter(local: TestClient) -> None:
    favorite = create(local, [photo(local, 1000, 700)])
    plain = create(local, [photo(local, 1100, 700)])
    local.patch(f"{API}/artworks/{favorite['id']}", json={"favorite": True})

    smart = collection(
        local,
        "Loved",
        kind="smart",
        filter={"op": "and", "clauses": [{"field": "favorite", "op": "eq", "value": True}]},
    )
    assert smart["item_count"] == 1
    items = query(local, collection_id=smart["id"])
    assert [a["id"] for a in items] == [favorite["id"]]

    # it updates live: favouriting the other one adds it, no reindex, no re-save
    local.patch(f"{API}/artworks/{plain['id']}", json={"favorite": True})
    assert len(query(local, collection_id=smart["id"])) == 2


def test_a_smart_collection_cannot_reference_itself(local: TestClient) -> None:
    smart = collection(
        local,
        "Loop",
        kind="smart",
        filter={"op": "and", "clauses": [{"field": "favorite", "op": "eq", "value": True}]},
    )
    res = local.patch(
        f"{API}/collections/{smart['id']}",
        json={
            "filter": {
                "op": "and",
                "clauses": [{"field": "collection", "op": "in", "value": smart["id"]}],
            }
        },
    )
    assert res.status_code == 422 and res.json()["code"] == "filter_cycle"


def test_filter_validation_endpoint(local: TestClient) -> None:
    create(local, [photo(local)])
    good = local.post(
        f"{API}/filters/validate",
        json={
            "filter": {"op": "and", "clauses": [{"field": "status", "op": "eq", "value": "draft"}]}
        },
    ).json()
    assert good["valid"] and good["match_count"] == 1
    bad = local.post(
        f"{API}/filters/validate",
        json={"filter": {"op": "and", "clauses": [{"field": "status", "op": "eq", "value": "x"}]}},
    ).json()
    assert bad["valid"] is False and bad["error"]


def test_a_manual_collection_refuses_a_filter(local: TestClient) -> None:
    res = local.post(
        f"{API}/collections",
        json={"name": "Nope", "filter": {"op": "and", "clauses": []}},
    )
    assert res.status_code == 422 and res.json()["code"] == "manual_collection"


# ---- filter AST over the library ----------------------------------------------------------------
def test_filter_clauses_reach_artwork_and_photo_columns(local: TestClient) -> None:
    label = tag(local, "Sunset")
    kyoto = photo(local, 1200, 800)
    artwork = create(local, [kyoto], title="Golden hour")
    local.patch(f"{API}/artworks/{artwork['id']}", json={"tag_ids": [label["id"]]})
    other = create(local, [photo(local, 900, 700)], title="Other")

    def ids(clause: dict[str, Any]) -> set[str]:
        return {a["id"] for a in query(local, filter={"op": "and", "clauses": [clause]})}

    assert ids({"field": "tag", "op": "has_any", "value": [label["id"]]}) == {artwork["id"]}
    assert ids({"field": "tag", "op": "none", "value": [label["id"]]}) == {other["id"]}
    assert ids({"field": "title", "op": "contains", "value": "golden"}) == {artwork["id"]}
    assert ids({"field": "photo_count", "op": "eq", "value": 1}) == {artwork["id"], other["id"]}
    # 1200×800 in a 3840×2160 canvas is upscaled, and `native` matches neither
    assert ids({"field": "worst_tier", "op": "in", "value": ["upscaled"]}) == {
        artwork["id"],
        other["id"],
    }
    assert ids({"field": "worst_tier", "op": "in", "value": ["native"]}) == set()
    # taken_at is a property of the photos an artwork uses (conftest stamps 2026-04-12)
    assert ids({"field": "taken_at", "op": "between", "value": ["2026-04-01", "2026-04-30"]}) == {
        artwork["id"],
        other["id"],
    }
    assert ids({"field": "taken_at", "op": "before", "value": "2026-01-01"}) == set()


def test_or_and_not_groups(local: TestClient) -> None:
    first = create(local, [photo(local, 1000, 700)], title="Alpha")
    second = create(local, [photo(local, 1100, 700)], title="Beta")
    both = query(
        local,
        filter={
            "op": "or",
            "clauses": [
                {"field": "title", "op": "contains", "value": "alpha"},
                {"field": "title", "op": "contains", "value": "beta"},
            ],
        },
    )
    assert {a["id"] for a in both} == {first["id"], second["id"]}
    negated = query(
        local,
        filter={
            "op": "not",
            "clauses": [{"field": "title", "op": "contains", "value": "alpha"}],
        },
    )
    assert {a["id"] for a in negated} == {second["id"]}


def test_an_invalid_filter_is_a_422(local: TestClient) -> None:
    res = local.post(
        f"{API}/artworks/query",
        json={"filter": {"op": "and", "clauses": [{"field": "nope", "op": "eq", "value": 1}]}},
    )
    assert res.status_code == 422 and res.json()["code"] == "invalid_filter"


# ---- search -------------------------------------------------------------------------------------
def test_full_text_search_finds_titles_tags_and_photo_names(local: TestClient) -> None:
    label = tag(local, "Temple")
    artwork = create(local, [photo(local, 1200, 800)], title="Kiyomizu at dawn")
    local.patch(f"{API}/artworks/{artwork['id']}", json={"tag_ids": [label["id"]]})
    create(local, [photo(local, 900, 700)], title="Unrelated")

    assert [a["id"] for a in query(local, q="kiyomizu")] == [artwork["id"]]
    assert [a["id"] for a in query(local, q="temp")] == [artwork["id"]]  # prefix
    assert query(local, q="nothing-here") == []

    photos = local.get(f"{API}/photos", params={"q": "IMG_1200x800"}).json()["items"]
    assert len(photos) == 1


def test_renaming_an_artwork_refreshes_the_index(local: TestClient) -> None:
    artwork = create(local, [photo(local)], title="Before")
    local.put(
        f"{API}/artworks/{artwork['id']}/document",
        json=artwork["document"],
        headers={"If-Match": f'"{artwork["document_version"]}"'},
    )
    local.patch(f"{API}/artworks/{artwork['id']}", json={"title": "Mountain hut"})
    assert [a["id"] for a in query(local, q="mountain")] == [artwork["id"]]
    assert query(local, q="before") == []


# ---- trash --------------------------------------------------------------------------------------
def test_trashing_a_photo_lists_the_artworks_and_trashes_them(local: TestClient) -> None:
    photo_id = photo(local, 1200, 800)
    artwork = create(local, [photo_id])

    preview = local.post(f"{API}/trash/preview", json={"photo_ids": [photo_id]}).json()
    assert preview["artworks"][0]["artwork_id"] == artwork["id"]
    assert preview["artworks"][0]["slot_count"] == 1

    res = local.post(f"{API}/trash/photos", json={"photo_ids": [photo_id]})
    assert res.status_code == 200
    body = res.json()
    assert (body["photos"], body["artworks"], body["emptied"]) == (1, 1, 0)
    assert local.get(f"{API}/photos/{photo_id}").status_code == 404
    assert local.get(f"{API}/artworks/{artwork['id']}").status_code == 404

    # one batch: restoring it brings the photo and the artwork back together
    restored = local.post(f"{API}/trash/restore", json={"batch_ids": [body["batch_id"]]}).json()
    assert (restored["photos"], restored["artworks"]) == (1, 1)
    assert local.get(f"{API}/artworks/{artwork['id']}").status_code == 200


def test_the_empty_slots_cascade_keeps_the_artwork(local: TestClient) -> None:
    kept, dropped = photo(local, 1200, 800), photo(local, 1000, 800)
    artwork = create(local, [kept, dropped])

    res = local.post(f"{API}/trash/photos", json={"photo_ids": [dropped], "cascade": "empty_slots"})
    assert res.json()["emptied"] == 1
    after = local.get(f"{API}/artworks/{artwork['id']}").json()
    assert after["status"] == "draft" and after["is_incomplete"] is True
    photo_ids = [s["photo_id"] for s in after["document"]["slots"]]
    assert photo_ids == [kept, None]
    # the change is undoable: a pre_trash snapshot was taken first
    reasons = [s["reason"] for s in local.get(f"{API}/artworks/{artwork['id']}/snapshots").json()]
    assert "pre_trash" in reasons


def test_trash_listing_and_purge_frees_disk(local: TestClient) -> None:
    photo_id = photo(local, 1200, 800)
    artwork = create(local, [photo_id])
    ctx = ctx_of(local)
    ctx.jobs.run_pending_sync()  # render, so there is a cache directory to free
    original = ctx.storage.original_path(
        local.get(f"{API}/photos/{photo_id}").json()["sha256"], "jpg"
    )
    assert original.exists()

    local.post(f"{API}/trash/photos", json={"photo_ids": [photo_id]})
    listed = local.get(f"{API}/trash").json()
    assert listed["photo_total"] == 1 and listed["artwork_total"] == 1
    assert listed["retention_days"] == 30

    purged = local.post(f"{API}/trash/purge", json={"all": True}).json()
    assert (purged["photos"], purged["artworks"]) == (1, 1)
    assert purged["bytes_freed"] > 0
    assert not original.exists()
    assert not ctx.storage.render_dir(artwork["id"]).exists()
    assert local.get(f"{API}/trash").json()["photo_total"] == 0


def test_purge_respects_the_retention_window(local: TestClient) -> None:
    photo_id = photo(local)
    local.post(f"{API}/trash/photos", json={"photo_ids": [photo_id]})
    kept = local.post(f"{API}/trash/purge", json={"all": False}).json()
    assert kept["photos"] == 0
    assert local.get(f"{API}/trash").json()["photo_total"] == 1


def test_trashed_items_leave_the_library_and_the_index(local: TestClient) -> None:
    artwork = create(local, [photo(local)], title="Ephemeral")
    local.post(f"{API}/trash/artworks", json={"artwork_ids": [artwork["id"]]})
    assert query(local, q="ephemeral") == []
    assert query(local) == []


def test_an_uploader_cannot_empty_the_trash(local: TestClient) -> None:
    from tests.conftest import pair

    uploader = pair(local, "uploader")
    assert uploader.get(f"{API}/trash").status_code == 403
    assert uploader.post(f"{API}/trash/purge", json={"all": True}).status_code == 403
    # but it may browse (mobile read-only, §6)
    assert uploader.get(f"{API}/artworks").status_code == 200
    assert uploader.get(f"{API}/collections").status_code == 200
