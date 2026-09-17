"""Tags (flat, case-insensitive unique names)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from the_frame_v2.db.models import PhotoTag, Tag
from the_frame_v2.errors import ProblemError

MAX_TAG_LENGTH = 64


def normalize_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ProblemError(422, "invalid_tag_name", "Tag name is empty")
    if len(cleaned) > MAX_TAG_LENGTH:
        raise ProblemError(422, "invalid_tag_name", "Tag name is too long")
    return cleaned


def search_tags(session: Session, q: str | None, limit: int = 50) -> list[tuple[Tag, int]]:
    usage = select(PhotoTag.tag_id, func.count().label("n")).group_by(PhotoTag.tag_id).subquery()
    stmt = select(Tag, func.coalesce(usage.c.n, 0)).outerjoin(usage, usage.c.tag_id == Tag.id)
    if q:
        stmt = stmt.where(Tag.name.ilike(f"%{q.strip()}%"))
    stmt = stmt.order_by(func.coalesce(usage.c.n, 0).desc(), Tag.name).limit(
        max(1, min(limit, 500))
    )
    return [(tag, int(count)) for tag, count in session.execute(stmt)]


def get_or_create(session: Session, name: str) -> tuple[Tag, bool]:
    normalized = normalize_name(name)
    existing = session.scalars(select(Tag).where(Tag.name == normalized)).first()
    if existing is not None:
        return existing, False
    tag = Tag(name=normalized)
    session.add(tag)
    session.flush()
    return tag, True
