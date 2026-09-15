"""API schemas for entities and their historical snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field

from ..models.enums import DiscoveryMethod, EntityType
from ..utils.normalization import platform_label


class SnapshotRead(BaseModel):
    """A stored point-in-time observation of an entity."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    entity_id: str
    timestamp: datetime
    username: str | None = None
    display_name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    external_links: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(
        default_factory=dict, validation_alias=AliasChoices("meta", "metadata")
    )


class EntityRead(BaseModel):
    """An entity as returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    investigation_id: str
    type: EntityType
    platform: str
    name: str
    identifier: str
    url: str | None = None

    display_name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    location: str | None = None
    email: str | None = None
    organization: str | None = None
    external_links: list[str] = Field(default_factory=list)

    source: str | None = None
    discovery_method: DiscoveryMethod = DiscoveryMethod.DIRECT
    discovered_via: str | None = None
    depth: int = 0
    is_seed: bool = False
    resolved: bool = False

    first_seen: datetime
    last_seen: datetime
    created_at: datetime
    updated_at: datetime

    metadata: dict[str, Any] = Field(
        default_factory=dict, validation_alias=AliasChoices("meta", "metadata")
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def platform_name(self) -> str:
        """Display label for the platform, e.g. ``GitHub``."""
        return platform_label(self.platform)


class EntityDetail(EntityRead):
    """An entity plus its observation history."""

    snapshots: list[SnapshotRead] = Field(default_factory=list)


class EntitySummary(BaseModel):
    """Compact entity reference embedded in relationship payloads.

    Carries the picture and the display name as well as the handle: every
    list that shows an account wants to show its face, and re-fetching the
    whole entity for each row of a results list to get one field would be
    absurd.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    type: EntityType
    platform: str
    name: str
    identifier: str
    url: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def platform_name(self) -> str:
        return platform_label(self.platform)
