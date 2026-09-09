"""Relationship endpoints, including the analyst's confirm/reject workflow."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..database import get_repository
from ..models.enums import AnalystStatus
from ..models.relationship import Relationship
from ..repository import Neo4jRepository
from ..schemas.entity import EntitySummary
from ..schemas.evidence import EvidenceRead
from ..schemas.relationship import AnalystDecision, RelationshipDetail
from ..utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/relationships", tags=["relationships"])


def _get_relationship(repo: Neo4jRepository, relationship_id: str) -> Relationship:
    relationship = repo.get_relationship(relationship_id)
    if relationship is None:
        raise HTTPException(status_code=404, detail="Relationship not found")
    return relationship


def _detail(
    repo: Neo4jRepository, relationship: Relationship
) -> RelationshipDetail:
    """Serialize a relationship with both endpoints and all evidence."""
    relationship.evidence = repo.evidence_for_relationship(relationship.id)
    source = repo.get_entity(relationship.source_entity_id)
    target = repo.get_entity(relationship.target_entity_id)
    detail = RelationshipDetail.model_validate(relationship)
    return detail.model_copy(
        update={
            "source_entity": EntitySummary.model_validate(source) if source else None,
            "target_entity": EntitySummary.model_validate(target) if target else None,
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
    relationship_id: str, repo: Neo4jRepository = Depends(get_repository)
) -> RelationshipDetail:
    """A relationship with its endpoints, evidence and contradictions."""
    return _detail(repo, _get_relationship(repo, relationship_id))


def _decide(
    repo: Neo4jRepository,
    relationship_id: str,
    verdict: AnalystStatus,
    decision: AnalystDecision | None,
) -> RelationshipDetail:
    _get_relationship(repo, relationship_id)
    note = decision.note if decision is not None else None
    relationship = repo.set_analyst_status(relationship_id, str(verdict), note)
    if relationship is None:  # pragma: no cover - deleted mid-flight
        raise HTTPException(status_code=404, detail="Relationship not found")
    logger.info(
        "analyst_decision relationship=%s verdict=%s", relationship_id, verdict
    )
    return _detail(repo, relationship)


@router.post(
    "/{relationship_id}/confirm",
    response_model=RelationshipDetail,
    summary="Confirm that the evidence supports this relationship",
)
def confirm_relationship(
    relationship_id: str,
    decision: AnalystDecision | None = None,
    repo: Neo4jRepository = Depends(get_repository),
) -> RelationshipDetail:
    """Record that an analyst reviewed the evidence and found it supportive.

    This is a judgement about the *evidence*, not a claim that two accounts
    belong to the same person.
    """
    return _decide(repo, relationship_id, AnalystStatus.CONFIRMED, decision)


@router.post(
    "/{relationship_id}/reject",
    response_model=RelationshipDetail,
    summary="Reject this relationship as a false positive",
)
def reject_relationship(
    relationship_id: str,
    decision: AnalystDecision | None = None,
    repo: Neo4jRepository = Depends(get_repository),
) -> RelationshipDetail:
    """Record that an analyst judged this relationship unsupported."""
    return _decide(repo, relationship_id, AnalystStatus.REJECTED, decision)


@router.post(
    "/{relationship_id}/reset",
    response_model=RelationshipDetail,
    summary="Return a relationship to UNREVIEWED",
)
def reset_relationship(
    relationship_id: str, repo: Neo4jRepository = Depends(get_repository)
) -> RelationshipDetail:
    """Undo a confirm/reject decision."""
    return _decide(repo, relationship_id, AnalystStatus.UNREVIEWED, None)
