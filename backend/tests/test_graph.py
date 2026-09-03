"""Graph service and persistence: entities, duplicates, relationships, evidence."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models.entity import Entity
from app.models.enums import EntityType, InvestigationStatus, RelationshipType
from app.models.evidence import Evidence
from app.models.relationship import Relationship
from app.models.snapshot import Snapshot
from app.schemas.investigation import InvestigationCreate
from app.services.graph import GraphService
from app.services.investigation import InvestigationService


@pytest.fixture
async def investigation(db):
    """A completed demo investigation."""
    service = InvestigationService(db)
    created = service.create(
        InvestigationCreate(identifier="@alice_98", platform="instagram", demo=True)
    )
    await service.run(created)
    return created


def count(db, model, investigation_id: str) -> int:
    return db.scalar(
        select(func.count(model.id)).where(model.investigation_id == investigation_id)
    )


async def test_entities_are_created_for_the_seed_and_its_discoveries(db, investigation):
    entities = list(
        db.scalars(select(Entity).where(Entity.investigation_id == investigation.id))
    )
    labels = {entity.label for entity in entities}

    assert investigation.status == InvestigationStatus.COMPLETED
    assert "instagram:alice_98" in labels
    assert "website:alice.dev" in labels
    assert "github:alice-security" in labels
    assert sum(entity.is_seed for entity in entities) == 1

    types = {entity.type for entity in entities}
    assert EntityType.ACCOUNT in types
    assert EntityType.WEBSITE in types


async def test_entities_are_not_duplicated_across_runs(db, investigation):
    """Re-running discovery updates entities instead of duplicating them."""
    before = count(db, Entity, investigation.id)
    await InvestigationService(db).run(investigation, reset=False)
    after = count(db, Entity, investigation.id)
    assert after == before

    duplicates = db.execute(
        select(Entity.type, Entity.platform, Entity.identifier, func.count(Entity.id))
        .where(Entity.investigation_id == investigation.id)
        .group_by(Entity.type, Entity.platform, Entity.identifier)
        .having(func.count(Entity.id) > 1)
    ).all()
    assert duplicates == []


async def test_relationships_are_created_and_deduplicated(db, investigation):
    before = count(db, Relationship, investigation.id)
    assert before > 0

    await InvestigationService(db).run(investigation, reset=False)
    assert count(db, Relationship, investigation.id) == before

    types = set(
        db.scalars(
            select(Relationship.relationship_type).where(
                Relationship.investigation_id == investigation.id
            )
        )
    )
    assert RelationshipType.LINKS_TO in types
    assert RelationshipType.POTENTIAL_SAME_IDENTITY in types


async def test_every_relationship_has_evidence_attached(db, investigation):
    relationships = list(
        db.scalars(
            select(Relationship).where(
                Relationship.investigation_id == investigation.id
            )
        )
    )
    assert relationships
    for relationship in relationships:
        assert relationship.evidence, f"{relationship.id} has no evidence"
        assert relationship.evidence_ids
        for item in relationship.evidence:
            assert item.description
            assert item.investigation_id == investigation.id


async def test_snapshots_record_every_resolved_observation(db, investigation):
    resolved = list(
        db.scalars(
            select(Entity).where(
                Entity.investigation_id == investigation.id, Entity.resolved.is_(True)
            )
        )
    )
    assert resolved
    for entity in resolved:
        snapshots = db.scalars(
            select(Snapshot).where(Snapshot.entity_id == entity.id)
        ).all()
        assert snapshots


async def test_graph_payload_is_renderable(db, investigation):
    graph = GraphService(db).build(investigation)

    assert graph.investigation_id == investigation.id
    assert graph.seed_entity_id
    assert len(graph.nodes) == count(db, Entity, investigation.id)
    assert len(graph.edges) == count(db, Relationship, investigation.id)

    node_ids = {node.id for node in graph.nodes}
    for edge in graph.edges:
        assert edge.source in node_ids and edge.target in node_ids
        assert edge.relationship_label
        assert edge.evidence_count >= 1

    seed = next(node for node in graph.nodes if node.is_seed)
    assert seed.depth == 0
    assert seed.position.y == 0
    # Deeper entities are laid out below their parents.
    assert max(node.position.y for node in graph.nodes) > 0
    assert graph.stats.entities == len(graph.nodes)
    assert graph.stats.evidence == count(db, Evidence, investigation.id)
    assert graph.stats.contradictions >= 1


async def test_a_website_seed_is_typed_as_a_website(db):
    """The seed's entity type follows its platform, not a default of ACCOUNT."""
    from app.services.discovery import seed_candidate

    assert seed_candidate("website", "alice.dev").entity_type == EntityType.WEBSITE
    assert seed_candidate("instagram", "alice_98").entity_type == EntityType.ACCOUNT


async def test_graph_layout_is_deterministic(db, investigation):
    first = GraphService(db).build(investigation)
    second = GraphService(db).build(investigation)
    assert [(node.id, node.position.x, node.position.y) for node in first.nodes] == [
        (node.id, node.position.x, node.position.y) for node in second.nodes
    ]
