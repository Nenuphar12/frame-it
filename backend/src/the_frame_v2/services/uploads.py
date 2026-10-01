"""Resumable upload sessions. Protocol: docs/PLAN.md §10 (uploads) and docs/data-model.md.

1. `check_hashes` lets clients skip files already in the library.
2. `open_session` creates (or resumes, keyed by device + sha256 + size) a session.
3. Chunks are appended at the declared offset (`append_chunk`, called by the API layer).
4. When complete, the file hash is verified and an `ingest` job is enqueued.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from the_frame_v2.context import AppContext
from the_frame_v2.db.models import Collection, Photo, Tag, UploadSession
from the_frame_v2.errors import ProblemError, not_found
from the_frame_v2.ids import utcnow
from the_frame_v2.services import photo_copies
from the_frame_v2.services import photos as photos_service

MAX_CHUNK_BYTES = 16 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def validate_sha256(value: str) -> str:
    value = value.lower()
    if not _SHA256_RE.match(value):
        raise ProblemError(422, "invalid_sha256", "Invalid SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class HashStatus:
    sha256: str
    status: str
    """new | exists | in_progress"""
    photo_id: str | None = None
    upload_id: str | None = None
    offset: int | None = None


def check_hashes(session: Session, device_key: str, hashes: list[str]) -> list[HashStatus]:
    normalized = [validate_sha256(h) for h in hashes]
    photos = photo_copies.photo_ids_for_hashes(session, normalized)
    uploads = {
        u.sha256: u
        for u in session.scalars(
            select(UploadSession).where(
                UploadSession.sha256.in_(normalized),
                UploadSession.device_key == device_key,
                UploadSession.state == "open",
            )
        )
    }
    results = []
    for sha in normalized:
        if (photo_id := photos.get(sha)) is not None:
            results.append(HashStatus(sha, "exists", photo_id=photo_id))
        elif (up := uploads.get(sha)) is not None:
            results.append(
                HashStatus(sha, "in_progress", upload_id=up.id, offset=up.received_bytes)
            )
        else:
            results.append(HashStatus(sha, "new"))
    return results


def _clean_meta(session: Session, meta: dict[str, Any]) -> dict[str, Any]:
    tag_ids = [str(t) for t in meta.get("tag_ids", [])][:100]
    collection_ids = [str(c) for c in meta.get("collection_ids", [])][:100]
    known_tags = set(session.scalars(select(Tag.id).where(Tag.id.in_(tag_ids))))
    known_cols = set(
        session.scalars(select(Collection.id).where(Collection.id.in_(collection_ids)))
    )
    return {
        "tag_ids": [t for t in tag_ids if t in known_tags],
        "collection_ids": [c for c in collection_ids if c in known_cols],
        "favorite": bool(meta.get("favorite", False)),
    }


@dataclass(frozen=True, slots=True)
class OpenResult:
    status: str
    """open | exists"""
    session: UploadSession | None
    photo_id: str | None = None


def open_session(
    ctx: AppContext,
    session: Session,
    *,
    device_key: str,
    filename: str,
    size: int,
    sha256: str,
    mime: str,
    meta: dict[str, Any] | None,
) -> OpenResult:
    sha256 = validate_sha256(sha256)
    if size <= 0:
        raise ProblemError(422, "empty_file", "File is empty")
    if size > ctx.settings.max_upload_bytes:
        raise ProblemError(413, "file_too_large", "File exceeds the upload limit")
    photo_id = photo_copies.photo_id_for_hash(session, sha256)
    photo = session.get(Photo, photo_id) if photo_id is not None else None
    if photo is not None:
        photo_copies.receive_again(photo)
        # Nothing is transferred, but what the sender chose for the batch still applies: the
        # phone page's tags, collections and favourite reach a photo the library already had.
        photos_service.apply_upload_meta(session, photo, _clean_meta(session, meta or {}))
        return OpenResult("exists", None, photo.id)
    existing = session.scalars(
        select(UploadSession).where(
            UploadSession.device_key == device_key,
            UploadSession.sha256 == sha256,
            UploadSession.size == size,
            UploadSession.state == "open",
        )
    ).first()
    if existing is not None:
        temp = ctx.storage.upload_temp_path(existing.id)
        actual = temp.stat().st_size if temp.exists() else 0
        if actual != existing.received_bytes:  # crash between write and commit: trust the disk
            existing.received_bytes = min(actual, existing.size)
        if meta is not None:
            existing.pending_meta = _clean_meta(session, meta)
        return OpenResult("open", existing)
    upload = UploadSession(
        device_key=device_key,
        sha256=sha256,
        size=size,
        filename=Path(filename).name[:512] or "upload",
        mime=mime[:128],
        pending_meta=_clean_meta(session, meta or {}),
        expires_at=utcnow() + timedelta(hours=ctx.settings.upload_session_ttl_hours),
    )
    session.add(upload)
    session.flush()
    ctx.storage.upload_temp_path(upload.id).touch()
    return OpenResult("open", upload)


def get_session_for(session: Session, upload_id: str, device_key: str) -> UploadSession:
    upload = session.get(UploadSession, upload_id)
    if upload is None or upload.device_key != device_key:
        raise not_found("Upload")
    return upload


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def finalize(ctx: AppContext, upload_id: str) -> UploadSession:
    """Verify a fully received upload and enqueue ingestion. Runs in a worker thread."""
    temp = ctx.storage.upload_temp_path(upload_id)
    actual_sha = file_sha256(temp)
    with ctx.db.session() as s:
        upload = s.get(UploadSession, upload_id)
        if upload is None:
            raise not_found("Upload")
        if actual_sha != upload.sha256:
            upload.state = "failed"
            upload.error = "checksum_mismatch"
            temp.unlink(missing_ok=True)
            s.commit()
            raise ProblemError(422, "checksum_mismatch", "Uploaded data does not match its hash")
        upload.state = "processing"
    job_id = ctx.jobs.enqueue("ingest", {"upload_id": upload_id})
    with ctx.db.session() as s:
        upload = s.get(UploadSession, upload_id)
        assert upload is not None
        upload.job_id = job_id
        s.expunge(upload)
    return upload


def cancel(ctx: AppContext, session: Session, upload: UploadSession) -> None:
    if upload.state == "processing":
        raise ProblemError(409, "upload_processing", "Upload is already being processed")
    ctx.storage.upload_temp_path(upload.id).unlink(missing_ok=True)
    session.delete(upload)


def purge_expired(ctx: AppContext) -> int:
    """Delete expired open/failed sessions and orphan temp files."""
    removed = 0
    with ctx.db.session() as s:
        expired = s.scalars(
            select(UploadSession).where(
                UploadSession.expires_at < utcnow(), UploadSession.state != "processing"
            )
        ).all()
        for upload in expired:
            ctx.storage.upload_temp_path(upload.id).unlink(missing_ok=True)
            s.delete(upload)
            removed += 1
        live = set(s.scalars(select(UploadSession.id)))
    if ctx.storage.uploads.is_dir():
        for part in ctx.storage.uploads.glob("*.part"):
            if part.stem not in live:
                part.unlink(missing_ok=True)
    return removed
