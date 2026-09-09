"""API schemas for the relationship path explorer."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, computed_field

from ..models.enums import AnalystStatus, ConfidenceLevel, RelationshipType
from .entity import EntitySummary


class PathStep(BaseModel):
    """One hop: the relationship traversed and the entity it reached."""

    model_config = ConfigDict(from_attributes=True)

    relationship_id: str
    relationship_type: RelationshipType
    relationship_label: str
    confidence_score: float
    confidence_level: ConfidenceLevel
    analyst_status: AnalystStatus
    evidence_count: int = 0
    #: True when the stored edge points the other way; the path still traverses
    #: it, and saying so keeps the direction honest.
    reversed: bool = False
    entity: EntitySummary


class RelationshipPath(BaseModel):
    """One route between two entities, and how much it is worth."""

    #: Position after ranking, 1 being the strongest.
    rank: int
    length: int
    start: EntitySummary
    steps: list[PathStep] = Field(default_factory=list)

    #: Deterministic ranking score. Not a probability, and not a correlation
    #: score - it orders routes, nothing more.
    strength_score: float = 0.0
    strength: str = "WEAK"
    total_evidence: int = 0
    contradictions: int = 0
    confirmed_steps: int = 0
    rejected_steps: int = 0

    #: Ids for the interface to highlight in the graph.
    node_ids: list[str] = Field(default_factory=list)
    relationship_ids: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_contradictions(self) -> bool:
        return self.contradictions > 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def relationship_types(self) -> list[str]:
        return [str(step.relationship_type) for step in self.steps]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def summary(self) -> str:
        """``Instagram @alice_98 → alice.dev → GitHub @alice-security``."""
        parts = [self.start.name]
        parts.extend(step.entity.name for step in self.steps)
        return " → ".join(parts)


class PathResponse(BaseModel):
    """Ranked routes between two entities in one investigation."""

    investigation_id: str
    source_entity_id: str
    target_entity_id: str
    source_entity: EntitySummary | None = None
    target_entity: EntitySummary | None = None
    max_depth: int
    max_paths: int
    paths: list[RelationshipPath] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def found(self) -> int:
        return len(self.paths)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def message(self) -> str:
        if self.paths:
            return f"{len(self.paths)} route(s) found within {self.max_depth} hops."
        return (
            "No route found within "
            f"{self.max_depth} hops. These entities are not connected by the "
            "evidence discovered so far."
        )
