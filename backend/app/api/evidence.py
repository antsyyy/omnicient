"""Evidence endpoints.

Evidence is read through the relationship it explains, which is how the
interface presents it: a relationship is never shown without the observations
that produced its score.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.evidence import Evidence
from ..models.relationship import Relationship
from ..schemas.evidence import EvidenceBundle, EvidenceRead

router = APIRouter(tags=["evidence"])


@router.get(
    "/relationships/{relationship_id}/evidence",
    response_model=EvidenceBundle,
    summary="Evidence behind a relationship",
)
def relationship_evidence(
    relationship_id: str, db: Session = Depends(get_db)
) -> EvidenceBundle:
    """Supporting and contradicting evidence, separated for display."""
    relationship = db.get(Relationship, relationship_id)
    if relationship is None:
        raise HTTPException(status_code=404, detail="Relationship not found")
    items = [EvidenceRead.model_validate(item) for item in relationship.evidence]
    return EvidenceBundle(
        relationship_id=relationship_id,
        supporting=[item for item in items if item.supports],
        contradicting=[item for item in items if not item.supports],
    )


@router.get(
    "/evidence/{evidence_id}",
    response_model=EvidenceRead,
    summary="Read one evidence item",
)
def read_evidence(evidence_id: str, db: Session = Depends(get_db)) -> EvidenceRead:
    """A single observation, with the URL it was collected from."""
    item = db.get(Evidence, evidence_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return EvidenceRead.model_validate(item)


@router.get(
    "/investigations/{investigation_id}/evidence",
    response_model=list[EvidenceRead],
    summary="All evidence for an investigation",
)
def investigation_evidence(
    investigation_id: str, db: Session = Depends(get_db)
) -> list[EvidenceRead]:
    """Every observation collected during an investigation, oldest first."""
    items = db.scalars(
        select(Evidence)
        .where(Evidence.investigation_id == investigation_id)
        .order_by(Evidence.collected_at)
    )
    return [EvidenceRead.model_validate(item) for item in items]
