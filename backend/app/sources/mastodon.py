"""Mastodon source adapter.

Mastodon instances expose a public, unauthenticated account API, and
``mastodon.social/robots.txt`` permits it.  Because Mastodon is federated there
is no single host: this adapter reads the instance named in the handle
(``user@instance``) and otherwise falls back to the default instance.

The profile "fields" are the interesting part for an investigation - that is
where people publish their personal site and their other accounts, and where a
verified link carries an instance-checked ``verified_at``.
"""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from ..utils.normalization import normalize_username
from .base import JsonProfileAdapter, ObservedProfile, enrich_profile

#: Instance queried when the handle does not name one.
DEFAULT_INSTANCE = "mastodon.social"

#: Instances the adapter is willing to query.  Mastodon is federated, so the
#: handle chooses the host - and an allow-list is what stops a crafted handle
#: from pointing the crawler at an arbitrary server.
ALLOWED_INSTANCES: frozenset[str] = frozenset(
    {
        "mastodon.social",
        "mastodon.online",
        "fosstodon.org",
        "infosec.exchange",
        "hachyderm.io",
        "mstdn.social",
        "techhub.social",
    }
)

def _links_and_text(html: str) -> tuple[list[str], str]:
    """Split Mastodon's rendered HTML into its hrefs and its prose.

    Anchors are pulled out *and removed* rather than flattened. Mastodon
    renders a long URL across ``<span class="invisible">`` fragments, so
    replacing tags with whitespace shatters
    ``bsky.app/profile/freshyill.bsky.social`` into ``freshyill.bsk`` and
    ``y.social`` - two entities that do not exist. The href already carries the
    real URL, so the display text is dropped.
    """
    soup = BeautifulSoup(html or "", "lxml")
    links: list[str] = []
    for anchor in soup.find_all("a"):
        href = (anchor.get("href") or "").strip()
        if href and href not in links:
            links.append(href)
        anchor.decompose()
    return links, " ".join(soup.get_text(" ", strip=True).split())


class MastodonAdapter(JsonProfileAdapter):
    """Looks up publicly available Mastodon account information."""

    platform = "mastodon"
    name = "Mastodon"
    api_template = "https://{instance}/api/v1/accounts/lookup?acct={handle}"
    url_template = "https://{instance}/@{handle}"
    probe_present = "Gargron"

    @staticmethod
    def _split(identifier: str) -> tuple[str, str]:
        """``alice@fosstodon.org`` -> ``("alice", "fosstodon.org")``."""
        handle, _, instance = identifier.lstrip("@").partition("@")
        instance = instance.lower() or DEFAULT_INSTANCE
        if instance not in ALLOWED_INSTANCES:
            instance = DEFAULT_INSTANCE
        return normalize_username(handle), instance

    def api_url(self, identifier: str) -> str:
        handle, instance = self._split(identifier)
        return self.api_template.format(instance=instance, handle=handle)

    def profile_url(self, identifier: str) -> str:
        handle, instance = self._split(identifier)
        return self.url_template.format(instance=instance, handle=handle)

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        if not isinstance(payload, dict) or not payload.get("username"):
            return None

        links: list[str] = []
        notes: list[str] = []
        for field in payload.get("fields") or []:
            if not isinstance(field, dict):
                continue
            field_links, text = _links_and_text(field.get("value") or "")
            for href in field_links:
                if href not in links:
                    links.append(href)
            if text:
                notes.append(f"{field.get('name', '')}: {text}".strip(": "))

        note_links, bio = _links_and_text(payload.get("note") or "")
        for href in note_links:
            if href not in links:
                links.append(href)
        # Field labels often name a platform ("GitHub: alice"), which is what
        # the shared reference extraction reads.
        combined = " ".join(part for part in [bio, *notes] if part)

        return enrich_profile(
            ObservedProfile(
                platform=self.platform,
                identifier=str(payload["username"]),
                name=f"@{payload['username']}",
                url=payload.get("url") or url,
                display_name=payload.get("display_name") or None,
                bio=combined or None,
                avatar_url=payload.get("avatar_static") or payload.get("avatar"),
                external_links=links,
                source=self.platform,
                metadata={
                    key: payload[key]
                    for key in ("followers_count", "statuses_count", "created_at", "bot")
                    if payload.get(key) is not None
                },
            )
        )
