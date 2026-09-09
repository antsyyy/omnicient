"""Identity Intelligence Profile: aggregation that stays evidence-backed."""

from __future__ import annotations

import pytest

from app.schemas.investigation import InvestigationCreate
from app.services.identity_profile import IdentityProfileService
from app.services.investigation import InvestigationService


@pytest.fixture
async def investigation(repo):
    service = InvestigationService(repo)
    created = service.create(
        InvestigationCreate(identifier="alice_98", platform="instagram", demo=True)
    )
    await service.run(created)
    return created


def profile_for(repo, investigation):
    return IdentityProfileService(repo).build(investigation)


async def test_profile_aggregates_multiple_accounts(repo, investigation) -> None:
    profile = profile_for(repo, investigation)

    assert profile.primary_identifier.value == "alice_98"
    platforms = {p.platform for p in profile.platforms}
    assert {"instagram", "github", "reddit", "threads"} <= platforms
    assert profile.statistics.accounts >= 5


async def test_profile_lists_potential_aliases_never_confirmed_ones(
    repo, investigation
) -> None:
    profile = profile_for(repo, investigation)
    assert profile.potential_aliases
    for alias in profile.potential_aliases:
        assert alias.label == "Potential Alias"
        assert alias.analyst_status == "UNREVIEWED"
        assert alias.transformations


async def test_profile_websites_are_corroborated_and_attributed(
    repo, investigation
) -> None:
    """A value must name the entities that published it."""
    profile = profile_for(repo, investigation)
    site = next(w for w in profile.websites if w.value == "alice.dev")

    assert site.observation_count > 1
    assert site.corroborated
    assert site.entity_ids
    entity_ids = {entity.id for entity in repo.list_entities(investigation.id)}
    assert set(site.entity_ids) <= entity_ids


async def test_profile_excludes_platform_hosts_from_websites(
    repo, investigation
) -> None:
    """github.com is an account, already under platforms - not a website."""
    profile = profile_for(repo, investigation)
    values = {w.value for w in profile.websites}
    assert "alice.dev" in values
    assert not values & {"github.com", "instagram.com", "reddit.com", "threads.net"}


async def test_profile_reports_organizations_emails_and_locations(
    repo, investigation
) -> None:
    profile = profile_for(repo, investigation)

    assert any("contoso" in (o.value or "") for o in profile.organizations)
    assert any(e.value == "alice@alice.dev" for e in profile.emails)
    # Locations are only ever what a source published.
    labels = {loc.label for loc in profile.locations}
    assert "Kathmandu" in labels


async def test_profile_statistics_match_the_graph(repo, investigation) -> None:
    profile = profile_for(repo, investigation)
    entities, relationships, evidence = repo.counts(investigation.id)

    assert profile.statistics.entities == entities
    assert profile.statistics.relationships == relationships
    assert profile.statistics.evidence == evidence
    assert (
        profile.statistics.high_confidence
        + profile.statistics.medium_confidence
        + profile.statistics.low_confidence
        == relationships
    )
    assert profile.statistics.unreviewed == relationships


async def test_profile_timeline_comes_from_snapshots(repo, investigation) -> None:
    profile = profile_for(repo, investigation)
    assert profile.snapshot_count > 0
    assert profile.first_observed is not None
    assert profile.last_observed is not None
    assert profile.first_observed <= profile.last_observed


async def test_every_relationship_is_traceable_to_evidence(repo, investigation) -> None:
    """A score with no observation behind it is what this tool must not emit."""
    profile = profile_for(repo, investigation)
    assert profile.evidence_summary.unexplained_relationships == 0
    assert profile.evidence_summary.traceable
    assert profile.evidence_summary.supporting > 0


async def test_profile_surfaces_contradictions(repo, investigation) -> None:
    profile = profile_for(repo, investigation)
    assert profile.statistics.contradictions >= 1
    assert profile.contradictions
    assert any("website" in line.lower() for line in profile.contradictions)


async def test_a_rejected_entity_stops_contributing_attributes(
    repo, investigation
) -> None:
    """Rejecting a relationship must remove its entity from the summary.

    Otherwise a false positive the analyst threw out keeps shaping the profile
    from behind the scenes.
    """
    before = profile_for(repo, investigation)
    assert any(w.value == "unrelated.example" for w in before.websites)

    # The near-miss account is tied in only by a CONTRADICTORY edge.
    near_miss = next(
        entity
        for entity in repo.list_entities(investigation.id)
        if entity.identifier == "alice98"
    )
    for relationship in repo.relationships_for_entity(near_miss.id):
        repo.set_analyst_status(relationship.id, "REJECTED", "Different person.")

    after = profile_for(repo, investigation)
    assert not any(w.value == "unrelated.example" for w in after.websites)
    assert "London" not in {loc.label for loc in after.locations}
    # The seed itself is never dropped, whatever was rejected.
    assert after.primary_identifier.value == "alice_98"
