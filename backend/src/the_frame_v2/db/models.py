"""SQLAlchemy models. Spec: docs/data-model.md. Every change requires an Alembic migration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Dialect,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from the_frame_v2.ids import new_id, utcnow


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes stored as sortable ISO-8601 strings."""

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def process_result_value(self, value: str | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))


class Base(DeclarativeBase):
    type_annotation_map = {datetime: UTCDateTime(), dict[str, Any]: JSON, list[Any]: JSON}


def _id() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=new_id)


# ---- Photos -----------------------------------------------------------------------------------


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[str] = _id()
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    content_fingerprint: Mapped[str | None] = mapped_column(String(64))
    """SHA-256 ignoring EXIF (imaging/fingerprint.py); NULL only until the startup backfill."""
    ext: Mapped[str] = mapped_column(String(8))
    mime: Mapped[str] = mapped_column(String(64))
    original_filename: Mapped[str] = mapped_column(String(512))
    file_size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    exif_orientation: Mapped[int] = mapped_column(Integer, default=1)
    bit_depth: Mapped[int] = mapped_column(Integer, default=8)
    icc_description: Mapped[str | None] = mapped_column(String(256))
    is_wide_gamut: Mapped[bool] = mapped_column(Boolean, default=False)
    has_gain_map: Mapped[bool] = mapped_column(Boolean, default=False)
    taken_at: Mapped[datetime | None]
    camera_make: Mapped[str | None] = mapped_column(String(128))
    camera_model: Mapped[str | None] = mapped_column(String(128))
    lens: Mapped[str | None] = mapped_column(String(128))
    gps_lat: Mapped[float | None] = mapped_column(Float)
    gps_lon: Mapped[float | None] = mapped_column(Float)
    place_name: Mapped[str | None] = mapped_column(String(256))
    place_admin1: Mapped[str | None] = mapped_column(String(256))
    place_country: Mapped[str | None] = mapped_column(String(128))
    uploaded_by_device_id: Mapped[str | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL")
    )
    imported_at: Mapped[datetime] = mapped_column(default=utcnow)
    inbox_state: Mapped[str] = mapped_column(String(16), default="inbox")
    quality_warnings: Mapped[list[Any]] = mapped_column(default=list)
    deleted_at: Mapped[datetime | None]
    trash_batch_id: Mapped[str | None] = mapped_column(String(36))

    __table_args__ = (
        Index("ix_photos_imported", "imported_at", "id"),
        Index("ix_photos_inbox", "inbox_state", "imported_at"),
        Index("ix_photos_taken", "taken_at"),
        Index("ux_photos_content_fingerprint", "content_fingerprint", unique=True),
        Index("ix_photos_deleted", "deleted_at"),
    )


class PhotoHashAlias(Base):
    """SHA-256 of another copy of a photo (e.g. GPS-redacted) merged into it: re-uploads dedupe."""

    __tablename__ = "photo_hash_aliases"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    photo_id: Mapped[str] = mapped_column(ForeignKey("photos.id", ondelete="CASCADE"), index=True)


class PhotoTag(Base):
    __tablename__ = "photo_tags"

    photo_id: Mapped[str] = mapped_column(
        ForeignKey("photos.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class PhotoPendingMeta(Base):
    """Metadata chosen at upload time, applied when artworks are created from the photo."""

    __tablename__ = "photo_pending_meta"

    photo_id: Mapped[str] = mapped_column(
        ForeignKey("photos.id", ondelete="CASCADE"), primary_key=True
    )
    collection_ids: Mapped[list[Any]] = mapped_column(default=list)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[str] = _id()
    name: Mapped[str] = mapped_column(String(128, collation="NOCASE"), unique=True)
    color: Mapped[str | None] = mapped_column(String(9))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


# ---- Artworks ---------------------------------------------------------------------------------


class Artwork(Base):
    __tablename__ = "artworks"

    id: Mapped[str] = _id()
    title: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    document: Mapped[dict[str, Any]] = mapped_column(default=dict)
    document_version: Mapped[int] = mapped_column(Integer, default=1)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    worst_tier: Mapped[str | None] = mapped_column(String(16))
    min_scale: Mapped[float | None] = mapped_column(Float)
    max_scale: Mapped[float | None] = mapped_column(Float)
    photo_count: Mapped[int] = mapped_column(Integer, default=0)
    is_incomplete: Mapped[bool] = mapped_column(Boolean, default=False)
    origin_style_id: Mapped[str | None] = mapped_column(String(36))
    origin_style_revision: Mapped[int | None] = mapped_column(Integer)
    origin_layout_id: Mapped[str | None] = mapped_column(String(36))
    origin_layout_revision: Mapped[int | None] = mapped_column(Integer)
    render_hash: Mapped[str | None] = mapped_column(String(64))
    rendered_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None]
    trash_batch_id: Mapped[str | None] = mapped_column(String(36))

    __table_args__ = (
        Index("ix_artworks_created", "created_at", "id"),
        Index("ix_artworks_updated", "updated_at", "id"),
        Index("ix_artworks_deleted", "deleted_at"),
        Index("ix_artworks_title", "title", "id"),
    )


class ArtworkPhoto(Base):
    __tablename__ = "artwork_photos"

    artwork_id: Mapped[str] = mapped_column(
        ForeignKey("artworks.id", ondelete="CASCADE"), primary_key=True
    )
    slot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    photo_id: Mapped[str] = mapped_column(ForeignKey("photos.id", ondelete="CASCADE"), index=True)


class ArtworkTag(Base):
    __tablename__ = "artwork_tags"

    artwork_id: Mapped[str] = mapped_column(
        ForeignKey("artworks.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class ArtworkSnapshot(Base):
    __tablename__ = "artwork_snapshots"

    id: Mapped[str] = _id()
    artwork_id: Mapped[str] = mapped_column(
        ForeignKey("artworks.id", ondelete="CASCADE"), index=True
    )
    document: Mapped[dict[str, Any]]
    document_version: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


# ---- Collections ------------------------------------------------------------------------------


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[str] = _id()
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    date_start: Mapped[str | None] = mapped_column(String(10))
    date_end: Mapped[str | None] = mapped_column(String(10))
    cover_artwork_id: Mapped[str | None] = mapped_column(
        ForeignKey("artworks.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(16), default="manual")
    filter: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    position: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class CollectionItem(Base):
    __tablename__ = "collection_items"

    collection_id: Mapped[str] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    )
    artwork_id: Mapped[str] = mapped_column(
        ForeignKey("artworks.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    position: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (Index("ix_collection_items_order", "collection_id", "position"),)


# ---- Templates & swatches ---------------------------------------------------------------------


class FrameStyle(Base):
    __tablename__ = "frame_styles"

    id: Mapped[str] = _id()
    name: Mapped[str] = mapped_column(String(128))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    document: Mapped[dict[str, Any]]
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Layout(Base):
    __tablename__ = "layouts"

    id: Mapped[str] = _id()
    name: Mapped[str] = mapped_column(String(128))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    document: Mapped[dict[str, Any]]
    slot_count: Mapped[int] = mapped_column(Integer, default=1)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Swatch(Base):
    __tablename__ = "swatches"

    id: Mapped[str] = _id()
    color: Mapped[str] = mapped_column(String(9))
    name: Mapped[str] = mapped_column(String(64), default="")
    position: Mapped[float] = mapped_column(Float, default=0.0)


# ---- Devices & auth ---------------------------------------------------------------------------


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = _id()
    name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))  # uploader | admin
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]


class PairingCode(Base):
    __tablename__ = "pairing_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    role: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]


class SetupCode(Base):
    __tablename__ = "setup_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]


class UploadSession(Base):
    __tablename__ = "upload_sessions"

    id: Mapped[str] = _id()
    device_key: Mapped[str] = mapped_column(String(64))
    """Device id, `localhost` for trusted local requests, or `localsend:<localsend device id>`."""
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(512))
    mime: Mapped[str] = mapped_column(String(128), default="")
    received_bytes: Mapped[int] = mapped_column(Integer, default=0)
    pending_meta: Mapped[dict[str, Any]] = mapped_column(default=dict)
    state: Mapped[str] = mapped_column(String(16), default="open")
    """open | processing | failed"""
    error: Mapped[str | None] = mapped_column(String(128))
    job_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]

    __table_args__ = (Index("ix_upload_sessions_lookup", "device_key", "sha256", "size", "state"),)


class LocalSendDevice(Base):
    """A phone/computer sending through the LocalSend protocol (identified by its fingerprint)."""

    __tablename__ = "localsend_devices"

    id: Mapped[str] = _id()
    fingerprint: Mapped[str] = mapped_column(String(128), unique=True)
    alias: Mapped[str] = mapped_column(String(128))
    device_model: Mapped[str | None] = mapped_column(String(128))
    device_type: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    """pending (asks an admin) | approved (auto-accepted) | blocked (always rejected)"""
    last_ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime | None]
    decided_at: Mapped[datetime | None]


# ---- Infrastructure ---------------------------------------------------------------------------


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = _id()
    kind: Mapped[str] = mapped_column(String(32))
    lane: Mapped[str] = mapped_column(String(16))
    coalesce_key: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    state: Mapped[str] = mapped_column(String(16), default="queued")
    """queued | running | done | failed | cancelled"""
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    __table_args__ = (
        Index("ix_jobs_claim", "lane", "state", "created_at"),
        Index("ix_jobs_coalesce", "coalesce_key", "state"),
    )


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
