"""Identifier detection: work out what the analyst typed.

Omnicient asks for one thing - "username, email, profile URL, or domain" - and
never for a platform (section 3.2).  This module is the layer that makes that
possible: it classifies the raw input, and where the input already names a
platform (a profile URL) it extracts that too.

    >>> detect_identifier("alice_98").type
    <IdentifierType.USERNAME: 'USERNAME'>
    >>> detect_identifier("https://github.com/alice-security").platform
    'github'
    >>> detect_identifier("alice.dev").type
    <IdentifierType.DOMAIN: 'DOMAIN'>

Detection is deliberately conservative and ordered most-specific first: an
email is unambiguous, a recognized profile URL names its own platform, and a
bare word with no dot and no scheme is a username.  Anything that matches
nothing raises :class:`~app.utils.normalization.NormalizationError` rather than
being guessed at, because a wrong guess sends the crawler somewhere useless.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

from .normalization import (
    NormalizationError,
    looks_like_domain,
    normalize_domain,
    normalize_platform,
    normalize_url,
    normalize_username,
)
from .url_parser import detect_platform, parse_profile_url

#: Longest input we will even look at, matching the URL guard in validation.
MAX_IDENTIFIER_LENGTH = 2048

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}$")

#: A bare hostname: at least one dot, a plausible TLD, no path or scheme.
DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$", re.IGNORECASE
)

#: Usernames as the supported platforms allow them.
#:
#: A leading underscore is deliberately allowed: "_alice" is a perfectly
#: ordinary handle on Instagram, X and TikTok, and requiring an alphanumeric
#: first character rejected every one of them outright.
USERNAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,63}$")


class IdentifierType(StrEnum):
    """What kind of thing the analyst typed."""

    USERNAME = "USERNAME"
    EMAIL = "EMAIL"
    PROFILE_URL = "PROFILE_URL"
    DOMAIN = "DOMAIN"
    #: A URL that is reachable but is not a recognized social profile - a
    #: personal site, a blog post, a contact page.
    WEBSITE_URL = "WEBSITE_URL"


#: Seed platform used for each identifier type when the input does not name
#: one itself.  ``USERNAME`` has no platform by definition: that is the case
#: the discovery engine fans out across every adapter.
DEFAULT_PLATFORM: dict[str, str | None] = {
    IdentifierType.EMAIL: "email",
    IdentifierType.DOMAIN: "website",
    IdentifierType.WEBSITE_URL: "website",
    IdentifierType.USERNAME: None,
    IdentifierType.PROFILE_URL: None,
}


@dataclass(frozen=True)
class DetectedIdentifier:
    """The classified seed, ready for :func:`app.services.discovery.discover_sources`."""

    type: IdentifierType
    #: The canonical value to search with: a handle, an email, a domain or a URL.
    identifier: str
    #: The platform the input named, if it named one.  ``None`` means "search
    #: every adapter that supports this identifier".
    platform: str | None
    #: Exactly what the analyst typed, preserved for display and audit.
    raw: str
    url: str | None = None

    @property
    def seed_platform(self) -> str:
        """Platform to record on the investigation.

        A username with no platform is seeded against ``username``, which the
        discovery engine expands across every account adapter.
        """
        if self.platform:
            return self.platform
        return "username" if self.type is IdentifierType.USERNAME else "website"

    @property
    def description(self) -> str:
        """Analyst-facing summary, e.g. ``USERNAME alice_98``."""
        platform = f" on {self.platform}" if self.platform else ""
        return f"{self.type} {self.identifier}{platform}"


def detect_identifier(value: str | None) -> DetectedIdentifier:
    """Classify a raw analyst input.

    Raises :class:`NormalizationError` when the input is empty, over-long or
    matches no supported shape.
    """
    if value is None:
        raise NormalizationError("an identifier is required")
    raw = str(value).strip()
    if not raw:
        raise NormalizationError("an identifier is required")
    if len(raw) > MAX_IDENTIFIER_LENGTH:
        raise NormalizationError("identifier is too long")

    # 1. Email: unambiguous, and checked before anything that contains a dot.
    candidate = raw[7:] if raw.lower().startswith("mailto:") else raw
    if EMAIL_RE.match(candidate):
        return DetectedIdentifier(
            type=IdentifierType.EMAIL,
            identifier=candidate.lower(),
            platform="email",
            raw=raw,
        )

    # 2. Anything with a scheme, or a host-plus-path, is a URL.
    if _looks_like_url(raw):
        return _classify_url(raw)

    # 3. A bare hostname - but only when the last label is a real TLD.
    #    "firstname.lastname" is a handle, not a site.
    if DOMAIN_RE.match(raw) and looks_like_domain(raw):
        domain = normalize_domain(raw)
        if domain:
            return DetectedIdentifier(
                type=IdentifierType.DOMAIN,
                identifier=domain,
                platform="website",
                raw=raw,
                url=f"https://{domain}/",
            )

    # 4. A bare handle, with or without a leading '@'.
    handle = raw[1:] if raw.startswith("@") else raw
    if USERNAME_RE.match(handle):
        return DetectedIdentifier(
            type=IdentifierType.USERNAME,
            identifier=normalize_username(handle),
            platform=None,
            raw=raw,
        )

    raise NormalizationError(
        f"{raw!r} is not a recognized username, email address, profile URL or domain"
    )


def _looks_like_url(value: str) -> bool:
    """True when the input should be parsed as a URL rather than a handle."""
    lowered = value.lower()
    if lowered.startswith(("http://", "https://")):
        return True
    # Reject other schemes outright: ftp:, file:, javascript: and friends are
    # never fetched, and must not fall through to the username branch.
    if "://" in value:
        return True
    # ``instagram.com/alice_98`` - a host with a path, but no scheme.
    head, _, tail = value.partition("/")
    return bool(tail) and bool(DOMAIN_RE.match(head))


def _classify_url(raw: str) -> DetectedIdentifier:
    """Split a URL into a recognized profile, or a plain website."""
    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https"):
        raise NormalizationError(
            f"unsupported URL scheme {parsed.scheme!r}: only http and https are fetched"
        )
    if not parsed.netloc:
        raise NormalizationError(f"{raw!r} is not a valid URL")

    profile = parse_profile_url(candidate)
    if profile is not None:
        platform, identifier = profile
        return DetectedIdentifier(
            type=IdentifierType.PROFILE_URL,
            identifier=identifier,
            platform=platform,
            raw=raw,
            url=normalize_url(candidate) or candidate,
        )

    # A known platform host whose path is not a profile: a post, a reel, a
    # search page, a login interstitial.  Refused rather than downgraded to a
    # website seed - crawling instagram.com because the analyst pasted a post
    # link would spend the budget somewhere they did not ask about, and the
    # honest answer is that this URL names no account.
    if detect_platform(candidate) is not None:
        raise NormalizationError(
            f"{raw!r} is not a public profile URL. Use the profile address "
            f"itself, or the handle on its own."
        )

    domain = normalize_domain(candidate)
    if domain is None:
        raise NormalizationError(f"{raw!r} is not a valid URL")

    return DetectedIdentifier(
        type=IdentifierType.WEBSITE_URL,
        identifier=domain,
        platform="website",
        raw=raw,
        url=normalize_url(candidate) or candidate,
    )


def describe_sources(detected: DetectedIdentifier, platforms: list[str]) -> str:
    """One line for the activity log: what will be searched, and why."""
    if detected.platform:
        return (
            f"Seed identifier detected: {detected.type} "
            f"({detected.platform} @{detected.identifier})"
        )
    return (
        f"Seed identifier detected: {detected.type} @{detected.identifier} - "
        f"searching {len(platforms)} supported sources"
    )


__all__ = [
    "DEFAULT_PLATFORM",
    "DetectedIdentifier",
    "IdentifierType",
    "describe_sources",
    "detect_identifier",
    "detect_platform",
    "normalize_platform",
]
