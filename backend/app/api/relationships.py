"""Relationship endpoints, including the analyst's confirm/reject workflow."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.enums import AnalystStatus
from ..models.relationship import Relationship
from ..schemas.entity import EntitySummary
from ..schemas.evidence import EvidenceRead
from ..schemas.relationship import AnalystDecision, RelationshipDetail
from ..utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/relationships", tags=["relationships"])


def _get_relationship(db: Session, relationship_id: str) -> Relationship:
    relationship = db.get(Relationship, relationship_id)
    if relationship is None:
        raise HTTPException(status_code=404, detail="Relationship not found")
    return relationship


def _detail(relationship: Relationship) -> RelationshipDetail:
    """Serialize a relationship with both endpoints and all evidence."""
    detail = RelationshipDetail.model_validate(relationship)
    return detail.model_copy(
        update={
            "source_entity": EntitySummary.model_validate(relationship.source_entity),
            "target_entity": EntitySummary.model_validate(relationship.target_entity),
            "evidence": [
                EvidenceRead.model_validate(item) for item in relationship.evidence
            ],
        }
    )


@router.get(
    "/{relationship_id}",
    response_model=RelationshipDetail,
    summary="Read one relationship",
)
def read_relationship(
    relationship_id: str, db: Session = Depends(get_db)
) -> RelationshipDetail:
    """A relationship with its endpoints, evidence and contradictions."""
    return _detail(_get_relationship(db, relationship_id))


def _decide(
    db: Session,
    relationship_id: str,
    verdict: AnalystStatus,
    decision: AnalystDecision | None,
) -> RelationshipDetail:
    relationship = _get_relationship(db, relationship_id)
    relationship.analyst_status = verdict
    if decision is not None and decision.note is not None:
        relationship.analyst_note = decision.note
    db.commit()
    db.refresh(relationship)
    logger.info(
        "analyst_decision relationship=%s verdict=%s", relationship_id, verdict
    )
    return _detail(relationship)


@router.post(
    "/{relationship_id}/confirm",
    response_model=RelationshipDetail,
    summary="Confirm that the evidence supports this relationship",
)
def confirm_relationship(
    relationship_id: str,
    decision: AnalystDecision | None = None,
    db: Session = Depends(get_db),
) -> RelationshipDetail:
    """Record that an analyst reviewed the evidence and found it supportive.

    This is a judgement about the *evidence*, not a claim that two accounts
    belong to the same person.
    """
    return _decide(db, relationship_id, AnalystStatus.CONFIRMED, decision)


@router.post(
    "/{relationship_id}/reject",
    response_model=RelationshipDetail,
    summary="Reject this relationship as a false positive",
)
def reject_relationship(
    relationship_id: str,
    decision: AnalystDecision | None = None,
    db: Session = Depends(get_db),
) -> RelationshipDetail:
    """Record that an analyst judged this relationship unsupported."""
    return _decide(db, relationship_id, AnalystStatus.REJECTED, decision)


@router.post(
    "/{relationship_id}/reset",
    response_model=RelationshipDetail,
    summary="Return a relationship to UNREVIEWED",
)
def reset_relationship(
    relationship_id: str, db: Session = Depends(get_db)
) -> RelationshipDetail:
    """Undo a confirm/reject decision."""
    return _decide(db, relationship_id, AnalystStatus.UNREVIEWED, None)
