"""Entity table: the nodes of an investigation graph.

A single generic entity model covers accounts, websites, domains, emails and
organizations.  Profile-specific fields (display name, bio, avatar, external
links) are stored as columns because the correlation engine compares them
directly; anything else observed goes into the ``metadata`` JSON column.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin, utcnow
from .enums import DiscoveryMethod, EntityType


class Entity(IdMixin, TimestampMixin, Base):
    """A publicly observable entity discovered during an investigation."""

    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint(
            "investigation_id",
            "type",
            "platform",
            "identifier",
            name="uq_entity_identity",
        ),
        Index("ix_entities_investigation", "investigation_id"),
    )

    investigation_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False
    )

    type: Mapped[str] = mapped_column(
        String(20), default=EntityType.ACCOUNT, nullable=False
    )
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    identifier: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Public profile fields (section 9).  All optional: a candidate entity may
    # be known only by platform and handle until it is looked up.
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(200), nullable=True)
    external_links: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    # Provenance.
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    discovery_method: Mapped[str] = mapped_column(
        String(20), default=DiscoveryMethod.DIRECT, nullable=False
    )
    discovered_via: Mapped[str | None] = mapped_column(Text, nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_seed: Mapped[bool] = mapped_column(default=False, nullable=False)
    resolved: Mapped[bool] = mapped_column(default=False, nullable=False)

    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    # ``metadata`` is reserved by SQLAlchemy's declarative API, so the Python
    # attribute is ``meta`` while the column keeps the documented name.
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict, nullable=False
    )

    investigation: Mapped["Investigation"] = relationship(  # noqa: F821
        back_populates="entities"
    )
    snapshots: Mapped[list["Snapshot"]] = relationship(  # noqa: F821
        back_populates="entity",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Snapshot.timestamp",
    )

    @property
    def key(self) -> tuple[str, str, str]:
        """De-duplication key within one investigation."""
        return (self.type, self.platform, self.identifier)

    @property
    def label(self) -> str:
        """``instagram:alice_98`` - stable short form for logs and events."""
        return f"{self.platform}:{self.identifier}"

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Entity {self.type} {self.label}>"
