"""Archive import, second half: the policies and the transaction that writes the library.

Spec: `docs/archive-format.md` §12.2 steps 3 and 4. `services/archive_import.py` has already
validated the archive and reported what would happen; this module is what happens.

Every reference in an archive travels through one set of id maps (`IdMaps`): a photo matched by
SHA-256, a tag merged by name and a `keep_both` copy under a fresh id all mean that the ids inside
an artwork document, a collection's parent, a smart collection's filter and every link row have to
be rewritten. Writing rows as they were read would make that impossible, so the passes run in
reference order and each one fills the map the next ones read.

Order: tag categories → tags → photos → templates → swatches → artworks → collections → links →
settings. Originals
are copied to their content-addressed path before the rows that name them (invariant 1); an artwork
that is overwritten is snapshotted `pre_import` first, and that snapshot *is* the undo.
"""

from __future__ import annotations

import logging
import shutil
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from the_frame_v2.context import AppContext
from the_frame_v2.db.models import (
    Artwork,
    ArtworkTag,
    Collection,
    CollectionItem,
    FrameStyle,
    Layout,
    Photo,
    PhotoTag,
    Setting,
    Swatch,
    Tag,
    TagCategory,
)
from the_frame_v2.domain import archive
from the_frame_v2.errors import ProblemError
from the_frame_v2.events import Event
from the_frame_v2.ids import new_id, utcnow
from the_frame_v2.services import artworks as artworks_service
from the_frame_v2.services import render, search
from the_frame_v2.services.archive_import import (
    IdMaps,
    StagedArchive,
    artwork_values,
    collection_values,
    photos_by_sha,
    problem_of,
    read_archive,
    remapped_document,
    remapped_filter,
    row_of,
    set_failed,
    tag_category,
)

log = logging.getLogger(__name__)


# ---- policies ----------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Policies:
    """Per-kind defaults plus per-item overrides keyed `"<kind>:<identity>"` (§12.2 step 3)."""

    default: archive.Policy = "keep_mine"
    per_kind: Mapping[str, archive.Policy] = field(default_factory=dict)
    per_item: Mapping[str, archive.Policy] = field(default_factory=dict)

    def for_entry(self, kind: str, key: str) -> archive.Policy:
        override = self.per_item.get(f"{kind}:{key}")
        return override or self.per_kind.get(kind) or self.default


@dataclass(slots=True)
class ApplyResult:
    created: dict[str, int] = field(default_factory=dict)
    updated: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    renders_adopted: int = 0
    renders_queued: int = 0
    warnings: list[str] = field(default_factory=list)

    def bump(self, bucket: dict[str, int], kind: str) -> None:
        bucket[kind] = bucket.get(kind, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "renders_adopted": self.renders_adopted,
            "renders_queued": self.renders_queued,
            "warnings": self.warnings,
        }


# ---- apply -------------------------------------------------------------------------------------
def apply_import(ctx: AppContext, import_id: str, policies: Policies) -> ApplyResult:
    """Write the archive into the library. One transaction; originals land on disk first."""
    with ctx.db.session() as session:
        row = row_of(session, import_id)
        if row.state == "applied":
            raise ProblemError(409, "import_already_applied", "This import was already applied")
        if row.state not in {"ready", "failed"}:
            raise ProblemError(409, "import_not_ready", "This import is not ready", row.state)
        row.state = "applying"
        import_id = row.id  # the staging path is named by the row, never by the caller's string
    try:
        staged = read_archive(
            ctx.storage.import_archive_path(import_id), max_bytes=ctx.settings.max_archive_bytes
        )
    except archive.ArchiveError as exc:
        set_failed(ctx, import_id, exc.code)
        raise problem_of(exc) from exc
    result = ApplyResult()
    maps = IdMaps()
    written = _Written()
    try:
        with ctx.db.session() as session:
            _apply_tag_categories(session, staged, policies, maps, result)
            _apply_tags(session, staged, policies, maps, result)
            _apply_photos(ctx, session, staged, policies, maps, result)
            _apply_templates(session, staged, policies, maps, result)
            _apply_swatches(session, staged, policies, maps, result)
            written = _apply_artworks(session, staged, policies, maps, result)
            _apply_collections(session, staged, policies, maps, result)
            _apply_collection_items(session, staged, maps, result)
            _apply_tag_links(session, staged, maps, result)
            _apply_settings(session, staged, policies, maps, result)
    except BaseException:
        set_failed(ctx, import_id, "apply_failed")
        raise
    _finish_renders(ctx, staged, written, result)
    with ctx.db.session() as session:
        row = row_of(session, import_id)
        row.state = "applied"
        row.error = None
    ctx.broker.publish(Event("import.applied", {"import_id": import_id} | result.as_dict()))
    return result


def _apply_tag_categories(
    session: Session,
    staged: StagedArchive,
    policies: Policies,
    maps: IdMaps,
    result: ApplyResult,
) -> None:
    """Categories are matched like tags — by name — and written before the tags that name them."""
    entity = archive.TAG_CATEGORIES
    by_name = {row.name.casefold(): row for row in session.scalars(select(TagCategory))}
    for record in staged.rows(entity.kind):
        assert isinstance(record, archive.TagCategoryRecord)
        match = by_name.get(record.name.casefold())
        if match is not None:  # the same name is the same category: merge, never duplicate
            maps.put(entity.kind, record.id, match.id)
            result.bump(result.skipped, entity.kind)
            continue
        existing = session.get(TagCategory, record.id)
        if existing is None:
            category = TagCategory(
                id=record.id,
                name=record.name,
                color=record.color,
                position=record.position,
                created_at=record.created_at,
            )
            session.add(category)
            by_name[record.name.casefold()] = category
            maps.put(entity.kind, record.id, record.id)
            result.bump(result.created, entity.kind)
            continue
        # Same id, another name: the policy decides.
        policy = policies.for_entry(entity.kind, record.id)
        if policy == "take_theirs":
            existing.name, existing.color = record.name, record.color
            by_name[record.name.casefold()] = existing
            maps.put(entity.kind, record.id, existing.id)
            result.bump(result.updated, entity.kind)
        elif policy == "keep_both":
            name = _unique_name(archive.imported_name(record.name), by_name)
            category = TagCategory(
                id=new_id(),
                name=name,
                color=record.color,
                position=record.position,
                created_at=record.created_at,
            )
            session.add(category)
            by_name[name.casefold()] = category
            maps.put(entity.kind, record.id, category.id)
            result.bump(result.created, entity.kind)
        else:
            maps.put(entity.kind, record.id, existing.id)
            result.bump(result.skipped, entity.kind)
    session.flush()


def _apply_tags(
    session: Session,
    staged: StagedArchive,
    policies: Policies,
    maps: IdMaps,
    result: ApplyResult,
) -> None:
    entity = archive.TAGS
    by_name = {row.name.casefold(): row for row in session.scalars(select(Tag))}
    for record in staged.rows(entity.kind):
        assert isinstance(record, archive.TagRecord)
        category_id = tag_category(session, record, maps)
        match = by_name.get(record.name.casefold())
        if match is not None:  # a tag is its name: merge rather than duplicate (and keep ours —
            # its category included: the report called it `matched`, i.e. nothing is written)
            maps.put(entity.kind, record.id, match.id)
            result.bump(result.skipped, entity.kind)
            continue
        existing = session.get(Tag, record.id)
        if existing is None:
            tag = Tag(
                id=record.id,
                name=record.name,
                color=record.color,
                category_id=category_id,
                created_at=record.created_at,
            )
            session.add(tag)
            by_name[record.name.casefold()] = tag
            maps.put(entity.kind, record.id, record.id)
            result.bump(result.created, entity.kind)
            continue
        # Same id, another name (the name match above already failed): a genuine conflict.
        policy = policies.for_entry(entity.kind, record.id)
        if policy == "take_theirs":
            existing.name, existing.color = record.name, record.color
            existing.category_id = category_id
            by_name[record.name.casefold()] = existing
            maps.put(entity.kind, record.id, existing.id)
            result.bump(result.updated, entity.kind)
        elif policy == "keep_both":
            name = _unique_name(archive.imported_name(record.name), by_name)
            tag = Tag(
                id=new_id(),
                name=name,
                color=record.color,
                category_id=category_id,
                created_at=record.created_at,
            )
            session.add(tag)
            by_name[name.casefold()] = tag
            maps.put(entity.kind, record.id, tag.id)
            result.bump(result.created, entity.kind)
        else:
            maps.put(entity.kind, record.id, existing.id)
            result.bump(result.skipped, entity.kind)
    session.flush()


def _unique_name(base: str, taken: Mapping[str, Any]) -> str:
    if base.casefold() not in taken:
        return base
    for n in range(2, 1000):
        candidate = f"{base} {n}"
        if candidate.casefold() not in taken:
            return candidate
    return f"{base} {new_id()[:8]}"


def _apply_photos(
    ctx: AppContext,
    session: Session,
    staged: StagedArchive,
    policies: Policies,
    maps: IdMaps,
    result: ApplyResult,
) -> None:
    entity = archive.PHOTOS
    by_sha = photos_by_sha(session)
    for record in staged.rows(entity.kind):
        assert isinstance(record, archive.PhotoRecord)
        match = by_sha.get(record.sha256)
        if match is not None:
            maps.put(entity.kind, record.id, match.id)
            if match.deleted_at is not None and record.deleted_at is None:
                # "Trashed local photo ⇒ restore" (§12.2): re-receiving a photo brings it back.
                match.deleted_at, match.trash_batch_id = None, None
                search.index_photo(session, match)
                result.bump(result.updated, entity.kind)
            else:
                result.bump(result.skipped, entity.kind)
            continue
        existing = session.get(Photo, record.id)
        photo_id = record.id
        if existing is not None:
            # Same id, other bytes. `take_theirs` would mean "this photo is now another image",
            # which content-addressed originals cannot express: it behaves as `keep_both`.
            policy = policies.for_entry(entity.kind, record.id)
            if policy == "keep_mine":
                maps.put(entity.kind, record.id, existing.id)
                result.bump(result.skipped, entity.kind)
                continue
            photo_id = new_id()
        _copy_original(ctx, staged, record)
        photo = Photo(
            **record.model_dump(exclude={"id"}),
            id=photo_id,
        )
        session.add(photo)
        session.flush()
        search.index_photo(session, photo)
        by_sha[record.sha256] = photo
        maps.put(entity.kind, record.id, photo_id)
        result.bump(result.created, entity.kind)
    session.flush()


def _copy_original(ctx: AppContext, staged: StagedArchive, record: archive.PhotoRecord) -> None:
    """Idempotent by hash: the same bytes always land on the same path (invariant 1)."""
    target = ctx.storage.original_path(record.sha256, record.ext)
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.part")
    member = staged.originals[record.sha256]
    with zipfile.ZipFile(staged.path) as zf, zf.open(member) as src, tmp.open("wb") as dst:
        shutil.copyfileobj(src, dst, 1024 * 1024)
    tmp.replace(target)


def _apply_templates(
    session: Session,
    staged: StagedArchive,
    policies: Policies,
    maps: IdMaps,
    result: ApplyResult,
) -> None:
    kinds: tuple[tuple[archive.Entity, Any], ...] = (
        (archive.FRAME_STYLES, FrameStyle),
        (archive.LAYOUTS, Layout),
    )
    for entity, model in kinds:
        names = {row.name.casefold(): row for row in session.scalars(select(model))}
        for record in staged.rows(entity.kind):
            existing = session.get(model, record.id)
            values = record.model_dump(exclude={"id"})
            if existing is None:
                session.add(model(id=record.id, builtin=False, **values))
                maps.put(entity.kind, record.id, record.id)
                result.bump(result.created, entity.kind)
                continue
            if existing.builtin:
                maps.put(entity.kind, record.id, existing.id)
                result.bump(result.skipped, entity.kind)
                continue
            mine = archive.comparable(entity, entity.model.model_validate(existing))
            if mine == archive.comparable(entity, record):
                maps.put(entity.kind, record.id, existing.id)
                result.bump(result.skipped, entity.kind)
                continue
            policy = policies.for_entry(entity.kind, record.id)
            if policy == "take_theirs":
                for key, value in values.items():
                    setattr(existing, key, value)
                existing.revision += 1  # a changed document is a new revision (outdated badge)
                maps.put(entity.kind, record.id, existing.id)
                result.bump(result.updated, entity.kind)
            elif policy == "keep_both":
                name = _unique_name(archive.imported_name(record.name), names)
                copy = model(id=new_id(), builtin=False, **{**values, "name": name})
                session.add(copy)
                names[name.casefold()] = copy
                maps.put(entity.kind, record.id, copy.id)
                result.bump(result.created, entity.kind)
            else:
                maps.put(entity.kind, record.id, existing.id)
                result.bump(result.skipped, entity.kind)
        session.flush()


def _apply_swatches(
    session: Session,
    staged: StagedArchive,
    policies: Policies,
    maps: IdMaps,
    result: ApplyResult,
) -> None:
    entity = archive.SWATCHES
    for record in staged.rows(entity.kind):
        assert isinstance(record, archive.SwatchRecord)
        existing = session.get(Swatch, record.id)
        values = record.model_dump(exclude={"id"})
        if existing is None:
            session.add(Swatch(id=record.id, **values))
            maps.put(entity.kind, record.id, record.id)
            result.bump(result.created, entity.kind)
            continue
        if archive.comparable(entity, entity.model.model_validate(existing)) == archive.comparable(
            entity, record
        ):
            maps.put(entity.kind, record.id, existing.id)
            result.bump(result.skipped, entity.kind)
            continue
        policy = policies.for_entry(entity.kind, record.id)
        if policy == "take_theirs":
            for key, value in values.items():
                setattr(existing, key, value)
            maps.put(entity.kind, record.id, existing.id)
            result.bump(result.updated, entity.kind)
        elif policy == "keep_both":
            copy = Swatch(id=new_id(), **{**values, "name": archive.imported_name(record.name)})
            session.add(copy)
            maps.put(entity.kind, record.id, copy.id)
            result.bump(result.created, entity.kind)
        else:
            maps.put(entity.kind, record.id, existing.id)
            result.bump(result.skipped, entity.kind)
    session.flush()


@dataclass(slots=True)
class _Written:
    """What the artwork pass produced: the rows written, and the renders worth adopting."""

    ids: list[str] = field(default_factory=list)
    adopt: dict[str, str] = field(default_factory=dict)


def _apply_artworks(
    session: Session,
    staged: StagedArchive,
    policies: Policies,
    maps: IdMaps,
    result: ApplyResult,
) -> _Written:
    """Write the artworks, noting the ones whose archived render can be adopted as-is.

    The comparison runs on the **translated** record: the same artwork in two libraries names the
    same photo under two ids, so comparing the raw document would call every re-import a conflict.
    """
    entity = archive.ARTWORKS
    written = _Written()
    reusable = staged.manifest.render_key == render.render_key()
    for record in staged.rows(entity.kind):
        assert isinstance(record, archive.ArtworkRecord)
        existing = session.get(Artwork, record.id)
        target_id = record.id
        doc, warnings = remapped_document(staged, record, maps)
        values = artwork_values(session, record, maps)
        translated = record.model_copy(update={**values, "document": doc.canonical()})
        if existing is not None:
            mine = archive.comparable(entity, entity.model.model_validate(existing))
            if mine == archive.comparable(entity, translated):
                maps.put(entity.kind, record.id, existing.id)
                result.bump(result.skipped, entity.kind)
                continue
            policy = policies.for_entry(entity.kind, record.id)
            if policy == "keep_mine":
                maps.put(entity.kind, record.id, existing.id)
                result.bump(result.skipped, entity.kind)
                continue
            if policy == "keep_both":
                target_id = new_id()
                existing = None
            else:  # take_theirs: the snapshot *is* the undo (docs/archive-format.md §12.2)
                artworks_service.create_snapshot(session, existing.id, "pre_import")
        result.warnings.extend(warnings)
        if target_id != record.id:
            values["title"] = archive.imported_name(record.title)
        if existing is None:
            artwork = Artwork(id=target_id, **values)
            session.add(artwork)
            result.bump(result.created, entity.kind)
        else:
            artwork = existing
            for key, value in values.items():
                setattr(artwork, key, value)
            artwork.document_version = max(artwork.document_version, record.document_version) + 1
            result.bump(result.updated, entity.kind)
        session.flush()
        artworks_service.store_document(session, artwork, doc)
        artwork.render_hash, artwork.rendered_at = None, None
        maps.put(entity.kind, record.id, artwork.id)
        written.ids.append(artwork.id)
        member = staged.renders.get(record.id)
        if member is not None and reusable:
            written.adopt[artwork.id] = member
    session.flush()
    return written


def _apply_collections(
    session: Session,
    staged: StagedArchive,
    policies: Policies,
    maps: IdMaps,
    result: ApplyResult,
) -> None:
    """Parents before children, so a re-parented or renamed collection keeps its tree."""
    entity = archive.COLLECTIONS
    records = [r for r in staged.rows(entity.kind) if isinstance(r, archive.CollectionRecord)]
    names = {row.name.casefold(): row for row in session.scalars(select(Collection))}
    wrote: dict[str, str] = {}
    for record in _parents_first(records):
        existing = session.get(Collection, record.id)
        target_id = record.id
        values = collection_values(session, record, maps)
        translated = record.model_copy(update=values)
        if existing is not None:
            mine = archive.comparable(entity, entity.model.model_validate(existing))
            if mine == archive.comparable(entity, translated):
                maps.put(entity.kind, record.id, existing.id)
                result.bump(result.skipped, entity.kind)
                continue
            policy = policies.for_entry(entity.kind, record.id)
            if policy == "keep_mine":
                maps.put(entity.kind, record.id, existing.id)
                result.bump(result.skipped, entity.kind)
                continue
            if policy == "keep_both":
                target_id = new_id()
                values["name"] = _unique_name(archive.imported_name(record.name), names)
                existing = None
            else:
                for key, value in values.items():
                    setattr(existing, key, value)
                maps.put(entity.kind, record.id, existing.id)
                names[existing.name.casefold()] = existing
                search.index_collection(session, existing)
                wrote[record.id] = existing.id
                result.bump(result.updated, entity.kind)
                continue
        collection = Collection(id=target_id, **values)
        session.add(collection)
        session.flush()
        search.index_collection(session, collection)
        names[collection.name.casefold()] = collection
        maps.put(entity.kind, record.id, collection.id)
        wrote[record.id] = collection.id
        result.bump(result.created, entity.kind)
    _fix_filters(session, staged, maps, wrote)
    session.flush()


def _parents_first(records: Sequence[archive.CollectionRecord]) -> list[archive.CollectionRecord]:
    by_id = {record.id: record for record in records}
    ordered: list[archive.CollectionRecord] = []
    seen: set[str] = set()

    def visit(record: archive.CollectionRecord, guard: frozenset[str]) -> None:
        if record.id in seen or record.id in guard:
            return
        parent = by_id.get(record.parent_id or "")
        if parent is not None:
            visit(parent, guard | {record.id})
        seen.add(record.id)
        ordered.append(record)

    for record in records:
        visit(record, frozenset())
    return ordered


def _fix_filters(
    session: Session, staged: StagedArchive, maps: IdMaps, wrote: Mapping[str, str]
) -> None:
    """Second pass over the filters we wrote, now that every collection id is known.

    Only the rows this import wrote are touched: a collection the user kept is none of the
    archive's business, filter included.
    """
    for record in staged.rows(archive.COLLECTIONS.kind):
        assert isinstance(record, archive.CollectionRecord)
        local_id = wrote.get(record.id)
        if local_id is None or record.kind != "smart" or not record.filter:
            continue
        row = session.get(Collection, local_id)
        if row is not None:
            row.filter = remapped_filter(record, maps)


def _apply_collection_items(
    session: Session, staged: StagedArchive, maps: IdMaps, result: ApplyResult
) -> None:
    entity = archive.COLLECTION_ITEMS
    for record in staged.rows(entity.kind):
        assert isinstance(record, archive.CollectionItemRecord)
        collection_id = maps.get(archive.COLLECTIONS.kind, record.collection_id)
        artwork_id = maps.get(archive.ARTWORKS.kind, record.artwork_id)
        if not collection_id or not artwork_id:
            result.bump(result.skipped, entity.kind)
            continue
        collection = session.get(Collection, collection_id)
        if collection is None or collection.kind != "manual":
            result.bump(result.skipped, entity.kind)
            continue
        existing = session.get(CollectionItem, (collection_id, artwork_id))
        if existing is not None:
            result.bump(result.skipped, entity.kind)
            continue
        session.add(
            CollectionItem(
                collection_id=collection_id, artwork_id=artwork_id, position=record.position
            )
        )
        result.bump(result.created, entity.kind)
    session.flush()


def _apply_tag_links(
    session: Session, staged: StagedArchive, maps: IdMaps, result: ApplyResult
) -> None:
    for entity, model, owner_field, owner_kind in (
        (archive.ARTWORK_TAGS, ArtworkTag, "artwork_id", archive.ARTWORKS.kind),
        (archive.PHOTO_TAGS, PhotoTag, "photo_id", archive.PHOTOS.kind),
    ):
        touched: set[str] = set()
        for record in staged.rows(entity.kind):
            owner = maps.get(owner_kind, getattr(record, owner_field))
            tag_id = maps.get(archive.TAGS.kind, record.tag_id)
            if not owner or not tag_id:
                result.bump(result.skipped, entity.kind)
                continue
            if session.get(model, (owner, tag_id)) is not None:
                result.bump(result.skipped, entity.kind)
                continue
            session.add(model(**{owner_field: owner, "tag_id": tag_id}))
            touched.add(owner)
            result.bump(result.created, entity.kind)
        session.flush()
        for owner in touched:  # tag names are searchable: the index is written in this transaction
            if owner_kind == archive.ARTWORKS.kind:
                artwork = session.get(Artwork, owner)
                if artwork is not None:
                    search.index_artwork(session, artwork)
            else:
                photo = session.get(Photo, owner)
                if photo is not None:
                    search.index_photo(session, photo)
        if owner_kind == archive.PHOTOS.kind:
            # An artwork carries its photos' tags: the ones made of these photos re-index too.
            search.index_artworks_using(session, touched)


def _apply_settings(
    session: Session,
    staged: StagedArchive,
    policies: Policies,
    maps: IdMaps,
    result: ApplyResult,
) -> None:
    for key, value in staged.settings.items():
        remapped = _remapped_setting(session, key, value, maps)
        row = session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=remapped))
            result.bump(result.created, "setting")
            continue
        if row.value == remapped:
            result.bump(result.skipped, "setting")
            continue
        if policies.for_entry("setting", key) == "keep_mine":
            result.bump(result.skipped, "setting")
            continue
        row.value = remapped
        result.bump(result.updated, "setting")


def _remapped_setting(session: Session, key: str, value: Any, maps: IdMaps) -> Any:
    """`artwork_defaults` names a frame style: follow the same remap as everything else."""
    if key != "artwork_defaults" or not isinstance(value, dict):
        return value
    style_id = value.get("style_id")
    if not isinstance(style_id, str):
        return value
    mapped = maps.get(archive.FRAME_STYLES.kind, style_id) or style_id
    if session.get(FrameStyle, mapped) is None:
        return {k: v for k, v in value.items() if k != "style_id"}
    return {**value, "style_id": mapped}


def _finish_renders(
    ctx: AppContext, staged: StagedArchive, written: _Written, result: ApplyResult
) -> None:
    """Put the archive's renders straight into the cache, and queue a render for the rest.

    An adopted render is only sound when the same renderer and the same assets produced it — the
    render hash is a function of both (`services/render.render_hash`), so the manifest carries
    them and a mismatch simply means re-rendering.
    """
    for artwork_id, member in written.adopt.items():
        try:
            inputs = render.artwork_inputs(ctx, artwork_id)
        except ProblemError:
            continue
        target = ctx.storage.render_path(artwork_id, inputs.hash, "png")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.part")
        with zipfile.ZipFile(staged.path) as zf, zf.open(member) as src, tmp.open("wb") as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
        tmp.replace(target)
        with ctx.db.session() as session:
            artwork = session.get(Artwork, artwork_id)
            if artwork is not None:
                artwork.render_hash, artwork.rendered_at = inputs.hash, utcnow()
        result.renders_adopted += 1
    with ctx.db.session() as session:
        pending = list(
            session.scalars(
                select(Artwork.id).where(
                    Artwork.id.in_(written.ids or {""}),
                    Artwork.render_hash.is_(None),
                    Artwork.deleted_at.is_(None),
                )
            )
        )
    for artwork_id in pending:
        render.enqueue_render(ctx, artwork_id)
    result.renders_queued = len(pending)
