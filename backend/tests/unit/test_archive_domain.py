"""Pure archive rules: member-name safety, identity/comparison and filter remapping."""

from __future__ import annotations

from typing import Any

import pytest

from the_frame_v2.domain import archive, filters


@pytest.mark.parametrize(
    "name",
    [
        "../etc/passwd",
        "/etc/passwd",
        "data/../../x",
        "C:/windows",
        "data\\photos.jsonl",
        "./data/photos.jsonl",
        "data//photos.jsonl",
        "data/./photos.jsonl",
        "",
        "x" * 256,
    ],
)
def test_unsafe_member_paths_are_refused(name: str) -> None:
    with pytest.raises(archive.ArchiveError) as exc:
        archive.safe_member_path(name)
    assert exc.value.code == "unsafe_archive_path"


@pytest.mark.parametrize(
    "name", ["manifest.json", "data/photos.jsonl", "originals/" + "a" * 64 + ".jpg"]
)
def test_ordinary_member_paths_pass_through(name: str) -> None:
    assert archive.safe_member_path(name) == name


def test_an_original_is_named_by_its_own_digest() -> None:
    sha = "b" * 64
    assert archive.parse_original_name(archive.original_name(sha, "jpg")) == (sha, "jpg")
    for bad in ("originals/short.jpg", "originals/" + "b" * 64, "originals/" + "b" * 64 + ".TIFF!"):
        with pytest.raises(archive.ArchiveError):
            archive.parse_original_name(bad)


def test_every_entity_has_a_schema_and_a_place() -> None:
    schemas = archive.json_schemas()
    assert "manifest.v1.json" in schemas
    for entity in archive.ENTITIES:
        assert entity.path.startswith(archive.DATA_PREFIX)
        assert f"{entity.kind}.v1.json" in schemas
    # `tag` before `photo_tag`, `artwork` before `collection_item`: references come first (§12.2).
    order = [entity.kind for entity in archive.ENTITIES]
    assert order.index("tag") < order.index("photo_tag")
    assert order.index("artwork") < order.index("collection_item")
    assert order.index("collection") < order.index("collection_item")


def test_timestamps_never_decide_that_two_rows_differ() -> None:
    """`identical` means the same content (§12.2): a save on either side moves the timestamps."""
    base = {"id": "t1", "name": "Sea", "color": "#0044FF", "created_at": "2026-01-01T00:00:00Z"}
    mine = archive.TagRecord.model_validate(base)
    later = archive.TagRecord.model_validate({**base, "created_at": "2026-09-01T12:00:00Z"})
    renamed = archive.TagRecord.model_validate({**base, "name": "Ocean"})
    assert archive.comparable(archive.TAGS, mine) == archive.comparable(archive.TAGS, later)
    assert archive.comparable(archive.TAGS, mine) != archive.comparable(archive.TAGS, renamed)


def test_a_no_op_save_is_not_an_artwork_conflict() -> None:
    base = {
        "id": "a1",
        "title": "Harbour",
        "document": {"schema": 1},
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    mine = archive.ArtworkRecord.model_validate(base)
    bumped = archive.ArtworkRecord.model_validate({**base, "document_version": 7})
    assert archive.comparable(archive.ARTWORKS, mine) == archive.comparable(
        archive.ARTWORKS, bumped
    )


def test_a_document_missing_a_later_default_is_not_a_conflict() -> None:
    """A row saved before a field existed does not carry its default; reading it back does.

    Comparing one against the other used to call every such artwork `conflicting` — on a real
    library, 23 of 30 (docs/progress.md, Phase 10). Both sides go through the schema now.
    """
    slot: dict[str, Any] = {
        "id": "s1",
        "rect": {"x": 0, "y": 0, "w": 1000, "h": 800},
        "source": {"crop": {"x": 0, "y": 0, "w": 1000, "h": 800}},
    }
    stored: dict[str, Any] = {
        "schema": 1,
        "slots": [slot],
        "margins": {"top": 10, "right": 10, "bottom": 10, "left": 10},
    }
    margins: dict[str, Any] = {
        "top": 10,
        "right": 10,
        "bottom": 10,
        "left": 10,
        "linked": False,
        "mirror_x": False,
        "mirror_y": False,
    }
    read_back: dict[str, Any] = {
        "schema": 1,
        "slots": [slot],
        "margins": margins,
    }
    base: dict[str, Any] = {
        "id": "a1",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    old = archive.ArtworkRecord.model_validate({**base, "document": stored})
    new = archive.ArtworkRecord.model_validate({**base, "document": read_back})
    assert archive.comparable(archive.ARTWORKS, old) == archive.comparable(archive.ARTWORKS, new)
    moved = archive.ArtworkRecord.model_validate(
        {**base, "document": {**read_back, "margins": {**margins, "top": 11}}}
    )
    assert archive.comparable(archive.ARTWORKS, old) != archive.comparable(archive.ARTWORKS, moved)


def test_identity_of_a_link_row_is_both_of_its_ids() -> None:
    link = archive.ArtworkTagRecord(artwork_id="a1", tag_id="t1")
    assert archive.identity_of(archive.ARTWORK_TAGS, link) == "a1\x1ft1"
    assert archive.ARTWORK_TAGS.is_link and not archive.ARTWORKS.is_link


def test_a_filter_travels_through_the_id_maps() -> None:
    """A smart collection's filter is content holding foreign keys: an import rewrites them."""
    node = filters.parse_filter(
        {
            "op": "and",
            "clauses": [
                {"field": "tag", "op": "has_any", "value": ["t-old", "t-unknown"]},
                {"field": "favorite", "op": "eq", "value": True},
                {
                    "op": "or",
                    "clauses": [{"field": "collection", "op": "in", "value": ["c-old"]}],
                },
            ],
        }
    )
    remapped = filters.remap_ids(node, {"t-old": "t-new"}, {"c-old": "c-new"})
    assert remapped.model_dump(mode="json")["clauses"] == [
        {"field": "tag", "op": "has_any", "value": ["t-new", "t-unknown"], "include_nested": False},
        {"field": "favorite", "op": "eq", "value": True, "include_nested": False},
        {
            "op": "or",
            "clauses": [
                {"field": "collection", "op": "in", "value": ["c-new"], "include_nested": False}
            ],
        },
    ]
    original = node.clauses[0]
    assert isinstance(original, filters.Clause)
    assert original.value == ["t-old", "t-unknown"]  # pure: the input is left untouched


def test_imported_names_are_suffixed_once() -> None:
    assert archive.imported_name("Trip") == "Trip (imported)"
    assert archive.imported_name("") == "(imported)"
