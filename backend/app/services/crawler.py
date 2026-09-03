"""Controlled breadth-first crawler.

The crawler walks outward from the seed identifier, one level at a time, and
only ever follows URLs it discovered during this investigation.  It is bounded
in every direction that matters: crawl depth, page count, per-request timeout,
response size, and a polite delay between requests (all configurable, see
:class:`app.config.Settings`).

It produces observations, never conclusions.  Entities and the explicit links
between them are recorded here; deciding whether two accounts might belong to
the same person is the correlation engine's job.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings, get_settings
from ..models.enums import DiscoveryMethod, EntityType, EvidenceType, RelationshipType
from ..sources import SourceRegistry
from ..sources.base import FailureReason, ObservedProfile
from ..utils.logging import get_logger, log_event
from .discovery import (
    Candidate,
    EntityKey,
    candidates_from_profile,
    email_domain_candidate,
    seed_candidate,
    similarity_candidates,
)

logger = get_logger(__name__)


@dataclass
class ObservedEntity:
    """An entity the crawler observed, with its provenance."""

    key: EntityKey
    entity_type: EntityType
    platform: str
    identifier: str
    name: str
    url: str | None = None
    profile: ObservedProfile | None = None
    method: DiscoveryMethod = DiscoveryMethod.DIRECT
    depth: int = 0
    discovered_via: str | None = None
    resolved: bool = False
    is_seed: bool = False

    @property
    def label(self) -> str:
        return f"{self.platform}:{self.identifier}"


@dataclass
class ObservedLink:
    """An explicit, directly observed link between two entities."""

    source_key: EntityKey
    target_key: EntityKey
    relationship_type: RelationshipType
    evidence_type: EvidenceType
    description: str
    weight: float
    source_url: str | None = None
    extracted_value: str | None = None


@dataclass
class CrawlEventRecord:
    """One line of the investigation timeline."""

    event: str
    message: str
    level: str = "INFO"
    data: dict[str, Any] | None = None


@dataclass
class SourceIssueRecord:
    """A source that could not be queried, kept for the analyst to see."""

    platform: str
    identifier: str | None
    reason: str
    detail: str
    url: str | None = None


@dataclass
class CrawlOutcome:
    """Everything one crawl produced."""

    entities: dict[EntityKey, ObservedEntity] = field(default_factory=dict)
    links: list[ObservedLink] = field(default_factory=list)
    issues: list[SourceIssueRecord] = field(default_factory=list)
    events: list[CrawlEventRecord] = field(default_factory=list)
    pages_fetched: int = 0
    seed_key: EntityKey | None = None

    @property
    def profiles(self) -> list[ObservedProfile]:
        return [
            entity.profile for entity in self.entities.values() if entity.profile
        ]


class Crawler:
    """Breadth-first, budget-limited public-source crawler."""

    def __init__(
        self,
        registry: SourceRegistry,
        settings: Settings | None = None,
    ) -> None:
        self.registry = registry
        self.settings = settings or get_settings()

    async def crawl(
        self,
        platform: str,
        identifier: str,
        *,
        max_depth: int | None = None,
        max_pages: int | None = None,
        include_similarity: bool = True,
    ) -> CrawlOutcome:
        """Walk outward from a seed identifier and return what was observed."""
        max_depth = self.settings.max_depth if max_depth is None else max_depth
        max_pages = self.settings.max_pages if max_pages is None else max_pages

        outcome = CrawlOutcome()
        seed = seed_candidate(platform, identifier)
        outcome.seed_key = seed.key
        self._record(
            outcome,
            "investigation_started",
            f"Investigation started for {seed.label}",
            seed=seed.label, max_depth=max_depth, max_pages=max_pages,
        )

        queue: deque[Candidate] = deque([seed])
        queued: set[EntityKey] = {seed.key}

        while queue:
            candidate = queue.popleft()

            if outcome.pages_fetched >= max_pages:
                self._record(
                    outcome,
                    "budget_exhausted",
                    f"Page budget of {max_pages} reached; stopping discovery",
                    level="WARNING",
                    pages=outcome.pages_fetched,
                )
                break

            entity, profile = await self._visit(candidate, outcome)
            if entity is None:
                continue

            if profile is None or candidate.depth >= max_depth:
                continue

            derived = candidates_from_profile(
                profile,
                parent_key=entity.key,
                depth=candidate.depth + 1,
                from_seed=entity.is_seed,
            )
            if include_similarity and entity.is_seed:
                derived.extend(
                    similarity_candidates(
                        profile,
                        depth=candidate.depth + 1,
                        platforms=self._similarity_platforms(),
                        known=set(queued),
                    )
                )

            for next_candidate in derived:
                if next_candidate.key in queued:
                    # Already known: still record the link that was observed.
                    self._link(outcome, next_candidate)
                    continue
                queued.add(next_candidate.key)
                queue.append(next_candidate)

        self._attach_email_domains(outcome)
        self._record(
            outcome,
            "crawl_completed",
            (
                f"Discovery finished: {len(outcome.entities)} entities, "
                f"{len(outcome.links)} observed links, "
                f"{outcome.pages_fetched} pages fetched"
            ),
            entities=len(outcome.entities),
            links=len(outcome.links),
            pages=outcome.pages_fetched,
        )
        return outcome

    # -- one candidate -----------------------------------------------------

    async def _visit(
        self, candidate: Candidate, outcome: CrawlOutcome
    ) -> tuple[ObservedEntity | None, ObservedProfile | None]:
        """Look a candidate up and record whatever came back."""
        adapter = self.registry.get(candidate.platform)

        if adapter is None:
            # Discovery is allowed to outrun adapter coverage: the account is
            # recorded as an unresolved candidate node (section 14).
            if candidate.method is DiscoveryMethod.SIMILARITY:
                return None, None
            entity = self._record_entity(outcome, candidate, profile=None)
            self._record(
                outcome,
                "candidate_recorded",
                (
                    f"{candidate.label} recorded as an unresolved candidate "
                    f"(no adapter for {candidate.platform})"
                ),
                platform=candidate.platform, identifier=candidate.identifier,
            )
            self._link(outcome, candidate)
            return entity, None

        result = await adapter.lookup(candidate.identifier)
        outcome.pages_fetched += result.pages_fetched

        if not result.ok:
            outcome.issues.append(
                SourceIssueRecord(
                    platform=candidate.platform,
                    identifier=candidate.identifier,
                    reason=str(result.reason),
                    detail=result.detail or "",
                    url=result.url,
                )
            )
            self._record(
                outcome,
                "source_unavailable",
                f"{candidate.label} could not be read: {result.detail}",
                level="WARNING" if result.reason != FailureReason.NOT_FOUND else "INFO",
                platform=candidate.platform, reason=str(result.reason),
            )
            if candidate.method is DiscoveryMethod.SIMILARITY:
                return None, None
            entity = self._record_entity(outcome, candidate, profile=None)
            self._link(outcome, candidate)
            return entity, None

        profile = result.primary
        if profile is None:
            self._record(
                outcome,
                "no_public_data",
                f"No public profile found for {candidate.label}",
                platform=candidate.platform, identifier=candidate.identifier,
            )
            if candidate.method is DiscoveryMethod.SIMILARITY:
                return None, None
            entity = self._record_entity(outcome, candidate, profile=None)
            self._link(outcome, candidate)
            return entity, None

        entity = self._record_entity(outcome, candidate, profile=profile)
        self._record(
            outcome,
            "entity_discovered",
            f"{entity.entity_type.title()} discovered: {entity.label}",
            type=str(entity.entity_type), value=entity.identifier,
            method=str(candidate.method), depth=candidate.depth,
        )
        self._link(outcome, candidate)
        return entity, profile

    def _similarity_platforms(self) -> tuple[str, ...]:
        """Account platforms weak handle variants may be tried against.

        Derived from the registry so a newly added adapter is covered
        automatically, and so demo mode exercises the platforms it can serve.
        """
        return tuple(
            platform
            for platform in self.registry.platforms()
            if platform not in ("website", "email", "domain", "organization")
        )

    # -- bookkeeping -------------------------------------------------------

    def _record_entity(
        self,
        outcome: CrawlOutcome,
        candidate: Candidate,
        profile: ObservedProfile | None,
    ) -> ObservedEntity:
        """Create or update the entity for a candidate."""
        existing = outcome.entities.get(candidate.key)
        adapter = self.registry.get(candidate.platform)
        fallback_url = adapter.profile_url(candidate.identifier) if adapter else None
        url = candidate.url or (profile.url if profile else fallback_url)
        name = candidate.display_name or (
            f"@{candidate.identifier}"
            if candidate.entity_type is EntityType.ACCOUNT
            else candidate.identifier
        )

        if existing is not None:
            if profile is not None and existing.profile is None:
                existing.profile = profile
                existing.resolved = True
                existing.url = existing.url or url
            return existing

        entity = ObservedEntity(
            key=candidate.key,
            entity_type=candidate.entity_type,
            platform=candidate.platform,
            identifier=candidate.identifier,
            name=(profile.name if profile and profile.name else name),
            url=url,
            profile=profile,
            method=candidate.method,
            depth=candidate.depth,
            discovered_via=candidate.reason,
            resolved=profile is not None,
            is_seed=candidate.method is DiscoveryMethod.SEED,
        )
        outcome.entities[entity.key] = entity
        return entity

    def _link(self, outcome: CrawlOutcome, candidate: Candidate) -> None:
        """Record the observed link from a candidate's parent, if any."""
        if candidate.parent_key is None or candidate.key not in outcome.entities:
            return
        if candidate.parent_key not in outcome.entities:
            return
        if self._has_link(outcome, candidate.parent_key, candidate.key):
            return

        parent = outcome.entities[candidate.parent_key]
        target = outcome.entities[candidate.key]
        relationship_type, evidence_type, weight = self._structural_edge(target)
        outcome.links.append(
            ObservedLink(
                source_key=candidate.parent_key,
                target_key=candidate.key,
                relationship_type=relationship_type,
                evidence_type=evidence_type,
                description=(
                    f"{parent.label} publicly references {target.label}: "
                    f"{candidate.link_context or candidate.reason}"
                ),
                weight=weight,
                source_url=parent.url,
                extracted_value=candidate.link_context,
            )
        )
        self._record(
            outcome,
            "relationship_created",
            f"{parent.label} -> {target.label} ({relationship_type})",
            type=str(relationship_type),
        )

    @staticmethod
    def _has_link(
        outcome: CrawlOutcome,
        source: EntityKey,
        target: EntityKey,
        both_ways: bool = False,
    ) -> bool:
        """Whether an observed link already connects two entities."""
        for link in outcome.links:
            if link.source_key == source and link.target_key == target:
                return True
            if both_ways and link.source_key == target and link.target_key == source:
                return True
        return False

    def _structural_edge(
        self, entity: ObservedEntity
    ) -> tuple[RelationshipType, EvidenceType, float]:
        """Edge type and weight for an observed reference to an entity.

        Weights come from the scoring configuration so the value of observing
        an attribute is defined in exactly one place.
        """
        scoring = self.settings.scoring
        if entity.entity_type is EntityType.EMAIL:
            return RelationshipType.REFERENCES, EvidenceType.SHARED_EMAIL, scoring.shared_email
        if entity.entity_type is EntityType.ORGANIZATION:
            return (
                RelationshipType.REFERENCES,
                EvidenceType.SHARED_ORGANIZATION,
                scoring.shared_organization,
            )
        if entity.entity_type is EntityType.DOMAIN:
            return RelationshipType.REFERENCES, EvidenceType.SAME_WEBSITE, scoring.shared_website
        return RelationshipType.LINKS_TO, EvidenceType.EXPLICIT_LINK, scoring.explicit_link

    def _attach_email_domains(self, outcome: CrawlOutcome) -> None:
        """Give every discovered email address its domain as a pivot entity.

        When the domain is already present as a website, the email is linked to
        that website instead of duplicating it as a DOMAIN node.
        """
        websites = {
            entity.identifier: entity
            for entity in outcome.entities.values()
            if entity.entity_type is EntityType.WEBSITE
        }
        for entity in list(outcome.entities.values()):
            if entity.entity_type is not EntityType.EMAIL:
                continue
            candidate = email_domain_candidate(
                entity.identifier, depth=entity.depth + 1, parent_key=entity.key
            )
            if candidate is None:
                continue
            website = websites.get(candidate.identifier)
            if website is not None:
                if self._has_link(outcome, entity.key, website.key, both_ways=True):
                    continue
                outcome.links.append(
                    ObservedLink(
                        source_key=entity.key,
                        target_key=website.key,
                        relationship_type=RelationshipType.REFERENCES,
                        evidence_type=EvidenceType.SAME_WEBSITE,
                        description=(
                            f"The public email address {entity.identifier} uses the "
                            f"domain of {website.identifier}"
                        ),
                        weight=self.settings.scoring.shared_website,
                        extracted_value=candidate.identifier,
                    )
                )
                continue
            if candidate.key not in outcome.entities:
                self._record_entity(outcome, candidate, profile=None)
                self._record(
                    outcome,
                    "entity_discovered",
                    f"Domain discovered: {candidate.identifier}",
                    type="DOMAIN", value=candidate.identifier,
                )
            self._link(outcome, candidate)

    def _record(
        self,
        outcome: CrawlOutcome,
        event: str,
        message: str,
        level: str = "INFO",
        **fields: Any,
    ) -> None:
        """Log a structured event and keep it for the investigation timeline."""
        import logging

        log_event(
            logger, event, level=getattr(logging, level, logging.INFO), **fields
        )
        outcome.events.append(
            CrawlEventRecord(event=event, message=message, level=level, data=fields or None)
        )
