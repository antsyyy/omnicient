"""Shared helpers for the domain records.

Omnicient stores everything in Neo4j, so these classes are plain dataclasses
rather than ORM rows: they are the in-memory shape of a node, produced by
:mod:`app.repository` from a Cypher result and consumed by the services and
the Pydantic schemas (which read them via ``from_attributes``).

Keeping the records free of any database machinery is what lets the
correlation engine, the crawler and the graph builder be unit tested with no
database at all.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any


def utcnow() -> datetime:
    """Timezone-aware current time, used for every timestamp."""
    return datetime.now(UTC)


def new_id() -> str:
    """Opaque identifier.  UUIDs keep exported graphs stable across databases."""
    return uuid.uuid4().hex


def as_datetime(value: Any) -> datetime | None:
    """Coerce a Neo4j temporal value into an aware :class:`datetime`.

    The driver returns ``neo4j.time.DateTime`` for temporal properties; the
    rest of the application only ever wants stdlib datetimes.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    to_native = getattr(value, "to_native", None)
    if callable(to_native):
        native = to_native()
        return native if native.tzinfo else native.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None
