"""Investigation orchestration.

This is the seam between the async, network-facing half of Omnicient (sources
and crawler) and the storage-facing half (records and repository).  The crawler
produces observations in memory; this service persists them to Neo4j, runs
correlation over them, and records the timeline the analyst reads.

A failing source never fails an investigation: source problems are recorded as
timeline events and surfaced in the UI, and the investigation completes with
whatever evidence was gathered.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..config import Settings, get_settings
from ..models.entity import Entity
from ..models.enums import (
    AnalystStatus,
    ConfidenceLevel,
    DiscoveryMethod,
    EntityType,
    EvidenceType,
    InvestigationStatus,
    RelationshipType,
)
from ..models.evidence import Evidence
from ..models.investigation import CrawlEvent, Investigation
from ..models.relationship import Relationship
from ..models.snapshot import Snapshot
from ..repository import Neo4jRepository
from ..schemas.investigation import (
    InvestigationCreate,
    InvestigationExport,
    InvestigationRead,
    SourceIssue,
)
from ..sources import SourceRegistry, build_registry
from ..utils.identifier import detect_identifier
from ..utils.logging import get_logger
from ..utils.normalization import platform_label
from .alias_detection import AliasCandidate, AliasDetector, normalize_alias_candidate
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

    def __init__(
        self, repo: Neo4jRepository, settings: Settings | None = None
    ) -> None:
        self.repo = repo
        self.settings = settings or get_settings()

    # -- creation ----------------------------------------------------------

    def create(self, payload: InvestigationCreate) -> Investigation:
        """Create an investigation from a raw analyst input.

        The analyst supplies one identifier and no platform (section 3.2):
        :func:`detect_identifier` classifies it, and the platform is only ever
        taken from the input itself - a profile URL names its own platform - or
        from an explicit override.
        """
        # detect_identifier is the validation: it enforces length, rejects
        # empty and unrecognized input, and refuses non-HTTP schemes.  Running
        # a username normalizer first would reject valid email seeds.
        detected = detect_identifier(payload.identifier)
        platform = payload.platform or detected.seed_platform
        identifier = detected.identifier
        demo = self.settings.demo_mode if payload.demo is None else payload.demo
        investigation = Investigation(
            name=payload.name or self._default_name(platform, identifier, demo),
            seed_platform=platform,
            seed_identifier=identifier,
            seed_input=detected.raw,
            seed_type=str(detected.type),
            status=InvestigationStatus.CREATED,
            demo=demo,
            max_depth=payload.max_depth
            if payload.max_depth is not None
            else self.settings.max_depth,
            max_pages=payload.max_pages
            if payload.max_pages is not None
            else self.settings.max_pages,
        )
        investigation = self.repo.create_investigation(investigation)
        self._event(
            investigation,
            "investigation_created",
            f"Investigation created for {platform_label(platform)} @{identifier}",
            data={"seed": investigation.seed_label, "demo": demo},
        )
        logger.info(
            "investigation_created id=%s seed=%s type=%s demo=%s",
            investigation.id,
            investigation.seed_label,
            detected.type,
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
            self.repo.reset_investigation(investigation.id)

        investigation.status = InvestigationStatus.CRAWLING
        investigation.status_message = None
        investigation.started_at = datetime.now(UTC)
        investigation.completed_at = None
        investigation.max_depth = max_depth or investigation.max_depth
        investigation.max_pages = max_pages or investigation.max_pages
        self.repo.save_investigation(investigation)
        self._event(
            investigation,
            "identifier_detected",
            (
                f"Seed identifier detected: {investigation.seed_type or 'USERNAME'} "
                f"{investigation.seed_identifier}"
            ),
            data={
                "raw": investigation.seed_input,
                "identifier_type": investigation.seed_type,
                "identifier": investigation.seed_identifier,
                "platform": investigation.seed_platform,
            },
        )

        registry = self._registry(investigation)
        # Written out as the crawl goes, so an analyst sees accounts appear
        # rather than a spinner. Events are CREATE-only, so the number already
        # written is tracked; entities are a MERGE and can simply be
        # re-persisted.
        written_events = 0

        async def publish(partial: CrawlOutcome) -> None:
            nonlocal written_events
            self._record_events(investigation, partial, offset=written_events)
            written_events = len(partial.events)
            self._persist_entities(investigation, partial, record_history=False)
            entities, relationships, evidence = self.counts(investigation.id)
            investigation.entity_count = entities
            investigation.relationship_count = relationships
            investigation.evidence_count = evidence
            self.repo.save_investigation(investigation)

        try:
            outcome = await Crawler(registry, self.settings).crawl(
                investigation.seed_platform,
                investigation.seed_identifier,
                max_depth=investigation.max_depth,
                max_pages=investigation.max_pages,
                on_level=publish,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced, never crashes the app
            logger.exception("crawl_failed investigation=%s", investigation.id)
            investigation.status = InvestigationStatus.FAILED
            investigation.status_message = str(exc)
            self.repo.save_investigation(investigation)
            self._event(
                investigation,
                "investigation_failed",
                f"Investigation failed: {exc}",
                level="ERROR",
            )
            return RunSummary()
        finally:
            await registry.aclose()

        # Whatever the last level did not already flush.
        self._record_events(investigation, outcome, offset=written_events)

        entity_map = self._persist_entities(investigation, outcome)
        evidence_count = self._persist_links(investigation, outcome, entity_map)
        self._warn_if_seed_unresolved(investigation, outcome, entity_map)

        investigation.status = InvestigationStatus.ANALYZING
        self.repo.save_investigation(investigation)

        results = CorrelationEngine(self.settings.scoring).correlate(outcome.profiles)
        correlation_evidence = self._persist_correlations(
            investigation, results, entity_map
        )
        aliases = AliasDetector(self.settings.scoring).detect(
            outcome.profiles, results
        )
        alias_evidence = self._persist_aliases(investigation, aliases, entity_map)
        if aliases:
            self._event(
                investigation,
                "aliases_detected",
                (
                    f"{len(aliases)} potential aliases proposed from handle "
                    f"transformations"
                ),
                data={"aliases": len(aliases)},
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

        investigation.status = InvestigationStatus.COMPLETED
        investigation.completed_at = datetime.now(UTC)
        self.repo.save_investigation(investigation)

        summary = RunSummary(
            entities=len(entity_map),
            relationships=len(outcome.links) + len(results),
            evidence=evidence_count + correlation_evidence + alias_evidence,
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
        self._event(
            investigation,
            "investigation_completed",
            (
                f"Investigation completed: {summary.entities} entities, "
                f"{summary.relationships} relationships, "
                f"{summary.evidence} evidence items"
            ),
            data={
                "entities": summary.entities,
                "relationships": summary.relationships,
                "evidence": summary.evidence,
            },
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
        if seed is None:
            return

        if seed.type == str(EntityType.USERNAME):
            # A bare handle seeds a pivot node that always "resolves".  What
            # matters is whether any source actually answered for it.
            found = any(
                entity.resolved
                for key, entity in entities.items()
                if key != outcome.seed_key
            )
            if found:
                return
        elif seed.resolved:
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
                f"No supported source returned public data for "
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

    # -- persistence -------------------------------------------------------

    def _persist_entities(
        self,
        investigation: Investigation,
        outcome: CrawlOutcome,
        *,
        record_history: bool = True,
    ) -> dict[tuple[str, str, str], Entity]:
        """Store observed entities and write a snapshot for each observation.

        ``record_history`` is false while the crawl is still running. The
        nodes themselves are a MERGE and can be written after every level
        safely, but a snapshot is one observation and the timeline entry is
        one line: writing either once per level would record the same
        observation several times and repeat itself in the activity log.
        """
        stored: dict[tuple[str, str, str], Entity] = {}
        snapshots: list[Snapshot] = []
        for observed in outcome.entities.values():
            entity = self._upsert_entity(investigation, observed)
            stored[observed.key] = entity
            if record_history and observed.profile is not None:
                snapshots.append(
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
        if not record_history:
            return stored

        self.repo.add_snapshots(snapshots)
        self._event(
            investigation,
            "entities_discovered",
            f"{len(stored)} entities discovered "
            f"({sum(1 for e in stored.values() if e.resolved)} with public data)",
            data={"entities": len(stored)},
        )
        return stored

    def _upsert_entity(
        self, investigation: Investigation, observed: ObservedEntity
    ) -> Entity:
        """Create or refresh the node for an observed entity."""
        profile = observed.profile
        entity = Entity(
            investigation_id=investigation.id,
            type=str(observed.entity_type),
            platform=observed.platform,
            identifier=observed.identifier,
            name=observed.name,
            url=observed.url,
            depth=observed.depth,
            discovery_method=str(observed.method),
            discovered_via=observed.discovered_via,
            resolved=observed.resolved,
            is_seed=observed.is_seed,
            source=profile.source if profile else None,
        )

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
            entity.meta = {"demo": True, "notice": "DEMO DATA"}

        return self.repo.upsert_entity(entity)

    def _persist_links(
        self,
        investigation: Investigation,
        outcome: CrawlOutcome,
        entities: dict[tuple[str, str, str], Entity],
    ) -> int:
        """Store the explicit links the crawler observed, with their evidence."""
        engine = CorrelationEngine(self.settings.scoring)
        evidence: list[Evidence] = []
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
            evidence.append(
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
        return self.repo.add_evidence(evidence)

    def _persist_correlations(
        self,
        investigation: Investigation,
        results: list[CorrelationResult],
        entities: dict[tuple[str, str, str], Entity],
    ) -> int:
        """Store correlation relationships and every evidence item behind them."""
        evidence: list[Evidence] = []
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
            evidence.extend(
                Evidence(
                    investigation_id=investigation.id,
                    relationship_id=relationship.id,
                    source_entity_id=source.id,
                    target_entity_id=target.id,
                    type=str(item.type),
                    description=item.description,
                    source_url=item.source_url,
                    extracted_value=item.extracted_value,
                    normalized_value=item.normalized_value,
                    weight=item.weight,
                    supports=item.supports,
                )
                for item in result.evidence
            )
        return self.repo.add_evidence(evidence)

    def _persist_aliases(
        self,
        investigation: Investigation,
        candidates: list[AliasCandidate],
        entities: dict[tuple[str, str, str], Entity],
    ) -> int:
        """Store potential aliases as their own edge type, with their signals.

        A ``POTENTIAL_ALIAS`` is deliberately distinct from
        ``POTENTIAL_SAME_IDENTITY``: it says the *handles* look related, which
        is a narrower and weaker claim than saying the accounts might be one
        person.  Keeping them apart lets an analyst filter for one without the
        other.
        """
        evidence: list[Evidence] = []
        for candidate in candidates:
            account = str(EntityType.ACCOUNT)
            source = entities.get(
                (account, candidate.source_platform or "", candidate.source_identifier)
            )
            target = entities.get(
                (account, candidate.target_platform or "", candidate.target_identifier)
            )
            if source is None or target is None:  # pragma: no cover - defensive
                continue

            relationship = self._upsert_relationship(
                investigation,
                source,
                target,
                str(RelationshipType.POTENTIAL_ALIAS),
                score=candidate.score,
                level=candidate.confidence,
                summary=candidate.summary,
            )
            # One evidence row per transformation, so the alias is as
            # traceable as any other scored relationship.
            for signal in candidate.signals:
                if signal.kind in {str(item.type) for item in candidate.supporting_evidence}:
                    # Contextual evidence is already stored against the
                    # correlation edge; do not duplicate the row.
                    continue
                evidence.append(
                    Evidence(
                        investigation_id=investigation.id,
                        relationship_id=relationship.id,
                        source_entity_id=source.id,
                        target_entity_id=target.id,
                        type=str(EvidenceType.USERNAME_TRANSFORMATION),
                        description=f"{signal.label}: {signal.detail}",
                        extracted_value=candidate.target_identifier,
                        normalized_value=normalize_alias_candidate(
                            candidate.target_identifier
                        ),
                        weight=0.0,
                        supports=True,
                        context={
                            "transformation": signal.kind,
                            "similarity": candidate.similarity,
                            "strength": str(candidate.strength),
                        },
                    )
                )
        return self.repo.add_evidence(evidence)

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
        return self.repo.upsert_relationship(
            Relationship(
                investigation_id=investigation.id,
                source_entity_id=source.id,
                target_entity_id=target.id,
                relationship_type=relationship_type,
                confidence_score=round(float(score), 1),
                confidence_level=level,
                analyst_status=AnalystStatus.UNREVIEWED,
                summary=summary,
            )
        )

    # -- reading -----------------------------------------------------------

    def _event(
        self,
        investigation: Investigation,
        event: str,
        message: str,
        level: str = "INFO",
        data: dict | None = None,
    ) -> None:
        """Append one line to the activity timeline.

        Events are written as they happen rather than batched at the end, so
        the interface can poll the timeline while a crawl is still running.
        """
        self.repo.add_events(
            [
                CrawlEvent(
                    investigation_id=investigation.id,
                    event=event,
                    message=message,
                    level=level,
                    data=data,
                )
            ]
        )

    def _record_events(
        self, investigation: Investigation, outcome: CrawlOutcome, offset: int = 0
    ) -> None:
        """Persist the crawler's buffered timeline in one round trip.

        ``offset`` skips the records already written by an earlier flush;
        events are created rather than merged, so writing the whole buffer
        again would duplicate the timeline.
        """
        self.repo.add_events(
            [
                CrawlEvent(
                    investigation_id=investigation.id,
                    event=record.event,
                    message=record.message,
                    level=record.level,
                    data=record.data,
                )
                for record in outcome.events[offset:]
            ]
        )

    def counts(self, investigation_id: str) -> tuple[int, int, int]:
        """``(entities, relationships, evidence)`` for one investigation."""
        return self.repo.counts(investigation_id)

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
        events = self.repo.list_events(
            investigation_id, events=list(ISSUE_EVENTS)
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
        return self.repo.seed_entity(investigation_id)

    # -- export ------------------------------------------------------------

    def export(self, investigation: Investigation) -> InvestigationExport:
        """Complete JSON export of an investigation (section 39)."""
        from ..schemas.entity import EntityRead, SnapshotRead
        from ..schemas.evidence import EvidenceRead
        from ..schemas.investigation import CrawlEventRead
        from ..schemas.relationship import RelationshipRead

        entities = self.repo.list_entities(investigation.id)
        relationships = self.repo.list_relationships(investigation.id)
        evidence = self.repo.list_evidence(investigation.id)
        events = self.repo.list_events(investigation.id, limit=1000)

        snapshots = [
            SnapshotRead.model_validate(snapshot)
            for entity in entities
            for snapshot in self.repo.snapshots_for_entity(entity.id)
        ]

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
            snapshots=snapshots,
            crawl_events=[CrawlEventRead.model_validate(event) for event in events],
        )


    def export_csv(self, investigation: Investigation) -> str:
        """Flat CSV export of an investigation (section 29).

        One row per relationship, with its endpoints, score, analyst verdict
        and its evidence collapsed into two columns.  A relationship with no
        evidence would be a claim without a reason, so the supporting and
        contradicting columns are always written even when empty.

        ``origin`` says whether the engine derived the row from observations
        or an analyst drew it by hand.  Whoever reads this file will not have
        the interface in front of them to tell the two apart, and they carry
        very different warrant, so the distinction has to travel with the data.
        """
        import csv
        import io

        entities = {
            entity.id: entity for entity in self.repo.list_entities(investigation.id)
        }
        relationships = self.repo.attach_evidence(
            self.repo.list_relationships(investigation.id)
        )

        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(
            [
                "investigation_id",
                "investigation_name",
                "demo_data",
                "source_platform",
                "source_identifier",
                "target_platform",
                "target_identifier",
                "relationship_type",
                "origin",
                "score",
                "confidence",
                "analyst_status",
                "analyst_note",
                "reviewed_at",
                "supporting_evidence",
                "contradicting_evidence",
            ]
        )

        def describe(items: list[Evidence], supports: bool) -> str:
            return " | ".join(
                f"{item.type} ({item.weight:+.0f}): {item.description}"
                for item in items
                if item.supports is supports
            )

        for relationship in relationships:
            source = entities.get(relationship.source_entity_id)
            target = entities.get(relationship.target_entity_id)
            writer.writerow(
                [
                    investigation.id,
                    investigation.name,
                    "yes" if investigation.demo else "no",
                    source.platform if source else "",
                    source.identifier if source else "",
                    target.platform if target else "",
                    target.identifier if target else "",
                    relationship.relationship_type,
                    relationship.origin,
                    f"{relationship.confidence_score:g}",
                    relationship.confidence_level,
                    relationship.analyst_status,
                    relationship.analyst_note or "",
                    relationship.reviewed_at.isoformat()
                    if relationship.reviewed_at
                    else "",
                    describe(relationship.evidence, True),
                    describe(relationship.evidence, False),
                ]
            )
        return buffer.getvalue()


# Re-exported so callers can describe a level without importing the enum path.
__all__ = ["ConfidenceLevel", "DiscoveryMethod", "EntityType", "InvestigationService", "RunSummary"]
