"""Archive reader: receiving, validating and the dry-run report.

Spec: `docs/archive-format.md` §12.2. Three steps, and nothing touches the library before the
last one — which lives in `services/archive_apply.py`:

1. **receive** — the archive arrives in chunks (or from a path, for the CLI) into
   `imports/<id>/archive.tfarchive`.
2. **stage** (`read_archive` + `classify`) — the ZIP is validated (safe member names, a bounded
   expanded size, `checksums.sha256` over every file, the manifest's format and versions, every
   record and every artwork document parsed), then every row is compared to the library and the
   **report** written to `imports/<id>/report.json`.
3. **apply** — `archive_apply.apply_import`.

Identity is deliberately not "same id" alone (§12.2):

- a **photo** is its bytes, so a local photo with the same SHA-256 *is* this photo, whatever its
  id — references are remapped to it and, if it sat in the trash, it comes back;
- a **tag** is its name (case-insensitive), so tags merge instead of duplicating;
- everything else is matched by id: same content ⇒ `identical` (nothing to do), different
  content ⇒ `conflicting`, and the caller's policy decides
  (`keep_mine` / `take_theirs` / `keep_both`).

An archive is read twice: once to report, once to apply. Staging never caches its verdict, because
the library can change between the two — the report is what the user saw, not what will happen.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from the_frame_v2.context import AppContext
from the_frame_v2.db.models import (
    ArchiveImport,
    Artwork,
    ArtworkTag,
    Collection,
    CollectionItem,
    FrameStyle,
    Layout,
    Photo,
    PhotoHashAlias,
    PhotoTag,
    Setting,
    Swatch,
    Tag,
)
from the_frame_v2.domain import archive, filters
from the_frame_v2.domain.document import SCHEMA_VERSION, ArtworkDocument, parse_document
from the_frame_v2.errors import ProblemError, not_found
from the_frame_v2.events import Event
from the_frame_v2.ids import new_id, utcnow
from the_frame_v2.jobs.queue import JobContext, JobHandler, PermanentJobError

log = logging.getLogger(__name__)

STAGE_JOB = "archive.stage"
STATES = ("receiving", "staging", "ready", "applying", "applied", "failed")
MAX_CHUNK_BYTES = 16 * 1024 * 1024
MAX_MEMBERS = 2_000_000
REPORT_NAME = "report.json"
#: Entries kept per kind in the API response; the counts are always exact.
REPORT_ITEM_LIMIT = 200


# ---- reading -----------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class StagedArchive:
    """A validated archive held in memory (rows only — the files stay in the ZIP)."""

    path: Path
    manifest: archive.Manifest
    records: dict[str, list[archive.Record]]
    settings: dict[str, Any]
    originals: dict[str, str]
    """SHA-256 → member name, one per `originals/<sha256>.<ext>`."""
    renders: dict[str, str]
    """Artwork id → member name, from `renders/`."""
    documents: dict[str, ArtworkDocument]
    warnings: list[str] = field(default_factory=list)

    def rows(self, kind: str) -> list[Any]:
        return self.records.get(kind, [])


def problem_of(error: archive.ArchiveError) -> ProblemError:
    return ProblemError(422, error.code, "Cannot read this archive", str(error))


def read_archive(path: Path, *, max_bytes: int) -> StagedArchive:
    """Validate an archive completely before anything is read out of it. Raises `ArchiveError`."""
    if not path.is_file() or not zipfile.is_zipfile(path):
        raise archive.ArchiveError("not_an_archive", "not a ZIP archive")
    with zipfile.ZipFile(path) as zf:
        names = _safe_names(zf, max_bytes)
        checksums = _verify_checksums(zf, names, max_bytes)
        manifest = _read_manifest(zf)
        records, documents = _read_records(zf, names)
        settings = _read_settings(zf, names)
        originals, renders = _read_files(names, checksums)
    _check_originals(records, originals)
    return StagedArchive(path, manifest, records, settings, originals, renders, documents)


def _safe_names(zf: zipfile.ZipFile, max_bytes: int) -> list[str]:
    """Member names are untrusted: refuse escapes, and refuse an archive that claims too much.

    `info.file_size` is what the archive *declares*. CPython's `zipfile` stops a member at that
    many bytes and then fails its CRC, so understating it cannot smuggle a bomb past this gate —
    but that is a property of the standard library, not of the format. `_verify_checksums` counts
    the bytes that actually come out, so the budget holds without relying on it.
    """
    infos = zf.infolist()
    if len(infos) > MAX_MEMBERS:
        raise archive.ArchiveError("archive_too_large", f"{len(infos)} members")
    total = 0
    names = []
    for info in infos:
        if info.is_dir():
            continue
        name = archive.safe_member_path(info.filename)
        total += info.file_size
        if total > max_bytes:
            raise archive.ArchiveError(
                "archive_too_large", f"expands to more than {max_bytes} bytes"
            )
        names.append(name)
    if archive.MANIFEST_NAME not in names:
        raise archive.ArchiveError("missing_manifest", "no manifest.json")
    return names


def _verify_checksums(zf: zipfile.ZipFile, names: Sequence[str], max_bytes: int) -> dict[str, str]:
    """`checksums.sha256` must cover every other member, and every digest must match.

    This is also where the **measured** expanded size is enforced, as opposed to the declared one
    `_safe_names` adds up. Every member is streamed here before anything else reads one, so the
    budget is spent against real bytes and no later `zf.read` can exceed it.
    """
    if archive.CHECKSUMS_NAME not in names:
        raise archive.ArchiveError("missing_checksums", "no checksums.sha256")
    listed: dict[str, str] = {}
    for line in zf.read(archive.CHECKSUMS_NAME).decode().splitlines():
        if not line.strip():
            continue
        digest, _, name = line.partition("  ")
        if len(digest) != 64 or not name:
            raise archive.ArchiveError("invalid_checksums", f"bad line {line!r}")
        listed[archive.safe_member_path(name)] = digest.lower()
    expected = {n for n in names if n != archive.CHECKSUMS_NAME}
    if missing := expected - listed.keys():
        raise archive.ArchiveError(
            "unlisted_file", f"not in checksums.sha256: {sorted(missing)[0]}"
        )
    if absent := listed.keys() - expected:
        raise archive.ArchiveError("missing_file", f"listed but absent: {sorted(absent)[0]}")
    budget = max_bytes
    for name, digest in listed.items():
        actual, read = _member_digest(zf, name, budget)
        if actual != digest:
            raise archive.ArchiveError("checksum_mismatch", name)
        budget -= read
    return listed


def _member_digest(zf: zipfile.ZipFile, name: str, budget: int) -> tuple[str, int]:
    """Digest of a member, streamed, stopping the moment it has produced more than `budget`."""
    sha = hashlib.sha256()
    read = 0
    with zf.open(name) as fh:
        while chunk := fh.read(1024 * 1024):
            read += len(chunk)
            if read > budget:
                raise archive.ArchiveError(
                    "archive_too_large", f"{name} expands past the {max(0, budget)}-byte budget"
                )
            sha.update(chunk)
    return sha.hexdigest(), read


def _read_manifest(zf: zipfile.ZipFile) -> archive.Manifest:
    try:
        raw = json.loads(zf.read(archive.MANIFEST_NAME))
        manifest = archive.Manifest.model_validate(raw)
    except (ValueError, ValidationError) as exc:
        raise archive.ArchiveError("invalid_manifest", str(exc)) from exc
    if manifest.format != archive.FORMAT:
        raise archive.ArchiveError("unknown_format", manifest.format)
    if manifest.format_version > archive.FORMAT_VERSION:
        raise archive.ArchiveError(
            "unsupported_archive_version",
            f"written by a newer version (format {manifest.format_version})",
        )
    if manifest.document_schema > SCHEMA_VERSION:
        raise archive.ArchiveError(
            "unsupported_document_schema", f"document schema {manifest.document_schema}"
        )
    return manifest


def _read_records(
    zf: zipfile.ZipFile, names: Sequence[str]
) -> tuple[dict[str, list[archive.Record]], dict[str, ArtworkDocument]]:
    records: dict[str, list[archive.Record]] = {}
    documents: dict[str, ArtworkDocument] = {}
    for entity in archive.ENTITIES:
        rows: list[archive.Record] = []
        if entity.path in names:
            for number, line in enumerate(zf.read(entity.path).decode().splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    rows.append(entity.model.model_validate_json(line))
                except ValidationError as exc:
                    raise archive.ArchiveError(
                        "invalid_record", f"{entity.path}:{number}: {_first_error(exc)}"
                    ) from exc
        records[entity.kind] = rows
    for row in records[archive.ARTWORKS.kind]:
        record = row
        assert isinstance(record, archive.ArtworkRecord)
        try:  # a document that does not parse would fail mid-apply: refuse the archive now
            documents[record.id] = parse_document(record.document)
        except (ValueError, ValidationError) as exc:
            raise archive.ArchiveError(
                "invalid_document", f"artwork {record.id}: {_first_error(exc)}"
            ) from exc
    return records, documents


def _first_error(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return str(exc)
    details = errors(include_url=False)
    if not details:
        return str(exc)
    first = details[0]
    where = ".".join(str(p) for p in first.get("loc", ()))
    message = str(first.get("msg", "")).removeprefix("Value error, ")
    return f"{where}: {message}" if where else message


def _read_settings(zf: zipfile.ZipFile, names: Sequence[str]) -> dict[str, Any]:
    if archive.SETTINGS_NAME not in names:
        return {}
    try:
        raw = json.loads(zf.read(archive.SETTINGS_NAME))
    except ValueError as exc:
        raise archive.ArchiveError("invalid_settings", str(exc)) from exc
    if not isinstance(raw, dict):
        raise archive.ArchiveError("invalid_settings", "settings.json is not an object")
    return {str(k): v for k, v in raw.items()}


def _read_files(
    names: Sequence[str], checksums: Mapping[str, str]
) -> tuple[dict[str, str], dict[str, str]]:
    originals: dict[str, str] = {}
    renders: dict[str, str] = {}
    for name in names:
        if name.startswith(archive.ORIGINALS_PREFIX):
            sha, _ = archive.parse_original_name(name)
            if checksums[name] != sha:
                # The name *is* the content address: a mismatch means the file is not that photo.
                raise archive.ArchiveError("original_mismatch", name)
            originals[sha] = name
        elif name.startswith(archive.RENDERS_PREFIX):
            renders[archive.parse_render_name(name)] = name
    return originals, renders


def _check_originals(
    records: Mapping[str, list[archive.Record]], originals: Mapping[str, str]
) -> None:
    for row in records.get(archive.PHOTOS.kind, []):
        assert isinstance(row, archive.PhotoRecord)
        if row.sha256 not in originals:
            raise archive.ArchiveError(
                "missing_original", f"photo {row.original_filename} ({row.sha256[:12]}…)"
            )


# ---- the dry-run report ------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Entry:
    kind: str
    key: str
    """The record's identity: its id, or the two ids of a link row joined by a tab."""
    name: str
    status: archive.Status
    maps_to: str | None = None
    """Local id this record will be remapped to (`matched`), when it is not the same id."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "key": self.key,
            "name": self.name,
            "status": self.status,
            "maps_to": self.maps_to,
        }


@dataclass(frozen=True, slots=True)
class KindReport:
    kind: str
    total: int
    new: int
    identical: int
    matched: int
    conflicting: int
    items: list[Entry]

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "total": self.total,
            "new": self.new,
            "identical": self.identical,
            "matched": self.matched,
            "conflicting": self.conflicting,
            "items": [item.as_dict() for item in self.items],
        }


@dataclass(frozen=True, slots=True)
class Report:
    manifest: archive.Manifest
    kinds: list[KindReport]
    warnings: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.model_dump(mode="json"),
            "kinds": [kind.as_dict() for kind in self.kinds],
            "warnings": list(self.warnings),
        }

    def summary(self) -> dict[str, Any]:
        return {kind.kind: kind.as_dict() | {"items": []} for kind in self.kinds}


def _local_index(session: Session, entity: archive.Entity) -> dict[str, Any]:
    """Every local row of this kind by id — the comparison the report is made of."""
    model: Any = {
        "photo": Photo,
        "tag": Tag,
        "artwork": Artwork,
        "collection": Collection,
        "frame_style": FrameStyle,
        "layout": Layout,
        "swatch": Swatch,
    }.get(entity.kind)
    if model is None:
        return {}
    return {row.id: row for row in session.scalars(select(model))}


def _link_exists(session: Session, entity: archive.Entity, record: archive.Record) -> bool:
    values = [getattr(record, field) for field in entity.identity]
    model = {
        "artwork_tag": ArtworkTag,
        "photo_tag": PhotoTag,
        "collection_item": CollectionItem,
    }[entity.kind]
    columns = [getattr(model, field) for field in entity.identity]
    stmt = select(func.count()).select_from(model)
    for column, value in zip(columns, values, strict=True):
        stmt = stmt.where(column == value)
    return bool(session.scalar(stmt))


def _name_of(entity: archive.Entity, record: archive.Record) -> str:
    if entity is archive.PHOTOS:
        assert isinstance(record, archive.PhotoRecord)
        return record.original_filename
    if entity.named:
        return str(getattr(record, entity.named) or "")
    return archive.identity_of(entity, record).replace("\x1f", " → ")


def classify(session: Session, staged: StagedArchive) -> Report:
    """Compare every record to the library. Pure reading: this is what the dialog shows."""
    kinds: list[KindReport] = []
    photo_by_sha = photos_by_sha(session)
    tags_by_name = {row.name.casefold(): row for row in session.scalars(select(Tag))}
    maps = predicted_maps(session, staged)
    for entity in archive.ENTITIES:
        rows = staged.rows(entity.kind)
        entries: list[Entry] = []
        local = _local_index(session, entity)
        for record in rows:
            entries.append(
                _classify_link(session, entity, record)
                if entity.is_link
                else _classify_row(
                    session, entity, record, local, photo_by_sha, tags_by_name, maps, staged
                )
            )
        kinds.append(_kind_report(entity.kind, entries))
    kinds.append(_settings_report(session, staged))
    return Report(staged.manifest, kinds, list(staged.warnings))


def photos_by_sha(session: Session) -> dict[str, Photo]:
    """Every SHA-256 the library answers to, merged copies included (`services/photo_copies.py`)."""
    photos = {row.sha256: row for row in session.scalars(select(Photo))}
    for alias in session.scalars(select(PhotoHashAlias)):
        photo = session.get(Photo, alias.photo_id)
        if photo is not None:
            photos.setdefault(alias.sha256, photo)
    return photos


# ---- translation (shared with `services/archive_apply.py`) -------------------------------------
# Every id an archive carries may land on a different one here: a photo matched by SHA-256, a tag
# merged by name, a `keep_both` copy under a fresh id. Both halves of an import need the same
# translation — the report, so that "identical" means *identical once translated* rather than
# "wrote the same ids", and the apply pass, which writes the result.


@dataclass(slots=True)
class IdMaps:
    """Archive id → local id, per kind: every reference in the archive travels through these."""

    by_kind: dict[str, dict[str, str]] = field(default_factory=dict)

    def put(self, kind: str, source: str, target: str) -> None:
        self.by_kind.setdefault(kind, {})[source] = target

    def get(self, kind: str, source: str) -> str | None:
        return self.by_kind.get(kind, {}).get(source)

    def of(self, kind: str) -> dict[str, str]:
        return self.by_kind.setdefault(kind, {})


def remapped_document(
    staged: StagedArchive, record: archive.ArtworkRecord, maps: IdMaps
) -> tuple[ArtworkDocument, list[str]]:
    """The archive's document with its photo ids rewritten; an unknown photo leaves a placeholder.

    The document is stored **verbatim** otherwise: an archive is a restore, not a client save, so
    the solver is not re-run over it (the exporting side had already applied it). The next editor
    save re-solves as usual. The warnings are returned rather than recorded: this also runs to
    decide whether the artwork is the one already here, and a comparison must not report anything.
    """
    doc = staged.documents[record.id].model_copy(deep=True)
    photos = maps.of(archive.PHOTOS.kind)
    warnings: list[str] = []
    for slot in doc.slots:
        if slot.photo_id is None:
            continue
        mapped = photos.get(slot.photo_id)
        if mapped is not None:
            slot.photo_id = mapped
            continue
        warnings.append(f"artwork {record.id}: photo {slot.photo_id} is not in the archive")
        slot.photo_id = None
        slot.quality_lock = "free"
        slot.source.crop.x, slot.source.crop.y = 0, 0
        slot.source.crop.w, slot.source.crop.h = slot.rect.w, slot.rect.h
    return doc, warnings


def template_reference(
    session: Session, model: Any, kind: str, template_id: str | None, maps: IdMaps
) -> str | None:
    """Where an artwork's origin template landed: remapped, still itself, or gone.

    A built-in template is not in the archive (it is part of the app), so its id has no mapping
    and must survive as written — dropping it would lose the origin badge on every artwork made
    from a built-in style.
    """
    if not template_id:
        return None
    mapped = maps.get(kind, template_id)
    if mapped is not None:
        return mapped
    return template_id if session.get(model, template_id) is not None else None


def artwork_values(session: Session, record: archive.ArtworkRecord, maps: IdMaps) -> dict[str, Any]:
    """An artwork's columns as this library would hold them (the document is handled apart)."""
    values = record.model_dump(
        exclude={"id", "document", "schema_version", "origin_style_id", "origin_layout_id"}
    )
    values["origin_style_id"] = template_reference(
        session, FrameStyle, archive.FRAME_STYLES.kind, record.origin_style_id, maps
    )
    values["origin_layout_id"] = template_reference(
        session, Layout, archive.LAYOUTS.kind, record.origin_layout_id, maps
    )
    return values


def collection_values(
    session: Session, record: archive.CollectionRecord, maps: IdMaps
) -> dict[str, Any]:
    """A collection's columns as this library would hold them: parent, cover and filter remapped."""
    values = record.model_dump(exclude={"id", "parent_id", "cover_artwork_id", "filter"})
    parent = maps.get(archive.COLLECTIONS.kind, record.parent_id) if record.parent_id else None
    if parent is None and record.parent_id:
        parent = record.parent_id if session.get(Collection, record.parent_id) else None
    values["parent_id"] = parent  # a parent left out of the archive makes this a root (§12.1)
    artworks = archive.ARTWORKS.kind
    cover = maps.get(artworks, record.cover_artwork_id) if record.cover_artwork_id else None
    values["cover_artwork_id"] = (
        cover if cover and session.get(Artwork, cover) is not None else None
    )
    values["filter"] = remapped_filter(record, maps)
    return values


def remapped_filter(record: archive.CollectionRecord, maps: IdMaps) -> dict[str, Any] | None:
    """A smart collection's filter names tags and collections: rewrite the ids it travelled with.

    Tags and artworks are fully mapped by the time collections are written; a filter naming a
    *collection* processed later than this one is caught by the second pass (`_fix_filters`).
    """
    if record.kind != "smart" or not record.filter:
        return record.filter
    try:
        parsed = filters.parse_filter(record.filter)
    except filters.FilterError:
        return None
    tags, collections = maps.of(archive.TAGS.kind), maps.of(archive.COLLECTIONS.kind)
    remapped: dict[str, Any] = filters.remap_ids(parsed, tags, collections).model_dump(mode="json")
    return remapped


def predicted_maps(session: Session, staged: StagedArchive) -> IdMaps:
    """The maps an import would use, as far as reading can tell — what the report is compared on.

    Photos are matched by SHA-256 and tags by name; every other id is assumed to stay itself,
    which is what `keep_mine` and a fresh insert both do. `keep_both` is the one policy that can
    move an id, and it is chosen *after* the report.
    """
    maps = IdMaps()
    by_sha = photos_by_sha(session)
    for record in staged.rows(archive.PHOTOS.kind):
        assert isinstance(record, archive.PhotoRecord)
        match = by_sha.get(record.sha256)
        maps.put(archive.PHOTOS.kind, record.id, match.id if match else record.id)
    by_name = {row.name.casefold(): row for row in session.scalars(select(Tag))}
    for record in staged.rows(archive.TAGS.kind):
        assert isinstance(record, archive.TagRecord)
        tag = by_name.get(record.name.casefold())
        maps.put(archive.TAGS.kind, record.id, tag.id if tag else record.id)
    for entity in (archive.ARTWORKS, archive.COLLECTIONS, archive.FRAME_STYLES, archive.LAYOUTS):
        for row in staged.rows(entity.kind):
            maps.put(entity.kind, row.id, row.id)
    return maps


# ---- classification ----------------------------------------------------------------------------
def _classify_link(session: Session, entity: archive.Entity, record: archive.Record) -> Entry:
    key = archive.identity_of(entity, record)
    exists = _link_exists(session, entity, record)
    return Entry(entity.kind, key, _name_of(entity, record), "identical" if exists else "new")


def _classify_row(
    session: Session,
    entity: archive.Entity,
    record: archive.Record,
    local: Mapping[str, Any],
    photo_by_sha: Mapping[str, Photo],
    tags_by_name: Mapping[str, Tag],
    maps: IdMaps,
    staged: StagedArchive,
) -> Entry:
    key = archive.identity_of(entity, record)
    name = _name_of(entity, record)
    if entity is archive.PHOTOS:
        assert isinstance(record, archive.PhotoRecord)
        match = photo_by_sha.get(record.sha256)
        if match is not None:  # a photo is its bytes, whatever id either side gave it
            return Entry(entity.kind, key, name, "matched", match.id)
    if entity is archive.TAGS:
        assert isinstance(record, archive.TagRecord)
        match_tag = tags_by_name.get(record.name.casefold())
        if match_tag is not None and match_tag.id != record.id:
            return Entry(entity.kind, key, name, "matched", match_tag.id)
    existing = local.get(key)
    if existing is None:
        return Entry(entity.kind, key, name, "new")
    if getattr(existing, "builtin", False):
        # A built-in template belongs to the app, not to the archive: never overwritten.
        return Entry(entity.kind, key, name, "matched", key)
    mine = archive.comparable(entity, entity.model.model_validate(existing))
    theirs = archive.comparable(entity, _translated(session, entity, record, maps, staged))
    return Entry(entity.kind, key, name, "identical" if mine == theirs else "conflicting")


def _translated(
    session: Session,
    entity: archive.Entity,
    record: archive.Record,
    maps: IdMaps,
    staged: StagedArchive,
) -> archive.Record:
    """The record as an import would write it — the only fair thing to compare a local row to.

    The same artwork in two libraries names the same photo under two ids, so comparing the raw
    document would report every re-import as a conflict.
    """
    if entity is archive.ARTWORKS:
        assert isinstance(record, archive.ArtworkRecord)
        doc, _ = remapped_document(staged, record, maps)
        values = artwork_values(session, record, maps)
        return record.model_copy(update={**values, "document": doc.canonical()})
    if entity is archive.COLLECTIONS:
        assert isinstance(record, archive.CollectionRecord)
        return record.model_copy(update=collection_values(session, record, maps))
    return record


def _kind_report(kind: str, entries: Sequence[Entry]) -> KindReport:
    counts = dict.fromkeys(("new", "identical", "matched", "conflicting"), 0)
    for entry in entries:
        counts[entry.status] += 1
    interesting = [e for e in entries if e.status in {"new", "conflicting"}] or list(entries)
    return KindReport(
        kind=kind,
        total=len(entries),
        new=counts["new"],
        identical=counts["identical"],
        matched=counts["matched"],
        conflicting=counts["conflicting"],
        items=interesting[:REPORT_ITEM_LIMIT],
    )


def _settings_report(session: Session, staged: StagedArchive) -> KindReport:
    entries: list[Entry] = []
    for key, value in sorted(staged.settings.items()):
        row = session.get(Setting, key)
        status: archive.Status = (
            "new" if row is None else "identical" if row.value == value else "conflicting"
        )
        entries.append(Entry("setting", key, key, status))
    return _kind_report("setting", entries)


# ---- sessions ----------------------------------------------------------------------------------
def row_of(session: Session, import_id: str) -> ArchiveImport:
    row = session.get(ArchiveImport, import_id)
    if row is None:
        raise not_found("Import")
    return row


def get_import(session: Session, import_id: str) -> ArchiveImport:
    return row_of(session, import_id)


def list_imports(session: Session) -> list[ArchiveImport]:
    return list(
        session.scalars(select(ArchiveImport).order_by(ArchiveImport.created_at.desc()).limit(20))
    )


def create_import(ctx: AppContext, session: Session, filename: str, size: int) -> ArchiveImport:
    if size <= 0:
        raise ProblemError(422, "empty_file", "File is empty")
    if size > ctx.settings.max_archive_bytes:
        raise ProblemError(413, "file_too_large", "Archive exceeds the import limit")
    row = ArchiveImport(
        id=new_id(),
        filename=Path(filename).name[:512] or "archive.tfarchive",
        size=size,
        expires_at=utcnow() + timedelta(hours=ctx.settings.import_retention_hours),
    )
    session.add(row)
    session.flush()
    ctx.storage.import_dir(row.id).mkdir(parents=True, exist_ok=True)
    ctx.storage.import_archive_path(row.id).touch()
    return row


def finalize(ctx: AppContext, import_id: str) -> str:
    """The archive is complete: hand staging to the queue (it validates the whole file)."""
    with ctx.db.session() as session:
        row = row_of(session, import_id)
        row.state = "staging"
    job_id = ctx.jobs.enqueue(STAGE_JOB, {"import_id": import_id})
    with ctx.db.session() as session:
        row_of(session, import_id).job_id = job_id
    return job_id


def stage_local(ctx: AppContext, path: Path) -> tuple[str, Report]:
    """Stage an archive already on this machine (the CLI): link it in rather than copy it."""
    if not path.is_file():
        raise ProblemError(422, "not_an_archive", "No such file", str(path))
    size = path.stat().st_size
    with ctx.db.session() as session:
        import_id = create_import(ctx, session, path.name, size).id
    target = ctx.storage.import_archive_path(import_id)
    target.unlink(missing_ok=True)
    try:
        os.link(path, target)  # same filesystem: no second copy of a possibly huge archive
    except OSError:
        shutil.copyfile(path, target)
    with ctx.db.session() as session:
        row_of(session, import_id).received_bytes = size
    return import_id, stage(ctx, import_id)


def stage(ctx: AppContext, import_id: str) -> Report:
    """Validate the archive and write the dry-run report. Never writes to the library."""
    path = ctx.storage.import_archive_path(import_id)
    staged = read_archive(path, max_bytes=ctx.settings.max_archive_bytes)
    with ctx.db.session() as session:
        report = classify(session, staged)
        row = row_of(session, import_id)
        row.state = "ready"
        row.error = None
        row.scope = staged.manifest.scope
        row.manifest = staged.manifest.model_dump(mode="json")
        row.summary = report.summary()
    _report_path(ctx, import_id).write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return report


def _report_path(ctx: AppContext, import_id: str) -> Path:
    return ctx.storage.import_dir(import_id) / REPORT_NAME


def stored_report(ctx: AppContext, import_id: str) -> dict[str, Any]:
    path = _report_path(ctx, import_id)
    if not path.is_file():
        raise ProblemError(409, "import_not_ready", "This import has no report yet")
    loaded: dict[str, Any] = json.loads(path.read_text())
    return loaded


def set_failed(ctx: AppContext, import_id: str, code: str) -> None:
    with ctx.db.session() as session:
        row = session.get(ArchiveImport, import_id)
        if row is not None:
            row.state, row.error = "failed", code[:128]


def stage_job(ctx: AppContext) -> JobHandler:
    def handler(job: JobContext) -> None:
        import_id = str(job.payload["import_id"])
        try:
            stage(ctx, import_id)
        except archive.ArchiveError as exc:
            set_failed(ctx, import_id, exc.code)
            ctx.broker.publish(Event("import.failed", {"import_id": import_id, "code": exc.code}))
            raise PermanentJobError(exc.code, str(exc)) from exc
        except Exception:
            set_failed(ctx, import_id, "staging_failed")
            raise
        ctx.broker.publish(Event("import.staged", {"import_id": import_id}))

    return handler


def delete_import(ctx: AppContext, session: Session, import_id: str) -> None:
    row = row_of(session, import_id)
    session.delete(row)
    shutil.rmtree(ctx.storage.import_dir(import_id), ignore_errors=True)


def sweep_imports(ctx: AppContext) -> int:
    """Drop expired staging directories: an archive received but never applied is disposable."""
    removed = 0
    with ctx.db.session() as session:
        expired = select(ArchiveImport).where(ArchiveImport.expires_at < utcnow())
        for row in session.scalars(expired):
            if row.state == "applying":
                continue
            shutil.rmtree(ctx.storage.import_dir(row.id), ignore_errors=True)
            session.delete(row)
            removed += 1
        live = set(session.scalars(select(ArchiveImport.id)))
    if ctx.storage.imports.is_dir():
        for directory in _orphans(ctx.storage.imports, live):
            shutil.rmtree(directory, ignore_errors=True)
            removed += 1
    return removed


def _orphans(root: Path, live: set[str]) -> Iterator[Path]:
    cutoff = datetime.now(tz=UTC) - timedelta(hours=1)
    for path in root.iterdir():
        stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if path.is_dir() and path.name not in live and stamp < cutoff:
            yield path
