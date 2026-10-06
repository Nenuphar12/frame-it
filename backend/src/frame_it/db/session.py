"""Engine and session factory (SQLite, WAL)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from frame_it.domain.geo import haversine_km

DISTANCE_FUNCTION = "tf_distance_km"
"""`tf_distance_km(lat1, lon1, lat2, lon2)`: great-circle km, NULL when a position is missing —
what the `place near` filter clause compiles to (SQLite's own math functions are a build option)."""


def _distance_km(
    lat1: float | None, lon1: float | None, lat2: float | None, lon2: float | None
) -> float | None:
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    return haversine_km(lat1, lon1, lat2, lon2)


def create_sqlite_engine(db_path: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_size=10,
        max_overflow=10,
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()
        dbapi_conn.create_function(DISTANCE_FUNCTION, 4, _distance_km, deterministic=True)

    return engine


class Database:
    """Owns the engine and hands out sessions. One instance per application."""

    def __init__(self, db_path: Path) -> None:
        self.engine = create_sqlite_engine(db_path)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Transactional scope: commit on success, rollback on error."""
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
