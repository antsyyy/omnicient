"""Snapshot table: what an entity looked like when it was observed.

A snapshot is written every time an entity is discovered or re-observed.  The
MVP only stores them; keeping the history from day one is what makes temporal
analysis ("what changed since the first observation?") possible later without
a migration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, utcnow


class Snapshot(IdMixin, Base):
    """A point-in-time copy of an entity's public fields."""

    __tablename__ = "snapshots"
    __table_args__ = (Index("ix_snapshots_entity", "entity_id", "timestamp"),)

    entity_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    username: Mapped[str | None] = mapped_column(String(200), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    external_links: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict, nullable=False
    )

    entity: Mapped["Entity"] = relationship(back_populates="snapshots")  # noqa: F821
