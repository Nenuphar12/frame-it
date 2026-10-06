"""Devices, setup codes and pairing codes. Spec: docs/security.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from frame_it.auth.principal import hash_secret
from frame_it.db.models import Device, PairingCode, SetupCode
from frame_it.errors import ProblemError, not_found
from frame_it.ids import new_human_code, new_token, normalize_human_code, utcnow

SETUP_CODE_TTL = timedelta(hours=1)
PAIRING_CODE_TTL = timedelta(minutes=5)
ROLES = ("admin", "uploader")


@dataclass(frozen=True, slots=True)
class IssuedCode:
    code: str
    expires_in_seconds: int


@dataclass(frozen=True, slots=True)
class RegisteredDevice:
    device: Device
    token: str


def _invalid_code() -> ProblemError:
    return ProblemError(400, "invalid_code", "Invalid or expired code")


def has_admin_device(session: Session) -> bool:
    return (
        session.scalars(
            select(Device.id).where(Device.role == "admin", Device.revoked_at.is_(None)).limit(1)
        ).first()
        is not None
    )


def issue_setup_code(session: Session) -> IssuedCode:
    """Create a new single-use setup code, invalidating previous unused ones."""
    session.execute(delete(SetupCode).where(SetupCode.used_at.is_(None)))
    code = new_human_code()
    session.add(SetupCode(code_hash=hash_secret(code), expires_at=utcnow() + SETUP_CODE_TTL))
    return IssuedCode(code, int(SETUP_CODE_TTL.total_seconds()))


def issue_pairing_code(session: Session, role: str) -> IssuedCode:
    if role not in ROLES:
        raise ProblemError(422, "invalid_role", "Invalid role")
    session.execute(delete(PairingCode).where(PairingCode.expires_at < utcnow()))
    code = new_human_code()
    session.add(
        PairingCode(code_hash=hash_secret(code), role=role, expires_at=utcnow() + PAIRING_CODE_TTL)
    )
    return IssuedCode(code, int(PAIRING_CODE_TTL.total_seconds()))


def _create_device(session: Session, name: str, role: str, user_agent: str) -> RegisteredDevice:
    token = new_token()
    device = Device(
        name=name.strip()[:128] or "Device",
        role=role,
        token_hash=hash_secret(token),
        user_agent=user_agent[:512],
        last_seen_at=utcnow(),
    )
    session.add(device)
    session.flush()
    return RegisteredDevice(device, token)


def redeem_setup_code(session: Session, code: str, name: str, user_agent: str) -> RegisteredDevice:
    row = session.get(SetupCode, hash_secret(normalize_human_code(code)))
    if row is None or row.used_at is not None or row.expires_at < utcnow():
        raise _invalid_code()
    row.used_at = utcnow()
    return _create_device(session, name, "admin", user_agent)


def redeem_pairing_code(
    session: Session, code: str, name: str, user_agent: str
) -> RegisteredDevice:
    row = session.get(PairingCode, hash_secret(normalize_human_code(code)))
    if row is None or row.used_at is not None or row.expires_at < utcnow():
        raise _invalid_code()
    row.used_at = utcnow()
    return _create_device(session, name, row.role, user_agent)


def list_devices(session: Session) -> list[Device]:
    return list(
        session.scalars(
            select(Device).where(Device.revoked_at.is_(None)).order_by(Device.created_at)
        )
    )


def get_active_device(session: Session, device_id: str) -> Device:
    device = session.get(Device, device_id)
    if device is None or device.revoked_at is not None:
        raise not_found("Device")
    return device


def update_device(session: Session, device_id: str, name: str | None, role: str | None) -> Device:
    device = get_active_device(session, device_id)
    if name is not None:
        device.name = name.strip()[:128] or device.name
    if role is not None:
        if role not in ROLES:
            raise ProblemError(422, "invalid_role", "Invalid role")
        device.role = role
    return device


def revoke_device(session: Session, device_id: str) -> None:
    device = get_active_device(session, device_id)
    device.revoked_at = utcnow()
