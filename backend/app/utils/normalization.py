"""Normalization primitives for identifiers, URLs, domains and platforms.

Normalization is deliberately conservative: it folds case and strips decoration
(``@``, ``www.``, trailing slashes, tracking parameters) but never rewrites
meaningful characters.  ``alice.dev``, ``alice_dev`` and ``alice-dev`` stay
distinct identities, because on most platforms they are different people.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# ---------------------------------------------------------------------------
# Platform vocabulary
# ---------------------------------------------------------------------------

# Canonical platform key -> hostnames that identify it.  Adding a platform here
# teaches the URL parser to recognise it even before an adapter exists.
PLATFORM_HOSTS: dict[str, tuple[str, ...]] = {
    "instagram": ("instagram.com", "instagr.am"),
    "threads": ("threads.net", "threads.com"),
    "facebook": ("facebook.com", "fb.com", "fb.me"),
    "github": ("github.com",),
    "reddit": ("reddit.com", "redd.it"),
    "x": ("x.com", "twitter.com"),
    "linkedin": ("linkedin.com",),
    "youtube": ("youtube.com", "youtu.be"),
    "mastodon": ("mastodon.social", "fosstodon.org", "infosec.exchange"),
}

# Alternative spellings analysts (and profile pages) actually use.
PLATFORM_ALIASES: dict[str, str] = {
    "twitter": "x",
    "x.com": "x",
    "ig": "instagram",
    "insta": "instagram",
    "gram": "instagram",
    "fb": "facebook",
    "meta": "facebook",
    "gh": "github",
    "li": "linkedin",
    "yt": "youtube",
    "site": "website",
    "web": "website",
    "homepage": "website",
}

# Human-readable labels for the UI and evidence descriptions.
PLATFORM_LABELS: dict[str, str] = {
    "instagram": "Instagram",
    "threads": "Threads",
    "facebook": "Facebook",
    "github": "GitHub",
    "reddit": "Reddit",
    "x": "X",
    "linkedin": "LinkedIn",
    "youtube": "YouTube",
    "mastodon": "Mastodon",
    "website": "Website",
    "domain": "Domain",
    "email": "Email",
}

# Path segments that are never account identifiers.
RESERVED_PATHS: frozenset[str] = frozenset(
    {
        "p", "reel", "reels", "stories", "story", "explore", "accounts",
        "about", "privacy", "terms", "policies", "help", "profile.php",
        "pages", "groups", "watch", "share", "login", "log_in", "signup",
        "signin", "direct", "tv", "home", "search", "settings", "notifications",
        "r.php", "checkpoint", "legal", "developers", "business", "sitemap",
        "feed", "posts", "status", "i", "intent", "hashtag", "topics",
    }
)

# Query parameters that carry no identity information.
TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "utm_id", "fbclid", "gclid", "igshid", "igsh", "mc_cid", "mc_eid",
        "ref", "ref_src", "ref_url", "si", "s", "spm", "yclid", "_ga",
    }
)

USERNAME_RE = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")

# Schemes that are never fetchable web pages.
NON_WEB_SCHEMES = (
    "mailto:", "javascript:", "tel:", "data:", "file:", "ftp:", "ws:", "wss:",
    "sms:", "callto:",
)

# Separators platforms use interchangeably for the same person's handle.
SEPARATORS = (".", "_", "-")


class NormalizationError(ValueError):
    """Raised when an input cannot be normalized into a usable identifier."""


# ---------------------------------------------------------------------------
# Platforms
# ---------------------------------------------------------------------------


def normalize_platform(value: str | None) -> str | None:
    """Fold a platform name onto its canonical key (``twitter`` -> ``x``)."""
    if not value:
        return None
    key = value.strip().lower().lstrip("@")
    key = PLATFORM_ALIASES.get(key, key)
    return key or None


def platform_label(value: str | None) -> str:
    """Human-readable platform name for display and evidence text."""
    key = normalize_platform(value) or ""
    return PLATFORM_LABELS.get(key, key.title() if key else "Unknown")


# ---------------------------------------------------------------------------
# Usernames
# ---------------------------------------------------------------------------


def normalize_username(value: str | None) -> str:
    """Normalize an analyst-supplied identifier to a canonical username.

    Accepts bare handles, ``@handles`` and full profile URLs::

        @Alice_Dev                          -> alice_dev
        Alice_Dev                           -> alice_dev
        https://instagram.com/alice_dev/    -> alice_dev

    Raises :class:`NormalizationError` when nothing username-shaped remains.
    """
    if value is None:
        raise NormalizationError("an identifier is required")

    candidate = value.strip().strip('"').strip("'")
    if not candidate:
        raise NormalizationError("an identifier is required")

    if "://" in candidate or _looks_like_bare_profile_url(candidate):
        extracted = username_from_url(candidate)
        if extracted is None:
            raise NormalizationError(
                f"could not extract an account identifier from URL: {value!r}"
            )
        candidate = extracted

    candidate = candidate.strip().strip("/").lstrip("@").strip()
    candidate = candidate.split("?", 1)[0].split("#", 1)[0]
    # Separators are meaningful inside a handle but never at its edges.
    candidate = candidate.strip("._-").lower()

    if not USERNAME_RE.match(candidate):
        raise NormalizationError(f"invalid identifier: {value!r}")
    return candidate


def _looks_like_bare_profile_url(value: str) -> bool:
    """Detect ``instagram.com/alice`` style input written without a scheme."""
    head = value.split("/", 1)[0].lower()
    if "/" not in value:
        return False
    return any(
        head in (host, f"www.{host}")
        for hosts in PLATFORM_HOSTS.values()
        for host in hosts
    )


def username_from_url(url: str) -> str | None:
    """Return the first path segment of a URL that looks like an account name."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    for segment in parsed.path.split("/"):
        segment = segment.strip()
        if not segment:
            continue
        if segment.lower() in RESERVED_PATHS:
            return None
        # reddit.com/u/alice and reddit.com/user/alice
        if segment.lower() in ("u", "user", "users", "in", "c", "@"):
            continue
        return segment.lstrip("@")
    return None


def username_variants(username: str) -> list[str]:
    """Plausible spellings of a handle on another platform.

    ``alice_dev`` -> ``alice_dev``, ``alice.dev``, ``alice-dev``, ``alicedev``.
    These are guesses used for candidate generation only; they earn no score
    unless the correlation engine finds real evidence behind them.
    """
    variants = [username]
    if not any(sep in username for sep in SEPARATORS):
        return variants
    skeleton = username
    for sep in SEPARATORS:
        skeleton = skeleton.replace(sep, "\x00")
    for sep in SEPARATORS:
        variant = skeleton.replace("\x00", sep)
        if variant not in variants:
            variants.append(variant)
    collapsed = skeleton.replace("\x00", "")
    if collapsed and collapsed not in variants:
        variants.append(collapsed)
    return variants


def username_similarity(a: str, b: str) -> float:
    """Similarity of two usernames in ``[0.0, 1.0]``.

    Identical handles score ``1.0``.  Handles differing only by separators
    (``alice_dev`` vs ``alice.dev``) score high but never ``1.0``, so callers
    can keep "same username" and "similar username" as distinct evidence.
    """
    a, b = (a or "").lower().strip(), (b or "").lower().strip()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    stripped_a = re.sub(r"[._\-]", "", a)
    stripped_b = re.sub(r"[._\-]", "", b)
    if stripped_a and stripped_a == stripped_b:
        return 0.9
    # Digits are frequently the only thing distinguishing two real people
    # (alice98 vs alice22), so compare the alphabetic stems too but cap the
    # score below the separator-only case.
    return round(SequenceMatcher(None, a, b).ratio(), 3)


# ---------------------------------------------------------------------------
# URLs and domains
# ---------------------------------------------------------------------------


def normalize_domain(value: str | None, *, strip_www: bool = True) -> str | None:
    """Canonical host form: lowercase, no port, no trailing dot.

    ``strip_www`` also drops a leading ``www.``, which is what comparison and
    de-duplication want.  Pass ``strip_www=False`` when the result will be
    *requested*: ``www.example.com`` and ``example.com`` are different hosts,
    and rewriting one into the other sends a crawler into a redirect loop.
    """
    if not value:
        return None
    host = value.strip().lower()
    if "://" in host or "/" in host:
        host = urlparse(host if "://" in host else f"https://{host}").netloc
    host = host.split("@")[-1].split(":")[0].strip().rstrip(".")
    if strip_www and host.startswith("www."):
        host = host[4:]
    return host or None


def normalize_url(value: str | None, *, canonical: bool = True) -> str | None:
    """Canonicalize a URL.

    Always: lowercases the scheme and host, drops the fragment, tracking
    parameters and default ports.  Returns ``None`` for anything that is not a
    usable http(s) URL.

    ``canonical=True`` (the default) additionally produces the *comparison*
    form by dropping ``www.`` and a trailing slash - what de-duplication and
    identity want.  ``canonical=False`` preserves the host and path exactly, and
    is what a URL about to be **requested** needs: ``www.example.com`` and
    ``example.com``, like ``/psf`` and ``/psf/``, can be different resources,
    and rewriting one into the other walks a crawler into a redirect loop.
    """
    if not value:
        return None
    raw = value.strip().strip("<>").rstrip(".,);:!'\"")
    if not raw:
        return None
    if raw.lower().startswith(NON_WEB_SCHEMES):
        return None
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        return None
    host = normalize_domain(parsed.netloc, strip_www=canonical)
    if not host or "." not in host:
        return None

    path = parsed.path or ""
    if canonical:
        if path.endswith("/") and path != "/":
            path = path.rstrip("/")
        if path == "/":
            path = ""

    query = urlencode(
        [
            (key, val)
            for key, val in parse_qsl(parsed.query, keep_blank_values=False)
            if key.lower() not in TRACKING_PARAMS
        ]
    )
    return urlunparse((parsed.scheme.lower(), host, path, "", query, ""))


def url_host(value: str | None) -> str | None:
    """The normalized host of a URL, or ``None`` if it has none."""
    if not value:
        return None
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return normalize_domain(parsed.netloc)


# ---------------------------------------------------------------------------
# Free text
# ---------------------------------------------------------------------------


def normalize_display_name(value: str | None) -> str | None:
    """Collapse whitespace and fold case for display-name comparison."""
    if not value:
        return None
    collapsed = " ".join(value.split()).strip().lower()
    return collapsed or None


_WORD_RE = re.compile(r"[a-z0-9]+")

# Words too common in profile bios to carry identity signal.
_STOPWORDS = frozenset(
    [
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "he", "her", "his", "i",
        "in", "is", "it", "its", "me", "my", "of", "on", "or", "our", "she", "that", "the",
        "their", "they", "this", "to", "was", "we", "were", "with", "you", "your", "com",
        "http", "https", "www", "dm", "via"
    ]
)


def text_tokens(value: str | None) -> set[str]:
    """Lowercase content words of a piece of free text."""
    if not value:
        return set()
    return {
        word
        for word in _WORD_RE.findall(value.lower())
        if len(word) > 2 and word not in _STOPWORDS
    }


def text_similarity(a: str | None, b: str | None) -> float:
    """Jaccard overlap of the content words in two texts, in ``[0.0, 1.0]``."""
    tokens_a, tokens_b = text_tokens(a), text_tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    union = tokens_a | tokens_b
    return round(len(tokens_a & tokens_b) / len(union), 3) if union else 0.0


def normalize_location(value: str | None) -> str | None:
    """Canonical location string for equality/contradiction comparison."""
    if not value:
        return None
    cleaned = " ".join(value.replace(",", " ").split()).strip().lower()
    return cleaned or None
