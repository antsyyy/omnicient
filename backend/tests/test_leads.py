"""Investigation leads: deterministic pivots derived from stored evidence."""

from __future__ import annotations

import pytest

from app.schemas.investigation import InvestigationCreate
from app.services.investigation import InvestigationService
from app.services.leads import LeadService


@pytest.fixture
async def investigation(repo):
    service = InvestigationService(repo)
    created = service.create(
        InvestigationCreate(identifier="alice_98", platform="instagram", demo=True)
    )
    await service.run(created)
    return created


def leads_for(repo, investigation):
    return LeadService(repo).generate(investigation)


def of_type(result, kind: str):
    return [lead for lead in result.leads if str(lead.type) == kind]


async def test_a_shared_website_produces_a_high_value_lead(repo, investigation) -> None:
    result = leads_for(repo, investigation)
    website = of_type(result, "SHARED_WEBSITE_CLUSTER")

    assert website, "alice.dev is published by several accounts"
    lead = website[0]
    assert lead.priority == "HIGH"
    assert lead.pivot_value == "alice.dev"
    assert lead.entity_count >= 2
    assert lead.related_entities, "the interface needs resolved entities to navigate"
    assert lead.suggested_action


async def test_a_repeated_email_produces_a_lead(repo, investigation) -> None:
    result = leads_for(repo, investigation)
    email = of_type(result, "REPEATED_EMAIL")
    assert email
    assert email[0].pivot_value == "alice@alice.dev"
    assert email[0].priority == "HIGH"


async def test_a_shared_avatar_produces_a_lead(repo, investigation) -> None:
    result = leads_for(repo, investigation)
    assert of_type(result, "SHARED_AVATAR")


async def test_an_alias_produces_a_lead(repo, investigation) -> None:
    result = leads_for(repo, investigation)
    alias = of_type(result, "POTENTIAL_ALIAS")
    assert alias
    # The wording must stay a claim about handles.
    assert any("handles" in lead.description for lead in alias)


async def test_a_contradiction_produces_a_review_lead(repo, investigation) -> None:
    """A contradiction under a score is exactly what an analyst must see."""
    result = leads_for(repo, investigation)
    contradiction = of_type(result, "CONTRADICTION_REVIEW")

    assert contradiction
    lead = contradiction[0]
    assert lead.label == "Review required"
    assert lead.supporting_evidence_ids
    assert lead.related_relationship_ids


async def test_unreviewed_associations_are_summarised_not_enumerated(
    repo, investigation
) -> None:
    """One lead per relationship would just be the relationship list again."""
    result = leads_for(repo, investigation)
    unreviewed = of_type(result, "UNREVIEWED_STRONG_ASSOCIATION")

    assert unreviewed
    # A handful of named ones, plus at most one roll-up.
    rollups = [lead for lead in unreviewed if "further associations" in lead.title]
    assert len(rollups) <= 1
    assert len(unreviewed) <= 4
    if rollups:
        assert rollups[0].related_relationship_ids


async def test_leads_are_ranked_and_banded(repo, investigation) -> None:
    result = leads_for(repo, investigation)
    scores = [lead.score for lead in result.leads]

    assert scores == sorted(scores, reverse=True)
    assert result.total == len(result.leads)
    assert sum(result.by_priority.values()) == result.total
    assert result.by_priority["HIGH"] > 0
    assert result.by_priority["LOW"] > 0
    for lead in result.leads:
        if lead.priority == "HIGH":
            assert lead.score >= 70
        elif lead.priority == "MEDIUM":
            assert 40 <= lead.score < 70
        else:
            assert lead.score < 40


async def test_lead_ids_are_stable_across_calls(repo, investigation) -> None:
    """The interface tracks leads by id; they must not churn per request."""
    first = {lead.id for lead in leads_for(repo, investigation).leads}
    second = {lead.id for lead in leads_for(repo, investigation).leads}
    assert first == second


async def test_leads_reflect_analyst_decisions(repo, investigation) -> None:
    """Reviewing a relationship must retire its "awaiting review" lead."""
    before = leads_for(repo, investigation)
    unreviewed = [
        lead
        for lead in before.leads
        if str(lead.type) == "UNREVIEWED_STRONG_ASSOCIATION"
        and "further associations" not in lead.title
    ]
    assert unreviewed
    target = unreviewed[0]
    for relationship_id in target.related_relationship_ids:
        repo.set_analyst_status(relationship_id, "CONFIRMED", "Reviewed.")

    after = leads_for(repo, investigation)
    assert target.id not in {lead.id for lead in after.leads}


async def test_every_lead_points_at_something_real(repo, investigation) -> None:
    """A lead with no entity behind it is an assumption, not a pivot."""
    result = leads_for(repo, investigation)
    entity_ids = {entity.id for entity in repo.list_entities(investigation.id)}

    assert result.leads
    for lead in result.leads:
        assert lead.related_entity_ids, f"{lead.type} names no entity"
        assert set(lead.related_entity_ids) <= entity_ids
        assert lead.title and lead.description and lead.suggested_action
        # Never phrased as a conclusion.
        assert lead.label in (
            "Suggested investigation lead",
            "Review required",
        )
