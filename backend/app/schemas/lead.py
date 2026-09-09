"""API schemas for investigation leads."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field

from .entity import EntitySummary


class LeadPriority(StrEnum):
    """How much an analyst's attention a lead is worth."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class LeadType(StrEnum):
    """The deterministic rule that produced a lead."""

    SHARED_WEBSITE_CLUSTER = "SHARED_WEBSITE_CLUSTER"
    REPEATED_EMAIL = "REPEATED_EMAIL"
    SHARED_AVATAR = "SHARED_AVATAR"
    POTENTIAL_ALIAS = "POTENTIAL_ALIAS"
    UNREVIEWED_STRONG_ASSOCIATION = "UNREVIEWED_STRONG_ASSOCIATION"
    CONTRADICTION_REVIEW = "CONTRADICTION_REVIEW"
    BRIDGE_ENTITY = "BRIDGE_ENTITY"
    UNRESOLVED_ENTITY = "UNRESOLVED_ENTITY"
    SHARED_ORGANIZATION = "SHARED_ORGANIZATION"


class Lead(BaseModel):
    """A suggested next step, derived from evidence already collected.

    A lead is never an investigative conclusion. It points at something in the
    graph that an analyst may want to look at, and says which observations
    prompted it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    type: LeadType
    priority: LeadPriority
    title: str
    description: str
    suggested_action: str

    related_entity_ids: list[str] = Field(default_factory=list)
    related_entities: list[EntitySummary] = Field(default_factory=list)
    related_relationship_ids: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)

    #: Deterministic ranking score behind the priority band.
    score: float = 0.0
    #: The observation the rule fired on, e.g. the shared domain.
    pivot_value: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def label(self) -> str:
        """Always framed as a suggestion, never as a finding."""
        return (
            "Review required"
            if self.type is LeadType.CONTRADICTION_REVIEW
            else "Suggested investigation lead"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def entity_count(self) -> int:
        return len(self.related_entity_ids)


class LeadList(BaseModel):
    """Leads for one investigation, highest priority first."""

    investigation_id: str
    leads: list[Lead] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> int:
        return len(self.leads)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def by_priority(self) -> dict[str, int]:
        counts: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for lead in self.leads:
            counts[str(lead.priority)] = counts.get(str(lead.priority), 0) + 1
        return counts
