"""Display targets: find and pair a TV, choose its set, push it (`docs/tv-display.md`)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from the_frame_v2.api.deps import Admin, Ctx, DbSession
from the_frame_v2.api.schemas import (
    DiscoveredTvOut,
    DisplayCapabilitiesOut,
    DisplayDiscoverOut,
    DisplayPlanIn,
    DisplayPlanOut,
    DisplayProgressOut,
    DisplayPushIn,
    DisplayPushOut,
    DisplayPushResultOut,
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
    items = DisplayTargetItem.target_id == target.id
    count = session.scalar(select(func.count()).select_from(DisplayTargetItem).where(items))
    in_set = session.scalar(
        select(func.count())
        .select_from(DisplayTargetItem)
        .where(items, DisplayTargetItem.position.is_not(None))
    )
    return DisplayTargetOut(
        id=target.id,
        name=target.name,
        host=target.host,
        mac=target.mac,
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
        set_count=int(in_set or 0),
        ours_count=target.ours_count,
        foreign_count=target.foreign_count,
        checked_at=target.checked_at,
        last_result=_result(target.last_result),
        progress=DisplayProgressOut.model_validate(target.progress) if target.progress else None,
        created_at=target.created_at,
        last_pushed_at=target.last_pushed_at,
        last_seen_at=target.last_seen_at,
    )


def _result(raw: dict[str, Any] | None) -> DisplayPushResultOut | None:
    """A stored result, or None — one written by an older version is simply not shown."""
    if not raw:
        return None
    try:
        return DisplayPushResultOut.model_validate(raw)
    except ValueError:
        return None


@router.get("/capabilities")
def capabilities(_: Admin) -> DisplayCapabilitiesOut:
    """What a Frame can actually do, so the UI never offers something the TV refuses."""
    return DisplayCapabilitiesOut(
        slideshow_minutes=list(SLIDESHOW_MINUTES),
        max_set=display.MAX_SET,
    )


@router.get("/discover")
async def discover(_: Admin, ctx: Ctx, session: DbSession) -> DisplayDiscoverOut:
    """Samsung TVs on the LAN (SSDP + a sweep of the /24), Frames first. Read-only, a few seconds.

    The first Frame that is not added yet is `recommended`: what the Add-TV dialog pre-selects.
    """
    subnet, found = await run_in_threadpool(display.discover, ctx, session)
    recommended = next(
        (f.tv.host for f in found if f.tv.frame_support and f.target_id is None), None
    )
    return DisplayDiscoverOut(
        subnet=subnet,
        tvs=[
            DiscoveredTvOut(
                host=f.tv.host,
                name=f.tv.name,
                model=f.tv.model,
                model_code=f.tv.model_code,
                frame_support=f.tv.frame_support,
                token_auth=f.tv.token_auth,
                mac=f.tv.mac,
                target_id=f.target_id,
                recommended=f.tv.host == recommended,
            )
            for f in found
        ],
    )


@router.get("/targets")
def list_targets(_: Admin, session: DbSession) -> DisplayTargetListOut:
    return DisplayTargetListOut(targets=[_out(session, t) for t in display.list_targets(session)])


@router.post("/targets", status_code=201)
def create_target(body: DisplayTargetIn, _: Admin, session: DbSession) -> DisplayTargetOut:
    target = display.create_target(
        session, name=body.name, host=body.host, mac=body.mac, model=body.model
    )
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
async def pair(target_id: str, _: Admin, ctx: Ctx, session: DbSession) -> DisplayTargetOut:
    """Ask the TV for a token. It must be **on** — in art mode it cannot draw its own dialog.

    Pairing blocks until the prompt is accepted, so it runs off the event loop.
    """
    target = await run_in_threadpool(display.pair, ctx, session, target_id)
    return _out(session, target)


@router.get("/targets/{target_id}/status")
async def status(target_id: str, _: Admin, ctx: Ctx, session: DbSession) -> DisplayStatusOut:
    """Ask the TV now. Refreshes the cached counts — and follows the TV by MAC if it moved."""
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
        moved_from=result.moved.old_host if result.moved else None,
    )


@router.put("/targets/{target_id}/source")
def set_source(
    target_id: str, body: DisplaySourceIn, _: Admin, session: DbSession
) -> DisplayTargetOut:
    source = body.model_dump(exclude={"label"}, exclude_none=True)
    target = display.set_source(session, target_id, source=source, label=body.label)
    return _out(session, target)


@router.post("/targets/{target_id}/plan")
async def plan(
    target_id: str, body: DisplayPlanIn, _: Admin, ctx: Ctx, session: DbSession
) -> DisplayPlanOut:
    """Dry-run a push: how many images go up, stay, leave — and whose. Nothing changes on the TV.

    The TV is asked what it holds (`check_tv`); when it does not answer, the numbers come from the
    app's own map and `tv_error` says why.
    """
    source = body.source.model_dump(exclude={"label"}, exclude_none=True) if body.source else None
    summary = await run_in_threadpool(
        lambda: display.plan(
            ctx,
            session,
            target_id,
            source=source,
            slideshow_minutes=body.slideshow_minutes,
            check_tv=body.check_tv,
        )
    )
    return DisplayPlanOut(
        mode="static" if summary.static else "slideshow",
        set_count=summary.set_count,
        to_upload=summary.to_upload,
        already_there=summary.already_there,
        ours_to_remove=summary.ours_to_remove,
        ours_left=summary.ours_left,
        foreign=summary.foreign,
        foreign_checked_at=summary.foreign_checked_at,
        tv_error=summary.tv_error,
        drafts=summary.drafts,
        drafts_left_out=summary.drafts_left_out,
        moved_from=summary.moved.old_host if summary.moved else None,
        moved_to=summary.moved.new_host if summary.moved else None,
    )


@router.post("/targets/{target_id}/push", status_code=202)
def push(
    target_id: str, body: DisplayPushIn, _: Admin, ctx: Ctx, session: DbSession
) -> DisplayPushOut:
    """Queue a push. Uploading a set takes minutes, so the work happens in the `display` lane.

    `slideshow_minutes` / `slideshow_ordered` are saved on the target first, so "Show on the TV"
    sets how the TV rotates and what it shows in one request.
    """
    display.update_target(
        session,
        target_id,
        slideshow_minutes=body.slideshow_minutes,
        slideshow_ordered=body.slideshow_ordered,
    )
    session.commit()  # the job reads the target from its own session
    job_id = display.enqueue_push(ctx, target_id, allow_delete_foreign=body.allow_delete_foreign)
    return DisplayPushOut(job_id=job_id)
