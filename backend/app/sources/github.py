"""GitHub source adapter.

Reads the public user document GitHub publishes at ``api.github.com/users/{u}``.
That endpoint is the documented, anonymous interface for exactly this data, so
Omnicient uses it rather than scraping the profile page: it returns strictly
less information, it is stable, and it keeps a single request per lookup.

No token is sent.  Anonymous requests are rate limited by GitHub, and a rate
limit is reported as ``RATE_LIMITED`` and the investigation continues - it is
never evaded.

GitHub matters disproportionately in an identity investigation because
developers publish a personal site (``blog``) and often a company on the same
profile, which is exactly the kind of shared external attribute the
correlation engine can pivot on.
"""

from __future__ import annotations

from typing import Any

from .base import JsonProfileAdapter, ObservedProfile, SourceCategory, enrich_profile


class GitHubAdapter(JsonProfileAdapter):
    """Looks up publicly available GitHub profile information."""

    platform = "github"
    name = "GitHub"
    category = SourceCategory.DEV
    api_template = "https://api.github.com/users/{identifier}"
    url_template = "https://github.com/{identifier}"
    # GitHub's documented versioned media type; a plain HTML Accept is refused
    # with 415.
    accept = "application/vnd.github+json"

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        if not isinstance(payload, dict) or payload.get("type") == "Organization":
            # Organizations are real, but they are not accounts an individual
            # identity can be correlated through.
            return None
        login = payload.get("login")
        if not login:
            return None

        links = [link for link in [_clean_url(payload.get("blog"))] if link]

        return enrich_profile(
            ObservedProfile(
                platform=self.platform,
                identifier=str(login),
                name=f"@{login}",
                url=payload.get("html_url") or url,
                display_name=payload.get("name") or None,
                bio=payload.get("bio") or None,
                avatar_url=payload.get("avatar_url") or None,
                location=payload.get("location") or None,
                # Only ever the address the user chose to publish.
                email=payload.get("email") or None,
                organization=_clean_company(payload.get("company")),
                external_links=links,
                source=self.platform,
                metadata={
                    key: payload[key]
                    for key in ("public_repos", "followers", "created_at", "twitter_username")
                    if payload.get(key) is not None
                },
            )
        )


def _clean_url(value: Any) -> str | None:
    """GitHub's ``blog`` field is free text: it may omit the scheme entirely."""
    from ..utils.normalization import normalize_url

    if not value or not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    return normalize_url(candidate)


def _clean_company(value: Any) -> str | None:
    """``company`` is free text and often an ``@org`` handle."""
    if not value or not isinstance(value, str):
        return None
    return value.strip().lstrip("@") or None
