"""Cypher data access for Omnicient.

Every read and write against Neo4j lives here, so services and API handlers
never build a query of their own.  Methods take and return the plain records
from :mod:`app.models`, which keeps the correlation engine, crawler and graph
builder testable without a database.

Graph shape
-----------

::

    (:Investigation)-[:DISCOVERED]->(:Entity:Account|Website|Domain|...)
    (:Entity)-[:LINKS_TO|REFERENCES|SHARED_WEBSITE|
               POTENTIAL_SAME_IDENTITY|CONTRADICTORY|...]->(:Entity)
    (:Entity)-[:HAS_SNAPSHOT]->(:Snapshot)
    (:Investigation)-[:COLLECTED]->(:Evidence)-[:CONCERNS]->(:Entity)
    (:Investigation)-[:LOGGED]->(:CrawlEvent)

Scored associations are native Neo4j relationships, as section 7 specifies.
Evidence is a node rather than a property bag on that relationship because
Neo4j relationships cannot be endpoints of other relationships: each
``(:Evidence)`` carries the ``relationship_id`` of the edge it explains, which
is what makes "show me every observation behind this score" a single indexed
lookup.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from neo4j import Session

from .models.entity import Entity, type_label
from .models.enums import AnalystStatus, RelationshipOrigin, RelationshipType
from .models.evidence import Evidence
from .models.investigation import CrawlEvent, Investigation
from .models.relationship import Relationship
from .models.snapshot import Snapshot
from .utils.logging import get_logger
from .utils.normalization import identity_key

logger = get_logger(__name__)

#: Relationship types that may be written as Neo4j relationship types.  Cypher
#: cannot parameterize a relationship type, so the value is interpolated into
#: the query - this allow-list is what keeps that safe.
ALLOWED_RELATIONSHIP_TYPES: frozenset[str] = frozenset(
    str(member) for member in RelationshipType
)


def _encode(value: Any) -> str | None:
    """JSON-encode a free-form map for storage as a Neo4j property.

    Neo4j properties are scalars or arrays of scalars, never nested maps, so
    observation metadata travels as a JSON string.
    """
    if value is None:
        return None
    return json.dumps(value, default=str)


def _relationship_type(value: str) -> str:
    """Validate a relationship type before it is interpolated into Cypher."""
    text = str(value)
    if text not in ALLOWED_RELATIONSHIP_TYPES:
        raise ValueError(f"Unsupported relationship type: {value!r}")
    return text


class Neo4jRepository:
    """All Cypher for Omnicient, bound to one driver session."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # -- investigations ----------------------------------------------------

    def create_investigation(self, investigation: Investigation) -> Investigation:
        """Persist a new investigation node."""
        record = self.session.run(
            """
            CREATE (i:Investigation {
                id: $id, name: $name,
                seed_platform: $seed_platform, seed_identifier: $seed_identifier,
                seed_input: $seed_input, seed_type: $seed_type,
                status: $status, status_message: $status_message,
                demo: $demo, max_depth: $max_depth, max_pages: $max_pages,
                started_at: $started_at, completed_at: $completed_at,
                created_at: datetime($created_at), updated_at: datetime($updated_at)
            })
            RETURN i
            """,
            id=investigation.id,
            name=investigation.name,
            seed_platform=investigation.seed_platform,
            seed_identifier=investigation.seed_identifier,
            # Section 8: the raw input and its detected type, kept alongside the
            # parsed form the crawler actually starts from.
            seed_input=investigation.seed_input or investigation.seed_identifier,
            seed_type=investigation.seed_type,
            status=str(investigation.status),
            status_message=investigation.status_message,
            demo=investigation.demo,
            max_depth=investigation.max_depth,
            max_pages=investigation.max_pages,
            started_at=None,
            completed_at=None,
            created_at=investigation.created_at.isoformat(),
            updated_at=investigation.updated_at.isoformat(),
        ).single()
        return Investigation.from_node(record["i"])

    def get_investigation(self, investigation_id: str) -> Investigation | None:
        record = self.session.run(
            "MATCH (i:Investigation {id: $id}) RETURN i", id=investigation_id
        ).single()
        return Investigation.from_node(record["i"]) if record else None

    def list_investigations(
        self, limit: int = 50, offset: int = 0
    ) -> list[Investigation]:
        """Most recent investigations first."""
        result = self.session.run(
            """
            MATCH (i:Investigation)
            RETURN i ORDER BY i.created_at DESC SKIP $offset LIMIT $limit
            """,
            offset=offset,
            limit=limit,
        )
        return [Investigation.from_node(record["i"]) for record in result]

    def save_investigation(self, investigation: Investigation) -> None:
        """Write back the mutable fields of an investigation."""
        self.session.run(
            """
            MATCH (i:Investigation {id: $id})
            SET i.name = $name,
                i.status = $status,
                i.status_message = $status_message,
                i.max_depth = $max_depth,
                i.max_pages = $max_pages,
                i.started_at = CASE WHEN $started_at IS NULL
                                    THEN NULL ELSE datetime($started_at) END,
                i.completed_at = CASE WHEN $completed_at IS NULL
                                      THEN NULL ELSE datetime($completed_at) END,
                i.updated_at = datetime()
            """,
            id=investigation.id,
            name=investigation.name,
            status=str(investigation.status),
            status_message=investigation.status_message,
            max_depth=investigation.max_depth,
            max_pages=investigation.max_pages,
            started_at=investigation.started_at.isoformat()
            if investigation.started_at
            else None,
            completed_at=investigation.completed_at.isoformat()
            if investigation.completed_at
            else None,
        )

    def delete_investigation(self, investigation_id: str) -> None:
        """Delete an investigation and everything discovered for it."""
        self.session.run(
            """
            MATCH (i:Investigation {id: $id})
            OPTIONAL MATCH (e:Entity {investigation_id: $id})
            OPTIONAL MATCH (e)-[:HAS_SNAPSHOT]->(s:Snapshot)
            OPTIONAL MATCH (v:Evidence {investigation_id: $id})
            OPTIONAL MATCH (c:CrawlEvent {investigation_id: $id})
            DETACH DELETE i, e, s, v, c
            """,
            id=investigation_id,
        )

    def reset_investigation(self, investigation_id: str) -> None:
        """Drop discovered data before a re-crawl, keeping the investigation."""
        self.session.run(
            """
            MATCH (e:Entity {investigation_id: $id})
            OPTIONAL MATCH (e)-[:HAS_SNAPSHOT]->(s:Snapshot)
            DETACH DELETE e, s
            """,
            id=investigation_id,
        )
        self.session.run(
            """
            MATCH (v:Evidence {investigation_id: $id}) DETACH DELETE v
            """,
            id=investigation_id,
        )
        self.session.run(
            """
            MATCH (c:CrawlEvent {investigation_id: $id}) DETACH DELETE c
            """,
            id=investigation_id,
        )

    # -- entities ----------------------------------------------------------

    def upsert_entity(self, entity: Entity) -> Entity:
        """Create or refresh an entity, keyed by type + platform + identity.

        The key is the case-folded identifier, not the observed one.  Handles
        are case-insensitive on every platform here, so keying on the raw text
        recorded ``PrashantRanjitkar`` and ``prashantranjitkar`` as two
        separate accounts - one person appearing twice on the canvas, with the
        relationships between them counted twice over.

        The observed spelling is still kept and shown.  The first one seen
        wins until the platform itself is read, at which point its own
        canonical form takes over - a candidate guessed from another site
        should not outrank how the site in question actually writes it.

        ``first_seen`` is preserved across re-observations while ``last_seen``
        moves, which is what makes the snapshot history meaningful.
        """
        label = type_label(entity.type)
        query = f"""
            MATCH (i:Investigation {{id: $investigation_id}})
            MERGE (e:Entity {{
                investigation_id: $investigation_id,
                type: $type,
                platform: $platform,
                normalized_identifier: $identity_key
            }})
            ON CREATE SET e.id = $id,
                          e.first_seen = datetime($now),
                          e.created_at = datetime($now),
                          e.is_seed = $is_seed,
                          e.identifier = $identifier,
                          e.name = $name
            SET e:{label},
                // Keep the spelling already on record unless this observation
                // came from the platform itself, which is authoritative about
                // how it writes its own handles. The displayed name moves with
                // the identifier: they are the same handle, and a node whose
                // label disagreed with its own identifier would read as two
                // different accounts again.
                e.identifier = CASE WHEN $resolved THEN $identifier
                                    ELSE coalesce(e.identifier, $identifier) END,
                e.name = CASE WHEN $resolved THEN $name
                              ELSE coalesce(e.name, $name) END,
                e.url = coalesce($url, e.url),
                e.display_name = $display_name,
                e.bio = $bio,
                e.avatar_url = $avatar_url,
                e.location = $location,
                e.email = $email,
                e.organization = $organization,
                e.external_links = $external_links,
                e.source = $source,
                e.discovery_method = $discovery_method,
                e.discovered_via = $discovered_via,
                e.depth = $depth,
                e.resolved = $resolved,
                e.is_seed = e.is_seed OR $is_seed,
                e.meta = $meta,
                e.last_seen = datetime($now),
                e.updated_at = datetime($now)
            MERGE (i)-[:DISCOVERED]->(e)
            RETURN e
            """
        record = self.session.run(
            query,
            investigation_id=entity.investigation_id,
            id=entity.id,
            type=str(entity.type),
            platform=entity.platform,
            identifier=entity.identifier,
            identity_key=identity_key(entity.identifier),
            name=entity.name,
            url=entity.url,
            display_name=entity.display_name,
            bio=entity.bio,
            avatar_url=entity.avatar_url,
            location=entity.location,
            email=entity.email,
            organization=entity.organization,
            external_links=list(entity.external_links or []),
            source=entity.source,
            discovery_method=str(entity.discovery_method),
            discovered_via=entity.discovered_via,
            depth=entity.depth,
            resolved=entity.resolved,
            is_seed=entity.is_seed,
            meta=_encode(entity.meta or {}),
            now=datetime.now(UTC).isoformat(),
        ).single()
        return Entity.from_node(record["e"])

    def merge_duplicate_entities(self) -> int:
        """Fold entities that differ only by capitalisation into one node.

        Databases written before identity was case-folded hold the same
        account twice - ``PrashantRanjitkar`` and ``prashantranjitkar`` as
        separate nodes, each with its own relationships and evidence. The new
        uniqueness constraint cannot be created while they are there, so this
        runs first and heals them.

        Nothing is discarded. Every relationship, evidence item and snapshot
        belonging to a duplicate is moved onto the survivor before the
        duplicate is removed; relationships that then collide collapse into
        one by MERGE, which is the correct outcome - they described the same
        association all along.

        The survivor is whichever node was actually read from the platform,
        preferring the earliest, so the spelling that is kept is the one the
        platform published.
        """
        groups = self.session.run(
            """
            MATCH (e:Entity)
            WITH e.investigation_id AS investigation, e.type AS type,
                 e.platform AS platform,
                 toLower(trim(e.identifier)) AS key,
                 collect(e) AS nodes
            WHERE size(nodes) > 1
            RETURN investigation, type, platform, key, nodes
            """
        ).data()

        merged = 0
        for group in groups:
            nodes = group["nodes"]
            # Read-from-the-platform first, then oldest: the spelling kept is
            # the one the platform itself published.
            ordered = sorted(
                nodes,
                key=lambda n: (
                    not n.get("resolved", False),
                    str(n.get("first_seen") or ""),
                    n["id"],
                ),
            )
            survivor = ordered[0]["id"]
            for duplicate in ordered[1:]:
                self._absorb_entity(duplicate["id"], survivor)
                merged += 1

        if merged:
            logger.info("entities_merged count=%d", merged)
        return merged

    def _absorb_entity(self, duplicate_id: str, survivor_id: str) -> None:
        """Move everything attached to one entity onto another, then remove it."""
        for rel_type in RelationshipType:
            name = _relationship_type(rel_type)
            # Outgoing, then incoming. Edges between the two duplicates would
            # become self-loops and are simply dropped.
            self.session.run(
                f"""
                MATCH (d:Entity {{id: $duplicate}})-[r:{name}]->(other:Entity)
                MATCH (s:Entity {{id: $survivor}})
                WITH r, s, other WHERE other.id <> $survivor
                MERGE (s)-[n:{name} {{investigation_id: r.investigation_id}}]->(other)
                ON CREATE SET n = properties(r), n.source_entity_id = $survivor
                DELETE r
                """,
                duplicate=duplicate_id,
                survivor=survivor_id,
            )
            self.session.run(
                f"""
                MATCH (other:Entity)-[r:{name}]->(d:Entity {{id: $duplicate}})
                MATCH (s:Entity {{id: $survivor}})
                WITH r, s, other WHERE other.id <> $survivor
                MERGE (other)-[n:{name} {{investigation_id: r.investigation_id}}]->(s)
                ON CREATE SET n = properties(r), n.target_entity_id = $survivor
                DELETE r
                """,
                duplicate=duplicate_id,
                survivor=survivor_id,
            )

        # Evidence and snapshots refer to entities by id rather than by edge.
        self.session.run(
            """
            MATCH (v:Evidence) WHERE v.source_entity_id = $duplicate
            SET v.source_entity_id = $survivor
            """,
            duplicate=duplicate_id,
            survivor=survivor_id,
        )
        self.session.run(
            """
            MATCH (v:Evidence) WHERE v.target_entity_id = $duplicate
            SET v.target_entity_id = $survivor
            """,
            duplicate=duplicate_id,
            survivor=survivor_id,
        )
        self.session.run(
            """
            MATCH (d:Entity {id: $duplicate})-[:HAS_SNAPSHOT]->(snap:Snapshot)
            MATCH (s:Entity {id: $survivor})
            SET snap.entity_id = $survivor
            MERGE (s)-[:HAS_SNAPSHOT]->(snap)
            """,
            duplicate=duplicate_id,
            survivor=survivor_id,
        )
        self.session.run(
            "MATCH (d:Entity {id: $duplicate}) DETACH DELETE d",
            duplicate=duplicate_id,
        )

    def get_entity(self, entity_id: str) -> Entity | None:
        record = self.session.run(
            "MATCH (e:Entity {id: $id}) RETURN e", id=entity_id
        ).single()
        return Entity.from_node(record["e"]) if record else None

    def list_entities(
        self, investigation_id: str, entity_type: str | None = None
    ) -> list[Entity]:
        """Every entity for an investigation, shallowest first."""
        result = self.session.run(
            """
            MATCH (e:Entity {investigation_id: $id})
            WHERE $type IS NULL OR e.type = $type
            RETURN e ORDER BY e.depth, e.created_at
            """,
            id=investigation_id,
            type=str(entity_type) if entity_type else None,
        )
        return [Entity.from_node(record["e"]) for record in result]

    def seed_entity(self, investigation_id: str) -> Entity | None:
        record = self.session.run(
            """
            MATCH (e:Entity {investigation_id: $id, is_seed: true})
            RETURN e LIMIT 1
            """,
            id=investigation_id,
        ).single()
        return Entity.from_node(record["e"]) if record else None

    # -- relationships -----------------------------------------------------

    def upsert_relationship(self, relationship: Relationship) -> Relationship:
        """Create or refresh a scored edge, preserving the analyst's verdict.

        Re-running a crawl must not silently discard a decision an analyst
        already made, so ``analyst_status`` and ``analyst_note`` are only set
        when the edge is first created.
        """
        rel_type = _relationship_type(relationship.relationship_type)
        query = f"""
            MATCH (s:Entity {{id: $source_id}})
            MATCH (t:Entity {{id: $target_id}})
            MERGE (s)-[r:{rel_type} {{investigation_id: $investigation_id}}]->(t)
            ON CREATE SET r.id = $id,
                          r.created_at = datetime($now),
                          r.origin = $origin,
                          r.analyst_status = $analyst_status,
                          r.analyst_note = NULL,
                          r.reviewed_at = NULL
            SET r.relationship_type = $relationship_type,
                r.source_entity_id = $source_id,
                r.target_entity_id = $target_id,
                r.confidence_score = $score,
                r.confidence_level = $level,
                r.summary = $summary,
                r.updated_at = datetime($now)
            RETURN r
            """
        record = self.session.run(
            query,
            investigation_id=relationship.investigation_id,
            id=relationship.id,
            source_id=relationship.source_entity_id,
            target_id=relationship.target_entity_id,
            relationship_type=rel_type,
            score=round(float(relationship.confidence_score), 1),
            level=str(relationship.confidence_level),
            summary=relationship.summary,
            origin=str(RelationshipOrigin.ENGINE),
            analyst_status=str(AnalystStatus.UNREVIEWED),
            now=datetime.now(UTC).isoformat(),
        ).single()
        return Relationship.from_edge(record["r"])

    def create_manual_relationship(self, relationship: Relationship) -> Relationship:
        """Record a link an analyst drew by hand.

        Kept apart from :meth:`upsert_relationship` because the two say
        different things.  That one refreshes a score the engine derived; this
        one asserts a connection on a person's authority, so it writes the
        verdict and the note it was created with, and stamps the edge as
        analyst-asserted for anyone reading the investigation later.
        """
        rel_type = _relationship_type(relationship.relationship_type)
        query = f"""
            MATCH (s:Entity {{id: $source_id}})
            MATCH (t:Entity {{id: $target_id}})
            MERGE (s)-[r:{rel_type} {{investigation_id: $investigation_id}}]->(t)
            ON CREATE SET r.id = $id,
                          r.created_at = datetime($now),
                          r.origin = $origin
            SET r.relationship_type = $relationship_type,
                r.source_entity_id = $source_id,
                r.target_entity_id = $target_id,
                r.confidence_score = $score,
                r.confidence_level = $level,
                r.summary = $summary,
                r.analyst_status = $analyst_status,
                r.analyst_note = $analyst_note,
                r.reviewed_at = datetime($now),
                r.updated_at = datetime($now)
            RETURN r
            """
        record = self.session.run(
            query,
            investigation_id=relationship.investigation_id,
            id=relationship.id,
            source_id=relationship.source_entity_id,
            target_id=relationship.target_entity_id,
            relationship_type=rel_type,
            score=round(float(relationship.confidence_score), 1),
            level=str(relationship.confidence_level),
            summary=relationship.summary,
            origin=str(RelationshipOrigin.ANALYST),
            analyst_status=str(relationship.analyst_status),
            analyst_note=relationship.analyst_note,
            now=datetime.now(UTC).isoformat(),
        ).single()
        return Relationship.from_edge(record["r"])

    def delete_relationship(self, relationship_id: str) -> bool:
        """Remove one relationship and the evidence written for it.

        Only ever called for analyst-asserted links.  Deleting an edge the
        engine derived would destroy observations that were actually made, so
        the API refuses it; retracting a machine finding is what REJECTED is
        for.
        """
        self.session.run(
            "MATCH (v:Evidence {relationship_id: $id}) DETACH DELETE v",
            id=relationship_id,
        )
        record = self.session.run(
            """
            MATCH ()-[r {id: $id}]->()
            DELETE r
            RETURN count(r) AS removed
            """,
            id=relationship_id,
        ).single()
        return bool(record and record["removed"])

    def list_relationships_of_type(
        self, investigation_id: str, relationship_type: str
    ) -> list[Relationship]:
        """Relationships of one type, strongest first.

        The type is validated against the enum before it reaches Cypher, which
        is what makes interpolating it safe.
        """
        rel_type = _relationship_type(relationship_type)
        result = self.session.run(
            f"""
            MATCH (:Entity)-[r:{rel_type} {{investigation_id: $id}}]->(:Entity)
            RETURN r ORDER BY r.confidence_score DESC
            """,
            id=investigation_id,
        )
        return [Relationship.from_edge(record["r"]) for record in result]

    def get_relationship(self, relationship_id: str) -> Relationship | None:
        record = self.session.run(
            "MATCH ()-[r {id: $id}]->() RETURN r LIMIT 1", id=relationship_id
        ).single()
        return Relationship.from_edge(record["r"]) if record else None

    def list_relationships(
        self, investigation_id: str, min_score: float = 0.0
    ) -> list[Relationship]:
        """Relationships for an investigation, strongest first."""
        result = self.session.run(
            """
            MATCH (:Entity)-[r {investigation_id: $id}]->(:Entity)
            WHERE r.confidence_score >= $min_score
            RETURN r ORDER BY r.confidence_score DESC
            """,
            id=investigation_id,
            min_score=min_score,
        )
        return [Relationship.from_edge(record["r"]) for record in result]

    def relationships_for_entity(self, entity_id: str) -> list[Relationship]:
        """Every relationship with this entity at either end."""
        result = self.session.run(
            """
            MATCH (a:Entity {id: $id})-[r]-(b:Entity)
            WHERE r.id IS NOT NULL
            RETURN DISTINCT r ORDER BY r.confidence_score DESC
            """,
            id=entity_id,
        )
        return [Relationship.from_edge(record["r"]) for record in result]

    def find_paths(
        self,
        investigation_id: str,
        source_entity_id: str,
        target_entity_id: str,
        *,
        max_depth: int,
        max_paths: int,
    ) -> list[dict[str, Any]]:
        """Bounded, parameterized search for paths between two entities.

        Every value is a query parameter except the depth bound, which Cypher
        cannot parameterize inside a variable-length pattern - so it is coerced
        to an ``int`` and clamped by the caller before it reaches here. No
        analyst-supplied text ever reaches the query text.

        The traversal is confined to entities of this investigation, so one
        investigation can never be used to walk into another.
        """
        depth = max(1, min(int(max_depth), 10))
        limit = max(1, min(int(max_paths), 50))

        result = self.session.run(
            f"""
            MATCH (a:Entity {{id: $source, investigation_id: $investigation}}),
                  (b:Entity {{id: $target, investigation_id: $investigation}})
            MATCH path = (a)-[rels*1..{depth}]-(b)
            WHERE ALL(r IN rels WHERE r.investigation_id = $investigation)
              AND ALL(n IN nodes(path) WHERE n.investigation_id = $investigation)
            WITH path, rels,
                 reduce(total = 0.0, r IN rels | total + coalesce(r.confidence_score, 0.0))
                   AS total_score,
                 size([r IN rels WHERE r.analyst_status = 'CONFIRMED']) AS confirmed,
                 size([r IN rels WHERE r.analyst_status = 'REJECTED']) AS rejected,
                 size([r IN rels WHERE r.relationship_type = 'CONTRADICTORY'])
                   AS contradictions
            RETURN [n IN nodes(path) | n.id] AS node_ids,
                   [r IN rels | r.id] AS relationship_ids,
                   size(rels) AS length,
                   total_score,
                   confirmed,
                   rejected,
                   contradictions
            ORDER BY rejected ASC, contradictions ASC, length ASC, total_score DESC
            LIMIT $limit
            """,
            investigation=investigation_id,
            source=source_entity_id,
            target=target_entity_id,
            limit=limit,
        )
        return [dict(record) for record in result]

    def set_analyst_status(
        self, relationship_id: str, status: str, note: str | None
    ) -> Relationship | None:
        """Record an analyst verdict, with the time it was made (section 25)."""
        record = self.session.run(
            """
            MATCH ()-[r {id: $id}]->()
            SET r.analyst_status = $status,
                r.analyst_note = CASE WHEN $note IS NULL
                                      THEN r.analyst_note ELSE $note END,
                r.reviewed_at = CASE WHEN $status = $unreviewed
                                     THEN NULL ELSE datetime() END,
                r.updated_at = datetime()
            RETURN r
            """,
            id=relationship_id,
            status=str(status),
            note=note,
            unreviewed=str(AnalystStatus.UNREVIEWED),
        ).single()
        return Relationship.from_edge(record["r"]) if record else None

    def analyst_status_counts(self, investigation_id: str) -> dict[str, int]:
        """``{status: count}`` across an investigation's relationships."""
        result = self.session.run(
            """
            MATCH (:Entity)-[r {investigation_id: $id}]->(:Entity)
            RETURN r.analyst_status AS status, count(r) AS total
            """,
            id=investigation_id,
        )
        return {record["status"]: record["total"] for record in result}

    # -- evidence ----------------------------------------------------------

    def add_evidence(self, items: Iterable[Evidence]) -> int:
        """Write evidence nodes in one round trip and link them up."""
        payload = [
            {
                "id": item.id,
                "investigation_id": item.investigation_id,
                "relationship_id": item.relationship_id,
                "source_entity_id": item.source_entity_id,
                "target_entity_id": item.target_entity_id,
                "type": str(item.type),
                "description": item.description,
                "source_url": item.source_url,
                "extracted_value": item.extracted_value,
                "normalized_value": item.normalized_value,
                "weight": float(item.weight),
                "supports": bool(item.supports),
                "context": _encode(item.context),
                "collected_at": item.collected_at.isoformat(),
            }
            for item in items
        ]
        if not payload:
            return 0
        self.session.run(
            """
            UNWIND $items AS item
            MATCH (i:Investigation {id: item.investigation_id})
            CREATE (v:Evidence {
                id: item.id,
                investigation_id: item.investigation_id,
                relationship_id: item.relationship_id,
                source_entity_id: item.source_entity_id,
                target_entity_id: item.target_entity_id,
                type: item.type,
                description: item.description,
                source_url: item.source_url,
                extracted_value: item.extracted_value,
                normalized_value: item.normalized_value,
                weight: item.weight,
                supports: item.supports,
                context: item.context,
                collected_at: datetime(item.collected_at)
            })
            CREATE (i)-[:COLLECTED]->(v)
            WITH v, item
            MATCH (s:Entity {id: item.source_entity_id})
            CREATE (v)-[:CONCERNS]->(s)
            WITH v, item
            OPTIONAL MATCH (t:Entity {id: item.target_entity_id})
            FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END |
                CREATE (v)-[:CONCERNS]->(t))
            """,
            items=payload,
        )
        return len(payload)

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        record = self.session.run(
            "MATCH (v:Evidence {id: $id}) RETURN v", id=evidence_id
        ).single()
        return Evidence.from_node(record["v"]) if record else None

    def evidence_for_relationship(self, relationship_id: str) -> list[Evidence]:
        """Observations behind one score, heaviest first."""
        result = self.session.run(
            """
            MATCH (v:Evidence {relationship_id: $id})
            RETURN v ORDER BY v.weight DESC
            """,
            id=relationship_id,
        )
        return [Evidence.from_node(record["v"]) for record in result]

    def attach_evidence(self, relationships: list[Relationship]) -> list[Relationship]:
        """Populate ``.evidence`` on each relationship in one round trip.

        List views show an evidence count next to every score, so fetching the
        observations per relationship would mean N queries for one screen.
        """
        if not relationships:
            return relationships
        ids = [relationship.id for relationship in relationships]
        result = self.session.run(
            """
            MATCH (v:Evidence) WHERE v.relationship_id IN $ids
            RETURN v ORDER BY v.weight DESC
            """,
            ids=ids,
        )
        grouped: dict[str, list[Evidence]] = {}
        for record in result:
            item = Evidence.from_node(record["v"])
            grouped.setdefault(item.relationship_id or "", []).append(item)
        for relationship in relationships:
            relationship.evidence = grouped.get(relationship.id, [])
        return relationships

    def evidence_between_entities(
        self, investigation_id: str, first_id: str, second_id: str
    ) -> list[Evidence]:
        """Every observation about a pair, whichever relationship holds it.

        Contradictions are recorded against the relationship they weaken, so an
        alias edge does not itself carry the conflicting-website row that
        pushed its score down.  Reading by entity pair is what lets the alias
        view still show an analyst *why* it scored low.
        """
        result = self.session.run(
            """
            MATCH (v:Evidence {investigation_id: $id})
            WHERE (v.source_entity_id = $a AND v.target_entity_id = $b)
               OR (v.source_entity_id = $b AND v.target_entity_id = $a)
            RETURN v ORDER BY v.weight DESC
            """,
            id=investigation_id,
            a=first_id,
            b=second_id,
        )
        return [Evidence.from_node(record["v"]) for record in result]

    def list_evidence(self, investigation_id: str) -> list[Evidence]:
        result = self.session.run(
            """
            MATCH (v:Evidence {investigation_id: $id})
            RETURN v ORDER BY v.collected_at
            """,
            id=investigation_id,
        )
        return [Evidence.from_node(record["v"]) for record in result]

    def evidence_counts(self, investigation_id: str) -> dict[str, tuple[int, int]]:
        """``relationship_id -> (total evidence, contradictions)``."""
        result = self.session.run(
            """
            MATCH (v:Evidence {investigation_id: $id})
            WHERE v.relationship_id IS NOT NULL
            RETURN v.relationship_id AS rid,
                   count(v) AS total,
                   sum(CASE WHEN v.supports THEN 0 ELSE 1 END) AS against
            """,
            id=investigation_id,
        )
        return {
            record["rid"]: (int(record["total"]), int(record["against"] or 0))
            for record in result
        }

    # -- snapshots ---------------------------------------------------------

    def add_snapshots(self, snapshots: Iterable[Snapshot]) -> int:
        """Store point-in-time copies of entity profiles (section 28)."""
        payload = [
            {
                "id": snapshot.id,
                "entity_id": snapshot.entity_id,
                "timestamp": snapshot.timestamp.isoformat(),
                "username": snapshot.username,
                "display_name": snapshot.display_name,
                "bio": snapshot.bio,
                "avatar_url": snapshot.avatar_url,
                "external_links": list(snapshot.external_links or []),
                "meta": _encode(snapshot.meta or {}),
            }
            for snapshot in snapshots
        ]
        if not payload:
            return 0
        self.session.run(
            """
            UNWIND $items AS item
            MATCH (e:Entity {id: item.entity_id})
            CREATE (s:Snapshot {
                id: item.id,
                entity_id: item.entity_id,
                timestamp: datetime(item.timestamp),
                username: item.username,
                display_name: item.display_name,
                bio: item.bio,
                avatar_url: item.avatar_url,
                external_links: item.external_links,
                meta: item.meta
            })
            CREATE (e)-[:HAS_SNAPSHOT]->(s)
            """,
            items=payload,
        )
        return len(payload)

    def snapshots_for_entity(self, entity_id: str) -> list[Snapshot]:
        result = self.session.run(
            """
            MATCH (:Entity {id: $id})-[:HAS_SNAPSHOT]->(s:Snapshot)
            RETURN s ORDER BY s.timestamp
            """,
            id=entity_id,
        )
        return [Snapshot.from_node(record["s"]) for record in result]

    # -- timeline ----------------------------------------------------------

    def add_events(self, events: Iterable[CrawlEvent]) -> int:
        """Append lines to the investigation activity timeline."""
        payload = [
            {
                "id": event.id,
                "investigation_id": event.investigation_id,
                "timestamp": event.timestamp.isoformat(),
                "level": event.level,
                "event": event.event,
                "message": event.message,
                "data": _encode(event.data),
            }
            for event in events
        ]
        if not payload:
            return 0
        self.session.run(
            """
            MATCH (i:Investigation {id: $investigation_id})
            OPTIONAL MATCH (existing:CrawlEvent {investigation_id: $investigation_id})
            // reduce() over collected values rather than max(), which warns
            // when the OPTIONAL MATCH found nothing.
            WITH i, [s IN collect(existing.sequence) WHERE s IS NOT NULL] AS seen
            WITH i, reduce(top = 0, s IN seen |
                     CASE WHEN s > top THEN s ELSE top END) AS base
            UNWIND range(0, size($items) - 1) AS index
            WITH i, base, index, $items[index] AS item
            CREATE (c:CrawlEvent {
                id: item.id,
                investigation_id: item.investigation_id,
                timestamp: datetime(item.timestamp),
                level: item.level,
                event: item.event,
                message: item.message,
                data: item.data,
                sequence: base + index + 1
            })
            CREATE (i)-[:LOGGED]->(c)
            """,
            investigation_id=payload[0]["investigation_id"],
            items=payload,
        )
        return len(payload)

    def list_events(
        self, investigation_id: str, limit: int = 500, events: list[str] | None = None
    ) -> list[CrawlEvent]:
        """The persisted crawl timeline, oldest first."""
        result = self.session.run(
            """
            MATCH (c:CrawlEvent {investigation_id: $id})
            WHERE $events IS NULL OR c.event IN $events
            RETURN c ORDER BY c.sequence LIMIT $limit
            """,
            id=investigation_id,
            events=events,
            limit=limit,
        )
        return [CrawlEvent.from_node(record["c"]) for record in result]

    # -- counts ------------------------------------------------------------

    def counts(self, investigation_id: str) -> tuple[int, int, int]:
        """``(entities, relationships, evidence)`` for one investigation."""
        record = self.session.run(
            """
            MATCH (i:Investigation {id: $id})
            OPTIONAL MATCH (e:Entity {investigation_id: $id})
            WITH i, count(DISTINCT e) AS entities
            OPTIONAL MATCH (:Entity)-[r {investigation_id: $id}]->(:Entity)
            WITH i, entities, count(DISTINCT r) AS relationships
            OPTIONAL MATCH (v:Evidence {investigation_id: $id})
            RETURN entities, relationships, count(DISTINCT v) AS evidence
            """,
            id=investigation_id,
        ).single()
        if record is None:
            return (0, 0, 0)
        return (
            int(record["entities"] or 0),
            int(record["relationships"] or 0),
            int(record["evidence"] or 0),
        )

    def platform_totals(self) -> dict[str, int]:
        """``{platform: entity count}`` across every investigation."""
        result = self.session.run(
            """
            MATCH (e:Entity)
            RETURN e.platform AS platform, count(e) AS total ORDER BY total DESC
            """
        )
        return {record["platform"]: record["total"] for record in result}

    def global_stats(self) -> dict[str, int]:
        """Dashboard headline numbers (section 19)."""
        record = self.session.run(
            """
            MATCH (i:Investigation)
            WITH count(i) AS investigations
            OPTIONAL MATCH (e:Entity)
            WITH investigations, count(e) AS entities
            OPTIONAL MATCH (:Entity)-[r]->(:Entity) WHERE r.id IS NOT NULL
            WITH investigations, entities, count(r) AS relationships,
                 sum(CASE WHEN r.analyst_status = 'CONFIRMED' THEN 1 ELSE 0 END)
                   AS confirmed,
                 sum(CASE WHEN r.analyst_status = 'REJECTED' THEN 1 ELSE 0 END)
                   AS rejected
            RETURN investigations, entities, relationships, confirmed, rejected
            """
        ).single()
        if record is None:  # pragma: no cover - empty database
            return {
                "investigations": 0,
                "entities": 0,
                "relationships": 0,
                "confirmed": 0,
                "rejected": 0,
            }
        # Named explicitly: iterating a neo4j Record yields values, not keys.
        return {
            key: int(record[key] or 0)
            for key in (
                "investigations",
                "entities",
                "relationships",
                "confirmed",
                "rejected",
            )
        }
