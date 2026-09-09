"""Relationship path explorer: bounded traversal and deterministic ranking."""

from __future__ import annotations

import pytest

from app.schemas.investigation import InvestigationCreate
from app.services.investigation import InvestigationService
from app.services.paths import PathNotFoundError, PathService


@pytest.fixture
async def investigation(repo):
    service = InvestigationService(repo)
    created = service.create(
        InvestigationCreate(identifier="alice_98", platform="instagram", demo=True)
    )
    await service.run(created)
    return created


def entity_id(repo, investigation, platform: str, identifier: str) -> str:
    return next(
        entity.id
        for entity in repo.list_entities(investigation.id)
        if entity.platform == platform and entity.identifier == identifier
    )


async def test_a_direct_connection_is_found(repo, investigation) -> None:
    source = entity_id(repo, investigation, "instagram", "alice_98")
    target = entity_id(repo, investigation, "website", "alice.dev")

    result = PathService(repo).find(investigation, source, target)
    assert result.found > 0
    assert min(path.length for path in result.paths) == 1
    assert result.paths[0].rank == 1


async def test_a_multi_hop_path_is_found_and_explained(repo, investigation) -> None:
    """Instagram → alice.dev → GitHub is the demonstration route."""
    source = entity_id(repo, investigation, "instagram", "alice_98")
    target = entity_id(repo, investigation, "github", "alice-security")

    result = PathService(repo).find(investigation, source, target)
    assert result.found > 0

    via_website = [
        path
        for path in result.paths
        if any(step.entity.identifier == "alice.dev" for step in path.steps)
    ]
    assert via_website, "the website pivot route should be discoverable"
    path = via_website[0]
    assert path.length == 2
    assert "alice.dev" in path.summary
    assert path.relationship_types
    assert path.node_ids and path.relationship_ids


async def test_a_direct_route_outranks_a_longer_detour(repo, investigation) -> None:
    """A weak, speculative detour must never sit above a strong direct link.

    Evidence is counted per hop for exactly this reason: summing it rewards
    length, so a two-hop route would otherwise beat the one-hop connection it
    detours around.
    """
    source = entity_id(repo, investigation, "instagram", "alice_98")
    target = entity_id(repo, investigation, "github", "alice-security")

    result = PathService(repo).find(investigation, source, target)
    direct = [p for p in result.paths if p.length == 1]
    longer = [p for p in result.paths if p.length > 1]
    assert direct and longer
    assert result.paths[0].length == 1
    assert direct[0].strength_score > max(p.strength_score for p in longer)


async def test_identical_routes_are_collapsed(repo, investigation) -> None:
    """Parallel edges of the same type are one route to an analyst."""
    source = entity_id(repo, investigation, "instagram", "alice_98")
    target = entity_id(repo, investigation, "github", "alice-security")

    result = PathService(repo).find(investigation, source, target)
    seen = [
        (tuple(path.node_ids), tuple(path.relationship_types))
        for path in result.paths
    ]
    assert len(seen) == len(set(seen))


async def test_max_depth_bounds_the_search(repo, investigation) -> None:
    source = entity_id(repo, investigation, "instagram", "alice_98")
    target = entity_id(repo, investigation, "github", "alice-security")

    shallow = PathService(repo).find(investigation, source, target, max_depth=1)
    assert all(path.length <= 1 for path in shallow.paths)
    assert shallow.max_depth == 1


async def test_max_paths_bounds_the_result_count(repo, investigation) -> None:
    source = entity_id(repo, investigation, "instagram", "alice_98")
    target = entity_id(repo, investigation, "github", "alice-security")

    limited = PathService(repo).find(investigation, source, target, max_paths=1)
    assert limited.found == 1
    assert limited.max_paths == 1


async def test_bounds_are_clamped_not_trusted(repo, investigation) -> None:
    """A request cannot ask for an unbounded traversal."""
    source = entity_id(repo, investigation, "instagram", "alice_98")
    target = entity_id(repo, investigation, "github", "alice-security")

    result = PathService(repo).find(
        investigation, source, target, max_depth=9999, max_paths=9999
    )
    assert result.max_depth <= 8
    assert result.max_paths <= 25


async def test_no_path_is_reported_plainly(repo, investigation) -> None:
    """An unconnected pair gets a clear answer, not an empty response."""
    source = entity_id(repo, investigation, "instagram", "alice_98")
    target = entity_id(repo, investigation, "github", "alice-security")

    result = PathService(repo).find(investigation, source, target, max_depth=1)
    unreachable = PathService(repo).find(
        investigation,
        entity_id(repo, investigation, "organization", "contoso labs"),
        entity_id(repo, investigation, "email", "alice@alice.dev"),
        max_depth=1,
    )
    assert result.found >= 0
    assert unreachable.found == 0
    assert "No route found" in unreachable.message


async def test_a_rejected_step_sinks_a_route(repo, investigation) -> None:
    """Ranking has to respect a decision the analyst already made."""
    source = entity_id(repo, investigation, "instagram", "alice_98")
    target = entity_id(repo, investigation, "github", "alice-security")

    before = PathService(repo).find(investigation, source, target)
    direct = next((p for p in before.paths if p.length == 1), None)
    assert direct is not None
    assert before.paths[0].length == 1, "the direct route should start on top"
    rejected_id = direct.relationship_ids[0]
    repo.set_analyst_status(rejected_id, "REJECTED", "Not the same person.")

    after = PathService(repo).find(investigation, source, target)
    # The rejected route must no longer lead, and wherever it still appears it
    # is labelled as rejected rather than quietly ranked.
    assert rejected_id not in after.paths[0].relationship_ids
    assert after.paths[0].rank == 1
    assert after.paths[0].strength != "REJECTED"
    for path in after.paths:
        if rejected_id in path.relationship_ids:
            assert path.rejected_steps == 1
            assert path.strength == "REJECTED"


async def test_entities_outside_the_investigation_are_refused(
    repo, investigation
) -> None:
    """Scoping is what stops one investigation probing another."""
    source = entity_id(repo, investigation, "instagram", "alice_98")
    with pytest.raises(PathNotFoundError):
        PathService(repo).find(investigation, source, "not-an-entity-id")
    with pytest.raises(PathNotFoundError):
        PathService(repo).find(investigation, source, source)
