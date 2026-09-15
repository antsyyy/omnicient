"""Entity endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..database import get_repository
from ..models.entity import Entity
from ..models.enums import EntityVerdict
from ..repository import Neo4jRepository
from ..schemas.entity import EntityDetail, EntityIdentityDecision, SnapshotRead
from ..schemas.relationship import RelationshipRead
from ..utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/entities", tags=["entities"])


def _get_entity(repo: Neo4jRepository, entity_id: str) -> Entity:
    entity = repo.get_entity(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


@router.get("/{entity_id}", response_model=EntityDetail, summary="Read one entity")
def read_entity(
    entity_id: str, repo: Neo4jRepository = Depends(get_repository)
) -> EntityDetail:
    """An entity with the observation history recorded for it."""
    entity = _get_entity(repo, entity_id)
    detail = EntityDetail.model_validate(entity)
    return detail.model_copy(
        update={
            "snapshots": [
                SnapshotRead.model_validate(snapshot)
                for snapshot in repo.snapshots_for_entity(entity_id)
            ]
        }
    )


@router.get(
    "/{entity_id}/relationships",
    response_model=list[RelationshipRead],
    summary="Relationships touching an entity",
)
def entity_relationships(
    entity_id: str, repo: Neo4jRepository = Depends(get_repository)
) -> list[RelationshipRead]:
    """Every relationship with this entity at either end - "expand connections"."""
    _get_entity(repo, entity_id)
    relationships = repo.attach_evidence(repo.relationships_for_entity(entity_id))
    return [
        RelationshipRead.model_validate(relationship) for relationship in relationships
    ]


@router.get(
    "/{entity_id}/snapshots",
    response_model=list[SnapshotRead],
    summary="Observation history for an entity",
)
def entity_snapshots(
    entity_id: str, repo: Neo4jRepository = Depends(get_repository)
) -> list[SnapshotRead]:
    """Point-in-time copies of this entity's public fields (section 28)."""
    _get_entity(repo, entity_id)
    return [
        SnapshotRead.model_validate(snapshot)
        for snapshot in repo.snapshots_for_entity(entity_id)
    ]


def _rule(
    repo: Neo4jRepository,
    entity_id: str,
    verdict: EntityVerdict,
    note: str | None,
) -> EntityDetail:
    entity = _get_entity(repo, entity_id)
    if entity.is_seed and verdict is EntityVerdict.DIFFERENT_IDENTITY:
        # The seed is the subject of the investigation, not a finding in it.
        # Ruling it out would leave an investigation of nobody, with every
        # other entity still hanging off it.
        raise HTTPException(
            status_code=409,
            detail=(
                "The seed is what the investigation is about and cannot be "
                "ruled out. Start a new investigation instead."
            ),
        )

    updated = repo.set_entity_verdict(entity_id, str(verdict), note)
    if updated is None:  # pragma: no cover - deleted mid-flight
        raise HTTPException(status_code=404, detail="Entity not found")
    logger.info("entity_verdict entity=%s verdict=%s", entity_id, verdict)
    return EntityDetail.model_validate(updated)


@router.post(
    "/{entity_id}/different-identity",
    response_model=EntityDetail,
    summary="Mark this entity as a different party",
)
def mark_different_identity(
    entity_id: str,
    decision: EntityIdentityDecision | None = None,
    repo: Neo4jRepository = Depends(get_repository),
) -> EntityDetail:
    """Record that an analyst judged this account to belong to somebody else.

    A namesake, a reused handle, a coincidence the evidence happened to
    surface. This is an analyst's assertion and is stored as one - the engine
    never sets it, and it is the only identity claim the system records.

    Nothing is deleted. The observations remain, the evidence stays readable
    and the relationships keep their own verdicts, because the analyst may be
    wrong and a later reviewer has to be able to see what was ruled out and
    why. The canvas draws it struck through rather than removing it, and a
    filter hides it for anyone who wants it out of the way.
    """
    return _rule(
        repo,
        entity_id,
        EntityVerdict.DIFFERENT_IDENTITY,
        decision.note if decision else None,
    )


@router.post(
    "/{entity_id}/reset-identity",
    response_model=EntityDetail,
    summary="Undo a different-identity ruling",
)
def reset_identity(
    entity_id: str, repo: Neo4jRepository = Depends(get_repository)
) -> EntityDetail:
    """Return an entity to UNREVIEWED, keeping the note that explained it."""
    return _rule(repo, entity_id, EntityVerdict.UNREVIEWED, None)
