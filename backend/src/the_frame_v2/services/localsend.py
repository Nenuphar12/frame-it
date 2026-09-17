"""LocalSend receiving: device approval, transfer sessions, hand-off to the ingest pipeline.

- Senders are identified by the fingerprint they announce. Unknown or pending devices wait for an
  admin decision in the web UI (`localsend.request` event); approved devices are auto-accepted;
  blocked devices are rejected.
- Only supported image files are accepted; files whose SHA-256 is already known are skipped.
- A received file becomes an `UploadSession` in state `processing` and goes through the regular
  `ingest` job (same dedupe/merge/inbox behaviour as browser uploads).

Spec: docs/localsend.md.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from the_frame_v2.context import AppContext
from the_frame_v2.db.models import LocalSendDevice, UploadSession
from the_frame_v2.errors import ProblemError, not_found
from the_frame_v2.events import Event
from the_frame_v2.ids import new_id, utcnow
from the_frame_v2.localsend.dto import DeviceInfo, FileOffer
from the_frame_v2.services import photo_copies

DEVICE_KEY_PREFIX = "localsend:"
ACCEPTED_EXTENSIONS = {"jpg", "jpeg", "png", "avif"}
ACCEPTED_MIMES = {"image/jpeg", "image/png", "image/avif"}
MAX_PENDING_REQUESTS = 10
SESSION_IDLE_SECONDS = 3600
DEVICE_STATUSES = ("pending", "approved", "blocked")


class LocalSendRejection(Exception):  # noqa: N818 — maps 1:1 to protocol status codes
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


# ---- devices ------------------------------------------------------------------------------------
def list_devices(session: Session) -> list[LocalSendDevice]:
    return list(session.scalars(select(LocalSendDevice).order_by(LocalSendDevice.alias)))


def touch_device(session: Session, info: DeviceInfo, ip: str) -> LocalSendDevice:
    fingerprint = info.fingerprint.strip()
    if not fingerprint:
        raise LocalSendRejection(400, "Missing fingerprint")
    device = session.scalars(
        select(LocalSendDevice).where(LocalSendDevice.fingerprint == fingerprint)
    ).first()
    if device is None:
        device = LocalSendDevice(fingerprint=fingerprint, alias="", status="pending")
        session.add(device)
    device.alias = (info.alias or "LocalSend device")[:128]
    device.device_model = info.device_model
    device.device_type = info.device_type
    device.last_ip = ip
    device.last_seen_at = utcnow()
    session.flush()
    return device


def set_device_status(session: Session, device_id: str, status: str) -> LocalSendDevice:
    if status not in DEVICE_STATUSES:
        raise ProblemError(422, "invalid_status", "Invalid status")
    device = session.get(LocalSendDevice, device_id)
    if device is None:
        raise not_found("LocalSend device")
    device.status = status
    device.decided_at = utcnow()
    return device


def forget_device(session: Session, device_id: str) -> None:
    device = session.get(LocalSendDevice, device_id)
    if device is None:
        raise not_found("LocalSend device")
    session.delete(device)


# ---- files --------------------------------------------------------------------------------------
def safe_filename(name: str) -> str:
    """Last path component of a sender-provided name (folders are sent as `dir/file.jpg`)."""
    base = PureWindowsPath(PurePosixPath(name).name).name
    return base.replace("\x00", "")[:512] or "localsend"


def is_supported(offer: FileOffer) -> bool:
    ext = safe_filename(offer.file_name).rsplit(".", 1)[-1].lower()
    if "." in offer.file_name and ext in ACCEPTED_EXTENSIONS:
        return True
    return offer.file_type.lower() in ACCEPTED_MIMES


@dataclass(frozen=True, slots=True)
class Selection:
    accepted: dict[str, FileOffer]
    duplicates: int
    unsupported: int


def select_files(session: Session, offers: dict[str, FileOffer], max_bytes: int) -> Selection:
    candidates = {
        fid: o for fid, o in offers.items() if is_supported(o) and 0 < o.size <= max_bytes
    }
    hashes = [o.sha256.lower() for o in candidates.values() if o.sha256]
    known = photo_copies.photo_ids_for_hashes(session, hashes) if hashes else {}
    accepted = {
        fid: o for fid, o in candidates.items() if not (o.sha256 and o.sha256.lower() in known)
    }
    return Selection(
        accepted=accepted,
        duplicates=len(candidates) - len(accepted),
        unsupported=len(offers) - len(candidates),
    )


# ---- in-memory state (approvals and transfer sessions) ------------------------------------------
@dataclass(slots=True)
class PendingRequest:
    id: str
    device_id: str
    alias: str
    device_model: str | None
    ip: str
    file_count: int
    total_bytes: int
    created_at: str
    future: asyncio.Future[bool]

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "device_id": self.device_id,
            "alias": self.alias,
            "device_model": self.device_model,
            "ip": self.ip,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class ReceiveFile:
    offer: FileOffer
    token: str
    state: str = "waiting"
    """waiting | receiving | done"""


@dataclass(slots=True)
class ReceiveSession:
    id: str
    device_id: str
    ip: str
    files: dict[str, ReceiveFile]
    touched: float = field(default_factory=time.monotonic)

    @property
    def finished(self) -> bool:
        return all(f.state == "done" for f in self.files.values())


class LocalSendHub:
    """Thread-safe registry of pending approvals and active transfer sessions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, PendingRequest] = {}
        self._sessions: dict[str, ReceiveSession] = {}

    # approvals
    def pending(self) -> list[PendingRequest]:
        with self._lock:
            return sorted(self._pending.values(), key=lambda r: r.created_at)

    async def request_approval(
        self,
        ctx: AppContext,
        device: LocalSendDevice,
        selection: Selection,
    ) -> bool:
        with self._lock:
            request = next((r for r in self._pending.values() if r.device_id == device.id), None)
            if request is None:
                if len(self._pending) >= MAX_PENDING_REQUESTS:
                    raise LocalSendRejection(429, "Too many pending requests")
                request = PendingRequest(
                    id=new_id(),
                    device_id=device.id,
                    alias=device.alias,
                    device_model=device.device_model,
                    ip=device.last_ip or "",
                    file_count=len(selection.accepted),
                    total_bytes=sum(o.size for o in selection.accepted.values()),
                    created_at=utcnow().isoformat(),
                    future=asyncio.get_running_loop().create_future(),
                )
                self._pending[request.id] = request
                ctx.broker.publish(Event("localsend.request", request.public()))
        try:
            timeout = ctx.settings.localsend_approval_timeout_seconds
            return await asyncio.wait_for(asyncio.shield(request.future), timeout)
        except TimeoutError:
            self._close(ctx, request.id, approved=False)
            return False

    def decide(self, ctx: AppContext, request_id: str, approve: bool) -> PendingRequest:
        with self._lock:
            request = self._pending.get(request_id)
        if request is None:
            raise not_found("LocalSend request")
        with ctx.db.session() as s:
            if approve:
                set_device_status(s, request.device_id, "approved")
        self._close(ctx, request_id, approved=approve)
        return request

    def _close(self, ctx: AppContext, request_id: str, *, approved: bool) -> None:
        with self._lock:
            request = self._pending.pop(request_id, None)
        if request is None:
            return
        loop = request.future.get_loop()

        def resolve() -> None:
            if not request.future.done():
                request.future.set_result(approved)

        with contextlib.suppress(RuntimeError):  # loop closed: nobody is waiting any more
            loop.call_soon_threadsafe(resolve)
        ctx.broker.publish(
            Event("localsend.request_closed", {"id": request_id, "approved": approved})
        )

    # sessions
    def open_session(
        self, device_id: str, ip: str, accepted: dict[str, FileOffer]
    ) -> ReceiveSession:
        session = ReceiveSession(
            id=new_id(),
            device_id=device_id,
            ip=ip,
            files={fid: ReceiveFile(o, secrets.token_urlsafe(24)) for fid, o in accepted.items()},
        )
        with self._lock:
            now = time.monotonic()
            for sid in [
                s for s, v in self._sessions.items() if now - v.touched > SESSION_IDLE_SECONDS
            ]:
                del self._sessions[sid]
            self._sessions[session.id] = session
        return session

    def claim_file(
        self, session_id: str, file_id: str, token: str, ip: str
    ) -> tuple[ReceiveSession, ReceiveFile]:
        with self._lock:
            session = self._sessions.get(session_id)
            item = session.files.get(file_id) if session else None
            if session is None or item is None:
                raise LocalSendRejection(403, "Invalid session or file")
            if session.ip != ip or not secrets.compare_digest(item.token, token):
                raise LocalSendRejection(403, "Invalid token or IP address")
            if item.state != "waiting":
                raise LocalSendRejection(409, "File already received")
            item.state = "receiving"
            session.touched = time.monotonic()
            return session, item

    def release_file(self, session: ReceiveSession, item: ReceiveFile, *, done: bool) -> None:
        with self._lock:
            item.state = "done" if done else "waiting"
            if session.finished:
                self._sessions.pop(session.id, None)

    def cancel(self, session_id: str, ip: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.ip != ip:
                return False
            del self._sessions[session_id]
            return True


# ---- received file → ingest ---------------------------------------------------------------------
def temp_path_for(ctx: AppContext) -> tuple[str, Path]:
    upload_id = new_id()
    ctx.storage.uploads.mkdir(parents=True, exist_ok=True)
    return upload_id, ctx.storage.upload_temp_path(upload_id)


def hand_off(
    ctx: AppContext,
    *,
    upload_id: str,
    device_id: str,
    offer: FileOffer,
    sha256: str,
    size: int,
) -> str | None:
    """Queue ingestion of a fully received file. Returns the job id (None for a known file)."""
    temp = ctx.storage.upload_temp_path(upload_id)
    with ctx.db.session() as s:
        if photo_copies.photo_id_for_hash(s, sha256) is not None:
            temp.unlink(missing_ok=True)
            return None
        s.add(
            UploadSession(
                id=upload_id,
                device_key=f"{DEVICE_KEY_PREFIX}{device_id}",
                sha256=sha256,
                size=size,
                filename=safe_filename(offer.file_name),
                mime=offer.file_type[:128],
                received_bytes=size,
                pending_meta={"tag_ids": [], "collection_ids": [], "favorite": False},
                state="processing",
                expires_at=utcnow() + timedelta(hours=ctx.settings.upload_session_ttl_hours),
            )
        )
    job_id = ctx.jobs.enqueue("ingest", {"upload_id": upload_id})
    with ctx.db.session() as s:
        row = s.get(UploadSession, upload_id)
        if row is not None:
            row.job_id = job_id
    return job_id
