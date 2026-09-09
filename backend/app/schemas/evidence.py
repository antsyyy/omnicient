"""API schemas for evidence items."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

from ..models.enums import EvidenceStance, EvidenceType


class EvidenceRead(BaseModel):
    """One observation supporting or contradicting a relationship.

    This is the provenance record: *what* was observed (``type``,
    ``extracted_value``), *where* (``source_url``, ``source_entity_id``),
    *when* (``collected_at``), *which entities it connects* (source/target)
    and *what it did to the score* (``weight``, ``stance``).
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    investigation_id: str
    relationship_id: str | None = None
    source_entity_id: str
    target_entity_id: str | None = None

    type: EvidenceType
    description: str
    source_url: str | None = None
    extracted_value: str | None = None
    normalized_value: str | None = None
    weight: float = 0.0
    supports: bool = True
    context: dict[str, Any] | None = None
    collected_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def stance(self) -> EvidenceStance:
        """``SUPPORTING`` / ``CONTRADICTORY`` / ``NEUTRAL``."""
        if not self.supports:
            return EvidenceStance.CONTRADICTORY
        return (
            EvidenceStance.NEUTRAL if self.weight == 0 else EvidenceStance.SUPPORTING
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def score_impact(self) -> str:
        """Analyst-facing effect, e.g. ``+20`` or ``-15``."""
        if self.weight == 0:
            return "0"
        return f"{self.weight:+.0f}"


class EvidenceBundle(BaseModel):
    """Evidence for one relationship, split into support and contradiction."""

    relationship_id: str
    supporting: list[EvidenceRead] = Field(default_factory=list)
    contradicting: list[EvidenceRead] = Field(default_factory=list)
    neutral: list[EvidenceRead] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> int:
        return len(self.supporting) + len(self.contradicting) + len(self.neutral)
