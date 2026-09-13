"""DEV (dev.to) source adapter.

dev.to publishes a documented, unauthenticated user API, and its robots.txt
permits it.  The payload is unusually useful for correlation because the
platform asks users for their GitHub and Twitter handles directly, so a single
lookup yields cross-platform references the user themselves entered rather than
anything Omnicient had to infer.
"""

from __future__ import annotations

from typing import Any

from ..utils.url_parser import Reference
from .base import JsonProfileAdapter, ObservedProfile, SourceCategory, enrich_profile

#: dev.to profile field -> Omnicient platform.
LINKED_ACCOUNT_FIELDS: dict[str, str] = {
    "github_username": "github",
    "twitter_username": "x",
}


class DevToAdapter(JsonProfileAdapter):
    """Looks up publicly available DEV profile information."""

    platform = "devto"
    name = "DEV"
    category = SourceCategory.DEV
    api_template = "https://dev.to/api/users/by_username?url={identifier}"
    url_template = "https://dev.to/{identifier}"

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        if not isinstance(payload, dict) or not payload.get("username"):
            return None

        website = payload.get("website_url") or None
        observed = ObservedProfile(
            platform=self.platform,
            identifier=str(payload["username"]),
            name=f"@{payload['username']}",
            url=url,
            display_name=payload.get("name") or None,
            bio=payload.get("summary") or None,
            location=payload.get("location") or None,
            avatar_url=payload.get("profile_image") or None,
            external_links=[website] if website else [],
            source=self.platform,
            metadata={"joined_at": payload["joined_at"]}
            if payload.get("joined_at")
            else {},
        )

        enrich_profile(observed)

        # The user filled these in on their own profile, so they are explicit
        # references, not inferences from prose.
        declared = [
            Reference(
                platform=platform,
                identifier=str(payload[field]).lstrip("@"),
                url=None,
                context=f"Published on the DEV profile as the user's {platform} account",
                explicit=True,
            )
            for field, platform in LINKED_ACCOUNT_FIELDS.items()
            if payload.get(field)
        ]
        known = {reference.key for reference in declared}
        observed.references = [
            *declared,
            *(r for r in observed.references if r.key not in known),
        ]
        return observed
