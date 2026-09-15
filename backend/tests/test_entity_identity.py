"""One account, one node - whatever capitalisation it was observed under.

A real crawl of "prashantranjitkar" produced twelve nodes for seven accounts:
five platforms held both `PrashantRanjitkar` and `prashantranjitkar`, because
GitHub publishes the canonical capitalisation and the handle was then fanned
out to other sites in that form. The same person appeared twice on the canvas,
with the relationships between the halves counted twice over.
"""

from __future__ import annotations

import pytest

from app.models.entity import Entity
from app.models.enums import EntityType
from app.utils.normalization import identity_key


def make(repo, investigation_id: str, identifier: str, **kwargs) -> Entity:
    return repo.upsert_entity(
        Entity(
            investigation_id=investigation_id,
            platform=kwargs.pop("platform", "instagram"),
            type=kwargs.pop("type", str(EntityType.ACCOUNT)),
            name=f"@{identifier}",
            identifier=identifier,
            **kwargs,
        )
    )


def test_the_key_folds_case_and_whitespace() -> None:
    assert identity_key("PrashantRanjitkar") == "prashantranjitkar"
    assert identity_key("  Alice_98 ") == "alice_98"
    assert identity_key(None) == ""


@pytest.fixture
def investigation(repo):
    from app.schemas.investigation import InvestigationCreate
    from app.services.investigation import InvestigationService

    return InvestigationService(repo).create(
        InvestigationCreate(identifier="prashantranjitkar", demo=True, auto_crawl=False)
    )


def test_one_account_seen_twice_is_one_node(repo, investigation) -> None:
    first = make(repo, investigation.id, "prashantranjitkar")
    second = make(repo, investigation.id, "PrashantRanjitkar")

    assert first.id == second.id, "the same account must not become two nodes"
    accounts = [
        e for e in repo.list_entities(investigation.id) if e.platform == "instagram"
    ]
    assert len(accounts) == 1


def test_the_first_spelling_stands_until_the_platform_is_read(
    repo, investigation
) -> None:
    """A guess from another site should not overwrite how a handle was seen."""
    make(repo, investigation.id, "prashantranjitkar")
    make(repo, investigation.id, "PrashantRanjitkar")

    entity = repo.list_entities(investigation.id)[0]
    assert entity.identifier == "prashantranjitkar"


def test_the_platforms_own_spelling_wins_once_it_is_read(
    repo, investigation
) -> None:
    """Resolved means the page was actually fetched: it is authoritative."""
    make(repo, investigation.id, "prashantranjitkar")
    make(repo, investigation.id, "PrashantRanjitkar", resolved=True)

    entity = repo.list_entities(investigation.id)[0]
    assert entity.identifier == "PrashantRanjitkar"


def test_the_label_never_disagrees_with_the_identifier(repo, investigation) -> None:
    """A node labelled @alice whose identifier reads Alice looks like two."""
    make(repo, investigation.id, "prashantranjitkar")
    make(repo, investigation.id, "PrashantRanjitkar", resolved=True)

    entity = repo.list_entities(investigation.id)[0]
    assert entity.name == f"@{entity.identifier}"


def test_different_platforms_stay_separate(repo, investigation) -> None:
    """Folding identity must not merge accounts across sites."""
    make(repo, investigation.id, "prashant", platform="instagram")
    make(repo, investigation.id, "prashant", platform="github")

    assert len(repo.list_entities(investigation.id)) == 2


def test_different_handles_stay_separate(repo, investigation) -> None:
    make(repo, investigation.id, "prashant")
    make(repo, investigation.id, "prashantr")

    assert len(repo.list_entities(investigation.id)) == 2


def test_a_crawl_produces_one_node_per_account(repo) -> None:
    """End to end: no platform may appear twice for the same handle."""
    import collections

    from app.schemas.investigation import InvestigationCreate
    from app.services.investigation import InvestigationService

    service = InvestigationService(repo)
    created = service.create(
        InvestigationCreate(identifier="alice_98", platform="instagram", demo=True)
    )
    import asyncio

    asyncio.run(service.run(created))

    seen = collections.Counter(
        (e.type, e.platform, identity_key(e.identifier))
        for e in repo.list_entities(created.id)
    )
    assert not [key for key, count in seen.items() if count > 1]


# ---------------------------------------------------------------------------
# Healing databases written before the fix
# ---------------------------------------------------------------------------


def _write_legacy_duplicate(repo, investigation_id: str, identifier: str) -> str:
    """Insert a node the way the old, case-sensitive MERGE would have.

    The constraint is dropped first because this is precisely the state it now
    forbids - which is why it has to be healed before the constraint can be
    put back.
    """
    from app.models.base import new_id

    entity_id = new_id()
    repo.session.run(
        """
        MATCH (i:Investigation {id: $investigation})
        CREATE (e:Entity:Account {
            id: $id, investigation_id: $investigation, type: 'ACCOUNT',
            platform: 'instagram', identifier: $identifier,
            normalized_identifier: toLower($identifier),
            name: $name, resolved: $resolved, is_seed: false, depth: 1,
            first_seen: datetime(), last_seen: datetime(),
            created_at: datetime(), updated_at: datetime()
        })
        CREATE (i)-[:DISCOVERED]->(e)
        """,
        investigation=investigation_id,
        id=entity_id,
        identifier=identifier,
        name=f"@{identifier}",
        resolved=identifier[0].isupper(),
    )
    return entity_id


@pytest.fixture
def legacy_duplicates(repo, investigation):
    """A database in the broken state, with evidence on both halves."""
    repo.session.run("DROP CONSTRAINT entity_identity_folded IF EXISTS")

    lower = _write_legacy_duplicate(repo, investigation.id, "prashantranjitkar")
    upper = _write_legacy_duplicate(repo, investigation.id, "PrashantRanjitkar")
    neighbour = make(repo, investigation.id, "someone_else", platform="github")

    # Each half carries an association the other does not.
    from app.models.evidence import Evidence
    from app.models.relationship import Relationship

    for half in (lower, upper):
        repo.upsert_relationship(
            Relationship(
                investigation_id=investigation.id,
                source_entity_id=half,
                target_entity_id=neighbour.id,
                relationship_type="LINKS_TO",
                confidence_score=40,
            )
        )
        repo.add_evidence(
            [
                Evidence(
                    investigation_id=investigation.id,
                    source_entity_id=half,
                    target_entity_id=neighbour.id,
                    type="EXPLICIT_LINK",
                    description=f"observed on {half}",
                    weight=40,
                )
            ]
        )
    return lower, upper, neighbour


def test_the_migration_folds_a_legacy_duplicate_into_one_node(
    repo, investigation, legacy_duplicates
) -> None:
    _, _, neighbour = legacy_duplicates

    assert repo.merge_duplicate_entities() == 1

    accounts = [
        e for e in repo.list_entities(investigation.id) if e.platform == "instagram"
    ]
    assert len(accounts) == 1
    # The half actually read from the platform is the spelling kept.
    assert accounts[0].identifier == "PrashantRanjitkar"
    assert neighbour is not None


def test_the_migration_loses_no_evidence(
    repo, investigation, legacy_duplicates
) -> None:
    """Both halves carried observations. Merging must keep all of them."""
    before = len(repo.list_evidence(investigation.id))

    repo.merge_duplicate_entities()

    after = repo.list_evidence(investigation.id)
    assert len(after) == before
    survivor = next(
        e for e in repo.list_entities(investigation.id) if e.platform == "instagram"
    )
    # Every item now points at the surviving node rather than a deleted one.
    live = {e.id for e in repo.list_entities(investigation.id)}
    for item in after:
        assert item.source_entity_id in live
        assert item.source_entity_id == survivor.id or item.target_entity_id in live


def test_the_migration_keeps_the_relationships_of_both_halves(
    repo, investigation, legacy_duplicates
) -> None:
    _, _, neighbour = legacy_duplicates

    repo.merge_duplicate_entities()

    survivor = next(
        e for e in repo.list_entities(investigation.id) if e.platform == "instagram"
    )
    edges = repo.relationships_for_entity(survivor.id)
    assert edges, "the survivor inherits the associations of both halves"
    # The two duplicate edges described the same association, so they collapse.
    assert len({e.relationship_type for e in edges}) == len(edges)
    for edge in edges:
        assert neighbour.id in (edge.source_entity_id, edge.target_entity_id)


def test_the_constraint_can_be_created_after_healing(
    repo, investigation, legacy_duplicates
) -> None:
    """The whole point: startup must be able to enforce the rule again."""
    from app.database import CONSTRAINTS

    repo.merge_duplicate_entities()

    entity_constraint = next(c for c in CONSTRAINTS if "entity_identity_folded" in c)
    repo.session.run(entity_constraint)  # would raise if duplicates remained
