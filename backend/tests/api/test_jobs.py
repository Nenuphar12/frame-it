"""The activity centre: listing failed jobs, retrying them, dismissing them (phase 11)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from frame_it.db.models import Job
from frame_it.ids import utcnow
from frame_it.jobs.queue import JobContext, PermanentJobError
from frame_it.services import jobs_admin
from frame_it.services.archive_export import EXPORT_JOB
from tests.conftest import ctx_of, pair

FAILING = "test_failing"
PERMANENT = "test_permanent"


def arm(client: TestClient, *, fail_times: int = 99) -> dict[str, int]:
    """Register two handlers on the live queue: one that retries, one that never does."""
    calls = {"count": 0}
    ctx = ctx_of(client)

    def failing(_: JobContext) -> None:
        calls["count"] += 1
        if calls["count"] <= fail_times:
            raise RuntimeError("boom")

    def permanent(_: JobContext) -> None:
        raise PermanentJobError("render_failed", "no pixels")

    ctx.jobs.register(FAILING, failing, lane="ingest", max_attempts=1)
    ctx.jobs.register(PERMANENT, permanent, lane="ingest", max_attempts=1)
    return calls


def run(client: TestClient, kind: str, payload: dict[str, Any] | None = None) -> str:
    ctx = ctx_of(client)
    job_id = ctx.jobs.enqueue(kind, payload or {})
    ctx.jobs.run_pending_sync()
    return job_id


def test_failed_jobs_are_listed_with_their_code(local: TestClient) -> None:
    arm(local)
    job_id = run(local, PERMANENT, {"artwork_id": "art-1"})

    body = local.get("/api/v1/jobs").json()
    assert body["failed"] == 1
    (job,) = body["jobs"]
    assert job["id"] == job_id
    assert job["kind"] == PERMANENT
    assert job["state"] == "failed"
    # `PermanentJobError` formats `code: message`; the client translates the code.
    assert job["code"] == "render_failed"
    assert "no pixels" in job["error"]
    assert job["subject_id"] == "art-1"
    assert job["retriable"] is True


def test_a_traceback_has_no_code(local: TestClient) -> None:
    arm(local)
    run(local, FAILING)
    (job,) = local.get("/api/v1/jobs").json()["jobs"]
    assert job["code"] is None
    assert "boom" in job["error"]


def test_retry_runs_the_work_again_and_keeps_the_history(local: TestClient) -> None:
    calls = arm(local, fail_times=1)
    job_id = run(local, FAILING)
    assert calls["count"] == 1

    res = local.post(f"/api/v1/jobs/{job_id}/retry")
    assert res.status_code == 200, res.text
    new_id = res.json()["job_id"]
    assert new_id != job_id
    ctx_of(local).jobs.run_pending_sync()
    assert calls["count"] == 2

    # The failure is gone from the count, and the old row is still there under `dismissed`.
    assert local.get("/api/v1/jobs").json()["failed"] == 0
    states = {
        job["id"]: job["state"]
        for job in local.get(
            "/api/v1/jobs", params={"state": ["dismissed", "done"], "limit": 10}
        ).json()["jobs"]
    }
    assert states[job_id] == "dismissed"
    assert states[new_id] == "done"


def test_retrying_a_job_that_did_not_fail_is_a_conflict(local: TestClient) -> None:
    arm(local, fail_times=0)
    job_id = run(local, FAILING)
    res = local.post(f"/api/v1/jobs/{job_id}/retry")
    assert res.status_code == 409
    assert res.json()["code"] == "job_not_failed"


def test_retrying_an_unknown_job_is_404(local: TestClient) -> None:
    res = local.post("/api/v1/jobs/nope/retry")
    assert res.status_code == 404
    assert res.json()["code"] == "unknown_job"


def test_dismiss_and_dismiss_all(local: TestClient) -> None:
    arm(local)
    first = run(local, PERMANENT)
    run(local, PERMANENT)
    assert local.get("/api/v1/jobs").json()["failed"] == 2

    assert local.post(f"/api/v1/jobs/{first}/dismiss").status_code == 204
    assert local.get("/api/v1/jobs").json()["failed"] == 1
    assert local.post("/api/v1/jobs/dismiss-all").json()["dismissed"] == 1
    assert local.get("/api/v1/jobs").json() == {"jobs": [], "failed": 0}


def test_a_job_whose_handler_is_gone_is_not_retriable(local: TestClient) -> None:
    arm(local)
    job_id = run(local, PERMANENT)
    ctx_of(local).jobs._handlers.pop(PERMANENT)  # as after an upgrade that dropped the kind

    (job,) = local.get("/api/v1/jobs").json()["jobs"]
    assert job["retriable"] is False
    res = local.post(f"/api/v1/jobs/{job_id}/retry")
    assert res.status_code == 409
    assert res.json()["code"] == "unknown_job_kind"


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", ""), ("post", "/x/retry"), ("post", "/x/dismiss"), ("post", "/dismiss-all")],
)
def test_jobs_are_admin_only(local: TestClient, method: str, path: str) -> None:
    uploader = pair(local, "uploader")
    res = getattr(uploader, method)(f"/api/v1/jobs{path}")
    assert res.status_code == 403


def test_finished_jobs_are_pruned_after_the_history_window(local: TestClient) -> None:
    ctx = ctx_of(local)
    old = utcnow() - timedelta(days=jobs_admin.HISTORY_DAYS + 1)
    rows = {
        "old_done": Job(kind="render", lane="render", state="done", created_at=old),
        "old_cancelled": Job(kind="render", lane="render", state="cancelled", created_at=old),
        "old_dismissed": Job(kind="ingest", lane="ingest", state="dismissed", created_at=old),
        # Kept: an unacknowledged failure is `/activity`; past exports are the Export dialog's list.
        "old_failed": Job(kind="ingest", lane="ingest", state="failed", created_at=old),
        "old_export": Job(kind=EXPORT_JOB, lane="ingest", state="done", created_at=old),
        "recent_done": Job(kind="render", lane="render", state="done"),
    }
    with ctx.db.session() as s:
        s.add_all(rows.values())
        s.flush()
        ids = {name: job.id for name, job in rows.items()}

    with ctx.db.session() as s:
        assert jobs_admin.prune_history(s) == 3
    with ctx.db.session() as s:
        left = {name for name, job_id in ids.items() if s.get(Job, job_id) is not None}
    assert left == {"old_failed", "old_export", "recent_done"}
