"""Investigation orchestration.

This is the seam between the async, network-facing half of Omnicient (sources
and crawler) and the synchronous, database-facing half (models and API).  The
crawler produces observations in memory; this service persists them, runs
correlation over them, and records the timeline the analyst reads.

A failing source never fails an investigation: source problems are recorded as
timeline events and surfaced in the UI, and the investigation completes with
whatever evidence was gathered.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models.entity import Entity
from ..models.enums import (
    AnalystStatus,
    ConfidenceLevel,
    DiscoveryMethod,
    EntityType,
    InvestigationStatus,
)
from ..models.evidence import Evidence
from ..models.investigation import CrawlEvent, Investigation
from ..models.relationship import Relationship
from ..models.snapshot import Snapshot
from ..schemas.investigation import (
    InvestigationCreate,
    InvestigationExport,
    InvestigationRead,
    SourceIssue,
)
from ..sources import SourceRegistry, build_registry
from ..utils.logging import get_logger
from ..utils.normalization import platform_label
from ..utils.validation import validate_seed_identifier
from .correlation import CorrelationEngine, CorrelationResult
from .crawler import Crawler, CrawlOutcome, ObservedEntity

logger = get_logger(__name__)

#: Timeline events the interface surfaces as analyst-facing problems.
ISSUE_EVENTS = ("source_unavailable", "seed_unresolved")

EXPORT_DISCLAIMER = (
    "Omnicient reports potential associations supported by publicly observable "
    "evidence. Nothing in this export asserts that two accounts belong to the "
    "same person. Analyst confirmation means the evidence was reviewed and "
    "judged supportive, not that an identity was proven."
)


@dataclass
class RunSummary:
    """Counts produced by one crawl + correlation run."""

    entities: int = 0
    relationships: int = 0
    evidence: int = 0
    pages_fetched: int = 0
    issues: list[SourceIssue] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.issues is None:
            self.issues = []


class InvestigationService:
    """Creates, runs, reads and exports investigations."""

    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    # -- creation ----------------------------------------------------------

    def create(self, payload: InvestigationCreate) -> Investigation:
        """Create an investigation from a validated seed identifier."""
        identifier = validate_seed_identifier(payload.identifier)
        demo = self.settings.demo_mode if payload.demo is None else payload.demo
        investigation = Investigation(
            name=payload.name or self._default_name(payload.platform, identifier, demo),
            seed_platform=payload.platform,
            seed_identifier=identifier,
            status=InvestigationStatus.CREATED,
            demo=demo,
            max_depth=payload.max_depth
            if payload.max_depth is not None
            else self.settings.max_depth,
            max_pages=payload.max_pages
            if payload.max_pages is not None
            else self.settings.max_pages,
        )
        self.db.add(investigation)
        self.db.flush()
        self._event(
            investigation,
            "investigation_created",
            f"Investigation created for {platform_label(payload.platform)} "
            f"@{identifier}",
            data={"seed": investigation.seed_label, "demo": demo},
        )
        self.db.commit()
        logger.info(
            "investigation_created id=%s seed=%s demo=%s",
            investigation.id,
            investigation.seed_label,
            demo,
        )
        return investigation

    @staticmethod
    def _default_name(platform: str, identifier: str, demo: bool) -> str:
        prefix = "DEMO " if demo else ""
        return f"{prefix}{platform_label(platform)} @{identifier}"

    # -- running -----------------------------------------------------------

    async def run(
        self,
        investigation: Investigation,
        *,
        max_depth: int | None = None,
        max_pages: int | None = None,
        reset: bool = True,
    ) -> RunSummary:
        """Crawl, correlate and persist.  Never raises for source failures."""
        if reset:
            self._reset(investigation)

        investigation.status = InvestigationStatus.CRAWLING
        investigation.status_message = None
        investigation.started_at = datetime.now(UTC)
        investigation.max_depth = max_depth or investigation.max_depth
        investigation.max_pages = max_pages or investigation.max_pages
        self.db.commit()

        registry = self._registry(investigation)
        try:
            outcome = await Crawler(registry, self.settings).crawl(
                investigation.seed_platform,
                investigation.seed_identifier,
                max_depth=investigation.max_depth,
                max_pages=investigation.max_pages,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced, never crashes the app
            logger.exception("crawl_failed investigation=%s", investigation.id)
            investigation.status = InvestigationStatus.FAILED
            investigation.status_message = str(exc)
            self._event(
                investigation,
                "investigation_failed",
                f"Investigation failed: {exc}",
                level="ERROR",
            )
            self.db.commit()
            return RunSummary()
        finally:
            await registry.aclose()

        entity_map = self._persist_entities(investigation, outcome)
        evidence_count = self._persist_links(investigation, outcome, entity_map)
        self._warn_if_seed_unresolved(investigation, outcome, entity_map)

        investigation.status = InvestigationStatus.ANALYZING
        self.db.flush()

        results = CorrelationEngine(self.settings.scoring).correlate(outcome.profiles)
        correlation_evidence = self._persist_correlations(
            investigation, results, entity_map
        )
        self._event(
            investigation,
            "correlation_completed",
            (
                f"Correlation completed: {len(results)} potential associations "
                f"from {len(outcome.profiles)} resolved profiles"
            ),
            data={"candidates": len(outcome.profiles), "relationships": len(results)},
        )

        for record in outcome.events:
            self._event(
                investigation,
                record.event,
                record.message,
                level=record.level,
                data=record.data,
            )

        investigation.status = InvestigationStatus.COMPLETED
        investigation.completed_at = datetime.now(UTC)
        self.db.commit()

        summary = RunSummary(
            entities=len(entity_map),
            relationships=len(outcome.links) + len(results),
            evidence=evidence_count + correlation_evidence,
            pages_fetched=outcome.pages_fetched,
            issues=[
                SourceIssue(
                    platform=issue.platform,
                    identifier=issue.identifier,
                    reason=issue.reason,
                    detail=issue.detail,
                    url=issue.url,
                )
                for issue in outcome.issues
            ],
        )
        logger.info(
            "investigation_completed id=%s entities=%d relationships=%d evidence=%d",
            investigation.id,
            summary.entities,
            summary.relationships,
            summary.evidence,
        )
        return summary

    def _warn_if_seed_unresolved(
        self,
        investigation: Investigation,
        outcome: CrawlOutcome,
        entities: dict[tuple[str, str, str], Entity],
    ) -> None:
        """Say so plainly when the seed itself could not be read.

        An investigation whose seed never resolved has nothing to expand from,
        and the reason matters: in demo mode it usually means the handle simply
        is not part of the synthetic dataset.
        """
        seed = entities.get(outcome.seed_key) if outcome.seed_key else None
        if seed is None or seed.resolved:
            return

        if investigation.demo:
            from ..demo_data import DEMO_SEED_IDENTIFIER

            message = (
                f"Demo mode serves only the built-in synthetic dataset, which does "
                f"not include {investigation.seed_label}. Start from the demo seed "
                f"@{DEMO_SEED_IDENTIFIER}, or switch demo mode off to query live "
                f"public sources."
            )
            reason = "NOT_IN_DEMO_DATASET"
        else:
            message = (
                f"No public data could be read for the seed "
                f"{investigation.seed_label}, so there was nothing to expand from."
            )
            reason = "SEED_UNRESOLVED"

        self._event(
            investigation,
            "seed_unresolved",
            message,
            level="WARNING",
            data={
                "platform": investigation.seed_platform,
                "identifier": investigation.seed_identifier,
                "reason": reason,
            },
        )

    def _registry(self, investigation: Investigation) -> SourceRegistry:
        """Demo investigations never touch the network."""
        if investigation.demo:
            from ..demo_data import build_demo_registry

            return build_demo_registry()
        return build_registry(self.settings)

    def _reset(self, investigation: Investigation) -> None:
        """Drop previously discovered data before a re-crawl."""
        for model in (Evidence, Relationship, Entity, CrawlEvent):
            self.db.execute(
                delete(model).where(model.investigation_id == investigation.id)
            )
        self.db.flush()

    # -- persistence -------------------------------------------------------

    def _persist_entities(
        self, investigation: Investigation, outcome: CrawlOutcome
    ) -> dict[tuple[str, str, str], Entity]:
        """Store observed entities and write a snapshot for each observation."""
        stored: dict[tuple[str, str, str], Entity] = {}
        for observed in outcome.entities.values():
            entity = self._upsert_entity(investigation, observed)
            stored[observed.key] = entity
            if observed.profile is not None:
                self.db.add(
                    Snapshot(
                        entity_id=entity.id,
                        username=observed.identifier,
                        display_name=entity.display_name,
                        bio=entity.bio,
                        avatar_url=entity.avatar_url,
                        external_links=list(entity.external_links or []),
                        meta={"source": observed.profile.source or observed.platform},
                    )
                )
        self.db.flush()
        return stored

    def _upsert_entity(
        self, investigation: Investigation, observed: ObservedEntity
    ) -> Entity:
        """Create or refresh the row for an observed entity."""
        entity = self.db.scalar(
            select(Entity).where(
                Entity.investigation_id == investigation.id,
                Entity.type == str(observed.entity_type),
                Entity.platform == observed.platform,
                Entity.identifier == observed.identifier,
            )
        )
        now = datetime.now(UTC)
        profile = observed.profile

        if entity is None:
            entity = Entity(
                investigation_id=investigation.id,
                type=str(observed.entity_type),
                platform=observed.platform,
                identifier=observed.identifier,
                name=observed.name,
                is_seed=observed.is_seed,
                first_seen=now,
            )
            self.db.add(entity)

        entity.name = observed.name
        entity.url = observed.url or entity.url
        entity.depth = observed.depth
        entity.discovery_method = str(observed.method)
        entity.discovered_via = observed.discovered_via
        entity.resolved = observed.resolved
        entity.last_seen = now
        entity.source = profile.source if profile else None

        if profile is not None:
            entity.display_name = profile.display_name
            entity.bio = profile.bio
            entity.avatar_url = profile.avatar_url
            entity.location = profile.location
            entity.email = profile.email
            entity.organization = profile.organization
            entity.external_links = list(profile.external_links)
            entity.meta = {
                **profile.metadata,
                "websites": profile.websites,
                "emails": profile.emails,
                "organizations": profile.organizations,
                "references": [
                    {
                        "platform": reference.platform,
                        "identifier": reference.identifier,
                        "url": reference.url,
                        "context": reference.context,
                    }
                    for reference in profile.references
                ],
            }
        elif investigation.demo:
            entity.meta = {**(entity.meta or {}), "demo": True, "notice": "DEMO DATA"}

        self.db.flush()
        return entity

    def _persist_links(
        self,
        investigation: Investigation,
        outcome: CrawlOutcome,
        entities: dict[tuple[str, str, str], Entity],
    ) -> int:
        """Store the explicit links the crawler observed, with their evidence."""
        engine = CorrelationEngine(self.settings.scoring)
        count = 0
        for link in outcome.links:
            source = entities.get(link.source_key)
            target = entities.get(link.target_key)
            if source is None or target is None:  # pragma: no cover - defensive
                continue
            relationship = self._upsert_relationship(
                investigation,
                source,
                target,
                str(link.relationship_type),
                score=link.weight,
                level=str(engine.score_to_level(link.weight)),
                summary=link.description,
            )
            self.db.add(
                Evidence(
                    investigation_id=investigation.id,
                    relationship_id=relationship.id,
                    source_entity_id=source.id,
                    target_entity_id=target.id,
                    type=str(link.evidence_type),
                    description=link.description,
                    source_url=link.source_url,
                    extracted_value=link.extracted_value,
                    weight=link.weight,
                    supports=True,
                )
            )
            count += 1
        self.db.flush()
        return count

    def _persist_correlations(
        self,
        investigation: Investigation,
        results: list[CorrelationResult],
        entities: dict[tuple[str, str, str], Entity],
    ) -> int:
        """Store correlation relationships and every evidence item behind them."""
        count = 0
        for result in results:
            source = entities.get(result.source_key)
            target = entities.get(result.target_key)
            if source is None or target is None:  # pragma: no cover - defensive
                continue
            relationship = self._upsert_relationship(
                investigation,
                source,
                target,
                str(result.relationship_type),
                score=result.score,
                level=str(result.confidence_level),
                summary=result.summary,
            )
            for item in result.evidence:
                self.db.add(
                    Evidence(
                        investigation_id=investigation.id,
                        relationship_id=relationship.id,
                        source_entity_id=source.id,
                        target_entity_id=target.id,
                        type=str(item.type),
                        description=item.description,
                        source_url=item.source_url,
                        extracted_value=item.extracted_value,
                        weight=item.weight,
                        supports=item.supports,
                    )
                )
                count += 1
        self.db.flush()
        return count

    def _upsert_relationship(
        self,
        investigation: Investigation,
        source: Entity,
        target: Entity,
        relationship_type: str,
        *,
        score: float,
        level: str,
        summary: str | None,
    ) -> Relationship:
        """Create or refresh a relationship, preserving the analyst's verdict."""
        relationship = self.db.scalar(
            select(Relationship).where(
                Relationship.investigation_id == investigation.id,
                Relationship.source_entity_id == source.id,
                Relationship.target_entity_id == target.id,
                Relationship.relationship_type == relationship_type,
            )
        )
        if relationship is None:
            relationship = Relationship(
                investigation_id=investigation.id,
                source_entity_id=source.id,
                target_entity_id=target.id,
                relationship_type=relationship_type,
                analyst_status=AnalystStatus.UNREVIEWED,
            )
            self.db.add(relationship)
        relationship.confidence_score = round(float(score), 1)
        relationship.confidence_level = level
        relationship.summary = summary
        self.db.flush()
        return relationship

    # -- reading -----------------------------------------------------------

    def _event(
        self,
        investigation: Investigation,
        event: str,
        message: str,
        level: str = "INFO",
        data: dict | None = None,
    ) -> None:
        self.db.add(
            CrawlEvent(
                investigation_id=investigation.id,
                event=event,
                message=message,
                level=level,
                data=data,
            )
        )

    def counts(self, investigation_id: str) -> tuple[int, int, int]:
        """``(entities, relationships, evidence)`` for one investigation."""
        return (
            self.db.scalar(
                select(func.count(Entity.id)).where(
                    Entity.investigation_id == investigation_id
                )
            )
            or 0,
            self.db.scalar(
                select(func.count(Relationship.id)).where(
                    Relationship.investigation_id == investigation_id
                )
            )
            or 0,
            self.db.scalar(
                select(func.count(Evidence.id)).where(
                    Evidence.investigation_id == investigation_id
                )
            )
            or 0,
        )

    def to_read(self, investigation: Investigation) -> InvestigationRead:
        """Serialize an investigation with its headline counts."""
        entities, relationships, evidence = self.counts(investigation.id)
        model = InvestigationRead.model_validate(investigation)
        return model.model_copy(
            update={
                "entity_count": entities,
                "relationship_count": relationships,
                "evidence_count": evidence,
            }
        )

    def issues(self, investigation_id: str) -> list[SourceIssue]:
        """Source failures recorded during the most recent run."""
        events = self.db.scalars(
            select(CrawlEvent)
            .where(
                CrawlEvent.investigation_id == investigation_id,
                CrawlEvent.event.in_(ISSUE_EVENTS),
            )
            .order_by(CrawlEvent.timestamp)
        )
        issues: list[SourceIssue] = []
        for event in events:
            data = event.data or {}
            issues.append(
                SourceIssue(
                    platform=data.get("platform", "unknown"),
                    identifier=data.get("identifier"),
                    reason=data.get("reason", "UNKNOWN"),
                    detail=event.message,
                    url=data.get("url"),
                )
            )
        return issues

    def seed_entity(self, investigation_id: str) -> Entity | None:
        return self.db.scalar(
            select(Entity).where(
                Entity.investigation_id == investigation_id, Entity.is_seed.is_(True)
            )
        )

    # -- export ------------------------------------------------------------

    def export(self, investigation: Investigation) -> InvestigationExport:
        """Complete JSON export of an investigation (section 39)."""
        from ..schemas.entity import EntityRead
        from ..schemas.evidence import EvidenceRead
        from ..schemas.investigation import CrawlEventRead
        from ..schemas.relationship import RelationshipRead

        entities = list(
            self.db.scalars(
                select(Entity)
                .where(Entity.investigation_id == investigation.id)
                .order_by(Entity.depth, Entity.created_at)
            )
        )
        relationships = list(
            self.db.scalars(
                select(Relationship)
                .where(Relationship.investigation_id == investigation.id)
                .order_by(Relationship.confidence_score.desc())
            )
        )
        evidence = list(
            self.db.scalars(
                select(Evidence)
                .where(Evidence.investigation_id == investigation.id)
                .order_by(Evidence.collected_at)
            )
        )
        events = list(
            self.db.scalars(
                select(CrawlEvent)
                .where(CrawlEvent.investigation_id == investigation.id)
                .order_by(CrawlEvent.timestamp)
            )
        )

        return InvestigationExport(
            generated_at=datetime.now(UTC),
            disclaimer=EXPORT_DISCLAIMER
            + (" This investigation uses synthetic DEMO DATA." if investigation.demo else ""),
            investigation=self.to_read(investigation),
            seed={
                "platform": investigation.seed_platform,
                "identifier": investigation.seed_identifier,
                "label": investigation.seed_label,
                "demo": investigation.demo,
            },
            entities=[EntityRead.model_validate(entity) for entity in entities],
            relationships=[
                RelationshipRead.model_validate(relationship)
                for relationship in relationships
            ],
            evidence=[EvidenceRead.model_validate(item) for item in evidence],
            crawl_events=[CrawlEventRead.model_validate(event) for event in events],
        )


# Re-exported so callers can describe a level without importing the enum path.
__all__ = ["ConfidenceLevel", "DiscoveryMethod", "EntityType", "InvestigationService", "RunSummary"]
