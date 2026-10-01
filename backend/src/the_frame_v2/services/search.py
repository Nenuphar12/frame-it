"""Full-text search index (`search_index`, FTS5 — docs/data-model.md §5.1).

One row per entity holding everything worth searching for it: an artwork's title, the names of
its tags — its own and the ones it inherits from its photos (docs/organization.md §1) — and the
place names and file names of the photos it uses; a photo's file name, place, camera and tags; a
collection's name and description. Writers call `index_artwork` / `index_photo` /
`index_collection` inside the same transaction as the change, so the index never outlives what it
describes; a change to a photo's tags also re-indexes the artworks made of it
(`index_artworks_using`).

The table is disposable: `reindex_all` rebuilds it from the library, at startup when it is empty
or was written under older rules than `INDEX_VERSION` (kept in a marker row).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from the_frame_v2.db.models import (
    Artwork,
    ArtworkPhoto,
    ArtworkTag,
    Collection,
    Photo,
    PhotoTag,
    Tag,
)

MAX_TEXT = 4000
#: Bump when what an entity's text holds changes: startup then rebuilds the index once.
#: 2 — an artwork's text holds its photos' tag names (tag inheritance).
INDEX_VERSION = 2
#: Entity type of the marker row that records `INDEX_VERSION` (never matched by a search).
_META = "meta"
#: Only these characters survive into an FTS5 MATCH expression (everything else is an operator).
_TOKEN = re.compile(r"[\w'-]+", re.UNICODE)


def match_query(raw: str) -> str | None:
    """User text → a safe FTS5 prefix query, or None when nothing searchable is left."""
    tokens = _TOKEN.findall(raw or "")
    if not tokens:
        return None
    return " ".join(f'"{token}"*' for token in tokens[:16])


def _join(parts: Iterable[str | None]) -> str:
    seen: list[str] = []
    for part in parts:
        value = (part or "").strip()
        if value and value not in seen:
            seen.append(value)
    return " ".join(seen)[:MAX_TEXT]


def _replace(session: Session, entity_type: str, entity_id: str, body: str) -> None:
    session.execute(
        text("DELETE FROM search_index WHERE entity_type = :t AND entity_id = :i"),
        {"t": entity_type, "i": entity_id},
    )
    if body:
        session.execute(
            text("INSERT INTO search_index (entity_type, entity_id, text) VALUES (:t, :i, :x)"),
            {"t": entity_type, "i": entity_id, "x": body},
        )


def remove(session: Session, entity_type: str, entity_ids: Sequence[str]) -> None:
    for entity_id in entity_ids:
        session.execute(
            text("DELETE FROM search_index WHERE entity_type = :t AND entity_id = :i"),
            {"t": entity_type, "i": entity_id},
        )


def photo_text(session: Session, photo: Photo) -> str:
    tags = session.scalars(
        select(Tag.name)
        .join(PhotoTag, PhotoTag.tag_id == Tag.id)
        .where(PhotoTag.photo_id == photo.id)
    )
    return _join(
        [
            photo.original_filename,
            photo.place_name,
            photo.place_admin1,
            photo.place_country,
            photo.camera_make,
            photo.camera_model,
            photo.lens,
            *tags,
        ]
    )


def index_photo(session: Session, photo: Photo) -> None:
    _replace(session, "photo", photo.id, photo_text(session, photo))


def artwork_text(session: Session, artwork: Artwork) -> str:
    own = session.scalars(
        select(Tag.name)
        .join(ArtworkTag, ArtworkTag.tag_id == Tag.id)
        .where(ArtworkTag.artwork_id == artwork.id)
    )
    inherited = session.scalars(
        select(Tag.name)
        .join(PhotoTag, PhotoTag.tag_id == Tag.id)
        .join(ArtworkPhoto, ArtworkPhoto.photo_id == PhotoTag.photo_id)
        .join(Photo, Photo.id == PhotoTag.photo_id)
        .where(ArtworkPhoto.artwork_id == artwork.id, Photo.deleted_at.is_(None))
        .order_by(Tag.name)
    )
    photos = session.execute(
        select(Photo.original_filename, Photo.place_name, Photo.place_admin1, Photo.place_country)
        .join(ArtworkPhoto, ArtworkPhoto.photo_id == Photo.id)
        .where(ArtworkPhoto.artwork_id == artwork.id)
    )
    parts: list[str | None] = [artwork.title, *own, *inherited]
    for row in photos:
        parts.extend(row)
    return _join(parts)


def index_artwork(session: Session, artwork: Artwork) -> None:
    _replace(session, "artwork", artwork.id, artwork_text(session, artwork))


def index_artworks_using(session: Session, photo_ids: Iterable[str]) -> None:
    """Re-index the live artworks made of these photos: their text holds the photos' tags."""
    ids = set(photo_ids)
    if not ids:
        return
    rows = session.scalars(
        select(Artwork).where(
            Artwork.deleted_at.is_(None),
            Artwork.id.in_(select(ArtworkPhoto.artwork_id).where(ArtworkPhoto.photo_id.in_(ids))),
        )
    )
    for artwork in rows:
        index_artwork(session, artwork)


def index_collection(session: Session, collection: Collection) -> None:
    _replace(session, "collection", collection.id, _join([collection.name, collection.description]))


def search_ids(session: Session, entity_type: str, query: str, limit: int = 500) -> list[str]:
    """Ids matching `query`, best match first (FTS5 `rank`)."""
    expression = match_query(query)
    if expression is None:
        return []
    rows = session.execute(
        text(
            "SELECT entity_id FROM search_index WHERE entity_type = :t AND search_index MATCH :q"
            " ORDER BY rank LIMIT :n"
        ),
        {"t": entity_type, "q": expression, "n": limit},
    )
    return [row[0] for row in rows]


def is_empty(session: Session) -> bool:
    return not session.execute(
        text("SELECT 1 FROM search_index WHERE entity_type != :m LIMIT 1"), {"m": _META}
    ).first()


def needs_rebuild(session: Session) -> bool:
    """Empty, or written under older rules than `INDEX_VERSION` (the marker row says which)."""
    marker = session.execute(
        text("SELECT text FROM search_index WHERE entity_type = :m AND entity_id = 'version'"),
        {"m": _META},
    ).first()
    return marker is None or marker[0] != str(INDEX_VERSION) or is_empty(session)


def reindex_all(session: Session) -> int:
    """Rebuild the whole index (cheap: the text comes from columns we already hold)."""
    session.execute(text("DELETE FROM search_index"))
    _replace(session, _META, "version", str(INDEX_VERSION))
    count = 0
    for photo in session.scalars(select(Photo)):
        _replace(session, "photo", photo.id, photo_text(session, photo))
        count += 1
    for artwork in session.scalars(select(Artwork)):
        _replace(session, "artwork", artwork.id, artwork_text(session, artwork))
        count += 1
    for collection in session.scalars(select(Collection)):
        index_collection(session, collection)
        count += 1
    return count
