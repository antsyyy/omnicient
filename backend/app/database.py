"""Neo4j driver lifecycle, schema bootstrap and repository access.

Neo4j is Omnicient's primary and only datastore.  An investigation *is* a
graph, so storing it as one removes a whole translation layer: the nodes the
analyst sees in the interface are the nodes on disk, and "which accounts are
two hops from this website?" is a query rather than a join plan.

This module owns the process-wide driver.  Data access lives in
:mod:`app.repository`; everything else in the application takes a
:class:`~app.repository.Neo4jRepository` rather than a driver or a session, so
services never build Cypher of their own.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from .config import get_settings
from .repository import Neo4jRepository
from .utils.logging import get_logger

logger = get_logger(__name__)

_driver: Driver | None = None


class DatabaseUnavailableError(RuntimeError):
    """Raised when Neo4j cannot be reached.

    The API turns this into a 503 rather than leaking driver internals.
    """


#: Constraints create the indexes that back them, so uniqueness and lookup
#: speed are declared together.  Section 37 calls out the fields that matter.
CONSTRAINTS: tuple[str, ...] = (
    "CREATE CONSTRAINT investigation_id IF NOT EXISTS "
    "FOR (n:Investigation) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT entity_id IF NOT EXISTS "
    "FOR (n:Entity) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT evidence_id IF NOT EXISTS "
    "FOR (n:Evidence) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT snapshot_id IF NOT EXISTS "
    "FOR (n:Snapshot) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT crawl_event_id IF NOT EXISTS "
    "FOR (n:CrawlEvent) REQUIRE n.id IS UNIQUE",
    # One entity per (investigation, type, platform, identifier): the
    # de-duplication rule the crawler relies on, enforced by the database.
    "CREATE CONSTRAINT entity_identity IF NOT EXISTS "
    "FOR (n:Entity) REQUIRE (n.investigation_id, n.type, n.platform, n.identifier) "
    "IS UNIQUE",
)

INDEXES: tuple[str, ...] = (
    "CREATE INDEX entity_investigation IF NOT EXISTS "
    "FOR (n:Entity) ON (n.investigation_id)",
    "CREATE INDEX entity_username IF NOT EXISTS "
    "FOR (n:Entity) ON (n.identifier)",
    "CREATE INDEX entity_normalized IF NOT EXISTS "
    "FOR (n:Entity) ON (n.normalized_identifier)",
    "CREATE INDEX website_domain IF NOT EXISTS FOR (n:Website) ON (n.identifier)",
    "CREATE INDEX email_value IF NOT EXISTS FOR (n:Email) ON (n.identifier)",
    "CREATE INDEX evidence_investigation IF NOT EXISTS "
    "FOR (n:Evidence) ON (n.investigation_id)",
    "CREATE INDEX evidence_relationship IF NOT EXISTS "
    "FOR (n:Evidence) ON (n.relationship_id)",
    "CREATE INDEX snapshot_entity IF NOT EXISTS FOR (n:Snapshot) ON (n.entity_id)",
    "CREATE INDEX crawl_event_investigation IF NOT EXISTS "
    "FOR (n:CrawlEvent) ON (n.investigation_id, n.sequence)",
    "CREATE INDEX investigation_created IF NOT EXISTS "
    "FOR (n:Investigation) ON (n.created_at)",
)


def get_driver() -> Driver:
    """Return the process-wide driver, creating it on first use."""
    global _driver
    if _driver is None:
        settings = get_settings()
        _driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
            max_connection_pool_size=settings.neo4j_max_connection_pool_size,
            connection_acquisition_timeout=settings.request_timeout * 3,
        )
        logger.info("neo4j_driver_created uri=%s", settings.neo4j_uri)
    return _driver


def close_driver() -> None:
    """Close the driver on shutdown."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
        logger.info("neo4j_driver_closed")


def wait_for_neo4j(timeout: float | None = None) -> bool:
    """Block until Neo4j answers, or the timeout expires.

    Returns ``True`` once connected.  A container start-up race is the common
    case here, so this retries rather than failing on the first refusal.
    """
    settings = get_settings()
    deadline = time.monotonic() + (
        settings.neo4j_startup_timeout if timeout is None else timeout
    )
    delay = 0.5
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            get_driver().verify_connectivity()
            return True
        except (ServiceUnavailable, Neo4jError, OSError) as exc:
            last_error = exc
            # Drop the half-built driver so the next attempt reconnects cleanly.
            close_driver()
            time.sleep(delay)
            delay = min(delay * 2, 4.0)
    logger.error("neo4j_unavailable error=%s", last_error)
    return False


def init_db() -> None:
    """Verify connectivity and apply constraints and indexes.

    Every statement is ``IF NOT EXISTS``, so this is safe to run on each boot.
    """
    settings = get_settings()
    if not wait_for_neo4j():
        raise DatabaseUnavailableError(
            f"Neo4j is not reachable at {settings.neo4j_uri}. "
            "Start it (docker compose up neo4j) and check NEO4J_* settings."
        )

    driver = get_driver()
    with driver.session(database=settings.neo4j_database) as session:
        for statement in CONSTRAINTS + INDEXES:
            session.run(statement)
    logger.info(
        "database_ready uri=%s database=%s constraints=%d indexes=%d",
        settings.neo4j_uri,
        settings.neo4j_database,
        len(CONSTRAINTS),
        len(INDEXES),
    )


def check_connection() -> tuple[bool, str | None]:
    """Health-probe helper: ``(connected, error message)``."""
    try:
        get_driver().verify_connectivity()
    except Exception as exc:  # noqa: BLE001 - reported, never raised onward
        return False, type(exc).__name__
    return True, None


def get_repository() -> Iterator[Neo4jRepository]:
    """FastAPI dependency yielding a request-scoped repository."""
    settings = get_settings()
    try:
        driver = get_driver()
    except Exception as exc:  # noqa: BLE001
        raise DatabaseUnavailableError(str(exc)) from exc
    with driver.session(database=settings.neo4j_database) as session:
        yield Neo4jRepository(session)


@contextmanager
def repository_scope() -> Iterator[Neo4jRepository]:
    """Context manager yielding a repository on its own session.

    Used by background tasks and scripts, which have no request to hang a
    dependency off.
    """
    settings = get_settings()
    driver = get_driver()
    with driver.session(database=settings.neo4j_database) as session:
        yield Neo4jRepository(session)
