"""Source adapters: parsing public pages and refusing everything else."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.models.enums import EvidenceType
from app.sources.base import FailureReason, SafeFetcher, SourceError
from app.sources.bluesky import BlueskyAdapter
from app.sources.devto import DevToAdapter
from app.sources.facebook import FacebookAdapter
from app.sources.github import GitHubAdapter
from app.sources.instagram import InstagramAdapter
from app.sources.keybase import KeybaseAdapter
from app.sources.mastodon import MastodonAdapter
from app.sources.reddit import RedditAdapter
from app.sources.threads import ThreadsAdapter
from app.sources.website import WebsiteAdapter

INSTAGRAM_HTML = """
<html><head>
<meta property="og:title" content="Alice R. (@alice_98) &bull; Instagram photos and videos">
<meta property="og:description" content='120 Posts - Alice R. (@alice_98) on Instagram: "Security researcher. Threads: @alice_dev"'>
<meta property="og:image" content="https://alice.dev/media/avatar.png">
<meta property="og:url" content="https://www.instagram.com/alice_98/">
</head><body>{"external_url": "https://alice.dev"}</body></html>
"""

LOGIN_WALL_HTML = "<html><body><h1>Please log in to continue</h1></body></html>"

INTERSTITIAL_HTML = """
<html><head>
<meta property="og:title" content="Instagram">
<meta property="og:url" content="https://www.instagram.com/accounts/login/">
</head></html>
"""

WEBSITE_HTML = """
<html><head><title>alice.dev</title>
<meta property="og:site_name" content="Contoso Labs">
<meta name="description" content="Alice R., security researcher"></head>
<body>
  <a rel="me" href="https://github.com/alice-security">GitHub</a>
  <a href="/blog">Blog</a>
  <a href="https://www.reddit.com/u/alice_security">Reddit</a>
  <a href="https://instagram.com/p/ABC">A post</a>
  <p>Contact alice@alice.dev</p>
</body></html>
"""


GITHUB_JSON = {
    "login": "alice-security",
    "type": "User",
    "name": "Alice R.",
    "bio": "Security researcher at Contoso Labs. alice@alice.dev",
    "blog": "alice.dev",
    "company": "@ContosoLabs",
    "location": "Kathmandu",
    "avatar_url": "https://avatars.example/u/1.png",
    "html_url": "https://github.com/alice-security",
    "public_repos": 24,
    "email": None,
}

REDDIT_JSON = {
    "kind": "t2",
    "data": {
        "name": "alice_security",
        "icon_img": "https://styles.example/avatar.png?width=256&amp;s=abc",
        "total_karma": 1200,
        "subreddit": {
            "title": "Alice R.",
            "public_description": "Detection engineering. Blog: https://alice.dev",
        },
    },
}


def fetcher_returning(html: str, *, status: int = 200) -> SafeFetcher:
    """A fetcher whose transport answers every request from memory."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, html=html)

    settings = Settings(request_delay=0.0, respect_robots=False)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    return SafeFetcher(settings, client=client)


def test_instagram_parses_public_open_graph_metadata() -> None:
    adapter = InstagramAdapter()
    profile = adapter.parse_profile("alice_98", INSTAGRAM_HTML, "https://instagram.com/alice_98/")

    assert profile is not None
    assert profile.display_name == "Alice R."
    assert profile.bio.startswith("Security researcher")
    assert profile.avatar_url == "https://alice.dev/media/avatar.png"
    assert "https://alice.dev" in profile.external_links
    assert ("threads", "alice_dev") in {reference.key for reference in profile.references}


def test_instagram_rejects_an_interstitial_page() -> None:
    """A login page served with HTTP 200 is not a profile."""
    assert InstagramAdapter().parse_profile("alice_98", INTERSTITIAL_HTML, "url") is None


async def test_login_wall_is_reported_as_private() -> None:
    adapter = ThreadsAdapter(fetcher_returning(LOGIN_WALL_HTML))
    result = await adapter.lookup("alice_dev")

    assert not result.ok
    assert result.reason == FailureReason.PRIVATE
    assert result.entities == []


async def test_http_errors_become_structured_failures() -> None:
    adapter = InstagramAdapter(fetcher_returning("nope", status=429))
    result = await adapter.lookup("alice_98")
    assert result.reason == FailureReason.RATE_LIMITED

    adapter = InstagramAdapter(fetcher_returning("nope", status=404))
    assert (await adapter.lookup("alice_98")).reason == FailureReason.NOT_FOUND

    adapter = InstagramAdapter(fetcher_returning("nope", status=403))
    assert (await adapter.lookup("alice_98")).reason == FailureReason.BLOCKED


def test_website_ignores_its_own_internal_pages() -> None:
    """Internal links are not new pivots; other hosts are."""
    html = """
    <html><body>
      <a href="/about">About</a>
      <a href="https://alice.dev/blog">Blog</a>
      <a href="https://notes.alice.dev/">Notes</a>
      <a href="https://alice-mirror.dev/">Mirror</a>
    </body></html>
    """
    profile = WebsiteAdapter().parse_page(html, "https://alice.dev/")
    assert profile.websites == ["https://notes.alice.dev", "https://alice-mirror.dev"]


def test_website_extracts_identities_contacts_and_organizations() -> None:
    profile = WebsiteAdapter().parse_page(WEBSITE_HTML, "https://alice.dev/")

    assert profile.identifier == "alice.dev"
    assert profile.emails == ["alice@alice.dev"]
    assert "Contoso Labs" in profile.organizations

    references = {reference.key: reference for reference in profile.references}
    assert ("github", "alice-security") in references
    assert ("reddit", "alice_security") in references
    # A post URL is not an account.
    assert ("instagram", "p") not in references
    assert 'rel="me"' in references[("github", "alice-security")].context


async def test_fetcher_refuses_internal_targets() -> None:
    fetcher = fetcher_returning("<html></html>")
    with pytest.raises(SourceError) as excinfo:
        await fetcher.get("http://169.254.169.254/latest/meta-data/")
    assert excinfo.value.reason == FailureReason.UNSAFE_URL


async def test_fetcher_enforces_the_response_size_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 5000)

    settings = Settings(request_delay=0.0, respect_robots=False, max_response_bytes=1000)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    with pytest.raises(SourceError) as excinfo:
        await SafeFetcher(settings, client=client).get("https://alice.dev/")
    assert excinfo.value.reason == FailureReason.TOO_LARGE


async def test_fetcher_validates_redirect_destinations() -> None:
    """A public host must not be able to redirect the crawler inside the network."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "alice.dev":
            return httpx.Response(302, headers={"location": "http://127.0.0.1:8000/admin"})
        return httpx.Response(200, html="<html></html>")

    settings = Settings(request_delay=0.0, respect_robots=False)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    with pytest.raises(SourceError) as excinfo:
        await SafeFetcher(settings, client=client).get("https://alice.dev/")
    assert excinfo.value.reason == FailureReason.UNSAFE_URL


async def test_fetcher_follows_a_www_redirect() -> None:
    """A bare domain redirecting to its www host must resolve, not loop."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "alice.dev":
            return httpx.Response(301, headers={"location": "https://www.alice.dev/"})
        return httpx.Response(200, html="<html><title>ok</title></html>")

    settings = Settings(request_delay=0.0, respect_robots=False)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    result = await SafeFetcher(settings, client=client).get("https://alice.dev/")

    assert result.status_code == 200
    assert result.url == "https://www.alice.dev/"
    assert seen == ["https://alice.dev/", "https://www.alice.dev/"]


async def test_fetcher_follows_a_trailing_slash_redirect() -> None:
    """/psf -> /psf/ is a redirect, not a loop."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/psf":
            return httpx.Response(301, headers={"location": "https://alice.dev/psf/"})
        return httpx.Response(200, html="<html><title>ok</title></html>")

    settings = Settings(request_delay=0.0, respect_robots=False)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    result = await SafeFetcher(settings, client=client).get("https://alice.dev/psf")
    assert result.status_code == 200
    assert result.url == "https://alice.dev/psf/"


async def test_fetcher_detects_a_redirect_loop() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://alice.dev/"})

    settings = Settings(request_delay=0.0, respect_robots=False)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    with pytest.raises(SourceError) as excinfo:
        await SafeFetcher(settings, client=client).get("https://alice.dev/")
    assert "redirect loop" in str(excinfo.value)


async def test_demo_adapters_never_touch_the_network(demo_registry) -> None:
    result = await demo_registry.get("instagram").lookup("@Alice_98")
    profile = result.primary
    assert profile is not None
    assert profile.metadata["notice"] == "DEMO DATA"
    assert (await demo_registry.get("instagram").lookup("nobody")).entities == []



def fetcher_returning_json(payload, *, status: int = 200) -> SafeFetcher:
    """A fetcher whose transport answers every request with JSON."""
    import json as _json

    body = payload if isinstance(payload, str) else _json.dumps(payload)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, content=body, headers={"content-type": "application/json"}
        )

    settings = Settings(request_delay=0.0, respect_robots=False)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    )
    return SafeFetcher(settings, client=client)


async def test_github_reads_the_public_user_document() -> None:
    adapter = GitHubAdapter(fetcher_returning_json(GITHUB_JSON))
    result = await adapter.lookup("alice-security")

    assert result.ok
    profile = result.primary
    assert profile is not None
    assert profile.display_name == "Alice R."
    assert profile.location == "Kathmandu"
    assert profile.organization == "ContosoLabs"
    # ``blog`` is free text and often omits the scheme.
    assert "https://alice.dev" in profile.external_links
    # The address published in the bio is picked up by the shared enrichment.
    assert "alice@alice.dev" in profile.emails


async def test_github_ignores_organization_accounts() -> None:
    """An org is a real account, but not one an identity correlates through."""
    adapter = GitHubAdapter(
        fetcher_returning_json({**GITHUB_JSON, "type": "Organization"})
    )
    result = await adapter.lookup("contoso-labs")
    assert result.ok
    assert result.primary is None


async def test_github_rate_limiting_is_reported_not_evaded() -> None:
    adapter = GitHubAdapter(fetcher_returning_json({}, status=429))
    result = await adapter.lookup("alice-security")
    assert result.reason == FailureReason.RATE_LIMITED


async def test_reddit_reads_the_public_about_document() -> None:
    adapter = RedditAdapter(fetcher_returning_json(REDDIT_JSON))
    result = await adapter.lookup("alice_security")

    assert result.ok
    profile = result.primary
    assert profile is not None
    assert profile.display_name == "Alice R."
    assert profile.bio.startswith("Detection engineering")
    # The avatar URL arrives HTML-escaped and query-tagged.
    assert profile.avatar_url == "https://styles.example/avatar.png"
    assert "https://alice.dev" in profile.websites


async def test_reddit_skips_suspended_accounts() -> None:
    payload = {"data": {"name": "gone", "is_suspended": True}}
    adapter = RedditAdapter(fetcher_returning_json(payload))
    result = await adapter.lookup("gone")
    assert result.ok
    assert result.primary is None


async def test_a_json_source_that_serves_html_is_a_parse_error() -> None:
    """A block page served where JSON was expected must not crash the crawl."""
    adapter = RedditAdapter(fetcher_returning_json("<html>blocked</html>"))
    result = await adapter.lookup("alice_security")
    assert result.reason == FailureReason.PARSE_ERROR


async def test_a_blocked_json_source_is_reported() -> None:
    adapter = RedditAdapter(fetcher_returning_json({}, status=403))
    result = await adapter.lookup("alice_security")
    assert result.reason == FailureReason.BLOCKED


async def test_json_sources_ask_for_json_not_html() -> None:
    """A JSON API answers 415 to the shared client's HTML Accept header.

    The mock transport ignores headers, so only asserting on the header
    actually sent catches this - it is invisible in a response-shape test.
    """
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[str(request.url)] = request.headers.get("accept", "")
        return httpx.Response(200, json=GITHUB_JSON)

    settings = Settings(request_delay=0.0, respect_robots=False)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    )
    adapter = GitHubAdapter(SafeFetcher(settings, client=client))
    await adapter.lookup("alice-security")

    accept = seen["https://api.github.com/users/alice-security"]
    assert "json" in accept
    assert "text/html" not in accept


async def test_html_sources_still_ask_for_html() -> None:
    """Overriding Accept per request must not change the HTML adapters."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[str(request.url)] = request.headers.get("accept", "")
        return httpx.Response(200, html=INSTAGRAM_HTML)

    settings = Settings(request_delay=0.0, respect_robots=False)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    )
    await InstagramAdapter(SafeFetcher(settings, client=client)).lookup("alice_98")

    assert "text/html" in next(iter(seen.values()))


KEYBASE_JSON = {
    "status": {"code": 0},
    "them": {
        "basics": {"username": "alice"},
        "profile": {"full_name": "Alice R.", "location": "Kathmandu"},
        "pictures": {"primary": {"url": "https://keybase.io/alice/avatar.jpg"}},
        "proofs_summary": {
            "all": [
                {"proof_type": "github", "nametag": "alice-security",
                 "service_url": "https://github.com/alice-security"},
                {"proof_type": "twitter", "nametag": "alice_x",
                 "service_url": "https://twitter.com/alice_x"},
                {"proof_type": "dns", "nametag": "alice.dev",
                 "service_url": "https://alice.dev"},
                {"proof_type": "zcash", "nametag": "zs1abc"},
            ]
        },
    },
}

DEVTO_JSON = {
    "username": "alice",
    "name": "Alice R.",
    "summary": "Security researcher.",
    "website_url": "https://alice.dev",
    "github_username": "alice-security",
    "twitter_username": "@alice_x",
}


async def test_keybase_turns_verified_proofs_into_explicit_references() -> None:
    """A Keybase proof is the strongest legitimate cross-platform signal."""
    adapter = KeybaseAdapter(fetcher_returning_json(KEYBASE_JSON))
    profile = (await adapter.lookup("alice")).primary

    assert profile is not None
    assert profile.display_name == "Alice R."
    refs = {(r.platform, r.identifier) for r in profile.references}
    assert ("github", "alice-security") in refs
    assert ("x", "alice_x") in refs
    # A DNS proof names a domain the user controls, not an account.
    assert any("alice.dev" in site for site in profile.websites)
    # An unmapped proof type is ignored rather than guessed at.
    assert not any(platform == "zcash" for platform, _ in refs)
    assert all(r.explicit for r in profile.references)


async def test_keybase_reports_an_unknown_user_as_no_data() -> None:
    adapter = KeybaseAdapter(fetcher_returning_json({"status": {"code": 205}}))
    result = await adapter.lookup("nobody")
    assert result.ok
    assert result.primary is None


async def test_devto_reads_the_handles_the_user_declared() -> None:
    """dev.to asks users for their GitHub and Twitter directly."""
    adapter = DevToAdapter(fetcher_returning_json(DEVTO_JSON))
    profile = (await adapter.lookup("alice")).primary

    assert profile is not None
    refs = {(r.platform, r.identifier) for r in profile.references}
    assert ("github", "alice-security") in refs
    # A leading "@" is stripped from the declared handle.
    assert ("x", "alice_x") in refs


async def test_mastodon_reads_profile_fields_and_strips_markup() -> None:
    payload = {
        "username": "alice",
        "display_name": "Alice R.",
        "note": "<p>Security researcher</p>",
        "url": "https://mastodon.social/@alice",
        "avatar_static": "https://files.example/a.png",
        "fields": [
            {"name": "GitHub",
             "value": '<a href="https://github.com/alice-security">alice-security</a>'}
        ],
    }
    adapter = MastodonAdapter(fetcher_returning_json(payload))
    profile = (await adapter.lookup("alice")).primary

    assert profile is not None
    assert profile.bio is not None and "<p>" not in profile.bio
    assert "https://github.com/alice-security" in profile.external_links
    assert ("github", "alice-security") in {
        (r.platform, r.identifier) for r in profile.references
    }


async def test_mastodon_only_queries_allowed_instances() -> None:
    """The handle picks the host, so an allow-list is the SSRF boundary."""
    adapter = MastodonAdapter()
    assert "fosstodon.org" in adapter.api_url("alice@fosstodon.org")
    # An unknown instance falls back rather than being fetched.
    assert "mastodon.social" in adapter.api_url("alice@evil.example")
    assert "evil.example" not in adapter.api_url("alice@evil.example")


async def test_bluesky_treats_a_custom_domain_handle_as_a_website() -> None:
    """A custom Bluesky handle is a proven claim of that domain."""
    payload = {"handle": "alice.dev", "displayName": "Alice R.", "did": "did:plc:x"}
    profile = (await BlueskyAdapter(fetcher_returning_json(payload)).lookup(
        "alice.dev"
    )).primary
    assert profile is not None
    assert "https://alice.dev" in profile.external_links

    # A bsky.social handle is issued by the platform and proves nothing.
    payload = {"handle": "alice.bsky.social", "displayName": "Alice"}
    profile = (await BlueskyAdapter(fetcher_returning_json(payload)).lookup(
        "alice"
    )).primary
    assert profile is not None
    assert profile.external_links == []


async def test_mastodon_does_not_shatter_a_link_across_invisible_spans() -> None:
    """Mastodon renders a long URL in fragments; flattening splits it in two.

    ``bsky.app/profile/freshyill.bsky.social`` becomes ``freshyill.bsk`` plus
    ``y.social`` if the markup is stripped to whitespace - two accounts that do
    not exist, both landing in the graph as real entities.
    """
    payload = {
        "username": "chris",
        "note": "<p>Hello</p>",
        "fields": [
            {
                "name": "Bluesky",
                "value": (
                    '<a href="https://bsky.app/profile/freshyill.bsky.social">'
                    '<span class="invisible">https://</span>'
                    '<span class="ellipsis">bsky.app/profile/freshyill.bsk</span>'
                    '<span class="invisible">y.social</span></a>'
                ),
            }
        ],
    }
    profile = (await MastodonAdapter(fetcher_returning_json(payload)).lookup(
        "chris"
    )).primary

    assert profile is not None
    assert profile.external_links == [
        "https://bsky.app/profile/freshyill.bsky.social"
    ]
    identifiers = {reference.identifier for reference in profile.references}
    assert "freshyill.bsk" not in identifiers
    assert not any("y.social" in site for site in profile.websites)


# Real markup shapes, trimmed. Meta prefixes every description with audience
# counts; treating those as biography text makes unrelated accounts look alike.
IG_STATS_HTML = """
<html><head>
<meta property="og:title" content="NASA (@nasa) &bull; Instagram photos and videos">
<meta property="og:description" content="104M Followers, 95 Following, 4,914 Posts - See Instagram photos and videos from NASA (@nasa)">
<meta name="description" content='104M Followers, 95 Following, 4,914 Posts - NASA (@nasa) on Instagram: "Making the impossible possible."'>
<meta property="og:image" content="https://example/a.jpg">
<meta property="og:url" content="https://www.instagram.com/nasa/">
</head></html>
"""

FB_VANITY_HTML = """
<html><head>
<meta property="og:title" content="Coca-Cola">
<meta property="og:description" content="Coca-Cola. 106,984,120 likes &middot; 865 talking about this. The Page is a collection of your stories.">
<meta property="og:image" content="https://example/c.png">
<meta property="og:url" content="https://www.facebook.com/Coca-Cola/">
</head></html>
"""


def test_instagram_bio_is_the_biography_not_the_follower_counts() -> None:
    profile = InstagramAdapter().parse_profile(
        "nasa", IG_STATS_HTML, "https://www.instagram.com/nasa/"
    )
    assert profile is not None
    assert profile.bio == "Making the impossible possible."
    assert "Followers" not in (profile.bio or "")
    # The counts are still observed, just not as biography text.
    assert profile.metadata["followers"] == "104M"
    assert profile.metadata["posts"] == "4,914"


def test_two_profiles_with_only_counts_in_common_do_not_share_a_bio() -> None:
    """The false positive the strip exists to prevent."""
    from app.services.correlation import CorrelationEngine

    a = InstagramAdapter().parse_profile(
        "nasa", IG_STATS_HTML, "https://www.instagram.com/nasa/"
    )
    other = IG_STATS_HTML.replace("nasa", "natgeo").replace(
        "Making the impossible possible.", "Taking you on a journey."
    )
    b = InstagramAdapter().parse_profile(
        "natgeo", other, "https://www.instagram.com/natgeo/"
    )
    result = CorrelationEngine().compare(a, b)
    types = {item.type for item in (result.evidence if result else [])}
    assert EvidenceType.SIMILAR_BIO not in types


def test_facebook_accepts_the_canonical_spelling_of_a_vanity_handle() -> None:
    """Facebook answers /cocacola with canonical /Coca-Cola/."""
    profile = FacebookAdapter().parse_profile(
        "cocacola", FB_VANITY_HTML, "https://www.facebook.com/cocacola"
    )
    assert profile is not None
    assert profile.display_name == "Coca-Cola"
    assert profile.bio == "The Page is a collection of your stories."
    assert profile.metadata["likes"] == "106,984,120"


def test_a_genuinely_different_account_is_still_rejected() -> None:
    """Relaxing the check must not let another account through."""
    assert (
        FacebookAdapter().parse_profile(
            "someone-else", FB_VANITY_HTML, "https://www.facebook.com/someone-else"
        )
        is None
    )
