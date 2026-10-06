"""Application settings.

Precedence: explicit overrides (CLI) > environment (`FRAME_IT_*`) >
`<data_dir>/config.toml` > defaults.

Until 2026-10 the app was called `the_frame_v2`: its `THE_FRAME_V2_*` variables are still read
(below the new ones) and its data directory is still used while the new one does not exist.
"""

from __future__ import annotations

import os
import socket
import tomllib
from functools import cached_property
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from platformdirs import user_data_dir
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "FRAME_IT_"
LEGACY_ENV_PREFIX = "THE_FRAME_V2_"
APP_DIR_NAME = "frame-it"
LEGACY_APP_DIR_NAME = "the_frame_v2"
CANVAS_WIDTH = 3840
CANVAS_HEIGHT = 2160


def default_data_dir() -> Path:
    """The platform's data dir, or the placeholder name's one when only that exists."""
    current = Path(user_data_dir(APP_DIR_NAME, appauthor=False))
    legacy = Path(user_data_dir(LEGACY_APP_DIR_NAME, appauthor=False))
    return legacy if not current.exists() and legacy.is_dir() else current


def adopt_legacy_env() -> None:
    """Copy each `THE_FRAME_V2_*` variable to its `FRAME_IT_*` name unless that one is set."""
    for key, value in list(os.environ.items()):
        if key.startswith(LEGACY_ENV_PREFIX):
            os.environ.setdefault(ENV_PREFIX + key.removeprefix(LEGACY_ENV_PREFIX), value)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, extra="ignore")

    data_dir: Path = Field(default_factory=default_data_dir)
    host: str = "0.0.0.0"  # noqa: S104 — LAN reachable by design (phone uploads)
    port: int = 8765
    public_url: str | None = None
    allowed_hosts: list[str] = Field(default_factory=list)
    """Extra allowed Host header values (hostnames or IPs, without port). `*` disables the check."""
    trust_localhost: bool = True
    trusted_proxies: list[str] = Field(default_factory=list)
    tls_cert: Path | None = None
    tls_key: Path | None = None
    trash_retention_days: int = 30
    max_upload_bytes: int = 1024**3
    max_archive_bytes: int = 64 * 1024**3
    """Largest archive `POST /imports` accepts, and the largest one staging will expand."""
    export_retention_hours: int = 24
    """How long a finished export stays downloadable in `exports/` before it is swept."""
    import_retention_hours: int = 24
    max_image_pixels: int = 250_000_000
    upload_session_ttl_hours: int = 24
    ingest_workers: int = 2
    render_workers: int = 1
    jpeg_quality: int = Field(default=95, ge=95, le=100)
    log_level: str = "INFO"
    localsend_enabled: bool = True
    """Built-in LocalSend receiver (docs/localsend.md)."""
    localsend_port: int = 53317
    localsend_discovery: bool = True
    """Multicast on 224.0.0.167:`localsend_multicast_port` (Docker: needs host networking)."""
    localsend_multicast_port: int = 53317
    localsend_alias: str | None = None
    localsend_approval_timeout_seconds: int = Field(default=120, ge=5, le=3600)
    tv_scan_subnet: str | None = None
    """The /24 to sweep for TVs (`192.168.1`). Default: the public URL's address, else this
    host's — set it when neither is on the TV's network (Docker without a public URL)."""
    fake_tv: bool = False
    """Development only: talk to an in-memory `FakeTv` instead of real TVs (discovery, pairing,
    pushes), so the TV pages can be driven in a browser without hardware. Never in production."""

    # ---- derived paths -------------------------------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.data_dir / "library.db"

    @property
    def originals_dir(self) -> Path:
        return self.data_dir / "originals"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads" / "tmp"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def imports_dir(self) -> Path:
        return self.data_dir / "imports"

    @property
    def localsend_dir(self) -> Path:
        return self.data_dir / "localsend"

    @property
    def effective_localsend_alias(self) -> str:
        return self.localsend_alias or f"Frame It ({socket.gethostname()})"

    @property
    def effective_trust_localhost(self) -> bool:
        return self.trust_localhost and not self.trusted_proxies

    @property
    def scheme(self) -> str:
        return "https" if self.tls_cert and self.tls_key else "http"

    @cached_property
    def lan_ip(self) -> str | None:
        return detect_lan_ip()

    @property
    def effective_public_url(self) -> str:
        if self.public_url:
            return self.public_url.rstrip("/")
        host = self.lan_ip or "localhost"
        return f"{self.scheme}://{host}:{self.port}"

    def allowed_host_set(self) -> set[str] | None:
        """Allowed `Host` names (lowercase, no port). `None` means any host is accepted."""
        if "*" in self.allowed_hosts:
            return None
        hosts = {"localhost", "127.0.0.1", "::1", "[::1]"}
        hostname = socket.gethostname().lower()
        hosts |= {hostname, f"{hostname}.local"}
        if self.lan_ip:
            hosts.add(self.lan_ip)
        if self.public_url:
            parsed = urlsplit(self.public_url)
            if parsed.hostname:
                hosts.add(parsed.hostname.lower())
        hosts |= {h.lower() for h in self.allowed_hosts}
        return hosts


def detect_lan_ip() -> str | None:
    """Best-effort private IPv4 of the default route (no packet is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))  # TEST-NET-1, never routed
            ip: str = sock.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith("127.") else ip


def load_settings(**overrides: Any) -> Settings:
    """Build settings, merging `<data_dir>/config.toml` below env vars and above defaults."""
    adopt_legacy_env()
    explicit = {k: v for k, v in overrides.items() if v is not None}
    data_dir = explicit.get("data_dir") or os.environ.get(f"{ENV_PREFIX}DATA_DIR")
    base = Path(data_dir) if data_dir else default_data_dir()
    file_values: dict[str, Any] = {}
    config_file = base / "config.toml"
    if config_file.is_file():
        with config_file.open("rb") as fh:
            file_values = tomllib.load(fh)
    env_keys = {k.removeprefix(ENV_PREFIX).lower() for k in os.environ if k.startswith(ENV_PREFIX)}
    merged = {k: v for k, v in file_values.items() if k not in env_keys}
    merged.update(explicit)
    merged.setdefault("data_dir", base)
    return Settings(**merged)
