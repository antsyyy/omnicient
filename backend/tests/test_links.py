"""Links an analyst draws by hand.

A manual link is the one association in Omnicient with no observation behind
it. These tests exist to keep that visible: it must be stamped as asserted,
score nothing, carry a stated reason, and never be presentable as something
the engine found.
"""

from __future__ import annotations

import pytest

from app.models.enums import EvidenceType, RelationshipOrigin, RelationshipType
from app.schemas.investigation import InvestigationCreate
from app.schemas.relationship import ManualLinkCreate
from app.services.investigation import InvestigationService
from app.services.links import LinkError, LinkService


@pytest.fixture
async def case(repo):
    """A finished investigation, plus two accounts nothing already connects.

    The demo graph links most of its accounts to each other, and drawing over
    an existing edge is refused on purpose - so the fixture hunts for a pair
    that is genuinely unconnected rather than tripping that guard by accident.
    """
    service = InvestigationService(repo)
    created = service.create(
        InvestigationCreate(identifier="alice_98", platform="instagram", demo=True)
    )
    await service.run(created)

    accounts = [e for e in repo.list_entities(created.id) if e.type == "ACCOUNT"]
    linked = {
        frozenset((r.source_entity_id, r.target_entity_id))
        for r in repo.list_relationships(created.id)
    }
    pair = next(
        (a, b)
        for i, a in enumerate(accounts)
        for b in accounts[i + 1 :]
        if frozenset((a.id, b.id)) not in linked
    )
    return created, pair


def draw(repo, investigation, source, target, **kwargs):
    request = ManualLinkCreate(
        source_entity_id=source.id,
        target_entity_id=target.id,
        rationale=kwargs.pop("rationale", "Confirmed against an archived copy."),
        **kwargs,
    )
    return LinkService(repo).create(investigation, request)


async def test_a_drawn_link_is_stamped_as_asserted_not_observed(repo, case) -> None:
    investigation, accounts = case
    link = draw(repo, investigation, accounts[0], accounts[1])

    assert str(link.origin) == RelationshipOrigin.ANALYST
    assert link.is_analyst_asserted
    # Drawing a link is itself the analyst's verdict on it.
    assert str(link.analyst_status) == "CONFIRMED"


async def test_a_drawn_link_scores_nothing(repo, case) -> None:
    """The engine observed nothing, so there is no score to report.

    Giving a hand-drawn link a confidence band would dress a judgement up as a
    measurement - exactly the claim this project refuses to make.
    """
    investigation, accounts = case
    link = draw(repo, investigation, accounts[0], accounts[1])

    assert link.confidence_score == 0.0
    assert str(link.confidence_level) == "INSUFFICIENT"


async def test_the_rationale_becomes_the_links_provenance(repo, case) -> None:
    investigation, accounts = case
    reason = "Named together in a court filing the crawler cannot reach."
    link = draw(repo, investigation, accounts[0], accounts[1], rationale=reason)

    evidence = repo.evidence_for_relationship(link.id)
    assert len(evidence) == 1
    item = evidence[0]
    assert str(item.type) == EvidenceType.ANALYST_ASSERTION
    assert item.description == reason
    # Zero weight: recorded as having been said, without arguing the score.
    assert item.weight == 0.0
    assert link.analyst_note == reason


async def test_a_rationale_is_required(repo, case) -> None:
    """An assertion nobody has to justify is not auditable."""
    from pydantic import ValidationError

    investigation, accounts = case
    with pytest.raises(ValidationError):
        ManualLinkCreate(
            source_entity_id=accounts[0].id,
            target_entity_id=accounts[1].id,
            rationale="",
        )


async def test_an_observation_cannot_be_asserted_by_hand(repo, case) -> None:
    """SHARED_AVATAR names something the engine saw. Nobody can claim it did."""
    investigation, accounts = case
    with pytest.raises(LinkError) as caught:
        draw(
            repo,
            investigation,
            accounts[0],
            accounts[1],
            relationship_type=RelationshipType.SHARED_AVATAR,
        )
    assert "observation" in str(caught.value)


async def test_an_entity_cannot_be_linked_to_itself(repo, case) -> None:
    investigation, accounts = case
    with pytest.raises(LinkError):
        draw(repo, investigation, accounts[0], accounts[0])


async def test_a_second_link_of_the_same_type_is_refused(repo, case) -> None:
    """Re-drawing an existing edge would overwrite the engine's score for it."""
    investigation, accounts = case
    draw(repo, investigation, accounts[0], accounts[1])

    with pytest.raises(LinkError) as caught:
        draw(repo, investigation, accounts[0], accounts[1])
    assert caught.value.conflict
    assert "already connected" in str(caught.value)


async def test_an_entity_from_another_investigation_is_refused(repo, case) -> None:
    investigation, accounts = case
    other = InvestigationService(repo).create(
        InvestigationCreate(identifier="bob_42", platform="instagram", demo=True)
    )
    with pytest.raises(LinkError) as caught:
        LinkService(repo).create(
            other,
            ManualLinkCreate(
                source_entity_id=accounts[0].id,
                target_entity_id=accounts[1].id,
                rationale="Crossing investigations.",
            ),
        )
    assert "different investigation" in str(caught.value)


async def test_a_drawn_link_can_be_removed(repo, case) -> None:
    investigation, accounts = case
    link = draw(repo, investigation, accounts[0], accounts[1])

    LinkService(repo).delete(link)

    assert repo.get_relationship(link.id) is None
    assert repo.evidence_for_relationship(link.id) == []


async def test_an_observed_relationship_cannot_be_deleted(repo, case) -> None:
    """Rejecting records disagreement; deleting would destroy the evidence."""
    investigation, _ = case
    engine = next(
        r
        for r in repo.list_relationships(investigation.id)
        if not r.is_analyst_asserted
    )
    with pytest.raises(LinkError) as caught:
        LinkService(repo).delete(engine)
    assert "Reject it instead" in str(caught.value)
    assert repo.get_relationship(engine.id) is not None


async def test_a_recrawl_keeps_the_origin_of_whoever_asserted_first(
    repo, case
) -> None:
    """If the engine later finds evidence for a drawn link, it stays asserted.

    The edge gains the observations, but a person put it there and the record
    has to keep saying so.
    """
    investigation, accounts = case
    link = draw(repo, investigation, accounts[0], accounts[1])

    from app.models.relationship import Relationship

    repo.upsert_relationship(
        Relationship(
            investigation_id=investigation.id,
            source_entity_id=accounts[0].id,
            target_entity_id=accounts[1].id,
            relationship_type=str(RelationshipType.POTENTIAL_SAME_IDENTITY),
            confidence_score=80,
        )
    )
    refreshed = repo.get_relationship(link.id)
    assert refreshed is not None
    assert str(refreshed.origin) == RelationshipOrigin.ANALYST
    assert refreshed.confidence_score == 80, "the evidence still counts"


async def test_the_export_says_which_links_a_person_drew(repo, case) -> None:
    """Whoever reads the file has no interface to tell them apart."""
    investigation, accounts = case
    draw(repo, investigation, accounts[0], accounts[1])

    csv_text = InvestigationService(repo).export_csv(investigation)
    header = csv_text.splitlines()[0].split(",")
    assert "origin" in header
    assert "ANALYST" in csv_text
    assert "ENGINE" in csv_text


async def test_the_endpoints_draw_and_remove_a_link(client) -> None:
    created = client.post(
        "/api/investigations",
        json={"identifier": "alice_98", "platform": "instagram", "demo": True},
    ).json()
    client.post(f"/api/investigations/{created['id']}/crawl")
    entities = client.get(f"/api/investigations/{created['id']}/entities").json()
    accounts = [e for e in entities if e["type"] == "ACCOUNT"]

    response = client.post(
        f"/api/investigations/{created['id']}/links",
        json={
            "source_entity_id": accounts[0]["id"],
            "target_entity_id": accounts[-1]["id"],
            "relationship_type": "POTENTIAL_ALIAS",
            "rationale": "Same handle pattern, verified off-platform.",
        },
    )
    assert response.status_code == 201
    link = response.json()
    assert link["origin"] == "ANALYST"
    assert link["analyst_asserted"] is True
    assert link["confidence_score"] == 0.0

    # It reaches the graph marked as asserted, so the canvas can draw it apart.
    graph = client.get(f"/api/investigations/{created['id']}/graph").json()
    drawn = next(e for e in graph["edges"] if e["id"] == link["id"])
    assert drawn["origin"] == "ANALYST"

    assert client.delete(f"/api/relationships/{link['id']}").status_code == 204
    assert client.get(f"/api/relationships/{link['id']}").status_code == 404
