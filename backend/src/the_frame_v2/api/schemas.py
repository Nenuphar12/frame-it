"""API request/response models (the OpenAPI source of frontend types: `make gen-api`)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from the_frame_v2.domain.composition import BalanceRange, RecipeNode
from the_frame_v2.domain.document import (
    ArtworkDocument,
    CompositionAxis,
    CompositionBorder,
    CompositionCaption,
    CompositionFormat,
    CompositionGutter,
    Placement,
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


class TagCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class CollectionOut(ApiModel):
    id: str
    parent_id: str | None
    name: str
    kind: Literal["manual", "smart"]
    position: float


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
    origin_layout_id: str | None
    render_hash: str | None
    """Hash of the latest completed render (use it to bust image caches)."""
    rendered_at: datetime | None
    created_at: datetime
    updated_at: datetime
    tags: list[TagOut] = Field(default_factory=list)


class ArtworkOut(ArtworkSummaryOut):
    document: ArtworkDocument


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
    border: CompositionBorder | None = None
    caption: CompositionCaption | None = None


class ArtworkCreateIn(BaseModel):
    photo_ids: list[str] = Field(min_length=1, max_length=32)
    """Photos in slot order."""
    style_id: str | None = None
    layout_id: str | None = None
    """Phase 6 path: a hand-placed document with no `composition`, for the Advanced editor."""
    composition: CompositionIn | None = None
    """Parametric layout; mutually exclusive with `layout_id`. Neither ⇒ the defaults of §7."""
    placement: Placement | None = None
    """Single-slot layouts only (default `fit_in_mat`); ignored on the composition path."""
    title: str | None = Field(default=None, max_length=256)


class ArtworkUpdateIn(BaseModel):
    title: str | None = Field(default=None, max_length=256)
    favorite: bool | None = None
    status: ArtworkStatus | None = None
    tag_ids: list[str] | None = Field(default=None, max_length=200)


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
    document: FrameStyleDocument


class LayoutOut(ApiModel):
    id: str
    name: str
    revision: int
    builtin: bool
    slot_count: int
    document: LayoutDocument


class RecipeOut(ApiModel):
    """A catalogue entry: the client solves and draws its picker schemas from this (§6.3)."""

    id: str
    count: int
    name_key: str
    balance: BalanceRange | None
    tree: RecipeNode


class ArtworkDefaultsOut(ApiModel):
    style_id: str
    layout_id: str


class ArtworkDefaultsIn(BaseModel):
    style_id: str
    layout_id: str


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
