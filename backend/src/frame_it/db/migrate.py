"""Programmatic Alembic helpers (no alembic.ini needed)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


def upgrade_to_head(engine: Engine) -> None:
    cfg = alembic_config()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")


def autogenerate(engine: Engine, message: str) -> None:
    """Developer helper: `uv run python -m frame_it.db.migrate "message"`."""
    cfg = alembic_config()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.revision(cfg, message=message, autogenerate=True)


if __name__ == "__main__":
    import sys
    import tempfile

    from frame_it.db.session import create_sqlite_engine

    with tempfile.TemporaryDirectory() as tmp:
        eng = create_sqlite_engine(Path(tmp) / "gen.db")
        upgrade_to_head(eng)
        autogenerate(eng, sys.argv[1])
