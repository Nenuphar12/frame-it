"""Who is calling: resolved from the device cookie or trusted localhost. Spec: docs/security.md."""

from __future__ import annotations

import hashlib
import ipaddress
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from sqlalchemy import select
from starlette.requests import HTTPConnection

from the_frame_v2.config import Settings
from the_frame_v2.db.models import Device
from the_frame_v2.db.session import Database
from the_frame_v2.ids import utcnow

COOKIE_NAME = "tf_device"
Role = Literal["admin", "uploader"]
_PROXY_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded")
_LAST_SEEN_RESOLUTION = timedelta(minutes=5)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Principal:
    role: Role | None
    via: Literal["device", "localhost", "anonymous"]
    device_id: str | None = None
    device_name: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_authenticated(self) -> bool:
        return self.role is not None

    @property
    def device_key(self) -> str | None:
        """Stable key for per-device resources (upload sessions, events)."""
        if self.device_id:
            return self.device_id
        return "localhost" if self.via == "localhost" else None


ANONYMOUS = Principal(role=None, via="anonymous")


def is_trusted_localhost(conn: HTTPConnection, settings: Settings) -> bool:
    if not settings.effective_trust_localhost or conn.client is None:
        return False
    if any(h in conn.headers for h in _PROXY_HEADERS):
        return False
    try:
        return ipaddress.ip_address(conn.client.host).is_loopback
    except ValueError:
        return False


def resolve_principal(conn: HTTPConnection, settings: Settings, db: Database) -> Principal:
    token = conn.cookies.get(COOKIE_NAME)
    if token:
        with db.session() as s:
            device = s.scalars(
                select(Device).where(
                    Device.token_hash == hash_secret(token), Device.revoked_at.is_(None)
                )
            ).first()
            if device is not None:
                now = utcnow()
                if device.last_seen_at is None or now - device.last_seen_at > _LAST_SEEN_RESOLUTION:
                    device.last_seen_at = now
                role: Role = "admin" if device.role == "admin" else "uploader"
                return Principal(
                    role=role, via="device", device_id=device.id, device_name=device.name
                )
    if is_trusted_localhost(conn, settings):
        return Principal(role="admin", via="localhost")
    return ANONYMOUS
