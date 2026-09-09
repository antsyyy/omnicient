"""Shared test fixtures.

The suite splits in two.  Pure-logic tests - identifier detection,
normalization, URL parsing, correlation scoring, source adapters - need no
database and always run.  Persistence and API tests need Neo4j; they use the
``repo`` and ``client`` fixtures and are skipped with a clear message when no
database is reachable, so a contributor without Neo4j still gets a useful run.

Point the suite at a scratch database with ``NEO4J_TEST_URI`` /
``NEO4J_TEST_DATABASE``.  Whatever database it lands on is **wiped** at the
start of the session, so never aim it at real investigation data.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("OMNICIENT_DEMO_MODE", "true")
os.environ.setdefault("OMNICIENT_REQUEST_DELAY", "0")
os.environ.setdefault("OMNICIENT_LOG_LEVEL", "WARNING")

# Tests talk to the test DBMS, falling back to the normal connection settings.
os.environ["NEO4J_URI"] = os.getenv(
    "NEO4J_TEST_URI", os.getenv("NEO4J_URI", "bolt://localhost:7687")
)
os.environ["NEO4J_USERNAME"] = os.getenv(
    "NEO4J_TEST_USERNAME", os.getenv("NEO4J_USERNAME", "neo4j")
)
os.environ["NEO4J_PASSWORD"] = os.getenv(
    "NEO4J_TEST_PASSWORD", os.getenv("NEO4J_PASSWORD", "")
)
# Neo4j Community serves a single database, so the default here is the same
# one the application uses - hence the wipe warning above.
os.environ["NEO4J_DATABASE"] = os.getenv(
    "NEO4J_TEST_DATABASE", os.getenv("NEO4J_DATABASE", "neo4j")
)
os.environ.setdefault("NEO4J_STARTUP_TIMEOUT", "5")

SKIP_REASON = (
    "Neo4j is not reachable. Start it (docker compose up -d neo4j) or set "
    "NEO4J_TEST_URI / NEO4J_TEST_PASSWORD to run the persistence and API tests."
)


def _database_available() -> bool:
    from app.database import wait_for_neo4j

    try:
        return wait_for_neo4j(timeout=5)
    except Exception:  # noqa: BLE001 - absence is the thing being tested
        return False


@pytest.fixture(scope="session")
def neo4j_available() -> bool:
    return _database_available()


@pytest.fixture(scope="session", autouse=True)
def _database(neo4j_available: bool) -> Iterator[None]:
    """Apply constraints and start from an empty graph."""
    if not neo4j_available:
        yield
        return

    from app.database import close_driver, init_db, repository_scope

    init_db()
    with repository_scope() as repo:
        repo.session.run("MATCH (n) DETACH DELETE n")
    yield
    close_driver()


@pytest.fixture
def repo(neo4j_available: bool) -> Iterator:
    """A repository bound to a fresh session, on an empty graph."""
    if not neo4j_available:
        pytest.skip(SKIP_REASON)

    from app.database import repository_scope

    with repository_scope() as repository:
        repository.session.run("MATCH (n) DETACH DELETE n")
        yield repository


@pytest.fixture
def client(neo4j_available: bool) -> Iterator:
    """FastAPI test client with startup/shutdown handlers applied."""
    if not neo4j_available:
        pytest.skip(SKIP_REASON)

    from fastapi.testclient import TestClient

    from app.database import repository_scope
    from app.main import app

    with repository_scope() as repository:
        repository.session.run("MATCH (n) DETACH DELETE n")

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def demo_registry():
    """The offline demo source registry."""
    from app.demo_data import build_demo_registry

    return build_demo_registry()
