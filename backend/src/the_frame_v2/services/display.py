"""Putting a set of artworks on a TV. Spec: `docs/tv-display.md`.

The Frame's slideshow plays a whole category and cannot be scoped to a subset — favourites refuse
the API, `content_list` is reported but ignored, and no per-item request exists
(`docs/research/tv-display.md`). So a push comes in two modes:

- **slideshow** (`slideshow_minutes` > 0): the TV's My Photos *is* the set — it is a mirror, and
  the delicate part is doing that without ever deleting something the user put there;
- **"Don't change"** (`slideshow_minutes` = 0): no slideshow, so nothing needs to go. Upload what
  is missing, show the first image, and leave everything else on the TV exactly as it is.

A push, in order (every step measured, none of it guessed):

1. resolve the set (an artwork query: a collection, a smart collection, Favorites, an ad-hoc list);
2. render every member and take the `jpg`/`png` derivative;
3. plan it (`plan_push`, pure — the dry run the UI shows is the same function);
4. upload what the TV does not already have, **oldest member last** — the TV lists newest first,
   so uploading in reverse makes its order our order (`image_date` is written to match);
5. slideshow mode only: delete our own uploads that left the set, and foreign items **only** when
   the caller passed `allow_delete_foreign` (the UI asks, `--yes-delete-others` on the CLI);
6. stop the slideshow, `select_image` the first member, then (slideshow mode) start it — in that
   order, because selecting an image stops a running slideshow and starting one never moves the
   panel.

The map `display_target_items` is the app's memory of what it put on the TV. **An upload is
written to it the moment the TV accepts it**, in its own transaction, and a row goes only once the
TV no longer holds its item: a push that dies half way, or a "Don't change" push that leaves our
older images in place, never turns our own uploads into "somebody else's photos".
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from the_frame_v2.context import AppContext
from the_frame_v2.db.models import Artwork, DisplayTarget, DisplayTargetItem
from the_frame_v2.errors import ProblemError
from the_frame_v2.events import Event
from the_frame_v2.ids import utcnow
from the_frame_v2.imaging.render import RenderError
from the_frame_v2.jobs.queue import JobContext, JobHandler, PermanentJobError
from the_frame_v2.services import artworks as artworks_service
from the_frame_v2.services import library, render
from the_frame_v2.tv import (
    SLIDESHOW_MINUTES,
    SamsungTvClient,
    TvClient,
    TvError,
    TvInfo,
    TvUnreachableError,
    discovery,
    normalize_mac,
)
from the_frame_v2.tv.client import pair_with_tv

log = logging.getLogger(__name__)

PUSH_JOB = "display.push"
MAX_SET = 200
"""A Frame holds a few hundred images at most; a set beyond this is a mistake, not a wish."""
STATIC = 0
"""`slideshow_minutes` for "Don't change": show the first image, rotate and delete nothing."""
INTERVALS: tuple[int, ...] = (STATIC, *SLIDESHOW_MINUTES)
PROGRESS_EVERY_SECONDS = 0.25

Phase = Literal["queued", "rendering", "uploading", "removing", "starting"]
Report = Callable[[Phase, int, int], None]
"""`(phase, done, total)` — how far a push is, for the UI (`display.progress`) or the CLI."""

TvFactory = Callable[[DisplayTarget], TvClient]


def default_tv(target: DisplayTarget) -> TvClient:
    return SamsungTvClient(target.host, target.token)


def _factory(ctx: AppContext) -> TvFactory:
    """Tests (and `fake_tv`) put a `FakeTv` on the context; production gets the real client."""
    return ctx.tv_factory or default_tv


def _discover(ctx: AppContext) -> discovery.Discover:
    return ctx.tv_discovery or discovery.discover


def scan_prefix(ctx: AppContext) -> str | None:
    """The /24 a discovery sweeps (`tv/discovery.subnet_prefix`)."""
    settings = ctx.settings
    return discovery.subnet_prefix(
        configured=settings.tv_scan_subnet,
        public_url=settings.public_url,
        lan_ip=settings.lan_ip,
    )


def is_static(minutes: int) -> bool:
    return minutes == STATIC


# ---- targets ------------------------------------------------------------------------------------


def list_targets(session: Session) -> list[DisplayTarget]:
    return list(session.scalars(select(DisplayTarget).order_by(DisplayTarget.created_at)).all())


def get_target(session: Session, target_id: str) -> DisplayTarget:
    target = session.get(DisplayTarget, target_id)
    if target is None:
        raise ProblemError(404, "target_not_found", "No such display target")
    return target


def create_target(
    session: Session,
    *,
    name: str,
    host: str,
    mac: str | None = None,
    model: str | None = None,
) -> DisplayTarget:
    """Register a TV. `mac`/`model` come from discovery when the user picked a scanned TV."""
    target = DisplayTarget(
        name=name.strip() or host.strip(),
        host=host.strip(),
        mac=normalize_mac(mac),
        model=(model or "").strip() or None,
    )
    session.add(target)
    session.flush()
    return target


def delete_target(session: Session, target_id: str) -> None:
    target = get_target(session, target_id)
    session.execute(sql_delete(DisplayTargetItem).where(DisplayTargetItem.target_id == target.id))
    session.delete(target)


def check_interval(minutes: int) -> int:
    if minutes not in INTERVALS:
        raise ProblemError(
            422,
            "invalid_interval",
            "The TV does not accept this interval",
            f"Pick 0 (don't change) or one of {', '.join(str(m) for m in SLIDESHOW_MINUTES)}"
            " minutes.",
        )
    return minutes


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
        target.slideshow_minutes = check_interval(slideshow_minutes)
    if slideshow_ordered is not None:
        target.slideshow_ordered = slideshow_ordered
    if render_format is not None:
        if render_format not in {"jpg", "png"}:
            raise ProblemError(422, "invalid_render_format", "Use jpg or png")
        target.render_format = render_format
    return target


def pair(
    ctx: AppContext, session: Session, target_id: str, *, timeout: float = 45.0
) -> DisplayTarget:
    """Ask the TV for a token. The TV must be **on** (not art mode) to show its dialog."""
    target = get_target(session, target_id)
    pairer = ctx.tv_pairer or (lambda host: pair_with_tv(host, timeout=timeout))
    try:
        token = pairer(target.host)
    except TvError as exc:
        target.last_error = exc.code
        raise _problem(exc) from exc
    target.token = token
    target.last_error = None
    target.state = "ready"
    target.last_seen_at = utcnow()
    return target


# ---- discovery and following a TV that moved -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Found:
    tv: discovery.DiscoveredTv
    target_id: str | None
    """The target this TV already is (same MAC, else same address), or None."""


def discover(ctx: AppContext, session: Session) -> tuple[str | None, list[Found]]:
    """The TVs on the LAN, each matched to the target it already is. Read-only, a few seconds."""
    prefix = scan_prefix(ctx)
    tvs = _discover(ctx)(prefix)
    targets = list_targets(session)
    by_mac = {t.mac: t.id for t in targets if t.mac}
    by_host = {t.host: t.id for t in targets}
    found = [
        Found(tv=tv, target_id=(by_mac.get(tv.mac) if tv.mac else None) or by_host.get(tv.host))
        for tv in tvs
    ]
    return prefix, found


@dataclass(frozen=True, slots=True)
class _Tv:
    """What it takes to reach a TV, copied out of the session (a push spans several)."""

    id: str
    host: str
    token: str | None
    mac: str | None

    @staticmethod
    def of(target: DisplayTarget) -> _Tv:
        return _Tv(id=target.id, host=target.host, token=target.token, mac=target.mac)

    def as_target(self) -> DisplayTarget:
        """A detached row, for the factory (`TvFactory` takes a `DisplayTarget`)."""
        return DisplayTarget(id=self.id, host=self.host, token=self.token, mac=self.mac)


@dataclass(frozen=True, slots=True)
class Moved:
    old_host: str
    new_host: str


def _with_tv[T](ctx: AppContext, tv: _Tv, work: Callable[[TvClient], T]) -> tuple[T, Moved | None]:
    """Run `work` against the TV; if it does not answer, look for it by MAC and try once more.

    DHCP hands a TV a new address after a router restart. With the MAC known, a TV that stopped
    answering at its old address is looked for on the LAN; found elsewhere, the target follows it
    (committed at once — the address is right even if the retry fails) and `work` runs again.
    `work` must be safe to repeat: a push re-plans from what the TV holds, so it is.
    """
    client = _factory(ctx)(tv.as_target())
    try:
        return work(client), None
    except TvUnreachableError:
        if not tv.mac:
            raise
        found = discovery.find_by_mac(_discover(ctx), scan_prefix(ctx), tv.mac)
        if found is None or found.host == tv.host:
            raise
    finally:
        client.close()
    moved = Moved(old_host=tv.host, new_host=found.host)
    log.info("TV %s moved from %s to %s", tv.mac, moved.old_host, moved.new_host)
    with ctx.db.session() as s:
        get_target(s, tv.id).host = found.host
    retry = _factory(ctx)(_Tv(tv.id, found.host, tv.token, tv.mac).as_target())
    try:
        return work(retry), moved
    finally:
        retry.close()


# ---- the map and the plan -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MapRow:
    """What the planner needs of a `display_target_items` row."""

    id: str
    artwork_id: str
    render_hash: str
    content_id: str
    position: int | None
    uploaded_at: datetime


def _map_rows(session: Session, target_id: str) -> list[MapRow]:
    rows = session.scalars(
        select(DisplayTargetItem).where(DisplayTargetItem.target_id == target_id)
    ).all()
    return [
        MapRow(
            id=row.id,
            artwork_id=row.artwork_id,
            render_hash=row.render_hash,
            content_id=row.content_id,
            position=row.position,
            uploaded_at=row.uploaded_at,
        )
        for row in rows
    ]


@dataclass(slots=True)
class PushPlan:
    """What a push will do, decided before anything is touched (`plan_push`)."""

    static: bool
    wanted: list[tuple[str, str]]
    """`(artwork_id, render_hash)` by position, 0 first."""
    gone: list[str] = field(default_factory=list)
    """Rows whose upload the TV no longer holds (deleted with the remote): forgotten."""
    reuse: dict[int, MapRow] = field(default_factory=dict)
    """Position → the upload already on the TV that serves it."""
    upload: list[int] = field(default_factory=list)
    """Positions to upload, in upload order: the last position first."""
    remove_ours: list[MapRow] = field(default_factory=list)
    """Slideshow mode: our uploads that are not part of the set — they would be shown too."""
    leave_ours: list[MapRow] = field(default_factory=list)
    """"Don't change": our uploads outside the set, which stay where they are."""
    foreign: list[str] = field(default_factory=list)
    """Content ids on the TV this app did not upload (empty when the TV was not asked)."""

    @property
    def set_count(self) -> int:
        return len(self.wanted)


def plan_push(
    wanted: list[tuple[str, str]],
    rows: list[MapRow],
    on_tv: set[str] | None,
    *,
    static: bool,
) -> PushPlan:
    """Decide a push. Pure: the push executes it and the dry run (`plan`) reports it.

    `on_tv` is what My Photos holds right now; None means the TV was not asked, and the map is
    taken at its word.

    **Slideshow mode** must leave the TV's newest-first list in set order. New uploads are always
    newer than everything already there, so only a *tail* of the set can be reused: walking from
    the last position up, an upload is kept while it is newer than the one kept after it. The
    first position that cannot be served that way is uploaded again, and so is every position
    before it — otherwise a re-uploaded middle image would jump ahead of its predecessors.

    **"Don't change"** shows the first image and rotates nothing, so any upload of the right
    render serves, whatever its position; our uploads outside the set are left alone.
    """
    plan = PushPlan(static=static, wanted=list(wanted))
    present = rows if on_tv is None else [r for r in rows if r.content_id in on_tv]
    if on_tv is not None:
        plan.gone = [r.id for r in rows if r.content_id not in on_tv]
        known = {r.content_id for r in rows}
        plan.foreign = sorted(on_tv - known)
    candidates: dict[tuple[str, str], list[MapRow]] = {}
    for row in sorted(present, key=lambda r: r.uploaded_at):
        candidates.setdefault((row.artwork_id, row.render_hash), []).append(row)
    used: set[str] = set()
    count = len(plan.wanted)
    if static:
        for position, key in enumerate(plan.wanted):
            free = [r for r in candidates.get(key, []) if r.id not in used]
            if free:
                row = free[-1]  # the newest upload of that render
                plan.reuse[position] = row
                used.add(row.id)
        plan.upload = [p for p in range(count - 1, -1, -1) if p not in plan.reuse]
    else:
        bound: datetime | None = None
        tail = count
        for position in range(count - 1, -1, -1):
            free = [
                r
                for r in candidates.get(plan.wanted[position], [])
                if r.id not in used and (bound is None or r.uploaded_at > bound)
            ]
            if not free:
                break
            row = free[0]  # the oldest that is still newer than the next one: leaves room above
            plan.reuse[position] = row
            used.add(row.id)
            bound = row.uploaded_at
            tail = position
        plan.upload = list(range(tail - 1, -1, -1))
    rest = [r for r in present if r.id not in used]
    if static:
        plan.leave_ours = rest
    else:
        plan.remove_ours = rest
    return plan


# ---- resolving the set --------------------------------------------------------------------------


def _query_from_source(source: dict[str, Any], *, status: str | None) -> library.ArtworkQuery:
    sort = str(source.get("sort") or "created_desc")
    return library.ArtworkQuery(
        filter=library.parse_query_filter(source.get("filter")),
        collection_id=source.get("collection_id"),
        include_nested=bool(source.get("include_nested")),
        favorite=source.get("favorite"),
        status=status,
        sort=sort,  # type: ignore[arg-type]
    )


def _explicit_ids(source: dict[str, Any]) -> list[str]:
    """An explicit list, in the order given, each artwork once."""
    return list(dict.fromkeys(str(i) for i in source.get("artwork_ids") or []))


def resolve_set(session: Session, source: dict[str, Any]) -> list[Artwork]:
    """The artworks of a source, in the order they should play.

    `status: "ready"` leaves the drafts out, for an explicit list as for a query. A query that
    matches more than `MAX_SET` artworks is refused rather than silently cut.
    """
    status = source.get("status")
    ids = _explicit_ids(source)
    if ids:
        stmt = select(Artwork).where(Artwork.id.in_(ids), Artwork.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(Artwork.status == status)
        rows = {a.id: a for a in session.scalars(stmt).all()}
        return [rows[i] for i in ids if i in rows]
    query = _query_from_source(source, status=status)
    if library.count_artworks(session, query=query) > MAX_SET:
        raise ProblemError(422, "set_too_large", f"A TV holds at most {MAX_SET} images")
    return library.list_artworks(session, query, limit=MAX_SET).items


def count_drafts(session: Session, source: dict[str, Any]) -> int:
    """Drafts the source holds, whatever its `status` says — what "Leave out N drafts" counts."""
    ids = _explicit_ids(source)
    if ids:
        return len(
            session.scalars(
                select(Artwork.id).where(
                    Artwork.id.in_(ids), Artwork.deleted_at.is_(None), Artwork.status == "draft"
                )
            ).all()
        )
    return library.count_artworks(session, query=_query_from_source(source, status="draft"))


def set_source(
    session: Session, target_id: str, *, source: dict[str, Any], label: str | None
) -> DisplayTarget:
    target = get_target(session, target_id)
    library.parse_query_filter(source.get("filter"))  # validates, raises `invalid_filter`
    target.source = source
    target.source_label = label
    return target


# ---- status -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TargetStatus:
    """What the TV says right now, plus what this app knows it put there."""

    info: TvInfo
    ours: int
    foreign: int
    """Items in My Photos this app did not upload — a slideshow push would have to delete them."""
    moved: Moved | None = None


def _forget(session: Session, row_ids: list[str]) -> None:
    if row_ids:
        session.execute(sql_delete(DisplayTargetItem).where(DisplayTargetItem.id.in_(row_ids)))


def _remember_counts(target: DisplayTarget, *, ours: int, foreign: int) -> None:
    now = utcnow()
    target.ours_count = ours
    target.foreign_count = foreign
    target.checked_at = now
    target.last_seen_at = now


def status(ctx: AppContext, session: Session, target_id: str) -> TargetStatus:
    """Ask the TV; refresh the cached counts, the model, the MAC — and follow it if it moved."""
    target = get_target(session, target_id)

    def probe(client: TvClient) -> tuple[TvInfo, set[str]]:
        info = client.info()
        return info, {i.content_id for i in client.items()}

    try:
        (info, on_tv), moved = _with_tv(ctx, _Tv.of(target), probe)
    except TvError as exc:
        target.last_error = exc.code
        target.state = "error"
        raise _problem(exc) from exc
    if moved is not None:
        session.refresh(target)  # the new host was committed by `_with_tv`
    rows = _map_rows(session, target.id)
    _forget(session, [r.id for r in rows if r.content_id not in on_tv])
    known = {r.content_id for r in rows}
    ours, foreign = len(on_tv & known), len(on_tv - known)
    target.model = info.model or target.model
    target.api_version = info.api_version or target.api_version
    target.mac = info.mac or target.mac
    target.last_error = None
    _remember_counts(target, ours=ours, foreign=foreign)
    if target.state in {"new", "error"}:
        target.state = "ready"
    return TargetStatus(info=info, ours=ours, foreign=foreign, moved=moved)


# ---- the dry run --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanSummary:
    """What a push of this source would do — the numbers the "Show on the TV" dialog states."""

    static: bool
    set_count: int
    to_upload: int
    already_there: int
    ours_to_remove: int
    """Slideshow mode: images sent before that leave the TV."""
    ours_left: int
    """"Don't change": images sent before that stay on the TV, untouched."""
    foreign: int | None
    """Photos this app did not send; None when the TV could not be asked and nothing is cached."""
    foreign_checked_at: datetime | None
    tv_error: str | None
    """Problem code when the TV did not answer (the numbers then come from the map)."""
    drafts: int
    """Drafts in the source, whatever `status` says."""
    drafts_left_out: int
    moved: Moved | None = None


def _wanted_hashes(ctx: AppContext, session: Session, set_: list[Artwork]) -> list[tuple[str, str]]:
    """The render hash each member would be pushed with — computed, not rendered."""
    return [
        (
            a.id,
            render.inputs_for(ctx, session, artworks_service.document_of(a), a.id).hash,
        )
        for a in set_
    ]


def plan(
    ctx: AppContext,
    session: Session,
    target_id: str,
    *,
    source: dict[str, Any] | None = None,
    slideshow_minutes: int | None = None,
    check_tv: bool = True,
) -> PlanSummary:
    """Dry-run a push: nothing is uploaded, deleted or selected. Asks the TV when `check_tv`."""
    target = get_target(session, target_id)
    effective = dict(source if source is not None else (target.source or {}))
    if not effective:
        raise ProblemError(422, "no_source", "This TV has no set to show yet")
    library.parse_query_filter(effective.get("filter"))
    minutes = check_interval(
        target.slideshow_minutes if slideshow_minutes is None else slideshow_minutes
    )
    members = resolve_set(session, effective)
    wanted = _wanted_hashes(ctx, session, members)
    drafts = count_drafts(session, effective)

    on_tv: set[str] | None = None
    tv_error: str | None = None
    moved: Moved | None = None
    if check_tv and target.token:
        try:
            on_tv, moved = _with_tv(
                ctx, _Tv.of(target), lambda c: {i.content_id for i in c.items()}
            )
        except TvError as exc:
            tv_error = exc.code
    elif check_tv:
        tv_error = "tv_unauthorized"
    if moved is not None:
        session.refresh(target)
    rows = _map_rows(session, target.id)
    result = plan_push(wanted, rows, on_tv, static=is_static(minutes))
    if on_tv is not None:
        _forget(session, result.gone)
        ours = len(on_tv & {r.content_id for r in rows})
        _remember_counts(target, ours=ours, foreign=len(result.foreign))
        target.last_error = None
    foreign = len(result.foreign) if on_tv is not None else target.foreign_count
    return PlanSummary(
        static=result.static,
        set_count=result.set_count,
        to_upload=len(result.upload),
        already_there=len(result.reuse),
        ours_to_remove=len(result.remove_ours),
        ours_left=len(result.leave_ours),
        foreign=foreign,
        foreign_checked_at=target.checked_at,
        tv_error=tv_error,
        drafts=drafts,
        drafts_left_out=drafts if effective.get("status") == "ready" else 0,
        moved=moved,
    )


# ---- pushing ------------------------------------------------------------------------------------


@dataclass(slots=True)
class PushResult:
    target_id: str
    static: bool = False
    uploaded: int = 0
    reused: int = 0
    deleted_ours: int = 0
    deleted_foreign: int = 0
    foreign_remaining: int = 0
    """Slideshow mode: items the app did not upload and was not allowed to delete — shown too."""
    foreign_on_tv: int = 0
    """Items the app did not upload, whatever the mode (in "Don't change" they are just there)."""
    left_ours: int = 0
    """"Don't change": our earlier uploads left on the TV."""
    total: int = 0
    slideshow_minutes: int | None = None
    first_content_id: str | None = None
    moved_from: str | None = None
    moved_to: str | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "mode": "static" if self.static else "slideshow",
            "uploaded": self.uploaded,
            "reused": self.reused,
            "deleted_ours": self.deleted_ours,
            "deleted_foreign": self.deleted_foreign,
            "foreign_remaining": self.foreign_remaining,
            "foreign_on_tv": self.foreign_on_tv,
            "left_ours": self.left_ours,
            "total": self.total,
            "slideshow_minutes": self.slideshow_minutes,
            "first_content_id": self.first_content_id,
            "moved_from": self.moved_from,
            "moved_to": self.moved_to,
            "warnings": list(self.warnings),
        }


def _date(stamp: datetime) -> str:
    return stamp.strftime("%Y:%m:%d %H:%M:%S")


def _image_base(target: DisplayTarget, rows: list[MapRow]) -> datetime:
    """Where this push's `image_date`s start: after every date already written to the TV.

    The TV lists newest first; if it sorts by `image_date`, a quick second push must still date
    its uploads after the first push's. Targets pushed before the clock existed (no
    `image_clock`) wrote `push start + (count − position)` minutes, so their dates end at most
    `len(rows)` minutes after their last upload.
    """
    now = utcnow()
    if target.image_clock is not None:
        return max(now, target.image_clock)
    if rows:
        return max(now, max(r.uploaded_at for r in rows) + timedelta(minutes=len(rows) + 1))
    return now


def _apply(
    ctx: AppContext,
    client: TvClient,
    target_id: str,
    *,
    wanted: list[tuple[str, str]],
    files: dict[str, Path],
    file_type: Literal["jpg", "png"],
    minutes: int,
    ordered: bool,
    allow_delete_foreign: bool,
    report: Report | None,
) -> PushResult:
    """Make the TV match the plan. Safe to repeat: it re-plans from what the TV holds."""
    static = is_static(minutes)
    on_tv = {item.content_id for item in client.items()}
    with ctx.db.session() as s:
        target = get_target(s, target_id)
        rows = _map_rows(s, target_id)
        base = _image_base(target, rows)
    plan_ = plan_push(wanted, rows, on_tv, static=static)
    result = PushResult(
        target_id=target_id,
        static=static,
        total=plan_.set_count,
        reused=len(plan_.reuse),
        foreign_on_tv=len(plan_.foreign),
    )
    with ctx.db.session() as s:
        _forget(s, plan_.gone)

    content_at: dict[int, str] = {p: row.content_id for p, row in plan_.reuse.items()}
    count = len(wanted)
    for done, position in enumerate(plan_.upload):
        artwork_id, render_hash = wanted[position]
        stamp = base + timedelta(minutes=count - position)
        content_id = client.upload(files[artwork_id].read_bytes(), file_type, _date(stamp))
        # Written at once, in its own transaction: whatever happens next, this upload is ours.
        with ctx.db.session() as s:
            s.add(
                DisplayTargetItem(
                    target_id=target_id,
                    artwork_id=artwork_id,
                    render_hash=render_hash,
                    content_id=content_id,
                    position=position,
                )
            )
            target = get_target(s, target_id)
            target.image_clock = max(stamp, target.image_clock or stamp)
        content_at[position] = content_id
        result.uploaded += 1
        if report:
            report("uploading", done + 1, len(plan_.upload))

    # Positions follow the set; anything of ours outside it is out of the set (NULL).
    in_set = {content_id: position for position, content_id in content_at.items()}
    with ctx.db.session() as s:
        for row in s.scalars(
            select(DisplayTargetItem).where(DisplayTargetItem.target_id == target_id)
        ).all():
            row.position = in_set.get(row.content_id)

    if static:
        result.left_ours = len(plan_.leave_ours)
    else:
        doomed = [row.content_id for row in plan_.remove_ours]
        removing = len(doomed) + (len(plan_.foreign) if allow_delete_foreign else 0)
        if removing and report:
            report("removing", 0, removing)
        if doomed:
            client.delete(doomed)
            with ctx.db.session() as s:
                _forget(s, [row.id for row in plan_.remove_ours])
            result.deleted_ours = len(doomed)
        # Anything somebody else put there: only with permission, never silently.
        if plan_.foreign and allow_delete_foreign:
            client.delete(plan_.foreign)
            result.deleted_foreign = len(plan_.foreign)
        elif plan_.foreign:
            result.foreign_remaining = len(plan_.foreign)
            result.warnings.append("foreign_items_remain")
        if removing and report:
            report("removing", removing, removing)

    # Stop → select → (start): selecting stops a running slideshow, and starting one never moves
    # the panel (both measured on 2025 firmware). "Don't change" stops at the selection.
    if report:
        report("starting", 0, 1)
    client.stop_slideshow()
    first = content_at.get(0)
    if first:
        client.select(first)
        result.first_content_id = first
    if not static:
        client.start_slideshow(minutes, ordered)
        result.slideshow_minutes = minutes
    if report:
        report("starting", 1, 1)
    return result


def push(
    ctx: AppContext,
    target_id: str,
    *,
    allow_delete_foreign: bool = False,
    report: Report | None = None,
) -> PushResult:
    """Make the TV show this target's set. Idempotent: re-pushing uploads nothing.

    `allow_delete_foreign` only means something in slideshow mode: "Don't change" deletes nothing.
    Whatever fails — an empty set as much as a sleeping TV — the target ends in `error` with the
    code, and without the progress `enqueue_push` stored (or the tray would wait forever).
    """
    try:
        with ctx.db.session() as s:
            target = get_target(s, target_id)
            source = dict(target.source or {})
            if not source:
                raise ProblemError(422, "no_source", "This TV has no set to show yet")
            members = resolve_set(s, source)
            if not members:
                raise ProblemError(422, "empty_set", "That set has no artworks")
            wanted_ids = [a.id for a in members]
            tv = _Tv.of(target)
            file_type: Literal["jpg", "png"] = "png" if target.render_format == "png" else "jpg"
            minutes, ordered = target.slideshow_minutes, target.slideshow_ordered
            target.state = "pushing"
            target.last_error = None

        # Rendering is slow and needs no TV, so it happens before the connection is opened.
        files: dict[str, Path] = {}
        wanted: list[tuple[str, str]] = []
        for index, artwork_id in enumerate(wanted_ids):
            path, render_hash = render.derivative(ctx, artwork_id, file_type)
            files[artwork_id] = path
            wanted.append((artwork_id, render_hash))
            if report:
                report("rendering", index + 1, len(wanted_ids))

        result, moved = _with_tv(
            ctx,
            tv,
            lambda client: _apply(
                ctx,
                client,
                target_id,
                wanted=wanted,
                files=files,
                file_type=file_type,
                minutes=minutes,
                ordered=ordered,
                allow_delete_foreign=allow_delete_foreign,
                report=report,
            ),
        )
    except Exception as exc:
        code = getattr(exc, "code", None) or "push_failed"
        with ctx.db.session() as s:
            failed = s.get(DisplayTarget, target_id)
            if failed is not None:  # a target deleted while its push was queued has no state
                failed.state = "error"
                failed.last_error = str(code)[:64]
                failed.progress = None
        raise

    if moved is not None:
        result.moved_from, result.moved_to = moved.old_host, moved.new_host
        result.warnings.append("tv_moved")
    with ctx.db.session() as s:
        target = get_target(s, target_id)
        ours = len(_map_rows(s, target_id))
        foreign = result.foreign_on_tv - result.deleted_foreign
        _remember_counts(target, ours=ours, foreign=foreign)
        target.state = "ready"
        target.last_error = None
        target.progress = None
        target.last_pushed_at = utcnow()
        target.last_result = {**result.as_dict(), "finished_at": utcnow().isoformat()}

    ctx.broker.publish(Event("display.pushed", result.as_dict()))
    return result


# ---- the job ------------------------------------------------------------------------------------


def _progress_out(job_id: str, phase: Phase, done: int, total: int) -> dict[str, Any]:
    return {"job_id": job_id, "phase": phase, "done": done, "total": total}


#: Where each phase sits in the job's overall progress (rendering is per artwork, uploads take
#: 4 to 6 s each on the real TV, removing and starting are a few calls).
_SPANS: dict[Phase, tuple[float, float]] = {
    "queued": (0.0, 0.0),
    "rendering": (0.0, 0.4),
    "uploading": (0.4, 0.9),
    "removing": (0.9, 0.95),
    "starting": (0.95, 1.0),
}


def progress_reporter(ctx: AppContext, target_id: str, job: JobContext) -> Report:
    """Publish `display.progress` (throttled), keep it on the target, and move the job's bar."""
    last: dict[str, Any] = {"phase": None, "at": 0.0}

    def report(phase: Phase, done: int, total: int) -> None:
        now = time.monotonic()
        boundary = phase != last["phase"] or done >= total
        if not boundary and now - last["at"] < PROGRESS_EVERY_SECONDS:
            return
        last.update(phase=phase, at=now)
        payload = _progress_out(job.job_id, phase, done, total)
        with ctx.db.session() as s:
            target = s.get(DisplayTarget, target_id)
            if target is not None:
                target.progress = payload
        ctx.broker.publish(Event("display.progress", {"target_id": target_id, **payload}))
        start, end = _SPANS[phase]
        job.progress(start + (end - start) * (done / total if total else 1.0))

    return report


def enqueue_push(ctx: AppContext, target_id: str, *, allow_delete_foreign: bool = False) -> str:
    job_id = ctx.jobs.enqueue(
        PUSH_JOB,
        {"target_id": target_id, "allow_delete_foreign": allow_delete_foreign},
        coalesce_key=f"{PUSH_JOB}:{target_id}",
    )
    queued = _progress_out(job_id, "queued", 0, 0)
    with ctx.db.session() as s:
        get_target(s, target_id).progress = queued
    ctx.broker.publish(Event("display.progress", {"target_id": target_id, **queued}))
    return job_id


def push_job(ctx: AppContext) -> JobHandler:
    def handler(job: JobContext) -> None:
        target_id = str(job.payload["target_id"])
        try:
            push(
                ctx,
                target_id,
                allow_delete_foreign=bool(job.payload.get("allow_delete_foreign")),
                report=progress_reporter(ctx, target_id, job),
            )
        except TvError as exc:
            # No automatic retry: a TV that is off stays off for longer than three attempts, and
            # /activity offers "Retry" with the reason spelled out.
            raise PermanentJobError(exc.code, str(exc)) from exc
        except (ProblemError, RenderError) as exc:
            raise PermanentJobError(exc.code, str(exc)) from exc

    return handler


def _problem(exc: TvError) -> ProblemError:
    titles = {
        "tv_unreachable": "The TV did not answer",
        "tv_art_unavailable": "The TV's art mode did not answer",
        "tv_unauthorized": "The TV no longer trusts this app",
        "tv_rejected": "The TV refused that",
    }
    status_code = 409 if exc.code == "tv_unauthorized" else 502
    return ProblemError(status_code, exc.code, titles.get(exc.code, "TV error"), str(exc))
