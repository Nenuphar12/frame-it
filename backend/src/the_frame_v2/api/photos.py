from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from the_frame_v2.api.deps import Admin, Ctx, DbSession, Uploader
from the_frame_v2.api.schemas import (
    CountOut,
    LibraryStats,
    PhotoIdsIn,
    PhotoOut,
    PhotoPageOut,
    PhotoTagsIn,
    PhotoUpdateIn,
    TagOut,
)
from the_frame_v2.context import AppContext
from the_frame_v2.db.models import Photo, Tag
from the_frame_v2.errors import not_found
from the_frame_v2.events import Event
from the_frame_v2.services import photos, tags
from the_frame_v2.services.ingest import ensure_derivatives

router = APIRouter(tags=["photos"])
_IMMUTABLE = {"Cache-Control": "private, max-age=31536000, immutable"}


def _photo_out(photo: Photo, tags: list[Tag], drafts: list[str] | None = None) -> PhotoOut:
    out = PhotoOut.model_validate(photo)
    out.tags = [TagOut.model_validate(t) for t in tags]
    out.draft_artwork_ids = list(drafts or [])
    return out


def _one(session: Session, photo: Photo) -> PhotoOut:
    return _photo_out(
        photo,
        photos.tags_for(session, [photo.id]).get(photo.id, []),
        photos.draft_artworks_for(session, [photo.id]).get(photo.id, []),
    )


def _photos_changed(ctx: AppContext, photo_ids: list[str]) -> None:
    """A photo's tags reach the artworks made of it, so every client refreshes both."""
    ctx.broker.publish(Event("photo.updated", {"photo_ids": photo_ids}, audience="all"))


@router.get("/photos")
def list_photos(
    _: Uploader,
    session: DbSession,
    inbox_state: Literal["inbox", "processed", "dismissed"] | None = None,
    q: str | None = Query(default=None, max_length=200),
    tag_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> PhotoPageOut:
    page = photos.list_photos(
        session, photos.PhotoFilter(inbox_state=inbox_state, q=q, tag_id=tag_id), cursor, limit
    )
    return PhotoPageOut(
        items=[
            _photo_out(p, page.tags.get(p.id, []), page.drafts.get(p.id, [])) for p in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.get("/photos/stats")
def library_stats(_: Uploader, session: DbSession) -> LibraryStats:
    return LibraryStats(
        inbox=photos.count_photos(session, photos.PhotoFilter(inbox_state="inbox")),
        photos=photos.count_photos(session, photos.PhotoFilter()),
    )


@router.post("/photos/tags")
def tag_photos(body: PhotoTagsIn, _: Admin, ctx: Ctx, session: DbSession) -> CountOut:
    """Add and remove tags on many photos at once (additive: other tags are left alone).

    `count` = the live photos it applied to. 422 `unknown_tag`, or `tag_conflict` when one tag is
    both added and removed.
    """
    count = tags.tag_photos(session, body.photo_ids, add=body.add, remove=body.remove)
    session.commit()
    _photos_changed(ctx, list(body.photo_ids))
    return CountOut(count=count)


@router.get("/photos/{photo_id}")
def get_photo(photo_id: str, _: Uploader, session: DbSession) -> PhotoOut:
    return _one(session, photos.get_photo(session, photo_id))


@router.patch("/photos/{photo_id}")
def update_photo(
    photo_id: str, body: PhotoUpdateIn, _: Admin, ctx: Ctx, session: DbSession
) -> PhotoOut:
    photo = photos.update_photo(
        session, photo_id, tag_ids=body.tag_ids, inbox_state=body.inbox_state
    )
    session.flush()
    out = _one(session, photo)
    session.commit()
    _photos_changed(ctx, [photo.id])
    return out


async def _derivative(ctx: Ctx, session: DbSession, photo_id: str, kind: str) -> FileResponse:
    photo = photos.get_photo(session, photo_id)
    path = (
        ctx.storage.proxy_path(photo.sha256)
        if kind == "proxy"
        else ctx.storage.thumb_path(photo.sha256, int(kind))
    )
    if not path.exists():
        original = ctx.storage.original_path(photo.sha256, photo.ext)
        if not original.exists():
            raise not_found("Original file")
        await run_in_threadpool(ensure_derivatives, ctx, photo.sha256, original)
    media = "image/jpeg" if kind == "proxy" else "image/webp"
    return FileResponse(path, media_type=media, headers=_IMMUTABLE)


@router.get("/photos/{photo_id}/thumb/{size}", response_class=FileResponse)
async def photo_thumb(
    photo_id: str, size: Literal["256", "768"], _: Uploader, ctx: Ctx, session: DbSession
) -> FileResponse:
    return await _derivative(ctx, session, photo_id, size)


@router.get("/photos/{photo_id}/proxy", response_class=FileResponse)
async def photo_proxy(photo_id: str, _: Uploader, ctx: Ctx, session: DbSession) -> FileResponse:
    return await _derivative(ctx, session, photo_id, "proxy")


@router.get("/photos/{photo_id}/original", response_class=FileResponse)
def photo_original(photo_id: str, _: Admin, ctx: Ctx, session: DbSession) -> FileResponse:
    photo = photos.get_photo(session, photo_id)
    path = ctx.storage.original_path(photo.sha256, photo.ext)
    if not path.exists():
        raise not_found("Original file")
    return FileResponse(
        path, media_type=photo.mime, filename=photo.original_filename, headers=_IMMUTABLE
    )


@router.post("/inbox/dismiss")
def dismiss_from_inbox(body: PhotoIdsIn, _: Admin, ctx: Ctx, session: DbSession) -> CountOut:
    count = photos.set_inbox_state(session, body.photo_ids, "dismissed")
    session.commit()
    _photos_changed(ctx, list(body.photo_ids))
    return CountOut(count=count)


@router.post("/inbox/restore")
def restore_to_inbox(body: PhotoIdsIn, _: Admin, ctx: Ctx, session: DbSession) -> CountOut:
    """Back to the inbox — from anywhere: processed, dismissed (docs/organization.md §6)."""
    count = photos.set_inbox_state(session, body.photo_ids, "inbox")
    session.commit()
    _photos_changed(ctx, list(body.photo_ids))
    return CountOut(count=count)
