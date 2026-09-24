"""API request/response models (the OpenAPI source of frontend types: `make gen-api`)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from the_frame_v2.domain.archive import Manifest as ArchiveManifest
from the_frame_v2.domain.archive import Policy as ImportPolicy
from the_frame_v2.domain.archive import Scope as ArchiveScope
from the_frame_v2.domain.archive import Status as ImportStatus
from the_frame_v2.domain.composition import BalanceRange, RecipeNode
from the_frame_v2.domain.document import (
    ArtworkDocument,
    CellFormat,
    CompositionAxis,
    CompositionBorder,
    CompositionCaption,
    CompositionFormat,
    CompositionGutter,
)
from the_frame_v2.domain.templates import FrameStyleDocument, LayoutDocument

RoleName = Literal["admin", "uploader"]
InboxState = Literal["inbox", "processed", "dismissed"]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- system -------------------------------------------------------------------------------------


class Capabilities(ApiModel):
    libvips_version: str
    avif: bool
    ultra_hdr: bool
    color_management: bool


class SystemInfo(ApiModel):
    name: str
    version: str
    public_url: str
    capabilities: Capabilities
    max_upload_bytes: int
    upload_chunk_bytes: int


class Me(ApiModel):
    authenticated: bool
    role: RoleName | None
    via: Literal["device", "localhost", "anonymous"]
    device_id: str | None
    device_name: str | None
    setup_required: bool
    """True when no admin device exists and the caller is not trusted (enter the setup code)."""


# ---- auth & devices -----------------------------------------------------------------------------


class CodeRedeemIn(BaseModel):
    code: str = Field(min_length=4, max_length=32)
    device_name: str = Field(default="", max_length=128)


class DeviceOut(ApiModel):
    id: str
    name: str
    role: RoleName
    user_agent: str
    created_at: datetime
    last_seen_at: datetime | None


class DeviceUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    role: RoleName | None = None


class PairingCodeIn(BaseModel):
    role: RoleName = "uploader"


class PairingCodeOut(ApiModel):
    code: str
    role: RoleName
    url: str
    expires_in_seconds: int


# ---- tags & collections -------------------------------------------------------------------------


class TagOut(ApiModel):
    id: str
    name: str
    color: str | None


class TagWithCount(TagOut):
    photo_count: int
    artwork_count: int = 0


class TagCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class TagUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    color: str | None = Field(default=None, max_length=9)
    """`#rrggbb`, `#rrggbbaa`, or `""` to clear it."""


class TagMergeIn(BaseModel):
    """Move every use of `source_ids` onto this tag; the sources disappear."""

    source_ids: list[str] = Field(min_length=1, max_length=100)


CollectionKind = Literal["manual", "smart"]


class CollectionOut(ApiModel):
    id: str
    parent_id: str | None
    name: str
    description: str
    kind: CollectionKind
    position: float
    date_start: str | None
    date_end: str | None
    cover_artwork_id: str | None
    filter: dict[str, Any] | None
    """The saved AST of a smart collection (docs/data-model.md §5.2); `null` for a manual one."""
    item_count: int = 0
    """Artworks in the collection itself."""
    nested_count: int = 0
    """Artworks in the collection and its whole subtree (each counted once)."""
    created_at: datetime
    updated_at: datetime


class CollectionCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    parent_id: str | None = None
    kind: CollectionKind = "manual"
    description: str = Field(default="", max_length=4000)
    filter: dict[str, Any] | None = None
    """Required for a smart collection, refused for a manual one."""


class CollectionUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4000)
    date_start: str | None = Field(default=None, max_length=10)
    date_end: str | None = Field(default=None, max_length=10)
    cover_artwork_id: str | None = None
    """An artwork id, or `""` to clear the cover."""
    filter: dict[str, Any] | None = None


class CollectionMoveIn(BaseModel):
    """Drag and drop: a new parent (`null` = top level) and the sibling to land before."""

    parent_id: str | None = None
    before_id: str | None = None


class CollectionItemsIn(BaseModel):
    artwork_ids: list[str] = Field(min_length=1, max_length=1000)


class CollectionReorderIn(BaseModel):
    artwork_id: str
    before_id: str | None = None
    """`null` puts it last."""


class FilterValidateIn(BaseModel):
    filter: dict[str, Any]


class FilterValidateOut(ApiModel):
    valid: bool
    error: str | None = None
    match_count: int | None = None
    """How many artworks the filter matches right now (only when it is valid)."""


# ---- uploads ------------------------------------------------------------------------------------


class HashCheckIn(BaseModel):
    sha256: list[str] = Field(max_length=1000)


class HashStatusOut(ApiModel):
    sha256: str
    status: Literal["new", "exists", "in_progress"]
    photo_id: str | None = None
    upload_id: str | None = None
    offset: int | None = None


class HashCheckOut(ApiModel):
    results: list[HashStatusOut]


class UploadMetaIn(BaseModel):
    tag_ids: list[str] = Field(default_factory=list, max_length=100)
    collection_ids: list[str] = Field(default_factory=list, max_length=100)
    favorite: bool = False


class UploadCreateIn(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    size: int = Field(gt=0)
    sha256: str = Field(min_length=64, max_length=64)
    mime: str = Field(default="", max_length=128)
    meta: UploadMetaIn | None = None
    """Omitted when resuming keeps the metadata chosen when the upload started."""


class UploadOut(ApiModel):
    status: Literal["open", "processing", "failed", "exists"]
    upload_id: str | None = None
    offset: int = 0
    size: int
    photo_id: str | None = None
    error: str | None = None
    chunk_bytes: int


# ---- photos -------------------------------------------------------------------------------------


class PhotoOut(ApiModel):
    id: str
    sha256: str
    mime: str
    original_filename: str
    file_size: int
    width: int
    height: int
    bit_depth: int
    icc_description: str | None
    is_wide_gamut: bool
    has_gain_map: bool
    taken_at: datetime | None
    camera_make: str | None
    camera_model: str | None
    lens: str | None
    gps_lat: float | None
    gps_lon: float | None
    place_name: str | None
    place_admin1: str | None
    place_country: str | None
    imported_at: datetime
    inbox_state: InboxState
    quality_warnings: list[str]
    tags: list[TagOut] = Field(default_factory=list)


class PhotoPageOut(ApiModel):
    items: list[PhotoOut]
    next_cursor: str | None


class PhotoUpdateIn(BaseModel):
    tag_ids: list[str] | None = Field(default=None, max_length=200)
    inbox_state: InboxState | None = None


class PhotoIdsIn(BaseModel):
    photo_ids: list[str] = Field(min_length=1, max_length=1000)


class CountOut(ApiModel):
    count: int


class LibraryStats(ApiModel):
    inbox: int
    photos: int


# ---- LocalSend ----------------------------------------------------------------------------------

LocalSendDeviceStatus = Literal["pending", "approved", "blocked"]


class LocalSendStatusOut(ApiModel):
    enabled: bool
    running: bool
    discovery: bool
    alias: str
    port: int
    fingerprint: str | None
    error: str | None


class LocalSendDeviceOut(ApiModel):
    id: str
    alias: str
    device_model: str | None
    device_type: str | None
    status: LocalSendDeviceStatus
    last_ip: str | None
    created_at: datetime
    last_seen_at: datetime | None


class LocalSendDeviceUpdateIn(BaseModel):
    status: LocalSendDeviceStatus


class LocalSendRequestOut(ApiModel):
    id: str
    device_id: str
    alias: str
    device_model: str | None
    ip: str
    file_count: int
    known_count: int
    """Offered files already in the library (included in `file_count`)."""
    total_bytes: int
    created_at: str


class LocalSendDecisionIn(BaseModel):
    approve: bool


# ---- artworks & templates -----------------------------------------------------------------------

ArtworkStatus = Literal["draft", "ready"]
Tier = Literal["native", "downscaled", "upscaled"]


class ArtworkSummaryOut(ApiModel):
    id: str
    title: str
    status: ArtworkStatus
    favorite: bool
    document_version: int
    worst_tier: Tier | None
    min_scale: float | None
    max_scale: float | None
    photo_count: int
    is_incomplete: bool
    origin_style_id: str | None
    origin_style_revision: int | None
    origin_layout_id: str | None
    origin_layout_revision: int | None
    """Revision of the template the artwork was made from: below the template's current one,
    the artwork is *outdated* and a push update would change it (docs/templates.md §5)."""
    render_hash: str | None
    """Hash of the latest completed render (use it to bust image caches)."""
    rendered_at: datetime | None
    created_at: datetime
    updated_at: datetime
    tags: list[TagOut] = Field(default_factory=list)


class ArtworkOut(ArtworkSummaryOut):
    document: ArtworkDocument
    collection_ids: list[str] = Field(default_factory=list)
    """Manual collections holding this artwork — the ones it can be added to and removed from.

    Only on the single-artwork response: a list would pay a join per row for something the grid
    does not show."""
    smart_collection_ids: list[str] = Field(default_factory=list)
    """Smart collections whose filter currently matches it. Derived, so read-only: the artwork
    leaves one by stopping to match, never by being removed from it."""


class ArtworkPageOut(ApiModel):
    items: list[ArtworkSummaryOut]
    next_cursor: str | None


class CompositionIn(BaseModel):
    """Parameters of a new parametric artwork (docs/simple-editor.md §7): all optional.

    Same fields as the document's `composition` block, minus `detached` (a new artwork never is).
    `recipe` defaults to the first catalogue entry for the number of photos, `format` to
    `original` for a single photo and `fill` above.
    """

    model_config = ConfigDict(extra="forbid")

    recipe: str | None = None
    balance: float | None = Field(default=None, ge=0, le=1)
    outer: CompositionAxis | None = None
    gutter: CompositionGutter | None = None
    format: CompositionFormat | None = None
    cell_formats: list[CellFormat | None] | None = None
    """Per-cell override of `format`, in photo order; `null` entries inherit it."""
    border: CompositionBorder | None = None
    caption: CompositionCaption | None = None


class ArtworkCreateIn(BaseModel):
    photo_ids: list[str] = Field(min_length=1, max_length=32)
    """Photos in slot order."""
    style_id: str | None = None
    layout_id: str | None = None
    """A saved layout: its recipe and parameters (docs/templates.md §4). Its cell count must
    match the number of photos."""
    composition: CompositionIn | None = None
    """An explicit parametric layout; mutually exclusive with `layout_id`. Neither ⇒ the
    Settings defaults, then the catalogue (docs/simple-editor.md §7)."""
    title: str | None = Field(default=None, max_length=256)


class ArtworkUpdateIn(BaseModel):
    title: str | None = Field(default=None, max_length=256)
    favorite: bool | None = None
    status: ArtworkStatus | None = None
    tag_ids: list[str] | None = Field(default=None, max_length=200)
    origin_style_id: str | None = None
    origin_layout_id: str | None = None
    """Record which template the artwork now wears (its revision is read from the template).

    The editor applies a template to its working document itself — that is one undoable edit like
    any other — and then says so here, which is what keeps a push update's reach honest.
    """


class SnapshotIn(BaseModel):
    reason: Literal["opened", "manual"] = "manual"


class SnapshotOut(ApiModel):
    id: str
    artwork_id: str
    document_version: int
    reason: str
    created_at: datetime


class RegionIn(BaseModel):
    x: int = Field(ge=0, le=3839)
    y: int = Field(ge=0, le=2159)
    w: int = Field(ge=1, le=1024)
    h: int = Field(ge=1, le=1024)


class RegionRenderIn(BaseModel):
    document: dict[str, Any]
    """Artwork document (possibly unsaved); validated like a save."""
    rect: RegionIn


class FrameStyleOut(ApiModel):
    id: str
    name: str
    revision: int
    builtin: bool
    """Built-in templates are seeded from `assets/presets/` and cannot be edited or deleted."""
    document: FrameStyleDocument


class LayoutOut(ApiModel):
    id: str
    name: str
    revision: int
    builtin: bool
    slot_count: int
    """The recipe's cell count: a layout only fits a selection of that many photos."""
    document: LayoutDocument


class FrameStyleIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    document: FrameStyleDocument


class FrameStyleUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    document: FrameStyleDocument | None = None


class LayoutIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    document: LayoutDocument


class LayoutUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    document: LayoutDocument | None = None


class TemplateNameIn(BaseModel):
    """Naming a copy, or the template "Save as …" is about to create."""

    name: str | None = Field(default=None, min_length=1, max_length=128)


class SaveAsTemplateIn(BaseModel):
    artwork_id: str
    name: str = Field(min_length=1, max_length=128)


class TemplateFileOut(ApiModel):
    """`.tfstyle.json` / `.tflayout.json` (docs/templates.md §6)."""

    kind: Literal["tfstyle", "tflayout"]
    version: int
    name: str
    document: dict[str, Any]


class TemplateImportIn(BaseModel):
    """The contents of a template file, as read by the browser."""

    kind: str
    version: int
    name: str | None = Field(default=None, max_length=128)
    document: dict[str, Any]


class TemplateApplicationOut(ApiModel):
    artwork_id: str
    title: str
    applied: bool
    reason: Literal["slot_count", "detached"] | None
    """Why the artwork was left alone: it holds another number of photos, or its slots were
    placed by hand (a layout would throw that away)."""


class PushUpdateOut(ApiModel):
    dry_run: bool
    applied: int
    skipped: int
    items: list[TemplateApplicationOut]


class ApplyTemplateIn(BaseModel):
    style_id: str | None = None
    layout_id: str | None = None


class RecipeOut(ApiModel):
    """A catalogue entry: the client solves and draws its picker schemas from this (§6.3)."""

    id: str
    count: int
    name_key: str
    balance: BalanceRange | None
    tree: RecipeNode


class ArtworkDefaultsOut(ApiModel):
    style_id: str
    recipe_id: str | None
    """`null` ⇒ the first catalogue entry for the number of photos selected."""
    format: CompositionFormat | None
    """`null` ⇒ `original` for a single photo, `fill` above (docs/simple-editor.md §7)."""


class ArtworkDefaultsIn(BaseModel):
    style_id: str
    recipe_id: str | None = None
    format: CompositionFormat | None = None


# ---- colours ------------------------------------------------------------------------------------


class PaletteEntryOut(ApiModel):
    color: str
    kind: Literal["dominant", "muted", "complementary"]
    weight: float
    """Share of the photo covered by the cluster this colour comes from (0 to 1)."""


class ColorPresetOut(ApiModel):
    name: str
    color: str


class SwatchOut(ApiModel):
    id: str
    color: str
    name: str
    position: float


class SwatchCreateIn(BaseModel):
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    name: str = Field(default="", max_length=64)


class SwatchUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=64)


class SwatchReorderIn(BaseModel):
    ids: list[str] = Field(max_length=200)


class FontMetricsOut(ApiModel):
    weight: int
    units_per_em: int
    ascender: int
    descender: int


class FontOut(ApiModel):
    id: str
    name: str
    category: str
    weights: list[int]
    metrics: list[FontMetricsOut]
    """Per weight, in font units: the editor places baselines like the renderer (§8.1 step 4)."""


class TextureOut(ApiModel):
    id: str
    name: str
    size: int


# ---- trash --------------------------------------------------------------------------------------


class AffectedArtworkOut(ApiModel):
    """One artwork in the cascade dialog: what deleting these photos would do to it."""

    artwork_id: str
    title: str
    slot_count: int
    """Slots of this artwork that use one of the photos."""
    photo_count: int
    """Photos the artwork holds in total — equal to `slot_count` ⇒ nothing would be left."""


class TrashPreviewOut(ApiModel):
    artworks: list[AffectedArtworkOut]


class TrashPhotosIn(BaseModel):
    photo_ids: list[str] = Field(min_length=1, max_length=1000)
    cascade: Literal["trash_artworks", "empty_slots"] = "trash_artworks"
    """What happens to the artworks using them: trash them too, or empty their slots."""


class TrashArtworksIn(BaseModel):
    artwork_ids: list[str] = Field(min_length=1, max_length=1000)


class RestoreIn(BaseModel):
    photo_ids: list[str] = Field(default_factory=list, max_length=1000)
    artwork_ids: list[str] = Field(default_factory=list, max_length=1000)
    batch_ids: list[str] = Field(default_factory=list, max_length=100)
    """Restores everything deleted by the same gesture."""


class TrashResultOut(ApiModel):
    batch_id: str
    photos: int
    artworks: int
    emptied: int


class TrashedPhotoOut(ApiModel):
    id: str
    original_filename: str
    width: int
    height: int
    file_size: int
    deleted_at: datetime | None
    trash_batch_id: str | None


class TrashedArtworkOut(ApiModel):
    id: str
    title: str
    photo_count: int
    render_hash: str | None
    deleted_at: datetime | None
    trash_batch_id: str | None


class TrashOut(ApiModel):
    photos: list[TrashedPhotoOut]
    artworks: list[TrashedArtworkOut]
    photo_total: int
    artwork_total: int
    retention_days: int


class PurgeIn(BaseModel):
    all: bool = False
    """Empty the trash now instead of only purging what is past the retention window."""


class PurgeOut(ApiModel):
    photos: int
    artworks: int
    bytes_freed: int


# ---- library query ------------------------------------------------------------------------------

ArtworkSort = Literal["created_desc", "created_asc", "updated_desc", "title_asc", "manual"]


class ArtworkQueryIn(BaseModel):
    """The filter bar as a POST body: an AST is too big and too nested for a query string."""

    filter: dict[str, Any] | None = None
    collection_id: str | None = None
    include_nested: bool = False
    status: ArtworkStatus | None = None
    favorite: bool | None = None
    photo_id: str | None = None
    q: str | None = Field(default=None, max_length=200)
    sort: ArtworkSort = "created_desc"
    cursor: str | None = None
    limit: int = Field(default=100, ge=1, le=500)


# ---- export / import (docs/archive-format.md) ----------------------------------------------------

ExportKind = Literal["library", "renders"]
JobState = Literal["queued", "running", "done", "failed", "cancelled"]
ImportState = Literal["receiving", "staging", "ready", "applying", "applied", "failed"]


class ExportRequestIn(BaseModel):
    """An empty selection exports the whole library (`scope: full`); anything else is partial."""

    kind: ExportKind = "library"
    artwork_ids: list[str] = Field(default_factory=list, max_length=5000)
    collection_ids: list[str] = Field(default_factory=list, max_length=200)
    include_nested: bool = True
    include_renders: bool = False
    include_templates: bool = True
    render_format: Literal["png", "jpg"] = "jpg"


class ExportOut(ApiModel):
    """An export job. The file is downloadable once `state` is `done`."""

    job_id: str
    kind: ExportKind
    scope: ArchiveScope
    state: JobState
    progress: float
    filename: str | None
    bytes: int | None
    error: str | None
    created_at: datetime


class ImportCreateIn(BaseModel):
    filename: str = Field(max_length=512)
    size: int = Field(gt=0)


class ImportSessionOut(ApiModel):
    import_id: str
    filename: str
    size: int
    offset: int
    state: ImportState
    error: str | None = None
    scope: ArchiveScope | None = None
    chunk_bytes: int
    created_at: datetime
    new_items: int = 0
    conflicting_items: int = 0
    """Totals from the dry run, for a one-line summary; the detail is `GET /imports/{id}/report`."""


class ImportEntryOut(ApiModel):
    kind: str
    key: str
    name: str
    status: ImportStatus
    maps_to: str | None = None


class ImportKindOut(ApiModel):
    kind: str
    total: int
    new: int
    identical: int
    matched: int
    conflicting: int
    items: list[ImportEntryOut] = Field(default_factory=list)


class ImportReportOut(ApiModel):
    """The dry run: what importing this archive would do, kind by kind."""

    manifest: ArchiveManifest
    kinds: list[ImportKindOut]
    warnings: list[str] = Field(default_factory=list)


class ImportPoliciesIn(BaseModel):
    """`default`, overridden per kind, overridden per item (keyed `"<kind>:<identity>"`)."""

    default: ImportPolicy = "keep_mine"
    per_kind: dict[str, ImportPolicy] = Field(default_factory=dict)
    per_item: dict[str, ImportPolicy] = Field(default_factory=dict)


class ImportApplyOut(ApiModel):
    created: dict[str, int]
    updated: dict[str, int]
    skipped: dict[str, int]
    renders_adopted: int
    renders_queued: int
    warnings: list[str]
