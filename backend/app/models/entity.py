"""Entity record: the nodes of an investigation graph.

One generic record covers accounts, websites, domains, emails, usernames and
organizations.  In Neo4j each entity carries the shared ``:Entity`` label plus
a label for its type (``:Account``, ``:Website``, ...), so the documented model
from section 7 is queryable directly while uniform traversals stay simple.

Profile fields the correlation engine compares (display name, bio, avatar,
external links) are first-class properties; anything else observed goes into
``meta``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .base import as_datetime, new_id, utcnow
from .enums import DiscoveryMethod, EntityType, EntityVerdict

#: Neo4j label carried by every entity node, whatever its type.
ENTITY_LABEL = "Entity"

#: Additional label per entity type, so ``MATCH (a:Account)`` works as the
#: specification describes.
TYPE_LABELS: dict[str, str] = {
    EntityType.ACCOUNT: "Account",
    EntityType.WEBSITE: "Website",
    EntityType.DOMAIN: "Domain",
    EntityType.USERNAME: "Username",
    EntityType.EMAIL: "Email",
    EntityType.PERSON: "Person",
    EntityType.ORGANIZATION: "Organization",
}


def type_label(entity_type: str) -> str:
    """Neo4j label for an :class:`EntityType` value."""
    return TYPE_LABELS.get(str(entity_type), "Account")


@dataclass
class Entity:
    """A publicly observable entity discovered during an investigation."""

    investigation_id: str
    platform: str
    name: str
    identifier: str
    type: str = EntityType.ACCOUNT
    id: str = field(default_factory=new_id)
    url: str | None = None

    # Public profile fields.  All optional: a candidate entity may be known
    # only by platform and handle until it is looked up.
    display_name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    location: str | None = None
    email: str | None = None
    organization: str | None = None
    external_links: list[str] = field(default_factory=list)

    # Provenance.
    source: str | None = None
    discovery_method: str = DiscoveryMethod.DIRECT
    discovered_via: str | None = None
    depth: int = 0
    is_seed: bool = False
    resolved: bool = False

    #: An analyst's ruling that this entity is somebody else. Never set by
    #: the engine, and it removes nothing - see :class:`EntityVerdict`.
    analyst_verdict: str = EntityVerdict.UNREVIEWED
    analyst_note: str | None = None
    reviewed_at: datetime | None = None

    first_seen: datetime = field(default_factory=utcnow)
    last_seen: datetime = field(default_factory=utcnow)
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    meta: dict[str, Any] = field(default_factory=dict)

    #: Populated on demand by the repository; not stored on the node.
    snapshots: list["Snapshot"] = field(default_factory=list)  # noqa: F821

    @property
    def key(self) -> tuple[str, str, str]:
        """De-duplication key within one investigation."""
        return (str(self.type), self.platform, self.identifier)

    @property
    def label(self) -> str:
        """``instagram:alice_98`` - stable short form for logs and events."""
        return f"{self.platform}:{self.identifier}"

    @classmethod
    def from_node(cls, node: Any) -> "Entity":
        """Build a record from a Neo4j node."""
        data = dict(node)
        return cls(
            id=data["id"],
            investigation_id=data["investigation_id"],
            type=data.get("type", EntityType.ACCOUNT),
            platform=data.get("platform", ""),
            name=data.get("name", ""),
            identifier=data.get("identifier", ""),
            url=data.get("url"),
            display_name=data.get("display_name"),
            bio=data.get("bio"),
            avatar_url=data.get("avatar_url"),
            location=data.get("location"),
            email=data.get("email"),
            organization=data.get("organization"),
            external_links=list(data.get("external_links") or []),
            source=data.get("source"),
            discovery_method=data.get("discovery_method", DiscoveryMethod.DIRECT),
            discovered_via=data.get("discovered_via"),
            depth=int(data.get("depth", 0)),
            is_seed=bool(data.get("is_seed", False)),
            resolved=bool(data.get("resolved", False)),
            analyst_verdict=data.get("analyst_verdict") or EntityVerdict.UNREVIEWED,
            analyst_note=data.get("analyst_note"),
            reviewed_at=as_datetime(data.get("reviewed_at")),
            first_seen=as_datetime(data.get("first_seen")) or utcnow(),
            last_seen=as_datetime(data.get("last_seen")) or utcnow(),
            created_at=as_datetime(data.get("created_at")) or utcnow(),
            updated_at=as_datetime(data.get("updated_at")) or utcnow(),
            meta=_json_field(data.get("meta")),
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Entity {self.type} {self.label}>"


def _json_field(value: Any) -> dict[str, Any]:
    """Decode a JSON-encoded map property.

    Neo4j properties are scalars or arrays of scalars - never nested maps - so
    free-form observation metadata is stored as a JSON string and decoded here.
    """
    import json

    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            decoded = json.loads(value)
        except ValueError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}
