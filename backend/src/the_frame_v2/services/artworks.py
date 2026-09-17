"""Artworks: creation from photos + templates, document saves (optimistic concurrency), snapshots.

Spec: docs/artwork-document.md, docs/data-model.md (`artworks`, `artwork_photos`, snapshots).
Every document save validates the document (structure + library references), recomputes the
derived columns and the `artwork_photos` index; callers enqueue a render after commit
(`services/render.py`).
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePath
from typing import Any

from pydantic import ValidationError
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from the_frame_v2.db.models import (
    Artwork,
    ArtworkPhoto,
    ArtworkSnapshot,
    ArtworkTag,
    Collection,
    CollectionItem,
    Layout,
    Photo,
    PhotoPendingMeta,
    Tag,
)
from the_frame_v2.domain.document import (
    ArtworkDocument,
    DocumentIssue,
    parse_document,
    validate_references,
)
from the_frame_v2.domain.geometry import Size
from the_frame_v2.domain.templates import PhotoInput, build_document
from the_frame_v2.errors import ProblemError, not_found
from the_frame_v2.ids import new_id, utcnow
from the_frame_v2.imaging.assets import catalog
from the_frame_v2.services import templates

MAX_SNAPSHOTS = 20
MAX_LIMIT = 500
STATUSES = ("draft", "ready")
SNAPSHOT_REASONS = ("opened", "manual", "pre_restore", "pre_template_update", "pre_import")


# ---- validation ---------------------------------------------------------------------------------
def invalid_document(issues: Sequence[DocumentIssue]) -> ProblemError:
    return ProblemError(
        422,
        "invalid_document",
        "Invalid artwork document",
        issues[0].msg if issues else None,
        extra={"errors": [i.as_dict() for i in issues]},
    )


def parse_or_raise(raw: Mapping[str, Any]) -> ArtworkDocument:
    """Structural validation with precise locations (422 `invalid_document`)."""
    try:
        return parse_document(raw)
    except ValidationError as exc:
        issues = [
            DocumentIssue(tuple(e["loc"]), e["msg"].removeprefix("Value error, "), e["type"])
            for e in exc.errors(include_url=False)
        ]
        raise invalid_document(issues) from exc
    except ValueError as exc:
        raise invalid_document(
            [DocumentIssue(("schema",), str(exc), "unsupported_schema")]
        ) from exc


def photo_sizes(session: Session, photo_ids: Sequence[str]) -> dict[str, Size]:
    """EXIF-oriented sizes of the given photos that exist and are not trashed."""
    if not photo_ids:
        return {}
    rows = session.execute(
        select(Photo.id, Photo.width, Photo.height).where(
            Photo.id.in_(set(photo_ids)), Photo.deleted_at.is_(None)
        )
    )
    return {row.id: Size(row.width, row.height) for row in rows}


def check_references(session: Session, doc: ArtworkDocument) -> None:
    assets = catalog()
    issues = validate_references(
        doc, photo_sizes(session, doc.photo_ids()), assets.font_weights, assets.texture_exists
    )
    if issues:
        raise invalid_document(issues)


def validated(session: Session, raw: Mapping[str, Any]) -> ArtworkDocument:
    doc = parse_or_raise(raw)
    check_references(session, doc)
    return doc


# ---- persistence helpers ------------------------------------------------------------------------
def _store_document(session: Session, artwork: Artwork, doc: ArtworkDocument) -> None:
    """Write the document and everything derived from it."""
    quality = doc.quality()
    artwork.document = doc.canonical()
    artwork.schema_version = doc.schema_version
    artwork.worst_tier = quality.worst_tier
    artwork.min_scale = quality.min_scale
    artwork.max_scale = quality.max_scale
    artwork.photo_count = quality.photo_count
    artwork.is_incomplete = quality.is_incomplete
    if artwork.status == "ready" and quality.is_incomplete:
        artwork.status = "draft"
    session.flush()
    session.execute(delete(ArtworkPhoto).where(ArtworkPhoto.artwork_id == artwork.id))
    session.add_all(
        ArtworkPhoto(artwork_id=artwork.id, slot_id=slot.id, photo_id=slot.photo_id)
        for slot in doc.slots
        if slot.photo_id is not None
    )


def get_artwork(session: Session, artwork_id: str) -> Artwork:
    artwork = session.get(Artwork, artwork_id)
    if artwork is None or artwork.deleted_at is not None:
        raise not_found("Artwork")
    return artwork


def document_of(artwork: Artwork) -> ArtworkDocument:
    """Stored documents are valid by construction; older schemas are migrated on read."""
    return parse_document(artwork.document)


def tags_for(session: Session, artwork_ids: Sequence[str]) -> dict[str, list[Tag]]:
    result: dict[str, list[Tag]] = {i: [] for i in artwork_ids}
    if not artwork_ids:
        return result
    rows = session.execute(
        select(ArtworkTag.artwork_id, Tag)
        .join(Tag, Tag.id == ArtworkTag.tag_id)
        .where(ArtworkTag.artwork_id.in_(artwork_ids))
        .order_by(Tag.name)
    )
    for artwork_id, tag in rows:
        result[artwork_id].append(tag)
    return result


# ---- create -------------------------------------------------------------------------------------
def _default_title(photo: Photo) -> str:
    if photo.place_name:
        return photo.place_name
    return PurePath(photo.original_filename).stem[:256]


def create_artwork(
    session: Session,
    photo_ids: Sequence[str],
    *,
    style_id: str | None = None,
    layout_id: str | None = None,
    placement: str | None = None,
    title: str | None = None,
) -> Artwork:
    """New draft from photos (in slot order), a frame style and a layout (defaults when omitted).

    Photos leave the inbox; their pending upload metadata (favorite, collections) is applied once.
    """
    photos = {
        p.id: p
        for p in session.scalars(
            select(Photo).where(Photo.id.in_(set(photo_ids)), Photo.deleted_at.is_(None))
        )
    }
    missing = [i for i in photo_ids if i not in photos]
    if missing:
        raise ProblemError(422, "unknown_photo", "Unknown photo", missing[0])
    default_style, default_layout = templates.defaults(session)
    style_row, style = templates.get_style(session, style_id or default_style)
    if layout_id is None:
        layout_id = _layout_for(session, default_layout, len(photo_ids))
    layout_row, layout = templates.get_layout(session, layout_id)
    if len(photo_ids) > len(layout.slots):
        raise ProblemError(
            422,
            "too_many_photos",
            "Too many photos for this layout",
            f"{layout_row.name} has {len(layout.slots)} slot(s)",
        )
    inputs = [PhotoInput(i, Size(photos[i].width, photos[i].height)) for i in photo_ids]
    doc = build_document(style, layout, inputs, placement)  # type: ignore[arg-type]
    check_references(session, doc)

    first = photos[photo_ids[0]] if photo_ids else None
    artwork = Artwork(
        title=(title if title is not None else (_default_title(first) if first else ""))[:256],
        origin_style_id=style_row.id,
        origin_style_revision=style_row.revision,
        origin_layout_id=layout_row.id,
        origin_layout_revision=layout_row.revision,
    )
    session.add(artwork)
    session.flush()
    _store_document(session, artwork, doc)
    _apply_pending_meta(session, artwork, list(photos))
    for photo in photos.values():
        if photo.inbox_state == "inbox":
            photo.inbox_state = "processed"
    return artwork


def _layout_for(session: Session, default_layout: str, photo_count: int) -> str:
    """The default layout if it has enough slots, else the first built-in with that slot count."""
    row = session.get(Layout, default_layout)
    if row is not None and row.slot_count >= max(1, photo_count):
        return row.id
    candidate = session.scalars(
        select(Layout.id)
        .where(Layout.slot_count == photo_count)
        .order_by(Layout.builtin.desc(), Layout.name)
    ).first()
    if candidate is None:
        raise ProblemError(
            422, "no_layout", "No layout for this number of photos", str(photo_count)
        )
    return candidate


def _apply_pending_meta(session: Session, artwork: Artwork, photo_ids: list[str]) -> None:
    metas = list(
        session.scalars(select(PhotoPendingMeta).where(PhotoPendingMeta.photo_id.in_(photo_ids)))
    )
    collection_ids: list[str] = []
    for meta in metas:
        artwork.favorite = artwork.favorite or meta.favorite
        collection_ids.extend(str(c) for c in meta.collection_ids)
        session.delete(meta)
    if not collection_ids:
        return
    manual = session.scalars(
        select(Collection.id).where(
            Collection.id.in_(set(collection_ids)), Collection.kind == "manual"
        )
    )
    for collection_id in manual:
        position = session.scalar(
            select(func.coalesce(func.max(CollectionItem.position), 0.0)).where(
                CollectionItem.collection_id == collection_id
            )
        )
        session.add(
            CollectionItem(
                collection_id=collection_id,
                artwork_id=artwork.id,
                position=float(position or 0) + 1,
            )
        )


# ---- document saves -----------------------------------------------------------------------------
def save_document(
    session: Session, artwork_id: str, raw: Mapping[str, Any], expected_version: int
) -> Artwork:
    """Replace the document if `expected_version` is current (409 `version_conflict` otherwise)."""
    artwork = get_artwork(session, artwork_id)
    if artwork.document_version != expected_version:
        raise ProblemError(
            409,
            "version_conflict",
            "The artwork was modified elsewhere",
            extra={"current_version": artwork.document_version},
        )
    doc = validated(session, raw)
    _store_document(session, artwork, doc)
    artwork.document_version += 1
    artwork.updated_at = utcnow()
    return artwork


def update_artwork(
    session: Session,
    artwork_id: str,
    *,
    title: str | None = None,
    favorite: bool | None = None,
    status: str | None = None,
    tag_ids: Sequence[str] | None = None,
) -> Artwork:
    artwork = get_artwork(session, artwork_id)
    if title is not None:
        artwork.title = title.strip()[:256]
    if favorite is not None:
        artwork.favorite = favorite
    if status == "ready":
        mark_ready(session, artwork_id)
    elif status == "draft":
        artwork.status = "draft"
    elif status is not None:
        raise ProblemError(422, "invalid_status", "Invalid status")
    if tag_ids is not None:
        unique = list(dict.fromkeys(tag_ids))
        known = set(session.scalars(select(Tag.id).where(Tag.id.in_(unique))))
        if len(known) != len(unique):
            raise ProblemError(422, "unknown_tag", "Unknown tag")
        session.execute(delete(ArtworkTag).where(ArtworkTag.artwork_id == artwork.id))
        session.add_all(ArtworkTag(artwork_id=artwork.id, tag_id=t) for t in unique)
    artwork.updated_at = utcnow()
    return artwork


def mark_ready(session: Session, artwork_id: str) -> Artwork:
    """Explicit validation: a complete, valid document becomes displayable (`ready`)."""
    artwork = get_artwork(session, artwork_id)
    doc = document_of(artwork)
    check_references(session, doc)
    if doc.quality().is_incomplete:
        raise ProblemError(422, "artwork_incomplete", "The artwork has empty slots")
    artwork.status = "ready"
    artwork.updated_at = utcnow()
    return artwork


def duplicate_artwork(session: Session, artwork_id: str) -> Artwork:
    source = get_artwork(session, artwork_id)
    copy = Artwork(
        title=source.title,
        status="draft",
        origin_style_id=source.origin_style_id,
        origin_style_revision=source.origin_style_revision,
        origin_layout_id=source.origin_layout_id,
        origin_layout_revision=source.origin_layout_revision,
    )
    session.add(copy)
    session.flush()
    _store_document(session, copy, document_of(source))
    tag_ids = session.scalars(select(ArtworkTag.tag_id).where(ArtworkTag.artwork_id == source.id))
    session.add_all(ArtworkTag(artwork_id=copy.id, tag_id=t) for t in tag_ids)
    return copy


def trash_artwork(session: Session, artwork_id: str) -> Artwork:
    """Soft delete (restore and purge: Phase 8 trash)."""
    artwork = get_artwork(session, artwork_id)
    artwork.deleted_at = utcnow()
    artwork.trash_batch_id = new_id()
    return artwork


# ---- snapshots ----------------------------------------------------------------------------------
def create_snapshot(session: Session, artwork_id: str, reason: str) -> ArtworkSnapshot:
    if reason not in SNAPSHOT_REASONS:
        raise ProblemError(422, "invalid_reason", "Invalid snapshot reason")
    artwork = get_artwork(session, artwork_id)
    snapshot = ArtworkSnapshot(
        artwork_id=artwork.id,
        document=artwork.document,
        document_version=artwork.document_version,
        reason=reason,
    )
    session.add(snapshot)
    session.flush()
    stale = session.scalars(
        select(ArtworkSnapshot.id)
        .where(ArtworkSnapshot.artwork_id == artwork.id)
        .order_by(ArtworkSnapshot.created_at.desc(), ArtworkSnapshot.id.desc())
        .offset(MAX_SNAPSHOTS)
    ).all()
    if stale:
        session.execute(delete(ArtworkSnapshot).where(ArtworkSnapshot.id.in_(stale)))
    return snapshot


def list_snapshots(session: Session, artwork_id: str) -> list[ArtworkSnapshot]:
    get_artwork(session, artwork_id)
    return list(
        session.scalars(
            select(ArtworkSnapshot)
            .where(ArtworkSnapshot.artwork_id == artwork_id)
            .order_by(ArtworkSnapshot.created_at.desc(), ArtworkSnapshot.id.desc())
        )
    )


def restore_snapshot(session: Session, artwork_id: str, snapshot_id: str) -> Artwork:
    """Restore a snapshot as a new document version (the current one is snapshotted first)."""
    artwork = get_artwork(session, artwork_id)
    snapshot = session.get(ArtworkSnapshot, snapshot_id)
    if snapshot is None or snapshot.artwork_id != artwork.id:
        raise not_found("Snapshot")
    document = dict(snapshot.document)
    create_snapshot(session, artwork_id, "pre_restore")
    return save_document(session, artwork_id, document, artwork.document_version)


# ---- listing ------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ArtworkPage:
    items: list[Artwork]
    tags: dict[str, list[Tag]]
    next_cursor: str | None


def _encode_cursor(artwork: Artwork) -> str:
    raw = f"{artwork.created_at.isoformat()}|{artwork.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        stamp, artwork_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
        return datetime.fromisoformat(stamp), artwork_id
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProblemError(400, "invalid_cursor", "Invalid cursor") from exc


def list_artworks(
    session: Session,
    *,
    status: str | None = None,
    favorite: bool | None = None,
    photo_id: str | None = None,
    cursor: str | None = None,
    limit: int = 100,
) -> ArtworkPage:
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(Artwork).where(Artwork.deleted_at.is_(None))
    if status is not None:
        stmt = stmt.where(Artwork.status == status)
    if favorite is not None:
        stmt = stmt.where(Artwork.favorite.is_(favorite))
    if photo_id is not None:
        stmt = stmt.where(
            Artwork.id.in_(select(ArtworkPhoto.artwork_id).where(ArtworkPhoto.photo_id == photo_id))
        )
    if cursor:
        stamp, artwork_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Artwork.created_at < stamp,
                and_(Artwork.created_at == stamp, Artwork.id < artwork_id),
            )
        )
    rows = list(
        session.scalars(
            stmt.order_by(Artwork.created_at.desc(), Artwork.id.desc()).limit(limit + 1)
        )
    )
    next_cursor = _encode_cursor(rows[limit - 1]) if len(rows) > limit else None
    items = rows[:limit]
    return ArtworkPage(items, tags_for(session, [a.id for a in items]), next_cursor)
