"""Instagram source adapter.

Reads the Open Graph metadata Instagram serves for *public* profiles.  Nothing
here logs in, replays a session, calls a private endpoint or works around a
block: if the page is not publicly readable the adapter returns a structured
error (``PRIVATE``, ``BLOCKED``, ``RATE_LIMITED`` …) and the investigation
continues with the evidence it already has.

Instagram publishes ``Disallow: /``, so reaching this adapter at all requires
the operator to set ``OMNICIENT_RESPECT_ROBOTS=false``.  That is their decision
and their responsibility; the adapter itself neither knows nor changes how the
fetch was authorised.
"""

from __future__ import annotations

import json
import re

from .base import ObservedProfile, OpenGraphProfileAdapter

# "Alice Doe (@alice_98) • Instagram photos and videos"
TITLE_RE = re.compile(r"^(?P<name>.*?)\s*\(@(?P<handle>[^)]+)\)")

# The real biography is the quoted tail of the ``description`` meta tag:
# '... - Alice Doe (@alice_98) on Instagram: "bio text"'
DESCRIPTION_BIO_RE = re.compile(
    r'on Instagram:\s*[\"“](?P<bio>.*?)[\"”]\s*$', re.DOTALL
)

# "104M Followers, 95 Following, 4,914 Posts - ..." — the audience preamble
# Instagram prefixes to every description.
STATS_RE = re.compile(
    r"^\s*(?P<followers>[\d.,KMB]+)\s+Followers,\s*"
    r"(?P<following>[\d.,KMB]+)\s+Following,\s*"
    r"(?P<posts>[\d.,KMB]+)\s+Posts\s*-\s*",
    re.IGNORECASE,
)

# What is left when a profile has no biography at all.
BOILERPLATE = re.compile(
    r"^See Instagram photos and videos from .*$", re.IGNORECASE | re.DOTALL
)

# The public profile payload embeds the link-in-bio target.
EXTERNAL_URL_RE = re.compile(r'"external_url"\s*:\s*"(?P<url>https?:[^"]+)"')


class InstagramAdapter(OpenGraphProfileAdapter):
    """Looks up publicly available Instagram profile information."""

    platform = "instagram"
    name = "Instagram"
    url_template = "https://www.instagram.com/{identifier}/"

    def extract_display_name(self, title: str) -> str | None:
        match = TITLE_RE.match(title)
        if match:
            return match.group("name").strip() or None
        return super().extract_display_name(title)

    def extract_bio(self, meta: dict[str, str], html: str) -> str | None:
        """Return the biography, never the follower counts.

        Instagram prefixes every description with "N Followers, N Following,
        N Posts - ". Leaving that in place would make two unrelated accounts
        look like they share a biography, so the counts are stripped here and
        recorded as metadata instead.
        """
        # ``description`` carries the quoted bio; ``og:description`` usually
        # does not, so both are tried rather than just the first present.
        for key in ("description", "og:description"):
            value = meta.get(key)
            if not value:
                continue
            match = DESCRIPTION_BIO_RE.search(value)
            if match:
                bio = match.group("bio").strip()
                if bio:
                    return bio

        for key in ("og:description", "description"):
            value = meta.get(key)
            if not value:
                continue
            remainder = STATS_RE.sub("", value).strip()
            if remainder and not BOILERPLATE.match(remainder):
                return remainder
        return None

    def extract_metadata(self, meta: dict[str, str], html: str) -> dict[str, str]:
        """Follower/following/post counts, as published on the profile."""
        for key in ("og:description", "description"):
            match = STATS_RE.match(meta.get(key) or "")
            if match:
                return {
                    "followers": match.group("followers"),
                    "following": match.group("following"),
                    "posts": match.group("posts"),
                }
        return {}

    def extract_links(
        self, meta: dict[str, str], html: str, bio: str | None
    ) -> list[str]:
        from ..utils.normalization import normalize_url
        from ..utils.url_parser import extract_urls

        links = extract_urls(bio)
        for raw in EXTERNAL_URL_RE.findall(html):
            # The payload is JSON-escaped inside the HTML.
            decoded = json.loads(f'"{raw}"') if "\\" in raw else raw
            normalized = normalize_url(decoded)
            if normalized and normalized not in links:
                links.append(normalized)
        return links

    def parse_profile(
        self, identifier: str, html: str, url: str
    ) -> ObservedProfile | None:
        profile = super().parse_profile(identifier, html, url)
        if profile is not None:
            profile.metadata.setdefault("verified_via", "open_graph")
        return profile
