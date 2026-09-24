"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from the_frame_v2 import __version__
from the_frame_v2.api import (
    archive,
    artworks,
    auth,
    colors,
    devices,
    events,
    library,
    localsend,
    photos,
    rendering,
    system,
    trash,
    uploads,
)
from the_frame_v2.api import jobs as jobs_router
from the_frame_v2.api import templates as templates_router
from the_frame_v2.auth.middleware import GuardMiddleware
from the_frame_v2.auth.ratelimit import RateLimiter
from the_frame_v2.config import Settings
from the_frame_v2.context import AppContext
from the_frame_v2.db.migrate import upgrade_to_head
from the_frame_v2.db.session import Database
from the_frame_v2.errors import install_error_handlers, problem_response
from the_frame_v2.events import EventBroker
from the_frame_v2.imaging import capabilities
from the_frame_v2.jobs.gate import RenderGate
from the_frame_v2.jobs.queue import JobQueue
from the_frame_v2.localsend.runner import LocalSendRunner
from the_frame_v2.services import (
    archive_export,
    archive_import,
    ingest,
    photo_copies,
    render,
    search,
    templates,
)
from the_frame_v2.services import devices as devices_service
from the_frame_v2.services import trash as trash_service
from the_frame_v2.services import uploads as uploads_service
from the_frame_v2.services.geocode import Geocoder
from the_frame_v2.services.localsend import LocalSendHub
from the_frame_v2.storage import Storage

log = logging.getLogger("the_frame_v2")
STATIC_DIR = Path(__file__).parent / "static"
API_PREFIX = "/api/v1"


def build_context(settings: Settings) -> AppContext:
    storage = Storage(settings)
    storage.ensure_dirs()
    db = Database(settings.db_path)
    upgrade_to_head(db.engine)
    broker = EventBroker()
    jobs = JobQueue(
        db, broker, lanes={"ingest": settings.ingest_workers, "render": settings.render_workers}
    )
    ctx = AppContext(
        settings=settings,
        storage=storage,
        db=db,
        broker=broker,
        jobs=jobs,
        geocoder=Geocoder(),
        auth_limiter=RateLimiter([(5, 60.0), (20, 3600.0)]),
        localsend=LocalSendHub(),
        render_gate=RenderGate(settings.render_workers),
    )
    jobs.register("ingest", ingest.ingest_job(ctx), lane="ingest")
    jobs.register(photo_copies.BACKFILL_JOB, photo_copies.backfill_job(ctx), lane="ingest")
    jobs.register(render.RENDER_JOB, render.render_job(ctx), lane="render", max_attempts=2)
    jobs.register(trash_service.PURGE_JOB, trash_service.purge_job(ctx), lane="ingest")
    jobs.schedule_every(trash_service.PURGE_JOB, trash_service.PURGE_INTERVAL_SECONDS, {})
    jobs.register(archive_export.EXPORT_JOB, archive_export.export_job(ctx), lane="ingest")
    jobs.register(archive_import.STAGE_JOB, archive_import.stage_job(ctx), lane="ingest")
    jobs.register(archive_export.SWEEP_JOB, archive_export.sweep_job(ctx), lane="ingest")
    jobs.schedule_every(archive_export.SWEEP_JOB, archive_export.SWEEP_INTERVAL_SECONDS, {})
    with db.session() as s:
        templates.seed_builtins(s)
        if search.is_empty(s):
            # The FTS index is disposable (docs/data-model.md): rebuild it when it is missing.
            count = search.reindex_all(s)
            if count:
                log.info("search index rebuilt (%d entries)", count)
    return ctx


def announce_setup_code(ctx: AppContext) -> str | None:
    """Print a setup code when no admin device exists (needed for non-localhost admin access)."""
    with ctx.db.session() as s:
        if devices_service.has_admin_device(s):
            return None
        issued = devices_service.issue_setup_code(s)
    log.warning(
        "No admin device registered. Setup code (valid %d min): %s  — or open the UI from this "
        "machine (localhost is trusted).",
        issued.expires_in_seconds // 60,
        issued.code,
    )
    return issued.code


def announce_urls(settings: Settings) -> None:
    """Log the URLs to open: uvicorn only prints the bind address (e.g. 0.0.0.0)."""
    local = f"{settings.scheme}://localhost:{settings.port}"
    if settings.host in {"127.0.0.1", "localhost", "::1"}:
        log.info("Open %s (bound to loopback: phones cannot connect)", local)
        return
    log.info("Open %s on this computer; phones use %s", local, settings.effective_public_url)


def create_app(settings: Settings, *, start_workers: bool = True) -> FastAPI:
    missing = capabilities.detect().missing_required
    if missing:
        raise RuntimeError(f"libvips lacks required capabilities: {', '.join(missing)}")
    ctx = build_context(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        ctx.broker.bind_loop(asyncio.get_running_loop())
        uploads_service.purge_expired(ctx)
        if start_workers:
            ctx.jobs.start()
        if photo_copies.needs_backfill(ctx):
            ctx.jobs.enqueue(photo_copies.BACKFILL_JOB, {}, coalesce_key=photo_copies.BACKFILL_JOB)
        announce_urls(settings)
        announce_setup_code(ctx)
        if start_workers and settings.localsend_enabled:
            ctx.localsend_runner = LocalSendRunner(ctx)
            await ctx.localsend_runner.start()
        try:
            yield
        finally:
            if ctx.localsend_runner is not None:
                await ctx.localsend_runner.stop()
            ctx.jobs.stop()
            ctx.db.dispose()

    app = FastAPI(
        title="the_frame_v2",
        version=__version__,
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    app.state.ctx = ctx
    install_error_handlers(app)

    api = APIRouter(prefix=API_PREFIX)
    for module in (
        system,
        auth,
        devices,
        localsend,
        uploads,
        photos,
        library,
        artworks,
        trash,
        archive,
        jobs_router,
        templates_router,
        rendering,
        colors,
        events,
    ):
        api.include_router(module.router)
    app.include_router(api)

    @app.api_route(
        f"{API_PREFIX}/{{path:path}}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    def api_not_found(path: str) -> Response:
        return problem_response(404, "not_found", "Not found", f"No API route {path}")

    _mount_spa(app)
    app.add_middleware(GuardMiddleware, settings=settings)
    return app


def _mount_spa(app: FastAPI) -> None:
    index = STATIC_DIR / "index.html"
    if not index.is_file():

        @app.get("/", include_in_schema=False)
        def no_frontend() -> Response:
            return Response(
                "Frontend not built. Run `make build` (or use the Vite dev server on :5173).",
                media_type="text/plain",
            )

        return
    assets = STATIC_DIR / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        candidate = (STATIC_DIR / path).resolve()
        if path and candidate.is_file() and STATIC_DIR.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
