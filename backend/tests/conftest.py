"""Shared test fixtures.

Every test runs against a throwaway SQLite file in demo mode, with the polite
request delay disabled, so the suite is fast and never touches the network.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

_TMP_DB = Path(tempfile.mkdtemp(prefix="omnicient-tests-")) / "test.db"
os.environ.setdefault("OMNICIENT_DATABASE_URL", f"sqlite:///{_TMP_DB}")
os.environ.setdefault("OMNICIENT_DEMO_MODE", "true")
os.environ.setdefault("OMNICIENT_REQUEST_DELAY", "0")
os.environ.setdefault("OMNICIENT_LOG_LEVEL", "WARNING")

from app.database import SessionLocal, engine, init_db  # noqa: E402
from app.models.base import Base  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db() -> Iterator:
    """A session that rolls its data back after each test."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> Iterator:
    """FastAPI test client with startup/shutdown handlers applied."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def demo_registry():
    """The offline demo source registry."""
    from app.demo_data import build_demo_registry

    return build_demo_registry()
