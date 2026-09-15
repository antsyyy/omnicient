"""Source adapter interface and the safe HTTP client every adapter shares.

Adapters only ever issue plain, unauthenticated GET requests for pages that are
publicly reachable.  Explicitly out of scope, by design: authentication,
session or cookie reuse, CAPTCHA handling, proxy rotation, undocumented private
endpoints and every other form of rate-limit or anti-bot evasion.  When a
platform declines to serve public data, the adapter returns a structured error
and the investigation continues with whatever evidence it already has.
"""

from __future__ import annotations

import asyncio
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from ..models.enums import EntityType
from ..utils.logging import get_logger
from ..utils.normalization import normalize_url
from ..utils.url_parser import Reference
from ..utils.validation import UnsafeURLError, resolve_public_host, validate_public_url

logger = get_logger(__name__)


class FailureReason(StrEnum):
    """Why a source lookup did not return public data."""

    NOT_FOUND = "NOT_FOUND"
    PRIVATE = "PRIVATE"
    BLOCKED = "BLOCKED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    ROBOTS_DISALLOWED = "ROBOTS_DISALLOWED"
    UNSAFE_URL = "UNSAFE_URL"
    TOO_LARGE = "TOO_LARGE"
    PARSE_ERROR = "PARSE_ERROR"
    UNSUPPORTED = "UNSUPPORTED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


# Analyst-facing explanations, shown in the UI when a source is unavailable.
REASON_MESSAGES: dict[str, str] = {
    FailureReason.NOT_FOUND: "No public profile found at that address.",
    FailureReason.PRIVATE: "The profile is private or hidden behind a login wall.",
    FailureReason.BLOCKED: "The platform declined the request (HTTP 401/403).",
    FailureReason.RATE_LIMITED: (
        "The platform rate limited the request (HTTP 429). Omnicient stops "
        "rather than evading; try again later."
    ),
    FailureReason.TIMEOUT: "The request timed out.",
    FailureReason.NETWORK_ERROR: "The host could not be reached.",
    FailureReason.ROBOTS_DISALLOWED: "robots.txt disallows crawling this path.",
    FailureReason.UNSAFE_URL: "The URL was rejected by the SSRF guard.",
    FailureReason.TOO_LARGE: "The response exceeded the maximum size limit.",
    FailureReason.PARSE_ERROR: "The page could not be parsed.",
    FailureReason.UNSUPPORTED: "No adapter is registered for this platform.",
    FailureReason.BUDGET_EXHAUSTED: "The crawl page budget was exhausted.",
}


class SourceCategory(StrEnum):
    """What kind of site a source is.

    Grouping sources lets the interface and the profile say "four developer
    accounts and a music profile" rather than listing nine platform names, and
    it keeps the adapter registry legible as it grows.
    """

    SOCIAL = "social"
    DEV = "dev"
    GAMING = "gaming"
    MUSIC = "music"
    LEARNING = "learning"
    WEB = "web"
    IDENTITY = "identity"


class SourceError(Exception):
    """A structured, non-fatal source failure."""

    def __init__(
        self,
        reason: FailureReason,
        detail: str | None = None,
        url: str | None = None,
    ) -> None:
        self.reason = reason
        self.detail = detail or REASON_MESSAGES.get(reason, str(reason))
        self.url = url
        super().__init__(f"{reason}: {self.detail}")


class ObservedProfile(BaseModel):
    """Publicly observable information about one entity.

    This is the shared vocabulary between adapters, the crawler and the
    correlation engine.  It is deliberately independent of the ORM so the
    engine can be tested - and later replaced - without a database.
    """

    entity_type: EntityType = EntityType.ACCOUNT
    platform: str
    identifier: str
    name: str | None = None
    url: str | None = None

    display_name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    location: str | None = None
    email: str | None = None
    organization: str | None = None
    external_links: list[str] = Field(default_factory=list)

    # Cross-platform accounts this page explicitly points at.
    references: list[Reference] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    websites: list[str] = Field(default_factory=list)

    source: str | None = None
    resolved: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}

    @property
    def key(self) -> tuple[str, str, str]:
        return (str(self.entity_type), self.platform, self.identifier)

    @property
    def label(self) -> str:
        return f"{self.platform}:{self.identifier}"


class LookupResult(BaseModel):
    """What an adapter returns: entities, or a structured reason it could not.

    A result with neither profiles nor an error means "queried successfully,
    nothing public found".
    """

    entities: list[ObservedProfile] = Field(default_factory=list)
    reason: FailureReason | None = None
    detail: str | None = None
    url: str | None = None
    pages_fetched: int = 0

    @property
    def ok(self) -> bool:
        return self.reason is None

    @property
    def primary(self) -> ObservedProfile | None:
        return self.entities[0] if self.entities else None

    @classmethod
    def failure(
        cls, error: SourceError, pages_fetched: int = 0
    ) -> LookupResult:
        return cls(
            reason=error.reason,
            detail=error.detail,
            url=error.url,
            pages_fetched=pages_fetched,
        )


@dataclass
class FetchResult:
    """Outcome of a single HTTP GET."""

    url: str
    status_code: int
    text: str = ""
    content_type: str = ""
    hops: list[str] = field(default_factory=list)


class SafeFetcher:
    """Polite, size-limited, SSRF-guarded HTTP GET client.

    Every request - and every redirect hop - is validated against the SSRF
    rules in :mod:`app.utils.validation` before a connection is opened.
    Responses are streamed and abandoned once they exceed the configured size
    limit, and a per-host delay is enforced between requests.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        # Applied per request rather than baked into the client, so an injected
        # client (tests, a shared pool) behaves exactly like one we built.
        self.default_headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self._client = client or httpx.AsyncClient(
            timeout=self.settings.request_timeout,
            follow_redirects=False,
        )
        self._owns_client = client is None
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        # One lock per host rather than one for the fetcher. A single lock
        # held across the politeness sleep would serialise every request the
        # crawler makes, including to unrelated hosts - which defeats the
        # point of fetching sources concurrently.
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._registry_lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # -- request pipeline --------------------------------------------------

    async def get(
        self, url: str, headers: dict[str, str] | None = None
    ) -> FetchResult:
        """Fetch a public URL, following validated redirects.

        ``headers`` overrides the client defaults for this request only - a
        JSON source has to ask for JSON, or an API answers 415 rather than
        serving the document.

        Raises :class:`SourceError` for every failure mode so callers handle
        one exception type: SSRF rejection, robots restriction, rate limiting,
        oversized bodies, timeouts and network errors.
        """
        current = url
        hops: list[str] = []
        seen: set[str] = set()
        for _ in range(self.settings.max_redirects + 1):
            validated = self._validate(current)
            if validated.url in seen:
                raise SourceError(
                    FailureReason.NETWORK_ERROR,
                    f"redirect loop at {validated.url}",
                    url,
                )
            seen.add(validated.url)
            await self._check_robots(validated.url)
            await self._respect_delay(validated.host)
            response = await self._request(validated.url, headers)

            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    raise SourceError(
                        FailureReason.NETWORK_ERROR,
                        "redirect response without a Location header",
                        current,
                    )
                hops.append(validated.url)
                # Redirect targets are re-validated on the next iteration,
                # which is what stops a public host redirecting to 127.0.0.1.
                current = urljoin(validated.url, location)
                continue

            try:
                self._raise_for_status(response, validated.url)
                text = await self._read_limited(response)
            finally:
                await response.aclose()

            return FetchResult(
                url=validated.url,
                status_code=response.status_code,
                text=text,
                content_type=response.headers.get("content-type", ""),
                hops=hops,
            )

        raise SourceError(
            FailureReason.NETWORK_ERROR, "too many redirects", url
        )

    def _validate(self, url: str):
        try:
            validated = validate_public_url(
                url, allow_private=self.settings.allow_private_networks
            )
            if not self.settings.allow_private_networks:
                port = 443 if validated.scheme == "https" else 80
                resolve_public_host(validated.host, port)
        except UnsafeURLError as exc:
            raise SourceError(FailureReason.UNSAFE_URL, str(exc), url) from exc
        return validated

    async def _request(
        self, url: str, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        try:
            merged = {**self.default_headers, **(headers or {})}
            request = self._client.build_request("GET", url, headers=merged)
            return await self._client.send(request, stream=True)
        except httpx.TimeoutException as exc:
            raise SourceError(
                FailureReason.TIMEOUT,
                f"timed out after {self.settings.request_timeout:.0f}s",
                url,
            ) from exc
        except httpx.HTTPError as exc:
            raise SourceError(FailureReason.NETWORK_ERROR, str(exc), url) from exc

    @staticmethod
    def _raise_for_status(response: httpx.Response, url: str) -> None:
        status = response.status_code
        if status == 404 or status == 410:
            raise SourceError(FailureReason.NOT_FOUND, f"HTTP {status}", url)
        if status == 429:
            raise SourceError(FailureReason.RATE_LIMITED, "HTTP 429", url)
        if status in (401, 403):
            raise SourceError(FailureReason.BLOCKED, f"HTTP {status}", url)
        if status >= 400:
            raise SourceError(
                FailureReason.NETWORK_ERROR, f"HTTP {status}", url
            )

    async def _read_limited(self, response: httpx.Response) -> str:
        """Read at most ``max_response_bytes`` of the body."""
        limit = self.settings.max_response_bytes
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            raise SourceError(
                FailureReason.TOO_LARGE,
                f"content-length {declared} exceeds {limit} bytes",
                str(response.url),
            )
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > limit:
                raise SourceError(
                    FailureReason.TOO_LARGE,
                    f"response exceeded {limit} bytes",
                    str(response.url),
                )
            chunks.append(chunk)
        return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")

    async def _lock_for(self, host: str) -> asyncio.Lock:
        """The politeness lock for one host, created on first use."""
        async with self._registry_lock:
            lock = self._host_locks.get(host)
            if lock is None:
                lock = asyncio.Lock()
                self._host_locks[host] = lock
            return lock

    async def _respect_delay(self, host: str) -> None:
        """Wait out the configured inter-request delay for a host.

        Serialises requests to the *same* host while leaving different hosts
        free to proceed in parallel, so politeness costs concurrency nothing
        across a fan-out to twenty different services.
        """
        delay = self.settings.request_delay
        if delay <= 0:
            return
        lock = await self._lock_for(host)
        async with lock:
            last = self._last_request.get(host, 0.0)
            elapsed = time.monotonic() - last
            if last and elapsed < delay:
                await asyncio.sleep(delay - elapsed)
            self._last_request[host] = time.monotonic()

    async def _check_robots(self, url: str) -> None:
        """Honour robots.txt for the target host where it is available.

        A missing, unreachable or unparseable robots.txt is treated as
        permissive - the same interpretation browsers and the robots RFC use -
        but an explicit ``Disallow`` stops the fetch.
        """
        if not self.settings.respect_robots:
            return
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            self._robots[origin] = await self._load_robots(origin)
        parser = self._robots[origin]
        if parser is None:
            return
        if not parser.can_fetch(self.settings.user_agent, url):
            raise SourceError(
                FailureReason.ROBOTS_DISALLOWED,
                f"robots.txt at {origin} disallows this path",
                url,
            )

    async def _load_robots(self, origin: str) -> RobotFileParser | None:
        parser = RobotFileParser()
        try:
            request = self._client.build_request("GET", f"{origin}/robots.txt")
            response = await self._client.send(request, follow_redirects=True)
            if response.status_code >= 400:
                return None
            parser.parse(response.text.splitlines())
            return parser
        except (httpx.HTTPError, UnicodeDecodeError, ValueError):
            logger.debug("robots_unavailable origin=%s", origin)
            return None


class SourceAdapter(ABC):
    """Interface every discovery source implements.

    Adding a platform means writing one adapter and registering it - the
    crawler, correlation engine and API are untouched.
    """

    platform: str = ""
    #: Human-readable name used in evidence descriptions and events.
    name: str = ""
    #: Which kind of site this is, for grouping in the UI and the profile.
    category: SourceCategory = SourceCategory.SOCIAL

    @abstractmethod
    async def lookup(self, identifier: str) -> LookupResult:
        """Look up a public identifier and return observed entities."""

    def profile_url(self, identifier: str) -> str | None:
        """Canonical public URL for an identifier on this platform."""
        return None


# ---------------------------------------------------------------------------
# HTML helpers shared by the adapters
# ---------------------------------------------------------------------------

# Phrases meaning "this content is not publicly available".
LOGIN_WALL_MARKERS = (
    "log in to continue",
    "log into facebook",
    "you must log in",
    "content isn't available",
    "this account is private",
    "sign up to see",
    "please log in",
)

# First path segments that identify an interstitial rather than a profile.
NON_PROFILE_PATHS = frozenset(
    {
        "login", "log_in", "signup", "r.php", "checkpoint", "accounts", "help",
        "explore", "privacy", "policies", "terms",
    }
)


def parse_meta(html: str) -> dict[str, str]:
    """Extract Open Graph, ``<meta>`` and canonical fields from a page.

    Public Meta profiles expose their card through Open Graph tags, which keeps
    parsing resilient to markup churn elsewhere on the page.
    """
    soup = BeautifulSoup(html, "lxml")
    data: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        key = tag.get("property") or tag.get("name")
        content = tag.get("content")
        if key and content:
            data.setdefault(str(key).strip().lower(), str(content).strip())
    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        data.setdefault("canonical", str(canonical["href"]).strip())
    if soup.title and soup.title.string:
        data.setdefault("title", soup.title.string.strip())
    return data


def looks_like_login_wall(html: str) -> bool:
    """Heuristic check for a private profile or a login interstitial."""
    lowered = html[:20000].lower()
    return any(marker in lowered for marker in LOGIN_WALL_MARKERS)


def page_is_profile_for(
    meta: dict[str, str], identifier: str, platform: str | None = None
) -> bool:
    """Check that a fetched page really is the requested profile.

    Meta platforms answer an unknown or gated handle with HTTP 200 and a
    generic page whose canonical URL points at that interstitial, so comparing
    the advertised canonical against the requested handle filters them out
    without guessing from page text.

    ``platform`` lets the check skip a known profile prefix: last.fm publishes
    ``/user/rj``, so comparing the first path segment alone would reject every
    profile on the site.
    """
    from ..utils.url_parser import PROFILE_PATH_PREFIXES

    url = meta.get("og:url") or meta.get("canonical")
    if not url:
        return True  # Nothing to verify against; other checks still apply.
    segments = [s for s in urlparse(url).path.split("/") if s]
    if not segments:
        return False

    prefixes = PROFILE_PATH_PREFIXES.get(platform or "", ())
    if len(segments) > 1 and segments[0].lower() in prefixes:
        segments = segments[1:]

    first = segments[0].lstrip("@").lower()
    if first in NON_PROFILE_PATHS:
        return False
    if first == identifier.lower():
        return True
    # Platforms rewrite a handle to their own canonical spelling: Facebook
    # answers /cocacola with canonical /Coca-Cola/. Comparing the letters and
    # digits alone accepts that without accepting a different account.
    return _squash(first) == _squash(identifier) and bool(_squash(identifier))


def _squash(value: str) -> str:
    """Letters and digits only, lowercased - for comparing handle spellings."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def absolute_links(html: str, base_url: str, limit: int = 200) -> list[str]:
    """Every outbound http(s) link on a page, absolutized and normalized."""
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        normalized = normalize_url(urljoin(base_url, href))
        if normalized and normalized not in links:
            links.append(normalized)
        if len(links) >= limit:
            break
    return links


def visible_text(html: str, limit: int = 20000) -> str:
    """Readable text of a page, with scripts and styles removed."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())[:limit]


def enrich_profile(profile: ObservedProfile) -> ObservedProfile:
    """Fill in the derived fields the crawler pivots on.

    References, websites, emails and organizations are extracted from whatever
    public text the adapter captured, so every adapter gets identical
    extraction behaviour for free.
    """
    from ..utils.url_parser import (
        extract_emails,
        extract_organizations,
        extract_references,
        extract_websites,
    )

    text_sources = " \n".join(
        part for part in (profile.bio, profile.display_name, profile.location) if part
    )
    links = list(profile.external_links)

    profile.references = [
        reference
        for reference in extract_references(profile.bio, links)
        # A profile referencing itself is not a discovery.
        if reference.key != (profile.platform, profile.identifier)
    ]
    profile.websites = extract_websites(profile.bio, links)
    profile.emails = extract_emails(text_sources)
    # Merge rather than overwrite. An adapter that read organizations from
    # structured page data - Facebook's Intro block, a developer profile's
    # company field - knows more than a guess at capitalised words after
    # "at", and replacing its findings with that guess threw them away.
    profile.organizations = list(profile.organizations) + [
        name
        for name in extract_organizations(text_sources)
        if name not in profile.organizations
    ]
    if profile.emails and not profile.email:
        profile.email = profile.emails[0]
    if profile.organizations and not profile.organization:
        profile.organization = profile.organizations[0]
    return profile


class OpenGraphProfileAdapter(SourceAdapter):
    """Adapter for platforms that publish public profiles as Open Graph cards.

    Instagram, Threads and Facebook all serve the same shape of metadata for
    public profiles, so the fetch/verify/parse flow lives here once.  Platform
    specifics (URL template, title format, extra fields) are overridden by the
    concrete adapters.
    """

    url_template: str = ""
    #: Titles that are the platform talking about itself, not a person.
    generic_titles: frozenset[str] = frozenset(
        {"facebook", "threads", "instagram", "log in", "threads • log in"}
    )
    #: When true, a login wall is reported as PRIVATE rather than NOT_FOUND.
    report_login_wall: bool = True

    def __init__(self, fetcher: SafeFetcher | None = None) -> None:
        self.fetcher = fetcher or SafeFetcher()

    def profile_url(self, identifier: str) -> str:
        return self.url_template.format(identifier=identifier)

    async def lookup(self, identifier: str) -> LookupResult:
        """Fetch and parse a public profile page."""
        from ..utils.normalization import NormalizationError, normalize_username

        try:
            identifier = normalize_username(identifier)
        except NormalizationError as exc:
            return LookupResult.failure(
                SourceError(FailureReason.NOT_FOUND, str(exc))
            )

        url = self.profile_url(identifier)
        try:
            fetched = await self.fetcher.get(url)
        except SourceError as exc:
            logger.info(
                "source_unavailable platform=%s identifier=%s reason=%s",
                self.platform,
                identifier,
                exc.reason,
            )
            return LookupResult.failure(exc)

        if looks_like_login_wall(fetched.text):
            return LookupResult.failure(
                SourceError(
                    FailureReason.PRIVATE,
                    f"{self.name} served a login wall or private profile for "
                    f"'{identifier}'",
                    url,
                ),
                pages_fetched=1,
            )

        try:
            profile = self.parse_profile(identifier, fetched.text, fetched.url)
        except Exception as exc:  # noqa: BLE001 - malformed HTML must not abort
            logger.warning(
                "parse_failed platform=%s identifier=%s error=%s",
                self.platform,
                identifier,
                exc,
            )
            return LookupResult.failure(
                SourceError(FailureReason.PARSE_ERROR, str(exc), url), pages_fetched=1
            )

        if profile is None:
            return LookupResult(pages_fetched=1, url=url)
        return LookupResult(entities=[profile], pages_fetched=1, url=url)

    def parse_profile(
        self, identifier: str, html: str, url: str
    ) -> ObservedProfile | None:
        """Build an enriched :class:`ObservedProfile` from public profile HTML."""
        meta = parse_meta(html)
        title = meta.get("og:title")
        if not title:
            return None
        if not page_is_profile_for(meta, identifier, self.platform):
            return None

        display_name = self.extract_display_name(title)
        bio = self.extract_bio(meta, html)
        avatar = meta.get("og:image")
        links = self.extract_links(meta, html, bio)

        if not any([display_name, bio, avatar, links]):
            return None

        metadata: dict[str, Any] = {}
        if meta.get("og:type"):
            metadata["og_type"] = meta["og:type"]
        metadata.update(self.extract_metadata(meta, html))

        return enrich_profile(
            ObservedProfile(
                entity_type=EntityType.ACCOUNT,
                platform=self.platform,
                identifier=identifier,
                name=f"@{identifier}",
                url=normalize_url(url) or url,
                display_name=display_name,
                bio=bio,
                avatar_url=avatar,
                location=self.extract_location(meta, html),
                organization=self.extract_organization(meta, html),
                organizations=self.extract_organizations(meta, html),
                external_links=links,
                source=self.platform,
                metadata=metadata,
            )
        )

    # -- overridable extraction hooks -------------------------------------

    def extract_display_name(self, title: str) -> str | None:
        """Read the person's display name out of the page title."""
        import re

        match = re.match(r"^(?P<name>.*?)\s*(?:\(@[^)]+\)|\||•|-\s)", title)
        name = (match.group("name") if match else title).strip() or None
        if name and name.lower() in self.generic_titles:
            return None
        return name

    def extract_bio(self, meta: dict[str, str], html: str) -> str | None:
        """Read the public biography text."""
        return meta.get("og:description") or meta.get("description") or None

    def extract_links(
        self, meta: dict[str, str], html: str, bio: str | None
    ) -> list[str]:
        """Public external links published on the profile."""
        from ..utils.url_parser import extract_urls

        return extract_urls(bio)

    def extract_location(self, meta: dict[str, str], html: str) -> str | None:
        """The place the profile publishes for itself, where it publishes one.

        Worth its own hook because the correlation engine treats conflicting
        locations as evidence *against* an association, so a source that can
        read one is contributing to both sides of the score.
        """
        return None

    def extract_organization(self, meta: dict[str, str], html: str) -> str | None:
        """The employer or institution the profile names."""
        return None

    def extract_organizations(self, meta: dict[str, str], html: str) -> list[str]:
        """Every organization the profile names - employers past and present,
        and schools.

        Separate from :meth:`extract_organization` because they answer
        different questions. That one is "where do they work", shown to an
        analyst; this one is "what institutions does this profile mention",
        which is what the correlation engine matches across platforms. Two
        profiles naming the same former employer is evidence worth scoring
        even though neither works there now.
        """
        return []

    def extract_metadata(self, meta: dict[str, str], html: str) -> dict[str, Any]:
        """Extra observed fields to record, e.g. audience counts.

        Given the already-parsed meta tags so a subclass never re-parses the
        page.  Nothing here is compared by the correlation engine; it is
        context for the analyst.
        """
        return {}


class JsonProfileAdapter(SourceAdapter):
    """Adapter for platforms that publish public profiles as JSON.

    GitHub and Reddit both serve a documented, unauthenticated endpoint
    describing a public account.  Using it is the *polite* option: it is the
    interface those platforms publish for this purpose, it returns far less
    data than scraping the HTML page, and it is stable.  No token, cookie or
    private endpoint is involved - an anonymous request is rate limited, and a
    rate limit is reported (``RATE_LIMITED``) rather than worked around.
    """

    #: Public JSON endpoint, formatted with ``identifier``.
    api_template: str = ""
    #: Human-facing profile URL, formatted with ``identifier``.
    url_template: str = ""
    #: Sent as ``Accept``.  Without it the shared client asks for HTML and a
    #: JSON API answers 415.
    accept: str = "application/json"

    def __init__(self, fetcher: SafeFetcher | None = None) -> None:
        self.fetcher = fetcher or SafeFetcher()

    def profile_url(self, identifier: str) -> str:
        return self.url_template.format(identifier=identifier)

    def api_url(self, identifier: str) -> str:
        return self.api_template.format(identifier=identifier)

    def normalize_identifier(self, identifier: str) -> str:
        """Canonicalise the identifier before it is looked up.

        Overridable because not every platform is keyed by a handle: Stack
        Exchange has only display names, which contain spaces that the handle
        normalizer rejects outright.
        """
        from ..utils.normalization import normalize_username

        return normalize_username(identifier)

    async def lookup(self, identifier: str) -> LookupResult:
        """Fetch and parse a public profile document."""
        from ..utils.normalization import NormalizationError

        try:
            identifier = self.normalize_identifier(identifier)
        except NormalizationError as exc:
            return LookupResult.failure(SourceError(FailureReason.NOT_FOUND, str(exc)))

        api_url = self.api_url(identifier)
        try:
            fetched = await self.fetcher.get(api_url, headers={"Accept": self.accept})
        except SourceError as exc:
            logger.info(
                "source_unavailable platform=%s identifier=%s reason=%s",
                self.platform,
                identifier,
                exc.reason,
            )
            return LookupResult.failure(exc)

        try:
            payload = json.loads(fetched.text)
        except ValueError:
            # A login wall or an error page served where JSON was expected.
            return LookupResult.failure(
                SourceError(
                    FailureReason.PARSE_ERROR,
                    f"{self.name} did not return JSON for '{identifier}'",
                    api_url,
                ),
                pages_fetched=1,
            )

        try:
            profile = self.parse_json(identifier, payload, self.profile_url(identifier))
        except Exception as exc:  # noqa: BLE001 - malformed payloads must not abort
            logger.warning(
                "parse_failed platform=%s identifier=%s error=%s",
                self.platform,
                identifier,
                exc,
            )
            return LookupResult.failure(
                SourceError(FailureReason.PARSE_ERROR, str(exc), api_url),
                pages_fetched=1,
            )

        if profile is None:
            return LookupResult(pages_fetched=1, url=api_url)
        return LookupResult(entities=[profile], pages_fetched=1, url=api_url)

    @abstractmethod
    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        """Build an :class:`ObservedProfile` from the public JSON document."""


class XmlProfileAdapter(SourceAdapter):
    """Adapter for platforms that publish a public profile as XML.

    Steam is the notable one: appending ``?xml=1`` to a community profile
    returns a small, stable document instead of a 200KB page built by
    JavaScript. Reading that is both lighter and more reliable than scraping
    the rendered profile.
    """

    #: Public XML endpoint, formatted with ``identifier``.
    api_template: str = ""
    #: Human-facing profile URL, formatted with ``identifier``.
    url_template: str = ""
    accept: str = "text/xml,application/xml"

    def __init__(self, fetcher: SafeFetcher | None = None) -> None:
        self.fetcher = fetcher or SafeFetcher()

    def profile_url(self, identifier: str) -> str:
        return self.url_template.format(identifier=identifier)

    def api_url(self, identifier: str) -> str:
        return self.api_template.format(identifier=identifier)

    async def lookup(self, identifier: str) -> LookupResult:
        """Fetch and parse a public XML profile document."""
        from ..utils.normalization import NormalizationError, normalize_username

        try:
            identifier = normalize_username(identifier)
        except NormalizationError as exc:
            return LookupResult.failure(SourceError(FailureReason.NOT_FOUND, str(exc)))

        api_url = self.api_url(identifier)
        try:
            fetched = await self.fetcher.get(api_url, headers={"Accept": self.accept})
        except SourceError as exc:
            logger.info(
                "source_unavailable platform=%s identifier=%s reason=%s",
                self.platform,
                identifier,
                exc.reason,
            )
            return LookupResult.failure(exc)

        try:
            soup = BeautifulSoup(fetched.text, "lxml-xml")
            profile = self.parse_xml(identifier, soup, self.profile_url(identifier))
        except Exception as exc:  # noqa: BLE001 - malformed XML must not abort
            logger.warning(
                "parse_failed platform=%s identifier=%s error=%s",
                self.platform,
                identifier,
                exc,
            )
            return LookupResult.failure(
                SourceError(FailureReason.PARSE_ERROR, str(exc), api_url),
                pages_fetched=1,
            )

        if profile is None:
            return LookupResult(pages_fetched=1, url=api_url)
        return LookupResult(entities=[profile], pages_fetched=1, url=api_url)

    @abstractmethod
    def parse_xml(
        self, identifier: str, soup: BeautifulSoup, url: str
    ) -> ObservedProfile | None:
        """Build an :class:`ObservedProfile` from the parsed XML document."""


def xml_text(soup: BeautifulSoup, tag: str) -> str | None:
    """Trimmed text of the first matching element, or ``None``."""
    element = soup.find(tag)
    if element is None:
        return None
    value = element.get_text(strip=True)
    return value or None
