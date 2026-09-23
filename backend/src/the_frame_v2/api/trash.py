"""Trash: soft delete with a cascade, restore by item or batch, purge (docs/organization.md §5)."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from the_frame_v2.api.deps import Admin, Ctx, DbSession
from the_frame_v2.api.schemas import (
    AffectedArtworkOut,
    PhotoIdsIn,
    PurgeIn,
    PurgeOut,
    RestoreIn,
    TrashArtworksIn,
    TrashedArtworkOut,
    TrashedPhotoOut,
    TrashOut,
    TrashPhotosIn,
    TrashPreviewOut,
    TrashResultOut,
)
from the_frame_v2.events import Event
from the_frame_v2.services import trash

router = APIRouter(prefix="/trash", tags=["trash"])


@router.get("")
def list_trash(_: Admin, ctx: Ctx, session: DbSession) -> TrashOut:
    page = trash.list_trash(session)
    return TrashOut(
        photos=[TrashedPhotoOut.model_validate(p) for p in page.photos],
        artworks=[TrashedArtworkOut.model_validate(a) for a in page.artworks],
        photo_total=page.photo_total,
        artwork_total=page.artwork_total,
        retention_days=ctx.settings.trash_retention_days,
    )


@router.post("/preview")
def preview(body: PhotoIdsIn, _: Admin, session: DbSession) -> TrashPreviewOut:
    """Which artworks use these photos — the cascade dialog asks before anything is written."""
    return TrashPreviewOut(
        artworks=[
            AffectedArtworkOut(
                artwork_id=a.artwork_id,
                title=a.title,
                slot_count=a.slot_count,
                photo_count=a.photo_count,
            )
            for a in trash.preview_photo_trash(session, body.photo_ids)
        ]
    )


@router.post("/photos")
def trash_photos(body: TrashPhotosIn, _: Admin, ctx: Ctx, session: DbSession) -> TrashResultOut:
    """Soft-delete photos. `cascade` decides what happens to the artworks using them."""
    result = trash.trash_photos(session, body.photo_ids, cascade=body.cascade)
    session.commit()
    ctx.broker.publish(Event("photo.updated", {"photo_ids": list(body.photo_ids)}, audience="all"))
    ctx.broker.publish(Event("trash.changed", {"batch_id": result.batch_id}, audience="all"))
    return TrashResultOut(
        batch_id=result.batch_id,
        photos=result.photos,
        artworks=result.artworks,
        emptied=result.emptied,
    )


@router.post("/artworks")
def trash_artworks(body: TrashArtworksIn, _: Admin, ctx: Ctx, session: DbSession) -> TrashResultOut:
    result = trash.trash_artworks(session, body.artwork_ids)
    session.commit()
    ctx.broker.publish(Event("trash.changed", {"batch_id": result.batch_id}, audience="all"))
    return TrashResultOut(
        batch_id=result.batch_id,
        photos=result.photos,
        artworks=result.artworks,
        emptied=result.emptied,
    )


@router.post("/restore")
def restore(body: RestoreIn, _: Admin, ctx: Ctx, session: DbSession) -> TrashResultOut:
    """Bring items back; a `batch_id` restores everything deleted by the same gesture."""
    result = trash.restore(
        session,
        photo_ids=body.photo_ids,
        artwork_ids=body.artwork_ids,
        batch_ids=body.batch_ids,
    )
    session.commit()
    ctx.broker.publish(Event("trash.changed", {"batch_id": result.batch_id}, audience="all"))
    ctx.broker.publish(Event("photo.updated", {"photo_ids": list(body.photo_ids)}, audience="all"))
    return TrashResultOut(
        batch_id=result.batch_id,
        photos=result.photos,
        artworks=result.artworks,
        emptied=result.emptied,
    )


@router.post("/purge")
async def purge(body: PurgeIn, _: Admin, ctx: Ctx) -> PurgeOut:
    """Delete for good, files included. `all` empties the trash; otherwise only what expired."""
    result = await run_in_threadpool(trash.purge, ctx, all_items=body.all)
    return PurgeOut(photos=result.photos, artworks=result.artworks, bytes_freed=result.bytes_freed)
