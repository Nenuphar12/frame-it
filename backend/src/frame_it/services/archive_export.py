"""Archive writer: `.tfarchive` files and rendered-image ZIPs.

Spec: `docs/archive-format.md` §12.1 / §12.3. The record models and the file layout live in
`domain/archive.py`; this module is the half that reads the library and streams bytes.

Two shapes of export:

- **library** (`full` / `partial`) → a `.tfarchive`: JSONL rows, the originals they reference and,
  optionally, the rendered PNG of every artwork. Originals are stored uncompressed (they are
  already compressed formats) and everything is listed in `checksums.sha256`.
- **renders** → a plain ZIP of finished images laid out by collection
  (`<Collection>/<Sub>/<title>.<jpg|png>`), the shape you copy onto a USB stick for the TV.

Both run as a job in the `ingest` lane and write into `exports/<job_id>/`; the API then streams the
single file that directory holds (`GET /exports/{job_id}/download`). Nothing here mutates the
library — except a renders export, which renders what has never been rendered.
"""

from __future__ import annotations

import hashlib
import json
import logging
import zipfile
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from frame_it import __version__
from frame_it.context import AppContext
from frame_it.db.models import (
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
from frame_it.domain import archive
from frame_it.domain.document import SCHEMA_VERSION
from frame_it.errors import ProblemError, not_found
from frame_it.events import Event
from frame_it.ids import utcnow
from frame_it.jobs.queue import JobContext, JobHandler, PermanentJobError
from frame_it.services import archive_import, library, render
from frame_it.services import collections as collections_service

log = logging.getLogger(__name__)

EXPORT_JOB = "archive.export"
SWEEP_JOB = "archive.sweep"
SWEEP_INTERVAL_SECONDS = 6 * 3600
ExportKind = Literal["library", "renders"]
RenderFormat = Literal["png", "jpg"]
UNSORTED = "Unsorted"
_MAX_NAME = 80


@dataclass(frozen=True, slots=True)
class ExportOptions:
    """What to export. An empty selection means the whole library (`scope = full`)."""

    kind: ExportKind = "library"
    artwork_ids: tuple[str, ...] = ()
    collection_ids: tuple[str, ...] = ()
    include_nested: bool = True
    """Whether a selected collection drags its subtree along."""
    include_renders: bool = False
    include_templates: bool = True
    render_format: RenderFormat = "jpg"

    @property
    def scope(self) -> archive.Scope:
        return "partial" if self.artwork_ids or self.collection_ids else "full"


@dataclass(slots=True)
class Selection:
    """The ids each JSONL file will hold, resolved once before anything is written."""

    scope: archive.Scope
    artworks: list[Artwork] = field(default_factory=list)
    photos: list[Photo] = field(default_factory=list)
    tag_categories: list[TagCategory] = field(default_factory=list)
    tags: list[Any] = field(default_factory=list)
    frame_styles: list[FrameStyle] = field(default_factory=list)
    layouts: list[Layout] = field(default_factory=list)
    swatches: list[Swatch] = field(default_factory=list)
    collections: list[Collection] = field(default_factory=list)
    collection_items: list[CollectionItem] = field(default_factory=list)
    artwork_tags: list[ArtworkTag] = field(default_factory=list)
    photo_tags: list[PhotoTag] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExportResult:
    path: Path
    scope: archive.Scope
    counts: dict[str, int]
    bytes_written: int
    warnings: tuple[str, ...] = ()


# ---- selection ---------------------------------------------------------------------------------
def _scoped_artwork_ids(session: Session, options: ExportOptions) -> set[str]:
    """Artworks named outright plus the members of the chosen collections (smart ones included)."""
    ids = set(options.artwork_ids)
    for collection_id in options.collection_ids:
        collection = collections_service.get_collection(session, collection_id)
        family = (
            collections_service.subtree_ids(session, collection_id)
            if options.include_nested
            else [collection.id]
        )
        for member in family:
            row = session.get(Collection, member)
            if row is None:
                continue
            if row.kind == "smart":
                ids |= library.smart_members(session, row)
            else:
                ids |= set(
                    session.scalars(
                        select(CollectionItem.artwork_id).where(
                            CollectionItem.collection_id == member
                        )
                    )
                )
    if ids:
        known = set(session.scalars(select(Artwork.id).where(Artwork.id.in_(ids))))
        missing = ids - known
        if missing:
            raise ProblemError(
                422, "unknown_artwork", "Unknown artwork in the selection", sorted(missing)[0]
            )
    return ids


def _collection_records(
    session: Session, options: ExportOptions, artwork_ids: set[str]
) -> tuple[list[Collection], list[CollectionItem]]:
    """The selected collections' subtree; a parent left out becomes a root on import (§12.1)."""
    if options.scope == "full":
        rows = collections_service.list_collections(session)
    else:
        wanted: set[str] = set()
        for collection_id in options.collection_ids:
            wanted |= set(collections_service.subtree_ids(session, collection_id))
        rows = [c for c in collections_service.list_collections(session) if c.id in wanted]
    kept = {c.id for c in rows}
    items = [
        item
        for item in session.scalars(
            select(CollectionItem).where(CollectionItem.collection_id.in_(kept or {""}))
        )
        if item.artwork_id in artwork_ids
    ]
    return rows, items


def plan_export(session: Session, options: ExportOptions) -> Selection:
    """Resolve the selection into rows. Built-in templates are part of the app: never exported."""
    scope = options.scope
    artwork_ids = _scoped_artwork_ids(session, options)
    if scope == "full":
        artworks = list(session.scalars(select(Artwork)))
        artwork_ids = {a.id for a in artworks}
    else:
        artworks = list(session.scalars(select(Artwork).where(Artwork.id.in_(artwork_ids))))
        artwork_ids = {a.id for a in artworks}
    photo_ids = {pid for artwork in artworks for pid in _document_photo_ids(artwork)}
    if scope == "full":
        photos = list(session.scalars(select(Photo)))
        photo_ids = {p.id for p in photos}
    else:
        photos = list(session.scalars(select(Photo).where(Photo.id.in_(photo_ids or {""}))))
        photo_ids = {p.id for p in photos}

    artwork_tags = list(
        session.scalars(select(ArtworkTag).where(ArtworkTag.artwork_id.in_(artwork_ids or {""})))
    )
    photo_tags = list(
        session.scalars(select(PhotoTag).where(PhotoTag.photo_id.in_(photo_ids or {""})))
    )
    tag_ids = {link.tag_id for link in artwork_tags} | {link.tag_id for link in photo_tags}
    collections, collection_items = _collection_records(session, options, artwork_ids)
    tags = list(
        session.scalars(
            select(Tag) if scope == "full" else select(Tag).where(Tag.id.in_(tag_ids or {""}))
        )
    )
    # Every category travels with a full archive (an empty one is still the user's); a partial
    # one carries only the categories of the tags it holds.
    category_ids = {t.category_id for t in tags if t.category_id}
    tag_categories = list(
        session.scalars(
            select(TagCategory).order_by(TagCategory.position)
            if scope == "full"
            else select(TagCategory)
            .where(TagCategory.id.in_(category_ids or {""}))
            .order_by(TagCategory.position)
        )
    )

    styles: list[FrameStyle] = []
    layouts: list[Layout] = []
    if options.include_templates:
        style_ids = {a.origin_style_id for a in artworks if a.origin_style_id}
        layout_ids = {a.origin_layout_id for a in artworks if a.origin_layout_id}
        style_stmt = select(FrameStyle).where(FrameStyle.builtin.is_(False))
        layout_stmt = select(Layout).where(Layout.builtin.is_(False))
        if scope == "partial":
            style_stmt = style_stmt.where(FrameStyle.id.in_(style_ids or {""}))
            layout_stmt = layout_stmt.where(Layout.id.in_(layout_ids or {""}))
        styles = list(session.scalars(style_stmt))
        layouts = list(session.scalars(layout_stmt))

    swatches: list[Swatch] = []
    settings: dict[str, Any] = {}
    if scope == "full":  # a global palette and the app's preferences are not part of a selection
        swatches = list(session.scalars(select(Swatch).order_by(Swatch.position)))
        settings = {row.key: row.value for row in session.scalars(select(Setting))}
    return Selection(
        scope=scope,
        artworks=artworks,
        photos=photos,
        tag_categories=tag_categories,
        tags=tags,
        frame_styles=styles,
        layouts=layouts,
        swatches=swatches,
        collections=collections,
        collection_items=collection_items,
        artwork_tags=artwork_tags,
        photo_tags=photo_tags,
        settings=settings,
    )


def _document_photo_ids(artwork: Artwork) -> set[str]:
    """Photo ids straight out of the stored document (no join: a slot may hold a trashed photo)."""
    slots = artwork.document.get("slots") if isinstance(artwork.document, dict) else None
    if not isinstance(slots, list):
        return set()
    return {str(s["photo_id"]) for s in slots if isinstance(s, dict) and s.get("photo_id")}


# ---- writing -----------------------------------------------------------------------------------
class _Writer:
    """A ZIP being built, hashing every member on the way in for `checksums.sha256`."""

    def __init__(self, target: Path) -> None:
        self._zip = zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6)
        self._checksums: list[tuple[str, str]] = []

    def __enter__(self) -> _Writer:
        return self

    def __exit__(self, *exc: object) -> None:
        self._zip.close()

    def text(self, name: str, body: str) -> None:
        data = body.encode()
        self._zip.writestr(name, data)
        self._checksums.append((hashlib.sha256(data).hexdigest(), name))

    def file(self, name: str, source: Path, *, store: bool = True) -> None:
        """Copy a file in, streaming it and hashing it at the same time.

        `store` leaves the bytes uncompressed: originals and JPEGs are already compressed, and
        deflating them again costs CPU for nothing (§12.1).
        """
        digest = hashlib.sha256()
        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_STORED if store else zipfile.ZIP_DEFLATED
        with source.open("rb") as src, self._zip.open(info, "w", force_zip64=True) as dst:
            while chunk := src.read(1024 * 1024):
                digest.update(chunk)
                dst.write(chunk)
        self._checksums.append((digest.hexdigest(), name))

    def finish_checksums(self) -> None:
        body = "".join(f"{digest}  {name}\n" for digest, name in sorted(self._checksums))
        self._zip.writestr(archive.CHECKSUMS_NAME, body.encode())


def _jsonl(records: Iterable[archive.Record]) -> str:
    return "".join(
        json.dumps(record.model_dump(mode="json"), sort_keys=True) + "\n" for record in records
    )


_ROWS: dict[str, Callable[[Selection], list[Any]]] = {
    "tag_category": lambda s: s.tag_categories,
    "tag": lambda s: s.tags,
    "photo": lambda s: s.photos,
    "frame_style": lambda s: s.frame_styles,
    "layout": lambda s: s.layouts,
    "swatch": lambda s: s.swatches,
    "artwork": lambda s: s.artworks,
    "collection": lambda s: s.collections,
    "collection_item": lambda s: s.collection_items,
    "artwork_tag": lambda s: s.artwork_tags,
    "photo_tag": lambda s: s.photo_tags,
}


def write_archive(
    ctx: AppContext,
    options: ExportOptions,
    target: Path,
    *,
    progress: Callable[[float], None] | None = None,
) -> ExportResult:
    """Write a `.tfarchive` at `target`. Reads the library in one snapshot-consistent session."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.part")
    with ctx.db.session() as session:
        selection = plan_export(session, options)
        warnings = _drop_missing_originals(ctx, selection)
        counts = {kind: len(rows(selection)) for kind, rows in _ROWS.items()}
        try:
            with _Writer(tmp) as writer:
                for entity in archive.ENTITIES:
                    rows = _ROWS[entity.kind](selection)
                    writer.text(
                        entity.path, _jsonl(entity.model.model_validate(row) for row in rows)
                    )
                if selection.scope == "full":  # always present in a full archive, even empty
                    writer.text(
                        archive.SETTINGS_NAME, json.dumps(selection.settings, sort_keys=True) + "\n"
                    )
                _write_originals(ctx, writer, selection, progress)
                if options.include_renders:
                    counts["render"] = _write_renders(ctx, writer, selection)
                manifest = archive.Manifest(
                    app_version=__version__,
                    created_at=utcnow(),
                    scope=selection.scope,
                    document_schema=SCHEMA_VERSION,
                    counts=counts,
                    includes_renders=options.include_renders,
                    render_key=render.render_key(),
                )
                writer.text(
                    archive.MANIFEST_NAME,
                    json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
                )
                writer.finish_checksums()
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    tmp.replace(target)
    return ExportResult(target, selection.scope, counts, target.stat().st_size, tuple(warnings))


def _drop_missing_originals(ctx: AppContext, selection: Selection) -> list[str]:
    """A photo whose file is gone cannot be exported: leave it out rather than fail the backup.

    An archive must be able to stand on its own (the importer refuses one whose records name a
    file it does not carry), and a damaged library is exactly when an export matters most. The
    artworks that used the photo still travel — the import leaves those slots as placeholders.
    """
    missing = [
        p for p in selection.photos if not ctx.storage.original_path(p.sha256, p.ext).is_file()
    ]
    if not missing:
        return []
    dropped = {photo.id for photo in missing}
    selection.photos = [p for p in selection.photos if p.id not in dropped]
    selection.photo_tags = [t for t in selection.photo_tags if t.photo_id not in dropped]
    for photo in missing:
        log.warning("original missing for photo %s (%s)", photo.id, photo.sha256)
    return [f"{p.original_filename}: original file is missing" for p in missing]


def _write_originals(
    ctx: AppContext,
    writer: _Writer,
    selection: Selection,
    progress: Callable[[float], None] | None,
) -> None:
    total = max(1, len(selection.photos))
    for index, photo in enumerate(selection.photos, start=1):
        source = ctx.storage.original_path(photo.sha256, photo.ext)
        writer.file(archive.original_name(photo.sha256, photo.ext), source)
        if progress and index % 10 == 0:
            progress(0.8 * index / total)


def _write_renders(ctx: AppContext, writer: _Writer, selection: Selection) -> int:
    """The PNG master of every artwork that has one. Missing renders are simply left out."""
    written = 0
    for artwork in selection.artworks:
        if not artwork.render_hash:
            continue
        source = ctx.storage.render_path(artwork.id, artwork.render_hash, "png")
        if not source.is_file():
            continue
        writer.file(archive.render_name(artwork.id), source, store=False)
        written += 1
    return written


# ---- rendered-image export (§12.3) -------------------------------------------------------------
def _safe_name(name: str, fallback: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in " -_.," else "_" for c in name).strip(" .")
    return (cleaned[:_MAX_NAME] or fallback).rstrip(". ")


def _collection_paths(session: Session) -> dict[str, list[str]]:
    """Folder path of every collection, from the root down (a smart one counts like any other)."""
    rows = {c.id: c for c in collections_service.list_collections(session)}
    paths: dict[str, list[str]] = {}

    def walk(collection_id: str, seen: frozenset[str]) -> list[str]:
        if collection_id in paths:
            return paths[collection_id]
        row = rows[collection_id]
        parent = row.parent_id
        prefix = (
            walk(parent, seen | {collection_id})
            if parent in rows and parent not in seen and parent is not None
            else []
        )
        paths[collection_id] = [*prefix, _safe_name(row.name, collection_id)]
        return paths[collection_id]

    for collection_id in rows:
        walk(collection_id, frozenset())
    return paths


def _artwork_folders(session: Session, artworks: Sequence[Artwork]) -> dict[str, list[str]]:
    """Every folder an artwork belongs in — it is copied into each, `Unsorted/` when it has none."""
    paths = _collection_paths(session)
    folders: dict[str, list[str]] = {a.id: [] for a in artworks}
    ids = {a.id for a in artworks}
    for item in session.scalars(select(CollectionItem)):
        if item.artwork_id in ids and item.collection_id in paths:
            folders[item.artwork_id].append("/".join(paths[item.collection_id]))
    for collection in collections_service.list_collections(session):
        if collection.kind != "smart":
            continue
        for artwork_id in library.smart_members(session, collection) & ids:
            folders[artwork_id].append("/".join(paths[collection.id]))
    for artwork_id, entries in folders.items():
        folders[artwork_id] = sorted(set(entries)) or [UNSORTED]
    return folders


def write_render_zip(
    ctx: AppContext,
    options: ExportOptions,
    target: Path,
    *,
    progress: Callable[[float], None] | None = None,
) -> ExportResult:
    """`<Collection>/<Sub>/<title or id>.<jpg|png>`, rendering whatever has never been rendered."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.part")
    with ctx.db.session() as session:
        selection = plan_export(session, options)
        live = [a for a in selection.artworks if a.deleted_at is None]
        folders = _artwork_folders(session, live)
        titles = {a.id: _safe_name(a.title, a.id) for a in live}
        ids = [a.id for a in live]
    written = 0
    try:
        with _Writer(tmp) as writer:
            for index, artwork_id in enumerate(ids, start=1):
                try:
                    source, _ = render.derivative(ctx, artwork_id, options.render_format)
                except Exception as exc:  # one broken artwork must not lose the whole export
                    log.warning("skipping artwork %s: %s", artwork_id, exc)
                    continue
                for folder in folders[artwork_id]:
                    name = f"{folder}/{titles[artwork_id]}.{options.render_format}"
                    writer.file(name, source, store=options.render_format == "jpg")
                written += 1
                if progress:
                    progress(index / max(1, len(ids)))
            writer.finish_checksums()
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(target)
    return ExportResult(target, selection.scope, {"render": written}, target.stat().st_size)


# ---- the job ------------------------------------------------------------------------------------
def _stamp() -> str:
    return utcnow().strftime("%Y%m%d-%H%M%S")


def filename_for(options: ExportOptions) -> str:
    if options.kind == "renders":
        return f"frame-it-renders-{_stamp()}.zip"
    return f"frame-it-{options.scope}-{_stamp()}{archive.ARCHIVE_SUFFIX}"


def enqueue_export(ctx: AppContext, options: ExportOptions) -> str:
    """Validate the selection now (so the caller gets a 422), then hand it to the queue."""
    with ctx.db.session() as session:
        _scoped_artwork_ids(session, options)
    return ctx.jobs.enqueue(
        EXPORT_JOB,
        {
            "kind": options.kind,
            "artwork_ids": list(options.artwork_ids),
            "collection_ids": list(options.collection_ids),
            "include_nested": options.include_nested,
            "include_renders": options.include_renders,
            "include_templates": options.include_templates,
            "render_format": options.render_format,
        },
    )


def options_from_payload(payload: dict[str, Any]) -> ExportOptions:
    kind = payload.get("kind", "library")
    render_format = payload.get("render_format", "jpg")
    return ExportOptions(
        kind="renders" if kind == "renders" else "library",
        artwork_ids=tuple(str(i) for i in payload.get("artwork_ids", [])),
        collection_ids=tuple(str(i) for i in payload.get("collection_ids", [])),
        include_nested=bool(payload.get("include_nested", True)),
        include_renders=bool(payload.get("include_renders", False)),
        include_templates=bool(payload.get("include_templates", True)),
        render_format="png" if render_format == "png" else "jpg",
    )


def export_job(ctx: AppContext) -> JobHandler:
    def handler(job: JobContext) -> None:
        options = options_from_payload(job.payload)
        directory = ctx.storage.export_dir(job.job_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / filename_for(options)
        try:
            result = (
                write_render_zip(ctx, options, target, progress=job.progress)
                if options.kind == "renders"
                else write_archive(ctx, options, target, progress=job.progress)
            )
        except ProblemError as exc:
            raise PermanentJobError(exc.code, str(exc)) from exc
        ctx.broker.publish(
            Event(
                "export.ready",
                {
                    "job_id": job.job_id,
                    "filename": target.name,
                    "bytes": result.bytes_written,
                    "counts": result.counts,
                    "warnings": list(result.warnings),
                },
            )
        )

    return handler


def export_file(ctx: AppContext, job_id: str) -> Path:
    """The one file an export job produced, or 404 while it is still running."""
    directory = ctx.storage.export_dir(job_id)
    files = sorted(p for p in directory.glob("*") if p.is_file() and not p.name.startswith("."))
    if not files:
        raise not_found("Export")
    return files[0]


def sweep_job(ctx: AppContext) -> JobHandler:
    """Sweep both staging areas: an export and an import are both temporary by design."""

    def handler(_: JobContext) -> None:
        sweep_exports(ctx)
        archive_import.sweep_imports(ctx)

    return handler


def sweep_exports(ctx: AppContext) -> int:
    """Delete finished exports past `export_retention_hours` (they are pure derivatives)."""
    if not ctx.storage.exports.is_dir():
        return 0
    cutoff = utcnow() - timedelta(hours=ctx.settings.export_retention_hours)
    removed = 0
    for directory in _directories(ctx.storage.exports):
        stamp = datetime.fromtimestamp(directory.stat().st_mtime, tz=UTC)
        if stamp < cutoff:
            for path in directory.glob("*"):
                path.unlink(missing_ok=True)
            directory.rmdir()
            removed += 1
    return removed


def _directories(root: Path) -> Iterator[Path]:
    for path in root.iterdir():
        if path.is_dir():
            yield path
