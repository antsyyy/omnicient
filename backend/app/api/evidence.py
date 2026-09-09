"""Evidence endpoints.

Evidence is read through the relationship it explains, which is how the
interface presents it: a relationship is never shown without the observations
that produced its score.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..database import get_repository
from ..repository import Neo4jRepository
from ..schemas.evidence import EvidenceBundle, EvidenceRead

router = APIRouter(tags=["evidence"])


@router.get(
    "/relationships/{relationship_id}/evidence",
    response_model=EvidenceBundle,
    summary="Evidence behind a relationship",
)
def relationship_evidence(
    relationship_id: str, repo: Neo4jRepository = Depends(get_repository)
) -> EvidenceBundle:
    """Supporting and contradicting evidence, separated for display."""
    if repo.get_relationship(relationship_id) is None:
        raise HTTPException(status_code=404, detail="Relationship not found")
    items = [
        EvidenceRead.model_validate(item)
        for item in repo.evidence_for_relationship(relationship_id)
    ]
    return EvidenceBundle(
        relationship_id=relationship_id,
        supporting=[item for item in items if item.stance == "SUPPORTING"],
        contradicting=[item for item in items if item.stance == "CONTRADICTORY"],
        # Observed and recorded, but it moved the score by nothing. Shown
        # rather than dropped: "we looked and it changed nothing" is itself
        # a finding an analyst may want.
        neutral=[item for item in items if item.stance == "NEUTRAL"],
    )


@router.get(
    "/evidence/{evidence_id}",
    response_model=EvidenceRead,
    summary="Read one evidence item",
)
def read_evidence(
    evidence_id: str, repo: Neo4jRepository = Depends(get_repository)
) -> EvidenceRead:
    """A single observation, with the URL it was collected from."""
    item = repo.get_evidence(evidence_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return EvidenceRead.model_validate(item)


@router.get(
    "/investigations/{investigation_id}/evidence",
    response_model=list[EvidenceRead],
    summary="All evidence for an investigation",
)
def investigation_evidence(
    investigation_id: str, repo: Neo4jRepository = Depends(get_repository)
) -> list[EvidenceRead]:
    """Every observation collected during an investigation, oldest first."""
    return [
        EvidenceRead.model_validate(item)
        for item in repo.list_evidence(investigation_id)
    ]
