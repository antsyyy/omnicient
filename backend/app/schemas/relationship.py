"""API schemas for relationships and analyst decisions."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from ..models.enums import (
    RELATIONSHIP_LABELS,
    AnalystStatus,
    ConfidenceLevel,
    RelationshipType,
)
from .entity import EntitySummary
from .evidence import EvidenceRead


class RelationshipRead(BaseModel):
    """A scored, evidence-backed association between two entities."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    investigation_id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: RelationshipType
    confidence_score: float
    confidence_level: ConfidenceLevel
    analyst_status: AnalystStatus
    analyst_note: str | None = None
    #: When the analyst last recorded a verdict (section 25).
    reviewed_at: datetime | None = None
    summary: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def relationship_label(self) -> str:
        """Analyst-facing wording, e.g. ``Potential Same Identity``."""
        return RELATIONSHIP_LABELS.get(self.relationship_type, self.relationship_type)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def evidence_count(self) -> int:
        return len(self.evidence_ids)


class RelationshipDetail(RelationshipRead):
    """A relationship with both endpoints and every evidence item resolved."""

    source_entity: EntitySummary | None = None
    target_entity: EntitySummary | None = None
    evidence: list[EvidenceRead] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def contradiction_count(self) -> int:
        return len([item for item in self.evidence if not item.supports])


class AnalystDecision(BaseModel):
    """Body of a confirm/reject request.

    Confirming records that the analyst agrees the evidence supports the
    relationship.  It does not assert real-world identity certainty.
    """

    note: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional analyst rationale stored with the decision.",
    )
