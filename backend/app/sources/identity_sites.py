"""Sites whose whole purpose is to say who somebody is.

about.me and Micro.blog are not platforms an investigation happens to find an
account on - they are pages a person made in order to be found, which makes
them unusually honest sources.  What they publish is what their owner wanted
published: a real name, a place, a short biography, and links to wherever else
they are.

about.me carries one trap worth knowing about.  It echoes the request headers
back into the page it serves, so the crawler's own user agent - which contains
a project URL - appears in the HTML of every profile.  Extracted naively that
recorded the same GitHub account on every about.me profile ever read, the
observer turning up in its own observations.  The shared link extraction drops
it; this module does not have to think about it, but the next person reading
an odd link on a profile should know it happened once.
"""

from __future__ import annotations

import re
from typing import Any

from .base import OpenGraphProfileAdapter, SourceCategory

#: "Tim Roberts - San Francisco | about.me" -> name and where they say they are.
ABOUTME_TITLE_RE = re.compile(
    r"^(?P<name>.+?)(?:\s+-\s+(?P<location>[^|]+?))?\s*\|\s*about\.me\s*$",
    re.IGNORECASE,
)

#: "Micro.blog - @manton"
MICROBLOG_TITLE_RE = re.compile(r"^\s*Micro\.blog\s*[-–]\s*@?(?P<name>.+?)\s*$", re.I)


class AboutMeAdapter(OpenGraphProfileAdapter):
    """about.me, a page built to introduce one person."""

    platform = "aboutme"
    name = "about.me"
    category = SourceCategory.IDENTITY
    url_template = "https://about.me/{identifier}"
    probe_present = "tim"
    generic_titles = frozenset({"about.me", "about me"})

    def _title(self, html: str) -> re.Match[str] | None:
        from .base import parse_meta

        meta = parse_meta(html)
        title = (meta.get("og:title") or meta.get("title") or "").strip()
        # The card says "Tim Roberts on about.me"; the page title carries the
        # location as well, so it is worth reading instead.
        page = re.search(r"<title[^>]*>([^<]+)</title>", html)
        return ABOUTME_TITLE_RE.match((page.group(1) if page else title).strip())

    def extract_display_name(self, title: str) -> str | None:
        match = ABOUTME_TITLE_RE.match(title.strip())
        if match:
            return match.group("name").strip() or None
        # "Tim Roberts on about.me"
        cleaned = re.sub(r"\s+on\s+about\.me\s*$", "", title, flags=re.I).strip()
        return cleaned or super().extract_display_name(title)

    def extract_location(self, meta: dict[str, str], html: str) -> str | None:
        """about.me puts the place in the page title, next to the name."""
        match = self._title(html)
        location = match.group("location") if match else None
        return (location or "").strip() or None


class MicroBlogAdapter(OpenGraphProfileAdapter):
    """Micro.blog, where a profile is a person and their own site."""

    platform = "microblog"
    name = "Micro.blog"
    category = SourceCategory.SOCIAL
    url_template = "https://micro.blog/{identifier}"
    probe_present = "manton"
    generic_titles = frozenset({"micro.blog", "microblog"})

    def parse_profile(self, identifier: str, html: str, url: str):
        """Read the page title, because there is no Open Graph title to read.

        Micro.blog publishes an ``og:image`` and nothing else from the card,
        so the shared parser - which needs an ``og:title`` to decide a page is
        a profile at all - gave up on every profile. The document title
        carries the handle.
        """
        from .base import parse_meta

        meta = parse_meta(html)
        if not meta.get("og:title"):
            page = re.search(r"<title[^>]*>([^<]+)</title>", html)
            if page and MICROBLOG_TITLE_RE.match(page.group(1).strip()):
                html = html.replace(
                    "</head>",
                    f'<meta property="og:title" content="{page.group(1).strip()}">'
                    "</head>",
                    1,
                )
        return super().parse_profile(identifier, html, url)

    def extract_display_name(self, title: str) -> str | None:
        match = MICROBLOG_TITLE_RE.match(title)
        if match:
            handle = match.group("name").strip()
            return handle or None
        return super().extract_display_name(title)

    def extract_metadata(self, meta: dict[str, str], html: str) -> dict[str, Any]:
        """Micro.blog marks a personal site the account has proven it owns.

        That is a stronger statement than a link in a bio - the platform
        checked - so it is worth recording as its own observation.
        """
        return {"verified_url": True} if "Verified URL" in html else {}
