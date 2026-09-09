"""API schemas for the Identity Intelligence Profile.

A profile is a *reading* of the investigation graph, never a second source of
truth: it is computed on request from the entities, relationships and evidence
already stored, so it cannot drift from what the graph says.

Every aggregated item carries the entities it came from, so a value shown in
the profile can always be traced back to the node that published it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from ..models.enums import EntityType
from .alias import AliasRead


class ObservedValue(BaseModel):
    """One publicly observed attribute, with where it was seen.

    ``entity_ids`` is what makes the profile navigable: clicking a website in
    the interface selects the accounts that published it.
    """

    model_config = ConfigDict(from_attributes=True)

    value: str
    #: Display form when it differs from the comparison value.
    label: str | None = None
    entity_ids: list[str] = Field(default_factory=list)
    #: Where it was seen, for the analyst's benefit.
    platforms: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def observation_count(self) -> int:
        """How many discovered entities published this value."""
        return len(self.entity_ids)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def corroborated(self) -> bool:
        """True when more than one entity published it independently."""
        return len(self.entity_ids) > 1


class PrimaryIdentifier(BaseModel):
    """The seed the investigation started from."""

    value: str
    type: str
    platform: str | None = None
    entity_id: str | None = None


class ObservedPlatform(BaseModel):
    """A platform where something was found."""

    platform: str
    platform_name: str
    entity_ids: list[str] = Field(default_factory=list)
    #: Accounts that actually returned public data, as opposed to candidates
    #: recorded but never resolved.
    resolved: int = 0
    total: int = 0


class ProfileStatistics(BaseModel):
    """Headline counts for the investigation."""

    entities: int = 0
    accounts: int = 0
    websites: int = 0
    relationships: int = 0
    potential_relationships: int = 0
    high_confidence: int = 0
    medium_confidence: int = 0
    low_confidence: int = 0
    contradictions: int = 0
    evidence: int = 0
    confirmed: int = 0
    rejected: int = 0
    unreviewed: int = 0
    by_entity_type: dict[str, int] = Field(default_factory=dict)


class EvidenceSummary(BaseModel):
    """What kinds of evidence the investigation is resting on."""

    by_type: dict[str, int] = Field(default_factory=dict)
    supporting: int = 0
    contradicting: int = 0
    neutral: int = 0
    #: Relationships with no evidence at all - should always be zero.
    unexplained_relationships: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def traceable(self) -> bool:
        """Every inferred relationship has at least one observation behind it."""
        return self.unexplained_relationships == 0


class IdentityProfile(BaseModel):
    """An evidence-backed summary of one investigation.

    Nothing here asserts an identity. The aggregated values are what was
    *publicly observed* during this investigation, and the aliases remain
    potential until an analyst reviews them.
    """

    investigation_id: str
    investigation_name: str
    demo: bool = False
    #: Standing reminder that this is an aggregation of observations.
    disclaimer: str = (
        "Aggregated from publicly observable data discovered in this "
        "investigation. Values are attributed to the entities that published "
        "them; nothing here asserts that they describe one person."
    )

    primary_identifier: PrimaryIdentifier
    potential_aliases: list[AliasRead] = Field(default_factory=list)
    platforms: list[ObservedPlatform] = Field(default_factory=list)
    websites: list[ObservedValue] = Field(default_factory=list)
    emails: list[ObservedValue] = Field(default_factory=list)
    organizations: list[ObservedValue] = Field(default_factory=list)
    locations: list[ObservedValue] = Field(default_factory=list)
    display_names: list[ObservedValue] = Field(default_factory=list)

    first_observed: datetime | None = None
    last_observed: datetime | None = None
    snapshot_count: int = 0

    statistics: ProfileStatistics = Field(default_factory=ProfileStatistics)
    evidence_summary: EvidenceSummary = Field(default_factory=EvidenceSummary)

    #: Contradictions worth an analyst's attention, surfaced rather than buried.
    contradictions: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_aliases(self) -> bool:
        return bool(self.potential_aliases)


ENTITY_TYPE_ORDER: tuple[str, ...] = (
    EntityType.ACCOUNT,
    EntityType.WEBSITE,
    EntityType.DOMAIN,
    EntityType.EMAIL,
    EntityType.USERNAME,
    EntityType.ORGANIZATION,
    EntityType.PERSON,
)
