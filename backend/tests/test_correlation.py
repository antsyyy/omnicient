"""Correlation: scoring, confidence bands, contradictions and no-evidence cases."""

from __future__ import annotations

import pytest

from app.config import ScoringConfig
from app.models.enums import ConfidenceLevel, EvidenceType, RelationshipType
from app.services.correlation import CorrelationEngine
from app.sources.base import ObservedProfile, enrich_profile

SCORING = ScoringConfig()


def profile(platform: str, identifier: str, **kwargs) -> ObservedProfile:
    """Build an enriched observed profile for a test."""
    return enrich_profile(
        ObservedProfile(platform=platform, identifier=identifier, **kwargs)
    )


@pytest.fixture
def engine() -> CorrelationEngine:
    return CorrelationEngine(SCORING)


def types_of(result) -> set[str]:
    return {str(item.type) for item in result.evidence}


def test_explicit_link_dominates_the_score(engine: CorrelationEngine) -> None:
    source = profile(
        "instagram", "alice_98", bio="Threads: @alice_dev", external_links=[]
    )
    target = profile("threads", "alice_dev")
    result = engine.compare(source, target)

    assert EvidenceType.EXPLICIT_LINK in types_of(result)
    assert result.score >= SCORING.explicit_link
    assert result.confidence_level == ConfidenceLevel.HIGH
    assert result.relationship_type == RelationshipType.POTENTIAL_SAME_IDENTITY


def test_explicit_link_is_found_in_either_direction(engine: CorrelationEngine) -> None:
    source = profile("threads", "alice_dev")
    target = profile("instagram", "alice_98", bio="Threads: @alice_dev")
    assert EvidenceType.EXPLICIT_LINK in types_of(engine.compare(source, target))


def test_exact_username_alone_is_weak(engine: CorrelationEngine) -> None:
    result = engine.compare(profile("instagram", "alice"), profile("threads", "alice"))
    assert types_of(result) == {EvidenceType.SAME_USERNAME}
    assert result.score == SCORING.exact_username
    assert result.confidence_level == ConfidenceLevel.LOW
    assert result.relationship_type == RelationshipType.USES_USERNAME


def test_similar_username_alone_is_weaker(engine: CorrelationEngine) -> None:
    result = engine.compare(
        profile("instagram", "alice_dev"), profile("threads", "alice.dev")
    )
    assert types_of(result) == {EvidenceType.SIMILAR_USERNAME}
    assert result.score == SCORING.similar_username
    assert result.confidence_level == ConfidenceLevel.LOW


def test_shared_website(engine: CorrelationEngine) -> None:
    source = profile("instagram", "alice_98", external_links=["https://alice.dev"])
    target = profile("github", "alice-security", external_links=["http://www.alice.dev/"])
    result = engine.compare(source, target)
    assert EvidenceType.SAME_WEBSITE in types_of(result)
    assert result.score >= SCORING.shared_website


def test_same_avatar_and_shared_email(engine: CorrelationEngine) -> None:
    avatar = "https://alice.dev/media/avatar.png"
    source = profile("instagram", "alice_98", avatar_url=avatar, bio="alice@alice.dev")
    target = profile("github", "alice-security", avatar_url=avatar, bio="mail alice@alice.dev")
    result = engine.compare(source, target)
    assert {EvidenceType.SAME_AVATAR, EvidenceType.SHARED_EMAIL} <= types_of(result)
    assert result.score >= SCORING.shared_avatar + SCORING.shared_email


def test_similar_biography_and_display_name(engine: CorrelationEngine) -> None:
    source = profile(
        "instagram", "alice_98",
        display_name="Alice R.",
        bio="Security researcher writing about detection engineering",
    )
    target = profile(
        "github", "alice-security",
        display_name="alice r.",
        bio="Detection engineering and security research",
    )
    result = engine.compare(source, target)
    assert {EvidenceType.SIMILAR_BIO, EvidenceType.SAME_DISPLAY_NAME} <= types_of(result)


def test_contradictory_website_and_location_reduce_the_score(
    engine: CorrelationEngine,
) -> None:
    source = profile(
        "instagram", "alice_98",
        location="Kathmandu",
        external_links=["https://alice.dev"],
    )
    target = profile(
        "x", "alice98",
        location="London",
        external_links=["https://unrelated.dev"],
    )
    result = engine.compare(source, target)

    contradictions = result.contradicting
    assert len(contradictions) == 2
    assert all(item.weight < 0 for item in contradictions)
    # A weak username match cannot survive two contradictions.
    assert result.score == 0
    assert result.relationship_type == RelationshipType.CONTRADICTORY


def test_contradictions_only_weaken_a_strong_relationship(
    engine: CorrelationEngine,
) -> None:
    source = profile(
        "instagram", "alice_98",
        bio="Threads: @alice_dev",
        location="Kathmandu",
    )
    target = profile("threads", "alice_dev", location="London")
    result = engine.compare(source, target)
    assert result.score == SCORING.explicit_link + SCORING.contradictory_location
    assert result.contradicting


def test_no_evidence_is_reported_as_insufficient(engine: CorrelationEngine) -> None:
    result = engine.compare(
        profile("instagram", "alice_98"), profile("threads", "bob_smith")
    )
    assert result.evidence == []
    assert result.confidence_level == ConfidenceLevel.INSUFFICIENT
    assert result.summary == "Insufficient evidence"


def test_correlate_skips_pairs_without_supporting_evidence(
    engine: CorrelationEngine,
) -> None:
    profiles = [
        profile("instagram", "alice_98", external_links=["https://alice.dev"]),
        profile("threads", "bob", external_links=["https://bob.dev"]),
    ]
    assert engine.correlate(profiles) == []


def test_confidence_bands_match_the_specification(engine: CorrelationEngine) -> None:
    assert engine.score_to_level(0) == ConfidenceLevel.LOW
    assert engine.score_to_level(19) == ConfidenceLevel.LOW
    assert engine.score_to_level(20) == ConfidenceLevel.MEDIUM
    assert engine.score_to_level(49) == ConfidenceLevel.MEDIUM
    assert engine.score_to_level(50) == ConfidenceLevel.HIGH
    assert engine.score_to_level(74) == ConfidenceLevel.HIGH
    assert engine.score_to_level(75) == ConfidenceLevel.VERY_HIGH
    assert engine.score_to_level(100) == ConfidenceLevel.VERY_HIGH


def test_scores_are_clamped_to_the_scale(engine: CorrelationEngine) -> None:
    avatar = "https://alice.dev/a.png"
    source = profile(
        "instagram", "alice_98",
        display_name="Alice R.",
        bio="Threads: @alice_dev security research at Contoso Labs alice@alice.dev",
        avatar_url=avatar,
        external_links=["https://alice.dev"],
    )
    target = profile(
        "threads", "alice_98",
        display_name="Alice R.",
        bio="Security research at Contoso Labs alice@alice.dev",
        avatar_url=avatar,
        external_links=["https://alice.dev"],
    )
    assert engine.compare(source, target).score == 100.0


def test_scoring_weights_come_from_configuration() -> None:
    custom = CorrelationEngine(ScoringConfig(exact_username=42))
    result = custom.compare(profile("instagram", "a1"), profile("threads", "a1"))
    assert result.score == 42


def test_demo_dataset_produces_the_documented_scenario() -> None:
    """The shipped demo must show a HIGH-confidence cross-platform association."""
    import asyncio

    from app.demo_data import build_demo_registry
    from app.services.crawler import Crawler

    outcome = asyncio.run(Crawler(build_demo_registry()).crawl("instagram", "alice_98"))
    results = CorrelationEngine(SCORING).correlate(outcome.profiles)

    github = next(
        result
        for result in results
        if {result.source_key[1], result.target_key[1]} == {"instagram", "github"}
    )
    assert github.relationship_type == RelationshipType.POTENTIAL_SAME_IDENTITY
    assert github.confidence_level == ConfidenceLevel.HIGH
    assert {EvidenceType.SAME_WEBSITE, EvidenceType.SAME_AVATAR, EvidenceType.SIMILAR_BIO} <= {
        str(item.type) for item in github.evidence
    }

    contradictory = next(
        result
        for result in results
        if {result.source_key[1], result.target_key[1]} == {"instagram", "x"}
    )
    assert contradictory.relationship_type == RelationshipType.CONTRADICTORY
    assert len(contradictory.contradicting) == 2


def test_a_shared_link_shortener_is_not_a_shared_website() -> None:
    """Half the internet links to linktr.ee; that ties nobody to anybody.

    Crediting a generic host as a shared website is an easy way to manufacture
    a false positive, so those hosts earn nothing.
    """
    engine = CorrelationEngine()
    a = profile("instagram", "alice_98", external_links=["https://linktr.ee/alice"])
    b = profile("threads", "bob_x", external_links=["https://linktr.ee/bob"])

    result = engine.compare(a, b)
    types = {item.type for item in (result.evidence if result else [])}
    assert EvidenceType.SAME_WEBSITE not in types


def test_a_shared_personal_domain_is_still_strong_evidence() -> None:
    """The filter must not weaken the signal it exists to protect."""
    engine = CorrelationEngine()
    a = profile("instagram", "alice_98", external_links=["https://alice.dev"])
    b = profile("threads", "alice_dev", external_links=["https://alice.dev"])

    result = engine.compare(a, b)
    assert result is not None
    types = {item.type for item in result.evidence}
    assert EvidenceType.SAME_WEBSITE in types


# ---------------------------------------------------------------------------
# The avatar rule, which until now could not fire across platforms
# ---------------------------------------------------------------------------


def _profile(platform: str, identifier: str, **fields):
    from app.sources.base import ObservedProfile

    return ObservedProfile(
        platform=platform,
        identifier=identifier,
        name=f"@{identifier}",
        url=f"https://{platform}.com/{identifier}",
        **fields,
    )


def _avatar_evidence(source, target):
    from app.config import ScoringConfig
    from app.services.correlation import CorrelationEngine

    return [
        item
        for item in CorrelationEngine(ScoringConfig()).compare(source, target).evidence
        if item.type == "SAME_AVATAR"
    ]


def test_the_same_photograph_matches_across_two_platforms() -> None:
    """The case the rule exists for, and the one it could never reach.

    Two sites serve the same picture from completely different addresses, so
    comparing URLs found nothing. The hashes differ by two bits because each
    platform re-encoded it.
    """
    source = _profile(
        "instagram",
        "beaulebens",
        avatar_url="https://scontent.cdninstagram.com/v/t51.signed",
        avatar_hash="d3633918984c67a6",
    )
    target = _profile(
        "facebook",
        "beaulebens",
        avatar_url="https://scontent.xx.fbcdn.net/v/t1.other",
        avatar_hash="d3633918984c67a4",
    )

    found = _avatar_evidence(source, target)
    assert found, "different addresses, same picture"
    assert "bits differ" in found[0].description


def test_different_pictures_do_not_match() -> None:
    source = _profile("instagram", "a", avatar_url="https://a/x", avatar_hash="d3633918984c67a6")
    target = _profile("facebook", "b", avatar_url="https://b/y", avatar_hash="29313a9b894ca662")

    assert _avatar_evidence(source, target) == []


def test_a_shared_placeholder_is_not_evidence() -> None:
    """Two accounts that both have *no* picture are served the same address.

    A real crawl scored twenty-five points for exactly this, linking two
    unrelated Duolingo accounts because neither had uploaded a photograph.
    """
    url = "https://simg-ssl.duolingo.com/avatar/default_2"
    source = _profile("duolingo", "one", avatar_url=url, avatar_hash="aaaaaaaaaaaaaaaa")
    target = _profile("duolingo", "two", avatar_url=url, avatar_hash="aaaaaaaaaaaaaaaa")

    assert _avatar_evidence(source, target) == []


def test_the_same_address_still_counts() -> None:
    """A real picture served from one address to two profiles."""
    url = "https://cdn.example.com/photos/beau.jpg"
    source = _profile("devto", "a", avatar_url=url)
    target = _profile("medium", "b", avatar_url=url)

    found = _avatar_evidence(source, target)
    assert found
    assert "same address" in found[0].description


def test_a_profile_with_no_hash_and_no_shared_address_is_not_a_match() -> None:
    source = _profile("instagram", "a", avatar_url="https://a/x")
    target = _profile("facebook", "b", avatar_url="https://b/y")

    assert _avatar_evidence(source, target) == []
