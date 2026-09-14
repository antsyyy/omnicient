"""Per-source results: what each source actually yielded.

Assembled from what the investigation already stored - the entities that were
recorded, the relationships tying them to the seed, and the timeline events
describing sources that answered with nothing or refused to answer at all.
Nothing is re-queried and nothing new is persisted.

The reason this exists as its own reading of the graph: a source that found
nothing and a source that refused are both *absent* from the graph, and an
analyst needs to tell them apart. "Reddit declined the request" and "the handle
is not on Reddit" lead to completely different next steps.
"""

from __future__ import annotations

from collections import defaultdict

from ..models.entity import Entity
from ..models.enums import AnalystStatus, EntityType
from ..models.investigation import Investigation
from ..models.relationship import Relationship
from ..repository import Neo4jRepository
from ..schemas.entity import EntitySummary
from ..schemas.results import SourceOutcome, SourceResult, SourceResults
from ..sources import ADAPTER_CLASSES
from ..utils.logging import get_logger
from ..utils.normalization import platform_label

logger = get_logger(__name__)

#: Timeline events naming a source that answered with nothing.
EMPTY_EVENTS = frozenset({"no_public_data"})
#: Timeline events naming a source that did not yield a profile.
UNAVAILABLE_EVENTS = frozenset({"source_unavailable"})

#: Failure reasons that mean the source *answered* and the handle is not
#: there. Everything else means the source never gave an answer to trust.
#: The crawler reports both through one event, but they are opposite
#: findings: a 404 closes a line of enquiry, a block leaves it open.
ANSWERED_EMPTY_REASONS = frozenset({"NOT_FOUND"})

#: Outcome ordering for display: what was found first, then what was tried.
OUTCOME_RANK: dict[str, int] = {
    SourceOutcome.FOUND: 0,
    SourceOutcome.REFERENCED_ONLY: 1,
    SourceOutcome.UNAVAILABLE: 2,
    SourceOutcome.NOT_FOUND: 3,
    SourceOutcome.NOT_QUERIED: 4,
}


class ResultsService:
    """Builds the per-source results list for one investigation."""

    def __init__(self, repo: Neo4jRepository) -> None:
        self.repo = repo

    def build(self, investigation: Investigation) -> SourceResults:
        """One row per source, strongest evidence first."""
        entities = self.repo.list_entities(investigation.id)
        relationships = self.repo.attach_evidence(
            self.repo.list_relationships(investigation.id)
        )
        events = self.repo.list_events(investigation.id, limit=1000)

        categories = {
            adapter.platform: str(adapter.category) for adapter in ADAPTER_CLASSES
        }
        best = self._strongest_by_entity(relationships)

        # Accounts that were actually recorded, keyed by platform. A platform
        # can yield more than one account; the resolved one wins the row and
        # the rest still appear.
        by_platform: dict[str, list[Entity]] = defaultdict(list)
        for entity in entities:
            if entity.type == str(EntityType.ACCOUNT):
                by_platform[entity.platform].append(entity)

        # Sources the timeline says were reached but yielded nothing, or
        # declined. Both are invisible in the graph.
        # ``issues`` keeps the reason and wording for every source that did
        # not yield a profile, whichever way it failed - the row wants to say
        # *why* even when the outcome is "nothing found". ``empty`` is the
        # subset that answered.
        empty: set[str] = set()
        issues: dict[str, tuple[str, str]] = {}
        for event in events:
            data = event.data or {}
            platform = data.get("platform")
            if not platform:
                continue
            if event.event in EMPTY_EVENTS:
                empty.add(platform)
            elif event.event in UNAVAILABLE_EVENTS:
                reason = data.get("reason", "UNAVAILABLE")
                issues[platform] = (reason, event.message)
                if reason in ANSWERED_EMPTY_REASONS:
                    empty.add(platform)

        results: list[SourceResult] = []
        seen: set[str] = set()

        for platform, members in by_platform.items():
            seen.add(platform)
            members.sort(key=lambda e: (not e.resolved, e.depth, e.identifier))
            for entity in members:
                results.append(self._row(entity, platform, categories, best, issues))

        for platform, (reason, detail) in issues.items():
            if platform in seen:
                continue
            seen.add(platform)
            results.append(
                SourceResult(
                    platform=platform,
                    platform_name=platform_label(platform),
                    category=categories.get(platform, "social"),
                    outcome=_outcome_for_reason(reason),
                    reason=reason,
                    detail=detail,
                )
            )

        for platform in empty - seen:
            seen.add(platform)
            results.append(
                SourceResult(
                    platform=platform,
                    platform_name=platform_label(platform),
                    category=categories.get(platform, "social"),
                    outcome=SourceOutcome.NOT_FOUND,
                )
            )

        # Adapters the run never reached. Only worth reporting when the run
        # was *supposed* to reach them: a bare handle fans out across the
        # catalogue, so a gap there is a finding. A seeded profile URL queries
        # one source by design, and a demo run has only the synthetic
        # registry available - listing two dozen untouched platforms in either
        # case buries the results that matter under rows that mean nothing.
        expected_fan_out = (
            not investigation.demo
            and (investigation.seed_type or "").upper() == "USERNAME"
        )
        if expected_fan_out:
            for platform, category in categories.items():
                if platform in seen or platform in ("website", "email", "domain"):
                    continue
                results.append(
                    SourceResult(
                        platform=platform,
                        platform_name=platform_label(platform),
                        category=category,
                        outcome=SourceOutcome.NOT_QUERIED,
                    )
                )

        results.sort(
            key=lambda r: (
                OUTCOME_RANK.get(str(r.outcome), 9),
                -(r.score or 0),
                r.platform_name.lower(),
            )
        )
        logger.info(
            "results_built investigation=%s sources=%d found=%d",
            investigation.id,
            len(results),
            sum(1 for r in results if r.outcome is SourceOutcome.FOUND),
        )
        return SourceResults(
            investigation_id=investigation.id,
            seed_identifier=investigation.seed_identifier,
            seed_type=investigation.seed_type or "USERNAME",
            results=results,
        )

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _strongest_by_entity(
        relationships: list[Relationship],
    ) -> dict[str, Relationship]:
        """The association an analyst would judge each entity on.

        A confirmed verdict outranks any score: once someone has reviewed a
        relationship, that is the one the row should report, even if an
        unreviewed edge happens to score higher.
        """
        best: dict[str, Relationship] = {}
        for relationship in relationships:
            for entity_id in (
                relationship.source_entity_id,
                relationship.target_entity_id,
            ):
                current = best.get(entity_id)
                if current is None or _outranks(relationship, current):
                    best[entity_id] = relationship
        return best

    @staticmethod
    def _row(
        entity: Entity,
        platform: str,
        categories: dict[str, str],
        best: dict[str, Relationship],
        issues: dict[str, tuple[str, str]],
    ) -> SourceResult:
        relationship = best.get(entity.id)
        reason = detail = None
        if not entity.resolved and platform in issues:
            reason, detail = issues[platform]

        return SourceResult(
            platform=platform,
            platform_name=platform_label(platform),
            category=categories.get(platform, "social"),
            # An entity node exists, so *something* pointed at this account
            # even though it was not read. That reference is the fallback
            # story when the source simply had nothing to show; a refusal is
            # still reported as a refusal, because a referenced account behind
            # a login wall is a finding an analyst will want to chase.
            outcome=(
                SourceOutcome.FOUND
                if entity.resolved
                else SourceOutcome.UNAVAILABLE
                if reason and reason not in ANSWERED_EMPTY_REASONS
                else SourceOutcome.REFERENCED_ONLY
            ),
            entity=EntitySummary.model_validate(entity),
            identifier=entity.identifier,
            display_name=entity.display_name,
            url=entity.url,
            confidence=relationship.confidence_level if relationship else None,
            score=relationship.confidence_score if relationship else None,
            analyst_status=relationship.analyst_status if relationship else None,
            relationship_id=relationship.id if relationship else None,
            evidence_count=len(relationship.evidence) if relationship else 0,
            contradiction_count=(
                sum(1 for item in relationship.evidence if not item.supports)
                if relationship
                else 0
            ),
            reason=reason,
            detail=detail,
        )


def _outcome_for_reason(reason: str | None) -> SourceOutcome:
    """Whether a failed lookup was an answer or a refusal.

    A 404 is an answer: the handle is not on that platform, and that closes a
    line of enquiry. A block, a login wall or a rate limit is not an answer -
    the question is still open and an analyst may want to ask it another way.
    """
    if reason and reason in ANSWERED_EMPTY_REASONS:
        return SourceOutcome.NOT_FOUND
    return SourceOutcome.UNAVAILABLE


def _outranks(candidate: Relationship, current: Relationship) -> bool:
    """Whether one relationship should represent an entity over another."""
    reviewed = {AnalystStatus.CONFIRMED, AnalystStatus.REJECTED}
    candidate_reviewed = str(candidate.analyst_status) in reviewed
    current_reviewed = str(current.analyst_status) in reviewed
    if candidate_reviewed != current_reviewed:
        return candidate_reviewed
    return candidate.confidence_score > current.confidence_score
