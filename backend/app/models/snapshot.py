"""Snapshot record: what an entity looked like when it was observed.

A snapshot is written every time an entity is discovered or re-observed, and
attached to it in Neo4j as ``(:Entity)-[:HAS_SNAPSHOT]->(:Snapshot)``.  The MVP
only stores them; keeping the history from day one is what makes temporal
analysis ("what changed since the first observation?") possible later without
a migration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .base import as_datetime, new_id, utcnow
from .entity import _json_field


@dataclass
class Snapshot:
    """A point-in-time copy of an entity's public fields."""

    entity_id: str
    id: str = field(default_factory=new_id)
    timestamp: datetime = field(default_factory=utcnow)

    username: str | None = None
    display_name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    external_links: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_node(cls, node: Any) -> "Snapshot":
        """Build a record from a Neo4j node."""
        data = dict(node)
        return cls(
            id=data["id"],
            entity_id=data["entity_id"],
            timestamp=as_datetime(data.get("timestamp")) or utcnow(),
            username=data.get("username"),
            display_name=data.get("display_name"),
            bio=data.get("bio"),
            avatar_url=data.get("avatar_url"),
            external_links=list(data.get("external_links") or []),
            meta=_json_field(data.get("meta")),
        )
