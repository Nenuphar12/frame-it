"""Phase 10 — export / import (docs/archive-format.md).

The AC (`docs/PLAN.md` §14): a full export imported into an empty library gives the same content
and the same renders; a partial import into a populated one classifies new / identical /
conflicting correctly and all three policies work; a malicious archive is refused.

Two libraries are two apps over two data dirs — `app_factory` builds one per call, so an export
from `local` is imported into `other` with nothing shared but the file.
"""

from __future__ import annotations

import io
import itertools
import json
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.test_artworks import create, photo
from tests.api.test_organization import collection, tag
from tests.conftest import ctx_of
from the_frame_v2.domain import archive

API = "/api/v1"


@pytest.fixture
def other_library(
    app_factory: Callable[..., TestClient], tmp_path: Path
) -> Callable[[], TestClient]:
    """Build another *empty* library — its own data dir, its own database, its own originals."""
    counter = itertools.count(1)

    def make() -> TestClient:
        return app_factory(data_dir=tmp_path / f"library-{next(counter)}")

    return make


# ---- helpers ------------------------------------------------------------------------------------
def export_archive(client: TestClient, **body: Any) -> Path:
    """Queue an export, run the job, and return the file it wrote."""
    res = client.post(f"{API}/exports", json=body)
    assert res.status_code == 202, res.text
    job_id = res.json()["job_id"]
    ctx_of(client).jobs.run_pending_sync()
    status = client.get(f"{API}/exports/{job_id}").json()
    assert status["state"] == "done", status
    download = client.get(f"{API}/exports/{job_id}/download")
    assert download.status_code == 200
    assert status["filename"] in download.headers["content-disposition"]
    path = Path(ctx_of(client).storage.export_dir(job_id)) / str(status["filename"])
    assert path.is_file()
    return path


def receive(client: TestClient, path: Path, chunk: int = 0) -> dict[str, Any]:
    """Upload an archive through the chunked protocol and stage it."""
    data = path.read_bytes()
    res = client.post(f"{API}/imports", json={"filename": path.name, "size": len(data)})
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    step = chunk or len(data)
    offset = body["offset"]
    while offset < len(data):
        res = client.patch(
            f"{API}/imports/{body['import_id']}",
            content=data[offset : offset + step],
            headers={
                "Upload-Offset": str(offset),
                "Content-Type": "application/offset+octet-stream",
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        offset = body["offset"]
    ctx_of(client).jobs.run_pending_sync()
    return dict(client.get(f"{API}/imports/{body['import_id']}").json())


def report_of(client: TestClient, import_id: str) -> dict[str, dict[str, Any]]:
    res = client.get(f"{API}/imports/{import_id}/report")
    assert res.status_code == 200, res.text
    return {kind["kind"]: kind for kind in res.json()["kinds"]}


def apply(client: TestClient, import_id: str, **policies: Any) -> dict[str, Any]:
    res = client.post(f"{API}/imports/{import_id}/apply", json=policies)
    assert res.status_code == 200, res.text
    ctx_of(client).jobs.run_pending_sync()
    body: dict[str, Any] = res.json()
    return body


def entries(kind: dict[str, Any]) -> dict[str, str]:
    return {item["name"]: item["status"] for item in kind["items"]}


def seed(local: TestClient) -> dict[str, Any]:
    """A small library: two artworks, a tag, a manual collection, a user style."""
    holiday = tag(local, "Holiday")
    first = create(local, [photo(local, 1600, 1200)], title="Harbour")
    second = create(local, [photo(local, 1200, 1600), photo(local, 900, 900)], title="Diptych")
    local.patch(
        f"{API}/artworks/{first['id']}", json={"tag_ids": [holiday["id"]], "favorite": True}
    )
    trip = collection(local, "Trip")
    local.post(f"{API}/collections/{trip['id']}/items", json={"artwork_ids": [first["id"]]})
    style = local.post(
        f"{API}/frame-styles/from-artwork", json={"artwork_id": first["id"], "name": "My style"}
    )
    assert style.status_code == 201, style.text
    ctx_of(local).jobs.run_pending_sync()
    return {"tag": holiday, "first": first, "second": second, "collection": trip}


def library_snapshot(client: TestClient) -> dict[str, Any]:
    """What the AC compares: the content of the library as the API reports it."""
    artworks = client.post(f"{API}/artworks/query", json={"limit": 500}).json()["items"]
    detail = [client.get(f"{API}/artworks/{a['id']}").json() for a in artworks]
    return {
        "artworks": sorted(
            (
                a["title"],
                a["favorite"],
                a["photo_count"],
                a["worst_tier"],
                a["render_hash"],
                json.dumps(a["document"], sort_keys=True),
                sorted(t["name"] for t in a["tags"]),
            )
            for a in detail
        ),
        "photos": sorted(
            (p["original_filename"], p["width"], p["height"])
            for p in client.get(f"{API}/photos?limit=200").json()["items"]
        ),
        "tags": sorted(t["name"] for t in client.get(f"{API}/tags").json()),
        "collections": sorted(
            (c["name"], c["kind"], c["item_count"]) for c in client.get(f"{API}/collections").json()
        ),
        "styles": sorted(
            (s["name"], json.dumps(s["document"], sort_keys=True))
            for s in client.get(f"{API}/frame-styles").json()
            if not s["builtin"]
        ),
    }


# ---- export -------------------------------------------------------------------------------------
def test_full_archive_holds_the_documented_layout(local: TestClient) -> None:
    seed(local)
    path = export_archive(local, include_renders=True)
    assert path.name.endswith(archive.ARCHIVE_SUFFIX)
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read(archive.MANIFEST_NAME))
        checksums = zf.read(archive.CHECKSUMS_NAME).decode()
        photos = [json.loads(line) for line in zf.read("data/photos.jsonl").splitlines()]
    assert names >= {entity.path for entity in archive.ENTITIES} | {
        archive.MANIFEST_NAME,
        archive.CHECKSUMS_NAME,
        archive.SETTINGS_NAME,
    }
    assert manifest["format"] == archive.FORMAT and manifest["scope"] == "full"
    assert manifest["counts"]["artwork"] == 2 and manifest["counts"]["photo"] == 3
    assert manifest["includes_renders"] and manifest["counts"]["render"] == 2
    # `sha256sum -c` format, and the originals are stored under their own digest
    assert all(len(line.split("  ")[0]) == 64 for line in checksums.splitlines())
    for row in photos:
        assert f"originals/{row['sha256']}.{row['ext']}" in names
    assert any(name.startswith("renders/") for name in names)


def test_partial_export_follows_the_collection_and_drops_the_rest(local: TestClient) -> None:
    data = seed(local)
    path = export_archive(local, collection_ids=[data["collection"]["id"]])
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read(archive.MANIFEST_NAME))
        artworks = [json.loads(line) for line in zf.read("data/artworks.jsonl").splitlines()]
        assert archive.SETTINGS_NAME not in zf.namelist()  # settings are not part of a selection
        swatches = zf.read("data/swatches.jsonl")
    assert manifest["scope"] == "partial"
    assert [a["title"] for a in artworks] == ["Harbour"]
    assert manifest["counts"]["photo"] == 1 and manifest["counts"]["tag"] == 1
    assert swatches == b""


def test_rendered_images_export_lays_out_collections(local: TestClient) -> None:
    data = seed(local)
    sub = collection(local, "Kyoto", parent_id=data["collection"]["id"])
    local.post(f"{API}/collections/{sub['id']}/items", json={"artwork_ids": [data["first"]["id"]]})
    path = export_archive(local, kind="renders", render_format="jpg")
    with zipfile.ZipFile(path) as zf:
        names = sorted(n for n in zf.namelist() if n != archive.CHECKSUMS_NAME)
    assert names == ["Trip/Harbour.jpg", "Trip/Kyoto/Harbour.jpg", "Unsorted/Diptych.jpg"]


# ---- round trip ---------------------------------------------------------------------------------
def test_full_round_trip_into_an_empty_library(
    local: TestClient, other_library: Callable[[], TestClient]
) -> None:
    seed(local)
    before = library_snapshot(local)
    path = export_archive(local, include_renders=True)

    other = other_library()
    session = receive(other, path, chunk=64 * 1024)
    assert session["state"] == "ready" and session["scope"] == "full"
    report = report_of(other, session["import_id"])
    assert report["photo"]["new"] == 3 and report["photo"]["conflicting"] == 0
    assert report["artwork"]["new"] == 2
    assert report["collection"]["new"] == 1 and report["frame_style"]["new"] == 1

    result = apply(other, session["import_id"])
    assert result["created"]["artwork"] == 2 and result["created"]["photo"] == 3
    # The archive carried renders made by this very renderer: they are adopted, not redone.
    assert result["renders_adopted"] == 2 and result["renders_queued"] == 0
    assert library_snapshot(other) == before
    assert other.get(f"{API}/imports/{session['import_id']}").json()["state"] == "applied"

    # Re-importing the same archive changes nothing: everything is identical.
    again = receive(other, path)
    assert report_of(other, again["import_id"])["artwork"]["identical"] == 2
    apply(other, again["import_id"])
    assert library_snapshot(other) == before


def test_originals_are_content_addressed_and_shared_between_photos(
    local: TestClient, other_library: Callable[[], TestClient]
) -> None:
    photo(local, 1000, 700)
    path = export_archive(local)
    other = other_library()
    session = receive(other, path)
    apply(other, session["import_id"])
    storage = ctx_of(other).storage
    photos = other.get(f"{API}/photos").json()["items"]
    row = other.get(f"{API}/photos/{photos[0]['id']}").json()
    assert storage.original_path(row["sha256"], "jpg").is_file()
    assert other.get(f"{API}/photos/{photos[0]['id']}/thumb/256").status_code == 200


# ---- classification & policies ------------------------------------------------------------------
def test_a_photo_is_its_bytes_so_ids_are_remapped(
    local: TestClient, other_library: Callable[[], TestClient]
) -> None:
    """The same file uploaded to both libraries has two ids: the import must follow the bytes."""
    artwork = create(local, [photo(local, 1600, 1200)], title="Harbour")
    path = export_archive(local)

    other = other_library()
    mine = photo(other, 1600, 1200)  # same generated bytes, a different id
    session = receive(other, path)
    report = report_of(other, session["import_id"])
    assert report["photo"]["matched"] == 1 and report["photo"]["new"] == 0

    apply(other, session["import_id"])
    assert len(other.get(f"{API}/photos").json()["items"]) == 1
    imported = other.get(f"{API}/artworks/{artwork['id']}").json()
    assert [slot["photo_id"] for slot in imported["document"]["slots"]] == [mine]


def test_a_remapped_photo_does_not_make_the_artwork_look_conflicting(
    local: TestClient, other_library: Callable[[], TestClient]
) -> None:
    """The comparison runs on the *translated* record, or every re-import invents conflicts."""
    create(local, [photo(local, 1600, 1200)], title="Harbour")
    path = export_archive(local)

    other = other_library()
    photo(other, 1600, 1200)  # the same bytes under another id: the document must be remapped
    session = receive(other, path)
    apply(other, session["import_id"])

    again = receive(other, path)
    report = report_of(other, again["import_id"])
    assert (report["artwork"]["identical"], report["artwork"]["conflicting"]) == (1, 0)
    assert report["photo"]["matched"] == 1
    result = apply(other, again["import_id"])
    assert result["created"] == {} and result["updated"] == {}


def test_tags_merge_by_name(local: TestClient, other_library: Callable[[], TestClient]) -> None:
    holiday = tag(local, "Holiday")
    artwork = create(local, [photo(local)])
    local.patch(f"{API}/artworks/{artwork['id']}", json={"tag_ids": [holiday["id"]]})
    path = export_archive(local)

    other = other_library()
    theirs = tag(other, "holiday")  # same tag, other case, other id
    session = receive(other, path)
    assert report_of(other, session["import_id"])["tag"]["matched"] == 1
    apply(other, session["import_id"])
    rows = other.get(f"{API}/tags").json()
    assert [(t["id"], t["name"], t["artwork_count"]) for t in rows] == [
        (theirs["id"], "holiday", 1)
    ]


def test_conflicting_artwork_and_the_three_policies(
    local: TestClient, other_library: Callable[[], TestClient]
) -> None:
    artwork = create(local, [photo(local, 1600, 1200)], title="Harbour")
    path = export_archive(local)

    def clash(client: TestClient) -> None:
        """Same archive, but the target already holds that artwork under another title."""
        session = receive(client, path)
        apply(client, session["import_id"])
        client.patch(f"{API}/artworks/{artwork['id']}", json={"title": "Mine"})

    keep_mine = other_library()
    clash(keep_mine)
    session = receive(keep_mine, path)
    report = report_of(keep_mine, session["import_id"])
    assert report["artwork"]["conflicting"] == 1
    assert entries(report["artwork"]) == {"Harbour": "conflicting"}
    apply(keep_mine, session["import_id"], default="keep_mine")
    titles = [a["title"] for a in keep_mine.post(f"{API}/artworks/query", json={}).json()["items"]]
    assert titles == ["Mine"]

    take_theirs = other_library()
    clash(take_theirs)
    session = receive(take_theirs, path)
    apply(take_theirs, session["import_id"], default="take_theirs")
    items = take_theirs.post(f"{API}/artworks/query", json={}).json()["items"]
    assert [a["title"] for a in items] == ["Harbour"]
    # The snapshot taken before overwriting *is* the undo (§12.2 step 4).
    snapshots = take_theirs.get(f"{API}/artworks/{artwork['id']}/snapshots").json()
    assert [s["reason"] for s in snapshots][:1] == ["pre_import"]

    keep_both = other_library()
    clash(keep_both)
    session = receive(keep_both, path)
    apply(keep_both, session["import_id"], default="keep_both")
    items = keep_both.post(f"{API}/artworks/query", json={}).json()["items"]
    assert sorted(a["title"] for a in items) == ["Harbour (imported)", "Mine"]
    assert len({a["id"] for a in items}) == 2


def test_per_item_policy_beats_the_kind_default(
    local: TestClient, other_library: Callable[[], TestClient]
) -> None:
    first = create(local, [photo(local, 1600, 1200)], title="Harbour")
    second = create(local, [photo(local, 1200, 1600)], title="Tower")
    path = export_archive(local)

    other = other_library()
    session = receive(other, path)
    apply(other, session["import_id"])
    for artwork_id, title in ((first["id"], "Mine A"), (second["id"], "Mine B")):
        other.patch(f"{API}/artworks/{artwork_id}", json={"title": title})

    session = receive(other, path)
    apply(
        other,
        session["import_id"],
        default="keep_mine",
        per_item={f"artwork:{second['id']}": "take_theirs"},
    )
    titles = sorted(
        a["title"] for a in other.post(f"{API}/artworks/query", json={}).json()["items"]
    )
    assert titles == ["Mine A", "Tower"]


def test_a_trashed_photo_comes_back_when_it_is_received_again(
    local: TestClient, other_library: Callable[[], TestClient]
) -> None:
    photo(local, 1400, 900)
    path = export_archive(local)
    other = other_library()
    session = receive(other, path)
    apply(other, session["import_id"])
    photo_id = other.get(f"{API}/photos").json()["items"][0]["id"]
    other.post(f"{API}/trash/photos", json={"photo_ids": [photo_id]})
    assert other.get(f"{API}/photos").json()["items"] == []

    session = receive(other, path)
    apply(other, session["import_id"])
    assert [p["id"] for p in other.get(f"{API}/photos").json()["items"]] == [photo_id]


def test_a_smart_collection_keeps_working_after_its_tag_is_remapped(
    local: TestClient, other_library: Callable[[], TestClient]
) -> None:
    holiday = tag(local, "Holiday")
    artwork = create(local, [photo(local, 1600, 1200)])
    local.patch(f"{API}/artworks/{artwork['id']}", json={"tag_ids": [holiday["id"]]})
    collection(
        local,
        "Tagged",
        kind="smart",
        filter={
            "op": "and",
            "clauses": [{"field": "tag", "op": "has_any", "value": [holiday["id"]]}],
        },
    )
    path = export_archive(local)

    other = other_library()
    theirs = tag(other, "Holiday")  # forces the tag id to be remapped on import
    session = receive(other, path)
    apply(other, session["import_id"])
    smart = next(c for c in other.get(f"{API}/collections").json() if c["kind"] == "smart")
    assert smart["filter"]["clauses"][0]["value"] == [theirs["id"]]
    assert smart["item_count"] == 1


def test_a_missing_photo_leaves_a_placeholder_rather_than_a_broken_document(
    local: TestClient, other_library: Callable[[], TestClient]
) -> None:
    create(local, [photo(local, 1600, 1200)], title="Harbour")
    path = export_archive(local)
    stripped = path.with_name("stripped.tfarchive")
    _rewrite(path, stripped, drop_photos=True)

    other = other_library()
    session = receive(other, stripped)
    result = apply(other, session["import_id"])
    assert result["warnings"] and "is not in the archive" in result["warnings"][0]
    artwork = other.post(f"{API}/artworks/query", json={}).json()["items"][0]
    detail = other.get(f"{API}/artworks/{artwork['id']}").json()
    assert detail["document"]["slots"][0]["photo_id"] is None
    assert detail["is_incomplete"] and detail["document"]["slots"][0]["quality_lock"] == "free"


# ---- safety -------------------------------------------------------------------------------------
def _rewrite(
    source: Path,
    target: Path,
    *,
    drop_photos: bool = False,
    extra: dict[str, bytes] | None = None,
) -> Path:
    """Copy an archive, dropping members and adding raw ones, then fix `checksums.sha256`."""
    import hashlib

    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w") as dst:
        members = {
            name: src.read(name) for name in src.namelist() if name != archive.CHECKSUMS_NAME
        }
        if drop_photos:
            members["data/photos.jsonl"] = b""
            members = {n: b for n, b in members.items() if not n.startswith("originals/")}
        members.update(extra or {})
        for name, body in members.items():
            dst.writestr(name, body)
        lines = sorted(f"{hashlib.sha256(b).hexdigest()}  {n}\n" for n, b in members.items())
        dst.writestr(archive.CHECKSUMS_NAME, "".join(lines))
    return target


def _refused(client: TestClient, path: Path) -> str:
    session = receive(client, path)
    assert session["state"] == "failed", session
    return str(session["error"])


def test_a_traversing_member_is_refused(local: TestClient) -> None:
    photo(local)
    path = export_archive(local)
    evil = _rewrite(path, path.with_name("evil.tfarchive"))
    with zipfile.ZipFile(evil, "a") as zf:  # added after the checksums: unlisted *and* unsafe
        zf.writestr("../../etc/passwd", b"root")
    assert _refused(local, evil) in {"unsafe_archive_path", "unlisted_file"}


def test_a_tampered_original_is_refused(local: TestClient) -> None:
    photo(local)
    path = export_archive(local)
    with zipfile.ZipFile(path) as zf:
        original = next(n for n in zf.namelist() if n.startswith("originals/"))
    tampered = _rewrite(path, path.with_name("tampered.tfarchive"), extra={original: b"not a jpeg"})
    assert _refused(local, tampered) == "original_mismatch"


def test_a_missing_checksum_line_is_refused(local: TestClient) -> None:
    photo(local)
    path = export_archive(local)
    target = path.with_name("unlisted.tfarchive")
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(target, "w") as dst:
        for name in src.namelist():
            dst.writestr(name, src.read(name))
        dst.writestr("data/extra.jsonl", b"{}\n")
    assert _refused(local, target) == "unlisted_file"


def test_a_newer_format_version_is_refused(local: TestClient) -> None:
    photo(local)
    path = export_archive(local)
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read(archive.MANIFEST_NAME))
    manifest["format_version"] = archive.FORMAT_VERSION + 1
    future = _rewrite(
        path,
        path.with_name("future.tfarchive"),
        extra={archive.MANIFEST_NAME: json.dumps(manifest).encode()},
    )
    assert _refused(local, future) == "unsupported_archive_version"


def test_something_that_is_not_an_archive_is_refused(local: TestClient) -> None:
    path = Path(ctx_of(local).storage.root) / "junk.tfarchive"
    path.write_bytes(b"PK\x03\x04 nope")
    assert _refused(local, path) == "not_an_archive"


def test_an_archive_with_no_manifest_is_refused(local: TestClient) -> None:
    path = Path(ctx_of(local).storage.root) / "bare.tfarchive"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("data/tags.jsonl", b"")
    path.write_bytes(buffer.getvalue())
    assert _refused(local, path) == "missing_manifest"


# ---- housekeeping -------------------------------------------------------------------------------
def test_an_import_can_be_forgotten_and_its_staging_goes_with_it(local: TestClient) -> None:
    photo(local)
    path = export_archive(local)
    session = receive(local, path)
    import_id = session["import_id"]
    staging = Path(ctx_of(local).storage.import_dir(import_id))
    assert staging.is_dir()
    assert local.delete(f"{API}/imports/{import_id}").status_code == 204
    assert not staging.exists()
    assert local.get(f"{API}/imports/{import_id}").status_code == 404


def test_an_export_can_be_deleted_and_needs_admin(local: TestClient) -> None:
    from tests.conftest import pair

    photo(local)
    path = export_archive(local)
    job_id = path.parent.name
    uploader = pair(local, "uploader")
    assert uploader.post(f"{API}/exports", json={}).status_code == 403
    assert uploader.get(f"{API}/imports").status_code == 403
    assert local.delete(f"{API}/exports/{job_id}").status_code == 204
    assert local.get(f"{API}/exports/{job_id}/download").status_code == 404


def test_a_member_that_lies_about_its_size_is_refused(local: TestClient) -> None:
    """An archive whose central directory understates a member is refused, not expanded.

    The budget in `_safe_names` adds up the sizes the archive *declares*, so it is worth pinning
    what happens when one lies: `zipfile` stops the member at the declared length and its CRC no
    longer matches, which staging reports rather than reading 8 MB out of a 64-byte claim.
    """
    import hashlib
    import struct

    photo(local)
    path = export_archive(local)
    bomb = b"\0" * (8 * 1024 * 1024)
    target = path.with_name("bomb.tfarchive")
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(target, "w") as dst:
        members = {
            name: src.read(name) for name in src.namelist() if name != archive.CHECKSUMS_NAME
        }
        members["data/bomb.bin"] = bomb
        for name, body in members.items():
            dst.writestr(name, body, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        lines = sorted(f"{hashlib.sha256(b).hexdigest()}  {n}\n" for n, b in members.items())
        dst.writestr(archive.CHECKSUMS_NAME, "".join(lines))

    raw = bytearray(target.read_bytes())
    for marker, offset_to_size in ((b"PK\x03\x04", 22), (b"PK\x01\x02", 24)):
        at = 0
        while (at := raw.find(marker, at)) != -1:
            base = at + offset_to_size
            if struct.unpack_from("<I", raw, base)[0] == len(bomb):
                struct.pack_into("<I", raw, base, 64)
            at += 4
    target.write_bytes(raw)
    with zipfile.ZipFile(target) as zf:
        assert zf.getinfo("data/bomb.bin").file_size == 64

    assert _refused(local, target) == "staging_failed"


def test_an_archive_over_the_size_budget_is_refused(
    local: TestClient, app_factory: Callable[..., TestClient]
) -> None:
    """The budget is spent against the bytes that actually come out of the members."""
    photo(local)
    path = export_archive(local)
    import hashlib

    target = path.with_name("big.tfarchive")
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(target, "w") as dst:
        members = {
            name: src.read(name) for name in src.namelist() if name != archive.CHECKSUMS_NAME
        }
        # Compresses to a few KB, so it sails through the upload cap and is caught on expansion.
        members["data/filler.bin"] = b"\0" * (8 * 1024 * 1024)
        for name, body in members.items():
            dst.writestr(name, body, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        lines = sorted(f"{hashlib.sha256(b).hexdigest()}  {n}\n" for n, b in members.items())
        dst.writestr(archive.CHECKSUMS_NAME, "".join(lines))
    assert target.stat().st_size < 1024 * 1024

    victim = app_factory(max_archive_bytes=1024 * 1024)
    assert _refused(victim, target) == "archive_too_large"
