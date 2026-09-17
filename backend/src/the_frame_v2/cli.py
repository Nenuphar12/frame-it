"""Command line interface: `the_frame_v2 --help`."""

from __future__ import annotations

import json
import logging
import shutil
import webbrowser
from pathlib import Path
from typing import Annotated

import typer

from the_frame_v2 import __version__
from the_frame_v2.config import Settings, load_settings

app = typer.Typer(no_args_is_help=True, add_completion=False, help="the_frame_v2 server")
db_app = typer.Typer(no_args_is_help=True, help="Database maintenance")
cache_app = typer.Typer(no_args_is_help=True, help="Cache maintenance")
app.add_typer(db_app, name="db")
app.add_typer(cache_app, name="cache")

DataDir = Annotated[
    Path | None, typer.Option("--data-dir", envvar="THE_FRAME_V2_DATA_DIR", help="Library data dir")
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
            "the_frame_v2.asgi:app",
            host=settings.host,
            port=settings.port,
            reload=True,
            proxy_headers=False,
        )
        return
    from the_frame_v2.app import create_app

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
    from the_frame_v2.imaging import capabilities

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
    from the_frame_v2.db.migrate import upgrade_to_head
    from the_frame_v2.db.session import Database
    from the_frame_v2.services.devices import issue_setup_code

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
    from the_frame_v2.db.migrate import upgrade_to_head
    from the_frame_v2.db.session import Database

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


@app.command()
def openapi(
    output: Annotated[Path, typer.Option("--output", "-o", help="Destination JSON file")],
) -> None:
    """Export the OpenAPI schema (used to generate frontend types)."""
    import tempfile

    from the_frame_v2.app import create_app

    with tempfile.TemporaryDirectory() as tmp:
        schema = create_app(Settings(data_dir=Path(tmp)), start_workers=False).openapi()
    output.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    typer.echo(f"Wrote {output}")


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


def main() -> None:
    app()
