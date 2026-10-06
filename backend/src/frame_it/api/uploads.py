from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from frame_it.api.deps import Ctx, DbSession, Uploader
from frame_it.api.schemas import (
    HashCheckIn,
    HashCheckOut,
    HashStatusOut,
    UploadCreateIn,
    UploadOut,
)
from frame_it.api.system import UPLOAD_CHUNK_BYTES
from frame_it.auth.principal import Principal
from frame_it.db.models import UploadSession
from frame_it.errors import ProblemError, not_found
from frame_it.events import Event
from frame_it.services import uploads

router = APIRouter(prefix="/uploads", tags=["uploads"])
_session_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _device_key(principal: Principal) -> str:
    key = principal.device_key
    assert key is not None  # guaranteed for authenticated principals
    return key


def _out(upload: UploadSession) -> UploadOut:
    status: Literal["open", "processing", "failed"] = (
        "open"
        if upload.state == "open"
        else "processing"
        if upload.state == "processing"
        else "failed"
    )
    return UploadOut(
        status=status,
        upload_id=upload.id,
        offset=upload.received_bytes,
        size=upload.size,
        error=upload.error,
        chunk_bytes=UPLOAD_CHUNK_BYTES,
    )


@router.post("/check")
def check_hashes(body: HashCheckIn, principal: Uploader, session: DbSession) -> HashCheckOut:
    """Tell which files (by SHA-256) are already known, so clients can skip them."""
    results = uploads.check_hashes(session, _device_key(principal), body.sha256)
    return HashCheckOut(results=[HashStatusOut.model_validate(r) for r in results])


@router.post("")
def create_upload(
    body: UploadCreateIn, principal: Uploader, ctx: Ctx, session: DbSession
) -> UploadOut:
    """Open a resumable upload session, or resume the existing one for the same file."""
    result = uploads.open_session(
        ctx,
        session,
        device_key=_device_key(principal),
        filename=body.filename,
        size=body.size,
        sha256=body.sha256,
        mime=body.mime,
        meta=body.meta.model_dump() if body.meta else None,
    )
    if result.status == "exists" or result.session is None:
        session.commit()  # the photo is back in the inbox (services/photo_copies.py)
        ctx.broker.publish(Event("photo.updated", {"photo_ids": [result.photo_id]}))
        return UploadOut(
            status="exists",
            size=body.size,
            offset=body.size,
            photo_id=result.photo_id,
            chunk_bytes=UPLOAD_CHUNK_BYTES,
        )
    return _out(result.session)


@router.get("/{upload_id}")
def get_upload(upload_id: str, principal: Uploader, session: DbSession) -> UploadOut:
    return _out(uploads.get_session_for(session, upload_id, _device_key(principal)))


@router.head("/{upload_id}")
def head_upload(upload_id: str, principal: Uploader, session: DbSession) -> Response:
    upload = uploads.get_session_for(session, upload_id, _device_key(principal))
    return Response(
        headers={
            "Upload-Offset": str(upload.received_bytes),
            "Upload-Length": str(upload.size),
            "Cache-Control": "no-store",
        }
    )


@router.patch(
    "/{upload_id}",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/offset+octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        }
    },
)
async def append_chunk(
    upload_id: str, request: Request, principal: Uploader, ctx: Ctx
) -> UploadOut:
    """Append a chunk at `Upload-Offset`. Completing the file verifies it and starts ingestion."""
    device_key = _device_key(principal)
    try:
        offset = int(request.headers["upload-offset"])
    except (KeyError, ValueError) as exc:
        raise ProblemError(400, "missing_offset", "Upload-Offset header required") from exc

    async with _session_locks[upload_id]:

        def load() -> UploadSession:
            with ctx.db.session() as s:
                upload = uploads.get_session_for(s, upload_id, device_key)
                s.expunge(upload)
                return upload

        upload = await run_in_threadpool(load)
        if upload.state != "open":
            return _out(upload)
        if offset != upload.received_bytes:
            raise ProblemError(
                409,
                "offset_mismatch",
                "Offset does not match",
                extra={"offset": upload.received_bytes},
            )
        temp = ctx.storage.upload_temp_path(upload.id)
        written = 0
        with temp.open("r+b" if temp.exists() else "wb") as fh:
            fh.seek(offset)
            fh.truncate()
            try:
                async for chunk in request.stream():
                    if not chunk:
                        continue
                    if (
                        written + len(chunk) > uploads.MAX_CHUNK_BYTES
                        or offset + written + len(chunk) > upload.size
                    ):
                        fh.truncate(offset)
                        raise ProblemError(413, "chunk_too_large", "Chunk too large")
                    await run_in_threadpool(fh.write, chunk)
                    written += len(chunk)
            except ClientDisconnect:
                pass  # keep what arrived: the client resumes from the committed offset

        new_offset = offset + written

        def commit() -> UploadSession:
            with ctx.db.session() as s:
                row = s.get(UploadSession, upload_id)
                if row is None:
                    raise not_found("Upload")
                row.received_bytes = new_offset
                s.flush()
                s.expunge(row)
                return row

        upload = await run_in_threadpool(commit)
        if new_offset == upload.size:
            upload = await run_in_threadpool(uploads.finalize, ctx, upload_id)
    return _out(upload)


@router.delete("/{upload_id}", status_code=204)
def cancel_upload(upload_id: str, principal: Uploader, ctx: Ctx, session: DbSession) -> None:
    upload = uploads.get_session_for(session, upload_id, _device_key(principal))
    uploads.cancel(ctx, session, upload)
