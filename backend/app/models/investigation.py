"""Investigation and crawl-event tables."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin, utcnow
from .enums import InvestigationStatus


class Investigation(IdMixin, TimestampMixin, Base):
    """One analyst investigation, rooted at a single public seed identifier."""

    __tablename__ = "investigations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    seed_platform: Mapped[str] = mapped_column(String(50), nullable=False)
    seed_identifier: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=InvestigationStatus.CREATED, nullable=False
    )
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    demo: Mapped[bool] = mapped_column(default=False, nullable=False)
    max_depth: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    max_pages: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    entities: Mapped[list["Entity"]] = relationship(  # noqa: F821
        back_populates="investigation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    relationships: Mapped[list["Relationship"]] = relationship(  # noqa: F821
        back_populates="investigation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    evidence: Mapped[list["Evidence"]] = relationship(  # noqa: F821
        back_populates="investigation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    events: Mapped[list["CrawlEvent"]] = relationship(
        back_populates="investigation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CrawlEvent.timestamp",
    )

    @property
    def seed_label(self) -> str:
        """``instagram:alice_98`` - the form used in logs and event lines."""
        return f"{self.seed_platform}:{self.seed_identifier}"


class CrawlEvent(Base):
    """A timestamped line in the investigation's activity timeline.

    Events mirror the structured log so an analyst can see exactly what the
    crawler did, including sources that failed and why.
    """

    __tablename__ = "crawl_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investigation_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    level: Mapped[str] = mapped_column(String(10), default="INFO", nullable=False)
    event: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    investigation: Mapped[Investigation] = relationship(back_populates="events")


Index("ix_crawl_events_investigation", CrawlEvent.investigation_id, CrawlEvent.timestamp)
