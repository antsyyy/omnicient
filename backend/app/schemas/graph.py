"""API schemas for the investigation graph.

This is the contract between the backend and the React Flow client: the
backend decides what the graph *is* (nodes, edges, evidence counts, layout
hints), the frontend decides how it looks.  The frontend never needs to know
how crawling or correlation work.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ..models.enums import (
    AnalystStatus,
    ConfidenceLevel,
    DiscoveryMethod,
    EntityType,
    RelationshipOrigin,
    RelationshipType,
)


class GraphPosition(BaseModel):
    """Layout hint in React Flow coordinates, computed with NetworkX."""

    x: float
    y: float


class GraphNode(BaseModel):
    """One entity, ready to render."""

    id: str
    type: EntityType
    platform: str
    platform_name: str
    label: str
    identifier: str
    url: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    is_seed: bool = False
    resolved: bool = True
    depth: int = 0
    discovery_method: DiscoveryMethod = DiscoveryMethod.DIRECT
    degree: int = 0
    # Strongest association attached to this node, used for node badges.
    confidence_level: ConfidenceLevel | None = None
    confidence_score: float | None = None
    position: GraphPosition


class GraphEdge(BaseModel):
    """One relationship, ready to render."""

    id: str
    source: str
    target: str
    relationship_type: RelationshipType
    relationship_label: str
    confidence_score: float
    confidence_level: ConfidenceLevel
    analyst_status: AnalystStatus
    #: Whether a person drew this link or the engine derived it. The canvas
    #: must never draw the two identically.
    origin: RelationshipOrigin = RelationshipOrigin.ENGINE
    evidence_count: int = 0
    contradiction_count: int = 0
    summary: str | None = None


class GraphStats(BaseModel):
    """Counts the sidebar and filter panel render."""

    entities: int = 0
    relationships: int = 0
    evidence: int = 0
    contradictions: int = 0
    max_depth: int = 0
    by_entity_type: dict[str, int] = Field(default_factory=dict)
    by_relationship_type: dict[str, int] = Field(default_factory=dict)
    by_confidence: dict[str, int] = Field(default_factory=dict)
    by_analyst_status: dict[str, int] = Field(default_factory=dict)


class GraphResponse(BaseModel):
    """The whole investigation graph."""

    investigation_id: str
    generated_at: datetime
    seed_entity_id: str | None = None
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    stats: GraphStats = Field(default_factory=GraphStats)
