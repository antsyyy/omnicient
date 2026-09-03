"""Source adapters: parsing public pages and refusing everything else."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.sources.base import FailureReason, SafeFetcher, SourceError
from app.sources.instagram import InstagramAdapter
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
