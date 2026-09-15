"""Facebook source adapter.

Only public profile and page URLs are read.  Numeric ``profile.php?id=`` links
and any page that answers with a login wall are reported as unavailable rather
than guessed at, and no credential, cookie or private endpoint is ever used.

Besides the Open Graph card, this reads the Intro block - employer, education,
hometown, relationship, joined date - out of the JSON Facebook embeds in the
page it serves to anonymous visitors.  See :mod:`app.sources.facebook_intro`
for what that does and does not reach: Pages and public-figure profiles carry
it, ordinary personal profiles do not, because Facebook only loads theirs
after a login this project will not perform.

Facebook publishes ``Disallow: /``, so reaching this adapter at all requires
the operator to set ``OMNICIENT_RESPECT_ROBOTS=false``.  That is their decision
and their responsibility.
"""

from __future__ import annotations

import re
from typing import Any

from .base import OpenGraphProfileAdapter
from .facebook_intro import parse_intro

# "Coca-Cola. 106,984,120 likes · 865 talking about this. <description>"
STATS_RE = re.compile(
    r"(?P<likes>[\d.,KMB]+)\s+likes"
    r"(?:\s*·\s*(?P<talking>[\d.,KMB]+)\s+talking about this)?"
    r"(?:\s*·\s*(?P<visits>[\d.,KMB]+)\s+were here)?\s*\.?\s*",
    re.IGNORECASE,
)


class FacebookAdapter(OpenGraphProfileAdapter):
    """Looks up publicly available Facebook profile or page information."""

    platform = "facebook"
    name = "Facebook"
    url_template = "https://www.facebook.com/{identifier}"

    def extract_bio(self, meta: dict[str, str], html: str) -> str | None:
        """Return the page description without its engagement counts.

        Facebook prefixes descriptions with "<name>. N likes · N talking about
        this." Left in place, every busy page looks like it shares a biography
        with every other busy page.
        """
        value = meta.get("og:description") or meta.get("description")
        if not value:
            return None

        remainder = STATS_RE.sub("", value, count=1).strip()
        # The page name is repeated ahead of the counts; drop it when the
        # title already carries it.
        title = (meta.get("og:title") or "").strip()
        if title and remainder.startswith(f"{title}."):
            remainder = remainder[len(title) + 1 :].strip()
        remainder = remainder.lstrip(".· ").strip()
        return remainder or None

    def extract_location(self, meta: dict[str, str], html: str) -> str | None:
        """Where the Intro says they live."""
        return parse_intro(html).location

    def extract_organization(self, meta: dict[str, str], html: str) -> str | None:
        """The employer the Intro names, preferring the current one."""
        intro = parse_intro(html)
        return intro.current_organization or next(iter(intro.organizations), None)

    def extract_links(
        self, meta: dict[str, str], html: str, bio: str | None
    ) -> list[str]:
        """Links from the description, plus any the Intro publishes.

        An Intro row naming another platform is the strongest thing a profile
        can offer an investigation: the account itself says where else it is,
        which is an explicit connection rather than an inference from a
        matching handle.
        """
        links = list(super().extract_links(meta, html, bio))
        for link in parse_intro(html).external_links:
            if link not in links:
                links.append(link)
        return links

    def extract_metadata(self, meta: dict[str, str], html: str) -> dict[str, Any]:
        """Engagement counts and the Intro block, as published on the page."""
        data: dict[str, Any] = {}
        match = STATS_RE.search(
            meta.get("og:description") or meta.get("description") or ""
        )
        if match:
            data.update(
                {
                    key: value
                    for key, value in (
                        ("likes", match.group("likes")),
                        ("talking_about", match.group("talking")),
                        ("were_here", match.group("visits")),
                    )
                    if value
                }
            )
        data.update(parse_intro(html).as_metadata())
        return data
