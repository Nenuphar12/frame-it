"""Display targets: pair a TV, tell it which set to show, push it (`docs/tv-display.md`)."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from the_frame_v2.api.deps import Admin, Ctx, DbSession
from the_frame_v2.api.schemas import (
    DisplayCapabilitiesOut,
    DisplayPushIn,
    DisplayPushOut,
    DisplaySourceIn,
    DisplayStatusOut,
    DisplayTargetIn,
    DisplayTargetListOut,
    DisplayTargetOut,
    DisplayTargetUpdateIn,
)
from the_frame_v2.db.models import DisplayTarget, DisplayTargetItem
from the_frame_v2.services import display
from the_frame_v2.tv import SLIDESHOW_MINUTES

router = APIRouter(prefix="/display", tags=["display"])


def _out(session: DbSession, target: DisplayTarget) -> DisplayTargetOut:
    count = session.scalar(
        select(func.count())
        .select_from(DisplayTargetItem)
        .where(DisplayTargetItem.target_id == target.id)
    )
    return DisplayTargetOut(
        id=target.id,
        name=target.name,
        host=target.host,
        model=target.model,
        api_version=target.api_version,
        state=target.state,
        last_error=target.last_error,
        source_label=target.source_label,
        source=target.source,
        slideshow_minutes=target.slideshow_minutes,
        slideshow_ordered=target.slideshow_ordered,
        render_format=target.render_format,
        paired=bool(target.token),
        item_count=int(count or 0),
        created_at=target.created_at,
        last_pushed_at=target.last_pushed_at,
        last_seen_at=target.last_seen_at,
    )


@router.get("/capabilities")
def capabilities(_: Admin) -> DisplayCapabilitiesOut:
    """What a Frame can actually do, so the UI never offers something the TV refuses."""
    return DisplayCapabilitiesOut(
        slideshow_minutes=list(SLIDESHOW_MINUTES),
        max_set=display.MAX_SET,
    )


@router.get("/targets")
def list_targets(_: Admin, session: DbSession) -> DisplayTargetListOut:
    return DisplayTargetListOut(targets=[_out(session, t) for t in display.list_targets(session)])


@router.post("/targets", status_code=201)
def create_target(body: DisplayTargetIn, _: Admin, session: DbSession) -> DisplayTargetOut:
    target = display.create_target(session, name=body.name, host=body.host)
    return _out(session, target)


@router.patch("/targets/{target_id}")
def update_target(
    target_id: str, body: DisplayTargetUpdateIn, _: Admin, session: DbSession
) -> DisplayTargetOut:
    target = display.update_target(
        session,
        target_id,
        name=body.name,
        host=body.host,
        slideshow_minutes=body.slideshow_minutes,
        slideshow_ordered=body.slideshow_ordered,
        render_format=body.render_format,
    )
    return _out(session, target)


@router.delete("/targets/{target_id}", status_code=204)
def delete_target(target_id: str, _: Admin, session: DbSession) -> None:
    display.delete_target(session, target_id)


@router.post("/targets/{target_id}/pair")
async def pair(target_id: str, _: Admin, session: DbSession) -> DisplayTargetOut:
    """Ask the TV for a token. It must be **on** — in art mode it cannot draw its own dialog.

    Pairing blocks until the prompt is accepted, so it runs off the event loop.
    """
    target = await run_in_threadpool(display.pair, session, target_id)
    return _out(session, target)


@router.get("/targets/{target_id}/status")
async def status(target_id: str, _: Admin, ctx: Ctx, session: DbSession) -> DisplayStatusOut:
    result = await run_in_threadpool(display.status, ctx, session, target_id)
    target = display.get_target(session, target_id)
    return DisplayStatusOut(
        target=_out(session, target),
        art_mode=result.info.art_mode,
        my_pictures=result.info.my_pictures,
        store_items=result.info.store_items,
        ours=result.ours,
        foreign=result.foreign,
        slideshow_minutes=result.info.slideshow_minutes,
        slideshow_ordered=result.info.slideshow_ordered,
        current_content_id=result.info.current_content_id,
    )


@router.put("/targets/{target_id}/source")
def set_source(
    target_id: str, body: DisplaySourceIn, _: Admin, session: DbSession
) -> DisplayTargetOut:
    source = body.model_dump(exclude={"label"}, exclude_none=True)
    target = display.set_source(session, target_id, source=source, label=body.label)
    return _out(session, target)


@router.post("/targets/{target_id}/push", status_code=202)
def push(
    target_id: str, body: DisplayPushIn, _: Admin, ctx: Ctx, session: DbSession
) -> DisplayPushOut:
    """Queue a push. Uploading a set takes minutes, so the work happens in the `display` lane."""
    display.get_target(session, target_id)
    job_id = display.enqueue_push(ctx, target_id, allow_delete_foreign=body.allow_delete_foreign)
    return DisplayPushOut(job_id=job_id)
