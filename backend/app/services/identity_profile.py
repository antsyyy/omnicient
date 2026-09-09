"""Identity Intelligence Profile: a reading of the investigation graph.

The graph is the source of truth and stays that way. This service computes a
profile from it on request rather than storing a second copy, so the summary
can never drift from the evidence underneath it.

Two rules govern the aggregation, and they are what keep this from becoming a
identity claim:

1. **Attribution, not assertion.** Every value carries the entities that
   published it. "alice.dev" is not "the subject's website" - it is a value two
   named accounts both published, and the interface can navigate to them.
2. **Rejected means rejected.** An entity reachable only through relationships
   an analyst rejected does not contribute its attributes. Aggregating them
   anyway would let a discarded false positive quietly shape the summary.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..models.entity import Entity
from ..models.enums import (
    AnalystStatus,
    ConfidenceLevel,
    EntityType,
    RelationshipType,
)
from ..models.evidence import Evidence
from ..models.investigation import Investigation
from ..models.relationship import Relationship
from ..repository import Neo4jRepository
from ..schemas.profile import (
    EvidenceSummary,
    IdentityProfile,
    ObservedPlatform,
    ObservedValue,
    PrimaryIdentifier,
    ProfileStatistics,
)
from ..utils.logging import get_logger
from ..utils.normalization import (
    is_identifying_host,
    normalize_domain,
    platform_label,
)
from ..utils.url_parser import detect_platform
from .alias_service import AliasService

logger = get_logger(__name__)

#: Relationship types that represent an inferred association rather than a
#: directly observed link.  Only these are counted as "potential relationships".
INFERRED_TYPES = frozenset(
    {
        str(RelationshipType.POTENTIAL_SAME_IDENTITY),
        str(RelationshipType.POTENTIAL_ALIAS),
        str(RelationshipType.CONTRADICTORY),
    }
)


@dataclass
class _Bucket:
    """Accumulates one observed value and where it was seen."""

    value: str
    label: str | None = None
    entity_ids: set[str] = field(default_factory=set)
    platforms: set[str] = field(default_factory=set)
    source_urls: set[str] = field(default_factory=set)

    def observe(self, entity: Entity, url: str | None = None) -> None:
        self.entity_ids.add(entity.id)
        self.platforms.add(entity.platform)
        if url:
            self.source_urls.add(url)

    def to_schema(self) -> ObservedValue:
        return ObservedValue(
            value=self.value,
            label=self.label,
            entity_ids=sorted(self.entity_ids),
            platforms=sorted(self.platforms),
            source_urls=sorted(self.source_urls)[:5],
        )


class IdentityProfileService:
    """Builds the Identity Intelligence Profile for one investigation."""

    def __init__(self, repo: Neo4jRepository) -> None:
        self.repo = repo

    def build(self, investigation: Investigation) -> IdentityProfile:
        """Aggregate the investigation into an evidence-backed summary."""
        entities = self.repo.list_entities(investigation.id)
        relationships = self.repo.list_relationships(investigation.id)
        evidence = self.repo.list_evidence(investigation.id)

        excluded = self._rejected_entity_ids(entities, relationships)
        contributing = [entity for entity in entities if entity.id not in excluded]

        seed = self.repo.seed_entity(investigation.id)
        profile = IdentityProfile(
            investigation_id=investigation.id,
            investigation_name=investigation.name,
            demo=investigation.demo,
            primary_identifier=PrimaryIdentifier(
                value=investigation.seed_identifier,
                type=investigation.seed_type or str(EntityType.USERNAME),
                platform=investigation.seed_platform,
                entity_id=seed.id if seed else None,
            ),
            potential_aliases=AliasService(self.repo)
            .list_aliases(investigation)
            .aliases,
            platforms=self._platforms(contributing),
            websites=self._websites(contributing),
            emails=self._emails(contributing),
            organizations=self._organizations(contributing),
            locations=self._locations(contributing),
            display_names=self._display_names(contributing),
            statistics=self._statistics(entities, relationships, evidence),
            evidence_summary=self._evidence_summary(relationships, evidence),
            contradictions=self._contradictions(relationships, evidence, entities),
        )
        self._apply_timeline(profile, contributing)

        logger.info(
            "profile_built investigation=%s entities=%d aliases=%d excluded=%d",
            investigation.id,
            len(contributing),
            len(profile.potential_aliases),
            len(excluded),
        )
        return profile

    # -- exclusion ---------------------------------------------------------

    @staticmethod
    def _rejected_entity_ids(
        entities: list[Entity], relationships: list[Relationship]
    ) -> set[str]:
        """Entities whose only tie to the investigation was rejected.

        An analyst rejecting a relationship is a statement that the entity does
        not belong here. Its attributes must stop contributing, or a discarded
        false positive keeps shaping the profile from behind the scenes. An
        entity that is *also* reachable some other way is kept.
        """
        rejected_partners: set[str] = set()
        surviving: set[str] = set()
        for relationship in relationships:
            pair = (relationship.source_entity_id, relationship.target_entity_id)
            if relationship.analyst_status == AnalystStatus.REJECTED:
                rejected_partners.update(pair)
            else:
                surviving.update(pair)

        seeds = {entity.id for entity in entities if entity.is_seed}
        return {
            entity_id
            for entity_id in rejected_partners
            if entity_id not in surviving and entity_id not in seeds
        }

    # -- aggregation -------------------------------------------------------

    @staticmethod
    def _platforms(entities: list[Entity]) -> list[ObservedPlatform]:
        grouped: dict[str, list[Entity]] = defaultdict(list)
        for entity in entities:
            if entity.type == str(EntityType.ACCOUNT):
                grouped[entity.platform].append(entity)
        return [
            ObservedPlatform(
                platform=platform,
                platform_name=platform_label(platform),
                entity_ids=sorted(entity.id for entity in members),
                resolved=sum(1 for entity in members if entity.resolved),
                total=len(members),
            )
            for platform, members in sorted(
                grouped.items(), key=lambda item: (-len(item[1]), item[0])
            )
        ]

    @staticmethod
    def _collect(
        entities: list[Entity],
        values: callable,  # type: ignore[valid-type]
    ) -> list[ObservedValue]:
        """Group a per-entity value extractor into corroborated buckets."""
        buckets: dict[str, _Bucket] = {}
        for entity in entities:
            for key, label in values(entity):
                if not key:
                    continue
                bucket = buckets.setdefault(key, _Bucket(value=key, label=label))
                bucket.observe(entity, entity.url)
        # Corroborated values first: a value two accounts published matters
        # more than one seen once.
        return [
            bucket.to_schema()
            for bucket in sorted(
                buckets.values(), key=lambda b: (-len(b.entity_ids), b.value)
            )
        ]

    def _websites(self, entities: list[Entity]) -> list[ObservedValue]:
        """Sites the subject published - not the platforms they published on.

        A profile that links to github.com is an *account*, already shown under
        platforms; listing the host again as a "public website" is noise. Link
        shorteners and mailbox providers are excluded for the same reason they
        earn no correlation score: everybody links to them.
        """

        def personal(url: str | None) -> str | None:
            domain = normalize_domain(url)
            if not domain:
                return None
            if detect_platform(url) is not None:
                return None
            if not is_identifying_host(domain):
                return None
            return domain

        def values(entity: Entity):
            if entity.type in (
                str(EntityType.WEBSITE),
                str(EntityType.DOMAIN),
            ) and is_identifying_host(entity.identifier):
                yield entity.identifier, entity.name
            for url in entity.external_links or []:
                domain = personal(url)
                if domain:
                    yield domain, url
            for url in (entity.meta or {}).get("websites", []) or []:
                domain = personal(url)
                if domain:
                    yield domain, url

        return self._collect(entities, values)

    def _emails(self, entities: list[Entity]) -> list[ObservedValue]:
        def values(entity: Entity):
            if entity.type == str(EntityType.EMAIL):
                yield entity.identifier.lower(), entity.identifier
            if entity.email:
                yield entity.email.lower(), entity.email
            for address in (entity.meta or {}).get("emails", []) or []:
                if address:
                    yield str(address).lower(), str(address)

        return self._collect(entities, values)

    def _organizations(self, entities: list[Entity]) -> list[ObservedValue]:
        def values(entity: Entity):
            if entity.type == str(EntityType.ORGANIZATION):
                yield entity.identifier.lower(), entity.name
            if entity.organization:
                yield entity.organization.lower(), entity.organization
            for name in (entity.meta or {}).get("organizations", []) or []:
                if name:
                    yield str(name).lower(), str(name)

        return self._collect(entities, values)

    def _locations(self, entities: list[Entity]) -> list[ObservedValue]:
        """Only locations a source actually published.  Never inferred."""

        def values(entity: Entity):
            if entity.location:
                yield entity.location.strip().lower(), entity.location.strip()

        return self._collect(entities, values)

    def _display_names(self, entities: list[Entity]) -> list[ObservedValue]:
        def values(entity: Entity):
            if entity.display_name:
                yield entity.display_name.strip().lower(), entity.display_name.strip()

        return self._collect(entities, values)

    # -- timeline ----------------------------------------------------------

    def _apply_timeline(
        self, profile: IdentityProfile, entities: list[Entity]
    ) -> None:
        """First and last observation, from the stored snapshots."""
        first = last = None
        count = 0
        for entity in entities:
            for snapshot in self.repo.snapshots_for_entity(entity.id):
                count += 1
                if first is None or snapshot.timestamp < first:
                    first = snapshot.timestamp
                if last is None or snapshot.timestamp > last:
                    last = snapshot.timestamp
        if first is None:
            # No snapshots: fall back to when the entities themselves were seen.
            observed = [entity.first_seen for entity in entities if entity.first_seen]
            first = min(observed, default=None)
            last = max(
                (entity.last_seen for entity in entities if entity.last_seen),
                default=None,
            )
        profile.first_observed = first
        profile.last_observed = last
        profile.snapshot_count = count

    # -- statistics --------------------------------------------------------

    @staticmethod
    def _statistics(
        entities: list[Entity],
        relationships: list[Relationship],
        evidence: list[Evidence],
    ) -> ProfileStatistics:
        by_type: dict[str, int] = defaultdict(int)
        for entity in entities:
            by_type[str(entity.type)] += 1

        stats = ProfileStatistics(
            entities=len(entities),
            accounts=by_type.get(str(EntityType.ACCOUNT), 0),
            websites=by_type.get(str(EntityType.WEBSITE), 0)
            + by_type.get(str(EntityType.DOMAIN), 0),
            relationships=len(relationships),
            evidence=len(evidence),
            by_entity_type=dict(sorted(by_type.items())),
        )
        for relationship in relationships:
            if str(relationship.relationship_type) in INFERRED_TYPES:
                stats.potential_relationships += 1
            level = str(relationship.confidence_level)
            if level in (ConfidenceLevel.HIGH, ConfidenceLevel.VERY_HIGH):
                stats.high_confidence += 1
            elif level == ConfidenceLevel.MEDIUM:
                stats.medium_confidence += 1
            else:
                stats.low_confidence += 1

            status = str(relationship.analyst_status)
            if status == AnalystStatus.CONFIRMED:
                stats.confirmed += 1
            elif status == AnalystStatus.REJECTED:
                stats.rejected += 1
            else:
                stats.unreviewed += 1

        stats.contradictions = sum(1 for item in evidence if not item.supports)
        return stats

    @staticmethod
    def _evidence_summary(
        relationships: list[Relationship], evidence: list[Evidence]
    ) -> EvidenceSummary:
        by_type: dict[str, int] = defaultdict(int)
        supporting = contradicting = neutral = 0
        explained: set[str] = set()
        for item in evidence:
            by_type[str(item.type)] += 1
            if item.relationship_id:
                explained.add(item.relationship_id)
            if not item.supports:
                contradicting += 1
            elif item.weight == 0:
                neutral += 1
            else:
                supporting += 1

        return EvidenceSummary(
            by_type=dict(sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))),
            supporting=supporting,
            contradicting=contradicting,
            neutral=neutral,
            unexplained_relationships=sum(
                1 for r in relationships if r.id not in explained
            ),
        )

    @staticmethod
    def _contradictions(
        relationships: list[Relationship],
        evidence: list[Evidence],
        entities: list[Entity],
    ) -> list[str]:
        """Plain-language contradictions, surfaced rather than buried."""
        names = {entity.id: entity for entity in entities}
        lines: list[str] = []
        for item in evidence:
            if item.supports:
                continue
            source = names.get(item.source_entity_id)
            target = names.get(item.target_entity_id or "")
            if source and target:
                lines.append(
                    f"{source.label} vs {target.label}: {item.description}"
                )
            else:
                lines.append(item.description)
        return lines[:20]
