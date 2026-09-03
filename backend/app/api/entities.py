"""Entity endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.entity import Entity
from ..models.relationship import Relationship
from ..schemas.entity import EntityDetail, SnapshotRead
from ..schemas.relationship import RelationshipRead

router = APIRouter(prefix="/entities", tags=["entities"])


def _get_entity(db: Session, entity_id: str) -> Entity:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


@router.get("/{entity_id}", response_model=EntityDetail, summary="Read one entity")
def read_entity(entity_id: str, db: Session = Depends(get_db)) -> EntityDetail:
    """An entity with the observation history recorded for it."""
    entity = _get_entity(db, entity_id)
    detail = EntityDetail.model_validate(entity)
    return detail.model_copy(
        update={
            "snapshots": [
                SnapshotRead.model_validate(snapshot) for snapshot in entity.snapshots
            ]
        }
    )


@router.get(
    "/{entity_id}/relationships",
    response_model=list[RelationshipRead],
    summary="Relationships touching an entity",
)
def entity_relationships(
    entity_id: str, db: Session = Depends(get_db)
) -> list[RelationshipRead]:
    """Every relationship with this entity at either end - "expand connections"."""
    entity = _get_entity(db, entity_id)
    relationships = db.scalars(
        select(Relationship)
        .where(
            Relationship.investigation_id == entity.investigation_id,
            or_(
                Relationship.source_entity_id == entity.id,
                Relationship.target_entity_id == entity.id,
            ),
        )
        .order_by(Relationship.confidence_score.desc())
    )
    return [
        RelationshipRead.model_validate(relationship) for relationship in relationships
    ]
