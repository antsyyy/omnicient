"""Per-source results: what each source yielded, including the silences.

The claim this feature makes is that "searched and found nothing" and
"refused to be searched" are different findings. Most of these tests exist to
hold that distinction in place, because the crawler reports both through one
timeline event and it would be easy to collapse them again.
"""

from __future__ import annotations

import pytest

from app.models.enums import AnalystStatus
from app.schemas.investigation import InvestigationCreate
from app.schemas.results import SourceOutcome
from app.services.investigation import InvestigationService
from app.services.results import ResultsService


@pytest.fixture
async def investigation(repo):
    service = InvestigationService(repo)
    created = service.create(
        InvestigationCreate(identifier="alice_98", platform="instagram", demo=True)
    )
    await service.run(created)
    return created


def results_for(repo, investigation):
    return ResultsService(repo).build(investigation)


def row_for(result, platform: str, identifier: str | None = None):
    for row in result.results:
        if row.platform == platform and (
            identifier is None or row.identifier == identifier
        ):
            return row
    return None


async def test_every_found_account_gets_a_row(repo, investigation) -> None:
    result = results_for(repo, investigation)
    found = [r for r in result.results if r.outcome is SourceOutcome.FOUND]

    assert found, "the demo crawl resolves several accounts"
    assert result.found == len(found)
    assert result.seed_identifier == "alice_98"
    for row in found:
        assert row.identifier
        assert row.platform_name, "rows are labelled for an analyst, not by slug"
        assert row.category


async def test_a_found_row_carries_the_evidence_behind_it(repo, investigation) -> None:
    """The row has to justify itself, not just assert a match."""
    result = results_for(repo, investigation)
    row = row_for(result, "instagram")

    assert row is not None
    assert row.outcome is SourceOutcome.FOUND
    assert row.confidence is not None
    assert row.score and row.score > 0
    assert row.evidence_count > 0, "a confidence with no evidence is a claim"
    assert row.relationship_id, "the row must be reviewable"
    assert row.actionable


async def test_a_refusal_is_not_reported_as_an_absence(repo, investigation) -> None:
    """The distinction the whole list view exists to make."""
    result = results_for(repo, investigation)
    unavailable = [r for r in result.results if r.outcome is SourceOutcome.UNAVAILABLE]

    assert unavailable, "the demo registry includes a source that declines"
    for row in unavailable:
        assert row.reason, "an unavailable row without a reason tells an analyst nothing"
        assert row.reason != "NOT_FOUND"
        assert row.outcome_label == "Source unavailable"


async def test_a_404_reads_as_nothing_found_not_as_unavailable(repo) -> None:
    """A source that answered "not here" closes a line of enquiry.

    The crawler reports a 404 through the same ``source_unavailable`` event as
    a block, so this is the case most likely to regress into "Source
    unavailable" for every handle that simply does not exist.
    """
    from app.services.results import _outcome_for_reason

    assert _outcome_for_reason("NOT_FOUND") is SourceOutcome.NOT_FOUND
    for refusal in ("BLOCKED", "PRIVATE", "RATE_LIMITED", "ROBOTS_DISALLOWED"):
        assert _outcome_for_reason(refusal) is SourceOutcome.UNAVAILABLE


async def test_a_referenced_account_keeps_its_reference_when_the_read_fails(
    repo,
) -> None:
    """An entity node means *something* pointed at this account.

    So a failed direct read does not erase it. The source having nothing to
    show leaves the reference as the story; an outright refusal is still
    reported as a refusal, because a referenced account behind a login wall is
    a finding worth chasing.
    """
    from app.models.entity import Entity
    from app.services.results import ResultsService

    def row(reason: str | None):
        entity = Entity(
            investigation_id="i",
            platform="github",
            name="@ghost",
            identifier="ghost",
            resolved=False,
        )
        issues = {"github": (reason, "detail")} if reason else {}
        return ResultsService._row(entity, "github", {}, {}, issues)

    assert row("NOT_FOUND").outcome is SourceOutcome.REFERENCED_ONLY
    assert row(None).outcome is SourceOutcome.REFERENCED_ONLY
    assert row("PRIVATE").outcome is SourceOutcome.UNAVAILABLE
    assert row("BLOCKED").outcome is SourceOutcome.UNAVAILABLE
    # The wording that explains the gap travels with the row either way.
    assert row("NOT_FOUND").reason == "NOT_FOUND"


async def test_a_source_that_found_nothing_still_appears(repo, investigation) -> None:
    """Silence is a result. A source missing from the list is a source untold."""
    result = results_for(repo, investigation)
    empty = [r for r in result.results if r.outcome is SourceOutcome.NOT_FOUND]

    assert empty
    for row in empty:
        assert row.identifier is None
        assert row.evidence_count == 0
        assert not row.actionable
        assert row.outcome_label == "Nothing found"


async def test_findings_are_ordered_above_silences(repo, investigation) -> None:
    result = results_for(repo, investigation)
    ranks = [
        {
            SourceOutcome.FOUND: 0,
            SourceOutcome.REFERENCED_ONLY: 1,
            SourceOutcome.UNAVAILABLE: 2,
            SourceOutcome.NOT_FOUND: 3,
            SourceOutcome.NOT_QUERIED: 4,
        }[row.outcome]
        for row in result.results
    ]
    assert ranks == sorted(ranks), "an analyst reads the top of the list first"

    scores = [r.score or 0 for r in result.results if r.outcome is SourceOutcome.FOUND]
    assert scores == sorted(scores, reverse=True), "strongest association first"


async def test_a_demo_run_does_not_pad_the_list_with_unreached_sources(
    repo, investigation
) -> None:
    """Only report a gap where the run was meant to reach the source.

    A demo run has the synthetic registry and nothing else, so listing two
    dozen untouched real platforms would bury six real findings under rows
    that mean nothing.
    """
    result = results_for(repo, investigation)
    assert not [r for r in result.results if r.outcome is SourceOutcome.NOT_QUERIED]
    assert result.queried == len(result.results)


async def test_the_summary_counts_every_row(repo, investigation) -> None:
    result = results_for(repo, investigation)
    assert sum(result.summary.values()) == len(result.results)
    assert result.summary.get(str(SourceOutcome.FOUND)) == result.found


async def test_an_analyst_verdict_wins_the_row_over_a_higher_score(
    repo, investigation
) -> None:
    """Once someone has ruled on an association, that is what the row reports."""
    from app.models.relationship import Relationship
    from app.services.results import _outranks

    def rel(score: float, status: AnalystStatus) -> Relationship:
        return Relationship(
            id=f"r{score}",
            investigation_id=investigation.id,
            source_entity_id="a",
            target_entity_id="b",
            relationship_type="POTENTIAL_SAME_IDENTITY",
            confidence_score=score,
            analyst_status=status,
        )

    reviewed = rel(40, AnalystStatus.CONFIRMED)
    stronger = rel(95, AnalystStatus.UNREVIEWED)

    assert _outranks(reviewed, stronger)
    assert not _outranks(stronger, reviewed)
    assert _outranks(rel(95, AnalystStatus.UNREVIEWED), rel(40, AnalystStatus.UNREVIEWED))


async def test_the_endpoint_serves_the_same_list(client) -> None:
    created = client.post(
        "/api/investigations",
        json={"identifier": "alice_98", "platform": "instagram", "demo": True},
    ).json()
    client.post(f"/api/investigations/{created['id']}/crawl")

    response = client.get(f"/api/investigations/{created['id']}/results")
    assert response.status_code == 200

    payload = response.json()
    assert payload["seed_identifier"] == "alice_98"
    assert payload["found"] > 0
    assert payload["results"]
    assert {"platform_name", "outcome", "outcome_label", "category"} <= set(
        payload["results"][0]
    )


async def test_an_unknown_investigation_is_a_404(client) -> None:
    assert client.get("/api/investigations/nope/results").status_code == 404


async def test_a_drawn_link_does_not_take_over_an_evidence_backed_row(
    repo, investigation
) -> None:
    """A hand-drawn link must not make a found account look unsupported.

    Drawing a link counts as confirming it, and it scores zero. Without a
    guard it would outrank an unreviewed edge carrying real evidence, and the
    row would report "insufficient evidence" for an account the crawl found.
    """
    from app.models.relationship import Relationship
    from app.services.results import _outranks

    asserted = Relationship(
        investigation_id=investigation.id,
        source_entity_id="a",
        target_entity_id="b",
        relationship_type="POTENTIAL_SAME_IDENTITY",
        confidence_score=0.0,
        origin="ANALYST",
        analyst_status=AnalystStatus.CONFIRMED,
    )
    observed = Relationship(
        investigation_id=investigation.id,
        source_entity_id="a",
        target_entity_id="b",
        relationship_type="POTENTIAL_SAME_IDENTITY",
        confidence_score=70.0,
        analyst_status=AnalystStatus.UNREVIEWED,
    )

    assert not _outranks(asserted, observed)
    assert _outranks(observed, asserted)
