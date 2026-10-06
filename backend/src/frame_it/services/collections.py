"""Collections: a nested tree of manual lists, plus smart collections (a saved filter).

Spec: docs/organization.md. Two kinds share one table:

- **manual** — artworks added by hand, ordered by a REAL `position` among the collection's items;
- **smart** — a stored filter AST (`domain/filters.py`); its items are a query, never rows.

Siblings are ordered by a REAL `position` too, so a drag-and-drop move writes exactly one row
(midpoint insertion, renormalized when neighbours get too close). Moving a collection under one of
its own descendants is refused (`collection_cycle`): the tree is the one invariant here.

Deleting a collection is **not** a trash operation (docs/data-model.md): its subtree goes with it
and the artworks are untouched.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from frame_it.db.models import Artwork, Collection, CollectionItem
from frame_it.domain import filters
from frame_it.errors import ProblemError, not_found
from frame_it.ids import utcnow
from frame_it.services import search

MAX_DEPTH = 8
MAX_NAME = 256
#: Items closer than this share a double: the whole list is renumbered instead.
MIN_GAP = 1e-9


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())[:MAX_NAME]
    if not cleaned:
        raise ProblemError(422, "invalid_collection_name", "The collection needs a name")
    return cleaned


def get_collection(session: Session, collection_id: str) -> Collection:
    collection = session.get(Collection, collection_id)
    if collection is None:
        raise not_found("Collection")
    return collection


def _manual(collection: Collection) -> Collection:
    if collection.kind != "manual":
        raise ProblemError(
            422, "smart_collection", "This is a smart collection", "Its items come from its filter"
        )
    return collection


# ---- the tree -----------------------------------------------------------------------------------
_SUBTREE = text(
    """
    WITH RECURSIVE subtree(id) AS (
        SELECT id FROM collections WHERE id = :root
        UNION ALL
        SELECT c.id FROM collections c JOIN subtree s ON c.parent_id = s.id
    )
    SELECT id FROM subtree
    """
)


def subtree_ids(session: Session, collection_id: str) -> list[str]:
    """The collection and every descendant (recursive CTE — §5.2's include-nested)."""
    return [row[0] for row in session.execute(_SUBTREE, {"root": collection_id})]


def _depth_of(session: Session, collection_id: str | None) -> int:
    depth = 0
    current = collection_id
    while current is not None and depth <= MAX_DEPTH:
        parent = session.scalar(select(Collection.parent_id).where(Collection.id == current))
        if parent is None:
            break
        current, depth = parent, depth + 1
    return depth


def _check_parent(session: Session, collection: Collection | None, parent_id: str | None) -> None:
    if parent_id is None:
        return
    parent = get_collection(session, parent_id)
    if parent.kind == "smart":
        raise ProblemError(422, "smart_parent", "A smart collection holds no sub-collections")
    if collection is not None and parent_id in set(subtree_ids(session, collection.id)):
        raise ProblemError(
            422, "collection_cycle", "A collection cannot be moved inside itself", collection.name
        )
    if _depth_of(session, parent_id) + 1 >= MAX_DEPTH:
        raise ProblemError(422, "collection_too_deep", f"More than {MAX_DEPTH} levels")


def _sibling_positions(session: Session, parent_id: str | None) -> list[tuple[str, float]]:
    stmt = select(Collection.id, Collection.position).order_by(Collection.position, Collection.name)
    stmt = stmt.where(
        Collection.parent_id.is_(None) if parent_id is None else Collection.parent_id == parent_id
    )
    return [(row[0], float(row[1])) for row in session.execute(stmt)]


def _next_position(session: Session, parent_id: str | None) -> float:
    siblings = _sibling_positions(session, parent_id)
    return (siblings[-1][1] + 1.0) if siblings else 1.0


def _place(
    session: Session, moved: Collection, parent_id: str | None, before_id: str | None
) -> None:
    """Give `moved` a position putting it right before `before_id` among its new siblings."""
    siblings = [(i, p) for i, p in _sibling_positions(session, parent_id) if i != moved.id]
    if before_id is None:
        moved.position = (siblings[-1][1] + 1.0) if siblings else 1.0
        return
    index = next((n for n, (i, _) in enumerate(siblings) if i == before_id), None)
    if index is None:
        raise ProblemError(422, "unknown_sibling", "Unknown collection to insert before")
    after = siblings[index][1]
    before = siblings[index - 1][1] if index > 0 else after - 2.0
    moved.position = (before + after) / 2
    if after - before < MIN_GAP:
        _renumber(session, parent_id, moved, index)


def _renumber(session: Session, parent_id: str | None, moved: Collection, index: int) -> None:
    """Doubles ran out of room: rewrite the whole sibling list as 1, 2, 3…"""
    order = [i for i, _ in _sibling_positions(session, parent_id) if i != moved.id]
    order.insert(index, moved.id)
    rows = {c.id: c for c in session.scalars(select(Collection).where(Collection.id.in_(order)))}
    for n, collection_id in enumerate(order, start=1):
        rows[collection_id].position = float(n)


# ---- CRUD ---------------------------------------------------------------------------------------
def create_collection(
    session: Session,
    *,
    name: str,
    parent_id: str | None = None,
    kind: str = "manual",
    description: str = "",
    filter_ast: Any | None = None,
) -> Collection:
    if kind not in ("manual", "smart"):
        raise ProblemError(422, "invalid_collection_kind", "Invalid kind")
    _check_parent(session, None, parent_id)
    collection = Collection(
        name=_clean_name(name),
        parent_id=parent_id,
        kind=kind,
        description=description.strip()[:4000],
        position=_next_position(session, parent_id),
    )
    if kind == "smart":
        collection.filter = _checked_filter(session, filter_ast, None)
    elif filter_ast is not None:
        raise ProblemError(422, "manual_collection", "A manual collection has no filter")
    session.add(collection)
    session.flush()
    search.index_collection(session, collection)
    return collection


def _checked_filter(session: Session, raw: Any, collection_id: str | None) -> dict[str, Any]:
    if raw is None:
        raise ProblemError(422, "filter_required", "A smart collection needs a filter")
    try:
        parsed = filters.parse_filter(raw)
    except filters.FilterError as exc:
        raise ProblemError(422, "invalid_filter", "Invalid filter", str(exc)) from exc
    referenced = filters.collection_ids_used(parsed)
    if collection_id is not None and collection_id in referenced:
        raise ProblemError(422, "filter_cycle", "A smart collection cannot reference itself")
    for other in referenced:
        row = session.get(Collection, other)
        if row is None:
            raise ProblemError(422, "unknown_collection", "Unknown collection", other)
        if collection_id is not None and row.kind == "smart":
            nested = row.filter or {}
            if collection_id in filters.collection_ids_used(filters.parse_filter(nested)):
                raise ProblemError(422, "filter_cycle", "Smart collections reference each other")
    return parsed.model_dump(mode="json")


def update_collection(
    session: Session,
    collection_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    cover_artwork_id: str | None = None,
    filter_ast: Any | None = None,
    include_nested: bool | None = None,
) -> Collection:
    collection = get_collection(session, collection_id)
    if name is not None:
        collection.name = _clean_name(name)
    if description is not None:
        collection.description = description.strip()[:4000]
    if date_start is not None:
        collection.date_start = _clean_date(date_start)
    if date_end is not None:
        collection.date_end = _clean_date(date_end)
    if cover_artwork_id is not None:
        if cover_artwork_id == "":
            collection.cover_artwork_id = None
        else:
            artwork = session.get(Artwork, cover_artwork_id)
            if artwork is None or artwork.deleted_at is not None:
                raise ProblemError(422, "unknown_artwork", "Unknown artwork")
            collection.cover_artwork_id = cover_artwork_id
    if filter_ast is not None:
        if collection.kind != "smart":
            raise ProblemError(422, "manual_collection", "A manual collection has no filter")
        collection.filter = _checked_filter(session, filter_ast, collection.id)
    collection.updated_at = utcnow()
    session.flush()
    search.index_collection(session, collection)
    return collection


def _clean_date(value: str) -> str | None:
    if not value:
        return None
    try:
        filters.parse_date(value)
    except filters.FilterError as exc:
        raise ProblemError(422, "invalid_date", "Invalid date", value) from exc
    return value[:10]


def move_collection(
    session: Session, collection_id: str, *, parent_id: str | None, before_id: str | None
) -> Collection:
    """Re-parent and/or reorder. Refuses to move a collection inside its own subtree."""
    collection = get_collection(session, collection_id)
    _check_parent(session, collection, parent_id)
    if (
        parent_id is not None
        and _depth_of(session, parent_id) + 1 + _height(session, collection.id) > MAX_DEPTH
    ):
        raise ProblemError(422, "collection_too_deep", f"More than {MAX_DEPTH} levels")
    collection.parent_id = parent_id
    _place(session, collection, parent_id, before_id)
    collection.updated_at = utcnow()
    return collection


def _height(session: Session, collection_id: str) -> int:
    ids = set(subtree_ids(session, collection_id))
    parents = {
        row[0]: row[1]
        for row in session.execute(
            select(Collection.id, Collection.parent_id).where(Collection.id.in_(ids))
        )
    }
    height = 0
    for node in ids:
        depth = 0
        current: str | None = node
        while current is not None and current != collection_id:
            current = parents.get(current)
            depth += 1
        height = max(height, depth)
    return height


def delete_collection(session: Session, collection_id: str) -> list[str]:
    """Delete the collection and its subtree (the artworks are untouched). Returns the ids."""
    collection = get_collection(session, collection_id)
    ids = subtree_ids(session, collection.id)
    search.remove(session, "collection", ids)
    session.delete(collection)  # ON DELETE CASCADE removes the subtree and its items
    return ids


# ---- items --------------------------------------------------------------------------------------
def add_items(session: Session, collection_id: str, artwork_ids: Sequence[str]) -> int:
    """Append artworks to a manual collection (already-present ones keep their position)."""
    collection = _manual(get_collection(session, collection_id))
    known = set(
        session.scalars(
            select(Artwork.id).where(Artwork.id.in_(set(artwork_ids)), Artwork.deleted_at.is_(None))
        )
    )
    missing = [i for i in artwork_ids if i not in known]
    if missing:
        raise ProblemError(422, "unknown_artwork", "Unknown artwork", missing[0])
    present = set(
        session.scalars(
            select(CollectionItem.artwork_id).where(
                CollectionItem.collection_id == collection.id,
                CollectionItem.artwork_id.in_(known),
            )
        )
    )
    position = float(
        session.scalar(
            select(func.coalesce(func.max(CollectionItem.position), 0.0)).where(
                CollectionItem.collection_id == collection.id
            )
        )
        or 0.0
    )
    added = 0
    for artwork_id in artwork_ids:
        if artwork_id in present:
            continue
        present.add(artwork_id)
        position += 1.0
        session.add(
            CollectionItem(collection_id=collection.id, artwork_id=artwork_id, position=position)
        )
        added += 1
    collection.updated_at = utcnow()
    return added


def remove_items(session: Session, collection_id: str, artwork_ids: Sequence[str]) -> int:
    collection = _manual(get_collection(session, collection_id))
    rows = list(
        session.scalars(
            select(CollectionItem).where(
                CollectionItem.collection_id == collection.id,
                CollectionItem.artwork_id.in_(set(artwork_ids)),
            )
        )
    )
    for row in rows:
        session.delete(row)
    collection.updated_at = utcnow()
    return len(rows)


def reorder_item(
    session: Session, collection_id: str, artwork_id: str, before_id: str | None
) -> None:
    """Manual order: put `artwork_id` right before `before_id` (or last when it is None)."""
    collection = _manual(get_collection(session, collection_id))
    items = [
        (row[0], float(row[1]))
        for row in session.execute(
            select(CollectionItem.artwork_id, CollectionItem.position)
            .where(CollectionItem.collection_id == collection.id)
            .order_by(CollectionItem.position, CollectionItem.artwork_id)
        )
    ]
    if artwork_id not in {i for i, _ in items}:
        raise not_found("Collection item")
    rest = [(i, p) for i, p in items if i != artwork_id]
    if before_id is None:
        index = len(rest)
    else:
        found = next((n for n, (i, _) in enumerate(rest) if i == before_id), None)
        if found is None:
            raise ProblemError(422, "unknown_sibling", "Unknown artwork to insert before")
        index = found
    after = rest[index][1] if index < len(rest) else None
    before = rest[index - 1][1] if index > 0 else None
    rows = {
        row.artwork_id: row
        for row in session.scalars(
            select(CollectionItem).where(CollectionItem.collection_id == collection.id)
        )
    }
    if before is None and after is None:
        rows[artwork_id].position = 1.0
    elif before is None:
        rows[artwork_id].position = after - 1.0  # type: ignore[operator]
    elif after is None:
        rows[artwork_id].position = before + 1.0
    else:
        rows[artwork_id].position = (before + after) / 2
        if after - before < MIN_GAP:
            order = [i for i, _ in rest]
            order.insert(index, artwork_id)
            for n, item_id in enumerate(order, start=1):
                rows[item_id].position = float(n)
    collection.updated_at = utcnow()


# ---- reading ------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CollectionCounts:
    """How many (non-trashed) artworks a collection holds, on its own and with its subtree."""

    direct: int
    nested: int


def counts(session: Session, collection_ids: Sequence[str]) -> dict[str, CollectionCounts]:
    """Item counts for a whole tree (the sidebar asks for all of them at once).

    `nested` counts **distinct** artworks: one filed in two sub-collections of the same parent is
    one artwork, not two, and summing the children's counts would say otherwise.
    """
    if not collection_ids:
        return {}
    from frame_it.services import library  # local: library imports collections

    members: dict[str, set[str]] = {}
    for row in session.execute(
        select(CollectionItem.collection_id, CollectionItem.artwork_id)
        .join(Artwork, Artwork.id == CollectionItem.artwork_id)
        .where(Artwork.deleted_at.is_(None))
    ):
        members.setdefault(row[0], set()).add(row[1])
    rows = list(session.scalars(select(Collection)))
    parents = {row.id: row.parent_id for row in rows}
    smart = {row.id: row for row in rows if row.kind == "smart"}
    children: dict[str | None, list[str]] = {}
    for node, parent in parents.items():
        children.setdefault(parent, []).append(node)

    # A smart collection's members are its filter's matches, resolved once and reused: a smart
    # *sub*-collection counts towards its parent's nested total like any other child.
    resolved: dict[str, set[str]] = {}

    def holds(collection_id: str) -> set[str]:
        if collection_id in smart:
            if collection_id not in resolved:
                resolved[collection_id] = library.smart_members(session, smart[collection_id])
            return resolved[collection_id]
        return members.get(collection_id, set())

    result: dict[str, CollectionCounts] = {}
    for collection_id in collection_ids:
        nested: set[str] = set()
        stack = [collection_id]
        while stack:
            node = stack.pop()
            nested |= holds(node)
            stack.extend(children.get(node, ()))
        result[collection_id] = CollectionCounts(len(holds(collection_id)), len(nested))
    return result


def collections_of(session: Session, artwork_id: str) -> list[str]:
    """The **manual** collections holding this artwork, in tree order (the ones it can leave).

    Smart membership is derived, not stored: `library.smart_collections_of` answers that.
    """
    return [
        row[0]
        for row in session.execute(
            select(CollectionItem.collection_id)
            .join(Collection, Collection.id == CollectionItem.collection_id)
            .where(CollectionItem.artwork_id == artwork_id)
            .order_by(Collection.position, Collection.name)
        )
    ]


def list_collections(session: Session) -> list[Collection]:
    return list(session.scalars(select(Collection).order_by(Collection.position, Collection.name)))


def parsed_filter(collection: Collection) -> filters.Group:
    """The stored AST of a smart collection (stored ones are valid by construction)."""
    return filters.parse_filter(collection.filter or {"op": "and", "clauses": []})
