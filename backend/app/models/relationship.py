"""Relationship table: the scored, evidence-backed edges of the graph."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin
from .enums import AnalystStatus, ConfidenceLevel, RelationshipType


class Relationship(IdMixin, TimestampMixin, Base):
    """A potential association between two entities.

    A relationship is never an assertion of identity.  ``confidence_score`` is
    the sum of its evidence weights, clamped to ``[0, 100]``, and
    ``confidence_level`` is the band that score falls into.
    """

    __tablename__ = "relationships"
    __table_args__ = (
        UniqueConstraint(
            "investigation_id",
            "source_entity_id",
            "target_entity_id",
            "relationship_type",
            name="uq_relationship_identity",
        ),
        Index("ix_relationships_investigation", "investigation_id"),
    )

    investigation_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False
    )
    source_entity_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    target_entity_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )

    relationship_type: Mapped[str] = mapped_column(
        String(30), default=RelationshipType.LINKS_TO, nullable=False
    )
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confidence_level: Mapped[str] = mapped_column(
        String(15), default=ConfidenceLevel.LOW, nullable=False
    )
    analyst_status: Mapped[str] = mapped_column(
        String(15), default=AnalystStatus.UNREVIEWED, nullable=False
    )
    analyst_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_entity: Mapped["Entity"] = relationship(  # noqa: F821
        foreign_keys=[source_entity_id]
    )
    target_entity: Mapped["Entity"] = relationship(  # noqa: F821
        foreign_keys=[target_entity_id]
    )
    investigation: Mapped["Investigation"] = relationship(  # noqa: F821
        back_populates="relationships"
    )
    evidence: Mapped[list["Evidence"]] = relationship(  # noqa: F821
        back_populates="relationship",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Evidence.weight.desc()",
    )

    @property
    def evidence_ids(self) -> list[str]:
        """Ids of the evidence items backing this relationship."""
        return [item.id for item in self.evidence]

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<Relationship {self.relationship_type} "
            f"score={self.confidence_score:.0f} {self.confidence_level}>"
        )
