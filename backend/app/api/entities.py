"""Entity endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..database import get_repository
from ..models.entity import Entity
from ..repository import Neo4jRepository
from ..schemas.entity import EntityDetail, SnapshotRead
from ..schemas.relationship import RelationshipRead

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
