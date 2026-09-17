"""API request/response models (the OpenAPI source of frontend types: `make gen-api`)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    total_bytes: int
    created_at: str


class LocalSendDecisionIn(BaseModel):
    approve: bool
