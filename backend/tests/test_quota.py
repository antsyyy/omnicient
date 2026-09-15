"""Living within a platform's rate limit instead of around it.

Omnicient does not evade limits - no proxy rotation, no spoofed identities, no
retry storms. It uses the three things the platforms themselves publish for
callers who need more room: don't re-ask for what you already have, revalidate
cheaply when you must, and authenticate if the operator has a credential.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.sources.base import FailureReason, SafeFetcher, SourceError
from app.sources.github import GitHubAdapter


def fetcher(handler, **overrides) -> SafeFetcher:
    settings = Settings(respect_robots=False, request_delay=0, **overrides)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    )
    return SafeFetcher(settings, client=client)


# ---------------------------------------------------------------------------
# Not asking twice
# ---------------------------------------------------------------------------


async def test_a_second_read_of_one_page_costs_no_request() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="<html>hi</html>",
                              headers={"content-type": "text/html"})

    f = fetcher(handler)
    first = await f.get("https://example.com/a")
    second = await f.get("https://example.com/a")
    await f.aclose()

    assert len(calls) == 1, "the second read must not reach the network"
    assert first.text == second.text
    assert not first.from_cache
    assert second.from_cache


async def test_a_stale_entry_is_fetched_again() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="fresh",
                              headers={"content-type": "text/plain"})

    f = fetcher(handler, cache_ttl_seconds=900)
    await f.get("https://example.com/a")
    f._cache[f._cache_key("https://example.com/a", None)].stored_at -= 10_000
    await f.get("https://example.com/a")
    await f.aclose()

    assert len(calls) == 2


async def test_reuse_can_be_turned_off() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="x", headers={"content-type": "text/plain"})

    f = fetcher(handler, cache_ttl_seconds=0)
    await f.get("https://example.com/a")
    await f.get("https://example.com/a")
    await f.aclose()

    assert len(calls) == 2


async def test_the_same_url_under_a_different_accept_is_a_different_read() -> None:
    """Several of these platforms serve JSON and HTML from one address."""
    served: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        accept = request.headers.get("accept", "")
        served.append(accept)
        body = '{"a":1}' if "json" in accept else "<html></html>"
        return httpx.Response(200, text=body, headers={"content-type": accept})

    f = fetcher(handler)
    j = await f.get("https://example.com/x", headers={"Accept": "application/json"})
    h = await f.get("https://example.com/x", headers={"Accept": "text/html"})
    await f.aclose()

    assert j.text == '{"a":1}'
    assert h.text == "<html></html>", "the JSON body must not be served as the page"
    assert len(served) == 2


# ---------------------------------------------------------------------------
# Revalidating cheaply
# ---------------------------------------------------------------------------


async def test_an_unchanged_page_is_revalidated_not_redownloaded() -> None:
    """A 304 costs nothing against every limit that documents one."""
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.headers))
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304, headers={"etag": '"v1"'})
        return httpx.Response(
            200, text="the body",
            headers={"content-type": "text/html", "etag": '"v1"'},
        )

    f = fetcher(handler, cache_ttl_seconds=900)
    await f.get("https://example.com/a")
    # Expire it: the body must be revalidated rather than trusted blindly.
    f._cache[f._cache_key("https://example.com/a", None)].stored_at -= 10_000
    second = await f.get("https://example.com/a")
    await f.aclose()

    assert seen[1].get("if-none-match") == '"v1"', "the validator must be offered"
    assert second.text == "the body", "a 304 serves the body we already held"
    assert second.from_cache


# ---------------------------------------------------------------------------
# Reporting the limit honestly
# ---------------------------------------------------------------------------


async def test_a_403_that_is_really_an_exhausted_quota_says_so() -> None:
    """GitHub answers an exhausted limit with 403, not 429.

    Reported as BLOCKED it reads as "the platform declined you", which sends
    an analyst hunting a permissions problem that does not exist.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, text="rate limited",
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-limit": "60"},
        )

    f = fetcher(handler)
    with pytest.raises(SourceError) as caught:
        await f.get("https://api.github.com/users/x")
    await f.aclose()

    assert caught.value.reason == FailureReason.RATE_LIMITED


async def test_a_genuine_refusal_is_still_reported_as_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    f = fetcher(handler)
    with pytest.raises(SourceError) as caught:
        await f.get("https://example.com/a")
    await f.aclose()

    assert caught.value.reason == FailureReason.BLOCKED


async def test_the_platforms_own_retry_time_is_passed_on() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="slow down", headers={"retry-after": "120"})

    f = fetcher(handler)
    with pytest.raises(SourceError) as caught:
        await f.get("https://example.com/a")
    await f.aclose()

    assert caught.value.reason == FailureReason.RATE_LIMITED
    assert "retry after 120s" in caught.value.detail


async def test_remaining_quota_is_recorded_for_the_operator() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text="{}",
            headers={
                "content-type": "application/json",
                "x-ratelimit-remaining": "4987",
                "x-ratelimit-limit": "5000",
            },
        )

    f = fetcher(handler)
    await f.get("https://api.github.com/users/x")
    await f.aclose()

    assert f.quota["api.github.com"]["remaining"] == "4987"
    assert f.quota["api.github.com"]["limit"] == "5000"


# ---------------------------------------------------------------------------
# The operator's own credential
# ---------------------------------------------------------------------------


def test_no_credential_is_sent_unless_one_is_configured(monkeypatch) -> None:
    monkeypatch.delenv("OMNICIENT_TOKEN_GITHUB", raising=False)
    adapter = GitHubAdapter(SafeFetcher(Settings()))

    assert adapter.credentials() == {}


def test_a_configured_credential_is_presented_as_the_platform_documents(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OMNICIENT_TOKEN_GITHUB", "ghp_example")
    adapter = GitHubAdapter(SafeFetcher(Settings()))

    assert adapter.credentials() == {"Authorization": "Bearer ghp_example"}


async def test_the_credential_reaches_the_platforms_own_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("OMNICIENT_TOKEN_GITHUB", "ghp_example")
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        return httpx.Response(
            200,
            json={"login": "octocat", "type": "User", "html_url": "https://x"},
            headers={"content-type": "application/json"},
        )

    f = fetcher(handler)
    await GitHubAdapter(f).lookup("octocat")
    await f.aclose()

    assert seen == ["Bearer ghp_example"]


def test_a_credential_is_never_written_into_a_log_line(monkeypatch) -> None:
    """The token is the one value here that must not leak anywhere."""
    monkeypatch.setenv("OMNICIENT_TOKEN_GITHUB", "ghp_secret_value")
    adapter = GitHubAdapter(SafeFetcher(Settings()))
    header = adapter.credentials()["Authorization"]

    assert "ghp_secret_value" in header
    # It exists only in the header: nothing puts it on the adapter, the
    # settings repr, or anywhere a log or an export would reach.
    assert "ghp_secret_value" not in repr(adapter.fetcher.settings)
    assert "ghp_secret_value" not in repr(adapter.__dict__)
