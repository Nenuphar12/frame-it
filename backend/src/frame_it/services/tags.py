"""Tags: one flat namespace, case-insensitive unique names, shared by photos and artworks.

An artwork's **effective** tags are its own plus the tags of the photos it uses — inherited, read
at query time, never copied (docs/organization.md §1). So the counts below say what the tag filter
returns (`artwork_count`, own or inherited), and separately what deleting the tag would detach
from artworks (`own_artwork_count`).

Management: rename, recolour, **merge** (the source's rows move to the target, duplicates
collapse, the source disappears), delete, **categories** (one level: People, Events…; NULL is
"Other") and the clean-up of tags nothing uses. Every mutation refreshes the FTS index of what
carried the tag — a tag name is searchable text, and an artwork's text holds its photos' tags too.

**Bulk tagging** is additive: `add` and `remove` lists, never a replacement, so tagging fifty
photos that already carry different tags only touches the tags named.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from types import EllipsisType
from typing import Literal

from sqlalchemy import delete, distinct, func, select, union, update
from sqlalchemy.orm import Session

from frame_it.db.models import (
    Artwork,
    ArtworkPhoto,
    ArtworkTag,
    Photo,
    PhotoTag,
    Tag,
    TagCategory,
)
from frame_it.errors import ProblemError, not_found
from frame_it.ids import utcnow
from frame_it.services import search

MAX_TAG_LENGTH = 64
MAX_CATEGORY_LENGTH = 64
#: `#rrggbb` or `#rrggbbaa`, like every other colour in the document.
_HEX_LENGTHS = (7, 9)

TagSort = Literal["usage", "recent", "name"]
TAG_SORTS: tuple[TagSort, ...] = ("usage", "recent", "name")


@dataclass(frozen=True, slots=True)
class TagUsage:
    tag: Tag
    photo_count: int
    artwork_count: int
    """Live artworks carrying the tag, their own or through a photo — what the filter returns."""
    own_artwork_count: int = 0
    """Live artworks the tag is attached to directly — what deleting it detaches."""


@dataclass(frozen=True, slots=True)
class CategoryUsage:
    category: TagCategory
    tag_count: int


def normalize_name(
    name: str, *, limit: int = MAX_TAG_LENGTH, code: str = "invalid_tag_name"
) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ProblemError(422, code, "The name is empty")
    if len(cleaned) > limit:
        raise ProblemError(422, code, "The name is too long")
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


def _check_tags(session: Session, tag_ids: Sequence[str]) -> list[str]:
    """The ids, de-duplicated in order; 422 `unknown_tag` if one does not exist."""
    unique = list(dict.fromkeys(tag_ids))
    if not unique:
        return unique
    known = set(session.scalars(select(Tag.id).where(Tag.id.in_(unique))))
    if len(known) != len(unique):
        raise ProblemError(422, "unknown_tag", "Unknown tag")
    return unique


def touch(session: Session, tag_ids: Sequence[str]) -> None:
    """Record that these tags were just attached to something (the picker's "recent" order)."""
    ids = list(dict.fromkeys(tag_ids))
    if ids:
        session.execute(update(Tag).where(Tag.id.in_(ids)).values(last_used_at=utcnow()))


# ---- counts & listing ---------------------------------------------------------------------------
def _counts(session: Session) -> dict[str, tuple[int, int, int]]:
    """tag id → (photos, artworks own or inherited, artworks own), trashed rows left out."""
    photos = {
        row[0]: int(row[1])
        for row in session.execute(
            select(PhotoTag.tag_id, func.count())
            .join(Photo, Photo.id == PhotoTag.photo_id)
            .where(Photo.deleted_at.is_(None))
            .group_by(PhotoTag.tag_id)
        )
    }
    own = {
        row[0]: int(row[1])
        for row in session.execute(
            select(ArtworkTag.tag_id, func.count())
            .join(Artwork, Artwork.id == ArtworkTag.artwork_id)
            .where(Artwork.deleted_at.is_(None))
            .group_by(ArtworkTag.tag_id)
        )
    }
    # (tag, artwork) pairs, own or inherited — UNION collapses an artwork that has both.
    pairs = union(
        select(ArtworkTag.tag_id.label("tag_id"), ArtworkTag.artwork_id.label("artwork_id")),
        select(PhotoTag.tag_id.label("tag_id"), ArtworkPhoto.artwork_id.label("artwork_id"))
        .join(ArtworkPhoto, ArtworkPhoto.photo_id == PhotoTag.photo_id)
        .join(Photo, Photo.id == PhotoTag.photo_id)
        .where(Photo.deleted_at.is_(None)),
    ).subquery()
    effective = {
        row[0]: int(row[1])
        for row in session.execute(
            select(pairs.c.tag_id, func.count(distinct(pairs.c.artwork_id)))
            .join(Artwork, Artwork.id == pairs.c.artwork_id)
            .where(Artwork.deleted_at.is_(None))
            .group_by(pairs.c.tag_id)
        )
    }
    keys = photos.keys() | own.keys() | effective.keys()
    return {k: (photos.get(k, 0), effective.get(k, 0), own.get(k, 0)) for k in keys}


def search_tags(
    session: Session, q: str | None, limit: int = 50, sort: TagSort = "usage"
) -> list[TagUsage]:
    """Tags matching `q`, in the order asked for.

    `usage` — most used first (the default); `recent` — last attached first, then by use (the
    picker: what you tagged with a minute ago is what you want again); `name` — alphabetical.
    """
    stmt = select(Tag)
    if q:
        stmt = stmt.where(Tag.name.ilike(f"%{q.strip()}%"))
    counts = _counts(session)
    usage = [TagUsage(t, *counts.get(t.id, (0, 0, 0))) for t in session.scalars(stmt)]

    def used(u: TagUsage) -> int:
        return u.photo_count + u.artwork_count

    if sort == "name":
        usage.sort(key=lambda u: u.tag.name.lower())
    elif sort == "recent":
        usage.sort(
            key=lambda u: (
                u.tag.last_used_at is None,
                -(u.tag.last_used_at.timestamp() if u.tag.last_used_at else 0.0),
                -used(u),
                u.tag.name.lower(),
            )
        )
    else:
        usage.sort(key=lambda u: (-used(u), u.tag.name.lower()))
    return usage[: max(1, min(limit, 500))]


def list_tags(session: Session) -> list[TagUsage]:
    return search_tags(session, None, limit=500)


def tag_usage(session: Session, tag: Tag) -> TagUsage:
    return TagUsage(tag, *_counts(session).get(tag.id, (0, 0, 0)))


# ---- create / edit ------------------------------------------------------------------------------
def get_or_create(
    session: Session, name: str, *, category_id: str | None = None
) -> tuple[Tag, bool]:
    """The tag with this name (case-insensitive), or a new one in `category_id`.

    An existing tag keeps its category: creating "Alice" from a People picker must not move an
    "alice" that lives elsewhere.
    """
    normalized = normalize_name(name)
    existing = session.scalars(select(Tag).where(Tag.name == normalized)).first()
    if existing is not None:
        return existing, False
    if category_id is not None:
        get_category(session, category_id)
    tag = Tag(name=normalized, category_id=category_id)
    session.add(tag)
    session.flush()
    return tag, True


def update_tag(
    session: Session,
    tag_id: str,
    *,
    name: str | None = None,
    color: str | None = None,
    category_id: str | EllipsisType | None = ...,
) -> Tag:
    """Rename, recolour (`""` clears) and/or move to a category (`None` = Other; `...` = leave)."""
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
    if not isinstance(category_id, EllipsisType):
        if category_id is not None:
            get_category(session, category_id)
        tag.category_id = category_id
    session.flush()
    if name is not None:
        _reindex_users(session, tag.id)
    return tag


def categorize(session: Session, tag_ids: Sequence[str], category_id: str | None) -> int:
    """Move many tags into one category at once (`None` = Other)."""
    ids = _check_tags(session, tag_ids)
    if category_id is not None:
        get_category(session, category_id)
    if not ids:
        return 0
    session.execute(update(Tag).where(Tag.id.in_(ids)).values(category_id=category_id))
    session.flush()
    return len(ids)


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
    touch(session, [target.id])
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


def unused_tags(session: Session) -> list[Tag]:
    """Tags attached to nothing at all — trashed photos and artworks included.

    A tag only a trashed photo carries is *not* unused: restoring the photo must bring it back.
    """
    linked = select(PhotoTag.tag_id).union(select(ArtworkTag.tag_id))
    return list(session.scalars(select(Tag).where(Tag.id.not_in(linked)).order_by(Tag.name)))


def delete_unused(session: Session) -> int:
    """Delete every tag `unused_tags` lists. Nothing to re-index: nothing carried them."""
    rows = unused_tags(session)
    for tag in rows:
        session.delete(tag)
    session.flush()
    return len(rows)


def _reindex_users(session: Session, tag_id: str) -> None:
    photo_ids = list(session.scalars(select(PhotoTag.photo_id).where(PhotoTag.tag_id == tag_id)))
    artwork_ids = list(
        session.scalars(select(ArtworkTag.artwork_id).where(ArtworkTag.tag_id == tag_id))
    )
    _reindex(session, photo_ids, artwork_ids)


def _reindex(session: Session, photo_ids: Sequence[str], artwork_ids: Sequence[str]) -> None:
    """Re-index the photos, the artworks, and every artwork that inherits from those photos."""
    for photo in session.scalars(select(Photo).where(Photo.id.in_(set(photo_ids)))):
        search.index_photo(session, photo)
    inheriting = set(
        session.scalars(
            select(ArtworkPhoto.artwork_id).where(ArtworkPhoto.photo_id.in_(set(photo_ids)))
        )
    )
    targets = set(artwork_ids) | inheriting
    for artwork in session.scalars(select(Artwork).where(Artwork.id.in_(targets))):
        search.index_artwork(session, artwork)


# ---- bulk tagging -------------------------------------------------------------------------------
def _add_remove(
    session: Session, add: Sequence[str], remove: Sequence[str]
) -> tuple[list[str], list[str]]:
    to_add, to_remove = _check_tags(session, add), _check_tags(session, remove)
    if set(to_add) & set(to_remove):
        raise ProblemError(
            422, "tag_conflict", "A tag cannot be added and removed at once", to_add[0]
        )
    return to_add, to_remove


def tag_photos(
    session: Session, photo_ids: Sequence[str], *, add: Sequence[str], remove: Sequence[str]
) -> int:
    """Add and remove tags on many photos; returns how many live photos it applied to."""
    to_add, to_remove = _add_remove(session, add, remove)
    photos = list(
        session.scalars(
            select(Photo).where(Photo.id.in_(set(photo_ids)), Photo.deleted_at.is_(None))
        )
    )
    ids = [p.id for p in photos]
    if not ids or not (to_add or to_remove):
        return len(ids)
    if to_remove:
        session.execute(
            delete(PhotoTag).where(PhotoTag.photo_id.in_(ids), PhotoTag.tag_id.in_(to_remove))
        )
    if to_add:
        have = set(
            session.execute(
                select(PhotoTag.photo_id, PhotoTag.tag_id).where(
                    PhotoTag.photo_id.in_(ids), PhotoTag.tag_id.in_(to_add)
                )
            ).tuples()
        )
        session.add_all(
            PhotoTag(photo_id=p, tag_id=t) for p in ids for t in to_add if (p, t) not in have
        )
        touch(session, to_add)
    session.flush()
    for photo in photos:
        search.index_photo(session, photo)
    search.index_artworks_using(session, ids)
    return len(ids)


def tag_artworks(
    session: Session, artwork_ids: Sequence[str], *, add: Sequence[str], remove: Sequence[str]
) -> int:
    """Add and remove an artwork's **own** tags (an inherited one is removed from the photo)."""
    to_add, to_remove = _add_remove(session, add, remove)
    artworks = list(
        session.scalars(
            select(Artwork).where(Artwork.id.in_(set(artwork_ids)), Artwork.deleted_at.is_(None))
        )
    )
    ids = [a.id for a in artworks]
    if not ids or not (to_add or to_remove):
        return len(ids)
    if to_remove:
        session.execute(
            delete(ArtworkTag).where(
                ArtworkTag.artwork_id.in_(ids), ArtworkTag.tag_id.in_(to_remove)
            )
        )
    if to_add:
        have = set(
            session.execute(
                select(ArtworkTag.artwork_id, ArtworkTag.tag_id).where(
                    ArtworkTag.artwork_id.in_(ids), ArtworkTag.tag_id.in_(to_add)
                )
            ).tuples()
        )
        session.add_all(
            ArtworkTag(artwork_id=a, tag_id=t) for a in ids for t in to_add if (a, t) not in have
        )
        touch(session, to_add)
    now = utcnow()
    for artwork in artworks:
        artwork.updated_at = now
    session.flush()
    for artwork in artworks:
        search.index_artwork(session, artwork)
    return len(ids)


# ---- categories ---------------------------------------------------------------------------------
def get_category(session: Session, category_id: str) -> TagCategory:
    category = session.get(TagCategory, category_id)
    if category is None:
        raise not_found("Tag category")
    return category


def list_categories(session: Session) -> list[CategoryUsage]:
    counts = {
        row[0]: int(row[1])
        for row in session.execute(
            select(Tag.category_id, func.count())
            .where(Tag.category_id.is_not(None))
            .group_by(Tag.category_id)
        )
    }
    rows = session.scalars(select(TagCategory).order_by(TagCategory.position, TagCategory.name))
    return [CategoryUsage(c, counts.get(c.id, 0)) for c in rows]


def _category_name(session: Session, name: str, *, exclude: str | None = None) -> str:
    normalized = normalize_name(name, limit=MAX_CATEGORY_LENGTH, code="invalid_category_name")
    stmt = select(TagCategory).where(TagCategory.name == normalized)
    if exclude is not None:
        stmt = stmt.where(TagCategory.id != exclude)
    if session.scalars(stmt).first() is not None:
        raise ProblemError(409, "category_exists", "A category with that name exists")
    return normalized


def create_category(session: Session, name: str, color: str | None = None) -> TagCategory:
    last = session.scalar(select(func.max(TagCategory.position)))
    category = TagCategory(
        name=_category_name(session, name),
        color=_normalize_color(color),
        position=float(last or 0) + 1,
    )
    session.add(category)
    session.flush()
    return category


def update_category(
    session: Session, category_id: str, *, name: str | None = None, color: str | None = None
) -> TagCategory:
    category = get_category(session, category_id)
    if name is not None:
        category.name = _category_name(session, name, exclude=category.id)
    if color is not None:
        category.color = _normalize_color(color)
    session.flush()
    return category


def delete_category(session: Session, category_id: str) -> int:
    """Delete a category; its tags stay and become "Other". Returns how many moved."""
    category = get_category(session, category_id)
    moved = session.execute(
        update(Tag).where(Tag.category_id == category.id).values(category_id=None)
    )
    session.delete(category)
    session.flush()
    return int(getattr(moved, "rowcount", 0) or 0)
