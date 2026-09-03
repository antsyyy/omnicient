"""Investigation endpoints: create, list, read, crawl, graph and export."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db, session_scope
from ..models.entity import Entity
from ..models.enums import EntityType
from ..models.investigation import CrawlEvent, Investigation
from ..models.relationship import Relationship
from ..schemas.entity import EntityRead
from ..schemas.graph import GraphResponse
from ..schemas.investigation import (
    CrawlEventRead,
    CrawlRequest,
    CrawlResult,
    InvestigationCreate,
    InvestigationDetail,
    InvestigationExport,
    InvestigationRead,
)
from ..schemas.relationship import RelationshipRead
from ..services.graph import GraphService
from ..services.investigation import InvestigationService
from ..utils.logging import get_logger
from ..utils.normalization import NormalizationError

logger = get_logger(__name__)

router = APIRouter(prefix="/investigations", tags=["investigations"])


def _get_investigation(db: Session, investigation_id: str) -> Investigation:
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return investigation


async def _run_in_background(investigation_id: str) -> None:
    """Run discovery for an investigation in its own database session."""
    with session_scope() as db:
        investigation = db.get(Investigation, investigation_id)
        if investigation is None:  # pragma: no cover - deleted mid-flight
            return
        await InvestigationService(db).run(investigation)


@router.post(
    "",
    response_model=InvestigationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an investigation",
)
def create_investigation(
    payload: InvestigationCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> InvestigationRead:
    """Create an investigation and, by default, start discovery in the background.

    The response returns immediately so the client can show crawl progress;
    poll ``GET /api/investigations/{id}`` until the status leaves ``CRAWLING``.
    """
    service = InvestigationService(db)
    try:
        investigation = service.create(payload)
    except NormalizationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if payload.auto_crawl:
        background.add_task(_run_in_background, investigation.id)
    return service.to_read(investigation)


@router.get("", response_model=list[InvestigationRead], summary="List investigations")
def list_investigations(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[InvestigationRead]:
    """Most recent investigations first, with their headline counts."""
    investigations = list(
        db.scalars(
            select(Investigation)
            .order_by(Investigation.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    service = InvestigationService(db)
    return [service.to_read(investigation) for investigation in investigations]


@router.get(
    "/{investigation_id}",
    response_model=InvestigationDetail,
    summary="Read one investigation",
)
def read_investigation(
    investigation_id: str, db: Session = Depends(get_db)
) -> InvestigationDetail:
    """An investigation with its activity timeline and any source failures."""
    investigation = _get_investigation(db, investigation_id)
    service = InvestigationService(db)
    events = list(
        db.scalars(
            select(CrawlEvent)
            .where(CrawlEvent.investigation_id == investigation_id)
            .order_by(CrawlEvent.timestamp, CrawlEvent.id)
        )
    )
    seed = service.seed_entity(investigation_id)
    base = service.to_read(investigation)
    return InvestigationDetail(
        **base.model_dump(),
        seed_entity_id=seed.id if seed else None,
        events=[CrawlEventRead.model_validate(event) for event in events],
        issues=service.issues(investigation_id),
    )


@router.delete(
    "/{investigation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an investigation",
)
def delete_investigation(investigation_id: str, db: Session = Depends(get_db)) -> None:
    """Delete an investigation and everything discovered for it."""
    investigation = _get_investigation(db, investigation_id)
    db.delete(investigation)
    db.commit()


@router.post(
    "/{investigation_id}/crawl",
    response_model=CrawlResult,
    summary="Run discovery and correlation",
)
async def crawl_investigation(
    investigation_id: str,
    payload: CrawlRequest | None = None,
    db: Session = Depends(get_db),
) -> CrawlResult:
    """Run (or re-run) discovery synchronously and return what it produced."""
    investigation = _get_investigation(db, investigation_id)
    options = payload or CrawlRequest()
    service = InvestigationService(db)
    summary = await service.run(
        investigation,
        max_depth=options.max_depth,
        max_pages=options.max_pages,
        reset=options.reset,
    )
    return CrawlResult(
        investigation=service.to_read(investigation),
        entities_discovered=summary.entities,
        relationships_created=summary.relationships,
        evidence_items=summary.evidence,
        pages_fetched=summary.pages_fetched,
        issues=summary.issues,
    )


@router.get(
    "/{investigation_id}/entities",
    response_model=list[EntityRead],
    summary="List discovered entities",
)
def list_entities(
    investigation_id: str,
    db: Session = Depends(get_db),
    entity_type: EntityType | None = Query(default=None, alias="type"),
) -> list[EntityRead]:
    """Every entity discovered for an investigation, shallowest first."""
    _get_investigation(db, investigation_id)
    query = select(Entity).where(Entity.investigation_id == investigation_id)
    if entity_type is not None:
        query = query.where(Entity.type == str(entity_type))
    entities = db.scalars(query.order_by(Entity.depth, Entity.created_at))
    return [EntityRead.model_validate(entity) for entity in entities]


@router.get(
    "/{investigation_id}/relationships",
    response_model=list[RelationshipRead],
    summary="List relationships",
)
def list_relationships(
    investigation_id: str,
    db: Session = Depends(get_db),
    min_score: float = Query(default=0.0, ge=0, le=100),
) -> list[RelationshipRead]:
    """Relationships for an investigation, strongest first."""
    _get_investigation(db, investigation_id)
    relationships = db.scalars(
        select(Relationship)
        .where(
            Relationship.investigation_id == investigation_id,
            Relationship.confidence_score >= min_score,
        )
        .order_by(Relationship.confidence_score.desc())
    )
    return [
        RelationshipRead.model_validate(relationship) for relationship in relationships
    ]


@router.get(
    "/{investigation_id}/graph",
    response_model=GraphResponse,
    summary="Investigation graph",
)
def read_graph(investigation_id: str, db: Session = Depends(get_db)) -> GraphResponse:
    """Nodes, edges, layout hints and statistics for the investigation graph."""
    investigation = _get_investigation(db, investigation_id)
    return GraphService(db).build(investigation)


@router.get(
    "/{investigation_id}/events",
    response_model=list[CrawlEventRead],
    summary="Investigation timeline",
)
def list_events(
    investigation_id: str,
    db: Session = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[CrawlEventRead]:
    """The persisted crawl timeline, oldest first."""
    _get_investigation(db, investigation_id)
    events = db.scalars(
        select(CrawlEvent)
        .where(CrawlEvent.investigation_id == investigation_id)
        .order_by(CrawlEvent.timestamp, CrawlEvent.id)
        .limit(limit)
    )
    return [CrawlEventRead.model_validate(event) for event in events]


@router.get(
    "/{investigation_id}/export",
    response_model=InvestigationExport,
    summary="Export an investigation as JSON",
)
def export_investigation(
    investigation_id: str,
    db: Session = Depends(get_db),
    download: bool = Query(default=False),
) -> InvestigationExport | JSONResponse:
    """Full JSON export: entities, relationships, evidence and timeline."""
    investigation = _get_investigation(db, investigation_id)
    export = InvestigationService(db).export(investigation)
    if not download:
        return export
    filename = f"investigation-{investigation.seed_identifier}-{investigation.id[:8]}.json"
    return JSONResponse(
        content=export.model_dump(mode="json"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{investigation_id}/summary",
    summary="Counts used by the dashboard",
    response_model=dict,
)
def investigation_summary(
    investigation_id: str, db: Session = Depends(get_db)
) -> dict:
    """Entity/relationship/evidence counts plus per-status breakdown."""
    _get_investigation(db, investigation_id)
    rows = db.execute(
        select(Relationship.analyst_status, func.count(Relationship.id))
        .where(Relationship.investigation_id == investigation_id)
        .group_by(Relationship.analyst_status)
    ).all()
    entities, relationships, evidence = InvestigationService(db).counts(investigation_id)
    return {
        "entities": entities,
        "relationships": relationships,
        "evidence": evidence,
        "analyst_status": {row[0]: row[1] for row in rows},
    }
