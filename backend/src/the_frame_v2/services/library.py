"""The library query: one filter AST (docs/data-model.md §5.2) compiled to SQL, once.

`domain/filters.py` says what a filter may *mean*; this module is the only place that knows how it
reaches the schema. The same compiler serves the filter bar, smart collections and the artwork
list, so a smart collection can never disagree with the filter that made it.

Two clause families:

- **artwork columns** — `favorite`, `status`, `worst_tier`, `photo_count`, `is_incomplete`,
  `title`, `created_at`, `updated_at`, `collection`;
- **photo properties** — `taken_at` and `place` hold when *some photo the artwork uses* matches,
  compiled as an EXISTS over `artwork_photos` (an artwork is only as old as its oldest photo);
- **both** — `tag` reads the artwork's own tags *and* its live photos' (tag inheritance).

`text` matches the FTS index (`services/search.py`).
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import ColumnElement, Select, and_, func, not_, or_, select
from sqlalchemy.orm import Session

from the_frame_v2.db.models import (
    Artwork,
    ArtworkPhoto,
    ArtworkTag,
    Collection,
    CollectionItem,
    Photo,
    PhotoTag,
    Tag,
)
from the_frame_v2.domain import filters
from the_frame_v2.domain.filters import Clause, Group
from the_frame_v2.errors import ProblemError
from the_frame_v2.services import collections, search

MAX_LIMIT = 500
Sort = Literal["created_desc", "created_asc", "updated_desc", "title_asc", "manual"]
SORTS: tuple[Sort, ...] = ("created_desc", "created_asc", "updated_desc", "title_asc", "manual")


def _true() -> ColumnElement[bool]:
    return Artwork.id.is_not(None)


def _false() -> ColumnElement[bool]:
    return Artwork.id.is_(None)


def _photo_exists(condition: ColumnElement[bool]) -> ColumnElement[bool]:
    return Artwork.id.in_(
        select(ArtworkPhoto.artwork_id)
        .join(Photo, Photo.id == ArtworkPhoto.photo_id)
        .where(Photo.deleted_at.is_(None), condition)
    )


def _collection_scope(session: Session, clause: Clause) -> set[str]:
    ids: set[str] = set()
    for collection_id in clause.value:
        ids.update(
            collections.subtree_ids(session, collection_id)
            if clause.include_nested
            else [collection_id]
        )
    return ids


def _in_collections(session: Session, ids: set[str]) -> ColumnElement[bool]:
    """Membership of manual collections *and* of the smart ones among them (their filters)."""
    rows = list(
        session.execute(select(Collection.id, Collection.kind).where(Collection.id.in_(ids)))
    )
    manual = [row[0] for row in rows if row[1] == "manual"]
    conditions: list[ColumnElement[bool]] = []
    if manual:
        conditions.append(
            Artwork.id.in_(
                select(CollectionItem.artwork_id).where(CollectionItem.collection_id.in_(manual))
            )
        )
    for row in rows:
        if row[1] != "smart":
            continue
        collection = session.get(Collection, row[0])
        if collection is None:
            continue
        conditions.append(compile_filter(session, collections.parsed_filter(collection), depth=1))
    if not conditions:
        return _false()
    return or_(*conditions)


def _clause_sql(session: Session, clause: Clause, depth: int) -> ColumnElement[bool]:
    field, op, value = clause.field, clause.op, clause.value
    if field == "favorite":
        return Artwork.favorite.is_(bool(value))
    if field == "is_incomplete":
        return Artwork.is_incomplete.is_(bool(value))
    if field == "status":
        return Artwork.status == value if op == "eq" else Artwork.status.in_(value)
    if field == "worst_tier":
        return Artwork.worst_tier.in_(value)
    if field == "photo_count":
        count = Artwork.photo_count
        options: dict[str, ColumnElement[bool]] = {
            "eq": count == value,
            "gte": count >= value,
            "lte": count <= value,
        }
        return options[op]
    if field == "title":
        return Artwork.title.ilike(f"%{value}%")
    if field in ("created_at", "updated_at"):
        stamp = Artwork.created_at if field == "created_at" else Artwork.updated_at
        return _date_sql(stamp, op, value)
    if field == "taken_at":
        return _photo_exists(_date_sql(Photo.taken_at, op, value))
    if field == "place":
        like = f"%{value}%"
        return _photo_exists(
            or_(
                Photo.place_name.ilike(like),
                Photo.place_admin1.ilike(like),
                Photo.place_country.ilike(like),
            )
        )
    if field == "tag":
        return _tag_sql(op, value)
    if field == "collection":
        if depth > filters.MAX_DEPTH:
            raise ProblemError(422, "filter_cycle", "Smart collections reference each other")
        scope = _collection_scope(session, clause)
        inside = _in_collections(session, scope)
        return inside if op == "in" else not_(inside)
    if field == "text":
        ids = search.search_ids(session, "artwork", str(value))
        return Artwork.id.in_(ids) if ids else _false()
    raise ProblemError(422, "invalid_filter", "Unsupported filter field", field)


def _carries(tag_ids: Sequence[str]) -> ColumnElement[bool]:
    """The artwork carries one of these tags — its own, or through one of its live photos.

    An artwork's effective tags are its own plus its photos' (docs/organization.md §1), the same
    reading `taken_at` and `place` already have: an artwork shows Alice when one of its photos does.
    """
    ids = list(tag_ids)
    own = select(ArtworkTag.artwork_id).where(ArtworkTag.tag_id.in_(ids))
    inherited = (
        select(ArtworkPhoto.artwork_id)
        .join(PhotoTag, PhotoTag.photo_id == ArtworkPhoto.photo_id)
        .join(Photo, Photo.id == ArtworkPhoto.photo_id)
        .where(PhotoTag.tag_id.in_(ids), Photo.deleted_at.is_(None))
    )
    return or_(Artwork.id.in_(own), Artwork.id.in_(inherited))


def _tag_sql(op: str, tag_ids: Sequence[str]) -> ColumnElement[bool]:
    if op == "has_any":
        return _carries(tag_ids)
    if op == "none":
        return not_(_carries(tag_ids))
    return and_(*(_carries([tag_id]) for tag_id in tag_ids))


def _date_sql(column: Any, op: str, value: Any) -> ColumnElement[bool]:
    if op == "between":
        start = filters.parse_date(value[0])
        end = filters.parse_date(value[1], end=True)
        return and_(column.is_not(None), column >= start, column <= end)
    bound = filters.parse_date(value, end=op == "before")
    return and_(column.is_not(None), column < bound if op == "before" else column > bound)


def compile_filter(session: Session, node: Group | Clause, depth: int = 0) -> ColumnElement[bool]:
    """The AST as one boolean SQL expression over `artworks`."""
    if isinstance(node, Clause):
        return _clause_sql(session, node, depth)
    if not node.clauses:
        return _true()
    parts = [compile_filter(session, child, depth + 1) for child in node.clauses]
    if node.op == "or":
        return or_(*parts)
    conjunction = and_(*parts)
    return not_(conjunction) if node.op == "not" else conjunction


# ---- listing ------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ArtworkQuery:
    """Everything the artwork list can be narrowed by (all optional, all combinable)."""

    filter: Group | None = None
    collection_id: str | None = None
    include_nested: bool = False
    status: str | None = None
    favorite: bool | None = None
    photo_id: str | None = None
    q: str | None = None
    sort: Sort = "created_desc"
    trashed: bool = False


def parse_query_filter(raw: Any) -> Group | None:
    if raw is None:
        return None
    try:
        return filters.parse_filter(raw)
    except filters.FilterError as exc:
        raise ProblemError(422, "invalid_filter", "Invalid filter", str(exc)) from exc


def _base(session: Session, query: ArtworkQuery) -> Select[tuple[Artwork]]:
    stmt = select(Artwork)
    stmt = stmt.where(
        Artwork.deleted_at.is_not(None) if query.trashed else Artwork.deleted_at.is_(None)
    )
    if query.status is not None:
        stmt = stmt.where(Artwork.status == query.status)
    if query.favorite is not None:
        stmt = stmt.where(Artwork.favorite.is_(query.favorite))
    if query.photo_id is not None:
        stmt = stmt.where(
            Artwork.id.in_(
                select(ArtworkPhoto.artwork_id).where(ArtworkPhoto.photo_id == query.photo_id)
            )
        )
    if query.q:
        ids = search.search_ids(session, "artwork", query.q)
        stmt = stmt.where(Artwork.id.in_(ids) if ids else _false())
    if query.filter is not None:
        stmt = stmt.where(compile_filter(session, query.filter))
    if query.collection_id is not None:
        # One path for both kinds and for the subtree: `_in_collections` unions manual membership
        # with the filters of the smart collections among the ids. Looking only at
        # `collection_items` made a smart *sub*-collection contribute nothing to include-nested.
        collection = collections.get_collection(session, query.collection_id)
        scope = (
            set(collections.subtree_ids(session, collection.id))
            if query.include_nested
            else {collection.id}
        )
        stmt = stmt.where(_in_collections(session, scope))
    return stmt


@dataclass(frozen=True, slots=True)
class ArtworkPage:
    items: list[Artwork]
    tags: dict[str, list[Tag]]
    next_cursor: str | None
    inherited: dict[str, list[Tag]] = field(default_factory=dict)
    """artwork id → tags it carries through its photos (`artworks.inherited_tags_for`)."""


def _sort_key(artwork: Artwork, sort: Sort) -> str:
    if sort == "title_asc":
        return artwork.title
    if sort == "updated_desc":
        return artwork.updated_at.isoformat()
    return artwork.created_at.isoformat()


def _encode_cursor(artwork: Artwork, sort: Sort, position: float | None) -> str:
    key = f"{position}" if sort == "manual" and position is not None else _sort_key(artwork, sort)
    return base64.urlsafe_b64encode(f"{key}|{artwork.id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        key, artwork_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
        return key, artwork_id
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProblemError(400, "invalid_cursor", "Invalid cursor") from exc


def _manual_order(
    session: Session, stmt: Select[tuple[Artwork]], collection_id: str
) -> Select[tuple[Any, ...]]:
    return stmt.join(
        CollectionItem,
        and_(
            CollectionItem.artwork_id == Artwork.id,
            CollectionItem.collection_id == collection_id,
        ),
    ).add_columns(CollectionItem.position)


def list_artworks(
    session: Session, query: ArtworkQuery, cursor: str | None = None, limit: int = 100
) -> ArtworkPage:
    """One page, newest first by default; `manual` order needs a manual collection."""
    from the_frame_v2.services import artworks as artworks_service

    limit = max(1, min(limit, MAX_LIMIT))
    sort = query.sort
    stmt = _base(session, query)
    if sort == "manual":
        if query.collection_id is None:
            raise ProblemError(422, "manual_sort", "Manual order needs a collection")
        if query.include_nested:
            # `position` only orders one collection's own items, so the join below would drop
            # every artwork that lives in a *sub*-collection and silently return the flat list.
            # Refuse instead: a manual order across a subtree has no meaning to fall back on.
            raise ProblemError(
                422,
                "manual_sort_nested",
                "Manual order cannot span sub-collections",
                "Turn off include-nested, or sort by date",
            )
        joined = _manual_order(session, stmt, query.collection_id)
        if cursor:
            key, artwork_id = _decode_cursor(cursor)
            joined = joined.where(
                or_(
                    CollectionItem.position > float(key),
                    and_(CollectionItem.position == float(key), Artwork.id > artwork_id),
                )
            )
        rows = list(
            session.execute(joined.order_by(CollectionItem.position, Artwork.id).limit(limit + 1))
        )
        found = [(row[0], float(row[1])) for row in rows]
        next_cursor = (
            _encode_cursor(found[limit - 1][0], sort, found[limit - 1][1])
            if len(found) > limit
            else None
        )
        items = [artwork for artwork, _ in found[:limit]]
    else:
        column, descending = _order_column(sort)
        if cursor:
            key, artwork_id = _decode_cursor(cursor)
            bound: Any = datetime.fromisoformat(key) if sort != "title_asc" else key
            stmt = stmt.where(
                or_(column < bound, and_(column == bound, Artwork.id < artwork_id))
                if descending
                else or_(column > bound, and_(column == bound, Artwork.id > artwork_id))
            )
        order = (
            (column.desc(), Artwork.id.desc()) if descending else (column.asc(), Artwork.id.asc())
        )
        rows_only = list(session.scalars(stmt.order_by(*order).limit(limit + 1)))
        next_cursor = (
            _encode_cursor(rows_only[limit - 1], sort, None) if len(rows_only) > limit else None
        )
        items = rows_only[:limit]
    ids = [a.id for a in items]
    return ArtworkPage(
        items,
        artworks_service.tags_for(session, ids),
        next_cursor,
        artworks_service.inherited_tags_for(session, ids),
    )


def _order_column(sort: Sort) -> tuple[Any, bool]:
    if sort == "created_asc":
        return Artwork.created_at, False
    if sort == "updated_desc":
        return Artwork.updated_at, True
    if sort == "title_asc":
        return Artwork.title, False
    return Artwork.created_at, True


def smart_collections_of(session: Session, artwork_id: str) -> list[str]:
    """Smart collections whose filter matches this artwork — membership it did not choose.

    One query per smart collection: the artwork is asked to satisfy each stored filter. The viewer
    shows these next to the manual ones, but greyed: there is no row to remove.
    """
    found: list[str] = []
    rows = session.scalars(
        select(Collection)
        .where(Collection.kind == "smart")
        .order_by(Collection.position, Collection.name)
    )
    for collection in rows:
        condition = compile_filter(session, collections.parsed_filter(collection))
        hit = session.scalar(
            select(Artwork.id).where(
                Artwork.id == artwork_id, Artwork.deleted_at.is_(None), condition
            )
        )
        if hit is not None:
            found.append(collection.id)
    return found


def smart_members(session: Session, collection: Collection) -> set[str]:
    """Every artwork a smart collection currently holds (its filter, as ids)."""
    condition = compile_filter(session, collections.parsed_filter(collection))
    return set(session.scalars(select(Artwork.id).where(Artwork.deleted_at.is_(None), condition)))


def count_artworks(
    session: Session,
    *,
    query: ArtworkQuery | None = None,
    collection_id: str | None = None,
) -> int:
    effective = query or ArtworkQuery(collection_id=collection_id)
    stmt = _base(session, effective).with_only_columns(func.count(Artwork.id))
    return int(session.scalar(stmt) or 0)
