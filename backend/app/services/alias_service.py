"""Reads persisted alias relationships back out of the graph.

:mod:`app.services.alias_detection` is the pure engine - it compares handles
and knows nothing about storage.  This is the thin layer that turns the
``POTENTIAL_ALIAS`` edges written during a run into the API shape, so the
detector stays testable without a database and the API stays free of Cypher.
"""

from __future__ import annotations

from ..models.enums import RelationshipType
from ..models.investigation import Investigation
from ..models.relationship import Relationship
from ..repository import Neo4jRepository
from ..schemas.alias import AliasList, AliasRead, AliasSignalRead
from ..schemas.entity import EntitySummary
from ..schemas.evidence import EvidenceRead
from ..services.alias_detection import (
    TRANSFORMATION_LABEL,
    AliasStrength,
    calculate_username_similarity,
)
from ..utils.logging import get_logger
from ..utils.normalization import identity_key

logger = get_logger(__name__)


class AliasService:
    """Turns stored alias edges into the analyst-facing alias list."""

    def __init__(self, repo: Neo4jRepository) -> None:
        self.repo = repo

    def list_aliases(self, investigation: Investigation) -> AliasList:
        """Every potential alias for an investigation, strongest first.

        One row per pair of *handles*, not per pair of accounts.  An alias is
        a claim about two names - that ``wordpresscom`` and
        ``wordpressdotcom`` might belong to the same party - and that claim is
        the same claim however many platforms happen to carry both. Listing it
        once per platform pairing turned a single finding into twelve
        near-identical rows and buried everything else.
        """
        relationships = self.repo.attach_evidence(
            self.repo.list_relationships_of_type(
                investigation.id, str(RelationshipType.POTENTIAL_ALIAS)
            )
        )
        entities = {
            entity.id: entity for entity in self.repo.list_entities(investigation.id)
        }

        # Strongest first, so the survivor of each handle pair is the best
        # evidenced one rather than whichever happened to be stored first.
        ranked = sorted(
            (
                relationship
                for relationship in relationships
                if relationship.source_entity_id in entities
                and relationship.target_entity_id in entities
            ),
            key=lambda r: -r.confidence_score,
        )

        aliases = []
        seen: set[frozenset[str]] = set()
        for relationship in ranked:
            source = entities[relationship.source_entity_id]
            target = entities[relationship.target_entity_id]
            pair = frozenset(
                {
                    identity_key(source.identifier),
                    identity_key(target.identifier),
                }
            )
            if pair in seen:
                continue
            seen.add(pair)
            aliases.append(
                self._to_read(
                    relationship,
                    entities,
                    # Contradictions sit on the relationship they weaken, not
                    # on the alias edge, so they are read by entity pair.
                    self.repo.evidence_between_entities(
                        investigation.id,
                        relationship.source_entity_id,
                        relationship.target_entity_id,
                    ),
                )
            )
        logger.info(
            "aliases_listed investigation=%s count=%d", investigation.id, len(aliases)
        )
        return AliasList(
            investigation_id=investigation.id,
            primary_identifier=investigation.seed_identifier,
            aliases=aliases,
        )

    @staticmethod
    def _to_read(
        relationship: Relationship,
        entities: dict,
        pair_evidence: list | None = None,
    ) -> AliasRead:
        source = entities[relationship.source_entity_id]
        target = entities[relationship.target_entity_id]

        signals: list[AliasSignalRead] = []
        transformations: list[str] = []
        strength = str(AliasStrength.WEAK)
        for item in relationship.evidence:
            context = item.context or {}
            name = context.get("transformation")
            if name and name not in transformations:
                transformations.append(name)
            if context.get("strength"):
                strength = context["strength"]
            signals.append(
                AliasSignalRead(
                    kind=name or str(item.type),
                    label=TRANSFORMATION_LABEL.get(name or "", str(item.type)),
                    detail=item.description,
                    weight=item.weight,
                )
            )

        return AliasRead(
            relationship_id=relationship.id,
            source_entity_id=source.id,
            target_entity_id=target.id,
            source_entity=EntitySummary.model_validate(source),
            target_entity=EntitySummary.model_validate(target),
            source_identifier=source.identifier,
            target_identifier=target.identifier,
            source_platform=source.platform,
            target_platform=target.platform,
            similarity=calculate_username_similarity(
                source.identifier, target.identifier
            ),
            strength=strength,
            transformations=transformations,
            signals=signals,
            score=relationship.confidence_score,
            confidence=relationship.confidence_level,
            analyst_status=relationship.analyst_status,
            supporting_evidence=[
                EvidenceRead.model_validate(item)
                for item in (pair_evidence or relationship.evidence)
                if item.supports and item.weight > 0
            ],
            contradicting_evidence=[
                EvidenceRead.model_validate(item)
                for item in (pair_evidence or relationship.evidence)
                if not item.supports
            ],
        )
