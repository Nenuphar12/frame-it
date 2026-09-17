"""Request guards applied to every request (pure ASGI, streaming-safe). Spec: docs/security.md.

- Host allowlist (DNS-rebinding protection).
- CSRF: mutating `/api` requests need `X-TF-Client: 1` and, when present, a same-origin `Origin`.
- Security headers on every response.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from the_frame_v2.config import Settings
from the_frame_v2.errors import PROBLEM_BASE, PROBLEM_MEDIA_TYPE

CLIENT_HEADER = "x-tf-client"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "content-security-policy": (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'wasm-unsafe-eval'; connect-src 'self'; font-src 'self' data:; "
        "frame-ancestors 'none'; base-uri 'self'"
    ),
}


def _host_without_port(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):
        return host[: host.find("]") + 1] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


class GuardMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.allowed_hosts = settings.allowed_host_set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        host_header = headers.get("host", "")
        if (
            self.allowed_hosts is not None
            and _host_without_port(host_header) not in self.allowed_hosts
        ):
            await _reject(send, 400, "host_not_allowed", "Host not allowed")
            return

        method = scope["method"]
        path: str = scope["path"]
        if method not in _SAFE_METHODS and path.startswith("/api/"):
            if headers.get(CLIENT_HEADER) != "1":
                await _reject(send, 403, "csrf_rejected", "Missing client header")
                return
            origin = headers.get("origin")
            if origin and origin != "null":
                origin_host = urlsplit(origin).netloc.lower()
                if origin_host != host_header.lower():
                    await _reject(send, 403, "csrf_rejected", "Cross-origin request rejected")
                    return
            elif origin == "null":
                await _reject(send, 403, "csrf_rejected", "Opaque origin rejected")
                return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                mutable = MutableHeaders(scope=message)
                for key, value in _SECURITY_HEADERS.items():
                    if key not in mutable:
                        mutable[key] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


async def _reject(send: Send, status: int, code: str, title: str) -> None:
    body = json.dumps(
        {"type": PROBLEM_BASE + code, "code": code, "title": title, "status": status}
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", PROBLEM_MEDIA_TYPE.encode()),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
