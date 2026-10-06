"""Merging copies of the same photo (same content fingerprint, different EXIF/file name).

Phone browsers upload GPS-redacted files; the Android photo picker renames them (MediaStore ids).
When another copy of the same image arrives (USB, LocalSend, "Files" picker), it completes the
existing photo instead of creating a duplicate:

Whatever the source (browser, LocalSend, drag and drop), receiving a photo again puts it back in the
inbox (`receive_again`): sending it from the phone is the natural way to bring it back.

- the copy has a location the photo lacks → the copy **replaces the original file** (identical image
  data, richer metadata); the previous SHA-256 is kept as an alias;
- otherwise the copy's SHA-256 becomes an alias (re-uploads of it dedupe immediately);
- a real file name replaces a generated one (`1000125423.jpg`) either way.

Spec: docs/data-model.md ("Photo copies").
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from frame_it.context import AppContext
from frame_it.db.models import Photo, PhotoHashAlias
from frame_it.imaging.decode import ProbeResult
from frame_it.imaging.fingerprint import content_fingerprint
from frame_it.jobs.queue import JobContext
from frame_it.services import search
from frame_it.services.geocode import Place

log = logging.getLogger(__name__)

_GENERATED_NAME = re.compile(r"^\d+\.[A-Za-z0-9]+$")
BACKFILL_JOB = "fingerprint_backfill"


def is_generated_name(filename: str) -> bool:
    """Names like `1000125423.jpg` (Android photo picker: MediaStore id, not the camera name)."""
    return bool(_GENERATED_NAME.match(filename))


def receive_again(photo: Photo) -> bool:
    """A copy of a photo in the library arrived: bring it back (out of the trash, into the inbox).

    Returns True if it was in the trash. The original file, tags and artworks are untouched; the
    import date is kept, so the photo keeps its place in the library."""
    restored = photo.deleted_at is not None
    photo.deleted_at = None
    photo.trash_batch_id = None
    photo.inbox_state = "inbox"
    return restored


def photo_id_for_hash(session: Session, sha256: str) -> str | None:
    """Photo whose file or one of its merged copies has this SHA-256."""
    photo_id = session.scalars(select(Photo.id).where(Photo.sha256 == sha256)).first()
    if photo_id is None:
        photo_id = session.scalars(
            select(PhotoHashAlias.photo_id).where(PhotoHashAlias.sha256 == sha256)
        ).first()
    return photo_id


def photo_ids_for_hashes(session: Session, hashes: list[str]) -> dict[str, str]:
    found = {
        row.sha256: row.id
        for row in session.execute(select(Photo.sha256, Photo.id).where(Photo.sha256.in_(hashes)))
    }
    for row in session.execute(
        select(PhotoHashAlias.sha256, PhotoHashAlias.photo_id).where(
            PhotoHashAlias.sha256.in_(hashes)
        )
    ):
        found.setdefault(row.sha256, row.photo_id)
    return found


@dataclass(frozen=True, slots=True)
class IncomingCopy:
    sha256: str
    size: int
    filename: str
    path: Path
    probe: ProbeResult
    place: Place | None
    warnings: list[str]


def merge_copy(ctx: AppContext, photo_id: str, copy: IncomingCopy) -> list[str]:
    """Merge `copy` into the photo; returns what was improved (`location`, `filename`)."""
    meta = copy.probe.metadata
    merged: list[str] = []
    replaced: tuple[str, str] | None = None
    with ctx.db.session() as s:
        photo = s.get(Photo, photo_id)
        if photo is None:
            raise LookupError(photo_id)
        receive_again(photo)
        if meta.gps_lat is not None and photo.gps_lat is None:
            target = ctx.storage.original_path(copy.sha256, copy.probe.sniffed.ext)
            _copy_atomic(copy.path, target)
            replaced = (photo.sha256, photo.ext)
            s.add(PhotoHashAlias(sha256=photo.sha256, photo_id=photo.id))
            photo.sha256 = copy.sha256
            photo.file_size = copy.size
            photo.gps_lat, photo.gps_lon = meta.gps_lat, meta.gps_lon
            photo.place_name = copy.place.name if copy.place else None
            photo.place_admin1 = copy.place.admin1 if copy.place else None
            photo.place_country = copy.place.country if copy.place else None
            photo.quality_warnings = copy.warnings
            merged.append("location")
        else:
            s.add(PhotoHashAlias(sha256=copy.sha256, photo_id=photo.id))
        if is_generated_name(photo.original_filename) and not is_generated_name(copy.filename):
            photo.original_filename = copy.filename
            merged.append("filename")
        s.flush()
        search.index_photo(s, photo)
    if replaced is not None:
        _retire_original(ctx, *replaced, new_sha=copy.sha256)
    log.info("merged copy %s into photo %s: %s", copy.sha256[:12], photo_id, merged or "alias")
    return merged


def _copy_atomic(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return
    tmp = target.with_suffix(target.suffix + ".tmp")
    shutil.copyfile(source, tmp)
    tmp.replace(target)


def _retire_original(ctx: AppContext, old_sha: str, old_ext: str, *, new_sha: str) -> None:
    """Reuse derivatives (identical pixels) and delete the superseded original file."""
    for old_dir, new_dir in (
        (ctx.storage.proxy_path(old_sha).parent, ctx.storage.proxy_path(new_sha).parent),
        (ctx.storage.thumb_path(old_sha, 256).parent, ctx.storage.thumb_path(new_sha, 256).parent),
    ):
        if old_dir.is_dir() and not new_dir.exists():
            old_dir.replace(new_dir)
        else:
            shutil.rmtree(old_dir, ignore_errors=True)
    ctx.storage.original_path(old_sha, old_ext).unlink(missing_ok=True)


# ---- backfill for photos ingested before fingerprints existed ------------------------------------
def needs_backfill(ctx: AppContext) -> bool:
    with ctx.db.session() as s:
        return (
            s.scalars(select(Photo.id).where(Photo.content_fingerprint.is_(None)).limit(1)).first()
            is not None
        )


def backfill_fingerprints(ctx: AppContext) -> int:
    """Compute missing fingerprints. Collisions (copies imported before this feature) stay NULL."""
    with ctx.db.session() as s:
        rows = s.execute(
            select(Photo.id, Photo.sha256, Photo.ext).where(Photo.content_fingerprint.is_(None))
        ).all()
    done = 0
    for photo_id, sha, ext in rows:
        original = ctx.storage.original_path(sha, ext)
        if not original.exists():
            log.warning("fingerprint backfill: original of %s missing", photo_id)
            continue
        fingerprint = content_fingerprint(original, "jpeg" if ext == "jpg" else ext)
        try:
            with ctx.db.session() as s:
                photo = s.get(Photo, photo_id)
                if photo is not None:
                    photo.content_fingerprint = fingerprint
            done += 1
        except IntegrityError:
            log.warning("fingerprint backfill: photo %s duplicates another photo's image", photo_id)
    return done


def backfill_job(ctx: AppContext) -> Any:
    def handler(_: JobContext) -> None:
        backfill_fingerprints(ctx)

    return handler
