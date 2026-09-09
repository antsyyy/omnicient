"""Omnicient API application.

    uvicorn app.main:app --reload

Applies the Neo4j constraints and indexes on startup, mounts every router
under ``/api`` and publishes OpenAPI documentation at ``/docs``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from .api import api_router
from .config import get_settings
from .database import DatabaseUnavailableError, close_driver, init_db
from .utils.logging import configure_logging, get_logger
from .utils.normalization import NormalizationError
from .utils.validation import UnsafeURLError

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)

DESCRIPTION = """
**Omnicient** is an evidence-backed OSINT crawling and identity correlation
platform.  It discovers publicly observable entities, maps their relationships
and helps analysts evaluate potential digital-identity associations through an
interactive investigation graph.

Omnicient reports *potential associations* supported by evidence.  It never
claims that two accounts belong to the same person - the analyst makes that
call, and the evidence behind every score is always shown.

Only publicly accessible information is collected.  Omnicient does not
authenticate, reuse sessions, bypass CAPTCHAs or evade rate limits.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Connect to Neo4j and apply constraints before serving traffic.

    A database that is still starting is retried; one that never answers is
    logged and the API still comes up, so ``/api/health`` can report the
    problem instead of the process dying at boot.
    """
    try:
        init_db()
    except DatabaseUnavailableError as exc:
        logger.error("startup_without_database error=%s", exc)
    logger.info(
        "omnicient_started version=%s demo_mode=%s", settings.version, settings.demo_mode
    )
    try:
        yield
    finally:
        close_driver()


app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION,
    version=settings.version,
    summary=settings.tagline,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.exception_handler(NormalizationError)
async def _normalization_error(request: Request, exc: NormalizationError) -> JSONResponse:
    """Invalid identifiers are a client error, not a server fault."""
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(UnsafeURLError)
async def _unsafe_url_error(request: Request, exc: UnsafeURLError) -> JSONResponse:
    """A URL rejected by the SSRF guard is reported, never fetched."""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(DatabaseUnavailableError)
async def _database_unavailable(
    request: Request, exc: DatabaseUnavailableError
) -> JSONResponse:
    """Neo4j being down is a 503, and the message never leaks driver internals."""
    logger.error("database_unavailable path=%s", request.url.path)
    return JSONResponse(
        status_code=503,
        content={"detail": "The investigation database is unavailable."},
    )


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")
