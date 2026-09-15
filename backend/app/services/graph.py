"""Graph service.

Turns the stored entities and relationships into the payload the React Flow
client renders.  The backend owns what the graph *is* - nodes, edges, evidence
counts, layout hints and summary statistics - and the frontend owns how it
looks.  That split is what lets the interface and the OSINT backend be built
in parallel against a fixed contract (section 47).

NetworkX does the structural work here (degree, layered layout).  It is a
processing library, not a store: the source of truth stays in Neo4j.
"""

from __future__ import annotations

from datetime import UTC, datetime

import networkx as nx

from ..models.entity import Entity
from ..models.enums import AnalystStatus, EntityType
from ..models.investigation import Investigation
from ..models.relationship import Relationship
from ..repository import Neo4jRepository
from ..schemas.graph import (
    GraphEdge,
    GraphNode,
    GraphPosition,
    GraphResponse,
    GraphStats,
)
from ..utils.logging import get_logger
from ..utils.normalization import platform_label

logger = get_logger(__name__)

# Layout spacing in React Flow pixels.
LAYER_HEIGHT = 220
NODE_SPACING = 260


class GraphService:
    """Builds the investigation graph payload."""

    def __init__(self, repo: Neo4jRepository) -> None:
        self.repo = repo

    def build(self, investigation: Investigation) -> GraphResponse:
        """Assemble nodes, edges, layout and statistics for one investigation."""
        entities = self.repo.list_entities(investigation.id)
        relationships = self.repo.list_relationships(investigation.id)
        evidence_counts = self.repo.evidence_counts(investigation.id)

        graph = self._networkx_graph(entities, relationships)
        positions = self._layout(graph, entities)
        best = self._best_confidence(relationships)

        nodes = [
            GraphNode(
                id=entity.id,
                type=EntityType(entity.type),
                platform=entity.platform,
                platform_name=platform_label(entity.platform),
                label=entity.name,
                identifier=entity.identifier,
                url=entity.url,
                display_name=entity.display_name,
                avatar_url=entity.avatar_url,
                is_seed=entity.is_seed,
                resolved=entity.resolved,
                depth=entity.depth,
                discovery_method=entity.discovery_method,
                degree=graph.degree(entity.id) if graph.has_node(entity.id) else 0,
                confidence_level=best.get(entity.id, (None, None))[0],
                confidence_score=best.get(entity.id, (None, None))[1],
                position=GraphPosition(**positions[entity.id]),
            )
            for entity in entities
        ]

        edges = [
            GraphEdge(
                id=relationship.id,
                source=relationship.source_entity_id,
                target=relationship.target_entity_id,
                relationship_type=relationship.relationship_type,
                relationship_label=_relationship_label(relationship.relationship_type),
                confidence_score=relationship.confidence_score,
                confidence_level=relationship.confidence_level,
                analyst_status=relationship.analyst_status,
                origin=relationship.origin,
                evidence_count=evidence_counts.get(relationship.id, (0, 0))[0],
                contradiction_count=evidence_counts.get(relationship.id, (0, 0))[1],
                summary=relationship.summary,
            )
            for relationship in relationships
        ]

        seed = next((entity.id for entity in entities if entity.is_seed), None)
        response = GraphResponse(
            investigation_id=investigation.id,
            generated_at=datetime.now(UTC),
            seed_entity_id=seed,
            nodes=nodes,
            edges=edges,
            stats=self._stats(entities, relationships, evidence_counts),
        )
        logger.info(
            "graph_built investigation=%s nodes=%d edges=%d",
            investigation.id,
            len(nodes),
            len(edges),
        )
        return response

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _networkx_graph(
        entities: list[Entity], relationships: list[Relationship]
    ) -> nx.Graph:
        """Undirected view used for degree and layout calculations."""
        graph = nx.Graph()
        for entity in entities:
            graph.add_node(entity.id, depth=entity.depth, type=entity.type)
        for relationship in relationships:
            if graph.has_node(relationship.source_entity_id) and graph.has_node(
                relationship.target_entity_id
            ):
                graph.add_edge(
                    relationship.source_entity_id,
                    relationship.target_entity_id,
                    weight=max(relationship.confidence_score, 1.0),
                )
        return graph

    @staticmethod
    def _layout(graph: nx.Graph, entities: list[Entity]) -> dict[str, dict[str, float]]:
        """Layered layout: the seed on top, each crawl depth on its own row.

        An investigation graph is rooted and shallow, so a depth-layered layout
        reads far better than a force-directed cloud - the analyst can see at a
        glance how far from the seed a claim is.
        """
        if not entities:
            return {}

        layers: dict[int, list[str]] = {}
        for entity in entities:
            layers.setdefault(entity.depth, []).append(entity.id)

        # NetworkX orders each layer; degree-sorting keeps hubs central.
        positions: dict[str, dict[str, float]] = {}
        for depth, node_ids in sorted(layers.items()):
            ordered = sorted(
                node_ids,
                key=lambda node_id: (
                    -(graph.degree(node_id) if graph.has_node(node_id) else 0),
                    node_id,
                ),
            )
            width = (len(ordered) - 1) * NODE_SPACING
            for index, node_id in enumerate(ordered):
                positions[node_id] = {
                    "x": round(index * NODE_SPACING - width / 2, 2),
                    "y": round(depth * LAYER_HEIGHT, 2),
                }
        return positions

    @staticmethod
    def _best_confidence(
        relationships: list[Relationship],
    ) -> dict[str, tuple[str, float]]:
        """Strongest association touching each node, for the node badge."""
        best: dict[str, tuple[str, float]] = {}
        for relationship in relationships:
            for node_id in (
                relationship.source_entity_id,
                relationship.target_entity_id,
            ):
                current = best.get(node_id)
                if current is None or relationship.confidence_score > current[1]:
                    best[node_id] = (
                        relationship.confidence_level,
                        relationship.confidence_score,
                    )
        return best

    @staticmethod
    def _stats(
        entities: list[Entity],
        relationships: list[Relationship],
        evidence_counts: dict[str, tuple[int, int]],
    ) -> GraphStats:
        stats = GraphStats(
            entities=len(entities),
            relationships=len(relationships),
            evidence=sum(total for total, _ in evidence_counts.values()),
            contradictions=sum(bad for _, bad in evidence_counts.values()),
            max_depth=max((entity.depth for entity in entities), default=0),
        )
        for entity in entities:
            stats.by_entity_type[entity.type] = stats.by_entity_type.get(entity.type, 0) + 1
        for relationship in relationships:
            key = relationship.relationship_type
            stats.by_relationship_type[key] = stats.by_relationship_type.get(key, 0) + 1
            level = relationship.confidence_level
            stats.by_confidence[level] = stats.by_confidence.get(level, 0) + 1
            status = relationship.analyst_status or AnalystStatus.UNREVIEWED
            stats.by_analyst_status[status] = stats.by_analyst_status.get(status, 0) + 1
        return stats


def _relationship_label(relationship_type: str) -> str:
    from ..models.enums import RELATIONSHIP_LABELS

    return RELATIONSHIP_LABELS.get(relationship_type, relationship_type)
