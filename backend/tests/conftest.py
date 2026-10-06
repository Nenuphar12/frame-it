from __future__ import annotations

import hashlib
import io
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from frame_it.app import create_app
from frame_it.config import Settings
from frame_it.context import AppContext

LOCAL = ("127.0.0.1", 50000)
REMOTE = ("192.168.1.50", 50000)
CLIENT_HEADERS = {"X-TF-Client": "1"}


def make_jpeg(
    width: int = 640,
    height: int = 480,
    color: tuple[int, int, int] = (200, 100, 50),
    *,
    make: str | None = "TestCam",
    taken: str | None = "2026:04:12 10:30:00",
    gps: tuple[float, float] | None = None,
    orientation: int | None = None,
    gps_redacted: bool = False,
) -> bytes:
    img = Image.new("RGB", (width, height), color)
    exif = Image.Exif()
    if make:
        exif[0x010F] = make
        exif[0x0110] = "Model X"
    if orientation:
        exif[0x0112] = orientation
    if taken:
        exif.get_ifd(0x8769)[0x9003] = taken
    if gps:
        lat, lon = gps

        def dms(v: float) -> tuple[float, float, float]:
            v = abs(v)
            d = int(v)
            m = int((v - d) * 60)
            s = round((v - d - m / 60) * 3600, 4)
            return (float(d), float(m), s)

        gps_ifd = exif.get_ifd(0x8825)
        gps_ifd[1] = "N" if lat >= 0 else "S"
        gps_ifd[2] = dms(lat)
        gps_ifd[3] = "E" if lon >= 0 else "W"
        gps_ifd[4] = dms(lon)
    if gps_redacted:  # what Android serves to apps without ACCESS_MEDIA_LOCATION
        gps_ifd = exif.get_ifd(0x8825)
        gps_ifd[0] = b"\x00\x00\x00\x00"
        gps_ifd[2] = (0.0, 0.0, 0.0)
        gps_ifd[4] = (0.0, 0.0, 0.0)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90, exif=exif.tobytes())
    return buf.getvalue()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data", allowed_hosts=["testserver"], public_url="http://testserver"
    )


@pytest.fixture
def app_factory(settings: Settings) -> Iterator[Callable[..., Any]]:
    clients: list[TestClient] = []

    def factory(client: tuple[str, int] = LOCAL, **overrides: Any) -> TestClient:
        s = settings.model_copy(update=overrides) if overrides else settings
        app = create_app(s, start_workers=False)
        tc = TestClient(app, client=client, headers=CLIENT_HEADERS)
        tc.__enter__()
        clients.append(tc)
        return tc

    yield factory
    for tc in clients:
        tc.__exit__(None, None, None)


@pytest.fixture
def local(app_factory: Callable[..., TestClient]) -> TestClient:
    """Client calling from localhost (trusted admin)."""
    return app_factory()


def ctx_of(client: TestClient) -> AppContext:
    ctx: AppContext = client.app.state.ctx  # type: ignore[attr-defined]
    return ctx


def remote_client(local: TestClient, client: tuple[str, int] = REMOTE) -> TestClient:
    """Another client on the same app, calling from a LAN address."""
    return TestClient(local.app, client=client, headers=CLIENT_HEADERS)


def pair(local: TestClient, role: str = "uploader", client: tuple[str, int] = REMOTE) -> TestClient:
    code = local.post("/api/v1/devices/pairing-codes", json={"role": role}).json()["code"]
    remote = remote_client(local, client)
    res = remote.post("/api/v1/auth/pair", json={"code": code, "device_name": f"{role} phone"})
    assert res.status_code == 200, res.text
    return remote


def upload_bytes(
    client: TestClient, data: bytes, filename: str = "photo.jpg", chunk: int = 0, **meta: Any
) -> dict[str, Any]:
    """Upload through the resumable protocol and run ingestion synchronously."""
    res = client.post(
        "/api/v1/uploads",
        json={"filename": filename, "size": len(data), "sha256": sha256(data), "meta": meta},
    )
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    if body["status"] == "exists":
        return body
    step = chunk or len(data)
    offset = body["offset"]
    while offset < len(data):
        part = data[offset : offset + step]
        res = client.patch(
            f"/api/v1/uploads/{body['upload_id']}",
            content=part,
            headers={
                "Upload-Offset": str(offset),
                "Content-Type": "application/offset+octet-stream",
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        offset = body["offset"]
    ctx_of(client).jobs.run_pending_sync()
    return body
