"""Persistent in-process job queue.

Jobs live in the `jobs` table and are executed by worker threads grouped in *lanes* (e.g. `ingest`,
`render`) so heavy work is bounded per lane. Jobs left `running` by a crash are re-queued at start.
A job with a `coalesce_key` replaces any still-queued job with the same key (only the latest runs).
"""

from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update

from the_frame_v2.db.models import Job
from the_frame_v2.db.session import Database
from the_frame_v2.events import Event, EventBroker
from the_frame_v2.ids import utcnow

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class JobContext:
    job_id: str
    payload: dict[str, Any]
    queue: JobQueue

    def progress(self, value: float) -> None:
        self.queue.set_progress(self.job_id, value)


class PermanentJobError(Exception):
    """Raise from a handler to fail the job without retry. `code` is exposed to clients."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


JobHandler = Callable[[JobContext], None]


@dataclass(frozen=True, slots=True)
class HandlerSpec:
    handler: JobHandler
    lane: str
    max_attempts: int = 3


class JobQueue:
    def __init__(self, db: Database, broker: EventBroker, lanes: dict[str, int]) -> None:
        self._db = db
        self._broker = broker
        self._lanes = lanes
        self._handlers: dict[str, HandlerSpec] = {}
        self._claim_lock = threading.Lock()
        self._conditions = {lane: threading.Condition() for lane in lanes}
        self._threads: list[threading.Thread] = []
        self._stopping = threading.Event()

    # ---- registration & lifecycle ----------------------------------------------------------------
    def register(self, kind: str, handler: JobHandler, lane: str, max_attempts: int = 3) -> None:
        if lane not in self._lanes:
            raise ValueError(f"unknown lane {lane}")
        self._handlers[kind] = HandlerSpec(handler, lane, max_attempts)

    def start(self) -> None:
        with self._db.session() as s:
            s.execute(update(Job).where(Job.state == "running").values(state="queued"))
        self._stopping.clear()
        for lane, count in self._lanes.items():
            for i in range(count):
                t = threading.Thread(target=self._run, args=(lane,), name=f"job-{lane}-{i}")
                t.daemon = True
                t.start()
                self._threads.append(t)

    def stop(self, timeout: float = 10.0) -> None:
        self._stopping.set()
        for cond in self._conditions.values():
            with cond:
                cond.notify_all()
        for t in self._threads:
            t.join(timeout)
        self._threads.clear()

    # ---- API ---------------------------------------------------------------------------------
    def enqueue(self, kind: str, payload: dict[str, Any], coalesce_key: str | None = None) -> str:
        spec = self._handlers.get(kind)
        if spec is None:
            raise ValueError(f"no handler for job kind {kind}")
        with self._db.session() as s:
            if coalesce_key:
                s.execute(
                    update(Job)
                    .where(Job.coalesce_key == coalesce_key, Job.state == "queued")
                    .values(state="cancelled", finished_at=utcnow())
                )
            job = Job(kind=kind, lane=spec.lane, payload=payload, coalesce_key=coalesce_key)
            s.add(job)
            s.flush()
            job_id = job.id
        cond = self._conditions[spec.lane]
        with cond:
            cond.notify()
        return job_id

    def set_progress(self, job_id: str, value: float) -> None:
        with self._db.session() as s:
            s.execute(update(Job).where(Job.id == job_id).values(progress=value))
        self._broker.publish(Event("job.progress", {"job_id": job_id, "progress": value}))

    def run_pending_sync(self) -> int:
        """Run all queued jobs in the calling thread (tests, CLI). Returns the number executed."""
        count = 0
        while True:
            claimed = None
            for lane in self._lanes:
                claimed = self._claim(lane)
                if claimed:
                    break
            if not claimed:
                return count
            self._execute(*claimed)
            count += 1

    # ---- internals ---------------------------------------------------------------------------
    def _run(self, lane: str) -> None:
        cond = self._conditions[lane]
        while not self._stopping.is_set():
            claimed = self._claim(lane)
            if claimed is None:
                with cond:
                    cond.wait(timeout=5.0)
                continue
            self._execute(*claimed)

    def _claim(self, lane: str) -> tuple[str, str, dict[str, Any], int] | None:
        with self._claim_lock, self._db.session() as s:
            job = s.scalars(
                select(Job)
                .where(Job.lane == lane, Job.state == "queued")
                .order_by(Job.created_at, Job.id)
                .limit(1)
            ).first()
            if job is None:
                return None
            job.state = "running"
            job.started_at = utcnow()
            job.attempts += 1
            return job.id, job.kind, dict(job.payload), job.attempts

    def _execute(self, job_id: str, kind: str, payload: dict[str, Any], attempts: int) -> None:
        spec = self._handlers.get(kind)
        try:
            if spec is None:
                raise PermanentJobError("unknown_job_kind", kind)
            spec.handler(JobContext(job_id, payload, self))
        except PermanentJobError as exc:
            self._finish(job_id, "failed", f"{exc.code}: {exc}")
        except Exception as exc:
            log.exception("job %s (%s) failed", job_id, kind)
            retry = spec is not None and attempts < spec.max_attempts
            detail = "".join(traceback.format_exception_only(exc)).strip()
            self._finish(job_id, "queued" if retry else "failed", detail)
        else:
            self._finish(job_id, "done", None)

    def _finish(self, job_id: str, state: str, error: str | None) -> None:
        with self._db.session() as s:
            values: dict[str, Any] = {"state": state, "error": error}
            if state != "queued":
                values["finished_at"] = utcnow()
            if state == "done":
                values["progress"] = 1.0
            s.execute(update(Job).where(Job.id == job_id).values(**values))
        if state == "failed":
            self._broker.publish(Event("job.failed", {"job_id": job_id, "error": error}))
