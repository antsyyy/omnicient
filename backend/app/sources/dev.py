"""Developer-platform source adapters.

Each of these publishes a documented, unauthenticated endpoint describing a
public account, and each one's robots.txt permits reading it. GitLab, Codeberg
and Gitee were checked and refuse it, so they have no adapter here.

Developer profiles are unusually productive in an identity investigation: the
platforms ask directly for a personal site, a company and a location, so one
lookup often yields the external attributes the correlation engine pivots on.

Thin adapters are grouped by category rather than split one-per-file - there
is no per-platform parsing to speak of, and a single module keeps the shared
shape visible.
"""

from __future__ import annotations

from typing import Any

from .base import (
    JsonProfileAdapter,
    ObservedProfile,
    SourceCategory,
    enrich_profile,
    visible_text,
)


class HackerNewsAdapter(JsonProfileAdapter):
    """Hacker News, via the public Firebase API.

    The ``about`` field is free text an author wrote about themselves, which
    is where personal sites and other handles usually appear.
    """

    platform = "hackernews"
    name = "Hacker News"
    category = SourceCategory.DEV
    api_template = "https://hacker-news.firebaseio.com/v0/user/{identifier}.json"
    url_template = "https://news.ycombinator.com/user?id={identifier}"
    probe_present = "pg"

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        if not isinstance(payload, dict) or not payload.get("id"):
            return None
        return enrich_profile(
            ObservedProfile(
                platform=self.platform,
                identifier=str(payload["id"]),
                name=f"@{payload['id']}",
                url=url,
                # HN renders the bio as HTML; the shared extraction reads the
                # links out of it either way.
                bio=payload.get("about") or None,
                source=self.platform,
                metadata={
                    key: payload[key]
                    for key in ("karma", "created")
                    if payload.get(key) is not None
                },
            )
        )


class HuggingFaceAdapter(JsonProfileAdapter):
    """Hugging Face, via the public user overview API."""

    platform = "huggingface"
    name = "Hugging Face"
    category = SourceCategory.DEV
    api_template = "https://huggingface.co/api/users/{identifier}/overview"
    url_template = "https://huggingface.co/{identifier}"
    probe_present = "julien-c"

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        if not isinstance(payload, dict) or not payload.get("user"):
            return None
        links = [
            link
            for link in (payload.get("homepage"), payload.get("websiteUrl"))
            if link
        ]
        return enrich_profile(
            ObservedProfile(
                platform=self.platform,
                identifier=str(payload["user"]),
                name=f"@{payload['user']}",
                url=url,
                display_name=payload.get("fullname") or None,
                bio=payload.get("details") or None,
                avatar_url=payload.get("avatarUrl") or None,
                organization=payload.get("company") or None,
                external_links=links,
                source=self.platform,
                metadata={
                    key: payload[key]
                    for key in ("numFollowers", "numModels", "numDatasets", "isPro")
                    if payload.get(key) is not None
                },
            )
        )


class CratesIoAdapter(JsonProfileAdapter):
    """crates.io, the Rust package registry.

    Accounts are GitHub-backed, so ``url`` is a verified link to the GitHub
    profile that owns this one - an explicit cross-platform reference rather
    than an inference.
    """

    platform = "crates"
    name = "crates.io"
    category = SourceCategory.DEV
    api_template = "https://crates.io/api/v1/users/{identifier}"
    url_template = "https://crates.io/users/{identifier}"
    probe_present = "carols10cents"

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        user = payload.get("user") if isinstance(payload, dict) else None
        if not isinstance(user, dict) or not user.get("login"):
            return None
        github = user.get("url")
        return enrich_profile(
            ObservedProfile(
                platform=self.platform,
                identifier=str(user["login"]),
                name=f"@{user['login']}",
                url=url,
                display_name=user.get("name") or None,
                avatar_url=user.get("avatar") or None,
                # The GitHub URL is the account this one is authenticated by.
                external_links=[github] if github else [],
                source=self.platform,
            )
        )


class DockerHubAdapter(JsonProfileAdapter):
    """Docker Hub, via the public v2 user API."""

    platform = "dockerhub"
    name = "Docker Hub"
    category = SourceCategory.DEV
    api_template = "https://hub.docker.com/v2/users/{identifier}/"
    url_template = "https://hub.docker.com/u/{identifier}"
    probe_present = "bmitch"

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        if not isinstance(payload, dict) or not payload.get("username"):
            return None
        website = payload.get("profile_url") or None
        return enrich_profile(
            ObservedProfile(
                platform=self.platform,
                identifier=str(payload["username"]),
                name=f"@{payload['username']}",
                url=url,
                display_name=payload.get("full_name") or None,
                location=payload.get("location") or None,
                organization=payload.get("company") or None,
                avatar_url=payload.get("gravatar_url") or None,
                external_links=[website] if website else [],
                source=self.platform,
                metadata={"date_joined": payload["date_joined"]}
                if payload.get("date_joined")
                else {},
            )
        )


class StackOverflowAdapter(JsonProfileAdapter):
    """Stack Overflow, via the public Stack Exchange API.

    Stack Exchange has no unique username, so this searches by display name
    and takes the single best match. That is weaker than an exact handle
    lookup, so a result is treated as a lead like any other: the correlation
    engine still has to find real evidence behind it.
    """

    platform = "stackoverflow"
    name = "Stack Overflow"
    category = SourceCategory.DEV
    api_template = (
        "https://api.stackexchange.com/2.3/users"
        "?inname={identifier}&site=stackoverflow&order=desc&sort=reputation"
    )
    probe_present = "Jon Skeet"
    url_template = "https://stackoverflow.com/users?tab=Reputation"

    def normalize_identifier(self, identifier: str) -> str:
        """Display names carry spaces, so the handle normalizer is too strict."""
        from urllib.parse import quote

        cleaned = " ".join(str(identifier).strip().split())
        if not cleaned:
            from ..utils.normalization import NormalizationError

            raise NormalizationError("a display name is required")
        return quote(cleaned)

    def profile_url(self, identifier: str) -> str:
        return self.url_template

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list) or not items:
            return None

        # Only an exact display-name match is worth reporting; a fuzzy search
        # hit would manufacture an account that may belong to anyone.
        from urllib.parse import unquote

        wanted = unquote(identifier).replace(" ", "").lower()
        user = next(
            (
                item
                for item in items
                if str(item.get("display_name", "")).replace(" ", "").lower() == wanted
            ),
            None,
        )
        if user is None:
            return None

        website = user.get("website_url") or None
        return enrich_profile(
            ObservedProfile(
                platform=self.platform,
                identifier=str(user.get("display_name")),
                name=f"@{user.get('display_name')}",
                url=user.get("link") or url,
                display_name=user.get("display_name") or None,
                location=user.get("location") or None,
                avatar_url=user.get("profile_image") or None,
                external_links=[website] if website else [],
                source=self.platform,
                metadata={
                    key: user[key]
                    for key in ("reputation", "user_id", "creation_date")
                    if user.get(key) is not None
                },
            )
        )


class LaunchpadAdapter(JsonProfileAdapter):
    """Launchpad, Canonical's public development platform."""

    platform = "launchpad"
    name = "Launchpad"
    category = SourceCategory.DEV
    api_template = "https://api.launchpad.net/1.0/~{identifier}"
    url_template = "https://launchpad.net/~{identifier}"
    probe_present = "mark"

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        if not isinstance(payload, dict) or not payload.get("name"):
            return None
        homepage = payload.get("homepage_content") or None
        return enrich_profile(
            ObservedProfile(
                platform=self.platform,
                identifier=str(payload["name"]),
                name=f"@{payload['name']}",
                url=payload.get("web_link") or url,
                display_name=payload.get("display_name") or None,
                bio=payload.get("description") or homepage or None,
                source=self.platform,
                metadata={"date_created": payload["date_created"]}
                if payload.get("date_created")
                else {},
            )
        )


class LobstersAdapter(JsonProfileAdapter):
    """Lobsters, via the public per-user JSON document.

    Worth reading for one field in particular: the site asks members to
    record their GitHub and Twitter handles, and publishes them. That is a
    self-declared cross-platform link rather than an inference from a
    matching handle.
    """

    platform = "lobsters"
    name = "Lobsters"
    category = SourceCategory.DEV
    # The site moved from /u/<name> to /~<name>; the old path still answers,
    # but with a 301 to the HTML page, so a JSON request quietly got a web
    # page instead of an error. Found by the self-check.
    api_template = "https://lobste.rs/~{identifier}.json"
    url_template = "https://lobste.rs/~{identifier}"
    probe_present = "jcs"

    #: Fields naming an account elsewhere, and how to build its URL.
    LINKED_ACCOUNTS = (
        ("github_username", "https://github.com/{}"),
        ("twitter_username", "https://twitter.com/{}"),
    )

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        if not isinstance(payload, dict) or not payload.get("username"):
            return None
        handle = str(payload["username"])

        links: list[str] = []
        for field, template in self.LINKED_ACCOUNTS:
            value = payload.get(field)
            if isinstance(value, str) and value.strip():
                links.append(template.format(value.strip()))

        avatar = payload.get("avatar_url")
        if isinstance(avatar, str) and avatar.startswith("/"):
            # Published relative to the site root; stored absolute so it can
            # still be fetched from anywhere else.
            avatar = f"https://lobste.rs{avatar}"

        return enrich_profile(
            ObservedProfile(
                platform=self.platform,
                identifier=handle,
                name=f"@{handle}",
                url=url,
                # Published as HTML. Stored as the text a person wrote, so
                # the bio comparison is not matching markup tags.
                bio=visible_text(payload.get("about") or "") or None,
                avatar_url=avatar or None,
                external_links=links,
                source=self.platform,
                metadata={
                    key: payload[key]
                    for key in ("karma", "created_at", "is_moderator")
                    if payload.get(key) is not None
                },
            )
        )
