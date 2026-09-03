"""Evidence table: why a relationship exists and what it is worth.

Evidence is first class in Omnicient.  Every point of every score traces back
to a row here, with the URL the observation came from, so an analyst can
reconstruct a score by reading its evidence list.  The schema is intentionally
flat and self-describing so a future retrieval layer (section 43) can index it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import relationship as orm_relationship

from .base import Base, IdMixin, utcnow


class Evidence(IdMixin, Base):
    """One observation supporting or contradicting a relationship."""

    __tablename__ = "evidence"
    __table_args__ = (Index("ix_evidence_relationship", "relationship_id"),)

    investigation_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False
    )
    relationship_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("relationships.id", ondelete="CASCADE"), nullable=True
    )
    source_entity_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    target_entity_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("entities.id", ondelete="CASCADE"), nullable=True
    )

    type: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    extracted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    supports: Mapped[bool] = mapped_column(default=True, nullable=False)
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    # The attribute is named ``relationship`` to match the documented evidence
    # model, so the SQLAlchemy helper is imported under an alias.
    relationship: Mapped["Relationship | None"] = orm_relationship(  # noqa: F821
        back_populates="evidence"
    )
    investigation: Mapped["Investigation"] = orm_relationship(  # noqa: F821
        back_populates="evidence"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Evidence {self.type} weight={self.weight:+.0f}>"
