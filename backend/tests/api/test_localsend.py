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

from tests.conftest import ctx_of, make_jpeg, sha256
from the_frame_v2.localsend.app import create_localsend_app
from the_frame_v2.localsend.discovery import Discovery, register_over_http
from the_frame_v2.localsend.dto import Announcement
from the_frame_v2.localsend.identity import ensure_identity, fingerprint_of
from the_frame_v2.localsend.runner import LocalSendRunner

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

    # Approved devices are accepted without asking again; known files are skipped (204).
    again = _prepare(phone, [_offer("a", "x.jpg", PHOTO, with_hash=True)])
    assert again.status_code == 204
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

    from the_frame_v2.localsend.app import own_info

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
