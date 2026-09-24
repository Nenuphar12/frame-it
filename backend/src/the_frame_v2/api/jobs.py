"""Background jobs: what failed, and a way to ask for it again (`docs/PLAN.md` §14 phase 11)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from the_frame_v2.api.deps import Admin, Ctx, DbSession
from the_frame_v2.api.schemas import JobDismissAllOut, JobListOut, JobOut, JobRetryOut
from the_frame_v2.services import jobs_admin

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    _: Admin,
    ctx: Ctx,
    session: DbSession,
    state: Annotated[list[str] | None, Query(description="Repeatable; default `failed`")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> JobListOut:
    listing = jobs_admin.list_jobs(ctx, session, states=tuple(state or ("failed",)), limit=limit)
    return JobListOut(
        jobs=[JobOut.model_validate(job) for job in listing.jobs], failed=listing.failed
    )


@router.post("/{job_id}/retry")
def retry_job(_: Admin, ctx: Ctx, session: DbSession, job_id: str) -> JobRetryOut:
    return JobRetryOut(job_id=jobs_admin.retry_job(ctx, session, job_id))


@router.post("/{job_id}/dismiss", status_code=204)
def dismiss_job(_: Admin, session: DbSession, job_id: str) -> None:
    jobs_admin.dismiss_job(session, job_id)


@router.post("/dismiss-all")
def dismiss_all(_: Admin, session: DbSession) -> JobDismissAllOut:
    return JobDismissAllOut(dismissed=jobs_admin.dismiss_all(session))
