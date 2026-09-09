"""Relationship path explorer: how are these two entities connected?

The graph already knows; the job here is to ask it within strict bounds and
then order the answers so the useful route is first.

Ranking is deterministic and stated openly, because "why is this path above
that one?" has to have an answer:

* a rejected step disqualifies a route outright - the analyst already said no
* fewer contradictions beat more
* shorter beats longer, since every hop is another inference
* confirmed steps beat unreviewed ones
* stronger evidence beats weaker

No learned model and no LLM: the same graph produces the same ordering.
"""

from __future__ import annotations

from ..config import Settings, get_settings
from ..models.entity import Entity
from ..models.enums import RELATIONSHIP_LABELS, AnalystStatus
from ..models.investigation import Investigation
from ..repository import Neo4jRepository
from ..schemas.entity import EntitySummary
from ..schemas.path import PathResponse, PathStep, RelationshipPath
from ..utils.logging import get_logger

logger = get_logger(__name__)

#: Ranking weights.  Kept here rather than in the query so the ordering can be
#: explained, tested and retuned without touching Cypher.
LENGTH_PENALTY = 12.0
CONTRADICTION_PENALTY = 30.0
CONFIRMED_BONUS = 15.0
#: Applied to evidence *per hop*, not to the total.  Summing rewards length -
#: a longer route accumulates evidence simply by having more steps, which is
#: how a two-hop route ends up outranking the direct connection it detours
#: around.
EVIDENCE_BONUS = 1.5


class PathNotFoundError(ValueError):
    """One of the requested entities is not part of this investigation."""


class PathService:
    """Finds and ranks routes between two entities."""

    def __init__(
        self, repo: Neo4jRepository, settings: Settings | None = None
    ) -> None:
        self.repo = repo
        self.settings = settings or get_settings()

    def find(
        self,
        investigation: Investigation,
        source_entity_id: str,
        target_entity_id: str,
        *,
        max_depth: int | None = None,
        max_paths: int | None = None,
    ) -> PathResponse:
        """Ranked routes between two entities, bounded on both axes."""
        depth = self._clamp(
            max_depth or self.settings.path_max_depth,
            1,
            self.settings.path_depth_ceiling,
        )
        limit = self._clamp(
            max_paths or self.settings.path_max_paths,
            1,
            self.settings.path_result_ceiling,
        )

        entities = {
            entity.id: entity
            for entity in self.repo.list_entities(investigation.id)
        }
        source = entities.get(source_entity_id)
        target = entities.get(target_entity_id)
        if source is None or target is None:
            # Scoping the lookup to this investigation is what stops one
            # investigation being used to probe another.
            raise PathNotFoundError(
                "Both entities must belong to this investigation."
            )
        if source_entity_id == target_entity_id:
            raise PathNotFoundError(
                "Choose two different entities to explore the route between them."
            )

        rows = self.repo.find_paths(
            investigation.id,
            source_entity_id,
            target_entity_id,
            max_depth=depth,
            max_paths=limit,
        )
        relationships = {
            relationship.id: relationship
            for relationship in self.repo.attach_evidence(
                self.repo.list_relationships(investigation.id)
            )
        }

        paths = [
            path
            for row in rows
            if (path := self._build(row, entities, relationships)) is not None
        ]
        paths = self._deduplicate(paths)
        paths.sort(key=lambda item: (-item.strength_score, item.length))
        for position, path in enumerate(paths[:limit], start=1):
            path.rank = position

        logger.info(
            "paths_found investigation=%s source=%s target=%s depth=%d found=%d",
            investigation.id,
            source_entity_id,
            target_entity_id,
            depth,
            len(paths),
        )
        return PathResponse(
            investigation_id=investigation.id,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            source_entity=EntitySummary.model_validate(source),
            target_entity=EntitySummary.model_validate(target),
            max_depth=depth,
            max_paths=limit,
            paths=paths[:limit],
        )

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _clamp(value: int, low: int, high: int) -> int:
        return max(low, min(int(value), high))

    @staticmethod
    def _deduplicate(paths: list[RelationshipPath]) -> list[RelationshipPath]:
        """Collapse routes an analyst would read as the same one.

        Parallel edges of the same type between the same entities produce
        several rows that traverse identical nodes for identical reasons; only
        the strongest is worth showing. Routes through the same entities by
        *different* relationship types are kept, because the reason differs.
        """
        best: dict[tuple, RelationshipPath] = {}
        for path in paths:
            key = (tuple(path.node_ids), tuple(path.relationship_types))
            existing = best.get(key)
            if existing is None or path.strength_score > existing.strength_score:
                best[key] = path
        return list(best.values())

    def _build(
        self,
        row: dict,
        entities: dict[str, Entity],
        relationships: dict,
    ) -> RelationshipPath | None:
        """Turn one Cypher row into a ranked, displayable path."""
        node_ids: list[str] = list(row.get("node_ids") or [])
        relationship_ids: list[str] = list(row.get("relationship_ids") or [])
        if len(node_ids) < 2 or len(relationship_ids) != len(node_ids) - 1:
            return None  # pragma: no cover - defensive

        start = entities.get(node_ids[0])
        if start is None:  # pragma: no cover - defensive
            return None

        steps: list[PathStep] = []
        total_evidence = 0
        contradictions = 0
        confirmed = 0
        rejected = 0

        for index, relationship_id in enumerate(relationship_ids):
            relationship = relationships.get(relationship_id)
            reached = entities.get(node_ids[index + 1])
            if relationship is None or reached is None:  # pragma: no cover
                return None

            evidence_count = len(relationship.evidence)
            total_evidence += evidence_count
            status = str(relationship.analyst_status)
            if status == AnalystStatus.CONFIRMED:
                confirmed += 1
            elif status == AnalystStatus.REJECTED:
                rejected += 1
            contradictions += sum(
                1 for item in relationship.evidence if not item.supports
            )

            steps.append(
                PathStep(
                    relationship_id=relationship.id,
                    relationship_type=relationship.relationship_type,
                    relationship_label=RELATIONSHIP_LABELS.get(
                        str(relationship.relationship_type),
                        str(relationship.relationship_type),
                    ),
                    confidence_score=relationship.confidence_score,
                    confidence_level=relationship.confidence_level,
                    analyst_status=relationship.analyst_status,
                    evidence_count=evidence_count,
                    # The stored edge may point the other way; the route still
                    # traverses it, and the direction is worth showing.
                    reversed=relationship.source_entity_id != node_ids[index],
                    entity=EntitySummary.model_validate(reached),
                )
            )

        score = self._strength(
            steps=steps,
            contradictions=contradictions,
            confirmed=confirmed,
            rejected=rejected,
            total_evidence=total_evidence,
        )
        return RelationshipPath(
            rank=0,
            length=len(steps),
            start=EntitySummary.model_validate(start),
            steps=steps,
            strength_score=score,
            strength=self._band(score, rejected),
            total_evidence=total_evidence,
            contradictions=contradictions,
            confirmed_steps=confirmed,
            rejected_steps=rejected,
            node_ids=node_ids,
            relationship_ids=relationship_ids,
        )

    @staticmethod
    def _strength(
        *,
        steps: list[PathStep],
        contradictions: int,
        confirmed: int,
        rejected: int,
        total_evidence: int,
    ) -> float:
        """Deterministic ranking score for one route.

        A route is only as good as its weakest link, so the mean step score is
        pulled toward the minimum rather than averaging a weak hop away.
        """
        if not steps:
            return 0.0
        scores = [step.confidence_score for step in steps]
        weakest = min(scores)
        mean = sum(scores) / len(scores)
        base = (weakest * 0.6) + (mean * 0.4)

        base -= LENGTH_PENALTY * (len(steps) - 1)
        base -= CONTRADICTION_PENALTY * contradictions
        base += CONFIRMED_BONUS * confirmed
        base += EVIDENCE_BONUS * (total_evidence / len(steps))
        if rejected:
            # An analyst already rejected a hop on this route; it should never
            # outrank a route they have not dismissed.
            base -= 1000.0
        return round(base, 2)

    @staticmethod
    def _band(score: float, rejected: int) -> str:
        if rejected:
            return "REJECTED"
        if score >= 70:
            return "STRONG"
        if score >= 40:
            return "MODERATE"
        return "WEAK"
