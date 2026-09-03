"""Website source adapter.

Personal sites are the highest-value pivot in a public-source investigation:
they are usually the one place a person deliberately lists all of their
accounts.  This adapter fetches a single publicly accessible page and extracts
the profile links, emails, usernames and organization references it advertises.

Discovery is allowed to outrun adapter coverage: a link to
``github.com/alice-security`` becomes a candidate entity even though no GitHub
adapter exists yet (section 14).
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from ..models.enums import EntityType
from ..utils.logging import get_logger
from ..utils.normalization import NormalizationError, normalize_domain, normalize_url
from ..utils.url_parser import (
    Reference,
    detect_platform,
    extract_emails,
    extract_organizations,
    website_identity,
)
from .base import (
    FailureReason,
    LookupResult,
    ObservedProfile,
    SafeFetcher,
    SourceAdapter,
    SourceError,
    absolute_links,
    enrich_profile,
    parse_meta,
    visible_text,
)

logger = get_logger(__name__)

# Links carrying this rel are an explicit identity claim (IndieAuth "rel=me").
IDENTITY_RELS = frozenset({"me", "author", "publisher"})


class WebsiteAdapter(SourceAdapter):
    """Fetches a public web page and extracts the identities it references."""

    platform = "website"
    name = "Website"

    def __init__(self, fetcher: SafeFetcher | None = None) -> None:
        self.fetcher = fetcher or SafeFetcher()

    def profile_url(self, identifier: str) -> str:
        """Websites are addressed by URL; bare domains get an https scheme."""
        if "://" in identifier:
            return identifier
        return f"https://{identifier}"

    async def lookup(self, identifier: str) -> LookupResult:
        """Fetch one public page and return it as a WEBSITE entity."""
        url = normalize_url(self.profile_url(identifier))
        if not url:
            return LookupResult.failure(
                SourceError(
                    FailureReason.UNSAFE_URL,
                    f"not a usable website address: {identifier!r}",
                )
            )

        try:
            fetched = await self.fetcher.get(url)
        except SourceError as exc:
            logger.info("source_unavailable platform=website url=%s reason=%s", url, exc.reason)
            return LookupResult.failure(exc)

        if "html" not in (fetched.content_type or "text/html").lower():
            return LookupResult.failure(
                SourceError(
                    FailureReason.PARSE_ERROR,
                    f"unsupported content type: {fetched.content_type}",
                    url,
                ),
                pages_fetched=1,
            )

        try:
            profile = self.parse_page(fetched.text, fetched.url)
        except Exception as exc:  # noqa: BLE001 - malformed HTML must not abort
            logger.warning("parse_failed url=%s error=%s", url, exc)
            return LookupResult.failure(
                SourceError(FailureReason.PARSE_ERROR, str(exc), url), pages_fetched=1
            )
        return LookupResult(entities=[profile], pages_fetched=1, url=fetched.url)

    def parse_page(self, html: str, url: str) -> ObservedProfile:
        """Extract identities, contacts and organizations from page HTML."""
        meta = parse_meta(html)
        identity = website_identity(url) or url
        text = visible_text(html)

        links = absolute_links(html, url)
        identity_links = self._identity_links(html, url)

        profile = ObservedProfile(
            entity_type=EntityType.WEBSITE,
            platform="website",
            identifier=identity,
            name=identity,
            url=normalize_url(url) or url,
            display_name=(meta.get("og:site_name") or meta.get("title") or "").strip()
            or None,
            bio=(meta.get("og:description") or meta.get("description") or "").strip()
            or None,
            external_links=links,
            source="website",
            metadata={
                "title": meta.get("title"),
                "identity_links": identity_links,
            },
        )

        # ``enrich_profile`` handles bio-derived signals; a website's evidence
        # comes mostly from its anchors, so extraction runs over page text too.
        enrich_profile(profile)
        bio_references = profile.references
        # rel="me" links are merged first so their stronger provenance wins
        # over the same URL seen as an ordinary anchor.
        profile.references = self._merge_references(
            self._merge_references([], identity_links, identity_links),
            links,
            identity_links,
        )
        profile.references = self._append_unique(profile.references, bio_references)
        profile.emails = self._merge(profile.emails, extract_emails(text))
        profile.organizations = self._merge(
            profile.organizations,
            extract_organizations(text[:4000]) + self._site_name(meta, identity),
        )
        if profile.emails and not profile.email:
            profile.email = profile.emails[0]
        if profile.organizations and not profile.organization:
            profile.organization = profile.organizations[0]
        # Other websites this page links to are pivots. A site's own pages are
        # not: crawling every internal link turns one site into dozens of
        # meaningless entities without adding a single new identity.
        own_host = normalize_domain(url)
        profile.websites = [
            link
            for link in links
            if detect_platform(link) is None and normalize_domain(link) != own_host
        ][:20]

        logger.info(
            "website_parsed url=%s references=%d emails=%d",
            url,
            len(profile.references),
            len(profile.emails),
        )
        return profile

    # -- extraction helpers ------------------------------------------------

    @staticmethod
    def _identity_links(html: str, base_url: str) -> list[str]:
        """``rel="me"`` links: an explicit, machine-readable identity claim."""
        from urllib.parse import urljoin

        soup = BeautifulSoup(html, "lxml")
        found: list[str] = []
        for anchor in soup.find_all("a", href=True):
            rels = {str(rel).lower() for rel in (anchor.get("rel") or [])}
            if not rels & IDENTITY_RELS:
                continue
            normalized = normalize_url(urljoin(base_url, str(anchor["href"])))
            if normalized and normalized not in found:
                found.append(normalized)
        return found

    @staticmethod
    def _merge_references(
        existing: list[Reference], links: list[str], identity_links: list[str]
    ) -> list[Reference]:
        """Add every social profile the page links to, marking rel=me links."""
        from ..utils.url_parser import parse_profile_url

        merged = list(existing)
        seen = {reference.key for reference in merged}
        for link in links:
            try:
                parsed = parse_profile_url(link)
            except NormalizationError:  # pragma: no cover - parser is defensive
                continue
            if not parsed:
                continue
            platform, handle = parsed
            if (platform, handle) in seen:
                continue
            seen.add((platform, handle))
            merged.append(
                Reference(
                    platform=platform,
                    identifier=handle,
                    url=link,
                    context=(
                        f'rel="me" link on the page: {link}'
                        if link in identity_links
                        else f"link published on the page: {link}"
                    ),
                    explicit=True,
                )
            )
        return merged

    @staticmethod
    def _append_unique(
        references: list[Reference], extra: list[Reference]
    ) -> list[Reference]:
        """Append references whose ``(platform, identifier)`` is not present."""
        merged = list(references)
        seen = {reference.key for reference in merged}
        for reference in extra:
            if reference.key not in seen:
                seen.add(reference.key)
                merged.append(reference)
        return merged

    @staticmethod
    def _merge(primary: list[str], extra: list[str]) -> list[str]:
        merged = list(primary)
        for item in extra:
            if item not in merged:
                merged.append(item)
        return merged

    @staticmethod
    def _site_name(meta: dict[str, str], identity: str) -> list[str]:
        """``og:site_name``, unless it is just the domain restated."""
        name = (meta.get("og:site_name") or "").strip()
        if not name or len(name) >= 60:
            return []
        if normalize_domain(name) == normalize_domain(identity):
            return []
        return [name]
