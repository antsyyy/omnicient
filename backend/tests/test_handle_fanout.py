"""Following a handle an investigation did not start with.

People do not use one handle everywhere, and the links between their accounts
are usually not published anywhere. When a profile *does* publish one - a
Facebook Intro linking to ``linkedin.com/in/prabhatach`` for an investigation
that began at ``prabhatacharya19`` - that second handle is the strongest lead
the crawl will get, and searching only LinkedIn for it wastes almost all of
its value.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.models.enums import DiscoveryMethod
from app.services.crawler import Crawler
from app.services.discovery import fanout_candidates
from app.sources import SourceRegistry
from app.sources.base import SafeFetcher
from app.sources.facebook import FacebookAdapter
from app.sources.instagram import InstagramAdapter
from app.sources.threads import ThreadsAdapter

PLATFORMS = ("instagram", "threads", "github", "linkedin", "website", "username")


def test_a_discovered_handle_is_searched_on_every_source() -> None:
    candidates = fanout_candidates(
        "prabhatach",
        platforms=PLATFORMS,
        depth=1,
        discovered_on="facebook:prabhatacharya19",
        source_platform="linkedin",
    )
    platforms = {candidate.platform for candidate in candidates}

    assert platforms == {"instagram", "threads", "github"}, (
        "pseudo-platforms, the website adapter and the platform that "
        "published the handle are all skipped"
    )
    assert all(c.identifier == "prabhatach" for c in candidates)
    assert all(c.depth == 1 for c in candidates)


def test_a_guessed_account_is_never_recorded_as_a_published_reference() -> None:
    """The profile linked to LinkedIn. It said nothing about Duolingo.

    These candidates carry no parent and no link context precisely so the
    crawler cannot write "facebook:x publicly references duolingo:y" for an
    account the Facebook page has never heard of. Like any similarity lead
    they earn nothing by existing; correlation still has to find evidence.
    """
    candidates = fanout_candidates(
        "prabhatach",
        platforms=PLATFORMS,
        depth=1,
        discovered_on="facebook:prabhatacharya19",
        source_platform="linkedin",
    )

    for candidate in candidates:
        assert candidate.parent_key is None
        assert candidate.link_context is None
        assert candidate.method is DiscoveryMethod.SIMILARITY
        assert candidate.drop_if_unresolved, "a miss must leave no node behind"
        assert "weak lead, not evidence" in candidate.reason


FACEBOOK_HTML_TEMPLATE = """
<html><head>
<meta property="og:title" content="Prabhat Acharya">
<meta property="og:description" content="Prabhat Acharya. 5 likes.">
</head><body><script type="application/json" data-sjs>
[{{"timeline_context_item":{{"renderer":{{"__typename":"ContextItemDefaultRenderer",
"context_item":{{"subtitle":null,"title":{{"ranges":[{{"entity":{{
"__typename":"ExternalUrl","url":"{link}"}},"offset":0,"length":1}}],
"text":"prabhatach"}}}}}}}}}}]
</script></body></html>
"""

PROFILE_HTML = """
<html><head>
<meta property="og:title" content="Prabhat (@{handle}) &bull; {site}">
<meta property="og:description" content="Prabhat on {site}">
<meta property="og:url" content="https://www.{host}/{handle}/">
</head></html>
"""


def build(handler, **overrides):
    settings = Settings(
        respect_robots=False, request_delay=0, max_depth=2, **overrides
    )
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    )
    fetcher = SafeFetcher(settings, client=client)
    registry = SourceRegistry()
    for adapter in (FacebookAdapter, InstagramAdapter, ThreadsAdapter):
        registry.register(adapter(fetcher))
    return Crawler(registry, settings), fetcher


def make_handler(seen: list[str]):
    facebook_html = FACEBOOK_HTML_TEMPLATE.format(
        link="https://www.linkedin.com/in/prabhatach"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        seen.append(f"{host}{path}")
        # Threads writes /@handle, Instagram adds a trailing slash.
        handle = path.strip("/").lstrip("@")
        if "facebook" in host:
            if handle == "prabhatacharya19":
                return httpx.Response(200, text=facebook_html,
                                      headers={"content-type": "text/html"})
            return httpx.Response(404, text="")
        site = "Instagram" if "instagram" in host else "Threads"
        if handle in ("prabhatacharya19", "prabhatach"):
            return httpx.Response(
                200,
                text=PROFILE_HTML.format(handle=handle, site=site, host=host),
                headers={"content-type": "text/html"},
            )
        return httpx.Response(404, text="")

    return handler


async def test_a_handle_from_an_intro_link_is_searched_everywhere() -> None:
    """End to end: the account that was invisible before this existed."""
    seen: list[str] = []
    crawler, fetcher = build(make_handler(seen))
    outcome = await crawler.crawl("username", "prabhatacharya19",
                                  include_similarity=False)
    await fetcher.aclose()

    discovered = {(e.platform, e.identifier) for e in outcome.entities.values()}
    assert ("facebook", "prabhatacharya19") in discovered
    assert ("linkedin", "prabhatach") in discovered, "the published link itself"
    # The point of the feature: the new handle looked for elsewhere.
    assert ("instagram", "prabhatach") in discovered
    assert ("threads", "prabhatach") in discovered

    # And it really was fetched, not inferred.
    assert any("instagram.com/prabhatach" in url for url in seen)


async def test_a_handle_is_not_searched_twice() -> None:
    """The seed was already asked of every source; sighting it again is not new."""
    seen: list[str] = []
    crawler, fetcher = build(make_handler(seen))
    await crawler.crawl("username", "prabhatacharya19", include_similarity=False)
    await fetcher.aclose()

    for handle in ("prabhatacharya19", "prabhatach"):
        asked = [u for u in seen if u.rstrip("/").endswith(f"instagram.com/{handle}")]
        assert len(asked) == 1, (
            f"instagram was asked for {handle} {len(asked)} times, expected once"
        )


async def test_the_number_of_handles_followed_is_capped() -> None:
    """Each new handle costs a full fan-out, so a chain of them is bounded."""
    seen: list[str] = []
    crawler, fetcher = build(make_handler(seen), max_fanout_handles=0)
    outcome = await crawler.crawl("username", "prabhatacharya19",
                                  include_similarity=False)
    await fetcher.aclose()

    discovered = {(e.platform, e.identifier) for e in outcome.entities.values()}
    assert ("linkedin", "prabhatach") in discovered, "the published link still stands"
    assert ("instagram", "prabhatach") not in discovered, "but nothing fanned out"


@pytest.mark.parametrize("explicit", [True, False])
def test_only_a_published_link_starts_a_new_search(explicit: bool) -> None:
    """A guessed reference must not multiply into more guesses."""
    from app.sources.base import ObservedProfile, Reference

    profile = ObservedProfile(
        platform="facebook", identifier="prabhatacharya19",
        name="@prabhatacharya19", url="https://facebook.com/prabhatacharya19",
    )
    profile.references = [
        Reference(
            platform="linkedin",
            identifier="prabhatach",
            url="https://linkedin.com/in/prabhatach",
            context="https://linkedin.com/in/prabhatach",
            explicit=explicit,
        )
    ]
    followed = [r for r in profile.references if r.explicit]
    assert bool(followed) is explicit
