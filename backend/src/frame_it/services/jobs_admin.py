"""Reading and retrying background jobs (the activity centre, `docs/PLAN.md` §14 phase 11).

The queue itself (`jobs/queue.py`) only knows how to *run* a job. This is the other half: what a
human needs when one did not run — what failed, why, and a way to ask for it again. A retry is a
new row rather than a reset of the old one, so the history of what failed is never rewritten; the
failed row is marked `dismissed`.

Finished rows are history, kept `HISTORY_DAYS` (`prune_job`): every render and every ingest leaves
one, which made a library of a hundred artworks collect two thousand rows in two months.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from frame_it.context import AppContext
from frame_it.db.models import Job
from frame_it.errors import ProblemError
from frame_it.ids import utcnow
from frame_it.jobs.queue import JobContext, JobHandler
from frame_it.services.archive_export import EXPORT_JOB

#: States a client may ask for; `dismissed` is ours (a failure the user has acknowledged).
STATES = ("queued", "running", "done", "failed", "cancelled", "dismissed")
#: A traceback is trimmed before it travels: the code is what a client acts on.
MAX_ERROR_CHARS = 2000

PRUNE_JOB = "jobs.prune"
PRUNE_INTERVAL_SECONDS = 24 * 3600
#: How long a finished job stays. Failures stay until acknowledged: they are `/activity`.
HISTORY_DAYS = 30
_PRUNABLE = ("done", "cancelled", "dismissed")
#: The Export dialog lists past exports from their job rows: a few, and kept.
_KEPT_KINDS = (EXPORT_JOB,)


@dataclass(frozen=True, slots=True)
class JobView:
    id: str
    kind: str
    lane: str
    state: str
    attempts: int
    progress: float
    error: str | None
    code: str | None
    subject_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    retriable: bool


@dataclass(frozen=True, slots=True)
class JobListing:
    jobs: tuple[JobView, ...]
    failed: int


def _subject(payload: dict[str, Any]) -> str | None:
    """The thing the job is about, so the UI can link to it."""
    for key in ("artwork_id", "photo_id", "upload_id", "import_id", "session_id"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return None


def _view(job: Job, *, retriable: bool) -> JobView:
    error = job.error[:MAX_ERROR_CHARS] if job.error else None
    return JobView(
        id=job.id,
        kind=job.kind,
        lane=job.lane,
        state=job.state,
        attempts=job.attempts,
        progress=job.progress,
        error=error,
        code=job.code,
        subject_id=_subject(job.payload),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        retriable=retriable,
    )


def list_jobs(
    ctx: AppContext,
    session: Session,
    *,
    states: tuple[str, ...] = ("failed",),
    limit: int = 50,
) -> JobListing:
    """The most recent jobs in `states`, newest first, plus the number still failed."""
    known = tuple(s for s in states if s in STATES) or ("failed",)
    rows = session.scalars(
        select(Job)
        .where(Job.state.in_(known))
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(max(1, min(limit, 200)))
    ).all()
    failed = session.scalar(select(func.count()).select_from(Job).where(Job.state == "failed")) or 0
    retriable = ctx.jobs.known_kinds()
    return JobListing(
        jobs=tuple(_view(job, retriable=job.kind in retriable) for job in rows),
        failed=int(failed),
    )


def retry_job(ctx: AppContext, session: Session, job_id: str) -> str:
    """Re-enqueue a failed job's work as a new job. Returns the new job id."""
    job = session.get(Job, job_id)
    if job is None:
        raise ProblemError(404, "unknown_job", "Unknown job", f"No job {job_id}.")
    if job.state != "failed":
        raise ProblemError(409, "job_not_failed", "Job is not failed", f"The job is {job.state}.")
    if job.kind not in ctx.jobs.known_kinds():
        raise ProblemError(
            409, "unknown_job_kind", "Unknown job kind", f"No handler for {job.kind}."
        )
    kind, payload, coalesce_key = job.kind, dict(job.payload), job.coalesce_key
    job.state = "dismissed"
    job.finished_at = job.finished_at or utcnow()
    # `enqueue` opens its own session, so this one has to be done with the database first
    # (SQLite has a single writer): commit, then queue, like `_changed` in `api/artworks.py`.
    session.commit()
    return ctx.jobs.enqueue(kind, payload, coalesce_key=coalesce_key)


def dismiss_job(session: Session, job_id: str) -> None:
    """Acknowledge a failure: it leaves the failed count without being run again."""
    job = session.get(Job, job_id)
    if job is None:
        raise ProblemError(404, "unknown_job", "Unknown job", f"No job {job_id}.")
    if job.state != "failed":
        raise ProblemError(409, "job_not_failed", "Job is not failed", f"The job is {job.state}.")
    job.state = "dismissed"
    job.finished_at = job.finished_at or utcnow()


def dismiss_all(session: Session) -> int:
    """Acknowledge every failure at once. Returns how many were dismissed."""
    rows = session.scalars(select(Job).where(Job.state == "failed")).all()
    now = utcnow()
    for job in rows:
        job.state = "dismissed"
        job.finished_at = job.finished_at or now
    return len(rows)


def prune_history(session: Session, *, now: datetime | None = None) -> int:
    """Delete finished jobs older than `HISTORY_DAYS`. Returns how many went."""
    cutoff = (now or utcnow()) - timedelta(days=HISTORY_DAYS)
    result = session.execute(
        delete(Job).where(
            Job.state.in_(_PRUNABLE), Job.created_at < cutoff, Job.kind.not_in(_KEPT_KINDS)
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


def prune_job(ctx: AppContext) -> JobHandler:
    def handler(_: JobContext) -> None:
        with ctx.db.session() as s:
            prune_history(s)

    return handler
