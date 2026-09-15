"""Link-in-bio pages: Linktree and the sites like it.

These are the most productive source an identity investigation can read.  A
link-in-bio page exists for exactly one purpose - to list, in one place, every
account its owner wants people to find - so a single fetch yields a set of
cross-platform handles the person published themselves.  That is an explicit,
self-declared connection, worth far more than the engine noticing two handles
look alike, and it is precisely what a crawl starting from one handle cannot
otherwise discover.

Each page also carries the things an analyst wants to see next to an account:
a display name, a short bio and an avatar.

What these adapters do not do is follow the aggregator's click-tracking
redirect to find out where a link really goes.  The destination is published
in the page; chasing the redirect would mean registering a click on somebody's
analytics, which is interfering with the thing being observed.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from ..models.enums import EntityType
from ..utils.normalization import normalize_url
from .base import (
    ObservedProfile,
    OpenGraphProfileAdapter,
    SourceCategory,
    enrich_profile,
    parse_meta,
)

#: Hosts that appear on these pages without being anybody's account: the
#: aggregator's own assets, analytics, consent tooling, fonts and CDNs.
INFRASTRUCTURE = (
    "cloudflare",
    "googletagmanager",
    "google-analytics",
    "googleapis",
    "gstatic",
    "doubleclick",
    "datagrail",
    "segment.",
    "sentry",
    "amazonaws",
    "cloudfront",
    "jquery",
    "jsdelivr",
    "unpkg",
    "w3.org",
    "schema.org",
    "bootstrapcdn",
    "fontawesome",
)

#: Paths that make a link a share button rather than an account. Every one of
#: these pages carries "share this on Facebook" and "post this to X", and
#: read naively they turn into an account called "sharer" on every profile
#: the crawl ever sees.
SHARE_PATHS = (
    "/sharer",
    "/intent/",
    "/share?",
    "/share/",
    "/submit?",
    "/dialog/",
)


def _is_account_link(url: str, own_hosts: tuple[str, ...]) -> bool:
    """Whether a link on the page points at somebody rather than at plumbing."""
    try:
        host = (urlparse(url).netloc or "").lower()
    except ValueError:
        return False
    if not host or not url.lower().startswith("http"):
        return False
    if any(own in host for own in own_hosts):
        return False
    if any(marker in host for marker in INFRASTRUCTURE):
        return False
    lowered = url.lower()
    if any(marker in lowered for marker in SHARE_PATHS):
        return False
    # An asset, not a destination.
    return not re.search(r"\.(png|jpe?g|gif|svg|webp|ico|css|js|woff2?)$", url, re.I)


class LinkAggregatorAdapter(OpenGraphProfileAdapter):
    """Shared shape for link-in-bio pages.

    The Open Graph card gives the name, bio and avatar; the body gives the
    links.  Subclasses override :meth:`collect_links` when a site publishes
    them somewhere richer than plain anchors.
    """

    category = SourceCategory.WEB
    #: Hosts belonging to the aggregator itself, which are never accounts.
    own_hosts: tuple[str, ...] = ()

    def collect_links(self, html: str) -> list[str]:
        """Outbound destinations published on the page, in order."""
        found: list[str] = []
        for match in re.finditer(r'href="(https?://[^"]+)"', html):
            url = match.group(1)
            if _is_account_link(url, self.own_hosts) and url not in found:
                found.append(url)
        return found

    def extract_links(
        self, meta: dict[str, str], html: str, bio: str | None
    ) -> list[str]:
        """The page's whole point: every account it points at.

        Merged with anything in the bio text, which is where a handle that
        has no button of its own tends to be written.
        """
        links = list(super().extract_links(meta, html, bio))
        for url in self.collect_links(html):
            if url not in links:
                links.append(url)
        return links


class LinktreeAdapter(LinkAggregatorAdapter):
    """Linktree, read from the JSON the page bootstraps itself from.

    The rendered page is built client-side, so the anchors are not in the
    HTML - but Next.js embeds the whole profile as JSON, which is better than
    scraped anchors anyway: each link arrives with the title its owner gave it
    and the kind of link Linktree believes it to be.
    """

    platform = "linktree"
    name = "Linktree"
    url_template = "https://linktr.ee/{identifier}"
    own_hosts = ("linktr.ee", "linktree")
    generic_titles = frozenset({"linktree", "linktree | blocked account"})
    probe_present = "github"

    #: The page state, including every link and the profile around it.
    NEXT_DATA_RE = re.compile(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
    )

    def _account(self, html: str) -> dict[str, Any]:
        match = self.NEXT_DATA_RE.search(html)
        if not match:
            return {}
        try:
            payload = json.loads(match.group(1))
        except ValueError:
            return {}
        props = payload.get("props", {}).get("pageProps", {})
        account = props.get("account")
        if not isinstance(account, dict):
            return {}
        links = props.get("links") or account.get("links") or []
        return {"account": account, "links": links if isinstance(links, list) else []}

    def parse_profile(
        self, identifier: str, html: str, url: str
    ) -> ObservedProfile | None:
        """Build the profile from the embedded state rather than the card."""
        state = self._account(html)
        account = state.get("account") or {}
        if not account or not account.get("username"):
            return None
        # A page Linktree has taken down publishes nothing and is not evidence
        # that the handle belongs to anybody.
        if account.get("isActive") is False:
            return None

        meta = parse_meta(html)
        links: list[str] = []
        for entry in state.get("links") or []:
            target = entry.get("url") if isinstance(entry, dict) else None
            if (
                isinstance(target, str)
                and _is_account_link(target, self.own_hosts)
                and target not in links
            ):
                links.append(target)
        # Some layouts publish no link list; the anchors are the fallback.
        for target in self.collect_links(html):
            if target not in links:
                links.append(target)

        title = (account.get("pageTitle") or "").lstrip("@").strip()
        return enrich_profile(
            ObservedProfile(
                entity_type=EntityType.ACCOUNT,
                platform=self.platform,
                identifier=str(account["username"]),
                name=f"@{account['username']}",
                url=normalize_url(url) or url,
                display_name=title or None,
                bio=(account.get("description") or "").strip() or None,
                avatar_url=account.get("profilePictureUrl")
                or meta.get("og:image")
                or None,
                external_links=links,
                source=self.platform,
                metadata={
                    "published_links": len(links),
                    **(
                        {"verified": True}
                        if account.get("isProfileVerified")
                        else {}
                    ),
                },
            )
        )


class SoloToAdapter(LinkAggregatorAdapter):
    """solo.to, which publishes its links as ordinary anchors."""

    platform = "solo"
    name = "solo.to"
    url_template = "https://solo.to/{identifier}"
    own_hosts = ("solo.to",)
    generic_titles = frozenset({"solo", "solo.to"})
    probe_present = "nasa"

    def extract_display_name(self, title: str) -> str | None:
        """``NASA · solo.to`` -> ``NASA``."""
        cleaned = re.sub(r"\s*·\s*solo\.to\s*$", "", title, flags=re.I).strip()
        return cleaned or super().extract_display_name(title)


class BioLinkAdapter(LinkAggregatorAdapter):
    """bio.link, same shape as solo.to."""

    platform = "biolink"
    name = "bio.link"
    url_template = "https://bio.link/{identifier}"
    own_hosts = ("bio.link",)
    generic_titles = frozenset({"bio.link", "bio link"})
    probe_present = "nasa"
