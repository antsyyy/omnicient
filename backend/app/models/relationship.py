"""Relationship record: the scored, evidence-backed edges of the graph.

Stored in Neo4j as a native relationship between two ``:Entity`` nodes, typed
by :class:`RelationshipType` (``POTENTIAL_SAME_IDENTITY``, ``LINKS_TO``, ...)
exactly as section 7 describes, so a Cypher traversal over the investigation
reads the way the analyst reads the graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .base import as_datetime, new_id, utcnow
from .enums import (
    AnalystStatus,
    ConfidenceLevel,
    RelationshipOrigin,
    RelationshipType,
)


@dataclass
class Relationship:
    """A potential association between two entities.

    A relationship is never an assertion of identity.  ``confidence_score`` is
    the sum of its evidence weights, clamped to ``[0, 100]``, and
    ``confidence_level`` is the band that score falls into.
    """

    investigation_id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str = RelationshipType.LINKS_TO
    id: str = field(default_factory=new_id)

    confidence_score: float = 0.0
    confidence_level: str = ConfidenceLevel.LOW
    #: Who asserted this edge first - the engine, or an analyst by hand.
    origin: str = RelationshipOrigin.ENGINE
    analyst_status: str = AnalystStatus.UNREVIEWED
    analyst_note: str | None = None
    #: When the analyst last recorded a verdict (section 25).
    reviewed_at: datetime | None = None
    summary: str | None = None

    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    #: Populated on demand by the repository; not stored on the edge.
    evidence: list["Evidence"] = field(default_factory=list)  # noqa: F821
    source_entity: Any | None = None
    target_entity: Any | None = None

    @property
    def evidence_ids(self) -> list[str]:
        """Ids of the evidence items backing this relationship."""
        return [item.id for item in self.evidence]

    @property
    def is_analyst_asserted(self) -> bool:
        """Whether a person drew this link rather than the engine deriving it."""
        return str(self.origin) == RelationshipOrigin.ANALYST

    @classmethod
    def from_edge(cls, edge: Any) -> "Relationship":
        """Build a record from a Neo4j relationship."""
        data = dict(edge)
        return cls(
            id=data["id"],
            investigation_id=data["investigation_id"],
            source_entity_id=data["source_entity_id"],
            target_entity_id=data["target_entity_id"],
            relationship_type=data.get("relationship_type", edge.type),
            confidence_score=float(data.get("confidence_score", 0.0)),
            confidence_level=data.get("confidence_level", ConfidenceLevel.LOW),
            origin=data.get("origin", RelationshipOrigin.ENGINE),
            analyst_status=data.get("analyst_status", AnalystStatus.UNREVIEWED),
            analyst_note=data.get("analyst_note"),
            reviewed_at=as_datetime(data.get("reviewed_at")),
            summary=data.get("summary"),
            created_at=as_datetime(data.get("created_at")) or utcnow(),
            updated_at=as_datetime(data.get("updated_at")) or utcnow(),
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<Relationship {self.relationship_type} "
            f"score={self.confidence_score:.0f} {self.confidence_level}>"
        )
