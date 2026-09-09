"""Identifier detection: the layer that removes platform selection."""

from __future__ import annotations

import pytest

from app.utils.identifier import (
    DetectedIdentifier,
    IdentifierType,
    detect_identifier,
)
from app.utils.normalization import NormalizationError


def detect(value: str) -> DetectedIdentifier:
    return detect_identifier(value)


# -- usernames --------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("alice_98", "alice_98"),
        ("@alice_98", "alice_98"),
        ("  alice_98  ", "alice_98"),
        ("Alice_98", "alice_98"),
        ("alice-security", "alice-security"),
        ("alice.dev98", "alice.dev98"),
    ],
)
def test_a_bare_handle_is_a_username(value: str, expected: str) -> None:
    detected = detect(value)
    assert detected.type is IdentifierType.USERNAME
    assert detected.identifier == expected
    # No platform is inferred: that is what makes the search fan out.
    assert detected.platform is None
    assert detected.seed_platform == "username"


def test_the_raw_input_is_preserved() -> None:
    """Normalization must never destroy what the analyst actually typed."""
    detected = detect("  @Alice_98 ")
    assert detected.raw == "@Alice_98"
    assert detected.identifier == "alice_98"


# -- emails -----------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["alice@example.com", "ALICE@Example.COM", "mailto:alice@example.com"],
)
def test_an_email_address_is_detected(value: str) -> None:
    detected = detect(value)
    assert detected.type is IdentifierType.EMAIL
    assert detected.identifier == "alice@example.com"
    assert detected.platform == "email"


def test_an_email_is_not_mistaken_for_a_domain() -> None:
    assert detect("alice@alice.dev").type is IdentifierType.EMAIL


# -- profile URLs -----------------------------------------------------------


@pytest.mark.parametrize(
    "value,platform,identifier",
    [
        ("https://instagram.com/alice_98", "instagram", "alice_98"),
        ("https://www.instagram.com/alice_98/", "instagram", "alice_98"),
        ("https://github.com/alice-security", "github", "alice-security"),
        ("https://www.reddit.com/user/alice_security", "reddit", "alice_security"),
        ("https://www.reddit.com/u/alice_security", "reddit", "alice_security"),
        ("https://www.threads.net/@alice_dev", "threads", "alice_dev"),
        ("instagram.com/alice_98", "instagram", "alice_98"),
    ],
)
def test_a_profile_url_names_its_own_platform(
    value: str, platform: str, identifier: str
) -> None:
    detected = detect(value)
    assert detected.type is IdentifierType.PROFILE_URL
    assert detected.platform == platform
    assert detected.identifier == identifier
    assert detected.seed_platform == platform


@pytest.mark.parametrize(
    "value",
    [
        "https://instagram.com/p/CxYz123",
        "https://www.facebook.com/profile.php?id=123",
        "https://instagram.com/accounts/login/",
    ],
)
def test_a_non_profile_url_on_a_known_host_is_refused(value: str) -> None:
    """A post link names no account, so guessing a seed from it is wrong.

    It is not quietly downgraded to a website seed either: crawling
    instagram.com because someone pasted a post link would spend the budget
    somewhere they never asked about.
    """
    with pytest.raises(NormalizationError):
        detect_identifier(value)


# -- domains ----------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("alice.dev", "alice.dev"),
        ("www.alice.dev", "alice.dev"),
        ("https://www.alice.dev/", "alice.dev"),
        ("ALICE.DEV", "alice.dev"),
    ],
)
def test_a_domain_is_detected_and_normalized(value: str, expected: str) -> None:
    detected = detect(value)
    assert detected.type in (IdentifierType.DOMAIN, IdentifierType.WEBSITE_URL)
    assert detected.identifier == expected
    assert detected.platform == "website"


def test_a_url_with_a_path_is_a_website_url() -> None:
    detected = detect("https://alice.dev/about")
    assert detected.type is IdentifierType.WEBSITE_URL
    assert detected.identifier == "alice.dev"
    assert detected.url == "https://alice.dev/about"


# -- invalid input ----------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        None,
        "not a valid identifier",
        "@@@",
        "a b c",
        "!!!",
    ],
)
def test_invalid_input_is_rejected(value: str | None) -> None:
    with pytest.raises(NormalizationError):
        detect_identifier(value)


def test_an_over_long_identifier_is_rejected() -> None:
    with pytest.raises(NormalizationError):
        detect_identifier("a" * 5000)


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "ftp://example.com/pub",
        "data:text/html,<script>",
    ],
)
def test_non_http_schemes_are_rejected(value: str) -> None:
    """A non-HTTP scheme must be refused, never silently read as a handle."""
    with pytest.raises(NormalizationError):
        detect_identifier(value)


# -- fan-out ----------------------------------------------------------------


def test_a_username_fans_out_across_supported_account_sources() -> None:
    """A platform-less handle asks every account source, and assumes none."""
    from app.services.discovery import discover_sources

    candidates = discover_sources(
        "alice_98",
        platforms=["instagram", "threads", "facebook", "website", "email"],
        parent_key=("USERNAME", "username", "alice_98"),
    )
    platforms = {candidate.platform for candidate in candidates}

    assert platforms == {"instagram", "threads", "facebook"}
    # Every one is a question, not an assumption: an unresolved search leaves
    # no node behind.
    assert all(candidate.drop_if_unresolved for candidate in candidates)
    assert all(candidate.identifier == "alice_98" for candidate in candidates)
