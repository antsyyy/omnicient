"""An analyst ruling that an entity is somebody else.

The one identity claim this system stores, and it is stored as an analyst's
assertion rather than a finding. What the tests here are really guarding is
that the ruling *removes nothing*: the account, its observations, its evidence
and its relationships all survive it, because the analyst may be wrong and a
later reviewer has to be able to see what was ruled out and why.
"""

from __future__ import annotations

import pytest

from app.models.enums import EntityVerdict
from app.schemas.investigation import InvestigationCreate
from app.services.investigation import InvestigationService


@pytest.fixture
async def case(repo):
    service = InvestigationService(repo)
    created = service.create(
        InvestigationCreate(identifier="alice_98", platform="instagram", demo=True)
    )
    await service.run(created)
    return created


def _a_non_seed(repo, investigation) -> str:
    entities = repo.list_entities(investigation.id)
    return next(entity.id for entity in entities if not entity.is_seed)


async def test_marking_an_entity_records_the_verdict_and_the_reason(repo, case) -> None:
    entity_id = _a_non_seed(repo, case)

    ruled = repo.set_entity_verdict(
        entity_id, EntityVerdict.DIFFERENT_IDENTITY, "Different city, common handle."
    )

    assert ruled is not None
    assert ruled.analyst_verdict == EntityVerdict.DIFFERENT_IDENTITY
    assert ruled.analyst_note == "Different city, common handle."
    assert ruled.reviewed_at is not None


async def test_an_unreviewed_entity_says_so(repo, case) -> None:
    """The default has to be a value, not an absence.

    Entities written before this field existed have no such property, and a
    node that answered ``None`` would make every consumer test for it.
    """
    entity = repo.get_entity(_a_non_seed(repo, case))

    assert entity.analyst_verdict == EntityVerdict.UNREVIEWED
    assert entity.reviewed_at is None


async def test_the_ruling_removes_nothing(repo, case) -> None:
    """The point of the whole design: a verdict is not a delete."""
    entity_id = _a_non_seed(repo, case)
    before = repo.relationships_for_entity(entity_id)
    assert before, "pick an entity that actually has relationships"
    evidence_before = {
        r.id: len(repo.evidence_for_relationship(r.id)) for r in before
    }
    assert any(evidence_before.values()), "and evidence to lose"

    repo.set_entity_verdict(entity_id, EntityVerdict.DIFFERENT_IDENTITY, None)

    assert repo.get_entity(entity_id) is not None
    after = repo.relationships_for_entity(entity_id)
    assert {r.id for r in after} == {r.id for r in before}
    assert {
        r.id: len(repo.evidence_for_relationship(r.id)) for r in after
    } == evidence_before
    # And the relationships keep their own verdicts, which are a separate
    # judgement about the evidence between two entities.
    assert [r.analyst_status for r in after] == [r.analyst_status for r in before]


async def test_the_ruling_can_be_undone(repo, case) -> None:
    entity_id = _a_non_seed(repo, case)
    repo.set_entity_verdict(entity_id, EntityVerdict.DIFFERENT_IDENTITY, "Namesake.")

    restored = repo.set_entity_verdict(entity_id, EntityVerdict.UNREVIEWED, None)

    assert restored.analyst_verdict == EntityVerdict.UNREVIEWED
    assert restored.reviewed_at is None
    # The reasoning survives the undo: it is a record of what was considered,
    # and losing it on every toggle would make the note not worth writing.
    assert restored.analyst_note == "Namesake."


async def test_the_verdict_survives_a_recrawl(repo, case) -> None:
    """The failure that would make the feature useless.

    A re-crawl re-observes every entity it finds and overwrites the observed
    fields. If it overwrote this too, an analyst would have to rule out the
    same namesake after every run.
    """
    entity_id = _a_non_seed(repo, case)
    repo.set_entity_verdict(entity_id, EntityVerdict.DIFFERENT_IDENTITY, "Namesake.")

    await InvestigationService(repo).run(case, reset=False)

    after = repo.get_entity(entity_id)
    assert after.analyst_verdict == EntityVerdict.DIFFERENT_IDENTITY
    assert after.analyst_note == "Namesake."


async def test_the_counts_include_every_entity(repo, case) -> None:
    counts = repo.entity_verdict_counts(case.id)

    assert sum(counts.values()) == len(repo.list_entities(case.id))
    assert counts[str(EntityVerdict.UNREVIEWED)] > 0


async def test_the_graph_carries_the_verdict(repo, case) -> None:
    """The canvas cannot draw or filter what the payload does not say."""
    from app.services.graph import GraphService

    entity_id = _a_non_seed(repo, case)
    repo.set_entity_verdict(entity_id, EntityVerdict.DIFFERENT_IDENTITY, "Namesake.")

    graph = GraphService(repo).build(case)
    node = next(node for node in graph.nodes if node.id == entity_id)

    assert node.analyst_verdict == EntityVerdict.DIFFERENT_IDENTITY
    assert node.analyst_note == "Namesake."
    # And it is still on the canvas: an entity the analyst cannot see is one
    # they cannot un-rule.
    assert len(graph.nodes) == len(repo.list_entities(case.id))


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------


@pytest.fixture
def investigation(client) -> dict:
    """A created-and-crawled demo investigation, over the HTTP surface."""
    created = client.post(
        "/api/investigations",
        json={"identifier": "@alice_98", "platform": "Instagram", "auto_crawl": False},
    ).json()
    client.post(f"/api/investigations/{created['id']}/crawl", json={})
    return client.get(f"/api/investigations/{created['id']}").json()


def _graph_entities(client, investigation_id: str) -> list[dict]:
    return client.get(f"/api/investigations/{investigation_id}/graph").json()["nodes"]


def test_the_endpoint_marks_and_resets(client, investigation) -> None:
    nodes = _graph_entities(client, investigation["id"])
    target = next(node for node in nodes if not node["is_seed"])

    marked = client.post(
        f"/api/entities/{target['id']}/different-identity",
        json={"note": "Different employer, handle is a common name."},
    )
    assert marked.status_code == 200
    body = marked.json()
    assert body["analyst_verdict"] == "DIFFERENT_IDENTITY"
    assert body["analyst_note"] == "Different employer, handle is a common name."
    assert body["reviewed_at"]

    reset = client.post(f"/api/entities/{target['id']}/reset-identity")
    assert reset.status_code == 200
    assert reset.json()["analyst_verdict"] == "UNREVIEWED"


def test_the_seed_cannot_be_ruled_out(client, investigation) -> None:
    """The seed is what the investigation is about, not a finding in it.

    Ruling it out would leave an investigation of nobody with every other
    entity still hanging off it - and on the canvas, a struck-through root
    with a live tree underneath.
    """
    nodes = _graph_entities(client, investigation["id"])
    seed = next(node for node in nodes if node["is_seed"])

    response = client.post(f"/api/entities/{seed['id']}/different-identity")

    assert response.status_code == 409
    assert "seed" in response.json()["detail"].lower()


def test_marking_an_unknown_entity_is_a_404(client) -> None:
    response = client.post("/api/entities/does-not-exist/different-identity")

    assert response.status_code == 404


def test_a_note_longer_than_the_limit_is_refused(client, investigation) -> None:
    nodes = _graph_entities(client, investigation["id"])
    target = next(node for node in nodes if not node["is_seed"])

    response = client.post(
        f"/api/entities/{target['id']}/different-identity",
        json={"note": "x" * 2001},
    )

    assert response.status_code == 422
