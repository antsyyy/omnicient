"""Threads source adapter.

Threads profiles are discovered either directly (the analyst seeded one) or,
far more often, because an Instagram bio or a personal website explicitly
pointed at ``threads.net/@handle``.  Ownership is never inferred from name
similarity alone - that only ever produces a weak candidate for the
correlation engine to judge.

Threads publishes ``Disallow: /``, so reaching this adapter at all requires the
operator to set ``OMNICIENT_RESPECT_ROBOTS=false``.  That is their decision and
their responsibility.
"""

from __future__ import annotations

import re
from typing import Any

from .base import OpenGraphProfileAdapter

# "5.7M Followers • 159 Threads • Mostly superintelligence and MMA"
STATS_RE = re.compile(
    r"^\s*(?P<followers>[\d.,KMB]+)\s+Followers"
    r"(?:\s*[•·]\s*(?P<posts>[\d.,KMB]+)\s+Threads)?\s*[•·]?\s*",
    re.IGNORECASE,
)


class ThreadsAdapter(OpenGraphProfileAdapter):
    """Looks up publicly available Threads profile information."""

    platform = "threads"
    name = "Threads"
    url_template = "https://www.threads.net/@{identifier}"
    probe_present = "zuck"

    def extract_bio(self, meta: dict[str, str], html: str) -> str | None:
        """Return the biography without the audience counts.

        Threads prefixes its description with "N Followers • N Threads •".
        Comparing that as biography text would make any two busy accounts look
        alike, so the counts are stripped and recorded as metadata instead.
        """
        value = meta.get("og:description") or meta.get("description")
        if not value:
            return None
        remainder = STATS_RE.sub("", value, count=1).strip()
        return remainder or None

    def extract_metadata(self, meta: dict[str, str], html: str) -> dict[str, Any]:
        """Audience counts, as published on the profile."""
        match = STATS_RE.match(
            meta.get("og:description") or meta.get("description") or ""
        )
        if not match:
            return {}
        return {
            key: value
            for key, value in (
                ("followers", match.group("followers")),
                ("posts", match.group("posts")),
            )
            if value
        }
