"""Database engine, session factory and schema creation.

SQLite via SQLAlchemy.  The database file and its parent directory are created
on startup, so no manual SQL or migration step is needed to run Omnicient.
The session factory is exposed both as a FastAPI dependency (:func:`get_db`)
and as a context manager (:func:`session_scope`) for services and scripts.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models.base import Base
from .utils.logging import get_logger

logger = get_logger(__name__)

_settings = get_settings()


def _ensure_sqlite_directory(database_url: str) -> None:
    """Create the parent directory of a file-backed SQLite database."""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return
    path = database_url[len(prefix) :]
    if path in ("", ":memory:"):
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_directory(_settings.database_url)

engine: Engine = create_engine(
    _settings.database_url,
    future=True,
    # SQLite + FastAPI: the connection may be used from a different worker
    # thread than the one that created it.
    connect_args={"check_same_thread": False}
    if _settings.database_url.startswith("sqlite")
    else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ANN001
    """Enable foreign key enforcement, which SQLite disables by default."""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:  # pragma: no cover - non-SQLite backends
        pass


def init_db() -> None:
    """Create every table that does not yet exist."""
    # Importing the model modules registers them on the declarative metadata.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("database_ready url=%s", _settings.database_url)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager yielding a session that commits or rolls back."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
