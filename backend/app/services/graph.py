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
# Card dimensions are measured, not assumed: a node renders about 185x109
# at zoom 1, so it is nearly twice as wide as it is tall. Spacing the levels
# as generously as the columns therefore looked wrong - the vertical gutter
# came out at 171px against 55px horizontally, and the tree read as three
# times airier down the screen than across it. Both gutters are now about
# the same, which is what makes it compact without crowding.
#: Vertical distance between one hop level and the next. 109 of that is card.
LEVEL_GAP = 170
#: Horizontal distance between neighbouring cards. 185 of that is card.
NODE_GAP = 225
#: A level with more members than this is stepped up and down alternately.
#: A bare handle asks two dozen sources about itself, and two dozen cards in
#: one dead-straight row run out of screen long before they run out of
#: content - the stagger lets the eye follow a line of them and keeps the
#: labels from crowding, without giving up the shape of a tree.
STAGGER_ABOVE = 6
#: How far a stepped node moves off its level. Enough to break the line of
#: labels, not so much that a level stops reading as one.
STAGGER_STEP = 70
#: Entities no relationship reaches are parked below the tree in a grid, this
#: many to a row, rather than being hung off a root they have no edge to.
ORPHAN_COLUMNS = 6


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
        """Tidy tree: the seed on top, each hop a level below the one before.

        An investigation is a rooted, shallow thing - a starting handle and
        what was found from it - and a tree says that directly: the seed is
        the thing at the top, every card below it was reached from the card
        above, and depth reads down the screen.

        Levels are hop distance from the seed, not crawl depth. They usually
        agree, but a bare handle asks every source about itself at depth
        zero, so depth alone would put the seed shoulder to shoulder with the
        two dozen accounts it found.

        Each node sits centred over its children, so a branch reads as one
        shape and a parent is always findable from the cards under it. The
        cost of a tree is width - a wide fan-out is a wide row, which is what
        the radial layout this replaces was avoiding - so a crowded level is
        stepped alternately up and down, which keeps the labels apart and
        lets the cards sit closer together than a dead-straight row allows.
        """
        if not entities:
            return {}

        by_id = {entity.id: entity for entity in entities}
        root = next(
            (entity.id for entity in entities if entity.is_seed),
            # No seed recorded: the busiest node is the closest thing to one.
            max(
                (entity.id for entity in entities),
                key=lambda node_id: (
                    graph.degree(node_id) if graph.has_node(node_id) else 0
                ),
            ),
        )

        # Hop distance from the seed, and the neighbour each node was reached
        # through - which is what makes the parent-child structure a tree.
        hops: dict[str, int] = {root: 0}
        parent: dict[str, str] = {}
        if graph.has_node(root):
            for node_id, path in nx.single_source_shortest_path(graph, root).items():
                hops[node_id] = len(path) - 1
                if len(path) > 1:
                    parent[node_id] = path[-2]

        def rank(node_id: str) -> tuple:
            """Deterministic sibling order: busiest first, then by id."""
            degree = graph.degree(node_id) if graph.has_node(node_id) else 0
            return (-degree, node_id)

        children: dict[str, list[str]] = {}
        for node_id, mother in parent.items():
            if node_id in by_id:
                children.setdefault(mother, []).append(node_id)
        for siblings in children.values():
            siblings.sort(key=rank)

        # Post-order walk, iteratively: a leaf takes the next free column, a
        # parent centres itself over the children already placed. Recursion
        # would be fine at the depths a crawl reaches, but the traversal is
        # the part worth being explicit about.
        columns: dict[str, float] = {}
        cursor = 0.0
        stack: list[tuple[str, bool]] = [(root, False)]
        seen: set[str] = set()
        while stack:
            node_id, expanded = stack.pop()
            kids = children.get(node_id, [])
            if not kids:
                columns[node_id] = cursor
                cursor += NODE_GAP
                continue
            if not expanded:
                if node_id in seen:
                    continue
                seen.add(node_id)
                stack.append((node_id, True))
                # Reversed so the sorted order comes off the stack intact.
                stack.extend((kid, False) for kid in reversed(kids))
                continue
            placed = [columns[kid] for kid in kids if kid in columns]
            columns[node_id] = (
                (min(placed) + max(placed)) / 2 if placed else cursor
            )

        # Step crowded levels so a wide fan-out stays readable.
        levels: dict[int, list[str]] = {}
        for node_id in columns:
            levels.setdefault(hops.get(node_id, 0), []).append(node_id)

        offsets: dict[str, float] = {}
        stepped: set[int] = set()
        for level, members in levels.items():
            if level == 0 or len(members) <= STAGGER_ABOVE:
                continue
            stepped.add(level)
            for index, node_id in enumerate(sorted(members, key=columns.get)):
                offsets[node_id] = STAGGER_STEP if index % 2 else 0.0

        # Level baselines, accumulated rather than multiplied, because a
        # stepped level is taller than an unstepped one. Spacing them evenly
        # and then stepping into the gap put a dropped card 160px above the
        # level below - closer to a stranger's child than to its own siblings.
        baseline: dict[int, float] = {}
        offset = 0.0
        for level in sorted(levels):
            baseline[level] = offset
            offset += LEVEL_GAP + (STAGGER_STEP if level in stepped else 0.0)

        # The seed anchors the picture at the origin.
        origin = columns.get(root, 0.0)
        positions = {
            node_id: {
                "x": round(column - origin, 2),
                "y": round(
                    baseline.get(hops.get(node_id, 0), 0.0)
                    + offsets.get(node_id, 0.0),
                    2,
                ),
            }
            for node_id, column in columns.items()
        }

        # Entities no relationship reaches are not part of the tree, and
        # hanging them off the root would draw a parentage that does not
        # exist. They are parked in a grid underneath it instead, which is
        # honest about their being unattached and still puts them on screen.
        loose = sorted(
            (entity.id for entity in entities if entity.id not in positions),
            key=rank,
        )
        if loose:
            floor = max((point["y"] for point in positions.values()), default=0.0)
            for index, node_id in enumerate(loose):
                row, column = divmod(index, ORPHAN_COLUMNS)
                positions[node_id] = {
                    "x": round((column - (ORPHAN_COLUMNS - 1) / 2) * NODE_GAP, 2),
                    "y": round(floor + LEVEL_GAP * (1.5 + row), 2),
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
