"""Trash: soft delete, cascade, restore and purge. Spec: docs/organization.md §5.

Photos and artworks carry `deleted_at` and a `trash_batch_id`: everything deleted by one gesture
shares a batch, so **restoring restores what was deleted together** — a photo and the artworks
that were trashed with it come back in one click.

Deleting a photo an artwork uses is the interesting case. The caller picks a **cascade**:

- `trash_artworks` (default) — the artworks that use it go to the trash in the same batch;
- `empty_slots` — the artworks stay, the photo leaves their slots. An emptied slot becomes a
  placeholder (`quality_lock = free`, crop = its rect, docs/geometry-and-quality.md), the artwork
  goes back to `draft`, and the change is snapshotted (`pre_trash`) so it is undoable.

`preview_photo_trash` answers the dialog before anything is written.

**Purge** is what frees disk: rows older than `trash_retention_days` are deleted for good, with
their originals (photos) and their render cache (artworks). It runs daily (`jobs.schedule_every`)
and on demand.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from the_frame_v2.context import AppContext
from the_frame_v2.db.models import Artwork, ArtworkPhoto, Photo, PhotoHashAlias
from the_frame_v2.errors import ProblemError
from the_frame_v2.events import Event
from the_frame_v2.ids import new_id, utcnow
from the_frame_v2.jobs.queue import JobContext, JobHandler
from the_frame_v2.services import artworks as artworks_service
from the_frame_v2.services import search

log = logging.getLogger(__name__)

PURGE_JOB = "trash.purge"
PURGE_INTERVAL_SECONDS = 24 * 3600
Cascade = str  # "trash_artworks" | "empty_slots"
CASCADES = ("trash_artworks", "empty_slots")


# ---- preview ------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class AffectedArtwork:
    artwork_id: str
    title: str
    slot_count: int
    """How many of the artwork's slots use one of the photos being deleted."""
    photo_count: int
    """How many photos the artwork holds in total (all of them ⇒ nothing would be left)."""


def preview_photo_trash(session: Session, photo_ids: Sequence[str]) -> list[AffectedArtwork]:
    """The artworks that use these photos — what the cascade dialog shows before deciding."""
    ids = set(photo_ids)
    if not ids:
        return []
    rows = session.execute(
        select(Artwork, func.count(ArtworkPhoto.slot_id))
        .join(ArtworkPhoto, ArtworkPhoto.artwork_id == Artwork.id)
        .where(ArtworkPhoto.photo_id.in_(ids), Artwork.deleted_at.is_(None))
        .group_by(Artwork.id)
        .order_by(Artwork.created_at.desc())
    )
    return [
        AffectedArtwork(artwork.id, artwork.title, int(count), artwork.photo_count)
        for artwork, count in rows
    ]


# ---- trashing -----------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TrashResult:
    batch_id: str
    photos: int
    artworks: int
    emptied: int
    """Artworks whose slots were emptied instead of being trashed."""


def trash_artworks(
    session: Session, artwork_ids: Sequence[str], batch_id: str | None = None
) -> TrashResult:
    batch = batch_id or new_id()
    rows = list(
        session.scalars(
            select(Artwork).where(Artwork.id.in_(set(artwork_ids)), Artwork.deleted_at.is_(None))
        )
    )
    now = utcnow()
    for artwork in rows:
        artwork.deleted_at = now
        artwork.trash_batch_id = batch
    search.remove(session, "artwork", [a.id for a in rows])
    return TrashResult(batch, 0, len(rows), 0)


def trash_photos(
    session: Session, photo_ids: Sequence[str], *, cascade: Cascade = "trash_artworks"
) -> TrashResult:
    """Soft-delete photos, applying `cascade` to the artworks that use them."""
    if cascade not in CASCADES:
        raise ProblemError(422, "invalid_cascade", "Invalid cascade", cascade)
    ids = list(dict.fromkeys(photo_ids))
    rows = list(session.scalars(select(Photo).where(Photo.id.in_(ids), Photo.deleted_at.is_(None))))
    if not rows:
        return TrashResult(new_id(), 0, 0, 0)
    batch = new_id()
    affected = preview_photo_trash(session, [p.id for p in rows])
    trashed_artworks, emptied = 0, 0
    if cascade == "trash_artworks":
        trashed_artworks = trash_artworks(session, [a.artwork_id for a in affected], batch).artworks
    else:
        for entry in affected:
            _empty_slots(session, entry.artwork_id, {p.id for p in rows})
            emptied += 1
    now = utcnow()
    for photo in rows:
        photo.deleted_at = now
        photo.trash_batch_id = batch
    search.remove(session, "photo", [p.id for p in rows])
    return TrashResult(batch, len(rows), trashed_artworks, emptied)


def _empty_slots(session: Session, artwork_id: str, photo_ids: set[str]) -> None:
    """Drop the photos from an artwork's slots, keeping the document valid (placeholders)."""
    artwork = artworks_service.get_artwork(session, artwork_id)
    doc = artworks_service.document_of(artwork)
    changed = False
    for slot in doc.slots:
        if slot.photo_id in photo_ids:
            slot.photo_id = None
            slot.quality_lock = "free"
            slot.source.crop.x, slot.source.crop.y = 0, 0
            slot.source.crop.w, slot.source.crop.h = slot.rect.w, slot.rect.h
            changed = True
    if not changed:
        return
    artworks_service.create_snapshot(session, artwork.id, "pre_trash")
    # Back through the regular path: structure, references and — while a composition is attached —
    # the solver, so an emptied slot leaves exactly the placeholder a new artwork would have.
    fresh = artworks_service.validated(session, doc.canonical())
    artworks_service.store_document(session, artwork, fresh)
    artwork.document_version += 1
    artwork.updated_at = utcnow()
    search.index_artwork(session, artwork)


# ---- restore ------------------------------------------------------------------------------------
def restore(
    session: Session,
    *,
    photo_ids: Sequence[str] = (),
    artwork_ids: Sequence[str] = (),
    batch_ids: Sequence[str] = (),
) -> TrashResult:
    """Bring items back. A batch id restores everything that was deleted in the same gesture."""
    photo_stmt = select(Photo).where(Photo.deleted_at.is_not(None))
    artwork_stmt = select(Artwork).where(Artwork.deleted_at.is_not(None))
    photo_filters = []
    artwork_filters = []
    if photo_ids:
        photo_filters.append(Photo.id.in_(set(photo_ids)))
    if artwork_ids:
        artwork_filters.append(Artwork.id.in_(set(artwork_ids)))
    if batch_ids:
        photo_filters.append(Photo.trash_batch_id.in_(set(batch_ids)))
        artwork_filters.append(Artwork.trash_batch_id.in_(set(batch_ids)))
    photos = list(session.scalars(photo_stmt.where(or_(*photo_filters)))) if photo_filters else []
    artworks = (
        list(session.scalars(artwork_stmt.where(or_(*artwork_filters)))) if artwork_filters else []
    )
    for photo in photos:
        photo.deleted_at = None
        photo.trash_batch_id = None
        search.index_photo(session, photo)
    for artwork in artworks:
        artwork.deleted_at = None
        artwork.trash_batch_id = None
        search.index_artwork(session, artwork)
    return TrashResult(batch_ids[0] if batch_ids else "", len(photos), len(artworks), 0)


# ---- listing ------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TrashPage:
    photos: list[Photo]
    artworks: list[Artwork]
    photo_total: int
    artwork_total: int


def list_trash(session: Session, limit: int = 200) -> TrashPage:
    limit = max(1, min(limit, 500))
    photos = list(
        session.scalars(
            select(Photo)
            .where(Photo.deleted_at.is_not(None))
            .order_by(Photo.deleted_at.desc(), Photo.id.desc())
            .limit(limit)
        )
    )
    artworks = list(
        session.scalars(
            select(Artwork)
            .where(Artwork.deleted_at.is_not(None))
            .order_by(Artwork.deleted_at.desc(), Artwork.id.desc())
            .limit(limit)
        )
    )
    photo_total = int(
        session.scalar(select(func.count(Photo.id)).where(Photo.deleted_at.is_not(None))) or 0
    )
    artwork_total = int(
        session.scalar(select(func.count(Artwork.id)).where(Artwork.deleted_at.is_not(None))) or 0
    )
    return TrashPage(photos, artworks, photo_total, artwork_total)


# ---- purge --------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PurgeResult:
    photos: int
    artworks: int
    bytes_freed: int


def purge(
    ctx: AppContext, *, older_than_days: int | None = None, all_items: bool = False
) -> PurgeResult:
    """Delete trashed rows for good, with their originals and render caches.

    `all_items` empties the trash now (the "Empty trash" button); otherwise only what has been
    there longer than `trash_retention_days` goes.
    """
    days = ctx.settings.trash_retention_days if older_than_days is None else older_than_days
    cutoff = utcnow() - timedelta(days=max(0, days))
    freed = 0
    with ctx.db.session() as session:
        photo_stmt = select(Photo).where(Photo.deleted_at.is_not(None))
        artwork_stmt = select(Artwork).where(Artwork.deleted_at.is_not(None))
        if not all_items:
            photo_stmt = photo_stmt.where(Photo.deleted_at < cutoff)
            artwork_stmt = artwork_stmt.where(Artwork.deleted_at < cutoff)
        photos = list(session.scalars(photo_stmt))
        artworks = list(session.scalars(artwork_stmt))
        shas = {p.sha256 for p in photos}
        aliases = set(
            session.scalars(
                select(PhotoHashAlias.sha256).where(
                    PhotoHashAlias.photo_id.in_([p.id for p in photos] or [""])
                )
            )
        )
        exts = {p.sha256: p.ext for p in photos}
        artwork_ids = [a.id for a in artworks]
        search.remove(session, "photo", [p.id for p in photos])
        search.remove(session, "artwork", artwork_ids)
        for photo in photos:
            session.delete(photo)
        for artwork in artworks:
            session.delete(artwork)
        session.flush()
        freed += _drop_artwork_caches(ctx, artwork_ids)
        freed += _drop_photo_files(ctx, shas, aliases, exts)
    if photos or artworks:
        log.info("purged %d photo(s) and %d artwork(s) from the trash", len(photos), len(artworks))
        ctx.broker.publish(
            Event(
                "trash.purged",
                {"photos": len(photos), "artworks": len(artworks), "bytes": freed},
                audience="all",
            )
        )
    return PurgeResult(len(photos), len(artworks), freed)


def _remove(target: Path) -> int:
    if target.is_dir():
        size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
        shutil.rmtree(target, ignore_errors=True)
        return size
    if target.is_file():
        size = target.stat().st_size
        target.unlink(missing_ok=True)
        return size
    return 0


def _drop_artwork_caches(ctx: AppContext, artwork_ids: Sequence[str]) -> int:
    return sum(_remove(ctx.storage.render_dir(artwork_id)) for artwork_id in artwork_ids)


def _drop_photo_files(
    ctx: AppContext, shas: set[str], aliases: set[str], exts: dict[str, str]
) -> int:
    freed = 0
    for sha in shas:
        freed += _remove(ctx.storage.original_path(sha, exts.get(sha, "jpg")))
        freed += _remove(ctx.storage.thumb_path(sha, 256).parent)
        freed += _remove(ctx.storage.proxy_path(sha).parent)
        freed += _remove(ctx.storage.palette_path(sha))
    for sha in aliases - shas:
        freed += _remove(ctx.storage.thumb_path(sha, 256).parent)
    return freed


def purge_job(ctx: AppContext) -> JobHandler:
    def handler(job: JobContext) -> None:
        purge(ctx, all_items=bool(job.payload.get("all")))

    return handler
