"""Tags and collections (read + minimal create needed by uploads; full management in Phase 8)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from the_frame_v2.api.deps import DbSession, Uploader
from the_frame_v2.api.schemas import CollectionOut, TagCreateIn, TagOut, TagWithCount
from the_frame_v2.db.models import Collection
from the_frame_v2.services import tags

router = APIRouter(tags=["library"])


@router.get("/tags")
def list_tags(
    _: Uploader,
    session: DbSession,
    q: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[TagWithCount]:
    return [
        TagWithCount(id=t.id, name=t.name, color=t.color, photo_count=n)
        for t, n in tags.search_tags(session, q, limit)
    ]


@router.post("/tags")
def create_tag(body: TagCreateIn, _: Uploader, session: DbSession, response: Response) -> TagOut:
    """Create a tag, or return the existing one with the same name (case-insensitive)."""
    tag, created = tags.get_or_create(session, body.name)
    response.status_code = 201 if created else 200
    return TagOut.model_validate(tag)


@router.get("/collections")
def list_collections(_: Uploader, session: DbSession) -> list[CollectionOut]:
    rows = session.scalars(select(Collection).order_by(Collection.position, Collection.name))
    return [CollectionOut.model_validate(c) for c in rows]
