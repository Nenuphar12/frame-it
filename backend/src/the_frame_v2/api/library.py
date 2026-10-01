"""Tags, collections and the library filter (docs/organization.md)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Response
from sqlalchemy.orm import Session

from the_frame_v2.api.deps import Admin, Ctx, DbSession, Uploader
from the_frame_v2.api.schemas import (
    CollectionCreateIn,
    CollectionItemsIn,
    CollectionMoveIn,
    CollectionOut,
    CollectionReorderIn,
    CollectionUpdateIn,
    CountOut,
    FilterValidateIn,
    FilterValidateOut,
    PlaceOut,
    PlacesOut,
    TagCategoryCreateIn,
    TagCategoryOut,
    TagCategoryUpdateIn,
    TagCreateIn,
    TagMergeIn,
    TagOut,
    TagsCategorizeIn,
    TagSort,
    TagUpdateIn,
    TagWithCount,
)
from the_frame_v2.context import AppContext
from the_frame_v2.db.models import Collection
from the_frame_v2.domain import filters
from the_frame_v2.events import Event
from the_frame_v2.services import collections, library, tags
from the_frame_v2.services import places as places_service

router = APIRouter(tags=["library"])


def _tag_out(usage: tags.TagUsage) -> TagWithCount:
    return TagWithCount(
        id=usage.tag.id,
        name=usage.tag.name,
        color=usage.tag.color,
        category_id=usage.tag.category_id,
        photo_count=usage.photo_count,
        artwork_count=usage.artwork_count,
        own_artwork_count=usage.own_artwork_count,
        last_used_at=usage.tag.last_used_at,
    )


def _tags_changed(ctx: AppContext, session: Session, tag_id: str) -> None:
    """Commit, then tell every client: a tag's name, colour, category or links moved.

    Tags reach artworks through their photos too, so clients refresh tags, photos and artworks.
    """
    session.commit()
    ctx.broker.publish(Event("entity.changed", {"entity": "tag", "id": tag_id}, audience="all"))


# ---- tags ---------------------------------------------------------------------------------------
@router.get("/tags")
def list_tags(
    _: Uploader,
    session: DbSession,
    q: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=500),
    sort: TagSort = "usage",
) -> list[TagWithCount]:
    """`usage` (most used first), `recent` (last attached first — the picker) or `name`."""
    return [_tag_out(u) for u in tags.search_tags(session, q, limit, sort)]


@router.post("/tags")
def create_tag(body: TagCreateIn, _: Uploader, session: DbSession, response: Response) -> TagOut:
    """Create a tag, or return the existing one with the same name (case-insensitive)."""
    tag, created = tags.get_or_create(session, body.name, category_id=body.category_id)
    response.status_code = 201 if created else 200
    return TagOut.model_validate(tag)


@router.get("/tags/unused")
def list_unused_tags(_: Admin, session: DbSession) -> list[TagOut]:
    """Tags attached to nothing at all — trashed photos and artworks count as a use."""
    return [TagOut.model_validate(t) for t in tags.unused_tags(session)]


@router.post("/tags/delete-unused")
def delete_unused_tags(_: Admin, ctx: Ctx, session: DbSession) -> CountOut:
    """Delete every tag `GET /tags/unused` lists."""
    count = tags.delete_unused(session)
    _tags_changed(ctx, session, "")
    return CountOut(count=count)


@router.post("/tags/categorize")
def categorize_tags(body: TagsCategorizeIn, _: Admin, ctx: Ctx, session: DbSession) -> CountOut:
    """Move many tags into one category at once (`category_id: null` ⇒ "Other")."""
    count = tags.categorize(session, body.tag_ids, body.category_id)
    _tags_changed(ctx, session, body.tag_ids[0])
    return CountOut(count=count)


@router.patch("/tags/{tag_id}")
def update_tag(tag_id: str, body: TagUpdateIn, _: Admin, ctx: Ctx, session: DbSession) -> TagOut:
    """Rename, recolour, or move to a category. 409 `tag_exists` when the name is taken."""
    tag = tags.update_tag(
        session,
        tag_id,
        name=body.name,
        color=body.color,
        category_id=body.category_id if "category_id" in body.model_fields_set else ...,
    )
    out = TagOut.model_validate(tag)
    _tags_changed(ctx, session, tag_id)
    return out


@router.post("/tags/{tag_id}/merge")
def merge_tags(tag_id: str, body: TagMergeIn, _: Admin, ctx: Ctx, session: DbSession) -> TagOut:
    """Move every use of `source_ids` onto this tag and delete the sources."""
    tag = tags.merge_tags(session, source_ids=body.source_ids, target_id=tag_id)
    out = TagOut.model_validate(tag)
    _tags_changed(ctx, session, tag_id)
    return out


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag(tag_id: str, _: Admin, ctx: Ctx, session: DbSession) -> None:
    tags.delete_tag(session, tag_id)
    _tags_changed(ctx, session, tag_id)


# ---- tag categories -----------------------------------------------------------------------------
def _category_out(usage: tags.CategoryUsage) -> TagCategoryOut:
    out = TagCategoryOut.model_validate(usage.category)
    out.tag_count = usage.tag_count
    return out


@router.get("/tag-categories")
def list_tag_categories(_: Uploader, session: DbSession) -> list[TagCategoryOut]:
    """Categories in their order; a tag with no category is "Other" (not listed here)."""
    return [_category_out(u) for u in tags.list_categories(session)]


@router.post("/tag-categories", status_code=201)
def create_tag_category(
    body: TagCategoryCreateIn, _: Admin, ctx: Ctx, session: DbSession
) -> TagCategoryOut:
    """409 `category_exists` when the name (case-insensitive) is taken."""
    category = tags.create_category(session, body.name, body.color)
    out = _category_out(tags.CategoryUsage(category, 0))
    _tags_changed(ctx, session, "")
    return out


@router.patch("/tag-categories/{category_id}")
def update_tag_category(
    category_id: str, body: TagCategoryUpdateIn, _: Admin, ctx: Ctx, session: DbSession
) -> TagCategoryOut:
    category = tags.update_category(session, category_id, name=body.name, color=body.color)
    count = next(
        (u.tag_count for u in tags.list_categories(session) if u.category.id == category.id), 0
    )
    out = _category_out(tags.CategoryUsage(category, count))
    _tags_changed(ctx, session, "")
    return out


@router.delete("/tag-categories/{category_id}")
def delete_tag_category(category_id: str, _: Admin, ctx: Ctx, session: DbSession) -> CountOut:
    """Delete a category; its tags stay and become "Other". `count` = tags that moved."""
    count = tags.delete_category(session, category_id)
    _tags_changed(ctx, session, "")
    return CountOut(count=count)


# ---- places -------------------------------------------------------------------------------------
def _place_out(place: places_service.Place) -> PlaceOut:
    return PlaceOut(
        name=place.name,
        photo_count=place.photo_count,
        artwork_count=place.artwork_count,
        children=[_place_out(child) for child in place.children],
    )


@router.get("/places")
def list_places(_: Uploader, session: DbSession) -> PlacesOut:
    """Where the photos were taken — country → region → place — derived from their metadata."""
    found = places_service.places(session)
    return PlacesOut(
        countries=[_place_out(c) for c in found.countries], unplaced_photos=found.unplaced_photos
    )


# ---- collections --------------------------------------------------------------------------------
def _collection_out(collection: Collection, counts: collections.CollectionCounts) -> CollectionOut:
    out = CollectionOut.model_validate(collection)
    out.item_count = counts.direct
    out.nested_count = counts.nested
    return out


def _one(session: Session, collection: Collection) -> CollectionOut:
    counts = collections.counts(session, [collection.id])
    return _collection_out(collection, counts[collection.id])


@router.get("/collections")
def list_collections(_: Uploader, session: DbSession) -> list[CollectionOut]:
    """The whole tree, ordered by `position` among siblings (the client nests it by `parent_id`)."""
    rows = collections.list_collections(session)
    counts = collections.counts(session, [c.id for c in rows])
    return [_collection_out(c, counts[c.id]) for c in rows]


@router.post("/collections", status_code=201)
def create_collection(
    body: CollectionCreateIn, _: Admin, ctx: Ctx, session: DbSession
) -> CollectionOut:
    collection = collections.create_collection(
        session,
        name=body.name,
        parent_id=body.parent_id,
        kind=body.kind,
        description=body.description,
        filter_ast=body.filter,
    )
    out = _one(session, collection)
    _changed(ctx, session, collection.id)
    return out


@router.get("/collections/{collection_id}")
def get_collection(collection_id: str, _: Uploader, session: DbSession) -> CollectionOut:
    return _one(session, collections.get_collection(session, collection_id))


@router.patch("/collections/{collection_id}")
def update_collection(
    collection_id: str, body: CollectionUpdateIn, _: Admin, ctx: Ctx, session: DbSession
) -> CollectionOut:
    collection = collections.update_collection(
        session,
        collection_id,
        name=body.name,
        description=body.description,
        date_start=body.date_start,
        date_end=body.date_end,
        cover_artwork_id=body.cover_artwork_id,
        filter_ast=body.filter,
    )
    out = _one(session, collection)
    _changed(ctx, session, collection_id)
    return out


@router.post("/collections/{collection_id}/move")
def move_collection(
    collection_id: str, body: CollectionMoveIn, _: Admin, ctx: Ctx, session: DbSession
) -> CollectionOut:
    """Re-parent and/or reorder. 422 `collection_cycle` when it would land inside itself."""
    collection = collections.move_collection(
        session, collection_id, parent_id=body.parent_id, before_id=body.before_id
    )
    out = _one(session, collection)
    _changed(ctx, session, collection_id)
    return out


@router.delete("/collections/{collection_id}", status_code=204)
def delete_collection(collection_id: str, _: Admin, ctx: Ctx, session: DbSession) -> None:
    """Deletes the collection **and its subtree**. The artworks are untouched (not a trash op)."""
    collections.delete_collection(session, collection_id)
    _changed(ctx, session, collection_id)


@router.post("/collections/{collection_id}/items")
def add_collection_items(
    collection_id: str, body: CollectionItemsIn, _: Admin, ctx: Ctx, session: DbSession
) -> CountOut:
    count = collections.add_items(session, collection_id, body.artwork_ids)
    _changed(ctx, session, collection_id)
    return CountOut(count=count)


@router.post("/collections/{collection_id}/items/remove")
def remove_collection_items(
    collection_id: str, body: CollectionItemsIn, _: Admin, ctx: Ctx, session: DbSession
) -> CountOut:
    count = collections.remove_items(session, collection_id, body.artwork_ids)
    _changed(ctx, session, collection_id)
    return CountOut(count=count)


@router.post("/collections/{collection_id}/reorder", status_code=204)
def reorder_collection_item(
    collection_id: str, body: CollectionReorderIn, _: Admin, ctx: Ctx, session: DbSession
) -> None:
    """Manual order inside a collection: put an artwork right before another (or last)."""
    collections.reorder_item(session, collection_id, body.artwork_id, body.before_id)
    _changed(ctx, session, collection_id)


def _changed(ctx: AppContext, session: Session, collection_id: str) -> None:
    session.commit()
    ctx.broker.publish(
        Event("entity.changed", {"entity": "collection", "id": collection_id}, audience="all")
    )


# ---- filters ------------------------------------------------------------------------------------
@router.post("/filters/validate")
def validate_filter(body: FilterValidateIn, _: Uploader, session: DbSession) -> FilterValidateOut:
    """Check a filter AST and say how many artworks it matches (the smart-collection editor)."""
    try:
        parsed = filters.parse_filter(body.filter)
    except filters.FilterError as exc:
        return FilterValidateOut(valid=False, error=str(exc))
    count = library.count_artworks(session, query=library.ArtworkQuery(filter=parsed))
    return FilterValidateOut(valid=True, match_count=count)
