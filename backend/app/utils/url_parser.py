"""URL and identifier extraction.

Turns free text and link lists into structured, platform-aware references.
The parser is deliberately strict: an arbitrary URL is *not* treated as a
social profile, and path segments that platforms use for posts, reels or
interstitials never become account identifiers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .normalization import (
    PLATFORM_HOSTS,
    RESERVED_PATHS,
    NormalizationError,
    normalize_domain,
    normalize_platform,
    normalize_url,
    normalize_username,
)

# Path segments that prefix an account identifier rather than being one.
PROFILE_PATH_PREFIXES: dict[str, tuple[str, ...]] = {
    "reddit": ("u", "user"),
    "linkedin": ("in", "company", "school", "pub"),
    "youtube": ("c", "channel", "user"),
    "facebook": ("people",),
}

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
BARE_DOMAIN_RE = re.compile(
    r"(?<![\w@/.])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:com|net|org|io|dev|me|co|app|xyz|info|blog|page|social|sh|ai|tech))"
    r"(/[^\s<>\"')\]]*)?",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(
    r"(?<![\w.+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24})(?![\w.-])"
)

# Platform words that appear in bios: "Threads: @alice_dev", "GitHub - alice".
# Deliberately excludes ambiguous one-letter aliases such as "x".
MENTION_WORDS: dict[str, str] = {
    "threads": "threads",
    "instagram": "instagram",
    "insta": "instagram",
    "ig": "instagram",
    "facebook": "facebook",
    "fb": "facebook",
    "github": "github",
    "reddit": "reddit",
    "twitter": "x",
    "linkedin": "linkedin",
    "youtube": "youtube",
    "mastodon": "mastodon",
}

MENTION_RE = re.compile(
    r"\b(?P<word>" + "|".join(sorted(MENTION_WORDS, key=len, reverse=True)) + r")\b"
    r"\s*(?:handle|profile|account|page|user(?:name)?)?\s*[:\-–>/]*\s*"
    r"@?(?P<handle>[A-Za-z0-9._-]{2,64})",
    re.IGNORECASE,
)

# "Security engineer at Acme Labs", "Researcher @ Contoso Security"
# A period ends the candidate: "at Contoso Labs. Threads: @alice" must not
# capture the following sentence.
ORGANISATION_RE = re.compile(
    r"\b(?:at|@)\s+(?P<org>[A-Z][\w&'-]*(?:\s+[A-Z][\w&'-]*){0,2})"
)
_ORG_STOPWORDS = frozenset(
    {"the", "home", "work", "night", "day", "gmail", "hotmail", "outlook"}
)

_TLD_LIKE = frozenset(
    {"com", "net", "org", "io", "dev", "me", "co", "app", "social", "ai"}
)


@dataclass(frozen=True)
class Reference:
    """A platform account referenced by some piece of public content."""

    platform: str
    identifier: str
    url: str | None
    context: str
    explicit: bool = True

    @property
    def key(self) -> tuple[str, str]:
        return (self.platform, self.identifier)


def detect_platform(url: str | None) -> str | None:
    """Return the platform a URL belongs to, or ``None`` if unrecognized."""
    host = normalize_domain(url)
    if not host:
        return None
    for platform, hosts in PLATFORM_HOSTS.items():
        if any(host == known or host.endswith(f".{known}") for known in hosts):
            return platform
    return None


def parse_profile_url(url: str | None) -> tuple[str, str] | None:
    """Parse a social profile URL into ``(platform, identifier)``.

    Returns ``None`` for unrecognized hosts and for non-profile paths such as
    ``instagram.com/p/XYZ``, ``facebook.com/profile.php?id=1`` or
    ``x.com/intent/follow``.

        >>> parse_profile_url("https://github.com/alice-security")
        ('github', 'alice-security')
    """
    if not url:
        return None
    platform = detect_platform(url)
    if platform is None:
        return None

    parsed = urlparse(url if "://" in url else f"https://{url}")
    segments = [segment for segment in parsed.path.split("/") if segment.strip()]
    if not segments:
        return None

    prefixes = PROFILE_PATH_PREFIXES.get(platform, ())
    first = segments[0].lstrip("@").lower()
    if first in prefixes:
        if len(segments) < 2:
            return None
        raw = segments[1]
    elif first in RESERVED_PATHS:
        return None
    else:
        raw = segments[0]

    try:
        return platform, normalize_username(raw)
    except NormalizationError:
        return None


def website_identity(url: str | None) -> str | None:
    """Canonical identity of a non-social website link.

    ``https://www.alice.dev/`` and ``http://alice.dev`` both become
    ``alice.dev``.  Social profile URLs return ``None`` - they are accounts,
    and counting them as shared websites would double-count evidence.
    """
    if not url or detect_platform(url) is not None:
        return None
    normalized = normalize_url(url)
    if not normalized:
        return None
    parsed = urlparse(normalized)
    host = parsed.netloc
    if not host or "." not in host:
        return None
    return f"{host}{parsed.path}".lower()


def extract_urls(text: str | None) -> list[str]:
    """Pull http(s) URLs and bare domains out of free text, in order."""
    if not text:
        return []
    found: list[str] = []

    def add(candidate: str) -> None:
        cleaned = candidate.strip().rstrip(".,);:!'\"")
        normalized = normalize_url(cleaned)
        if normalized and normalized not in found:
            found.append(normalized)

    spans: list[tuple[int, int]] = []
    for match in URL_RE.finditer(text):
        spans.append(match.span())
        add(match.group(0))
    for match in BARE_DOMAIN_RE.finditer(text):
        if any(start <= match.start() < end for start, end in spans):
            continue
        add(match.group(0))
    return found


def extract_emails(text: str | None) -> list[str]:
    """Publicly visible email addresses, lowercased and de-duplicated."""
    if not text:
        return []
    emails: list[str] = []
    for match in EMAIL_RE.findall(text):
        address = match.lower()
        if address not in emails:
            emails.append(address)
    return emails


def extract_organizations(text: str | None) -> list[str]:
    """Organization names referenced in free text.

    Conservative by design: only capitalized names following "at"/"@" are
    returned, and the result is weak evidence worth few points.
    """
    if not text:
        return []
    organizations: list[str] = []
    for match in ORGANISATION_RE.finditer(text):
        name = " ".join(match.group("org").split()).strip(" .")
        head = name.split()[0].lower() if name else ""
        if not name or head in _ORG_STOPWORDS:
            continue
        if head in MENTION_WORDS or head in _TLD_LIKE:
            continue
        if name not in organizations:
            organizations.append(name)
    return organizations


def extract_references(
    text: str | None = None, links: list[str] | None = None
) -> list[Reference]:
    """Find every account reference in a bio and its link list.

    Structured links are parsed first (they are unambiguous), then free-text
    mentions such as ``Threads: @alice_dev``.  Results are de-duplicated on
    ``(platform, identifier)``, keeping the strongest observation.
    """
    references: list[Reference] = []
    seen: set[tuple[str, str]] = set()

    def add(reference: Reference) -> None:
        if reference.key in seen:
            return
        seen.add(reference.key)
        references.append(reference)

    for url in list(links or []) + extract_urls(text):
        parsed = parse_profile_url(url)
        if parsed:
            platform, identifier = parsed
            add(
                Reference(
                    platform=platform,
                    identifier=identifier,
                    url=normalize_url(url),
                    context=url,
                    explicit=True,
                )
            )

    if not text:
        return references

    url_spans = [match.span() for match in URL_RE.finditer(text)]
    for match in MENTION_RE.finditer(text):
        if any(start <= match.start() < end for start, end in url_spans):
            continue
        # Trailing sentence punctuation is not part of a handle:
        # "Threads: @alice_dev." refers to @alice_dev.
        handle = match.group("handle").strip("._-")
        platform = normalize_platform(MENTION_WORDS[match.group("word").lower()])
        lowered = handle.lower()
        if platform is None or lowered in RESERVED_PATHS or lowered in _TLD_LIKE:
            continue
        if lowered.startswith(("http", "www", ".", "-", "_")):
            continue
        try:
            identifier = normalize_username(handle)
        except NormalizationError:
            continue
        add(
            Reference(
                platform=platform,
                identifier=identifier,
                url=None,
                context=" ".join(match.group(0).split()),
                explicit=True,
            )
        )
    return references


def extract_websites(text: str | None = None, links: list[str] | None = None) -> list[str]:
    """Non-social website URLs referenced by a profile, normalized."""
    websites: list[str] = []
    for url in list(links or []) + extract_urls(text):
        normalized = normalize_url(url)
        if not normalized or detect_platform(normalized) is not None:
            continue
        if normalized not in websites:
            websites.append(normalized)
    return websites
