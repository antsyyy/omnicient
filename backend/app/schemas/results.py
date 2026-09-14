"""API schemas for the per-source results list.

The graph shows how discovered entities connect. This shows what happened to
each *source* — which is a different question, and the one an analyst asks
first: "you searched twenty-three places, what came back?"

The distinction that matters here is one a graph cannot express. A source that
was searched and found nothing, and a source that refused to be searched, both
leave no node behind. On a board they are identically invisible. In a list
they are two different findings, and the second one is often the more
interesting.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field

from ..models.enums import AnalystStatus, ConfidenceLevel
from .entity import EntitySummary


class SourceOutcome(StrEnum):
    """What happened when a source was queried."""

    #: Public data was returned and an entity recorded.
    FOUND = "FOUND"
    #: Queried successfully; the handle is not there.
    NOT_FOUND = "NOT_FOUND"
    #: The platform declined - robots.txt, a login wall, a block, a rate limit.
    UNAVAILABLE = "UNAVAILABLE"
    #: Referenced by something else but never read publicly.
    REFERENCED_ONLY = "REFERENCED_ONLY"
    #: Registered as an adapter but not reached in this run.
    NOT_QUERIED = "NOT_QUERIED"


#: Analyst-facing wording for each outcome.
OUTCOME_LABEL: dict[str, str] = {
    SourceOutcome.FOUND: "Found",
    SourceOutcome.NOT_FOUND: "Nothing found",
    SourceOutcome.UNAVAILABLE: "Source unavailable",
    SourceOutcome.REFERENCED_ONLY: "Referenced, not read",
    SourceOutcome.NOT_QUERIED: "Not queried",
}


class SourceResult(BaseModel):
    """One source, and what the investigation got from it."""

    model_config = ConfigDict(from_attributes=True)

    platform: str
    platform_name: str
    category: str
    outcome: SourceOutcome

    #: The account found, when there was one.
    entity: EntitySummary | None = None
    identifier: str | None = None
    display_name: str | None = None
    url: str | None = None

    #: Strongest association tying this entity back into the investigation.
    confidence: ConfidenceLevel | None = None
    score: float | None = None
    analyst_status: AnalystStatus | None = None
    relationship_id: str | None = None
    evidence_count: int = 0
    contradiction_count: int = 0

    #: Why a source was unavailable, in the analyst's words.
    reason: str | None = None
    detail: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def outcome_label(self) -> str:
        return OUTCOME_LABEL.get(str(self.outcome), str(self.outcome))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def actionable(self) -> bool:
        """Whether there is an association here an analyst could review."""
        return self.relationship_id is not None


class SourceResults(BaseModel):
    """Every source this investigation touched, and what it yielded."""

    investigation_id: str
    seed_identifier: str
    seed_type: str
    results: list[SourceResult] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.results:
            counts[str(result.outcome)] = counts.get(str(result.outcome), 0) + 1
        return counts

    @computed_field  # type: ignore[prop-decorator]
    @property
    def found(self) -> int:
        return sum(1 for r in self.results if r.outcome is SourceOutcome.FOUND)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def queried(self) -> int:
        """Sources actually reached, however they answered."""
        return sum(
            1 for r in self.results if r.outcome is not SourceOutcome.NOT_QUERIED
        )
