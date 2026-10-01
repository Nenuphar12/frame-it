"""Artworks: create from photos, documents with optimistic concurrency, snapshots, renders."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from the_frame_v2.api.deps import Admin, Ctx, DbSession, Uploader
from the_frame_v2.api.schemas import (
    ApplyTemplateIn,
    ArtworkCreateIn,
    ArtworkOut,
    ArtworkPageOut,
    ArtworkQueryIn,
    ArtworkSort,
    ArtworkStatus,
    ArtworkSummaryOut,
    ArtworkTagsIn,
    ArtworkUpdateIn,
    CountOut,
    SnapshotIn,
    SnapshotOut,
    TagOut,
)
from the_frame_v2.context import AppContext
from the_frame_v2.db.models import Artwork
from the_frame_v2.domain.document import ArtworkDocument
from the_frame_v2.errors import ProblemError
from the_frame_v2.events import Event
from the_frame_v2.imaging.render import RenderError
from the_frame_v2.services import artworks, collections, library, render, tags

router = APIRouter(prefix="/artworks", tags=["artworks"])
_IMMUTABLE = {"Cache-Control": "private, max-age=31536000, immutable"}
_REVALIDATE = {"Cache-Control": "private, no-cache"}


def _summary(session: Session, artwork: Artwork) -> ArtworkSummaryOut:
    out = ArtworkSummaryOut.model_validate(artwork)
    out.tags = [
        TagOut.model_validate(t) for t in artworks.tags_for(session, [artwork.id])[artwork.id]
    ]
    out.inherited_tags = [
        TagOut.model_validate(t)
        for t in artworks.inherited_tags_for(session, [artwork.id])[artwork.id]
    ]
    return out


def _full(session: Session, artwork: Artwork) -> ArtworkOut:
    return ArtworkOut.model_validate(
        {
            **_summary(session, artwork).model_dump(),
            "document": artworks.document_of(artwork),
            "collection_ids": collections.collections_of(session, artwork.id),
            "smart_collection_ids": library.smart_collections_of(session, artwork.id),
        }
    )


def _changed(ctx: AppContext, session: Session, artwork_id: str, *, rerender: bool) -> None:
    """Commit, notify clients, and queue a render of the new document."""
    session.commit()
    ctx.broker.publish(
        Event("entity.changed", {"entity": "artwork", "id": artwork_id}, audience="all")
    )
    if rerender:
        render.enqueue_render(ctx, artwork_id)


def _photos_left_inbox(ctx: AppContext, session: Session, artwork: Artwork) -> None:
    """Marking ready moves the photos out of the inbox: the inbox and the photo grids refresh."""
    photo_ids = artworks.document_of(artwork).photo_ids()
    if photo_ids:
        ctx.broker.publish(Event("photo.updated", {"photo_ids": photo_ids}, audience="all"))


def _etag(artwork: Artwork) -> dict[str, str]:
    return {"ETag": f'"{artwork.document_version}"'}


def _expected_version(if_match: str | None) -> int:
    if if_match is None:
        raise ProblemError(
            428, "precondition_required", "If-Match header required", "Send the document_version"
        )
    try:
        return int(if_match.strip().removeprefix("W/").strip('"'))
    except ValueError as exc:
        raise ProblemError(400, "invalid_if_match", "Invalid If-Match header") from exc


def _page_out(page: library.ArtworkPage) -> ArtworkPageOut:
    items = []
    for artwork in page.items:
        out = ArtworkSummaryOut.model_validate(artwork)
        out.tags = [TagOut.model_validate(t) for t in page.tags[artwork.id]]
        out.inherited_tags = [TagOut.model_validate(t) for t in page.inherited.get(artwork.id, [])]
        items.append(out)
    return ArtworkPageOut(items=items, next_cursor=page.next_cursor)


@router.get("")
def list_artworks(
    _: Uploader,
    session: DbSession,
    status: ArtworkStatus | None = None,
    favorite: bool | None = None,
    photo_id: str | None = None,
    collection_id: str | None = None,
    include_nested: bool = False,
    q: str | None = Query(default=None, max_length=200),
    sort: ArtworkSort = "created_desc",
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> ArtworkPageOut:
    """The simple cases as query parameters; a full filter AST goes to `POST /artworks/query`."""
    query = library.ArtworkQuery(
        status=status,
        favorite=favorite,
        photo_id=photo_id,
        collection_id=collection_id,
        include_nested=include_nested,
        q=q,
        sort=sort,
    )
    return _page_out(library.list_artworks(session, query, cursor, limit))


@router.post("/query")
def query_artworks(body: ArtworkQueryIn, _: Uploader, session: DbSession) -> ArtworkPageOut:
    """The filter bar and smart collections: one AST (docs/data-model.md §5.2), one page back."""
    query = library.ArtworkQuery(
        filter=library.parse_query_filter(body.filter),
        collection_id=body.collection_id,
        include_nested=body.include_nested,
        status=body.status,
        favorite=body.favorite,
        photo_id=body.photo_id,
        q=body.q,
        sort=body.sort,
    )
    return _page_out(library.list_artworks(session, query, body.cursor, body.limit))


@router.post("", status_code=201)
def create_artwork(body: ArtworkCreateIn, _: Admin, ctx: Ctx, session: DbSession) -> ArtworkOut:
    artwork = artworks.create_artwork(
        session,
        body.photo_ids,
        style_id=body.style_id,
        layout_id=body.layout_id,
        title=body.title,
        composition=(body.composition.model_dump(exclude_none=True) if body.composition else None),
    )
    _changed(ctx, session, artwork.id, rerender=True)
    ctx.broker.publish(Event("photo.updated", {"photo_ids": body.photo_ids}, audience="all"))
    return _full(session, artwork)


@router.get("/{artwork_id}")
def get_artwork(artwork_id: str, _: Uploader, session: DbSession, response: Response) -> ArtworkOut:
    artwork = artworks.get_artwork(session, artwork_id)
    response.headers.update(_etag(artwork))
    return _full(session, artwork)


@router.put("/{artwork_id}/document")
def put_document(
    artwork_id: str,
    body: ArtworkDocument,
    _: Admin,
    ctx: Ctx,
    session: DbSession,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> ArtworkOut:
    """Replace the document. `If-Match: <document_version>` is required (409 when outdated)."""
    expected = _expected_version(if_match)
    artwork = artworks.save_document(session, artwork_id, body.canonical(), expected)
    _changed(ctx, session, artwork.id, rerender=True)
    response.headers.update(_etag(artwork))
    return _full(session, artwork)


@router.post("/tags")
def tag_artworks(body: ArtworkTagsIn, _: Admin, ctx: Ctx, session: DbSession) -> CountOut:
    """Add and remove **own** tags on many artworks (additive: other tags are left alone).

    An inherited tag belongs to a photo: `remove` cannot take it off an artwork. `count` = the
    live artworks it applied to.
    """
    count = tags.tag_artworks(session, body.artwork_ids, add=body.add, remove=body.remove)
    # One event for the batch: a client refetches the lists once, not once per artwork.
    _changed(ctx, session, body.artwork_ids[0], rerender=False)
    return CountOut(count=count)


@router.patch("/{artwork_id}")
def update_artwork(
    artwork_id: str, body: ArtworkUpdateIn, _: Admin, ctx: Ctx, session: DbSession
) -> ArtworkOut:
    artwork = artworks.update_artwork(
        session,
        artwork_id,
        title=body.title,
        favorite=body.favorite,
        status=body.status,
        tag_ids=body.tag_ids,
        origin_style_id=body.origin_style_id,
        origin_layout_id=body.origin_layout_id,
    )
    _changed(ctx, session, artwork.id, rerender=False)
    if body.status == "ready":
        _photos_left_inbox(ctx, session, artwork)
    return _full(session, artwork)


@router.post("/{artwork_id}/apply-template")
def apply_template(
    artwork_id: str,
    body: ApplyTemplateIn,
    _: Admin,
    ctx: Ctx,
    session: DbSession,
    response: Response,
) -> ArtworkOut:
    """Re-dress and/or re-lay out an artwork from a saved template (docs/templates.md §5).

    Copy on apply: the template is read once and the artwork records it as its origin. A
    `pre_template_update` snapshot is taken first, so the change is undoable from the history.
    """
    artwork = artworks.apply_template(
        session, artwork_id, style_id=body.style_id, layout_id=body.layout_id
    )
    _changed(ctx, session, artwork.id, rerender=True)
    response.headers.update(_etag(artwork))
    return _full(session, artwork)


@router.post("/{artwork_id}/validate")
def validate_artwork(artwork_id: str, _: Admin, ctx: Ctx, session: DbSession) -> ArtworkOut:
    """Mark as ready — done: its photos leave the inbox (docs/organization.md §6).

    422 `artwork_incomplete` / `invalid_document` otherwise.
    """
    artwork = artworks.mark_ready(session, artwork_id)
    _changed(ctx, session, artwork.id, rerender=False)
    _photos_left_inbox(ctx, session, artwork)
    return _full(session, artwork)


@router.post("/{artwork_id}/duplicate", status_code=201)
def duplicate_artwork(artwork_id: str, _: Admin, ctx: Ctx, session: DbSession) -> ArtworkOut:
    artwork = artworks.duplicate_artwork(session, artwork_id)
    _changed(ctx, session, artwork.id, rerender=True)
    return _full(session, artwork)


@router.delete("/{artwork_id}", status_code=204)
def trash_artwork(artwork_id: str, _: Admin, ctx: Ctx, session: DbSession) -> None:
    """Move to trash (restore and purge: `/trash`, docs/organization.md §5)."""
    artworks.trash_artwork(session, artwork_id)
    _changed(ctx, session, artwork_id, rerender=False)


# ---- snapshots ----------------------------------------------------------------------------------
@router.get("/{artwork_id}/snapshots")
def list_snapshots(artwork_id: str, _: Admin, session: DbSession) -> list[SnapshotOut]:
    return [SnapshotOut.model_validate(s) for s in artworks.list_snapshots(session, artwork_id)]


@router.post("/{artwork_id}/snapshots", status_code=201)
def create_snapshot(artwork_id: str, body: SnapshotIn, _: Admin, session: DbSession) -> SnapshotOut:
    return SnapshotOut.model_validate(artworks.create_snapshot(session, artwork_id, body.reason))


@router.post("/{artwork_id}/snapshots/{snapshot_id}/restore")
def restore_snapshot(
    artwork_id: str, snapshot_id: str, _: Admin, ctx: Ctx, session: DbSession, response: Response
) -> ArtworkOut:
    artwork = artworks.restore_snapshot(session, artwork_id, snapshot_id)
    _changed(ctx, session, artwork.id, rerender=True)
    response.headers.update(_etag(artwork))
    return _full(session, artwork)


# ---- renders ------------------------------------------------------------------------------------
async def _render_file(
    ctx: AppContext,
    artwork_id: str,
    kind: render.Derivative,
    media_type: str,
    v: str | None,
    *,
    trashed_ok: bool = False,
) -> FileResponse:
    try:
        path, render_hash = await run_in_threadpool(
            render.derivative, ctx, artwork_id, kind, trashed_ok=trashed_ok
        )
    except RenderError as exc:
        raise ProblemError(422, exc.code, "Cannot render the artwork", str(exc)) from exc
    headers = {**(_IMMUTABLE if v == render_hash else _REVALIDATE), "X-Render-Hash": render_hash}
    filename = None
    if kind in ("png", "jpg"):
        filename = f"artwork-{artwork_id}.{kind}"
    return FileResponse(path, media_type=media_type, headers=headers, filename=filename)


RenderVersion = Annotated[
    str | None, Query(description="Render hash: the response is cached forever when it matches")
]


@router.get("/{artwork_id}/render.png", response_class=FileResponse)
async def render_png(
    artwork_id: str, _: Uploader, ctx: Ctx, v: RenderVersion = None
) -> FileResponse:
    """Lossless 3840×2160 master (rendered on demand when missing)."""
    return await _render_file(ctx, artwork_id, "png", "image/png", v)


@router.get("/{artwork_id}/render.jpg", response_class=FileResponse)
async def render_jpg(
    artwork_id: str, _: Uploader, ctx: Ctx, v: RenderVersion = None
) -> FileResponse:
    return await _render_file(ctx, artwork_id, "jpg", "image/jpeg", v)


@router.get("/{artwork_id}/thumb/{size}", response_class=FileResponse)
async def render_thumb(
    artwork_id: str,
    size: Literal["256", "768"],
    _: Uploader,
    ctx: Ctx,
    v: RenderVersion = None,
) -> FileResponse:
    kind: render.Derivative = "thumb-256" if size == "256" else "thumb-768"
    # Thumbnails only — a trashed artwork is shown in the trash until it is purged, but its
    # renders are no longer downloadable.
    return await _render_file(ctx, artwork_id, kind, "image/webp", v, trashed_ok=True)
