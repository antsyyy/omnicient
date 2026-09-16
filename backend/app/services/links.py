"""Links an analyst draws by hand.

Omnicient's whole claim is that every association it shows can be traced back
to something observed.  A manual link is the one exception, so it is handled
as an exception rather than smuggled in alongside the engine's findings: it is
stamped with its origin, it carries the analyst's stated reason as its
provenance, it scores nothing, and it is the only kind of relationship the API
will delete.

Why allow it at all.  Investigators know things the crawler cannot reach - a
court filing, a conversation, an archived page that no longer resolves.
Forcing that knowledge out of the tool does not make the investigation more
rigorous; it just means the reasoning lives in someone's notes where nobody
can audit it.  Recording it *as an assertion*, clearly separated from observed
evidence, is the honest way to hold both.
"""

from __future__ import annotations

from ..models.entity import Entity
from ..models.enums import (
    AnalystStatus,
    ConfidenceLevel,
    EvidenceType,
    RelationshipOrigin,
)
from ..models.evidence import Evidence
from ..models.investigation import Investigation
from ..models.relationship import Relationship
from ..repository import Neo4jRepository
from ..schemas.relationship import ANALYST_LINKABLE_TYPES, ManualLinkCreate
from ..utils.logging import get_logger

logger = get_logger(__name__)


class LinkError(Exception):
    """A manual link the API should refuse, with an analyst-facing reason."""

    def __init__(self, message: str, *, conflict: bool = False) -> None:
        super().__init__(message)
        self.message = message
        #: True when the request clashes with something that already exists,
        #: which the API reports as 409 rather than 400.
        self.conflict = conflict


class LinkService:
    """Creates and removes analyst-asserted links."""

    def __init__(self, repo: Neo4jRepository) -> None:
        self.repo = repo

    def create(
        self, investigation: Investigation, request: ManualLinkCreate
    ) -> Relationship:
        """Draw a link between two entities on the analyst's authority."""
        if request.relationship_type not in ANALYST_LINKABLE_TYPES:
            allowed = ", ".join(str(t) for t in ANALYST_LINKABLE_TYPES)
            raise LinkError(
                f"{request.relationship_type} names an observation the engine "
                f"makes, so it cannot be asserted by hand. Use one of: {allowed}."
            )

        if request.source_entity_id == request.target_entity_id:
            raise LinkError("An entity cannot be linked to itself.")

        source = self._entity(investigation, request.source_entity_id, "source")
        target = self._entity(investigation, request.target_entity_id, "target")

        # MERGE would quietly fold a manual link onto an existing edge of the
        # same type and overwrite the score the engine derived for it. An
        # analyst who wants to endorse that edge should confirm it, which is a
        # different and more honest action than re-drawing it.
        for existing in self.repo.relationships_for_entity(source.id):
            same_pair = {existing.source_entity_id, existing.target_entity_id} == {
                source.id,
                target.id,
            }
            if same_pair and str(existing.relationship_type) == str(
                request.relationship_type
            ):
                raise LinkError(
                    f"{source.name} and {target.name} are already connected by "
                    f"a {request.relationship_type} relationship. Confirm or "
                    f"reject that one rather than drawing a second.",
                    conflict=True,
                )

        relationship = Relationship(
            investigation_id=investigation.id,
            source_entity_id=source.id,
            target_entity_id=target.id,
            relationship_type=str(request.relationship_type),
            # No observation stands behind this, so it scores nothing. The
            # interface reports it as analyst-asserted instead of dressing it
            # in a confidence band it has not earned.
            confidence_score=0.0,
            confidence_level=str(ConfidenceLevel.INSUFFICIENT),
            origin=str(RelationshipOrigin.ANALYST),
            # Drawing a link *is* the analyst's verdict on it.
            analyst_status=str(AnalystStatus.CONFIRMED),
            analyst_note=request.rationale,
            summary=f"Asserted by an analyst: {request.rationale}",
        )
        created = self.repo.create_manual_relationship(relationship)

        # The rationale is the provenance. Zero weight keeps it out of the
        # score while still recording that it was said, by whom, and when -
        # which is exactly what the NEUTRAL stance exists for.
        self.repo.add_evidence(
            [
                Evidence(
                    investigation_id=investigation.id,
                    relationship_id=created.id,
                    source_entity_id=source.id,
                    target_entity_id=target.id,
                    type=str(EvidenceType.ANALYST_ASSERTION),
                    description=request.rationale,
                    extracted_value=None,
                    weight=0.0,
                    supports=True,
                    context={
                        "asserted_by": "analyst",
                        "source_entity": source.name,
                        "target_entity": target.name,
                    },
                )
            ]
        )

        logger.info(
            "manual_link_created investigation=%s type=%s source=%s target=%s",
            investigation.id,
            request.relationship_type,
            source.identifier,
            target.identifier,
        )
        return created

    def delete(self, relationship: Relationship) -> None:
        """Remove an analyst-asserted link.

        Engine-derived edges are never deleted: the evidence behind them was
        genuinely observed, and erasing it would leave the investigation
        unable to explain itself. Disagreeing with one is what REJECTED is
        for.
        """
        if not relationship.is_analyst_asserted:
            raise LinkError(
                "This relationship was derived from observed evidence, so it "
                "cannot be deleted. Reject it instead - that records your "
                "disagreement while keeping the observations intact."
            )
        self.repo.delete_relationship(relationship.id)
        logger.info("manual_link_deleted relationship=%s", relationship.id)

    # -- internals ---------------------------------------------------------

    def _entity(
        self, investigation: Investigation, entity_id: str, role: str
    ) -> Entity:
        entity = self.repo.get_entity(entity_id)
        if entity is None:
            raise LinkError(f"The {role} entity does not exist.")
        if entity.investigation_id != investigation.id:
            raise LinkError(
                f"The {role} entity belongs to a different investigation."
            )
        return entity
