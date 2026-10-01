"""Photo library queries and updates."""

from __future__ import annotations

import base64
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, delete, func, or_, select
from sqlalchemy.orm import Session

from the_frame_v2.db.models import (
    Artwork,
    ArtworkPhoto,
    Collection,
    Photo,
    PhotoPendingMeta,
    PhotoTag,
    Tag,
)
from the_frame_v2.errors import ProblemError, not_found
from the_frame_v2.services import search, tags

INBOX_STATES = ("inbox", "processed", "dismissed")
MAX_LIMIT = 500


@dataclass(frozen=True, slots=True)
class PhotoFilter:
    inbox_state: str | None = None
    q: str | None = None
    tag_id: str | None = None
    trashed: bool = False


@dataclass(frozen=True, slots=True)
class PhotoPage:
    items: list[Photo]
    tags: dict[str, list[Tag]]
    next_cursor: str | None
    drafts: dict[str, list[str]] = field(default_factory=dict)
    """photo id → live draft artworks using it (`draft_artworks_for`)."""


def _encode_cursor(photo: Photo) -> str:
    raw = f"{photo.imported_at.isoformat()}|{photo.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        stamp, photo_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
        return datetime.fromisoformat(stamp), photo_id
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProblemError(400, "invalid_cursor", "Invalid cursor") from exc


def _apply_filter(
    session: Session, stmt: Select[tuple[Photo]], flt: PhotoFilter
) -> Select[tuple[Photo]]:
    stmt = stmt.where(Photo.deleted_at.is_not(None) if flt.trashed else Photo.deleted_at.is_(None))
    if flt.inbox_state:
        if flt.inbox_state not in INBOX_STATES:
            raise ProblemError(422, "invalid_inbox_state", "Invalid inbox state")
        stmt = stmt.where(Photo.inbox_state == flt.inbox_state)
    if flt.q:
        # FTS first (it reaches the tags too), then LIKE so a mid-word fragment still finds a file.
        like = f"%{flt.q.strip()}%"
        stmt = stmt.where(
            or_(
                Photo.id.in_(search.search_ids(session, "photo", flt.q)),
                Photo.original_filename.ilike(like),
                Photo.place_name.ilike(like),
                Photo.place_admin1.ilike(like),
                Photo.place_country.ilike(like),
                Photo.camera_model.ilike(like),
            )
        )
    if flt.tag_id:
        stmt = stmt.where(
            Photo.id.in_(select(PhotoTag.photo_id).where(PhotoTag.tag_id == flt.tag_id))
        )
    return stmt


def tags_for(session: Session, photo_ids: list[str]) -> dict[str, list[Tag]]:
    result: dict[str, list[Tag]] = defaultdict(list)
    if not photo_ids:
        return result
    rows = session.execute(
        select(PhotoTag.photo_id, Tag)
        .join(Tag, Tag.id == PhotoTag.tag_id)
        .where(PhotoTag.photo_id.in_(photo_ids))
        .order_by(Tag.name)
    )
    for photo_id, tag in rows:
        result[photo_id].append(tag)
    return result


def list_photos(session: Session, flt: PhotoFilter, cursor: str | None, limit: int) -> PhotoPage:
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = _apply_filter(session, select(Photo), flt)
    if cursor:
        stamp, photo_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(Photo.imported_at < stamp, and_(Photo.imported_at == stamp, Photo.id < photo_id))
        )
    stmt = stmt.order_by(Photo.imported_at.desc(), Photo.id.desc()).limit(limit + 1)
    rows = list(session.scalars(stmt))
    next_cursor = _encode_cursor(rows[limit - 1]) if len(rows) > limit else None
    items = rows[:limit]
    ids = [p.id for p in items]
    return PhotoPage(items, tags_for(session, ids), next_cursor, draft_artworks_for(session, ids))


def count_photos(session: Session, flt: PhotoFilter) -> int:
    stmt = _apply_filter(session, select(Photo), flt).with_only_columns(func.count(Photo.id))
    return int(session.scalar(stmt) or 0)


def get_photo(session: Session, photo_id: str) -> Photo:
    photo = session.get(Photo, photo_id)
    if photo is None or photo.deleted_at is not None:
        raise not_found("Photo")
    return photo


def update_photo(
    session: Session, photo_id: str, *, tag_ids: list[str] | None, inbox_state: str | None
) -> Photo:
    photo = get_photo(session, photo_id)
    if inbox_state is not None:
        if inbox_state not in INBOX_STATES:
            raise ProblemError(422, "invalid_inbox_state", "Invalid inbox state")
        photo.inbox_state = inbox_state
    if tag_ids is not None:
        unique = list(dict.fromkeys(tag_ids))
        known = set(session.scalars(select(Tag.id).where(Tag.id.in_(unique))))
        if len(known) != len(unique):
            raise ProblemError(422, "unknown_tag", "Unknown tag")
        before = set(session.scalars(select(PhotoTag.tag_id).where(PhotoTag.photo_id == photo.id)))
        session.execute(delete(PhotoTag).where(PhotoTag.photo_id == photo.id))
        session.add_all(PhotoTag(photo_id=photo.id, tag_id=t) for t in unique)
        tags.touch(session, [t for t in unique if t not in before])
        session.flush()
        search.index_photo(session, photo)
        # The artworks made of this photo carry its tags (docs/organization.md §1).
        search.index_artworks_using(session, [photo.id])
    return photo


def apply_upload_meta(session: Session, photo: Photo, meta: Mapping[str, Any] | None) -> None:
    """What the sender chose for a batch (tags, collections, favourite), on one photo of it.

    The same whether the photo is new or one the library already had (a duplicate, or a copy of
    it): tags land on the photo now — **added**, never replacing what it carries — and the
    collections and favourite wait in `photo_pending_meta` for the first artwork made of it,
    merged with whatever was already waiting. Unknown tags and collections are dropped, so a tag
    deleted between upload and ingest cannot break the ingest.
    """
    if not meta:
        return
    wanted = [str(t) for t in meta.get("tag_ids") or []]
    known = set(session.scalars(select(Tag.id).where(Tag.id.in_(wanted)))) if wanted else set()
    have = set(session.scalars(select(PhotoTag.tag_id).where(PhotoTag.photo_id == photo.id)))
    added = [t for t in dict.fromkeys(wanted) if t in known and t not in have]
    session.add_all(PhotoTag(photo_id=photo.id, tag_id=t) for t in added)
    tags.touch(session, added)

    collection_ids = [str(c) for c in meta.get("collection_ids") or []]
    if collection_ids:
        collection_ids = list(
            session.scalars(select(Collection.id).where(Collection.id.in_(collection_ids)))
        )
    favorite = bool(meta.get("favorite"))
    if collection_ids or favorite:
        pending = session.get(PhotoPendingMeta, photo.id)
        if pending is None:
            session.add(
                PhotoPendingMeta(
                    photo_id=photo.id, collection_ids=collection_ids, favorite=favorite
                )
            )
        else:
            pending.collection_ids = list(
                dict.fromkeys([*(str(c) for c in pending.collection_ids), *collection_ids])
            )
            pending.favorite = pending.favorite or favorite
    session.flush()
    if added:
        search.index_photo(session, photo)
        search.index_artworks_using(session, [photo.id])


def draft_artworks_for(session: Session, photo_ids: list[str]) -> dict[str, list[str]]:
    """photo id → the live **draft** artworks using it, oldest first.

    While a photo has only drafts it stays in the inbox (it leaves when one is marked ready), and
    the inbox shows a badge that opens the draft rather than inviting a second artwork.
    """
    result: dict[str, list[str]] = defaultdict(list)
    if not photo_ids:
        return result
    rows = session.execute(
        select(ArtworkPhoto.photo_id, Artwork.id)
        .join(Artwork, Artwork.id == ArtworkPhoto.artwork_id)
        .where(
            ArtworkPhoto.photo_id.in_(photo_ids),
            Artwork.deleted_at.is_(None),
            Artwork.status == "draft",
        )
        .order_by(Artwork.created_at, Artwork.id)
    )
    for photo_id, artwork_id in rows:
        if artwork_id not in result[photo_id]:
            result[photo_id].append(artwork_id)
    return result


def set_inbox_state(session: Session, photo_ids: list[str], state: str) -> int:
    if state not in INBOX_STATES:
        raise ProblemError(422, "invalid_inbox_state", "Invalid inbox state")
    photos = session.scalars(
        select(Photo).where(Photo.id.in_(photo_ids), Photo.deleted_at.is_(None))
    ).all()
    for photo in photos:
        photo.inbox_state = state
    return len(photos)
