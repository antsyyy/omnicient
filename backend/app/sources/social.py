"""Additional social source adapters.

Telegram and Medium both serve a public Open Graph card to anonymous readers
and permit it in robots.txt. Pinterest, Flickr, Patreon and Linktree were
checked and all disallow crawling.

Telegram is the lighter and more useful of the two: a public ``t.me`` page is
a 10KB card with the account's own description, which is where people put
their other handles.
"""

from __future__ import annotations

import re

from .base import OpenGraphProfileAdapter, SourceCategory

# "Read writing from DHH on Medium. Creator of Ruby on Rails, Founder ..."
MEDIUM_PREAMBLE_RE = re.compile(
    r"^Read writing from .*? on Medium\.\s*", re.IGNORECASE
)
MEDIUM_TRAILER_RE = re.compile(
    r"\s*Every day, .*? and thousands of other voices read, write, and share.*$",
    re.IGNORECASE | re.DOTALL,
)


class TelegramAdapter(OpenGraphProfileAdapter):
    """Public Telegram accounts and channels, via the t.me preview card.

    Only the public preview is read. Nothing here joins a channel, reads
    messages or touches the Telegram API - a ``t.me`` page is a public web
    page and is treated as one.
    """

    platform = "telegram"
    name = "Telegram"
    category = SourceCategory.SOCIAL
    url_template = "https://t.me/{identifier}"
    generic_titles = frozenset({"telegram", "telegram messenger"})

    def extract_bio(self, meta: dict[str, str], html: str) -> str | None:
        value = meta.get("og:description") or meta.get("description")
        if not value:
            return None
        text = value.strip()
        # What a non-existent handle returns, rather than a profile.
        if text.lower().startswith("you can contact @") or text.lower().startswith(
            "if you have telegram"
        ):
            return None
        return text or None


class MediumAdapter(OpenGraphProfileAdapter):
    """Medium author profiles, via the public Open Graph card."""

    platform = "medium"
    name = "Medium"
    category = SourceCategory.SOCIAL
    url_template = "https://medium.com/@{identifier}"
    generic_titles = frozenset({"medium"})

    def extract_display_name(self, title: str) -> str | None:
        """``DHH – Medium`` -> ``DHH``."""
        cleaned = re.sub(r"\s*[–—|-]\s*Medium\s*$", "", title).strip()
        return cleaned or super().extract_display_name(title)

    def extract_bio(self, meta: dict[str, str], html: str) -> str | None:
        """Strip Medium's own framing from around the author's text.

        Every profile description is wrapped in "Read writing from X on
        Medium… Every day, X and thousands of other voices…". Keeping that
        would make every Medium author look like they share a biography.
        """
        value = meta.get("og:description") or meta.get("description")
        if not value:
            return None
        trimmed = MEDIUM_TRAILER_RE.sub("", MEDIUM_PREAMBLE_RE.sub("", value)).strip()
        return trimmed or None
