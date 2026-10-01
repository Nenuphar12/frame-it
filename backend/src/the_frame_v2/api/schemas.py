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
    """Its own colour; when null the UI shows its category's (`TagCategoryOut.color`)."""
    category_id: str | None = None
    """Its category, or null ("Other")."""


class TagWithCount(TagOut):
    photo_count: int
    artwork_count: int = 0
    """Live artworks carrying it — their own tag or one of their photos' — i.e. what the tag
    filter returns (docs/organization.md §1)."""
    own_artwork_count: int = 0
    """Live artworks it is attached to directly: what deleting it detaches from artworks."""
    last_used_at: datetime | None = None


TagSort = Literal["usage", "recent", "name"]


class TagCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    category_id: str | None = None
    """Category of a *new* tag; an existing tag with this name keeps its own."""


class TagUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    color: str | None = Field(default=None, max_length=9)
    """`#rrggbb`, `#rrggbbaa`, or `""` to clear it."""
    category_id: str | None = None
    """A category id, or null for "Other". Left alone when the field is absent."""


class TagMergeIn(BaseModel):
    """Move every use of `source_ids` onto this tag; the sources disappear."""

    source_ids: list[str] = Field(min_length=1, max_length=100)


class TagsCategorizeIn(BaseModel):
    """Move many tags into one category (null ⇒ "Other")."""

    tag_ids: list[str] = Field(min_length=1, max_length=500)
    category_id: str | None = None


class TagCategoryOut(ApiModel):
    id: str
    name: str
    color: str | None
    position: float
    tag_count: int = 0


class TagCategoryCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    color: str | None = Field(default=None, max_length=9)


class TagCategoryUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    color: str | None = Field(default=None, max_length=9)
    """`#rrggbb`, `#rrggbbaa`, or `""` to clear it."""


class BulkTagIn(BaseModel):
    """Additive: `add` and `remove` name tags, nothing else is touched (docs/organization.md §1)."""

    add: list[str] = Field(default_factory=list, max_length=200)
    remove: list[str] = Field(default_factory=list, max_length=200)


class PhotoTagsIn(BulkTagIn):
    photo_ids: list[str] = Field(min_length=1, max_length=1000)


class ArtworkTagsIn(BulkTagIn):
    artwork_ids: list[str] = Field(min_length=1, max_length=1000)
    """`remove` only reaches an artwork's own tags: an inherited one belongs to a photo."""


class PlaceOut(ApiModel):
    """One level of the Places view: a country, a region in it, or a place in that region."""

    name: str
    photo_count: int
    artwork_count: int
    """Live artworks using at least one photo from here."""
    children: list[PlaceOut] = Field(default_factory=list)


class PlacesOut(ApiModel):
    countries: list[PlaceOut]
    unplaced_photos: int
    """Live photos without a place (no GPS — e.g. Android's photo picker strips it)."""
    unlocated_artworks: int
    """Live artworks none of whose photos has a GPS position: `place near` never matches them."""


class PlaceMatchOut(ApiModel):
    """A place of the offline dataset, for the `place near` picker."""

    name: str
    admin1: str
    country: str
    lat: float
    lon: float
    photo_count: int
    """Live photos the library has at this place (the picker lists those first)."""


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
    draft_artwork_ids: list[str] = Field(default_factory=list)
    """Live **draft** artworks using it, oldest first. A photo stays in the inbox until one of its
    artworks is marked ready, so the inbox offers to open the draft instead of making another."""


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
    """Its own tags — the ones that can be removed from it."""
    inherited_tags: list[TagOut] = Field(default_factory=list)
    """Tags of its photos that are not its own: it carries them too (filters, search), but they
    are removed from the photo, not from the artwork (docs/organization.md §1)."""


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


# ---- jobs (the activity centre) ------------------------------------------------------------------


class JobOut(ApiModel):
    """One background job. `code` is the stable problem code when the handler raised one."""

    id: str
    kind: str
    lane: str
    state: str
    attempts: int
    progress: float
    error: str | None = None
    code: str | None = None
    subject_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    retriable: bool


class JobListOut(ApiModel):
    jobs: list[JobOut]
    failed: int


class JobRetryOut(ApiModel):
    job_id: str


class JobDismissAllOut(ApiModel):
    dismissed: int


# ---- Display targets (Phase 12) ----------------------------------------------------------------


class DisplayTargetIn(BaseModel):
    name: str = Field(default="", max_length=128)
    host: str = Field(min_length=3, max_length=64)
    mac: str | None = Field(default=None, max_length=32)
    """From discovery: what recognises the TV when DHCP moves it."""
    model: str | None = Field(default=None, max_length=128)


class DisplayTargetUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    host: str | None = Field(default=None, max_length=64)
    slideshow_minutes: int | None = None
    """0 = "Don't change" (show the first, rotate nothing, delete nothing), or one of the
    intervals the TV accepts (`GET /display/capabilities`)."""
    slideshow_ordered: bool | None = None
    render_format: Literal["jpg", "png"] | None = None


class DisplaySourceIn(BaseModel):
    """The set this TV should show — the same query shape the artwork grid uses."""

    filter: dict[str, Any] | None = None
    collection_id: str | None = None
    include_nested: bool = False
    favorite: bool | None = None
    status: str | None = None
    """`"ready"` leaves the drafts out (for an explicit `artwork_ids` list too)."""
    sort: str = "created_desc"
    artwork_ids: list[str] = Field(default_factory=list, max_length=200)
    label: str | None = Field(default=None, max_length=256)


class DisplayPushIn(BaseModel):
    allow_delete_foreign: bool = False
    """Delete items on the TV this app did not upload. The UI asks first, every time. Ignored when
    the target does not rotate (`slideshow_minutes = 0`): such a push deletes nothing."""
    slideshow_minutes: int | None = None
    """Saved on the target before the push is queued (same values as `PATCH`)."""
    slideshow_ordered: bool | None = None


DisplayPhase = Literal["queued", "rendering", "uploading", "removing", "starting"]


class DisplayProgressOut(ApiModel):
    """How far the running push is (`display.progress` carries the same, plus `target_id`)."""

    job_id: str
    phase: DisplayPhase
    done: int
    total: int


class DisplayPushResultOut(ApiModel):
    """What a push did (`display.pushed` carries the same)."""

    target_id: str
    mode: Literal["slideshow", "static"]
    uploaded: int
    reused: int
    deleted_ours: int
    deleted_foreign: int
    foreign_remaining: int
    """Slideshow mode: photos this app did not send, still there — and shown between ours."""
    foreign_on_tv: int = 0
    left_ours: int = 0
    """"Don't change": images sent before, left on the TV."""
    total: int
    slideshow_minutes: int | None = None
    first_content_id: str | None = None
    moved_from: str | None = None
    moved_to: str | None = None
    """The TV answered at a new address (same MAC): the target followed it."""
    warnings: list[str] = Field(default_factory=list)
    finished_at: datetime | None = None


class DisplayTargetOut(ApiModel):
    id: str
    name: str
    host: str
    mac: str | None = None
    model: str | None = None
    api_version: str | None = None
    state: str
    last_error: str | None = None
    source_label: str | None = None
    source: dict[str, Any] | None = None
    slideshow_minutes: int
    """0 = "Don't change"."""
    slideshow_ordered: bool
    render_format: str
    paired: bool
    item_count: int
    """Images this app put on the TV and believes are still there."""
    set_count: int = 0
    """Of those, the ones in the current set."""
    ours_count: int | None = None
    """As the TV last said (`checked_at`); None until it was asked."""
    foreign_count: int | None = None
    checked_at: datetime | None = None
    last_result: DisplayPushResultOut | None = None
    progress: DisplayProgressOut | None = None
    created_at: datetime
    last_pushed_at: datetime | None = None
    last_seen_at: datetime | None = None


class DisplayTargetListOut(ApiModel):
    targets: list[DisplayTargetOut]


class DisplayStatusOut(ApiModel):
    """What the TV reports right now, next to what this app believes it put there."""

    target: DisplayTargetOut
    art_mode: bool
    my_pictures: int
    store_items: int
    ours: int
    foreign: int
    slideshow_minutes: int | None = None
    slideshow_ordered: bool = False
    current_content_id: str | None = None
    moved_from: str | None = None
    """Set when the TV no longer answered at its old address and was found at `target.host`."""


class DisplayPushOut(ApiModel):
    job_id: str


class DisplayPlanIn(BaseModel):
    """A dry run: what pushing this source would do. Nothing on the TV changes."""

    source: DisplaySourceIn | None = None
    """None: the target's current set."""
    slideshow_minutes: int | None = None
    """None: the target's setting."""
    check_tv: bool = True
    """Ask the TV what it holds (a few seconds); otherwise the app's own map is believed."""


class DisplayPlanOut(ApiModel):
    mode: Literal["slideshow", "static"]
    set_count: int
    to_upload: int
    already_there: int
    ours_to_remove: int
    """Slideshow mode: images sent before that leave the TV."""
    ours_left: int
    """"Don't change": images sent before that stay where they are."""
    foreign: int | None = None
    """Photos this app did not send; None when unknown (the TV did not answer, nothing cached)."""
    foreign_checked_at: datetime | None = None
    tv_error: str | None = None
    """Problem code when the TV could not be asked; the numbers then come from the app's map."""
    drafts: int
    """Drafts in the source, whatever `status` says."""
    drafts_left_out: int
    moved_from: str | None = None
    moved_to: str | None = None


class DisplayCapabilitiesOut(ApiModel):
    """What this TV generation can do — measured, not assumed (`docs/tv-display.md`)."""

    slideshow_minutes: list[int]
    """The intervals the TV's slideshow accepts (anything else answers -7)."""
    static_display: bool = True
    """`slideshow_minutes = 0` is "Don't change": the first image stays, nothing is deleted."""
    max_set: int
    scoped_slideshow: bool = False
    """False everywhere so far: a Frame plays a whole category, so a push mirrors the set."""
    favourites: bool = False
    thumbnails: bool = False


class DiscoveredTvOut(ApiModel):
    host: str
    name: str | None = None
    model: str | None = None
    model_code: str | None = None
    frame_support: bool
    token_auth: bool
    mac: str | None = None
    target_id: str | None = None
    """Already added: the target it is."""
    recommended: bool = False
    """The first Frame not added yet — what the Add-TV dialog pre-selects."""


class DisplayDiscoverOut(ApiModel):
    subnet: str | None = None
    """The /24 swept (`192.168.1`), None when no LAN address could be told."""
    tvs: list[DiscoveredTvOut]
