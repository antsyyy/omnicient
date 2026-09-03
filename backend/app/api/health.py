"""Health and capability endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from ..config import get_settings
from ..demo_data import DEMO_SEED_IDENTIFIER, DEMO_SEED_PLATFORM, demo_platforms
from ..sources import ADAPTER_CLASSES

router = APIRouter(tags=["health"])


@router.get("/health", summary="Service health and capabilities")
def health() -> dict:
    """Liveness plus the facts the client needs to configure itself.

    The client uses ``demo_mode`` to decide whether to label investigations as
    synthetic, and ``sources`` to show which platforms can be queried live.
    """
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "tagline": settings.tagline,
        "version": settings.version,
        "demo_mode": settings.demo_mode,
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
