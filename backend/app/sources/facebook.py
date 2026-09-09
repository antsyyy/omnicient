"""Facebook source adapter.

Only public profile and page URLs are read.  Numeric ``profile.php?id=`` links
and any page that answers with a login wall are reported as unavailable rather
than guessed at, and no credential, cookie or private endpoint is ever used.

Facebook publishes ``Disallow: /``, so reaching this adapter at all requires
the operator to set ``OMNICIENT_RESPECT_ROBOTS=false``.  That is their decision
and their responsibility.
"""

from __future__ import annotations

import re
from typing import Any

from .base import OpenGraphProfileAdapter

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

    def extract_metadata(self, meta: dict[str, str], html: str) -> dict[str, Any]:
        """Engagement counts, as published on the page."""
        match = STATS_RE.search(
            meta.get("og:description") or meta.get("description") or ""
        )
        if not match:
            return {}
        return {
            key: value
            for key, value in (
                ("likes", match.group("likes")),
                ("talking_about", match.group("talking")),
                ("were_here", match.group("visits")),
            )
            if value
        }
