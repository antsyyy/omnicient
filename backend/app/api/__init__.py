"""FastAPI routers, mounted under ``/api`` by :mod:`app.main`."""

from fastapi import APIRouter

from . import entities, evidence, health, investigations, relationships

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(investigations.router)
api_router.include_router(entities.router)
api_router.include_router(relationships.router)
api_router.include_router(evidence.router)

__all__ = ["api_router"]
