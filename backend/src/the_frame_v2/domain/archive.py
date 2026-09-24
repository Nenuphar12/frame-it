"""Archive (export/import) format — PURE record models, layout and safety rules.

Spec: `docs/archive-format.md`. A `.tfarchive` is a ZIP holding

```
manifest.json          the format, its version, the scope and the counts
data/*.jsonl           one JSON object per line per entity kind (+ settings.json)
originals/<sha256>.<ext>
renders/<artwork_id>.png   (optional)
checksums.sha256       every other file, `<sha256>  <path>`
```

This module owns *what a record is*: the models below are the published JSON Schemas
(`docs/schemas/archive/`, written by `the_frame_v2 schemas`) and the single place that says which
columns travel. Reading and writing the ZIP is `services/archive_export.py` /
`services/archive_import.py`.

Deliberately **not** in an archive: devices, pairing/setup codes, upload sessions, jobs, snapshots,
LocalSend senders, the FTS index, `artwork_photos` (derived from the documents), photo hash aliases
and everything under `cache/` (derivatives regenerate). Built-in templates are part of the app: they
are seeded on startup on both sides, so exporting them would only invent conflicts.

Records keep the timestamps they were created with, and trashed rows travel too (with `deleted_at`),
so a full round-trip restores the library as it was — including its trash.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from the_frame_v2.domain import document as document_schema
from the_frame_v2.domain import templates as template_schema

FORMAT = "the_frame_v2.archive"
FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
CHECKSUMS_NAME = "checksums.sha256"
DATA_PREFIX = "data/"
ORIGINALS_PREFIX = "originals/"
RENDERS_PREFIX = "renders/"
SETTINGS_NAME = "data/settings.json"
ARCHIVE_SUFFIX = ".tfarchive"

Scope = Literal["full", "partial"]
Policy = Literal["keep_mine", "take_theirs", "keep_both"]
POLICIES: tuple[Policy, ...] = ("keep_mine", "take_theirs", "keep_both")
Status = Literal["new", "identical", "matched", "conflicting"]

#: Suffix `keep_both` appends to the name of a duplicated entity (docs/archive-format.md §12.2).
IMPORTED_SUFFIX = " (imported)"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EXT_RE = re.compile(r"^[a-z0-9]{1,8}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ArchiveError(ValueError):
    """An archive we refuse to read. `code` becomes the problem code of the API error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ---- safety ------------------------------------------------------------------------------------
def safe_member_path(name: str) -> str:
    """Member names are data, not paths: refuse anything that could escape the staging dir.

    Absolute paths, drive letters, backslashes, `.` / `..` segments and empty segments are all
    rejected rather than normalized — an archive that carries one is not one of ours.
    """
    if not name or len(name) > 255 or "\\" in name or ":" in name:
        raise ArchiveError("unsafe_archive_path", f"unsafe path {name!r}")
    if name.startswith("/") or name != posixpath.normpath(name):
        raise ArchiveError("unsafe_archive_path", f"unsafe path {name!r}")
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ArchiveError("unsafe_archive_path", f"unsafe path {name!r}")
    return name


def parse_original_name(name: str) -> tuple[str, str]:
    """`originals/<sha256>.<ext>` → (sha256, ext). The name *is* the content address."""
    base = name.removeprefix(ORIGINALS_PREFIX)
    sha, dot, ext = base.partition(".")
    if not dot or not _SHA256_RE.match(sha) or not _EXT_RE.match(ext.lower()):
        raise ArchiveError("invalid_original_name", f"not a content-addressed original: {name!r}")
    return sha, ext.lower()


def original_name(sha256: str, ext: str) -> str:
    return f"{ORIGINALS_PREFIX}{sha256}.{ext}"


def render_name(artwork_id: str, ext: str = "png") -> str:
    return f"{RENDERS_PREFIX}{artwork_id}.{ext}"


def parse_render_name(name: str) -> str:
    base = name.removeprefix(RENDERS_PREFIX)
    artwork_id = base.rsplit(".", 1)[0]
    if not _ID_RE.match(artwork_id):
        raise ArchiveError("invalid_render_name", f"not an artwork render: {name!r}")
    return artwork_id


# ---- records -----------------------------------------------------------------------------------
class Record(BaseModel):
    """Base of every archived row: built from an ORM object, dumped as one JSONL line."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")


class PhotoRecord(Record):
    id: str
    sha256: str
    content_fingerprint: str | None = None
    ext: str
    mime: str
    original_filename: str
    file_size: int
    width: int
    height: int
    exif_orientation: int = 1
    bit_depth: int = 8
    icc_description: str | None = None
    is_wide_gamut: bool = False
    has_gain_map: bool = False
    taken_at: datetime | None = None
    """Floating camera-local time (invariant 9): stored and restored verbatim, never converted."""
    camera_make: str | None = None
    camera_model: str | None = None
    lens: str | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None
    place_name: str | None = None
    place_admin1: str | None = None
    place_country: str | None = None
    imported_at: datetime
    inbox_state: str = "inbox"
    quality_warnings: list[Any] = Field(default_factory=list)
    deleted_at: datetime | None = None
    trash_batch_id: str | None = None


class TagRecord(Record):
    id: str
    name: str
    color: str | None = None
    created_at: datetime


class ArtworkRecord(Record):
    id: str
    title: str = ""
    status: str = "draft"
    document: dict[str, Any]
    document_version: int = 1
    schema_version: int = 1
    favorite: bool = False
    origin_style_id: str | None = None
    origin_style_revision: int | None = None
    origin_layout_id: str | None = None
    origin_layout_revision: int | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    trash_batch_id: str | None = None


class ArtworkTagRecord(Record):
    artwork_id: str
    tag_id: str


class PhotoTagRecord(Record):
    photo_id: str
    tag_id: str


class CollectionRecord(Record):
    id: str
    parent_id: str | None = None
    name: str
    description: str = ""
    date_start: str | None = None
    date_end: str | None = None
    cover_artwork_id: str | None = None
    kind: str = "manual"
    filter: dict[str, Any] | None = None
    position: float = 0.0
    created_at: datetime
    updated_at: datetime


class CollectionItemRecord(Record):
    collection_id: str
    artwork_id: str
    position: float = 0.0


class FrameStyleRecord(Record):
    id: str
    name: str
    revision: int = 1
    document: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class LayoutRecord(Record):
    id: str
    name: str
    revision: int = 1
    document: dict[str, Any]
    slot_count: int = 1
    created_at: datetime
    updated_at: datetime


class SwatchRecord(Record):
    id: str
    color: str
    name: str = ""
    position: float = 0.0


class Manifest(BaseModel):
    """`manifest.json`: what this file is, what it holds and what wrote it."""

    model_config = ConfigDict(extra="ignore")

    format: str = FORMAT
    format_version: int = FORMAT_VERSION
    app_version: str = ""
    created_at: datetime
    scope: Scope = "full"
    document_schema: int = 1
    counts: dict[str, int] = Field(default_factory=dict)
    includes_renders: bool = False
    render_key: str = ""
    """Renderer + asset versions the archived renders were made with: an importer only reuses a
    render when they still match (the render hash is a function of both)."""


# ---- entity table ------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Entity:
    """One JSONL file: its kind (also the policy key), its path and its record model.

    `identity` names the fields that make a row *the same row* somewhere else — an id for entities,
    the two columns of a link table. `ignored` are the fields left out when deciding whether two
    rows with the same id are identical: every timestamp (a save on either side moves them without
    changing anything the eye sees) and the trash batch.
    """

    kind: str
    path: str
    model: type[Record]
    identity: tuple[str, ...] = ("id",)
    ignored: frozenset[str] = frozenset({"created_at", "updated_at", "imported_at", "deleted_at"})
    named: str | None = None
    """The field `keep_both` suffixes, when the entity has a name."""

    @property
    def is_link(self) -> bool:
        return len(self.identity) > 1


PHOTOS = Entity("photo", "data/photos.jsonl", PhotoRecord, ignored=frozenset({"imported_at"}))
TAGS = Entity("tag", "data/tags.jsonl", TagRecord, named="name")
ARTWORKS = Entity("artwork", "data/artworks.jsonl", ArtworkRecord, named="title")
ARTWORK_TAGS = Entity(
    "artwork_tag", "data/artwork_tags.jsonl", ArtworkTagRecord, identity=("artwork_id", "tag_id")
)
PHOTO_TAGS = Entity(
    "photo_tag", "data/photo_tags.jsonl", PhotoTagRecord, identity=("photo_id", "tag_id")
)
COLLECTIONS = Entity("collection", "data/collections.jsonl", CollectionRecord, named="name")
COLLECTION_ITEMS = Entity(
    "collection_item",
    "data/collection_items.jsonl",
    CollectionItemRecord,
    identity=("collection_id", "artwork_id"),
)
FRAME_STYLES = Entity("frame_style", "data/frame_styles.jsonl", FrameStyleRecord, named="name")
LAYOUTS = Entity("layout", "data/layouts.jsonl", LayoutRecord, named="name")
SWATCHES = Entity("swatch", "data/swatches.jsonl", SwatchRecord, named="name")

#: Write and read order — references first, so an importer never sees a dangling id.
ENTITIES: tuple[Entity, ...] = (
    TAGS,
    PHOTOS,
    FRAME_STYLES,
    LAYOUTS,
    SWATCHES,
    ARTWORKS,
    COLLECTIONS,
    COLLECTION_ITEMS,
    ARTWORK_TAGS,
    PHOTO_TAGS,
)
BY_KIND: dict[str, Entity] = {entity.kind: entity for entity in ENTITIES}
#: Kinds a policy can be chosen for (`setting` has no record model: it is `data/settings.json`).
POLICY_KINDS: tuple[str, ...] = (*BY_KIND, "setting")


def comparable(entity: Entity, record: Record) -> dict[str, Any]:
    """The part of a record that decides `identical` vs `conflicting`."""
    dumped = record.model_dump(mode="json")
    drop = set(entity.ignored) | {"trash_batch_id"}
    if entity is ARTWORKS:
        drop.add("document_version")  # a no-op save on one side is not a conflict
    if "document" in dumped:
        dumped["document"] = canonical_document(entity, dumped["document"])
    return {k: v for k, v in dumped.items() if k not in drop}


def canonical_document(entity: Entity, raw: Any) -> Any:
    """A document parsed and dumped again, so both sides of a comparison read the same.

    A row saved before a field existed does not carry its default, while the same document read
    back through the schema does — comparing one against the other calls every such artwork a
    conflict. Migrating both sides makes `identical` mean *the same document*, which is the
    question being asked. A document that does not parse is compared as it is.
    """
    if not isinstance(raw, dict):
        return raw
    try:
        if entity is ARTWORKS:
            return document_schema.parse_document(raw).canonical()
        if entity is FRAME_STYLES:
            return template_schema.FrameStyleDocument.model_validate(raw).model_dump(mode="json")
        if entity is LAYOUTS:
            return template_schema.LayoutDocument.model_validate(raw).model_dump(mode="json")
    except ValueError, ValidationError:
        return raw
    return raw


def identity_of(entity: Entity, record: Record) -> str:
    return "\x1f".join(str(getattr(record, field)) for field in entity.identity)


def imported_name(name: str) -> str:
    return f"{name}{IMPORTED_SUFFIX}" if name else IMPORTED_SUFFIX.strip()


# ---- published schemas -------------------------------------------------------------------------
def json_schemas() -> dict[str, dict[str, Any]]:
    """`docs/schemas/archive/*.json` — the manifest plus one schema per JSONL entity."""
    base = "https://the-frame-v2/schemas/archive/"
    schemas: dict[str, dict[str, Any]] = {}
    models: list[tuple[str, type[BaseModel], str]] = [
        ("manifest.v1.json", Manifest, "Archive manifest v1")
    ]
    models += [
        (f"{entity.kind}.v1.json", entity.model, f"Archive {entity.kind} record v1")
        for entity in ENTITIES
    ]
    for filename, model, title in models:
        schema = model.model_json_schema(mode="validation")
        schema.update(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": base + filename,
                "title": title,
            }
        )
        schemas[filename] = schema
    return schemas
