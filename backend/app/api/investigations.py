"""Investigation endpoints: create, list, read, crawl, graph and export."""

from __future__ import annotations

from enum import StrEnum

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, PlainTextResponse

from ..database import get_repository, repository_scope
from ..models.enums import EntityType
from ..models.investigation import Investigation
from ..repository import Neo4jRepository
from ..schemas.alias import AliasList
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
from ..schemas.lead import LeadList
from ..schemas.path import PathResponse
from ..schemas.profile import IdentityProfile
from ..schemas.relationship import ManualLinkCreate, RelationshipRead
from ..schemas.results import SourceResults
from ..services.alias_service import AliasService
from ..services.graph import GraphService
from ..services.identity_profile import IdentityProfileService
from ..services.investigation import InvestigationService
from ..services.leads import LeadService
from ..services.links import LinkError, LinkService
from ..services.paths import PathNotFoundError, PathService
from ..services.results import ResultsService
from ..utils.logging import get_logger
from ..utils.normalization import NormalizationError

logger = get_logger(__name__)

router = APIRouter(prefix="/investigations", tags=["investigations"])


class ExportFormat(StrEnum):
    """Supported export formats (section 29)."""

    JSON = "json"
    CSV = "csv"


def _get_investigation(repo: Neo4jRepository, investigation_id: str) -> Investigation:
    investigation = repo.get_investigation(investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return investigation


async def _run_in_background(investigation_id: str) -> None:
    """Run discovery for an investigation on its own database session."""
    with repository_scope() as repo:
        investigation = repo.get_investigation(investigation_id)
        if investigation is None:  # pragma: no cover - deleted mid-flight
            return
        await InvestigationService(repo).run(investigation)


@router.post(
    "",
    response_model=InvestigationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an investigation",
)
def create_investigation(
    payload: InvestigationCreate,
    background: BackgroundTasks,
    repo: Neo4jRepository = Depends(get_repository),
) -> InvestigationRead:
    """Create an investigation and, by default, start discovery in the background.

    The response returns immediately so the client can show crawl progress;
    poll ``GET /api/investigations/{id}`` until the status leaves ``CRAWLING``.
    """
    service = InvestigationService(repo)
    try:
        investigation = service.create(payload)
    except NormalizationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if payload.auto_crawl:
        background.add_task(_run_in_background, investigation.id)
    return service.to_read(investigation)


@router.get("", response_model=list[InvestigationRead], summary="List investigations")
def list_investigations(
    repo: Neo4jRepository = Depends(get_repository),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[InvestigationRead]:
    """Most recent investigations first, with their headline counts."""
    service = InvestigationService(repo)
    return [
        service.to_read(investigation)
        for investigation in repo.list_investigations(limit=limit, offset=offset)
    ]


@router.get(
    "/{investigation_id}",
    response_model=InvestigationDetail,
    summary="Read one investigation",
)
def read_investigation(
    investigation_id: str, repo: Neo4jRepository = Depends(get_repository)
) -> InvestigationDetail:
    """An investigation with its activity timeline and any source failures."""
    investigation = _get_investigation(repo, investigation_id)
    service = InvestigationService(repo)
    events = repo.list_events(investigation_id)
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
def delete_investigation(
    investigation_id: str, repo: Neo4jRepository = Depends(get_repository)
) -> None:
    """Delete an investigation and everything discovered for it."""
    _get_investigation(repo, investigation_id)
    repo.delete_investigation(investigation_id)


@router.post(
    "/{investigation_id}/crawl",
    response_model=CrawlResult,
    summary="Run discovery and correlation",
)
async def crawl_investigation(
    investigation_id: str,
    payload: CrawlRequest | None = None,
    repo: Neo4jRepository = Depends(get_repository),
) -> CrawlResult:
    """Run (or re-run) discovery synchronously and return what it produced."""
    investigation = _get_investigation(repo, investigation_id)
    options = payload or CrawlRequest()
    service = InvestigationService(repo)
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
    repo: Neo4jRepository = Depends(get_repository),
    entity_type: EntityType | None = Query(default=None, alias="type"),
) -> list[EntityRead]:
    """Every entity discovered for an investigation, shallowest first."""
    _get_investigation(repo, investigation_id)
    entities = repo.list_entities(
        investigation_id, str(entity_type) if entity_type else None
    )
    return [EntityRead.model_validate(entity) for entity in entities]


@router.get(
    "/{investigation_id}/relationships",
    response_model=list[RelationshipRead],
    summary="List relationships",
)
def list_relationships(
    investigation_id: str,
    repo: Neo4jRepository = Depends(get_repository),
    min_score: float = Query(default=0.0, ge=0, le=100),
) -> list[RelationshipRead]:
    """Relationships for an investigation, strongest first."""
    _get_investigation(repo, investigation_id)
    relationships = repo.attach_evidence(
        repo.list_relationships(investigation_id, min_score=min_score)
    )
    return [
        RelationshipRead.model_validate(relationship) for relationship in relationships
    ]


@router.post(
    "/{investigation_id}/links",
    response_model=RelationshipRead,
    status_code=201,
    summary="Draw a link by hand",
)
def create_link(
    investigation_id: str,
    request: ManualLinkCreate,
    repo: Neo4jRepository = Depends(get_repository),
) -> RelationshipRead:
    """Record a connection an analyst asserts between two entities.

    Investigators know things the crawler cannot reach. This records that
    knowledge inside the investigation, where it can be audited, rather than
    leaving it in someone's notes - but it is stamped as analyst-asserted,
    scores nothing, and requires a stated reason, because it rests on a
    person's judgement rather than on anything observed.
    """
    investigation = _get_investigation(repo, investigation_id)
    try:
        relationship = LinkService(repo).create(investigation, request)
    except LinkError as error:
        raise HTTPException(
            status_code=409 if error.conflict else 400, detail=error.message
        ) from error
    return RelationshipRead.model_validate(
        repo.attach_evidence([relationship])[0]
    )


@router.get(
    "/{investigation_id}/results",
    response_model=SourceResults,
    summary="What each source yielded",
)
def read_results(
    investigation_id: str, repo: Neo4jRepository = Depends(get_repository)
) -> SourceResults:
    """One row per source: found, nothing found, or unavailable.

    The graph cannot express the difference between a source that was
    searched and came back empty and one that refused to be searched - both
    are simply absent from it. This is where that distinction lives.
    """
    investigation = _get_investigation(repo, investigation_id)
    return ResultsService(repo).build(investigation)


@router.get(
    "/{investigation_id}/profile",
    response_model=IdentityProfile,
    summary="Identity Intelligence Profile",
)
def read_profile(
    investigation_id: str, repo: Neo4jRepository = Depends(get_repository)
) -> IdentityProfile:
    """An evidence-backed summary of what this investigation observed.

    Computed from the graph on request rather than stored, so it cannot drift
    from the entities and evidence behind it. Every aggregated value names the
    entities that published it; nothing here asserts an identity.
    """
    investigation = _get_investigation(repo, investigation_id)
    return IdentityProfileService(repo).build(investigation)


@router.get(
    "/{investigation_id}/aliases",
    response_model=AliasList,
    summary="Potential aliases discovered in this investigation",
)
def list_aliases(
    investigation_id: str, repo: Neo4jRepository = Depends(get_repository)
) -> AliasList:
    """Handle variants proposed by the alias detector, strongest first.

    Every entry is a *potential* alias: a claim about the handles, backed by a
    named transformation and whatever contextual evidence corroborates it.
    """
    investigation = _get_investigation(repo, investigation_id)
    return AliasService(repo).list_aliases(investigation)


@router.get(
    "/{investigation_id}/leads",
    response_model=LeadList,
    summary="Suggested investigation leads",
)
def list_leads(
    investigation_id: str,
    repo: Neo4jRepository = Depends(get_repository),
    limit: int = Query(default=50, ge=1, le=200),
) -> LeadList:
    """What is worth looking at next, derived from evidence already collected.

    Leads are suggestions for an analyst, not investigative conclusions, and
    nothing here starts a new external search - the analyst stays in control.
    """
    investigation = _get_investigation(repo, investigation_id)
    return LeadService(repo).generate(investigation, limit=limit)


@router.get(
    "/{investigation_id}/paths",
    response_model=PathResponse,
    summary="How are two entities connected?",
)
def find_paths(
    investigation_id: str,
    source_entity_id: str = Query(min_length=1, max_length=64),
    target_entity_id: str = Query(min_length=1, max_length=64),
    repo: Neo4jRepository = Depends(get_repository),
    max_depth: int | None = Query(default=None, ge=1, le=8),
    max_paths: int | None = Query(default=None, ge=1, le=25),
) -> PathResponse:
    """Ranked routes between two entities of this investigation.

    Both entities must belong to the investigation in the path - the traversal
    is scoped to it, so one investigation cannot be used to walk into another.
    Depth and result count are bounded; there is no way to ask for an
    unlimited search and no way to supply Cypher.
    """
    investigation = _get_investigation(repo, investigation_id)
    try:
        return PathService(repo).find(
            investigation,
            source_entity_id,
            target_entity_id,
            max_depth=max_depth,
            max_paths=max_paths,
        )
    except PathNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/{investigation_id}/graph",
    response_model=GraphResponse,
    summary="Investigation graph",
)
def read_graph(
    investigation_id: str, repo: Neo4jRepository = Depends(get_repository)
) -> GraphResponse:
    """Nodes, edges, layout hints and statistics for the investigation graph."""
    investigation = _get_investigation(repo, investigation_id)
    return GraphService(repo).build(investigation)


@router.get(
    "/{investigation_id}/events",
    response_model=list[CrawlEventRead],
    summary="Investigation timeline",
)
def list_events(
    investigation_id: str,
    repo: Neo4jRepository = Depends(get_repository),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[CrawlEventRead]:
    """The persisted crawl timeline, oldest first."""
    _get_investigation(repo, investigation_id)
    events = repo.list_events(investigation_id, limit=limit)
    return [CrawlEventRead.model_validate(event) for event in events]


# ``/activity`` is the name section 27 uses for the timeline; both spellings
# reach the same data so neither the spec nor existing clients are surprised.
@router.get(
    "/{investigation_id}/activity",
    response_model=list[CrawlEventRead],
    summary="Investigation activity log",
)
def list_activity(
    investigation_id: str,
    repo: Neo4jRepository = Depends(get_repository),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[CrawlEventRead]:
    """Alias of ``/events``: the crawl and analysis activity log."""
    return list_events(investigation_id, repo=repo, limit=limit)


@router.get(
    "/{investigation_id}/export",
    summary="Export an investigation as JSON or CSV",
    # The handler returns either a model or a prepared Response, which FastAPI
    # cannot turn into a single response schema.
    response_model=None,
    responses={
        200: {
            "content": {
                "application/json": {},
                "text/csv": {"schema": {"type": "string"}},
            }
        }
    },
)
def export_investigation(
    investigation_id: str,
    repo: Neo4jRepository = Depends(get_repository),
    download: bool = Query(default=False),
    format: ExportFormat = Query(
        default=ExportFormat.JSON,
        description="json is the complete record; csv is one row per relationship.",
    ),
) -> InvestigationExport | JSONResponse | PlainTextResponse:
    """Export an investigation.

    ``json`` carries everything - investigation, entities, relationships,
    evidence, snapshots, analyst decisions and the timeline.  ``csv`` is the
    flat, spreadsheet-friendly view: one row per relationship with its evidence
    collapsed into two columns.
    """
    investigation = _get_investigation(repo, investigation_id)
    service = InvestigationService(repo)
    stem = f"investigation-{investigation.seed_identifier}-{investigation.id[:8]}"

    if format is ExportFormat.CSV:
        return PlainTextResponse(
            content=service.export_csv(investigation),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'},
        )

    export = service.export(investigation)
    if not download:
        return export
    return JSONResponse(
        content=export.model_dump(mode="json"),
        headers={"Content-Disposition": f'attachment; filename="{stem}.json"'},
    )


@router.get(
    "/{investigation_id}/summary",
    summary="Counts used by the dashboard",
    response_model=dict,
)
def investigation_summary(
    investigation_id: str, repo: Neo4jRepository = Depends(get_repository)
) -> dict:
    """Entity/relationship/evidence counts plus per-status breakdown."""
    _get_investigation(repo, investigation_id)
    entities, relationships, evidence = repo.counts(investigation_id)
    return {
        "entities": entities,
        "relationships": relationships,
        "evidence": evidence,
        "analyst_status": repo.analyst_status_counts(investigation_id),
    }
