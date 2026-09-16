"""Graph service and Neo4j persistence: entities, duplicates, relationships, evidence."""

from __future__ import annotations

import pytest

from app.models.enums import EntityType, InvestigationStatus, RelationshipType
from app.schemas.investigation import InvestigationCreate
from app.services.graph import GraphService
from app.services.investigation import InvestigationService


@pytest.fixture
async def investigation(repo):
    """A completed demo investigation."""
    service = InvestigationService(repo)
    created = service.create(
        InvestigationCreate(identifier="@alice_98", platform="instagram", demo=True)
    )
    await service.run(created)
    return created


async def test_entities_are_created_for_the_seed_and_its_discoveries(
    repo, investigation
):
    entities = repo.list_entities(investigation.id)
    labels = {entity.label for entity in entities}

    assert investigation.status == InvestigationStatus.COMPLETED
    assert "instagram:alice_98" in labels
    assert "website:alice.dev" in labels
    assert "github:alice-security" in labels
    assert sum(entity.is_seed for entity in entities) == 1

    types = {entity.type for entity in entities}
    assert EntityType.ACCOUNT in types
    assert EntityType.WEBSITE in types


async def test_entities_carry_their_neo4j_type_label(repo, investigation):
    """An account is stored as ``(:Entity:Account)``, a website as ``(:Website)``.

    The documented model in section 7 is queried by label, so the labels have
    to be real - not just a ``type`` property.
    """
    accounts = repo.session.run(
        "MATCH (n:Account {investigation_id: $id}) RETURN count(n) AS total",
        id=investigation.id,
    ).single()["total"]
    websites = repo.session.run(
        "MATCH (n:Website {investigation_id: $id}) RETURN count(n) AS total",
        id=investigation.id,
    ).single()["total"]
    assert accounts > 0
    assert websites > 0


async def test_entities_are_not_duplicated_across_runs(repo, investigation):
    """Re-running discovery updates entities instead of duplicating them."""
    before = len(repo.list_entities(investigation.id))
    await InvestigationService(repo).run(investigation, reset=False)
    after = repo.list_entities(investigation.id)
    assert len(after) == before

    keys = [entity.key for entity in after]
    assert len(keys) == len(set(keys))


async def test_relationships_are_created_and_deduplicated(repo, investigation):
    before = len(repo.list_relationships(investigation.id))
    assert before > 0

    await InvestigationService(repo).run(investigation, reset=False)
    assert len(repo.list_relationships(investigation.id)) == before

    types = {
        relationship.relationship_type
        for relationship in repo.list_relationships(investigation.id)
    }
    assert RelationshipType.LINKS_TO in types
    assert RelationshipType.POTENTIAL_SAME_IDENTITY in types


async def test_every_relationship_has_evidence_attached(repo, investigation):
    relationships = repo.attach_evidence(repo.list_relationships(investigation.id))
    assert relationships
    for relationship in relationships:
        assert relationship.evidence, f"{relationship.id} has no evidence"
        assert relationship.evidence_ids
        for item in relationship.evidence:
            assert item.description
            assert item.investigation_id == investigation.id


async def test_snapshots_record_every_resolved_observation(repo, investigation):
    resolved = [
        entity for entity in repo.list_entities(investigation.id) if entity.resolved
    ]
    assert resolved
    for entity in resolved:
        assert repo.snapshots_for_entity(entity.id)


async def test_graph_payload_is_renderable(repo, investigation):
    graph = GraphService(repo).build(investigation)
    entities, relationships, evidence = repo.counts(investigation.id)

    assert graph.investigation_id == investigation.id
    assert graph.seed_entity_id
    assert len(graph.nodes) == entities
    assert len(graph.edges) == relationships

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
    assert graph.stats.evidence == evidence
    assert graph.stats.contradictions >= 1


async def test_a_website_seed_is_typed_as_a_website():
    """The seed's entity type follows its platform, not a default of ACCOUNT."""
    from app.services.discovery import seed_candidate

    assert seed_candidate("website", "alice.dev").entity_type == EntityType.WEBSITE
    assert seed_candidate("instagram", "alice_98").entity_type == EntityType.ACCOUNT


async def test_graph_layout_is_deterministic(repo, investigation):
    first = GraphService(repo).build(investigation)
    second = GraphService(repo).build(investigation)
    assert [(node.id, node.position.x, node.position.y) for node in first.nodes] == [
        (node.id, node.position.x, node.position.y) for node in second.nodes
    ]


async def test_analyst_decision_is_preserved_across_recrawl(repo, investigation):
    """A verdict an analyst already recorded must survive a re-run."""
    relationship = repo.list_relationships(investigation.id)[0]
    repo.set_analyst_status(relationship.id, "CONFIRMED", "Checked the evidence.")

    await InvestigationService(repo).run(investigation, reset=False)

    refreshed = repo.get_relationship(relationship.id)
    assert refreshed.analyst_status == "CONFIRMED"
    assert refreshed.analyst_note == "Checked the evidence."
    assert refreshed.reviewed_at is not None


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


async def test_the_seed_sits_at_the_top(repo) -> None:
    """An investigation hangs from the thing it started with."""
    from app.schemas.investigation import InvestigationCreate
    from app.services.graph import GraphService
    from app.services.investigation import InvestigationService

    service = InvestigationService(repo)
    created = service.create(
        InvestigationCreate(identifier="alice_98", platform="instagram", demo=True)
    )
    await service.run(created)

    graph = GraphService(repo).build(created)
    seed = next(node for node in graph.nodes if node.is_seed)

    assert (seed.position.x, seed.position.y) == (0.0, 0.0)


async def test_the_tree_grows_downward_from_the_seed(repo) -> None:
    """Hop distance reads down the screen, and only downward.

    The layout is a tree now rather than a ring, so the property worth
    holding is the one a tree promises: everything reached from the seed is
    below it, and a card is below the card it was reached through. A row that
    drifts upward would say the crawl went the other way.
    """
    from app.schemas.investigation import InvestigationCreate
    from app.services.graph import GraphService
    from app.services.investigation import InvestigationService

    service = InvestigationService(repo)
    created = service.create(
        InvestigationCreate(identifier="alice_98", platform="instagram", demo=True)
    )
    await service.run(created)

    graph = GraphService(repo).build(created)
    seed = next(node for node in graph.nodes if node.is_seed)
    by_id = {node.id: node for node in graph.nodes}

    assert all(node.position.y >= seed.position.y for node in graph.nodes)
    assert max(node.position.y for node in graph.nodes) > seed.position.y

    # Everything the seed touches hangs below it, strictly - the one
    # parent-child relationship the payload states plainly enough to check.
    kin = [
        by_id[edge.target if edge.source == seed.id else edge.source]
        for edge in graph.edges
        if seed.id in (edge.source, edge.target)
    ]
    assert kin, "the seed should be connected to something"
    for node in kin:
        assert node.position.y > seed.position.y, (
            f"{node.label} was reached from the seed but is drawn level with "
            "it or above it"
        )

    # And a parent sits over its children rather than off to one side.
    if len(kin) > 1:
        xs = [node.position.x for node in kin]
        assert min(xs) <= seed.position.x <= max(xs), (
            "the seed is not centred over what it found"
        )


async def test_no_two_cards_overlap(repo) -> None:
    """Cards are boxes, so the check has to be about boxes.

    This measured straight-line distance against a single threshold, which
    quietly assumed a square card. A node actually renders about 185x109 -
    nearly twice as wide as it is tall - so one number was simultaneously too
    slack horizontally and far too strict vertically, and the strict half was
    holding the levels three times further apart than the columns for no
    reason anyone had checked.
    """
    from app.schemas.investigation import InvestigationCreate
    from app.services.graph import GraphService
    from app.services.investigation import InvestigationService

    # The measured card, rounded up, so the assertion has a little margin.
    card_width, card_height = 200, 120

    service = InvestigationService(repo)
    created = service.create(
        InvestigationCreate(identifier="alice_98", platform="instagram", demo=True)
    )
    await service.run(created)

    graph = GraphService(repo).build(created)
    points = [(node.id, node.position.x, node.position.y) for node in graph.nodes]
    for index, (first, x1, y1) in enumerate(points):
        for second, x2, y2 in points[index + 1 :]:
            assert abs(x1 - x2) >= card_width or abs(y1 - y2) >= card_height, (
                f"{first} and {second} overlap: "
                f"{abs(x1 - x2):.0f}px apart across, {abs(y1 - y2):.0f}px down"
            )


def test_an_empty_investigation_lays_out_to_nothing() -> None:
    import networkx as nx

    from app.services.graph import GraphService

    assert GraphService._layout(nx.Graph(), []) == {}
