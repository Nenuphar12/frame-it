"""Tags: one flat namespace, case-insensitive unique names, shared by photos and artworks.

Management (docs/organization.md §1): rename, recolor, **merge** (the source's rows move to the
target, duplicates collapse, the source disappears) and delete. Every mutation refreshes the FTS
index of the entities that carried the tag: a tag name is searchable text.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from the_frame_v2.db.models import Artwork, ArtworkTag, Photo, PhotoTag, Tag
from the_frame_v2.errors import ProblemError, not_found
from the_frame_v2.services import search

MAX_TAG_LENGTH = 64
#: `#rrggbb` or `#rrggbbaa`, like every other colour in the document.
_HEX_LENGTHS = (7, 9)


@dataclass(frozen=True, slots=True)
class TagUsage:
    tag: Tag
    photo_count: int
    artwork_count: int


def normalize_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ProblemError(422, "invalid_tag_name", "Tag name is empty")
    if len(cleaned) > MAX_TAG_LENGTH:
        raise ProblemError(422, "invalid_tag_name", "Tag name is too long")
    return cleaned


def _normalize_color(color: str | None) -> str | None:
    if color is None or color == "":
        return None
    value = color.strip().lower()
    if len(value) not in _HEX_LENGTHS or not value.startswith("#"):
        raise ProblemError(422, "invalid_color", "Invalid colour", color)
    try:
        int(value[1:], 16)
    except ValueError as exc:
        raise ProblemError(422, "invalid_color", "Invalid colour", color) from exc
    return value


def get_tag(session: Session, tag_id: str) -> Tag:
    tag = session.get(Tag, tag_id)
    if tag is None:
        raise not_found("Tag")
    return tag


def _counts(session: Session, tag_ids: Sequence[str]) -> dict[str, tuple[int, int]]:
    photos = {
        row[0]: int(row[1])
        for row in session.execute(
            select(PhotoTag.tag_id, func.count())
            .join(Photo, Photo.id == PhotoTag.photo_id)
            .where(Photo.deleted_at.is_(None))
            .group_by(PhotoTag.tag_id)
        )
    }
    artworks = {
        row[0]: int(row[1])
        for row in session.execute(
            select(ArtworkTag.tag_id, func.count())
            .join(Artwork, Artwork.id == ArtworkTag.artwork_id)
            .where(Artwork.deleted_at.is_(None))
            .group_by(ArtworkTag.tag_id)
        )
    }
    return {i: (photos.get(i, 0), artworks.get(i, 0)) for i in tag_ids}


def search_tags(session: Session, q: str | None, limit: int = 50) -> list[TagUsage]:
    """Tags ordered by how much they are used, then by name (the autocomplete's order)."""
    stmt = select(Tag)
    if q:
        stmt = stmt.where(Tag.name.ilike(f"%{q.strip()}%"))
    tags = list(session.scalars(stmt))
    counts = _counts(session, [t.id for t in tags])
    usage = [TagUsage(t, *counts.get(t.id, (0, 0))) for t in tags]
    usage.sort(key=lambda u: (-(u.photo_count + u.artwork_count), u.tag.name.lower()))
    return usage[: max(1, min(limit, 500))]


def list_tags(session: Session) -> list[TagUsage]:
    return search_tags(session, None, limit=500)


def get_or_create(session: Session, name: str) -> tuple[Tag, bool]:
    normalized = normalize_name(name)
    existing = session.scalars(select(Tag).where(Tag.name == normalized)).first()
    if existing is not None:
        return existing, False
    tag = Tag(name=normalized)
    session.add(tag)
    session.flush()
    return tag, True


def update_tag(
    session: Session, tag_id: str, *, name: str | None = None, color: str | None = None
) -> Tag:
    tag = get_tag(session, tag_id)
    if name is not None:
        normalized = normalize_name(name)
        clash = session.scalars(select(Tag).where(Tag.name == normalized, Tag.id != tag.id)).first()
        if clash is not None:
            raise ProblemError(
                409, "tag_exists", "A tag with that name exists", "Merge them instead"
            )
        tag.name = normalized
    if color is not None:
        tag.color = _normalize_color(color)
    session.flush()
    _reindex_users(session, tag.id)
    return tag


def merge_tags(session: Session, *, source_ids: Sequence[str], target_id: str) -> Tag:
    """Move every use of `source_ids` onto `target_id` and delete the sources."""
    target = get_tag(session, target_id)
    sources = [get_tag(session, i) for i in dict.fromkeys(source_ids) if i != target_id]
    if not sources:
        raise ProblemError(422, "nothing_to_merge", "Pick at least one other tag")
    for source in sources:
        _move_photo_links(session, source.id, target.id)
        _move_artwork_links(session, source.id, target.id)
        session.delete(source)
    session.flush()
    _reindex_users(session, target.id)
    return target


def _move_photo_links(session: Session, source_id: str, target_id: str) -> None:
    already = set(session.scalars(select(PhotoTag.photo_id).where(PhotoTag.tag_id == target_id)))
    for row in session.scalars(select(PhotoTag).where(PhotoTag.tag_id == source_id)):
        if row.photo_id in already:
            session.delete(row)  # already tagged: the link collapses
        else:
            row.tag_id = target_id


def _move_artwork_links(session: Session, source_id: str, target_id: str) -> None:
    already = set(
        session.scalars(select(ArtworkTag.artwork_id).where(ArtworkTag.tag_id == target_id))
    )
    for row in session.scalars(select(ArtworkTag).where(ArtworkTag.tag_id == source_id)):
        if row.artwork_id in already:
            session.delete(row)
        else:
            row.tag_id = target_id


def delete_tag(session: Session, tag_id: str) -> None:
    tag = get_tag(session, tag_id)
    photo_ids = list(session.scalars(select(PhotoTag.photo_id).where(PhotoTag.tag_id == tag.id)))
    artwork_ids = list(
        session.scalars(select(ArtworkTag.artwork_id).where(ArtworkTag.tag_id == tag.id))
    )
    session.execute(delete(PhotoTag).where(PhotoTag.tag_id == tag.id))
    session.execute(delete(ArtworkTag).where(ArtworkTag.tag_id == tag.id))
    session.delete(tag)
    session.flush()
    _reindex(session, photo_ids, artwork_ids)


def _reindex_users(session: Session, tag_id: str) -> None:
    photo_ids = list(session.scalars(select(PhotoTag.photo_id).where(PhotoTag.tag_id == tag_id)))
    artwork_ids = list(
        session.scalars(select(ArtworkTag.artwork_id).where(ArtworkTag.tag_id == tag_id))
    )
    _reindex(session, photo_ids, artwork_ids)


def _reindex(session: Session, photo_ids: Sequence[str], artwork_ids: Sequence[str]) -> None:
    for photo in session.scalars(select(Photo).where(Photo.id.in_(set(photo_ids)))):
        search.index_photo(session, photo)
    for artwork in session.scalars(select(Artwork).where(Artwork.id.in_(set(artwork_ids)))):
        search.index_artwork(session, artwork)
