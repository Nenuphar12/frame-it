"""Artworks: creation from photos + templates, document saves (optimistic concurrency), snapshots.

Spec: docs/artwork-document.md, docs/data-model.md (`artworks`, `artwork_photos`, snapshots).
Every document save validates the document (structure + library references), recomputes the
derived columns and the `artwork_photos` index; callers enqueue a render after commit
(`services/render.py`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from the_frame_v2.db.models import (
    Artwork,
    ArtworkPhoto,
    ArtworkSnapshot,
    ArtworkTag,
    Collection,
    CollectionItem,
    FrameStyle,
    Layout,
    Photo,
    PhotoPendingMeta,
    PhotoTag,
    Tag,
)
from the_frame_v2.domain import composition as composition_solver
from the_frame_v2.domain import templates as template_docs
from the_frame_v2.domain.composition import Recipe
from the_frame_v2.domain.document import (
    ArtworkDocument,
    Composition,
    DocumentIssue,
    parse_document,
    validate_references,
)
from the_frame_v2.domain.geometry import Size
from the_frame_v2.domain.templates import PhotoInput, build_composition_document
from the_frame_v2.errors import ProblemError, not_found
from the_frame_v2.ids import utcnow
from the_frame_v2.imaging.assets import catalog
from the_frame_v2.services import recipes, search, templates
from the_frame_v2.services import tags as tags_service

MAX_SNAPSHOTS = 20
MAX_LIMIT = 500
STATUSES = ("draft", "ready")
SNAPSHOT_REASONS = (
    "opened",
    "manual",
    "pre_restore",
    "pre_template_update",
    "pre_import",
    "pre_trash",
)


# ---- validation ---------------------------------------------------------------------------------
def invalid_document(issues: Sequence[DocumentIssue]) -> ProblemError:
    return ProblemError(
        422,
        "invalid_document",
        "Invalid artwork document",
        issues[0].msg if issues else None,
        extra={"errors": [i.as_dict() for i in issues]},
    )


def parse_or_raise(raw: Mapping[str, Any]) -> ArtworkDocument:
    """Structural validation with precise locations (422 `invalid_document`)."""
    try:
        return parse_document(raw)
    except ValidationError as exc:
        issues = [
            DocumentIssue(tuple(e["loc"]), e["msg"].removeprefix("Value error, "), e["type"])
            for e in exc.errors(include_url=False)
        ]
        raise invalid_document(issues) from exc
    except ValueError as exc:
        raise invalid_document(
            [DocumentIssue(("schema",), str(exc), "unsupported_schema")]
        ) from exc


def photo_sizes(session: Session, photo_ids: Sequence[str]) -> dict[str, Size]:
    """EXIF-oriented sizes of the given photos that exist and are not trashed."""
    if not photo_ids:
        return {}
    rows = session.execute(
        select(Photo.id, Photo.width, Photo.height).where(
            Photo.id.in_(set(photo_ids)), Photo.deleted_at.is_(None)
        )
    )
    return {row.id: Size(row.width, row.height) for row in rows}


def check_references(session: Session, doc: ArtworkDocument) -> None:
    _check_references(doc, photo_sizes(session, doc.photo_ids()))


def _check_references(doc: ArtworkDocument, sizes: Mapping[str, Size]) -> None:
    assets = catalog()
    issues = validate_references(
        doc, sizes, assets.font_weights, assets.texture_exists, recipes.spec
    )
    if issues:
        raise invalid_document(issues)


def resolved(doc: ArtworkDocument, sizes: Mapping[str, Size]) -> ArtworkDocument:
    """Server authority (§7): while attached, the composition — not the payload — sets the geometry.

    The two solvers are identical (conformance), so this is a no-op for a healthy client; a buggy
    one simply cannot persist a wrong rect. A detached block, or none at all, leaves `doc` alone:
    the slots are the truth then (§5). An unknown recipe is left to `_check_references`.
    """
    composition = doc.composition
    if composition is None or composition.detached:
        return doc
    recipe = recipes.find(composition.recipe)
    return doc if recipe is None else composition_solver.apply(doc, recipe, sizes)


def validated(session: Session, raw: Mapping[str, Any]) -> ArtworkDocument:
    """Parse, check against the library, then let the composition re-derive the geometry."""
    doc = parse_or_raise(raw)
    sizes = photo_sizes(session, doc.photo_ids())
    _check_references(doc, sizes)
    return resolved(doc, sizes)


# ---- persistence helpers ------------------------------------------------------------------------
def store_document(session: Session, artwork: Artwork, doc: ArtworkDocument) -> None:
    """Write the document and everything derived from it (columns, photo index, search index)."""
    quality = doc.quality()
    artwork.document = doc.canonical()
    artwork.schema_version = doc.schema_version
    artwork.worst_tier = quality.worst_tier
    artwork.min_scale = quality.min_scale
    artwork.max_scale = quality.max_scale
    artwork.photo_count = quality.photo_count
    artwork.is_incomplete = quality.is_incomplete
    if artwork.status == "ready" and quality.is_incomplete:
        artwork.status = "draft"
    session.flush()
    session.execute(delete(ArtworkPhoto).where(ArtworkPhoto.artwork_id == artwork.id))
    session.add_all(
        ArtworkPhoto(artwork_id=artwork.id, slot_id=slot.id, photo_id=slot.photo_id)
        for slot in doc.slots
        if slot.photo_id is not None
    )
    search.index_artwork(session, artwork)


def get_artwork(session: Session, artwork_id: str) -> Artwork:
    artwork = session.get(Artwork, artwork_id)
    if artwork is None or artwork.deleted_at is not None:
        raise not_found("Artwork")
    return artwork


def document_of(artwork: Artwork) -> ArtworkDocument:
    """Stored documents are valid by construction; older schemas are migrated on read."""
    return parse_document(artwork.document)


def tags_for(session: Session, artwork_ids: Sequence[str]) -> dict[str, list[Tag]]:
    result: dict[str, list[Tag]] = {i: [] for i in artwork_ids}
    if not artwork_ids:
        return result
    rows = session.execute(
        select(ArtworkTag.artwork_id, Tag)
        .join(Tag, Tag.id == ArtworkTag.tag_id)
        .where(ArtworkTag.artwork_id.in_(artwork_ids))
        .order_by(Tag.name)
    )
    for artwork_id, tag in rows:
        result[artwork_id].append(tag)
    return result


def inherited_tags_for(session: Session, artwork_ids: Sequence[str]) -> dict[str, list[Tag]]:
    """artwork id → the tags it carries through its live photos and not on its own, by name.

    An artwork's effective tags are its own plus these (docs/organization.md §1): read, never
    copied, so tagging a photo later tags every artwork made of it.
    """
    result: dict[str, list[Tag]] = {i: [] for i in artwork_ids}
    if not artwork_ids:
        return result
    own = set(
        session.execute(
            select(ArtworkTag.artwork_id, ArtworkTag.tag_id).where(
                ArtworkTag.artwork_id.in_(artwork_ids)
            )
        ).tuples()
    )
    rows = session.execute(
        select(ArtworkPhoto.artwork_id, Tag)
        .join(PhotoTag, PhotoTag.photo_id == ArtworkPhoto.photo_id)
        .join(Photo, Photo.id == ArtworkPhoto.photo_id)
        .join(Tag, Tag.id == PhotoTag.tag_id)
        .where(ArtworkPhoto.artwork_id.in_(artwork_ids), Photo.deleted_at.is_(None))
        .order_by(Tag.name)
    )
    seen: set[tuple[str, str]] = set()
    for artwork_id, tag in rows:
        key = (artwork_id, tag.id)
        if key in own or key in seen:
            continue
        seen.add(key)
        result[artwork_id].append(tag)
    return result


def _check_slot_count(recipe: Recipe, photo_count: int, name: str) -> None:
    """A layout holds exactly its recipe's cells; fewer photos leave placeholders, more is a 422."""
    if recipe.count < photo_count:
        raise ProblemError(
            422,
            "layout_slot_count",
            "Wrong number of photos for this layout",
            f"{name} holds {recipe.count} photo(s), {photo_count} given",
        )


# ---- create -------------------------------------------------------------------------------------
def _default_title(photo: Photo) -> str:
    if photo.place_name:
        return photo.place_name
    return PurePath(photo.original_filename).stem[:256]


def _composition_for(
    photo_count: int,
    requested: Mapping[str, Any] | None,
    defaults: templates.ArtworkDefaults | None = None,
) -> tuple[Recipe, Composition]:
    """The recipe and the block a new parametric artwork starts from (§7).

    Nothing requested ⇒ the Settings defaults when they fit the selection (a recipe holding that
    many photos), else the first catalogue entry for that many photos, `original` for a single
    photo (the whole photo in the mat, today's `fit_in_mat`) and `fill` above.
    """
    params = dict(requested or {})
    fallback = defaults or templates.ArtworkDefaults(style_id=templates.DEFAULT_STYLE_ID)
    preferred = recipes.find(fallback.recipe_id) if fallback.recipe_id else None
    recipe_id = params.pop("recipe", None)
    if recipe_id is None and preferred is not None and preferred.count == photo_count:
        recipe_id = preferred.id
    if params.get("format") is None and fallback.format is not None:
        params["format"] = fallback.format
    recipe = recipes.find(recipe_id) if recipe_id else recipes.for_count(photo_count)
    if recipe is None and recipe_id:
        raise ProblemError(422, "unknown_recipe", "Unknown composition", str(recipe_id))
    if recipe is None:
        raise ProblemError(
            422, "no_recipe", "No composition for this number of photos", str(photo_count)
        )
    if recipe.count != photo_count:
        raise ProblemError(
            422,
            "recipe_slot_count",
            "Wrong number of photos for this composition",
            f"{recipe.id} holds {recipe.count} photo(s), {photo_count} given",
        )
    params.setdefault("format", "original" if photo_count == 1 else "fill")
    try:
        return recipe, Composition(recipe=recipe.id, **params)
    except ValidationError as exc:
        raise invalid_document(
            [
                DocumentIssue(
                    ("composition", *e["loc"]), e["msg"].removeprefix("Value error, "), e["type"]
                )
                for e in exc.errors(include_url=False)
            ]
        ) from exc


def create_artwork(
    session: Session,
    photo_ids: Sequence[str],
    *,
    style_id: str | None = None,
    layout_id: str | None = None,
    title: str | None = None,
    composition: Mapping[str, Any] | None = None,
) -> Artwork:
    """New draft from photos (in slot order), a frame style and a composition or a layout.

    Every new artwork is parametric (docs/templates.md §4): a `layout_id` names a saved recipe +
    parameters and is recorded as the artwork's origin layout, while a bare `composition` (or
    nothing at all) starts from the catalogue and the Settings defaults. Hand-built documents are
    still reachable — the Advanced editor detaches the block (docs/simple-editor.md §5).

    The photos' pending upload metadata (favorite, collections) is applied once. The photos stay
    in the inbox until an artwork using them is marked ready (docs/organization.md §6).
    """
    if layout_id is not None and composition is not None:
        raise ProblemError(
            422, "layout_and_composition", "Pass a layout or a composition, not both"
        )
    photos = {
        p.id: p
        for p in session.scalars(
            select(Photo).where(Photo.id.in_(set(photo_ids)), Photo.deleted_at.is_(None))
        )
    }
    missing = [i for i in photo_ids if i not in photos]
    if missing:
        raise ProblemError(422, "unknown_photo", "Unknown photo", missing[0])
    defaults = templates.defaults(session)
    style_row, style = templates.get_style(session, style_id or defaults.style_id)
    inputs = [PhotoInput(i, Size(photos[i].width, photos[i].height)) for i in photo_ids]
    layout_row = None
    cells: list[PhotoInput | None] = list(inputs)
    if layout_id is None:
        recipe, block = _composition_for(len(photo_ids), composition, defaults)
    else:
        layout_row, layout = templates.get_layout(session, layout_id)
        recipe = templates.layout_recipe(layout)
        _check_slot_count(recipe, len(photo_ids), layout_row.name)
        block = layout.block()
        # fewer photos than cells is allowed: the empty ones are placeholders to fill later
        cells += [None] * (recipe.count - len(inputs))
    doc = build_composition_document(style, recipe, block, cells)
    check_references(session, doc)

    first = photos[photo_ids[0]] if photo_ids else None
    artwork = Artwork(
        title=(title if title is not None else (_default_title(first) if first else ""))[:256],
        origin_style_id=style_row.id,
        origin_style_revision=style_row.revision,
        origin_layout_id=layout_row.id if layout_row else None,
        origin_layout_revision=layout_row.revision if layout_row else None,
    )
    session.add(artwork)
    session.flush()
    store_document(session, artwork, doc)
    _apply_pending_meta(session, artwork, list(photos))
    # The photos stay in the inbox: they leave it when an artwork using them is marked ready
    # (`mark_ready`), so an abandoned draft never makes a photo disappear from the to-do list.
    return artwork


def _apply_pending_meta(session: Session, artwork: Artwork, photo_ids: list[str]) -> None:
    metas = list(
        session.scalars(select(PhotoPendingMeta).where(PhotoPendingMeta.photo_id.in_(photo_ids)))
    )
    collection_ids: list[str] = []
    for meta in metas:
        artwork.favorite = artwork.favorite or meta.favorite
        collection_ids.extend(str(c) for c in meta.collection_ids)
        session.delete(meta)
    if not collection_ids:
        return
    manual = session.scalars(
        select(Collection.id).where(
            Collection.id.in_(set(collection_ids)), Collection.kind == "manual"
        )
    )
    for collection_id in manual:
        position = session.scalar(
            select(func.coalesce(func.max(CollectionItem.position), 0.0)).where(
                CollectionItem.collection_id == collection_id
            )
        )
        session.add(
            CollectionItem(
                collection_id=collection_id,
                artwork_id=artwork.id,
                position=float(position or 0) + 1,
            )
        )


# ---- document saves -----------------------------------------------------------------------------
def save_document(
    session: Session, artwork_id: str, raw: Mapping[str, Any], expected_version: int
) -> Artwork:
    """Replace the document if `expected_version` is current (409 `version_conflict` otherwise)."""
    artwork = get_artwork(session, artwork_id)
    if artwork.document_version != expected_version:
        raise ProblemError(
            409,
            "version_conflict",
            "The artwork was modified elsewhere",
            extra={"current_version": artwork.document_version},
        )
    doc = validated(session, raw)
    store_document(session, artwork, doc)
    artwork.document_version += 1
    artwork.updated_at = utcnow()
    return artwork


# ---- templates ----------------------------------------------------------------------------------
def _recipe_of(doc: ArtworkDocument) -> Recipe | None:
    """The catalogue entry the document's block names, while it is attached."""
    block = doc.composition
    if block is None or block.detached:
        return None
    return recipes.find(block.recipe)


@dataclass(frozen=True, slots=True)
class TemplateApplication:
    """One artwork in a push update: what would happen, or what did (docs/templates.md §5)."""

    artwork_id: str
    title: str
    applied: bool
    reason: str | None = None
    """Why it was skipped: `slot_count` (the layout holds another number of photos) or
    `detached` (hand-placed slots a layout would overwrite)."""


def _apply_template_to(
    session: Session,
    artwork: Artwork,
    *,
    style: tuple[FrameStyle, template_docs.FrameStyleDocument] | None,
    layout: tuple[Layout, template_docs.LayoutDocument] | None,
    snapshot: bool,
) -> None:
    """Re-dress and/or re-lay out one artwork, in place, as a new document version."""
    doc = document_of(artwork)
    sizes = photo_sizes(session, doc.photo_ids())
    # Layout first, then the look: both own `composition.border` (the block writes `bands`, §3.7),
    # and when the user asks for a style *and* a layout the style is what they see.
    if layout is not None:
        layout_row, layout_doc = layout
        recipe = templates.layout_recipe(layout_doc)
        _check_slot_count(recipe, len(doc.slots), layout_row.name)
        caption = template_docs.caption_style(style[1]) if style is not None else None
        doc = template_docs.relayout(doc, layout_doc, recipe, sizes, caption)
    if style is not None:
        doc = template_docs.restyle(doc, style[1], _recipe_of(doc), sizes)
    if snapshot:
        create_snapshot(session, artwork.id, "pre_template_update")
    _check_references(doc, sizes)
    store_document(session, artwork, resolved(doc, sizes))
    artwork.document_version += 1
    artwork.updated_at = utcnow()
    if style is not None:
        artwork.origin_style_id, artwork.origin_style_revision = style[0].id, style[0].revision
    if layout is not None:
        artwork.origin_layout_id, artwork.origin_layout_revision = layout[0].id, layout[0].revision


def apply_template(
    session: Session, artwork_id: str, *, style_id: str | None, layout_id: str | None
) -> Artwork:
    """Apply a style and/or a layout to one artwork (copy on apply + origin, §5).

    Snapshotted as `pre_template_update`, so the artwork's history carries a way back.
    """
    if style_id is None and layout_id is None:
        raise ProblemError(422, "nothing_to_apply", "Pass a style, a layout, or both")
    artwork = get_artwork(session, artwork_id)
    _apply_template_to(
        session,
        artwork,
        style=templates.get_style(session, style_id) if style_id else None,
        layout=templates.get_layout(session, layout_id) if layout_id else None,
        snapshot=True,
    )
    return artwork


def push_template_update(
    session: Session, kind: templates.TemplateKind, template_id: str, *, dry_run: bool
) -> list[TemplateApplication]:
    """Push a changed template onto every artwork that came from it (§5).

    A layout only reaches artworks with the same number of photos, and never a detached one: its
    slots were placed by hand and re-solving would throw that away. Every touched artwork is
    snapshotted first (`pre_template_update`), which is what makes the whole operation undoable.
    """
    style = templates.get_style(session, template_id) if kind == "frame_style" else None
    layout = templates.get_layout(session, template_id) if kind == "layout" else None
    recipe = templates.layout_recipe(layout[1]) if layout else None
    results: list[TemplateApplication] = []
    for artwork in templates.users_of(session, kind, template_id):
        doc = document_of(artwork)
        block = doc.composition
        reason: str | None = None
        if recipe is not None and recipe.count != len(doc.slots):
            reason = "slot_count"
        elif layout is not None and (block is None or block.detached):
            reason = "detached"
        results.append(
            TemplateApplication(artwork.id, artwork.title, applied=reason is None, reason=reason)
        )
        if reason is None and not dry_run:
            _apply_template_to(session, artwork, style=style, layout=layout, snapshot=True)
    return results


def style_from_artwork(session: Session, artwork_id: str, name: str) -> FrameStyle:
    """ "Save as style": the artwork's look becomes a reusable template (§3)."""
    doc = document_of(get_artwork(session, artwork_id))
    document = template_docs.style_of_document(doc).model_dump(mode="json")
    return templates.create_style(session, name, document)


def layout_from_artwork(session: Session, artwork_id: str, name: str) -> Layout:
    """ "Save as layout": the artwork's recipe and parameters become a template (§3)."""
    doc = document_of(get_artwork(session, artwork_id))
    layout = template_docs.layout_of_document(doc)
    if layout is None:
        raise ProblemError(
            422,
            "artwork_detached",
            "This artwork has no layout to save",
            "Its slots were placed by hand; re-apply a layout first",
        )
    return templates.create_layout(session, name, layout.model_dump(mode="json"))


def update_artwork(
    session: Session,
    artwork_id: str,
    *,
    title: str | None = None,
    favorite: bool | None = None,
    status: str | None = None,
    tag_ids: Sequence[str] | None = None,
    origin_style_id: str | None = None,
    origin_layout_id: str | None = None,
) -> Artwork:
    artwork = get_artwork(session, artwork_id)
    if origin_style_id is not None:
        style, _ = templates.get_style(session, origin_style_id)
        artwork.origin_style_id, artwork.origin_style_revision = style.id, style.revision
    if origin_layout_id is not None:
        layout, _ = templates.get_layout(session, origin_layout_id)
        artwork.origin_layout_id, artwork.origin_layout_revision = layout.id, layout.revision
    if title is not None:
        artwork.title = title.strip()[:256]
    if favorite is not None:
        artwork.favorite = favorite
    if status == "ready":
        mark_ready(session, artwork_id)
    elif status == "draft":
        artwork.status = "draft"
    elif status is not None:
        raise ProblemError(422, "invalid_status", "Invalid status")
    if tag_ids is not None:
        unique = list(dict.fromkeys(tag_ids))
        known = set(session.scalars(select(Tag.id).where(Tag.id.in_(unique))))
        if len(known) != len(unique):
            raise ProblemError(422, "unknown_tag", "Unknown tag")
        before = set(
            session.scalars(select(ArtworkTag.tag_id).where(ArtworkTag.artwork_id == artwork.id))
        )
        session.execute(delete(ArtworkTag).where(ArtworkTag.artwork_id == artwork.id))
        session.add_all(ArtworkTag(artwork_id=artwork.id, tag_id=t) for t in unique)
        tags_service.touch(session, [t for t in unique if t not in before])
    artwork.updated_at = utcnow()
    session.flush()
    search.index_artwork(session, artwork)
    return artwork


def mark_ready(session: Session, artwork_id: str) -> Artwork:
    """Explicit validation: a complete, valid document becomes `ready` — *done*.

    Its photos leave the inbox here, and only here (docs/organization.md §6): creating a draft
    keeps them in it, and nothing ever puts them back — not going back to draft, not trashing the
    artwork. A dismissed photo stays dismissed.
    """
    artwork = get_artwork(session, artwork_id)
    doc = document_of(artwork)
    check_references(session, doc)
    if doc.quality().is_incomplete:
        raise ProblemError(422, "artwork_incomplete", "The artwork has empty slots")
    artwork.status = "ready"
    artwork.updated_at = utcnow()
    photo_ids = doc.photo_ids()
    if photo_ids:
        for photo in session.scalars(
            select(Photo).where(Photo.id.in_(set(photo_ids)), Photo.inbox_state == "inbox")
        ):
            photo.inbox_state = "processed"
    return artwork


def duplicate_artwork(session: Session, artwork_id: str) -> Artwork:
    source = get_artwork(session, artwork_id)
    copy = Artwork(
        title=source.title,
        status="draft",
        origin_style_id=source.origin_style_id,
        origin_style_revision=source.origin_style_revision,
        origin_layout_id=source.origin_layout_id,
        origin_layout_revision=source.origin_layout_revision,
    )
    session.add(copy)
    session.flush()
    store_document(session, copy, document_of(source))
    tag_ids = session.scalars(select(ArtworkTag.tag_id).where(ArtworkTag.artwork_id == source.id))
    session.add_all(ArtworkTag(artwork_id=copy.id, tag_id=t) for t in tag_ids)
    return copy


def trash_artwork(session: Session, artwork_id: str) -> Artwork:
    """Soft delete: `services/trash.py` restores it (same batch) or purges it after 30 days."""
    from the_frame_v2.services import trash

    artwork = get_artwork(session, artwork_id)
    trash.trash_artworks(session, [artwork.id])
    return artwork


# ---- snapshots ----------------------------------------------------------------------------------
def create_snapshot(session: Session, artwork_id: str, reason: str) -> ArtworkSnapshot:
    if reason not in SNAPSHOT_REASONS:
        raise ProblemError(422, "invalid_reason", "Invalid snapshot reason")
    artwork = get_artwork(session, artwork_id)
    snapshot = ArtworkSnapshot(
        artwork_id=artwork.id,
        document=artwork.document,
        document_version=artwork.document_version,
        reason=reason,
    )
    session.add(snapshot)
    session.flush()
    stale = session.scalars(
        select(ArtworkSnapshot.id)
        .where(ArtworkSnapshot.artwork_id == artwork.id)
        .order_by(ArtworkSnapshot.created_at.desc(), ArtworkSnapshot.id.desc())
        .offset(MAX_SNAPSHOTS)
    ).all()
    if stale:
        session.execute(delete(ArtworkSnapshot).where(ArtworkSnapshot.id.in_(stale)))
    return snapshot


def list_snapshots(session: Session, artwork_id: str) -> list[ArtworkSnapshot]:
    get_artwork(session, artwork_id)
    return list(
        session.scalars(
            select(ArtworkSnapshot)
            .where(ArtworkSnapshot.artwork_id == artwork_id)
            .order_by(ArtworkSnapshot.created_at.desc(), ArtworkSnapshot.id.desc())
        )
    )


def restore_snapshot(session: Session, artwork_id: str, snapshot_id: str) -> Artwork:
    """Restore a snapshot as a new document version (the current one is snapshotted first)."""
    artwork = get_artwork(session, artwork_id)
    snapshot = session.get(ArtworkSnapshot, snapshot_id)
    if snapshot is None or snapshot.artwork_id != artwork.id:
        raise not_found("Snapshot")
    document = dict(snapshot.document)
    create_snapshot(session, artwork_id, "pre_restore")
    return save_document(session, artwork_id, document, artwork.document_version)


# ---- listing ------------------------------------------------------------------------------------
# Listing lives in `services/library.py`: it is one filter AST away from smart collections, and
# only that module knows how a filter reaches the schema (docs/organization.md §4).
