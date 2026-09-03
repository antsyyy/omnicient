"""Normalization: usernames, URLs, domains, platforms and similarity."""

from __future__ import annotations

import pytest

from app.utils.normalization import (
    NormalizationError,
    normalize_display_name,
    normalize_domain,
    normalize_location,
    normalize_platform,
    normalize_url,
    normalize_username,
    platform_label,
    text_similarity,
    username_similarity,
    username_variants,
)


@pytest.mark.parametrize(
    "raw",
    [
        "@Alice_Dev",
        "alice_dev",
        "Alice_Dev",
        " alice_dev ",
        "https://instagram.com/alice_dev/",
        "https://www.instagram.com/alice_dev?hl=en",
        "instagram.com/alice_dev",
        "https://www.threads.net/@alice_dev",
    ],
)
def test_username_forms_normalize_to_one_identifier(raw: str) -> None:
    assert normalize_username(raw) == "alice_dev"


def test_username_separators_are_preserved() -> None:
    """Different separators are different people on most platforms."""
    assert normalize_username("alice.dev") == "alice.dev"
    assert normalize_username("alice-dev") == "alice-dev"
    assert normalize_username("alice.dev") != normalize_username("alice_dev")


def test_trailing_punctuation_is_stripped() -> None:
    assert normalize_username("@alice_dev.") == "alice_dev"


@pytest.mark.parametrize("raw", ["", "   ", None, "@", "alice dev", "a" * 200])
def test_invalid_usernames_are_rejected(raw) -> None:
    with pytest.raises(NormalizationError):
        normalize_username(raw)


def test_post_urls_are_not_usernames() -> None:
    with pytest.raises(NormalizationError):
        normalize_username("https://instagram.com/p/ABC123/")


def test_normalize_url_strips_www_tracking_and_fragment() -> None:
    assert (
        normalize_url("http://WWW.Alice.dev/blog/?utm_source=x&id=7#top")
        == "http://alice.dev/blog?id=7"
    )


def test_normalize_url_handles_missing_scheme_and_trailing_slash() -> None:
    assert normalize_url("alice.dev/") == "https://alice.dev"


def test_normalize_url_can_preserve_the_form_to_request() -> None:
    """www.example.com/x/ and example.com/x can be different resources."""
    assert normalize_url("https://www.alice.dev/x/") == "https://alice.dev/x"
    assert (
        normalize_url("https://www.alice.dev/x/", canonical=False)
        == "https://www.alice.dev/x/"
    )
    assert normalize_domain("www.alice.dev", strip_www=False) == "www.alice.dev"


def test_normalize_url_rejects_non_http_schemes() -> None:
    assert normalize_url("mailto:alice@alice.dev") is None
    assert normalize_url("not a url") is None


@pytest.mark.parametrize(
    "raw", ["www.alice.dev", "alice.dev", "https://www.alice.dev/x", "ALICE.DEV:443"]
)
def test_domains_normalize_consistently(raw: str) -> None:
    assert normalize_domain(raw) == "alice.dev"


def test_platform_aliases_fold_onto_canonical_names() -> None:
    assert normalize_platform("Twitter") == "x"
    assert normalize_platform("IG") == "instagram"
    assert normalize_platform("fb") == "facebook"
    assert platform_label("github") == "GitHub"


def test_username_similarity_grades() -> None:
    assert username_similarity("alice_dev", "alice_dev") == 1.0
    # Separator-only differences score high but never exactly 1.0.
    assert 0.85 <= username_similarity("alice_dev", "alice.dev") < 1.0
    assert username_similarity("alice_dev", "bob_smith") < 0.5
    assert username_similarity("", "alice") == 0.0


def test_username_variants_cover_separator_spellings() -> None:
    variants = username_variants("alice_dev")
    assert set(variants) == {"alice_dev", "alice.dev", "alice-dev", "alicedev"}
    assert username_variants("alice") == ["alice"]


def test_display_name_and_location_normalization() -> None:
    assert normalize_display_name("  Alice   R.  ") == "alice r."
    assert normalize_display_name(None) is None
    assert normalize_location("Kathmandu, Nepal") == "kathmandu nepal"


def test_text_similarity_ignores_stopwords() -> None:
    high = text_similarity(
        "Security researcher and detection engineer",
        "Detection engineer, security researcher",
    )
    assert high > 0.8
    assert text_similarity("Security researcher", "Landscape photographer") == 0.0
