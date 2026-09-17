"""Data directory layout. Spec: docs/data-model.md §5.3. `cache/` is always safe to delete."""

from __future__ import annotations

from pathlib import Path

from the_frame_v2.config import Settings


class Storage:
    def __init__(self, settings: Settings) -> None:
        self.root = settings.data_dir
        self.originals = settings.originals_dir
        self.cache = settings.cache_dir
        self.uploads = settings.uploads_dir

    def ensure_dirs(self) -> None:
        for d in (self.root, self.originals, self.cache, self.uploads):
            d.mkdir(parents=True, exist_ok=True)

    def original_path(self, sha256: str, ext: str) -> Path:
        return self.originals / sha256[:2] / f"{sha256}.{ext}"

    def proxy_path(self, sha256: str) -> Path:
        return self.cache / "proxies" / sha256 / "2560.jpg"

    def thumb_path(self, sha256: str, size: int) -> Path:
        return self.cache / "thumbs" / sha256 / f"{size}.webp"

    def render_dir(self, artwork_id: str) -> Path:
        return self.cache / "renders" / artwork_id

    def render_path(self, artwork_id: str, render_hash: str, suffix: str) -> Path:
        """`suffix`: `png` (master), `jpg`, `thumb-256.webp`, `thumb-768.webp`."""
        return self.render_dir(artwork_id) / f"{render_hash}.{suffix}"

    def upload_temp_path(self, session_id: str) -> Path:
        return self.uploads / f"{session_id}.part"
