"""Alias detection: explainable variants, and resistance to false positives.

The hard requirement is the negative one. Handles are short and reused, so a
detector that fires on string similarity alone will confidently connect
strangers - which is the exact failure Omnicient exists to avoid.
"""

from __future__ import annotations

import pytest

from app.models.enums import EvidenceType
from app.services.alias_detection import (
    AliasDetector,
    AliasStrength,
    Transformation,
    calculate_username_similarity,
    detect_transformations,
    extract_username_tokens,
    normalize_alias_candidate,
    root_token,
)
from app.services.correlation import EvidenceItem


def evidence(kind: EvidenceType, weight: float, supports: bool = True) -> EvidenceItem:
    return EvidenceItem(
        type=kind, description=f"{kind} observed", weight=weight, supports=supports
    )


# -- primitives -------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [("  Alice_98 ", "alice_98"), ("_alice-", "alice"), ("ALICE.SEC", "alice.sec")],
)
def test_normalize_alias_candidate(value: str, expected: str) -> None:
    assert normalize_alias_candidate(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("alice_98", ["alice", "98"]),
        ("alice-security", ["alice", "security"]),
        ("alice98", ["alice", "98"]),
        ("alice.dev.sec", ["alice", "dev", "sec"]),
    ],
)
def test_extract_username_tokens(value: str, expected: list[str]) -> None:
    assert extract_username_tokens(value) == expected


def test_root_token_ignores_short_and_generic_tokens() -> None:
    assert root_token("alice_98") == "alice"
    assert root_token("al_98") is None          # too short to mean anything
    assert root_token("admin_98") is None       # too generic to mean anything


# -- transformations --------------------------------------------------------


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("alice_98", "alice_98", Transformation.IDENTICAL),
        ("Alice_98", "alice_98", Transformation.CASE_ONLY),
        ("alice_security", "alice-security", Transformation.SEPARATOR_SUBSTITUTION),
        ("alice_98", "alice98", Transformation.SEPARATOR_REMOVED),
        ("alice98", "alice_98", Transformation.SEPARATOR_ADDED),
        ("alice", "alice98", Transformation.NUMERIC_SUFFIX_ADDED),
        ("alice98", "alice", Transformation.NUMERIC_SUFFIX_REMOVED),
        ("alice98", "alice22", Transformation.NUMERIC_SUFFIX_CHANGED),
        ("alice", "alice-security", Transformation.COMMON_SUFFIX_ADDED),
    ],
)
def test_transformations_are_named(a: str, b: str, expected: Transformation) -> None:
    assert str(expected) in detect_transformations(a, b)


@pytest.mark.parametrize(
    "a,b",
    [
        ("alex", "alexander"),      # different names sharing a prefix
        ("sam", "samantha"),
        ("bob_dev", "alice_dev"),   # shared suffix, different people
        ("john123", "jane456"),
        ("nasa", "natgeo"),
        ("admin", "admin_user"),    # generic root proves nothing
    ],
)
def test_unrelated_handles_produce_no_transformation(a: str, b: str) -> None:
    """The false-positive gate. A shared prefix is not a transformation."""
    assert detect_transformations(a, b) == []
    assert AliasDetector().compare(a, b) is None


def test_similarity_is_separator_blind() -> None:
    assert calculate_username_similarity("alice_98", "alice-98") >= 0.95
    assert calculate_username_similarity("alice_98", "alice_98") == 1.0
    assert calculate_username_similarity("alice", "bob") < 0.5


# -- candidates -------------------------------------------------------------


def test_the_same_handle_is_not_an_alias_of_itself() -> None:
    """Same handle on two platforms is SAME_USERNAME, not an alias."""
    assert AliasDetector().compare("alice_98", "alice_98") is None
    assert AliasDetector().compare("Alice_98", "alice_98") is None


def test_a_separator_variant_is_a_strong_resemblance() -> None:
    candidate = AliasDetector().compare("alice_security", "alice-security")
    assert candidate is not None
    assert candidate.strength is AliasStrength.STRONG
    assert candidate.signals
    assert "Potential" in candidate.summary or "potential" in candidate.summary


def test_resemblance_alone_cannot_reach_high_confidence() -> None:
    """A handle variant with no corroboration must stay low.

    This is the guard against the tool asserting an identity from spelling.
    """
    candidate = AliasDetector().compare("alice_security", "alice-security")
    assert candidate is not None
    assert candidate.confidence in ("LOW", "MEDIUM")


def test_contextual_evidence_strengthens_an_alias() -> None:
    detector = AliasDetector()
    bare = detector.compare("alice_security", "alice-security")
    corroborated = detector.compare(
        "alice_security",
        "alice-security",
        evidence=[
            evidence(EvidenceType.SAME_WEBSITE, 20),
            evidence(EvidenceType.SHARED_EMAIL, 40),
        ],
    )
    assert bare is not None and corroborated is not None
    assert corroborated.score > bare.score
    assert corroborated.supporting_evidence


def test_contradictory_evidence_weakens_an_alias() -> None:
    """A near-miss handle with conflicting attributes must not score highly."""
    detector = AliasDetector()
    weakened = detector.compare(
        "alice_98",
        "alice98",
        evidence=[
            evidence(EvidenceType.CONTRADICTORY_ATTRIBUTE, -20, supports=False),
            evidence(EvidenceType.CONTRADICTORY_ATTRIBUTE, -15, supports=False),
        ],
    )
    assert weakened is not None
    assert weakened.contradicting_evidence
    assert weakened.confidence == "LOW"
    assert weakened.score < 20


def test_detect_runs_over_the_demo_dataset() -> None:
    """End to end on the synthetic profiles, with correlation context."""
    from app.demo_data import build_demo_profiles
    from app.services.correlation import CorrelationEngine

    profiles = list(build_demo_profiles().values())
    results = CorrelationEngine().correlate(profiles)
    candidates = AliasDetector().detect(profiles, results)

    pairs = {
        (c.source_identifier, c.target_identifier) for c in candidates
    }
    assert ("alice-security", "alice_security") in pairs

    # The deliberate near-miss must be present but weak: it looks alike and
    # contradicts on website and location.
    near_miss = next(
        (c for c in candidates if {c.source_identifier, c.target_identifier}
         == {"alice_98", "alice98"}),
        None,
    )
    assert near_miss is not None
    assert near_miss.strength is AliasStrength.STRONG   # the handles do resemble
    assert near_miss.confidence == "LOW"                # the evidence does not
    assert near_miss.contradicting_evidence
