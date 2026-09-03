"""API schemas for investigations, crawl runs and JSON export."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models.enums import InvestigationStatus
from ..utils.normalization import normalize_platform
from .entity import EntityRead
from .evidence import EvidenceRead
from .relationship import RelationshipRead


class InvestigationCreate(BaseModel):
    """Request body for starting a new investigation."""

    identifier: str = Field(
        min_length=1,
        max_length=2048,
        description="Seed username, @handle or profile URL, e.g. @alice_98.",
    )
    platform: str = Field(default="instagram", max_length=50)
    name: str | None = Field(default=None, max_length=200)
    demo: bool | None = Field(
        default=None,
        description=(
            "Force demo mode on or off.  Defaults to the server's "
            "OMNICIENT_DEMO_MODE setting."
        ),
    )
    max_depth: int | None = Field(default=None, ge=0, le=4)
    max_pages: int | None = Field(default=None, ge=1, le=500)
    auto_crawl: bool = Field(
        default=True,
        description="Run discovery and correlation immediately after creation.",
    )

    @field_validator("platform")
    @classmethod
    def _normalize_platform(cls, value: str) -> str:
        normalized = normalize_platform(value)
        if not normalized:
            raise ValueError("platform is required")
        return normalized


class InvestigationRead(BaseModel):
    """An investigation and its headline counts."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    seed_platform: str
    seed_identifier: str
    status: InvestigationStatus
    status_message: str | None = None
    demo: bool = False
    max_depth: int = 2
    max_pages: int = 50
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    entity_count: int = 0
    relationship_count: int = 0
    evidence_count: int = 0


class CrawlEventRead(BaseModel):
    """One line of the investigation activity timeline."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    investigation_id: str
    timestamp: datetime
    level: str
    event: str
    message: str
    data: dict[str, Any] | None = None


class SourceIssue(BaseModel):
    """A source that could not be queried, and why.

    Surfaced to the analyst rather than raised: a failing source must never
    abort an investigation that already has usable evidence.
    """

    platform: str
    identifier: str | None = None
    reason: str
    detail: str | None = None
    url: str | None = None


class InvestigationDetail(InvestigationRead):
    """An investigation with its timeline and any source failures."""

    seed_entity_id: str | None = None
    events: list[CrawlEventRead] = Field(default_factory=list)
    issues: list[SourceIssue] = Field(default_factory=list)


class CrawlRequest(BaseModel):
    """Options for (re-)running discovery on an existing investigation."""

    max_depth: int | None = Field(default=None, ge=0, le=4)
    max_pages: int | None = Field(default=None, ge=1, le=500)
    reset: bool = Field(
        default=True,
        description="Discard previously discovered entities before crawling.",
    )


class CrawlResult(BaseModel):
    """Outcome of a crawl + correlation run."""

    investigation: InvestigationRead
    entities_discovered: int
    relationships_created: int
    evidence_items: int
    pages_fetched: int
    issues: list[SourceIssue] = Field(default_factory=list)


class InvestigationExport(BaseModel):
    """Complete JSON export of an investigation (section 39).

    The shape is intentionally flat and self-describing so downstream formats
    (CSV, STIX, PDF reporting) can be generated from it without re-querying.
    """

    format: str = "omnicient.investigation"
    format_version: str = "1.0"
    generated_at: datetime
    disclaimer: str
    investigation: InvestigationRead
    seed: dict[str, Any]
    entities: list[EntityRead] = Field(default_factory=list)
    relationships: list[RelationshipRead] = Field(default_factory=list)
    evidence: list[EvidenceRead] = Field(default_factory=list)
    crawl_events: list[CrawlEventRead] = Field(default_factory=list)
