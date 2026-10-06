"""Export and import: `.tfarchive` files, rendered-image ZIPs and the dry-run import flow.

Spec: `docs/archive-format.md`. Both sides are jobs, because both can take minutes on a real
library: an export writes into `exports/<job_id>/` and is then downloadable; an import is received
in chunks, staged (validated + reported on) and only written when the caller says so.

Everything here is admin-only, and the receive protocol is the upload one (`Upload-Offset`) so a
dropped connection resumes instead of starting the archive again.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from frame_it.api.deps import Admin, Ctx, DbSession
from frame_it.api.schemas import (
    ExportOut,
    ExportRequestIn,
    ImportApplyOut,
    ImportCreateIn,
    ImportPoliciesIn,
    ImportReportOut,
    ImportSessionOut,
)
from frame_it.api.system import UPLOAD_CHUNK_BYTES
from frame_it.context import AppContext
from frame_it.db.models import ArchiveImport, Job
from frame_it.domain import archive as archive_domain
from frame_it.errors import ProblemError, not_found
from frame_it.services import archive_apply, archive_export, archive_import

router = APIRouter(tags=["archive"])
_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


# ---- exports ------------------------------------------------------------------------------------
def _export_out(ctx: AppContext, job: Job) -> ExportOut:
    payload = job.payload
    options = archive_export.options_from_payload(dict(payload))
    filename, size = None, None
    if job.state == "done":
        try:
            path = archive_export.export_file(ctx, job.id)
        except ProblemError:
            path = None  # swept by the retention sweep: the job is done, the file is gone
        if path is not None:
            filename, size = path.name, path.stat().st_size
    return ExportOut(
        job_id=job.id,
        kind=options.kind,
        scope=options.scope,
        state=job.state,
        progress=job.progress,
        filename=filename,
        bytes=size,
        error=job.error,
        created_at=job.created_at,
    )


@router.post("/exports", status_code=202)
def start_export(body: ExportRequestIn, _: Admin, ctx: Ctx, session: DbSession) -> ExportOut:
    """Queue an export. A selection makes it partial; no selection exports the whole library."""
    options = archive_export.ExportOptions(
        kind=body.kind,
        artwork_ids=tuple(body.artwork_ids),
        collection_ids=tuple(body.collection_ids),
        include_nested=body.include_nested,
        include_renders=body.include_renders,
        include_templates=body.include_templates,
        render_format=body.render_format,
    )
    job_id = archive_export.enqueue_export(ctx, options)
    job = session.get(Job, job_id)
    if job is None:
        raise not_found("Export")
    return _export_out(ctx, job)


@router.get("/exports")
def list_exports(_: Admin, ctx: Ctx, session: DbSession) -> list[ExportOut]:
    rows = session.scalars(
        select(Job)
        .where(Job.kind == archive_export.EXPORT_JOB)
        .order_by(Job.created_at.desc())
        .limit(20)
    )
    return [_export_out(ctx, job) for job in rows]


@router.get("/exports/{job_id}")
def get_export(job_id: str, _: Admin, ctx: Ctx, session: DbSession) -> ExportOut:
    job = session.get(Job, job_id)
    if job is None or job.kind != archive_export.EXPORT_JOB:
        raise not_found("Export")
    return _export_out(ctx, job)


@router.get("/exports/{job_id}/download", response_class=FileResponse)
def download_export(job_id: str, _: Admin, ctx: Ctx, session: DbSession) -> FileResponse:
    """Stream the finished file. `Content-Disposition` carries the name it was written under."""
    job = session.get(Job, job_id)
    if job is None or job.kind != archive_export.EXPORT_JOB:
        raise not_found("Export")
    if job.state != "done":
        raise ProblemError(409, "export_not_ready", "This export is not finished", job.state)
    path = archive_export.export_file(ctx, job_id)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
        headers={"Cache-Control": "no-store"},
    )


@router.delete("/exports/{job_id}", status_code=204)
def delete_export(job_id: str, _: Admin, ctx: Ctx, session: DbSession) -> None:
    """Drop the produced file (the job row stays as history)."""
    job = session.get(Job, job_id)
    if job is None or job.kind != archive_export.EXPORT_JOB:
        raise not_found("Export")
    directory = ctx.storage.export_dir(job_id)
    for path in directory.glob("*"):
        path.unlink(missing_ok=True)
    if directory.is_dir():
        directory.rmdir()


# ---- imports ------------------------------------------------------------------------------------
def _session_out(row: ArchiveImport) -> ImportSessionOut:
    summary: dict[str, Any] = row.summary or {}
    return ImportSessionOut(
        import_id=row.id,
        filename=row.filename,
        size=row.size,
        offset=row.received_bytes,
        state=row.state,
        error=row.error,
        scope=row.scope,
        chunk_bytes=UPLOAD_CHUNK_BYTES,
        created_at=row.created_at,
        new_items=sum(int(kind.get("new", 0)) for kind in summary.values()),
        conflicting_items=sum(int(kind.get("conflicting", 0)) for kind in summary.values()),
    )


@router.post("/imports")
def create_import(body: ImportCreateIn, _: Admin, ctx: Ctx, session: DbSession) -> ImportSessionOut:
    """Open a staging slot for an archive; the bytes follow as `PATCH` chunks."""
    row = archive_import.create_import(ctx, session, body.filename, body.size)
    return _session_out(row)


@router.get("/imports")
def list_imports(_: Admin, session: DbSession) -> list[ImportSessionOut]:
    return [_session_out(row) for row in archive_import.list_imports(session)]


@router.get("/imports/{import_id}")
def get_import(import_id: str, _: Admin, session: DbSession) -> ImportSessionOut:
    return _session_out(archive_import.get_import(session, import_id))


@router.patch(
    "/imports/{import_id}",
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
async def append_chunk(import_id: str, request: Request, _: Admin, ctx: Ctx) -> ImportSessionOut:
    """Append a chunk at `Upload-Offset`; the last one starts staging (docs/archive-format.md)."""
    try:
        offset = int(request.headers["upload-offset"])
    except (KeyError, ValueError) as exc:
        raise ProblemError(400, "missing_offset", "Upload-Offset header required") from exc

    async with _locks[import_id]:

        def load() -> ImportSessionOut:
            with ctx.db.session() as s:
                return _session_out(archive_import.get_import(s, import_id))

        current = await run_in_threadpool(load)
        if current.state != "receiving":
            return current
        if offset != current.offset:
            raise ProblemError(
                409, "offset_mismatch", "Offset does not match", extra={"offset": current.offset}
            )
        # The row is looked up first (404 otherwise) and the path is built from *its* id: a
        # staging directory is never named by something straight out of the URL.
        path = ctx.storage.import_archive_path(current.import_id)
        written = 0
        with path.open("r+b" if path.exists() else "wb") as fh:
            fh.seek(offset)
            fh.truncate()
            try:
                async for chunk in request.stream():
                    if not chunk:
                        continue
                    if (
                        written + len(chunk) > archive_import.MAX_CHUNK_BYTES
                        or offset + written + len(chunk) > current.size
                    ):
                        fh.truncate(offset)
                        raise ProblemError(413, "chunk_too_large", "Chunk too large")
                    await run_in_threadpool(fh.write, chunk)
                    written += len(chunk)
            except ClientDisconnect:
                pass  # keep what arrived: the client resumes from the committed offset
        new_offset = offset + written

        def commit() -> ImportSessionOut:
            with ctx.db.session() as s:
                row = archive_import.get_import(s, import_id)
                row.received_bytes = new_offset
                s.flush()
                return _session_out(row)

        result = await run_in_threadpool(commit)
        if new_offset == current.size:
            await run_in_threadpool(archive_import.finalize, ctx, import_id)
            result = await run_in_threadpool(load)
    return result


@router.get("/imports/{import_id}/report")
def import_report(import_id: str, _: Admin, ctx: Ctx, session: DbSession) -> ImportReportOut:
    """The dry run (§12.2 step 2): per kind, what is new, identical, remapped or conflicting."""
    row = archive_import.get_import(session, import_id)
    if row.state == "failed":
        raise ProblemError(422, row.error or "staging_failed", "This archive was refused")
    return ImportReportOut.model_validate(archive_import.stored_report(ctx, import_id))


@router.post("/imports/{import_id}/apply")
async def apply_import(
    import_id: str, body: ImportPoliciesIn, _: Admin, ctx: Ctx
) -> ImportApplyOut:
    """Write the archive into the library, per-kind and per-item policies applied (§12.2 step 3)."""
    for value in (body.default, *body.per_kind.values(), *body.per_item.values()):
        if value not in archive_domain.POLICIES:
            raise ProblemError(422, "invalid_policy", "Unknown conflict policy", value)
    policies = archive_apply.Policies(
        default=body.default, per_kind=dict(body.per_kind), per_item=dict(body.per_item)
    )
    result = await run_in_threadpool(archive_apply.apply_import, ctx, import_id, policies)
    return ImportApplyOut(**result.as_dict())


@router.delete("/imports/{import_id}", status_code=204)
def delete_import(import_id: str, _: Admin, ctx: Ctx, session: DbSession) -> Response:
    """Forget an import: the staging directory and the archive go with it."""
    archive_import.delete_import(ctx, session, import_id)
    return Response(status_code=204)
