"""Instagram source adapter.

Reads the Open Graph metadata Instagram serves for *public* profiles.  Nothing
here logs in, replays a session, calls a private endpoint or works around a
block: if the page is not publicly readable the adapter returns a structured
error (``PRIVATE``, ``BLOCKED``, ``RATE_LIMITED`` …) and the investigation
continues with the evidence it already has.
"""

from __future__ import annotations

import json
import re

from .base import ObservedProfile, OpenGraphProfileAdapter

# "Alice Doe (@alice_98) • Instagram photos and videos"
TITLE_RE = re.compile(r"^(?P<name>.*?)\s*\(@(?P<handle>[^)]+)\)")
# '... 45 Posts - Alice Doe (@alice_98) on Instagram: "bio text"'
DESCRIPTION_BIO_RE = re.compile(
    r'on Instagram:\s*[\"“](?P<bio>.*?)[\"”]\s*$', re.DOTALL
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
        description = meta.get("og:description") or meta.get("description") or ""
        match = DESCRIPTION_BIO_RE.search(description)
        if match:
            return match.group("bio").strip() or None
        return description.strip() or None

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
