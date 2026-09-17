"""Render cache and render jobs. Spec: docs/rendering-spec.md §8.4.

Renders live in `cache/renders/<artwork_id>/<render_hash>.{png,jpg,thumb-*.webp}` and are
addressed by `(artwork_id, render_hash, format)` (display-target seam, ADR-0005). The hash covers
everything that changes pixels, so a stale file is never served. Full renders are bounded by
`render_workers`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pyvips
from sqlalchemy import select
from sqlalchemy.orm import Session

from the_frame_v2.context import AppContext
from the_frame_v2.db.models import Artwork, Photo
from the_frame_v2.domain.document import ArtworkDocument
from the_frame_v2.domain.geometry import Rect
from the_frame_v2.errors import ProblemError
from the_frame_v2.events import Event
from the_frame_v2.ids import utcnow
from the_frame_v2.imaging import render as renderer
from the_frame_v2.imaging.assets import catalog
from the_frame_v2.jobs.queue import JobContext, JobHandler, PermanentJobError
from the_frame_v2.services import artworks

log = logging.getLogger(__name__)

RENDER_JOB = "render"
THUMB_SIZES = (256, 768)
MAX_REGION_SIDE = 1024
Derivative = Literal["png", "jpg", "thumb-256", "thumb-768"]


def render_hash(document: Mapping[str, Any], photo_shas: list[str]) -> str:
    """sha256(canonical document + renderer version + sorted photo SHA-256s + asset versions)."""
    digest = hashlib.sha256()
    digest.update(json.dumps(document, sort_keys=True, separators=(",", ":")).encode())
    digest.update(f"\nrenderer:{renderer.RENDERER_VERSION}\n".encode())
    digest.update(",".join(sorted(set(photo_shas))).encode())
    digest.update(f"\n{catalog().version_key}".encode())
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class RenderInputs:
    artwork_id: str
    document: ArtworkDocument
    originals: dict[str, Path]
    """photo id → original file (only photos that exist and are not trashed)."""
    hash: str


def inputs_for(
    ctx: AppContext, session: Session, doc: ArtworkDocument, artwork_id: str = ""
) -> RenderInputs:
    ids = doc.photo_ids()
    rows = (
        session.execute(
            select(Photo.id, Photo.sha256, Photo.ext).where(
                Photo.id.in_(set(ids)), Photo.deleted_at.is_(None)
            )
        ).all()
        if ids
        else []
    )
    originals = {row.id: ctx.storage.original_path(row.sha256, row.ext) for row in rows}
    shas = [row.sha256 for row in rows]
    return RenderInputs(artwork_id, doc, originals, render_hash(doc.canonical(), shas))


def artwork_inputs(ctx: AppContext, artwork_id: str) -> RenderInputs:
    with ctx.db.session() as s:
        artwork = artworks.get_artwork(s, artwork_id)
        return inputs_for(ctx, s, artworks.document_of(artwork), artwork.id)


# ---- full renders -------------------------------------------------------------------------------
def ensure_render(ctx: AppContext, artwork_id: str) -> RenderInputs:
    """Render the artwork's current document unless its PNG master already exists."""
    inputs = artwork_inputs(ctx, artwork_id)
    target = ctx.storage.render_path(artwork_id, inputs.hash, "png")
    if target.exists():
        return inputs
    gate = ctx.render_gate
    with gate.artwork_lock(artwork_id):
        if not target.exists():
            with gate.slots:
                _render_to(inputs, target)
            _prune(ctx, artwork_id, inputs.hash)
    _mark_rendered(ctx, inputs)
    return inputs


def _render_to(inputs: RenderInputs, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp.png")
    try:
        rendered = renderer.render_document(inputs.document, inputs.originals.get)
        renderer.save_png(rendered.image, tmp)
    except pyvips.Error as exc:
        tmp.unlink(missing_ok=True)
        raise renderer.RenderError("render_failed", str(exc).splitlines()[0]) from exc
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(target)


def _prune(ctx: AppContext, artwork_id: str, keep_hash: str) -> None:
    """Old renders of the artwork are deleted when a new one completes."""
    for path in ctx.storage.render_dir(artwork_id).iterdir():
        if not path.name.startswith(keep_hash):
            path.unlink(missing_ok=True)


def _mark_rendered(ctx: AppContext, inputs: RenderInputs) -> None:
    changed = False
    with ctx.db.session() as s:
        artwork = s.get(Artwork, inputs.artwork_id)
        if artwork is not None and artwork.render_hash != inputs.hash:
            current = inputs_for(ctx, s, artworks.document_of(artwork), artwork.id)
            if current.hash == inputs.hash:
                artwork.render_hash = inputs.hash
                artwork.rendered_at = utcnow()
                changed = True
    if changed:
        ctx.broker.publish(
            Event(
                "artwork.rendered",
                {"artwork_id": inputs.artwork_id, "render_hash": inputs.hash},
                audience="all",
            )
        )


def derivative(ctx: AppContext, artwork_id: str, kind: Derivative) -> tuple[Path, str]:
    """Path of a render file (created on demand) and the render hash it belongs to."""
    inputs = ensure_render(ctx, artwork_id)
    master = ctx.storage.render_path(artwork_id, inputs.hash, "png")
    if kind == "png":
        return master, inputs.hash
    target = ctx.storage.render_path(
        artwork_id, inputs.hash, "jpg" if kind == "jpg" else f"{kind}.webp"
    )
    if not target.exists():
        with ctx.render_gate.artwork_lock(artwork_id):
            if not target.exists():
                _write_derivative(ctx, master, target, kind)
    return target, inputs.hash


def _write_derivative(ctx: AppContext, master: Path, target: Path, kind: Derivative) -> None:
    tmp = target.with_name(f".{target.name}.tmp")
    if kind == "jpg":
        image = pyvips.Image.new_from_file(str(master), access="sequential")
        renderer.save_jpeg(image, tmp, ctx.settings.jpeg_quality)
    else:
        size = int(kind.removeprefix("thumb-"))
        pyvips.Image.thumbnail(str(master), size, height=size).webpsave(str(tmp), Q=85, keep="none")
    tmp.replace(target)


def enqueue_render(ctx: AppContext, artwork_id: str) -> str:
    return ctx.jobs.enqueue(
        RENDER_JOB, {"artwork_id": artwork_id}, coalesce_key=f"render:{artwork_id}"
    )


def render_job(ctx: AppContext) -> JobHandler:
    def handler(job: JobContext) -> None:
        artwork_id = str(job.payload["artwork_id"])
        try:
            ensure_render(ctx, artwork_id)
        except ProblemError as exc:
            if exc.code == "not_found":
                return  # deleted since
            raise PermanentJobError(exc.code, str(exc)) from exc
        except renderer.RenderError as exc:
            raise PermanentJobError(exc.code, str(exc)) from exc

    return handler


# ---- region renders (loupe) ---------------------------------------------------------------------
def region_png(ctx: AppContext, session: Session, raw: Mapping[str, Any], rect: Rect) -> bytes:
    """Render only `rect` (canvas px, ≤ 1024²) of an unsaved document."""
    if rect.w > MAX_REGION_SIDE or rect.h > MAX_REGION_SIDE:
        raise ProblemError(422, "region_too_large", "Region too large", f"max {MAX_REGION_SIDE} px")
    doc = artworks.validated(session, raw)
    inputs = inputs_for(ctx, session, doc)
    try:
        rendered = renderer.render_document(doc, inputs.originals.get, region=rect)
        return renderer.png_bytes(rendered.image)
    except renderer.RenderError as exc:
        raise ProblemError(422, exc.code, "Cannot render", str(exc)) from exc
    except pyvips.Error as exc:
        raise ProblemError(500, "render_failed", "Render failed", str(exc).splitlines()[0]) from exc
