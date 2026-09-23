"""Ingest pipeline: completed upload → validated original + metadata + proxies → inbox.

A file whose image is already in the library (same content fingerprint) is merged into that photo
instead (services/photo_copies.py).

Runs as the `ingest` job (lane `ingest`). Idempotent: re-running after a crash is safe.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from the_frame_v2.context import AppContext
from the_frame_v2.db.models import Photo, PhotoPendingMeta, PhotoTag, UploadSession
from the_frame_v2.events import Event
from the_frame_v2.imaging import decode
from the_frame_v2.imaging.decode import DecodeError, ProbeResult
from the_frame_v2.imaging.fingerprint import content_fingerprint
from the_frame_v2.jobs.queue import JobContext, PermanentJobError
from the_frame_v2.services import photo_copies, search

log = logging.getLogger(__name__)

TV_WIDTH, TV_HEIGHT = 3840, 2160
POSSIBLY_DOWNSCALED_LONG_EDGE = 2000


def quality_warnings(result: ProbeResult) -> list[str]:
    """Hints shown to the user. Heuristics documented in docs/research/phone-uploads.md."""
    warnings: list[str] = []
    long_edge = max(result.width, result.height)
    if not result.metadata.has_capture_info:
        warnings.append("metadata_missing")
    if result.metadata.location_removed:
        warnings.append("location_removed")
    if long_edge < POSSIBLY_DOWNSCALED_LONG_EDGE:
        warnings.append("possibly_downscaled")
    elif result.width < TV_WIDTH and result.height < TV_HEIGHT:
        warnings.append("below_tv_resolution")
    if result.bit_depth > 8 and result.sniffed.kind == "png":
        warnings.append("high_bit_depth_reduced")
    return warnings


def ensure_derivatives(ctx: AppContext, sha256: str, original: Path) -> None:
    """(Re)generate proxy and thumbnails if missing (cache is disposable)."""
    thumbs = {size: ctx.storage.thumb_path(sha256, size) for size in decode.THUMB_SIZES}
    proxy = ctx.storage.proxy_path(sha256)
    if proxy.exists() and all(p.exists() for p in thumbs.values()):
        return
    decode.write_proxy_and_thumbs(original, proxy, thumbs)


def _fail(ctx: AppContext, upload: UploadSession, code: str, message: str) -> None:
    with ctx.db.session() as s:
        row = s.get(UploadSession, upload.id)
        if row is not None:
            row.state = "failed"
            row.error = code
    ctx.storage.upload_temp_path(upload.id).unlink(missing_ok=True)
    ctx.broker.publish(
        Event(
            "photo.ingest_failed",
            {
                "upload_id": upload.id,
                "sha256": upload.sha256,
                "filename": upload.filename,
                "code": code,
                "message": message,
            },
            device_key=upload.device_key,
        )
    )


def ingest_upload(ctx: AppContext, upload_id: str, *, _retry: bool = True) -> str | None:
    with ctx.db.session() as s:
        upload = s.get(UploadSession, upload_id)
        if upload is None:
            return None  # already ingested (session removed) or cancelled
        s.expunge(upload)
    temp = ctx.storage.upload_temp_path(upload.id)

    with ctx.db.session() as s:
        existing_id = photo_copies.photo_id_for_hash(s, upload.sha256)
        existing = s.get(Photo, existing_id) if existing_id is not None else None
        if existing is not None:
            photo_copies.receive_again(existing)
    if existing_id is not None:
        _finish_as_existing(ctx, upload, existing_id, merged=[])
        return existing_id

    if not temp.exists():
        _fail(ctx, upload, "upload_missing", "Uploaded file is missing")
        raise PermanentJobError("upload_missing")
    try:
        result = decode.probe(temp, ctx.settings.max_image_pixels)
    except DecodeError as exc:
        _fail(ctx, upload, exc.code, str(exc))
        raise PermanentJobError(exc.code, str(exc)) from exc

    meta = result.metadata
    place = None
    if meta.gps_lat is not None and meta.gps_lon is not None:
        try:
            place = ctx.geocoder.reverse(meta.gps_lat, meta.gps_lon)
        except Exception:
            log.warning("reverse geocoding failed", exc_info=True)

    fingerprint = content_fingerprint(temp, result.sniffed.kind)
    with ctx.db.session() as s:
        same_image = s.scalars(
            select(Photo.id).where(Photo.content_fingerprint == fingerprint)
        ).first()
    if same_image is not None:
        copy = photo_copies.IncomingCopy(
            sha256=upload.sha256,
            size=upload.size,
            filename=upload.filename,
            path=temp,
            probe=result,
            place=place,
            warnings=quality_warnings(result),
        )
        merged = photo_copies.merge_copy(ctx, same_image, copy)
        _finish_as_existing(ctx, upload, same_image, merged=merged)
        return same_image

    original = ctx.storage.original_path(upload.sha256, result.sniffed.ext)
    original.parent.mkdir(parents=True, exist_ok=True)
    if not original.exists():
        tmp_target = original.with_suffix(original.suffix + ".tmp")
        shutil.copyfile(temp, tmp_target)
        tmp_target.replace(original)
    try:
        ensure_derivatives(ctx, upload.sha256, original)
    except DecodeError as exc:
        original.unlink(missing_ok=True)
        _fail(ctx, upload, exc.code, str(exc))
        raise PermanentJobError(exc.code, str(exc)) from exc

    pending: dict[str, Any] = upload.pending_meta or {}
    is_device = upload.device_key != "localhost" and ":" not in upload.device_key
    device_id = upload.device_key if is_device else None
    try:
        with ctx.db.session() as s:
            photo = Photo(
                sha256=upload.sha256,
                content_fingerprint=fingerprint,
                ext=result.sniffed.ext,
                mime=result.sniffed.mime,
                original_filename=upload.filename,
                file_size=upload.size,
                width=result.width,
                height=result.height,
                exif_orientation=result.orientation,
                bit_depth=result.bit_depth,
                icc_description=meta.icc_description,
                is_wide_gamut=meta.is_wide_gamut,
                has_gain_map=result.has_gain_map,
                taken_at=meta.taken_at,
                camera_make=meta.camera_make,
                camera_model=meta.camera_model,
                lens=meta.lens,
                gps_lat=meta.gps_lat,
                gps_lon=meta.gps_lon,
                place_name=place.name if place else None,
                place_admin1=place.admin1 if place else None,
                place_country=place.country if place else None,
                uploaded_by_device_id=device_id,
                quality_warnings=quality_warnings(result),
            )
            s.add(photo)
            s.flush()
            for tag_id in pending.get("tag_ids", []):
                s.add(PhotoTag(photo_id=photo.id, tag_id=tag_id))
            if pending.get("collection_ids") or pending.get("favorite"):
                s.add(
                    PhotoPendingMeta(
                        photo_id=photo.id,
                        collection_ids=list(pending.get("collection_ids", [])),
                        favorite=bool(pending.get("favorite")),
                    )
                )
            row = s.get(UploadSession, upload.id)
            if row is not None:
                s.delete(row)
            search.index_photo(s, photo)
            photo_id = photo.id
    except IntegrityError:
        if not _retry:
            raise
        # Another worker ingested the same file or image concurrently: take the dedupe/merge path.
        return ingest_upload(ctx, upload_id, _retry=False)
    temp.unlink(missing_ok=True)
    _publish_ingested(ctx, upload, photo_id, duplicate=False)
    return photo_id


def _finish_as_existing(
    ctx: AppContext, upload: UploadSession, photo_id: str, *, merged: list[str]
) -> None:
    with ctx.db.session() as s:
        row = s.get(UploadSession, upload.id)
        if row is not None:
            s.delete(row)
    ctx.storage.upload_temp_path(upload.id).unlink(missing_ok=True)
    _publish_ingested(ctx, upload, photo_id, duplicate=True, merged=merged)


def _publish_ingested(
    ctx: AppContext,
    upload: UploadSession,
    photo_id: str,
    *,
    duplicate: bool,
    merged: list[str] | None = None,
) -> None:
    ctx.broker.publish(
        Event(
            "photo.ingested",
            {
                "photo_id": photo_id,
                "upload_id": upload.id,
                "sha256": upload.sha256,
                "filename": upload.filename,
                "duplicate": duplicate,
                "merged": merged or [],
            },
            device_key=upload.device_key,
        )
    )


def ingest_job(ctx: AppContext) -> Any:
    def handler(job: JobContext) -> None:
        upload_id = str(job.payload["upload_id"])
        try:
            ingest_upload(ctx, upload_id)
        except PermanentJobError:
            raise
        except (
            Exception
        ) as exc:  # unexpected: fail visibly instead of retrying a deterministic error
            log.exception("ingest of upload %s failed", upload_id)
            with ctx.db.session() as s:
                upload = s.get(UploadSession, upload_id)
                if upload is not None:
                    s.expunge(upload)
            if upload is not None:
                _fail(ctx, upload, "ingest_failed", str(exc))
            raise PermanentJobError("ingest_failed", str(exc)) from exc

    return handler
