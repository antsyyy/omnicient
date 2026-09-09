"""Investigation and crawl-event records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .base import as_datetime, new_id, utcnow
from .entity import _json_field
from .enums import InvestigationStatus


@dataclass
class Investigation:
    """One analyst investigation, rooted at a single public seed identifier."""

    name: str
    seed_platform: str
    seed_identifier: str
    id: str = field(default_factory=new_id)
    #: Exactly what the analyst typed, before normalization.
    seed_input: str = ""
    #: The detected :class:`~app.utils.identifier.IdentifierType`.
    seed_type: str = ""
    status: str = InvestigationStatus.CREATED
    status_message: str | None = None
    demo: bool = False
    max_depth: int = 2
    max_pages: int = 50
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    @property
    def seed_label(self) -> str:
        """``instagram:alice_98`` - the form used in logs and event lines."""
        return f"{self.seed_platform}:{self.seed_identifier}"

    @classmethod
    def from_node(cls, node: Any) -> "Investigation":
        """Build a record from a Neo4j node."""
        data = dict(node)
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            seed_platform=data.get("seed_platform", ""),
            seed_identifier=data.get("seed_identifier", ""),
            seed_input=data.get("seed_input", ""),
            seed_type=data.get("seed_type", ""),
            status=data.get("status", InvestigationStatus.CREATED),
            status_message=data.get("status_message"),
            demo=bool(data.get("demo", False)),
            max_depth=int(data.get("max_depth", 2)),
            max_pages=int(data.get("max_pages", 50)),
            started_at=as_datetime(data.get("started_at")),
            completed_at=as_datetime(data.get("completed_at")),
            created_at=as_datetime(data.get("created_at")) or utcnow(),
            updated_at=as_datetime(data.get("updated_at")) or utcnow(),
        )


@dataclass
class CrawlEvent:
    """A timestamped line in the investigation's activity timeline.

    Events mirror the structured log so an analyst can see exactly what the
    crawler did, including sources that failed and why.
    """

    investigation_id: str
    event: str
    message: str
    id: str = field(default_factory=new_id)
    timestamp: datetime = field(default_factory=utcnow)
    level: str = "INFO"
    data: dict[str, Any] | None = None
    #: Monotonic position within the investigation, so events written inside
    #: the same millisecond still read back in the order they happened.
    sequence: int = 0

    @classmethod
    def from_node(cls, node: Any) -> "CrawlEvent":
        """Build a record from a Neo4j node."""
        data = dict(node)
        raw = data.get("data")
        return cls(
            id=data["id"],
            investigation_id=data["investigation_id"],
            event=data.get("event", ""),
            message=data.get("message", ""),
            timestamp=as_datetime(data.get("timestamp")) or utcnow(),
            level=data.get("level", "INFO"),
            data=_json_field(raw) if raw else None,
            sequence=int(data.get("sequence", 0)),
        )
