"""Putting a set of artworks on a TV. Spec: `docs/tv-display.md`.

The Frame's slideshow plays a whole category and cannot be scoped to a subset — favourites refuse
the API, `content_list` is reported but ignored, and no per-item request exists
(`docs/research/tv-display.md`). So "show only this set" means **the TV's My Photos *is* the set**,
and the delicate part of a push is doing that without ever deleting something the user put there.

A push, in order (every step measured, none of it guessed):

1. resolve the set (an artwork query: a collection, a smart collection, Favorites, an ad-hoc list);
2. render every member and take the `jpg`/`png` derivative;
3. upload what the TV does not already have, **oldest member last** — the TV lists newest first, so
   uploading in reverse makes its order our order (`image_date` is written to match);
4. delete our own stale uploads, and foreign items **only** when the caller passed
   `allow_delete_foreign` (the UI asks, `--yes-delete-others` on the CLI);
5. stop the slideshow, `select_image` the first member, then start the slideshow — in that order,
   because selecting an image stops a running slideshow and starting one never moves the panel.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from the_frame_v2.context import AppContext
from the_frame_v2.db.models import Artwork, DisplayTarget, DisplayTargetItem
from the_frame_v2.errors import ProblemError
from the_frame_v2.events import Event
from the_frame_v2.ids import utcnow
from the_frame_v2.jobs.queue import JobContext, JobHandler, PermanentJobError
from the_frame_v2.services import library, render
from the_frame_v2.tv import SLIDESHOW_MINUTES, SamsungTvClient, TvClient, TvError, TvInfo
from the_frame_v2.tv.client import pair_with_tv

log = logging.getLogger(__name__)

PUSH_JOB = "display.push"
MAX_SET = 200
"""A Frame holds a few hundred images at most; a set beyond this is a mistake, not a wish."""

TvFactory = Callable[[DisplayTarget], TvClient]


def default_tv(target: DisplayTarget) -> TvClient:
    return SamsungTvClient(target.host, target.token)


def _factory(ctx: AppContext) -> TvFactory:
    """Tests put a `FakeTv` on the context; production gets the real client."""
    factory: TvFactory | None = getattr(ctx, "tv_factory", None)
    return factory or default_tv


# ---- targets ------------------------------------------------------------------------------------


def list_targets(session: Session) -> list[DisplayTarget]:
    return list(session.scalars(select(DisplayTarget).order_by(DisplayTarget.created_at)).all())


def get_target(session: Session, target_id: str) -> DisplayTarget:
    target = session.get(DisplayTarget, target_id)
    if target is None:
        raise ProblemError(404, "target_not_found", "No such display target")
    return target


def create_target(session: Session, *, name: str, host: str) -> DisplayTarget:
    target = DisplayTarget(name=name.strip() or host, host=host.strip())
    session.add(target)
    session.flush()
    return target


def delete_target(session: Session, target_id: str) -> None:
    target = get_target(session, target_id)
    session.execute(sql_delete(DisplayTargetItem).where(DisplayTargetItem.target_id == target.id))
    session.delete(target)


def update_target(
    session: Session,
    target_id: str,
    *,
    name: str | None = None,
    host: str | None = None,
    slideshow_minutes: int | None = None,
    slideshow_ordered: bool | None = None,
    render_format: str | None = None,
) -> DisplayTarget:
    target = get_target(session, target_id)
    if name is not None:
        target.name = name.strip() or target.name
    if host is not None and host.strip() != target.host:
        target.host = host.strip()
    if slideshow_minutes is not None:
        if slideshow_minutes not in SLIDESHOW_MINUTES:
            raise ProblemError(
                422,
                "invalid_interval",
                "The TV does not accept this interval",
                f"Pick one of {', '.join(str(m) for m in SLIDESHOW_MINUTES)} minutes.",
            )
        target.slideshow_minutes = slideshow_minutes
    if slideshow_ordered is not None:
        target.slideshow_ordered = slideshow_ordered
    if render_format is not None:
        if render_format not in {"jpg", "png"}:
            raise ProblemError(422, "invalid_render_format", "Use jpg or png")
        target.render_format = render_format
    return target


def pair(session: Session, target_id: str, *, timeout: float = 45.0) -> DisplayTarget:
    """Ask the TV for a token. The TV must be **on** (not art mode) to show its dialog."""
    target = get_target(session, target_id)
    try:
        token = pair_with_tv(target.host, timeout=timeout)
    except TvError as exc:
        target.last_error = exc.code
        raise _problem(exc) from exc
    target.token = token
    target.last_error = None
    target.state = "ready"
    target.last_seen_at = utcnow()
    return target


@dataclass(frozen=True, slots=True)
class TargetStatus:
    """What the TV says right now, plus what this app knows it put there."""

    info: TvInfo
    ours: int
    foreign: int
    """Items in My Photos this app did not upload — a push would have to delete them."""


def status(ctx: AppContext, session: Session, target_id: str) -> TargetStatus:
    target = get_target(session, target_id)
    client = _factory(ctx)(target)
    try:
        info = client.info()
        items = client.items()
    except TvError as exc:
        target.last_error = exc.code
        target.state = "error"
        raise _problem(exc) from exc
    finally:
        client.close()
    known = _known_content_ids(session, target.id)
    on_tv = {i.content_id for i in items}
    target.model = info.model or target.model
    target.api_version = info.api_version or target.api_version
    target.last_seen_at = utcnow()
    target.last_error = None
    if target.state in {"new", "error"}:
        target.state = "ready"
    return TargetStatus(
        info=info,
        ours=len(on_tv & known),
        foreign=len(on_tv - known),
    )


def set_source(
    session: Session, target_id: str, *, source: dict[str, Any], label: str | None
) -> DisplayTarget:
    target = get_target(session, target_id)
    library.parse_query_filter(source.get("filter"))  # validates, raises `invalid_filter`
    target.source = source
    target.source_label = label
    return target


# ---- resolving the set --------------------------------------------------------------------------


def _query_from_source(source: dict[str, Any]) -> library.ArtworkQuery:
    sort = str(source.get("sort") or "created_desc")
    return library.ArtworkQuery(
        filter=library.parse_query_filter(source.get("filter")),
        collection_id=source.get("collection_id"),
        include_nested=bool(source.get("include_nested")),
        favorite=source.get("favorite"),
        status=source.get("status"),
        sort=sort,  # type: ignore[arg-type]
    )


def resolve_set(session: Session, source: dict[str, Any]) -> list[Artwork]:
    """The artworks of a source, in the order they should play."""
    ids = list(source.get("artwork_ids") or [])
    if ids:
        rows = {
            a.id: a
            for a in session.scalars(
                select(Artwork).where(Artwork.id.in_(ids), Artwork.deleted_at.is_(None))
            ).all()
        }
        return [rows[i] for i in ids if i in rows]
    page = library.list_artworks(session, _query_from_source(source), limit=MAX_SET)
    return page.items


# ---- pushing ------------------------------------------------------------------------------------


@dataclass(slots=True)
class PushResult:
    target_id: str
    uploaded: int = 0
    reused: int = 0
    deleted_ours: int = 0
    deleted_foreign: int = 0
    foreign_remaining: int = 0
    """Items the app did not upload and was not allowed to delete — the TV shows them too."""
    total: int = 0
    slideshow_minutes: int | None = None
    first_content_id: str | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "uploaded": self.uploaded,
            "reused": self.reused,
            "deleted_ours": self.deleted_ours,
            "deleted_foreign": self.deleted_foreign,
            "foreign_remaining": self.foreign_remaining,
            "total": self.total,
            "slideshow_minutes": self.slideshow_minutes,
            "first_content_id": self.first_content_id,
            "warnings": list(self.warnings),
        }


def _known_content_ids(session: Session, target_id: str) -> set[str]:
    return set(
        session.scalars(
            select(DisplayTargetItem.content_id).where(DisplayTargetItem.target_id == target_id)
        ).all()
    )


def _image_date(position: int, count: int) -> str:
    """A date per position so the TV's newest-first order is our order.

    Position 0 gets the latest stamp; the TV lists newest first, so it leads.
    """
    stamp = utcnow() + timedelta(minutes=count - position)
    return stamp.strftime("%Y:%m:%d %H:%M:%S")


def push(
    ctx: AppContext,
    target_id: str,
    *,
    allow_delete_foreign: bool = False,
    progress: Callable[[float], None] | None = None,
) -> PushResult:
    """Make the TV show exactly this target's set. Idempotent: re-pushing uploads nothing."""
    with ctx.db.session() as s:
        target = get_target(s, target_id)
        source = dict(target.source or {})
        if not source:
            raise ProblemError(422, "no_source", "This TV has no set to show yet")
        artworks_in_set = resolve_set(s, source)
        if not artworks_in_set:
            raise ProblemError(422, "empty_set", "That set has no artworks")
        if len(artworks_in_set) > MAX_SET:
            raise ProblemError(422, "set_too_large", f"A TV holds at most {MAX_SET} images")
        wanted = [a.id for a in artworks_in_set]
        host, token = target.host, target.token
        fmt = target.render_format
        minutes, ordered = target.slideshow_minutes, target.slideshow_ordered
        target.state = "pushing"

    # Rendering is slow and needs no TV, so it happens before the connection is opened.
    renders: dict[str, tuple[bytes, str]] = {}
    for index, artwork_id in enumerate(wanted):
        path, render_hash = render.derivative(ctx, artwork_id, fmt)  # type: ignore[arg-type]
        renders[artwork_id] = (path.read_bytes(), render_hash)
        if progress:
            progress(0.4 * (index + 1) / len(wanted))

    result = PushResult(target_id=target_id, total=len(wanted))
    with ctx.db.session() as s:
        target = get_target(s, target_id)
        existing = {
            (row.artwork_id, row.render_hash): row
            for row in s.scalars(
                select(DisplayTargetItem).where(DisplayTargetItem.target_id == target_id)
            ).all()
        }
        client = _factory(ctx)(target)
        try:
            on_tv = {item.content_id for item in client.items()}
            keep: dict[str, str] = {}
            # Newest first on the TV ⇒ upload in reverse so position 0 ends up leading.
            for position in range(len(wanted) - 1, -1, -1):
                artwork_id = wanted[position]
                data, render_hash = renders[artwork_id]
                row = existing.get((artwork_id, render_hash))
                if row is not None and row.content_id in on_tv and row.position == position:
                    keep[artwork_id] = row.content_id
                    result.reused += 1
                    continue
                content_id = client.upload(
                    data,
                    "png" if target.render_format == "png" else "jpg",
                    _image_date(position, len(wanted)),
                )
                keep[artwork_id] = content_id
                result.uploaded += 1
                if row is not None:
                    s.delete(row)
                s.add(
                    DisplayTargetItem(
                        target_id=target_id,
                        artwork_id=artwork_id,
                        render_hash=render_hash,
                        content_id=content_id,
                        position=position,
                    )
                )
                if progress:
                    done = len(wanted) - position
                    progress(0.4 + 0.5 * done / len(wanted))
            s.flush()

            # Anything of ours that is no longer part of the set.
            stale = [
                row
                for row in s.scalars(
                    select(DisplayTargetItem).where(DisplayTargetItem.target_id == target_id)
                ).all()
                if row.content_id not in set(keep.values())
            ]
            if stale:
                client.delete([row.content_id for row in stale])
                result.deleted_ours = len(stale)
                for row in stale:
                    s.delete(row)
                s.flush()

            # Anything somebody else put there: only with permission, never silently.
            known = _known_content_ids(s, target_id) | set(keep.values())
            foreign = [item.content_id for item in client.items() if item.content_id not in known]
            if foreign and allow_delete_foreign:
                client.delete(foreign)
                result.deleted_foreign = len(foreign)
            elif foreign:
                result.foreign_remaining = len(foreign)
                result.warnings.append("foreign_items_remain")

            # Stop → select → start: selecting stops a running slideshow, and starting one never
            # moves the panel (both measured on 2025 firmware).
            client.stop_slideshow()
            first = keep.get(wanted[0])
            if first:
                client.select(first)
                result.first_content_id = first
            client.start_slideshow(minutes, ordered)
            result.slideshow_minutes = minutes
        except TvError as exc:
            target.state = "error"
            target.last_error = exc.code
            raise
        finally:
            client.close()

        target.state = "ready"
        target.last_error = None
        target.last_pushed_at = utcnow()
        target.last_seen_at = utcnow()
        target.host = host
        target.token = token

    ctx.broker.publish(Event("display.pushed", result.as_dict()))
    if progress:
        progress(1.0)
    return result


def enqueue_push(ctx: AppContext, target_id: str, *, allow_delete_foreign: bool = False) -> str:
    return ctx.jobs.enqueue(
        PUSH_JOB,
        {"target_id": target_id, "allow_delete_foreign": allow_delete_foreign},
        coalesce_key=f"{PUSH_JOB}:{target_id}",
    )


def push_job(ctx: AppContext) -> JobHandler:
    def handler(job: JobContext) -> None:
        target_id = str(job.payload["target_id"])
        try:
            push(
                ctx,
                target_id,
                allow_delete_foreign=bool(job.payload.get("allow_delete_foreign")),
                progress=job.progress,
            )
        except TvError as exc:
            # No automatic retry: a TV that is off stays off for longer than three attempts, and
            # /activity offers "Retry" with the reason spelled out.
            raise PermanentJobError(exc.code, str(exc)) from exc
        except ProblemError as exc:
            raise PermanentJobError(exc.code, str(exc)) from exc

    return handler


def _problem(exc: TvError) -> ProblemError:
    titles = {
        "tv_unreachable": "The TV did not answer",
        "tv_unauthorized": "The TV no longer trusts this app",
        "tv_rejected": "The TV refused that",
    }
    status_code = 409 if exc.code == "tv_unauthorized" else 502
    return ProblemError(status_code, exc.code, titles.get(exc.code, "TV error"), str(exc))
