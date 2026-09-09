"""Evidence record: why a relationship exists and what it is worth.

Evidence is first class in Omnicient.  Every point of every score traces back
to one of these, with the URL the observation came from, so an analyst can
reconstruct a score by reading its evidence list.

Storage note: Neo4j relationships cannot themselves be the endpoint of another
relationship, so the ``SUPPORTED_BY`` edge sketched in section 9 is realised as
an ``(:Evidence)`` node that carries the ``relationship_id`` of the scored edge
and is attached to the investigation and to both entities it concerns.  The
scored association stays a native Neo4j relationship, which is what section 7
asks for and what makes the graph traversable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .base import as_datetime, new_id, utcnow
from .entity import _json_field
from .enums import EvidenceStance, evidence_stance


@dataclass
class Evidence:
    """One observation supporting or contradicting a relationship."""

    investigation_id: str
    source_entity_id: str
    type: str
    description: str
    id: str = field(default_factory=new_id)

    relationship_id: str | None = None
    target_entity_id: str | None = None

    source_url: str | None = None
    #: The value exactly as it was published.
    extracted_value: str | None = None
    #: The comparison form the engine actually matched on.  Kept alongside the
    #: raw value so an analyst can see *why* two differently-written values
    #: were treated as the same observation.
    normalized_value: str | None = None
    weight: float = 0.0
    supports: bool = True
    context: dict[str, Any] | None = None

    collected_at: datetime = field(default_factory=utcnow)

    @classmethod
    def from_node(cls, node: Any) -> "Evidence":
        """Build a record from a Neo4j node."""
        data = dict(node)
        raw_context = data.get("context")
        return cls(
            id=data["id"],
            investigation_id=data["investigation_id"],
            relationship_id=data.get("relationship_id"),
            source_entity_id=data["source_entity_id"],
            target_entity_id=data.get("target_entity_id"),
            type=data.get("type", ""),
            description=data.get("description", ""),
            source_url=data.get("source_url"),
            extracted_value=data.get("extracted_value"),
            normalized_value=data.get("normalized_value"),
            weight=float(data.get("weight", 0.0)),
            supports=bool(data.get("supports", True)),
            context=_json_field(raw_context) if raw_context else None,
            collected_at=as_datetime(data.get("collected_at")) or utcnow(),
        )

    @property
    def stance(self) -> EvidenceStance:
        """Whether this observation argues for, against, or neither."""
        return evidence_stance(self.weight, self.supports)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Evidence {self.type} weight={self.weight:+.0f}>"
