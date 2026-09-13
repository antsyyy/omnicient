"""Learning-platform source adapters.

Codewars, Scratch and Duolingo all publish a documented JSON endpoint for a
public profile and permit it in robots.txt. HackerRank disallows crawling;
LeetCode and Exercism answer a non-browser client with HTTP 403, which is
their decision and is reported rather than worked around.
"""

from __future__ import annotations

from typing import Any

from .base import (
    JsonProfileAdapter,
    ObservedProfile,
    SourceCategory,
    enrich_profile,
)


class CodewarsAdapter(JsonProfileAdapter):
    """Codewars, via the public v1 user API."""

    platform = "codewars"
    name = "Codewars"
    category = SourceCategory.LEARNING
    api_template = "https://www.codewars.com/api/v1/users/{identifier}"
    url_template = "https://www.codewars.com/users/{identifier}"

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        if not isinstance(payload, dict) or not payload.get("username"):
            return None
        ranks = payload.get("ranks") or {}
        overall = ranks.get("overall") if isinstance(ranks, dict) else None
        return enrich_profile(
            ObservedProfile(
                platform=self.platform,
                identifier=str(payload["username"]),
                name=f"@{payload['username']}",
                url=url,
                display_name=payload.get("name") or None,
                # "clan" is a free-text field people commonly fill with an
                # employer or a school.
                organization=payload.get("clan") or None,
                source=self.platform,
                metadata={
                    key: value
                    for key, value in (
                        ("honor", payload.get("honor")),
                        ("leaderboard_position", payload.get("leaderboardPosition")),
                        ("rank", (overall or {}).get("name")),
                    )
                    if value is not None
                },
            )
        )


class ScratchAdapter(JsonProfileAdapter):
    """Scratch, via the public MIT API.

    Scratch is used heavily by minors. The adapter reads only what the site
    already serves publicly and records nothing extra; as everywhere else in
    Omnicient, an account is a publicly observable entity, not a person.
    """

    platform = "scratch"
    name = "Scratch"
    category = SourceCategory.LEARNING
    api_template = "https://api.scratch.mit.edu/users/{identifier}"
    url_template = "https://scratch.mit.edu/users/{identifier}"

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        if not isinstance(payload, dict) or not payload.get("username"):
            return None
        profile = payload.get("profile") or {}
        images = profile.get("images") or {}
        # "status" is the "what I'm working on" box, where people put links.
        bio = " ".join(
            part
            for part in (profile.get("bio"), profile.get("status"))
            if part
        ).strip()

        return enrich_profile(
            ObservedProfile(
                platform=self.platform,
                identifier=str(payload["username"]),
                name=f"@{payload['username']}",
                url=url,
                bio=bio or None,
                location=profile.get("country") or None,
                avatar_url=images.get("90x90") or images.get("60x60") or None,
                source=self.platform,
                metadata={
                    key: value
                    for key, value in (
                        ("scratch_id", payload.get("id")),
                        ("joined", (payload.get("history") or {}).get("joined")),
                    )
                    if value is not None
                },
            )
        )


class DuolingoAdapter(JsonProfileAdapter):
    """Duolingo, via the public user lookup endpoint."""

    platform = "duolingo"
    name = "Duolingo"
    category = SourceCategory.LEARNING
    api_template = "https://www.duolingo.com/2017-06-30/users?username={identifier}"
    url_template = "https://www.duolingo.com/profile/{identifier}"

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        users = payload.get("users") if isinstance(payload, dict) else None
        if not isinstance(users, list) or not users:
            return None
        user = users[0]
        if not isinstance(user, dict) or not user.get("username"):
            return None

        picture = user.get("picture")
        # The API returns a protocol-relative URL.
        if isinstance(picture, str) and picture.startswith("//"):
            picture = f"https:{picture}"

        return enrich_profile(
            ObservedProfile(
                platform=self.platform,
                identifier=str(user["username"]),
                name=f"@{user['username']}",
                url=url,
                display_name=user.get("name") or None,
                bio=user.get("bio") or None,
                avatar_url=picture or None,
                source=self.platform,
                metadata={
                    key: user[key]
                    for key in ("streak", "totalXp", "creationDate", "learningLanguage")
                    if user.get(key) is not None
                },
            )
        )
