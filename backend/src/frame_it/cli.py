"""Command line interface: `frame-it --help`."""

from __future__ import annotations

import json
import logging
import shutil
import webbrowser
from pathlib import Path
from typing import Annotated, Any

import typer

from frame_it import __version__
from frame_it.config import Settings, load_settings

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Frame It server")
db_app = typer.Typer(no_args_is_help=True, help="Database maintenance")
cache_app = typer.Typer(no_args_is_help=True, help="Cache maintenance")
service_app = typer.Typer(no_args_is_help=True, help="Run the server at login (systemd / launchd)")
tv_app = typer.Typer(no_args_is_help=True, help="The TV a set is shown on (docs/tv-display.md)")
app.add_typer(db_app, name="db")
app.add_typer(cache_app, name="cache")
app.add_typer(service_app, name="service")
app.add_typer(tv_app, name="tv")

DataDir = Annotated[
    Path | None, typer.Option("--data-dir", envvar="FRAME_IT_DATA_DIR", help="Library data dir")
]


def _settings(data_dir: Path | None, **overrides: object) -> Settings:
    return load_settings(data_dir=data_dir, **overrides)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(), format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )


@app.command()
def serve(
    data_dir: DataDir = None,
    host: Annotated[str | None, typer.Option(help="Bind address")] = None,
    port: Annotated[int | None, typer.Option(help="Port")] = None,
    public_url: Annotated[str | None, typer.Option(help="URL phones use (QR codes)")] = None,
    open_browser: Annotated[bool, typer.Option("--open/--no-open", help="Open the UI")] = False,
    reload: Annotated[bool, typer.Option(help="Auto-reload (development)")] = False,
) -> None:
    """Run the server."""
    import uvicorn

    settings = _settings(data_dir, host=host, port=port, public_url=public_url)
    _configure_logging(settings.log_level)
    if open_browser:
        webbrowser.open(f"{settings.scheme}://localhost:{settings.port}")
    if reload:
        uvicorn.run(
            "frame_it.asgi:app",
            host=settings.host,
            port=settings.port,
            reload=True,
            proxy_headers=False,
        )
        return
    from frame_it.app import create_app

    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        ssl_certfile=str(settings.tls_cert) if settings.tls_cert else None,
        ssl_keyfile=str(settings.tls_key) if settings.tls_key else None,
        proxy_headers=False,
        log_level=settings.log_level.lower(),
    )


@app.command()
def doctor(data_dir: DataDir = None) -> None:
    """Report configuration and image-processing capabilities."""
    from frame_it.imaging import capabilities

    settings = _settings(data_dir)
    caps = capabilities.detect()
    report = {
        "version": __version__,
        "data_dir": str(settings.data_dir),
        "public_url": settings.effective_public_url,
        "trust_localhost": settings.effective_trust_localhost,
        "capabilities": caps.as_dict(),
        "missing_required": caps.missing_required,
    }
    typer.echo(json.dumps(report, indent=2))
    if caps.missing_required:
        raise typer.Exit(1)


@app.command("setup-code")
def setup_code(data_dir: DataDir = None) -> None:
    """Issue a new one-time setup code to register a remote browser as admin."""
    from frame_it.db.migrate import upgrade_to_head
    from frame_it.db.session import Database
    from frame_it.services.devices import issue_setup_code

    settings = _settings(data_dir)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.db_path)
    upgrade_to_head(db.engine)
    with db.session() as s:
        issued = issue_setup_code(s)
    typer.echo(f"Setup code: {issued.code} (valid {issued.expires_in_seconds // 60} min)")
    typer.echo(f"Open {settings.effective_public_url}/setup and enter it.")


@db_app.command("upgrade")
def db_upgrade(data_dir: DataDir = None) -> None:
    """Apply database migrations."""
    from frame_it.db.migrate import upgrade_to_head
    from frame_it.db.session import Database

    settings = _settings(data_dir)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    upgrade_to_head(Database(settings.db_path).engine)
    typer.echo("Database is up to date.")


@cache_app.command("clear")
def cache_clear(data_dir: DataDir = None) -> None:
    """Delete all cached derivatives (regenerated on demand)."""
    settings = _settings(data_dir)
    if settings.cache_dir.is_dir():
        shutil.rmtree(settings.cache_dir)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    typer.echo(f"Cleared {settings.cache_dir}")


# ---- service ------------------------------------------------------------------------------------


def _service_plan(data_dir: Path | None, public_url: str | None) -> tuple[Any, Settings]:
    from frame_it import service

    settings = _settings(data_dir, public_url=public_url)
    try:
        return service.plan(settings.data_dir, public_url=settings.public_url), settings
    except service.ServiceError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


@service_app.command("install")
def service_install(
    data_dir: DataDir = None,
    public_url: Annotated[
        str | None, typer.Option(help="URL phones use (QR codes); baked into the unit")
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing unit")] = False,
    show: Annotated[bool, typer.Option("--show", help="Print the unit, write nothing")] = False,
) -> None:
    """Write a user service unit for this machine (it is not started for you)."""
    plan, settings = _service_plan(data_dir, public_url)
    if show:
        typer.echo(plan.content)
        return
    if plan.path.exists() and not force:
        typer.echo(f"{plan.path} already exists (use --force to replace it).", err=True)
        raise typer.Exit(1)
    plan.path.parent.mkdir(parents=True, exist_ok=True)
    plan.path.write_text(plan.content)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    typer.echo(f"Wrote {plan.kind} unit: {plan.path}")
    typer.echo(f"Library: {settings.data_dir}")
    typer.echo("\nEnable it with:")
    for command in plan.enable:
        typer.echo(f"  {command}")


@service_app.command("uninstall")
def service_uninstall(data_dir: DataDir = None) -> None:
    """Remove the unit this machine's `service install` wrote (the library is untouched)."""
    plan, _ = _service_plan(data_dir, None)
    if not plan.path.exists():
        typer.echo(f"Nothing to remove at {plan.path}.")
        return
    typer.echo("Stop it first with:")
    for command in plan.disable:
        typer.echo(f"  {command}")
    plan.path.unlink()
    typer.echo(f"\nRemoved {plan.path}")


@service_app.command("status")
def service_status(data_dir: DataDir = None) -> None:
    """Report whether a unit is installed, and what it points at."""
    plan, settings = _service_plan(data_dir, None)
    typer.echo(
        json.dumps(
            {
                "kind": plan.kind,
                "path": str(plan.path),
                "installed": plan.path.exists(),
                "data_dir": str(settings.data_dir),
                "public_url": settings.effective_public_url,
            },
            indent=2,
        )
    )


@app.command()
def openapi(
    output: Annotated[Path, typer.Option("--output", "-o", help="Destination JSON file")],
) -> None:
    """Export the OpenAPI schema (used to generate frontend types)."""
    import tempfile

    from frame_it.app import create_app

    with tempfile.TemporaryDirectory() as tmp:
        schema = create_app(Settings(data_dir=Path(tmp)), start_workers=False).openapi()
    output.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    typer.echo(f"Wrote {output}")


@app.command()
def schemas(
    output: Annotated[Path, typer.Option("--output", "-o", help="Destination directory")],
) -> None:
    """Export the JSON Schemas of published documents and of the archive format."""
    from frame_it.domain import archive, document, templates

    output.mkdir(parents=True, exist_ok=True)
    for name, schema in schema_documents(document, templates).items():
        (output / name).write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
        typer.echo(f"Wrote {output / name}")
    archive_dir = output / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    for name, schema in archive.json_schemas().items():
        (archive_dir / name).write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
        typer.echo(f"Wrote {archive_dir / name}")


def schema_documents(document: Any, templates: Any) -> dict[str, dict[str, Any]]:
    base = "https://frame-it/schemas/"
    result = {"artwork-document.v1.json": document.json_schema()}
    for filename, model, title in (
        ("frame-style.v1.json", templates.FrameStyleDocument, "Frame style document v1"),
        ("layout.v1.json", templates.LayoutDocument, "Layout document v1"),
    ):
        schema = model.model_json_schema(mode="validation")
        schema.update(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": base + filename,
                "title": title,
            }
        )
        result[filename] = schema
    return result


@app.command("export")
def export_archive(
    output: Annotated[Path, typer.Option("--out", "-o", help="File to write")],
    data_dir: DataDir = None,
    kind: Annotated[
        str, typer.Option("--kind", help="library (a .tfarchive) or renders (a ZIP of images)")
    ] = "library",
    artwork: Annotated[
        list[str] | None, typer.Option("--artwork", help="Artwork id (repeatable)")
    ] = None,
    collection: Annotated[
        list[str] | None, typer.Option("--collection", help="Collection id (repeatable)")
    ] = None,
    nested: Annotated[
        bool, typer.Option("--nested/--no-nested", help="Follow sub-collections")
    ] = True,
    renders: Annotated[bool, typer.Option("--renders", help="Include rendered PNGs")] = False,
    templates: Annotated[bool, typer.Option("--templates/--no-templates")] = True,
    image_format: Annotated[str, typer.Option("--format", help="renders: jpg or png")] = "jpg",
) -> None:
    """Write an archive (docs/archive-format.md). No selection exports the whole library."""
    from frame_it.app import build_context
    from frame_it.services import archive_export

    settings = _settings(data_dir)
    _configure_logging(settings.log_level)
    ctx = build_context(settings)
    options = archive_export.ExportOptions(
        kind="renders" if kind == "renders" else "library",
        artwork_ids=tuple(artwork or ()),
        collection_ids=tuple(collection or ()),
        include_nested=nested,
        include_renders=renders,
        include_templates=templates,
        render_format="png" if image_format == "png" else "jpg",
    )
    write = archive_export.write_render_zip if kind == "renders" else archive_export.write_archive
    result = write(ctx, options, output)
    ctx.db.dispose()
    typer.echo(json.dumps({"path": str(result.path), "scope": result.scope, **result.counts}))
    for warning in result.warnings:
        typer.echo(f"warning: {warning}", err=True)


@app.command("import")
def import_archive(
    source: Annotated[Path, typer.Argument(help="Archive to read")],
    data_dir: DataDir = None,
    policy: Annotated[
        str, typer.Option("--policy", help="keep_mine | take_theirs | keep_both (conflicts)")
    ] = "keep_mine",
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Report only, write nothing")] = False,
) -> None:
    """Import an archive, reporting what it would do first (docs/archive-format.md §12.2)."""
    from frame_it.app import build_context
    from frame_it.domain import archive
    from frame_it.services import archive_apply, archive_import

    if policy not in archive.POLICIES:
        typer.echo(f"Unknown policy {policy!r} (use {', '.join(archive.POLICIES)})", err=True)
        raise typer.Exit(2)
    settings = _settings(data_dir)
    _configure_logging(settings.log_level)
    ctx = build_context(settings)
    import_id, report = archive_import.stage_local(ctx, source)
    typer.echo(json.dumps(report.summary(), indent=2, sort_keys=True))
    for warning in report.warnings:
        typer.echo(f"warning: {warning}", err=True)
    if dry_run:
        with ctx.db.session() as session:
            archive_import.delete_import(ctx, session, import_id)
        ctx.db.dispose()
        return
    result = archive_apply.apply_import(
        ctx,
        import_id,
        archive_apply.Policies(default=policy),
    )
    ctx.jobs.run_pending_sync()  # render what the import left to render, then exit
    ctx.db.dispose()
    typer.echo(json.dumps(result.as_dict(), indent=2, sort_keys=True))


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


def main() -> None:
    app()


# ---- TV -----------------------------------------------------------------------------------------


def _display_ctx(data_dir: Path | None) -> Any:
    from frame_it.app import build_context

    settings = _settings(data_dir)
    _configure_logging(settings.log_level)
    return build_context(settings)


@tv_app.command("add")
def tv_add(
    host: Annotated[str, typer.Argument(help="The TV's IP address")],
    name: Annotated[str, typer.Option("--name", help="What to call it")] = "The Frame",
    data_dir: DataDir = None,
) -> None:
    """Register a TV. Pair it next — the TV must be ON for its dialog to appear."""
    from frame_it.services import display

    ctx = _display_ctx(data_dir)
    with ctx.db.session() as s:
        target = display.create_target(s, name=name, host=host)
        typer.echo(f"{target.id}  {target.name}  {target.host}")


@tv_app.command("scan")
def tv_scan(data_dir: DataDir = None) -> None:
    """Find Samsung TVs on the LAN (SSDP + a sweep of the /24). Read-only."""
    from frame_it.services import display

    ctx = _display_ctx(data_dir)
    with ctx.db.session() as s:
        subnet, found = display.discover(ctx, s)
    typer.echo(f"Scanned {subnet}.1-254" if subnet else "No LAN /24 known: SSDP only.")
    if not found:
        typer.echo("No TV answered — is it on the same network, and was it awake once?")
    for f in found:
        tv = f.tv
        kind = "The Frame" if tv.frame_support else "Samsung TV"
        added = f"  (added: {f.target_id})" if f.target_id else ""
        label = f"{tv.name or '?'} — {tv.model or '?'} [{kind}]"
        typer.echo(f"{tv.host:<16} {label} mac {tv.mac or '?'}{added}")


@tv_app.command("list")
def tv_list(data_dir: DataDir = None) -> None:
    """Every TV this library knows."""
    from frame_it.services import display

    ctx = _display_ctx(data_dir)
    with ctx.db.session() as s:
        targets = display.list_targets(s)
        if not targets:
            typer.echo("No TV yet. Add one with `frame-it tv add <ip>`.")
        for t in targets:
            paired = "paired" if t.token else "NOT PAIRED"
            shown = t.source_label or "no set"
            rotation = (
                "don't change"
                if display.is_static(t.slideshow_minutes)
                else f"every {t.slideshow_minutes} min"
            )
            typer.echo(f"{t.id}  {t.name} ({t.host})  {paired}  {shown}  {rotation}")


@tv_app.command("pair")
def tv_pair(
    target_id: Annotated[str, typer.Argument(help="Target id (`tv list`)")],
    data_dir: DataDir = None,
) -> None:
    """Ask the TV for a token: accept the prompt on screen. The TV must be ON, not in art mode."""
    from frame_it.services import display

    ctx = _display_ctx(data_dir)
    typer.echo("Accept the 'allow this device' prompt on the TV …")
    with ctx.db.session() as s:
        target = display.pair(ctx, s, target_id)
        typer.echo(f"Paired with {target.name} ({target.host}).")


@tv_app.command("status")
def tv_status(
    target_id: Annotated[str, typer.Argument(help="Target id (`tv list`)")],
    data_dir: DataDir = None,
) -> None:
    """What the TV says right now, and how much of what it holds came from this app."""
    from frame_it.services import display

    ctx = _display_ctx(data_dir)
    with ctx.db.session() as s:
        result = display.status(ctx, s, target_id)
    info = result.info
    if result.moved:
        typer.echo(f"The TV moved: {result.moved.old_host} -> {result.moved.new_host} (followed).")
    typer.echo(f"{info.name or '?'} — {info.model or '?'} (art API {info.api_version or '?'})")
    typer.echo(f"art mode: {'on' if info.art_mode else 'off'}")
    typer.echo(f"my photos: {info.my_pictures} ({result.ours} from this app, {result.foreign} not)")
    if info.slideshow_minutes:
        kind = "ordered" if info.slideshow_ordered else "shuffled"
        typer.echo(f"slideshow: every {info.slideshow_minutes} min, {kind}")
    else:
        typer.echo("slideshow: off")


@tv_app.command("push")
def tv_push(
    target_id: Annotated[str, typer.Argument(help="Target id (`tv list`)")],
    collection: Annotated[
        str | None, typer.Option("--collection", help="Collection id to show")
    ] = None,
    favorites: Annotated[bool, typer.Option("--favorites", help="Show the Favorites view")] = False,
    every: Annotated[
        int | None,
        typer.Option(
            "--every",
            help="Minutes between images (3, 15, 60, 720, 1440), or 0: don't change — show the "
            "first image and leave everything else on the TV untouched",
        ),
    ] = None,
    shuffle: Annotated[bool, typer.Option("--shuffle", help="Shuffle instead of in order")] = False,
    yes_delete_others: Annotated[
        bool,
        typer.Option(
            "--yes-delete-others",
            help="Delete photos on the TV this app did not upload (irreversible; ignored with "
            "--every 0, which deletes nothing)",
        ),
    ] = False,
    keep_previous: Annotated[
        bool,
        typer.Option(
            "--keep-previous",
            help="Leave the images this app sent before on the TV (they play along with the set)",
        ),
    ] = False,
    data_dir: DataDir = None,
) -> None:
    """Make the TV show a set. Without --collection/--favorites it re-pushes the current one."""
    from frame_it.services import display

    ctx = _display_ctx(data_dir)
    with ctx.db.session() as s:
        if collection or favorites:
            source: dict[str, Any] = {"sort": "manual" if collection else "created_desc"}
            label = "Favorites"
            if collection:
                source["collection_id"] = collection
                label = f"Collection {collection}"
            if favorites:
                source["favorite"] = True
                source["sort"] = "created_desc"
            display.set_source(s, target_id, source=source, label=label)
        if every is not None or shuffle:
            display.update_target(
                s,
                target_id,
                slideshow_minutes=every,
                slideshow_ordered=False if shuffle else None,
            )
    phases = {"rendering": "Rendering", "uploading": "Uploading", "removing": "Removing"}

    def report(phase: str, done: int, total: int) -> None:
        if phase in phases and total and done == total:
            typer.echo(f"{phases[phase]}: {done}/{total}")

    result = display.push(
        ctx,
        target_id,
        allow_delete_foreign=yes_delete_others,
        keep_ours=keep_previous,
        report=report,
    )
    if result.moved_to:
        typer.echo(f"The TV moved: {result.moved_from} -> {result.moved_to} (followed).")
    typer.echo(
        f"{result.total} artwork(s): {result.uploaded} uploaded, {result.reused} already there, "
        f"{result.deleted_ours} removed."
    )
    if result.deleted_foreign:
        typer.echo(f"{result.deleted_foreign} photo(s) not from this app were deleted.")
    if result.foreign_remaining:
        typer.echo(
            f"WARNING: {result.foreign_remaining} photo(s) on the TV are not part of this set and "
            "are still shown. Re-run with --yes-delete-others to remove them."
        )
    if result.static:
        left = (
            f" ({result.left_ours} image(s) sent before are still there)"
            if result.left_ours
            else ""
        )
        typer.echo(f"Showing the first image, no slideshow. Nothing else was touched{left}.")
    else:
        if result.left_ours:
            typer.echo(f"{result.left_ours} image(s) sent before were kept and play along.")
        typer.echo(f"Slideshow: every {result.slideshow_minutes} min.")
