"""LocalSend receiver: protocol endpoints, device approval, hand-off to ingest, TLS identity."""

from __future__ import annotations

import asyncio
import hashlib
import http.client
import json
import socket
import ssl
import threading
import time
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from frame_it.db.models import Photo
from frame_it.events import Event
from frame_it.ids import utcnow
from frame_it.localsend.app import create_localsend_app, own_info
from frame_it.localsend.discovery import Discovery, register_over_http
from frame_it.localsend.dto import Announcement
from frame_it.localsend.identity import ensure_identity, fingerprint_of
from frame_it.localsend.runner import LocalSendRunner
from tests.conftest import ctx_of, make_jpeg, sha256

PHONE_IP = "192.168.1.50"
PREFIX = "/api/localsend/v2"
PHOTO = make_jpeg(color=(10, 200, 30))


def _info(fingerprint: str = "PHONE-FP") -> dict[str, Any]:
    return {
        "alias": "Pixel 8 Pro",
        "version": "2.1",
        "deviceModel": "Google",
        "deviceType": "mobile",
        "fingerprint": fingerprint,
        "port": 53317,
        "protocol": "https",
    }


def _offer(
    file_id: str, name: str, data: bytes, mime: str = "image/jpeg", *, with_hash: bool = False
) -> dict[str, Any]:
    return {
        "id": file_id,
        "fileName": name,
        "size": len(data),
        "fileType": mime,
        "sha256": sha256(data) if with_hash else None,
    }


@pytest.fixture
def phone(local: TestClient) -> TestClient:
    ctx = ctx_of(local)
    identity = ensure_identity(ctx.settings.localsend_dir)
    return TestClient(create_localsend_app(ctx, identity, 53317), client=(PHONE_IP, 40000))


def _prepare(phone: TestClient, files: list[dict[str, Any]], **info: Any) -> httpx.Response:
    res: httpx.Response = phone.post(
        f"{PREFIX}/prepare-upload",
        json={"info": _info(**info), "files": {f["id"]: f for f in files}},
    )
    return res


def _prepare_and_decide(
    local: TestClient, phone: TestClient, files: list[dict[str, Any]], *, approve: bool
) -> httpx.Response:
    result: dict[str, httpx.Response] = {}
    thread = threading.Thread(target=lambda: result.update(res=_prepare(phone, files)))
    thread.start()
    hub = ctx_of(local).localsend
    for _ in range(200):
        if hub.pending():
            break
        time.sleep(0.02)
    [request] = local.get("/api/v1/localsend/requests").json()
    assert request["alias"] == "Pixel 8 Pro" and request["file_count"] == 1
    res = local.post(
        f"/api/v1/localsend/requests/{request['id']}/decision", json={"approve": approve}
    )
    assert res.status_code == 204
    thread.join(timeout=10)
    return result["res"]


def _photo_ids(local: TestClient) -> list[str]:
    return [p["id"] for p in local.get("/api/v1/photos").json()["items"]]


def _record_events(local: TestClient, monkeypatch: pytest.MonkeyPatch) -> list[Event]:
    events: list[Event] = []
    monkeypatch.setattr(ctx_of(local).broker, "publish", events.append)
    return events


def _upload(phone: TestClient, body: dict[str, Any], file_id: str, data: bytes) -> httpx.Response:
    params = {"sessionId": body["sessionId"], "fileId": file_id, "token": body["files"][file_id]}
    res: httpx.Response = phone.post(f"{PREFIX}/upload", params=params, content=data)
    return res


def _approve_phone(local: TestClient, phone: TestClient) -> None:
    res = _prepare_and_decide(local, phone, [_offer("warmup", "w.jpg", PHOTO)], approve=True)
    assert res.status_code == 200


def test_info_and_register_expose_the_certificate_fingerprint(
    local: TestClient, phone: TestClient
) -> None:
    ctx = ctx_of(local)
    fingerprint = fingerprint_of((ctx.settings.localsend_dir / "cert.pem").read_bytes())
    info = phone.get(f"{PREFIX}/info").json()
    assert info["fingerprint"] == fingerprint and len(fingerprint) == 64
    assert info["alias"] == ctx.settings.effective_localsend_alias
    assert phone.post(f"{PREFIX}/register", json=_info()).json()["fingerprint"] == fingerprint


def test_new_device_is_approved_then_sends_photos_to_the_inbox(
    local: TestClient, phone: TestClient
) -> None:
    offers = [
        _offer("a", "PXL_20260917_082757358.jpg", PHOTO),
        _offer("clip", "VID_1.mp4", b"x" * 10, "video/mp4"),
        _offer("heic", "IMG_1.heic", b"x" * 10, "image/heic"),
    ]
    res = _prepare_and_decide(local, phone, offers, approve=True)
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body["files"]) == {"a"}

    up = phone.post(
        f"{PREFIX}/upload",
        params={"sessionId": body["sessionId"], "fileId": "a", "token": body["files"]["a"]},
        content=PHOTO,
    )
    assert up.status_code == 200, up.text
    ctx_of(local).jobs.run_pending_sync()

    [photo] = local.get("/api/v1/photos", params={"inbox_state": "inbox"}).json()["items"]
    assert photo["original_filename"] == "PXL_20260917_082757358.jpg"
    assert photo["sha256"] == sha256(PHOTO)
    [device] = local.get("/api/v1/localsend/devices").json()
    assert device["status"] == "approved" and device["last_ip"] == PHONE_IP

    # Approved devices are accepted without asking again.
    other = _prepare(phone, [_offer("b", "b.jpg", make_jpeg(color=(1, 2, 3)))])
    assert other.status_code == 200 and not ctx_of(local).localsend.pending()


def test_declined_device_is_rejected_and_asked_again_next_time(
    local: TestClient, phone: TestClient
) -> None:
    res = _prepare_and_decide(local, phone, [_offer("a", "a.jpg", PHOTO)], approve=False)
    assert res.status_code == 403
    [device] = local.get("/api/v1/localsend/devices").json()
    assert device["status"] == "pending"


def test_unanswered_request_times_out(app_factory: Any) -> None:
    local = app_factory(localsend_approval_timeout_seconds=1)
    ctx = ctx_of(local)
    phone = TestClient(
        create_localsend_app(ctx, ensure_identity(ctx.settings.localsend_dir), 53317),
        client=(PHONE_IP, 40000),
    )
    assert _prepare(phone, [_offer("a", "a.jpg", PHOTO)]).status_code == 403
    assert ctx.localsend.pending() == []


def test_blocked_device_and_unsupported_files_are_rejected(
    local: TestClient, phone: TestClient
) -> None:
    assert _prepare(phone, [_offer("v", "v.mp4", b"1", "video/mp4")]).status_code == 403
    [device] = local.get("/api/v1/localsend/devices").json()
    local.patch(f"/api/v1/localsend/devices/{device['id']}", json={"status": "blocked"})
    assert _prepare(phone, [_offer("a", "a.jpg", PHOTO)]).status_code == 403
    assert local.delete(f"/api/v1/localsend/devices/{device['id']}").status_code == 204
    assert local.get("/api/v1/localsend/devices").json() == []


def test_upload_is_bound_to_token_ip_size_and_checksum(
    local: TestClient, phone: TestClient
) -> None:
    _approve_phone(local, phone)
    body = _prepare(phone, [_offer("a", "a.jpg", PHOTO, with_hash=True)]).json()
    params = {"sessionId": body["sessionId"], "fileId": "a", "token": body["files"]["a"]}

    assert (
        phone.post(
            f"{PREFIX}/upload", params={**params, "token": "nope"}, content=PHOTO
        ).status_code
        == 403
    )
    intruder = TestClient(phone.app, client=("192.168.1.99", 1))
    assert intruder.post(f"{PREFIX}/upload", params=params, content=PHOTO).status_code == 403
    assert phone.post(f"{PREFIX}/upload", params=params, content=PHOTO[:-1]).status_code == 400
    corrupted = PHOTO[:-1] + b"\x00"
    assert phone.post(f"{PREFIX}/upload", params=params, content=corrupted).status_code == 422
    assert phone.post(f"{PREFIX}/upload", params={"sessionId": "x"}).status_code == 400
    assert not list(ctx_of(local).storage.uploads.iterdir())  # failed attempts leave nothing

    assert phone.post(f"{PREFIX}/upload", params=params, content=PHOTO).status_code == 200
    assert phone.post(f"{PREFIX}/upload", params=params, content=PHOTO).status_code == 403  # done


def test_cancel_closes_the_session(local: TestClient, phone: TestClient) -> None:
    _approve_phone(local, phone)
    body = _prepare(phone, [_offer("a", "a.jpg", PHOTO)]).json()
    assert (
        phone.post(f"{PREFIX}/cancel", params={"sessionId": body["sessionId"]}).status_code == 200
    )
    params = {"sessionId": body["sessionId"], "fileId": "a", "token": body["files"]["a"]}
    assert phone.post(f"{PREFIX}/upload", params=params, content=PHOTO).status_code == 403


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def test_runner_serves_tls_with_the_announced_certificate(app_factory: Any) -> None:
    local = app_factory(host="127.0.0.1", localsend_port=_free_port(), localsend_discovery=False)
    ctx = ctx_of(local)

    async def scenario() -> None:
        runner = LocalSendRunner(ctx)
        await runner.start()
        try:
            assert runner.running and runner.identity is not None
            port = ctx.settings.localsend_port

            def fetch() -> tuple[bytes, dict[str, Any], bool]:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                conn = http.client.HTTPSConnection("127.0.0.1", port, context=context, timeout=5)
                conn.request("GET", f"{PREFIX}/info")
                info: dict[str, Any] = json.loads(conn.getresponse().read())
                assert isinstance(conn.sock, ssl.SSLSocket)
                der = conn.sock.getpeercert(binary_form=True)
                assert der is not None
                conn.close()
                assert runner.identity is not None
                registered = register_over_http(runner.identity)(
                    "127.0.0.1", port, "https", {"alias": "x", "fingerprint": "y"}
                )
                return der, info, registered

            der, info, registered = await asyncio.to_thread(fetch)
            fingerprint = hashlib.sha256(der).hexdigest().upper()
            assert fingerprint == runner.identity.fingerprint == info["fingerprint"]
            assert registered
        finally:
            await runner.stop()

    asyncio.run(scenario())


def test_runner_reports_a_busy_port(app_factory: Any) -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        local = app_factory(host="127.0.0.1", localsend_port=port, localsend_discovery=False)
        runner = LocalSendRunner(ctx_of(local))
        asyncio.run(runner.start())
        assert not runner.running and runner.error

        # With discovery the real port is announced, so the next free port is used instead.
        fallback = LocalSendRunner(ctx_of(app_factory(host="127.0.0.1", localsend_port=port)))
        sock = fallback._bind()
        assert sock is not None and sock.getsockname()[1] != port
        sock.close()


def test_discovery_answers_announcements_but_not_itself(local: TestClient) -> None:
    ctx = ctx_of(local)
    identity = ensure_identity(ctx.settings.localsend_dir)
    calls: list[tuple[str, int, str]] = []

    def register(host: str, port: int, protocol: str, body: dict[str, object]) -> bool:
        calls.append((host, port, protocol))
        assert body["fingerprint"] == identity.fingerprint
        return True

    discovery = Discovery(own_info(ctx, identity, 53317), register, port=53317, interface_ip=None)

    async def scenario() -> None:
        announce = {**_info(), "port": 53318, "announce": True}
        discovery.datagram_received(json.dumps(announce).encode(), (PHONE_IP, 53317))
        discovery.datagram_received(
            json.dumps({**announce, "announce": False}).encode(), (PHONE_IP, 1)
        )
        discovery.datagram_received(discovery.message(announce=True), ("127.0.0.1", 53317))
        discovery.datagram_received(b"not json", (PHONE_IP, 53317))
        await asyncio.sleep(0.2)

    asyncio.run(scenario())
    assert calls == [(PHONE_IP, 53318, "https")]
    parsed = Announcement.model_validate_json(discovery.message(announce=True))
    assert parsed.announce and parsed.fingerprint == identity.fingerprint


def _send_photo_once(local: TestClient, phone: TestClient) -> None:
    """Allow the phone, then send PHOTO (`w.jpg`) into the library."""
    res = _prepare_and_decide(local, phone, [_offer("w", "w.jpg", PHOTO)], approve=True)
    assert _upload(phone, res.json(), "w", PHOTO).status_code == 200
    ctx_of(local).jobs.run_pending_sync()


def _send_again(local: TestClient, phone: TestClient, data: bytes, name: str) -> None:
    """Send another new photo from the (already allowed) phone."""
    body = _prepare(phone, [_offer(name, name, data)]).json()
    assert _upload(phone, body, name, data).status_code == 200
    ctx_of(local).jobs.run_pending_sync()


def _photo_state(local: TestClient) -> list[str]:
    return [p["inbox_state"] for p in local.get("/api/v1/photos").json()["items"]]


def _dismiss(local: TestClient) -> None:
    res = local.post("/api/v1/inbox/dismiss", json={"photo_ids": _photo_ids(local)})
    assert res.status_code == 200 and res.json()["count"] > 0
    assert set(_photo_state(local)) == {"dismissed"}


def test_offer_of_already_sent_photos_transfers_one_of_them_for_the_app_to_show_it(
    local: TestClient, phone: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _send_photo_once(local, phone)
    small = make_jpeg(width=80, height=60, color=(5, 5, 5))
    _send_again(local, phone, small, "small.jpg")
    _dismiss(local)
    ctx = ctx_of(local)
    events = _record_events(local, monkeypatch)
    offers = [
        _offer("big", "PXL_1.jpg", PHOTO, with_hash=True),
        _offer("small", "small.jpg", small, with_hash=True),
        _offer("v", "clip.mp4", b"x", "video/mp4"),
    ]

    body = _prepare(phone, offers).json()

    # The app shows a transfer screen only for files it may send: the smallest one is transferred
    # (and dropped) so that a send of already-sent photos looks like any other.
    assert set(body["files"]) == {"small"}
    assert _upload(phone, body, "small", small).status_code == 200
    ctx.jobs.run_pending_sync()

    assert sorted(_photo_state(local)) == ["inbox", "inbox"]  # both are back in the inbox
    assert len(local.get("/api/v1/photos").json()["items"]) == 2  # nothing imported twice
    assert not list(ctx.storage.uploads.iterdir())
    [transfer] = [e for e in events if e.name == "localsend.transfer"]
    files = {f["file_id"]: f for f in transfer.data["files"]}
    assert files["big"]["status"] == "known" and files["small"]["status"] == "known"
    assert files["v"]["status"] == "rejected" and files["v"]["code"] == "unsupported_format"
    assert [e.data["status"] for e in events if e.name == "localsend.file"] == [
        "receiving",
        "known",
    ]
    # Nothing is ingested, so only this event tells open pages to refresh the inbox.
    [updated] = [e for e in events if e.name == "photo.updated"]
    assert sorted(updated.data["photo_ids"]) == sorted(_photo_ids(local))


def test_already_sent_files_of_a_mixed_offer_are_skipped(
    local: TestClient, phone: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _send_photo_once(local, phone)
    _dismiss(local)
    ctx = ctx_of(local)
    events = _record_events(local, monkeypatch)
    new_photo = make_jpeg(color=(200, 10, 10))

    body = _prepare(
        phone,
        [_offer("old", "w.jpg", PHOTO, with_hash=True), _offer("new", "n.jpg", new_photo)],
    ).json()
    assert set(body["files"]) == {"new"}  # the app hides files without a token

    assert _upload(phone, body, "new", new_photo).status_code == 200
    ctx.jobs.run_pending_sync()

    assert sorted(_photo_state(local)) == ["inbox", "inbox"]
    assert ctx.localsend._sessions == {}
    [transfer] = [e for e in events if e.name == "localsend.transfer"]
    assert {f["file_id"]: f["status"] for f in transfer.data["files"]} == {
        "new": "incoming",
        "old": "known",
    }
    statuses = [(e.data["file_id"], e.data["status"]) for e in events if e.name == "localsend.file"]
    assert statuses == [("new", "receiving"), ("new", "processing")]


def test_already_sent_file_without_checksum_is_received_then_dropped(
    local: TestClient, phone: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _send_photo_once(local, phone)
    _dismiss(local)
    ctx = ctx_of(local)
    events = _record_events(local, monkeypatch)

    body = _prepare(phone, [_offer("a", "again.jpg", PHOTO)]).json()

    assert _upload(phone, body, "a", PHOTO).status_code == 200  # a plain success for the app
    assert _photo_state(local) == ["inbox"]
    assert not list(ctx.storage.uploads.iterdir())  # the received copy is dropped
    [known] = [e for e in events if e.name == "localsend.file" and e.data["status"] == "known"]
    assert known.data["photo_id"] and known.data["restored"] is False


def test_sending_a_trashed_photo_again_restores_it(local: TestClient, phone: TestClient) -> None:
    _send_photo_once(local, phone)
    ctx = ctx_of(local)
    with ctx.db.session() as s:
        photo = s.query(Photo).one()
        photo.deleted_at = utcnow()
        photo.inbox_state = "dismissed"
    assert local.get("/api/v1/photos").json()["items"] == []

    res = _prepare(phone, [_offer("a", "w.jpg", PHOTO, with_hash=True)])

    assert res.status_code == 200  # transferred again (and dropped) to show a normal transfer
    assert _photo_state(local) == ["inbox"]


def test_unknown_device_must_be_allowed_before_learning_a_photo_was_sent(
    local: TestClient, phone: TestClient
) -> None:
    _send_photo_once(local, phone)
    ctx = ctx_of(local)
    stranger = TestClient(phone.app, client=("192.168.1.77", 40000))
    result: dict[str, httpx.Response] = {}
    offers = [_offer("a", "w.jpg", PHOTO, with_hash=True)]
    thread = threading.Thread(
        target=lambda: result.update(res=_prepare(stranger, offers, fingerprint="OTHER-FP"))
    )
    thread.start()
    for _ in range(200):
        if ctx.localsend.pending():
            break
        time.sleep(0.02)
    [request] = local.get("/api/v1/localsend/requests").json()
    assert request["file_count"] == 1 and request["known_count"] == 1
    local.post(f"/api/v1/localsend/requests/{request['id']}/decision", json={"approve": False})
    thread.join(timeout=10)
    assert result["res"].status_code == 403
