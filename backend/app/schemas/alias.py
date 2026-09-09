"""API schemas for potential aliases.

Everything here is a claim about *handles*, never about people.  The wording is
deliberate: ``POTENTIAL_ALIAS``, ``potential_aliases``, ``strength`` - nothing
in this module asserts that two accounts belong to one person.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, computed_field

from ..models.enums import AnalystStatus, ConfidenceLevel
from .entity import EntitySummary
from .evidence import EvidenceRead


class AliasSignalRead(BaseModel):
    """One reason a handle pair was proposed."""

    model_config = ConfigDict(from_attributes=True)

    kind: str
    label: str
    detail: str
    weight: float = 0.0


class AliasRead(BaseModel):
    """A potential alias pair and the reasoning behind it."""

    model_config = ConfigDict(from_attributes=True)

    #: The relationship id when this alias is stored on the graph.
    relationship_id: str | None = None
    source_entity_id: str | None = None
    target_entity_id: str | None = None
    source_entity: EntitySummary | None = None
    target_entity: EntitySummary | None = None

    source_identifier: str
    target_identifier: str
    source_platform: str | None = None
    target_platform: str | None = None

    #: Handle resemblance alone, before contextual evidence.
    similarity: float
    strength: str
    transformations: list[str] = Field(default_factory=list)
    signals: list[AliasSignalRead] = Field(default_factory=list)

    #: Resemblance plus corroboration, minus contradictions.
    score: float = 0.0
    confidence: ConfidenceLevel = ConfidenceLevel.LOW
    analyst_status: AnalystStatus = AnalystStatus.UNREVIEWED
    supporting_evidence: list[EvidenceRead] = Field(default_factory=list)
    contradicting_evidence: list[EvidenceRead] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def label(self) -> str:
        """Always "Potential Alias" - the vocabulary is not negotiable."""
        return "Potential Alias"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def contradiction_count(self) -> int:
        return len(self.contradicting_evidence)


class AliasList(BaseModel):
    """Potential aliases discovered in one investigation."""

    investigation_id: str
    #: The seed handle every alias is measured against, where there is one.
    primary_identifier: str | None = None
    aliases: list[AliasRead] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> int:
        return len(self.aliases)
