"""API schemas for evidence items."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..models.enums import EvidenceType


class EvidenceRead(BaseModel):
    """One observation supporting or contradicting a relationship.

    ``supports`` distinguishes corroborating evidence from contradictions;
    ``weight`` is the number of points the item contributed to the score, and
    is negative for contradictions.
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
    weight: float = 0.0
    supports: bool = True
    context: dict[str, Any] | None = None
    collected_at: datetime


class EvidenceBundle(BaseModel):
    """Evidence for one relationship, split into support and contradiction."""

    relationship_id: str
    supporting: list[EvidenceRead] = Field(default_factory=list)
    contradicting: list[EvidenceRead] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.supporting) + len(self.contradicting)
