"""Reddit source adapter.

Reads the public account document Reddit publishes at
``reddit.com/user/{name}/about.json`` - the same data the profile page renders,
in the form Reddit publishes for anonymous readers.

Reddit is strict with automated clients and will answer some requests with a
block or a rate limit.  That is reported (``BLOCKED`` / ``RATE_LIMITED``) and
the investigation continues with the other sources; Omnicient does not rotate
user agents, retry behind proxies or otherwise work around the refusal.

A Reddit handle is usually weak evidence on its own - handles are reused across
unrelated people - so what makes a Reddit account interesting here is the
public description, which is where users publish a personal site or another
handle.
"""

from __future__ import annotations

from typing import Any

from .base import JsonProfileAdapter, ObservedProfile, enrich_profile


class RedditAdapter(JsonProfileAdapter):
    """Looks up publicly available Reddit account information."""

    platform = "reddit"
    name = "Reddit"
    api_template = "https://www.reddit.com/user/{identifier}/about.json"
    url_template = "https://www.reddit.com/user/{identifier}"

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        name = data.get("name")
        if not name:
            return None
        # Suspended and shadowbanned accounts still return a document, but
        # there is no public profile behind it.
        if data.get("is_suspended"):
            return None

        subreddit = data.get("subreddit") if isinstance(data.get("subreddit"), dict) else {}
        bio = (
            subreddit.get("public_description")
            or subreddit.get("description")
            or None
        )
        avatar = _clean_image(
            subreddit.get("icon_img") or data.get("icon_img") or data.get("snoovatar_img")
        )

        return enrich_profile(
            ObservedProfile(
                platform=self.platform,
                identifier=str(name),
                name=f"@{name}",
                url=url,
                display_name=(subreddit.get("title") or "").strip() or None,
                bio=bio.strip() if isinstance(bio, str) else None,
                avatar_url=avatar,
                source=self.platform,
                metadata={
                    key: data[key]
                    for key in ("created_utc", "total_karma", "is_employee", "verified")
                    if data.get(key) is not None
                },
            )
        )


def _clean_image(value: Any) -> str | None:
    """Reddit serves avatar URLs with HTML-escaped query strings."""
    if not value or not isinstance(value, str):
        return None
    candidate = value.split("?")[0].replace("&amp;", "&").strip()
    return candidate or None
