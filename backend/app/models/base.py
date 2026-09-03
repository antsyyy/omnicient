"""Declarative base and shared column mixins."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Timezone-aware current time, used for every timestamp column."""
    return datetime.now(UTC)


def new_id() -> str:
    """Opaque primary key.  UUIDs keep exported graphs stable across databases."""
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    """Declarative base for every Omnicient table."""


class IdMixin:
    """String UUID primary key."""

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)


class TimestampMixin:
    """``created_at`` / ``updated_at`` columns maintained by the ORM."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
