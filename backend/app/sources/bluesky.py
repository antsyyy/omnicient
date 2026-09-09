"""Bluesky source adapter.

Bluesky's AT Protocol exposes an unauthenticated public appview at
``public.api.bsky.app``, which its robots.txt permits.  Handles are domains
(``alice.bsky.social``, or a personal domain the user proved they control), and
that is what makes the platform interesting here: a custom Bluesky handle *is*
a claim of domain ownership, which the correlation engine can line up against a
website discovered elsewhere.
"""

from __future__ import annotations

from typing import Any

from .base import JsonProfileAdapter, ObservedProfile, enrich_profile

#: Handle suffixes issued by Bluesky itself, which say nothing about ownership.
PLATFORM_SUFFIXES = (".bsky.social", ".bsky.app")


class BlueskyAdapter(JsonProfileAdapter):
    """Looks up publicly available Bluesky profile information."""

    platform = "bluesky"
    name = "Bluesky"
    api_template = (
        "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor={identifier}"
    )
    url_template = "https://bsky.app/profile/{identifier}"

    def api_url(self, identifier: str) -> str:
        # A bare handle needs the default suffix; a dotted one is already
        # fully qualified (either a Bluesky subdomain or a custom domain).
        actor = identifier if "." in identifier else f"{identifier}.bsky.social"
        return self.api_template.format(identifier=actor)

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        if not isinstance(payload, dict) or not payload.get("handle"):
            return None

        handle = str(payload["handle"])
        links: list[str] = []
        # A custom domain handle is a verified claim of that domain.
        if not handle.endswith(PLATFORM_SUFFIXES) and "." in handle:
            links.append(f"https://{handle}")

        return enrich_profile(
            ObservedProfile(
                platform=self.platform,
                identifier=handle,
                name=f"@{handle}",
                url=self.url_template.format(identifier=handle),
                display_name=payload.get("displayName") or None,
                bio=payload.get("description") or None,
                avatar_url=payload.get("avatar") or None,
                external_links=links,
                source=self.platform,
                metadata={
                    key: payload[key]
                    for key in ("did", "followersCount", "postsCount", "createdAt")
                    if payload.get(key) is not None
                },
            )
        )
