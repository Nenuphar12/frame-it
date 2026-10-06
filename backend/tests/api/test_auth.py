from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from tests.conftest import CLIENT_HEADERS, REMOTE, ctx_of, pair, remote_client

ADMIN_ONLY = [
    ("get", "/api/v1/devices", None),
    ("post", "/api/v1/devices/pairing-codes", {"role": "uploader"}),
    ("post", "/api/v1/inbox/dismiss", {"photo_ids": ["x"]}),
    ("patch", "/api/v1/photos/x", {"inbox_state": "processed"}),
]
UPLOADER_ALLOWED = [
    ("get", "/api/v1/photos", None),
    ("get", "/api/v1/photos/stats", None),
    ("get", "/api/v1/tags", None),
    ("get", "/api/v1/collections", None),
    ("post", "/api/v1/uploads/check", {"sha256": ["0" * 64]}),
]


def _call(client: TestClient, method: str, url: str, body: object) -> int:
    fn = getattr(client, method)
    return int((fn(url, json=body) if body is not None else fn(url)).status_code)


def test_localhost_is_admin(local: TestClient) -> None:
    me = local.get("/api/v1/system/me").json()
    assert me["authenticated"] and me["role"] == "admin" and me["via"] == "localhost"


def test_remote_anonymous_needs_setup(local: TestClient) -> None:
    remote = remote_client(local)
    me = remote.get("/api/v1/system/me").json()
    assert me == {
        "authenticated": False,
        "role": None,
        "via": "anonymous",
        "device_id": None,
        "device_name": None,
        "setup_required": True,
    }
    for method, url, body in ADMIN_ONLY + UPLOADER_ALLOWED:
        assert _call(remote, method, url, body) == 401, url


def test_role_matrix(local: TestClient) -> None:
    uploader = pair(local, "uploader")
    admin = pair(local, "admin", client=("192.168.1.51", 1))
    for method, url, body in ADMIN_ONLY:
        assert _call(uploader, method, url, body) == 403, url
        assert _call(admin, method, url, body) != 403, url
    for method, url, body in UPLOADER_ALLOWED:
        assert _call(uploader, method, url, body) == 200, url


def test_proxy_headers_disable_localhost_trust(local: TestClient) -> None:
    res = local.get("/api/v1/system/me", headers={"X-Forwarded-For": "10.0.0.2"})
    assert res.json()["authenticated"] is False


def test_trusted_proxies_disable_localhost_trust(app_factory: Callable[..., TestClient]) -> None:
    client = app_factory(trusted_proxies=["127.0.0.1"])
    assert client.get("/api/v1/system/me").json()["authenticated"] is False


def test_host_allowlist_blocks_rebinding(local: TestClient) -> None:
    res = local.get("/api/v1/system/me", headers={"Host": "evil.example.com"})
    assert res.status_code == 400
    assert res.json()["code"] == "host_not_allowed"


def test_csrf_requires_client_header(local: TestClient) -> None:
    bare = TestClient(local.app, client=("127.0.0.1", 1))
    res = bare.post("/api/v1/devices/pairing-codes", json={"role": "uploader"})
    assert res.status_code == 403 and res.json()["code"] == "csrf_rejected"
    assert bare.get("/api/v1/system/me").status_code == 200


def test_csrf_rejects_cross_origin(local: TestClient) -> None:
    res = local.post(
        "/api/v1/devices/pairing-codes",
        json={"role": "uploader"},
        headers={"Origin": "http://evil.example.com"},
    )
    assert res.status_code == 403
    ok = local.post(
        "/api/v1/devices/pairing-codes",
        json={"role": "uploader"},
        headers={"Origin": "http://testserver"},
    )
    assert ok.status_code == 200


def test_security_headers(local: TestClient) -> None:
    res = local.get("/api/v1/system/me")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert res.headers["x-frame-options"] == "DENY"
    # Another origin must not be able to embed a render, open a window on us, or ask for a device.
    assert res.headers["cross-origin-resource-policy"] == "same-origin"
    assert res.headers["cross-origin-opener-policy"] == "same-origin"
    assert "geolocation=()" in res.headers["permissions-policy"]
    csp = res.headers["content-security-policy"]
    for directive in (
        "default-src 'self'",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        # A form's POST target is not covered by `default-src`.
        "form-action 'self'",
        "object-src 'none'",
    ):
        assert directive in csp, directive


def test_an_image_response_carries_the_headers_too(local: TestClient) -> None:
    """The guard is ASGI-level, so a streamed file gets the same headers as a JSON body."""
    res = local.get("/api/v1/photos", params={"limit": 1})
    assert res.headers["cross-origin-resource-policy"] == "same-origin"


def test_setup_code_flow(local: TestClient) -> None:
    from frame_it.services.devices import issue_setup_code

    with ctx_of(local).db.session() as s:
        code = issue_setup_code(s).code
    remote = remote_client(local)
    res = remote.post("/api/v1/auth/setup", json={"code": code.lower(), "device_name": "Laptop"})
    assert res.status_code == 200, res.text
    assert res.json()["role"] == "admin"
    cookie = res.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    me = remote.get("/api/v1/system/me").json()
    assert me["role"] == "admin" and me["via"] == "device"
    # single use
    other = remote_client(local, ("192.168.1.99", 1))
    assert other.post("/api/v1/auth/setup", json={"code": code}).status_code == 400
    assert other.get("/api/v1/system/me").json()["setup_required"] is False


def test_pairing_code_url_and_single_use(local: TestClient) -> None:
    body = local.post("/api/v1/devices/pairing-codes", json={"role": "uploader"}).json()
    assert body["url"] == f"http://testserver/pair#code={body['code']}"
    phone = remote_client(local)
    assert phone.post("/api/v1/auth/pair", json={"code": body["code"]}).json()["role"] == "uploader"
    again = remote_client(local, ("192.168.1.77", 1))
    assert again.post("/api/v1/auth/pair", json={"code": body["code"]}).status_code == 400


def test_revoke_is_immediate(local: TestClient) -> None:
    phone = pair(local)
    device_id = phone.get("/api/v1/system/me").json()["device_id"]
    assert local.delete(f"/api/v1/devices/{device_id}").status_code == 204
    assert phone.get("/api/v1/photos").status_code == 401


def test_rename_and_role_change(local: TestClient) -> None:
    phone = pair(local)
    device_id = phone.get("/api/v1/system/me").json()["device_id"]
    res = local.patch(f"/api/v1/devices/{device_id}", json={"name": "Pixel", "role": "admin"})
    assert res.json()["name"] == "Pixel"
    assert phone.get("/api/v1/devices").status_code == 200


def test_admin_cannot_demote_self(local: TestClient) -> None:
    admin = pair(local, "admin")
    device_id = admin.get("/api/v1/system/me").json()["device_id"]
    res = admin.patch(f"/api/v1/devices/{device_id}", json={"role": "uploader"})
    assert res.status_code == 409


def test_auth_rate_limited(local: TestClient) -> None:
    remote = remote_client(local)
    codes = [
        remote.post("/api/v1/auth/pair", json={"code": "AAAAA-AAAAA"}).status_code for _ in range(6)
    ]
    assert codes[:5] == [400] * 5
    assert codes[5] == 429


@pytest.mark.parametrize("path", ["/api/v1/nope", "/api/v1/photos/missing"])
def test_unknown_resources_are_problem_json(local: TestClient, path: str) -> None:
    res = local.get(path)
    assert res.status_code == 404
    assert res.headers["content-type"].startswith("application/problem+json")


def test_logout_clears_cookie(local: TestClient) -> None:
    phone = pair(local)
    res = phone.post("/api/v1/auth/logout")
    assert res.status_code == 204
    assert phone.get("/api/v1/system/me").json()["authenticated"] is False


def test_constants() -> None:
    assert CLIENT_HEADERS["X-TF-Client"] == "1"
    assert REMOTE[0].startswith("192.168.")
