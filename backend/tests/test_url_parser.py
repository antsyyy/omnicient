"""URL parsing, reference extraction and the SSRF guard."""

from __future__ import annotations

import pytest

from app.utils.url_parser import (
    detect_platform,
    extract_emails,
    extract_organizations,
    extract_references,
    extract_urls,
    extract_websites,
    parse_profile_url,
    website_identity,
)
from app.utils.validation import UnsafeURLError, is_blocked_ip, validate_public_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://instagram.com/alice_98", ("instagram", "alice_98")),
        ("https://www.threads.net/@alice_dev", ("threads", "alice_dev")),
        ("https://facebook.com/alice.example", ("facebook", "alice.example")),
        ("https://github.com/alice-security", ("github", "alice-security")),
        ("https://www.reddit.com/u/alice_security", ("reddit", "alice_security")),
        ("https://reddit.com/user/alice_security/", ("reddit", "alice_security")),
        ("https://x.com/alice98", ("x", "alice98")),
        ("https://twitter.com/alice98", ("x", "alice98")),
        ("https://linkedin.com/in/alice-r", ("linkedin", "alice-r")),
        ("https://youtube.com/@alicedev", ("youtube", "alicedev")),
    ],
)
def test_profile_urls_yield_platform_and_identifier(url, expected) -> None:
    assert parse_profile_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://instagram.com/p/ABC123/",
        "https://instagram.com/reel/XYZ",
        "https://facebook.com/profile.php?id=100",
        "https://x.com/intent/follow",
        "https://alice.dev/about",
        "https://example.com",
        "not-a-url",
        "",
    ],
)
def test_non_profile_urls_are_not_accounts(url) -> None:
    """An arbitrary URL must never be mistaken for a social profile."""
    assert parse_profile_url(url) is None


def test_detect_platform_and_website_identity() -> None:
    assert detect_platform("https://www.instagram.com/x") == "instagram"
    assert detect_platform("https://alice.dev") is None
    assert website_identity("https://www.alice.dev/") == "alice.dev"
    assert website_identity("http://alice.dev") == "alice.dev"
    # Social profiles are accounts, not shared websites.
    assert website_identity("https://github.com/alice-security") is None


def test_extract_urls_finds_links_and_bare_domains() -> None:
    text = "Portfolio https://alice.dev/blog and mirror alice-mirror.dev."
    assert extract_urls(text) == ["https://alice.dev/blog", "https://alice-mirror.dev"]


def test_extract_references_reads_links_and_text_mentions() -> None:
    references = extract_references(
        "Developer | Threads: @alice_dev | GitHub alice-security",
        ["https://reddit.com/u/alice_security"],
    )
    found = {(reference.platform, reference.identifier) for reference in references}
    assert found == {
        ("reddit", "alice_security"),
        ("threads", "alice_dev"),
        ("github", "alice-security"),
    }


def test_extract_references_ignores_plain_websites() -> None:
    references = extract_references("Site: https://alice.dev", [])
    assert references == []
    assert extract_websites("Site: https://alice.dev", []) == ["https://alice.dev"]


def test_extract_emails_and_organizations() -> None:
    assert extract_emails("Contact: Alice@Alice.dev") == ["alice@alice.dev"]
    assert extract_organizations("Security engineer at Contoso Labs. Threads: @a") == [
        "Contoso Labs"
    ]
    assert extract_organizations("works at the office") == []


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://127.0.0.1:8000/",
        "http://10.1.2.3/",
        "http://192.168.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://service.internal/",
        "file:///etc/passwd",
        "http://user:secret@alice.dev/",
    ],
)
def test_ssrf_guard_blocks_internal_targets(url) -> None:
    with pytest.raises(UnsafeURLError):
        validate_public_url(url)


def test_ssrf_guard_allows_public_urls() -> None:
    """The URL is returned in the form that will be requested, path intact."""
    validated = validate_public_url("https://alice.dev/about/?utm_source=x#top")
    assert validated.host == "alice.dev"
    assert validated.url == "https://alice.dev/about/"


def test_ssrf_guard_does_not_rewrite_the_host() -> None:
    """The validated URL is the one that gets requested, so www must survive."""
    validated = validate_public_url("https://www.python.org/")
    assert validated.host == "www.python.org"
    assert validated.url == "https://www.python.org/"


def test_is_blocked_ip() -> None:
    assert is_blocked_ip("127.0.0.1")
    assert is_blocked_ip("172.16.0.5")
    assert is_blocked_ip("not-an-ip")
    assert not is_blocked_ip("93.184.216.34")


@pytest.mark.parametrize(
    "bio",
    [
        "Follow my Instagram account for updates",
        "Check the GitHub profile here",
        "My Reddit page has more",
        "official Bluesky account (check username)",
        "Posting to Threads and Mastodon these days",
    ],
)
def test_a_platform_named_in_prose_is_not_a_reference(bio: str) -> None:
    """"Instagram account for updates" must not yield ``instagram:for``.

    A mention only counts when the platform word is attached to the handle by
    a separator or an "@"; bare adjacency is prose. Without this every bio
    that merely names a platform plants a junk node in the graph.
    """
    assert extract_references(bio, []) == []


@pytest.mark.parametrize(
    "bio,platform,identifier",
    [
        ("Threads: @alice_dev", "threads", "alice_dev"),
        ("GitHub - alice-security", "github", "alice-security"),
        ("IG @alice_98", "instagram", "alice_98"),
        ("FB: alice.private", "facebook", "alice.private"),
        ("Keybase: alice", "keybase", "alice"),
        ("Find me on Mastodon > @alice", "mastodon", "alice"),
        # Unattached, but the token carries handle punctuation.
        ("GitHub alice-security", "github", "alice-security"),
        ("Instagram alice_98", "instagram", "alice_98"),
    ],
)
def test_an_attached_mention_is_still_a_reference(
    bio: str, platform: str, identifier: str
) -> None:
    """The fix must not cost us the references that matter."""
    assert (platform, identifier) in {
        (reference.platform, reference.identifier)
        for reference in extract_references(bio, [])
    }


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://bsky.app/profile/alice.dev", ("bluesky", "alice.dev")),
        ("https://news.ycombinator.com/user?id=alice", ("hackernews", "alice")),
        ("https://keybase.io/alice", ("keybase", "alice")),
        ("https://dev.to/alice", ("devto", "alice")),
        # Not profiles: a starter pack, a story, a listing page.
        ("https://bsky.app/starter-pack/xyz123", None),
        ("https://news.ycombinator.com/item?id=123", None),
        ("https://news.ycombinator.com/newest", None),
        ("https://bsky.app/profile", None),
    ],
)
def test_profile_urls_for_the_live_sources(url: str, expected) -> None:
    """These platforms put the account behind a fixed prefix or a query param.

    Reading the first path segment instead yields entities like
    ``bluesky:starter-pack`` and ``hackernews:item``.
    """
    assert parse_profile_url(url) == expected
