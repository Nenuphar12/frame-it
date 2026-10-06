"""Colour tools for the editor: photo palettes, saved swatches and curated mat presets.

Spec: docs/PLAN.md §11.3. Palettes are computed from a photo's proxy (`imaging/palette.py`) and
cached as JSON under `cache/palettes/` (disposable like every other derivative).
"""

from __future__ import annotations

import json
from dataclasses import asdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from frame_it.context import AppContext
from frame_it.db.models import Swatch
from frame_it.errors import ProblemError, not_found
from frame_it.imaging import decode, palette
from frame_it.services import photos
from frame_it.services.ingest import ensure_derivatives

MAX_SWATCHES = 200

CURATED: tuple[tuple[str, str], ...] = (
    ("Museum white", "#F7F7F4"),
    ("Warm off-white", "#F2EFE8"),
    ("Linen", "#E4DCCD"),
    ("Stone", "#C9C6BE"),
    ("Charcoal", "#3A3A3A"),
    ("Black", "#000000"),
)
"""Curated mat colours offered next to the picker (§11.3)."""


# ---- photo palette ------------------------------------------------------------------------------
def photo_palette(ctx: AppContext, session: Session, photo_id: str) -> list[dict[str, object]]:
    """Dominant/muted/complementary colours of a photo (cached; computed from the proxy)."""
    photo = photos.get_photo(session, photo_id)
    cached = ctx.storage.palette_path(photo.sha256)
    if cached.exists():
        entries: list[dict[str, object]] = json.loads(cached.read_text())
        return entries
    proxy = ctx.storage.proxy_path(photo.sha256)
    if not proxy.exists():
        original = ctx.storage.original_path(photo.sha256, photo.ext)
        if not original.exists():
            raise not_found("Original file")
        ensure_derivatives(ctx, photo.sha256, original)
    image = decode.load_srgb(proxy)
    result = [asdict(entry) for entry in palette.palette_from_pixels(palette.sample_pixels(image))]
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(result))
    return result


# ---- swatches -----------------------------------------------------------------------------------
def list_swatches(session: Session) -> list[Swatch]:
    return list(session.scalars(select(Swatch).order_by(Swatch.position, Swatch.id)))


def create_swatch(session: Session, color: str, name: str) -> Swatch:
    count = session.scalar(select(func.count()).select_from(Swatch)) or 0
    if count >= MAX_SWATCHES:
        raise ProblemError(422, "too_many_swatches", "Too many saved colours", str(MAX_SWATCHES))
    existing = session.scalars(select(Swatch).where(Swatch.color == color.upper())).first()
    if existing is not None:
        return existing
    last = session.scalar(select(func.coalesce(func.max(Swatch.position), 0.0))) or 0.0
    swatch = Swatch(color=color.upper(), name=name.strip()[:64], position=float(last) + 1)
    session.add(swatch)
    session.flush()
    return swatch


def update_swatch(session: Session, swatch_id: str, *, name: str | None) -> Swatch:
    swatch = session.get(Swatch, swatch_id)
    if swatch is None:
        raise not_found("Swatch")
    if name is not None:
        swatch.name = name.strip()[:64]
    return swatch


def delete_swatch(session: Session, swatch_id: str) -> None:
    swatch = session.get(Swatch, swatch_id)
    if swatch is None:
        raise not_found("Swatch")
    session.delete(swatch)


def reorder_swatches(session: Session, ids: list[str]) -> list[Swatch]:
    """Set the order from a full or partial list of ids (listed ones come first, in order)."""
    known = {s.id: s for s in list_swatches(session)}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise ProblemError(422, "unknown_swatch", "Unknown swatch", unknown[0])
    for position, swatch_id in enumerate(ids):
        known[swatch_id].position = float(position)
    for offset, swatch in enumerate(s for s in known.values() if s.id not in set(ids)):
        swatch.position = float(len(ids) + offset)
    session.flush()
    return list_swatches(session)
