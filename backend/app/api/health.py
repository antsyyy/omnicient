"""Health and capability endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import get_settings
from ..database import check_connection, get_repository
from ..demo_data import DEMO_SEED_IDENTIFIER, DEMO_SEED_PLATFORM, demo_platforms
from ..repository import Neo4jRepository
from ..sources import ADAPTER_CLASSES

router = APIRouter(tags=["health"])


@router.get("/health", summary="Service health and capabilities")
def health() -> dict:
    """Liveness plus the facts the client needs to configure itself.

    The client uses ``demo_mode`` to decide whether to label investigations as
    synthetic, and ``sources`` to show which platforms can be queried live.
    ``status`` is ``degraded`` when Neo4j cannot be reached.
    """
    settings = get_settings()
    connected, error = check_connection()
    return {
        "status": "ok" if connected else "degraded",
        "app": settings.app_name,
        "tagline": settings.tagline,
        "version": settings.version,
        "demo_mode": settings.demo_mode,
        "database": {
            "engine": "neo4j",
            "connected": connected,
            # The error *type* is enough to diagnose; connection strings and
            # credentials never reach the client.
            "error": error,
        },
        "demo_seed": {
            "platform": DEMO_SEED_PLATFORM,
            "identifier": DEMO_SEED_IDENTIFIER,
        },
        "sources": [adapter.platform for adapter in ADAPTER_CLASSES],
        "demo_sources": demo_platforms(),
        "crawler": {
            "max_depth": settings.max_depth,
            "max_pages": settings.max_pages,
            "request_timeout": settings.request_timeout,
            "respect_robots": settings.respect_robots,
        },
        "confidence_bands": [
            {"min_score": threshold, "level": level}
            for threshold, level in settings.scoring.bands
        ],
    }


@router.get("/stats", summary="Headline numbers for the dashboard")
def stats(repo: Neo4jRepository = Depends(get_repository)) -> dict:
    """Totals across every investigation (section 19).

    ``confirmed`` counts relationships an analyst reviewed and judged
    supportive - it is not a count of proven identities.
    """
    totals = repo.global_stats()
    return {**totals, "by_platform": repo.platform_totals()}
