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
    "bluesky": ("bsky.app", "bsky.social"),
    "devto": ("dev.to",),
    "keybase": ("keybase.io",),
    "hackernews": ("news.ycombinator.com",),
    "pypi": ("pypi.org",),
    "telegram": ("t.me", "telegram.me"),
    "huggingface": ("huggingface.co",),
    "crates": ("crates.io",),
    "dockerhub": ("hub.docker.com",),
    "stackoverflow": ("stackoverflow.com", "stackexchange.com"),
    "launchpad": ("launchpad.net",),
    "steam": ("steamcommunity.com",),
    "soundcloud": ("soundcloud.com",),
    "lastfm": ("last.fm", "lastfm.com"),
    "codewars": ("codewars.com",),
    "scratch": ("scratch.mit.edu",),
    "duolingo": ("duolingo.com",),
    "medium": ("medium.com",),
    # Link-in-bio pages: a whole page of somebody's other accounts.
    "linktree": ("linktr.ee", "linktree.com"),
    "solo": ("solo.to",),
    "biolink": ("bio.link",),
    "gravatar": ("gravatar.com", "en.gravatar.com"),
    "chess": ("chess.com",),
    "lobsters": ("lobste.rs",),
    # No adapter reads these - they wall off anonymous access - but a link to
    # one is still a lead worth putting on the board as an unread reference.
    "twitch": ("twitch.tv", "m.twitch.tv"),
    "tiktok": ("tiktok.com",),
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
    "bsky": "bluesky",
    "dev": "devto",
    "dev.to": "devto",
    "hn": "hackernews",
    "ycombinator": "hackernews",
    "kb": "keybase",
    "tg": "telegram",
    "hf": "huggingface",
    "so": "stackoverflow",
    "stackexchange": "stackoverflow",
    "docker": "dockerhub",
    "sc": "soundcloud",
    "last.fm": "lastfm",
    "lastfm.com": "lastfm",
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
    "bluesky": "Bluesky",
    "devto": "DEV",
    "keybase": "Keybase",
    "hackernews": "Hacker News",
    "pypi": "PyPI",
    "telegram": "Telegram",
    "huggingface": "Hugging Face",
    "crates": "crates.io",
    "dockerhub": "Docker Hub",
    "stackoverflow": "Stack Overflow",
    "launchpad": "Launchpad",
    "steam": "Steam",
    "soundcloud": "SoundCloud",
    "lastfm": "Last.fm",
    "codewars": "Codewars",
    "scratch": "Scratch",
    "duolingo": "Duolingo",
    "medium": "Medium",
    "linktree": "Linktree",
    "solo": "solo.to",
    "biolink": "bio.link",
    "gravatar": "Gravatar",
    "chess": "Chess.com",
    "lobsters": "Lobsters",
    "twitch": "Twitch",
    "tiktok": "TikTok",
    "username": "Username",
    "organization": "Organization",
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

#: Generic top-level domains common enough to be worth recognising by name.
#:
#: Every country-code TLD is exactly two letters, so those are matched by
#: length instead of being listed. The point of the set is to tell a domain
#: from a dotted handle: "alice.dev" is a site, "firstname.lastname" is a
#: person's handle, and the only thing separating them is whether the last
#: label is a real TLD.
KNOWN_GTLDS: frozenset[str] = frozenset(
    {
        "com", "net", "org", "edu", "gov", "mil", "int", "info", "biz",
        "name", "pro", "mobi", "asia", "tel", "xxx", "aero", "coop", "jobs",
        "museum", "travel", "cat", "post",
        # Newer generics people actually use for personal sites.
        "app", "art", "bio", "blog", "cloud", "club", "codes", "dev", "digital",
        "design", "email", "fyi", "games", "gg", "guru", "host", "icu", "ink",
        "io", "link", "live", "ltd", "media", "network", "news", "ninja",
        "online", "page", "photo", "photography", "pics", "press", "pub",
        "rocks", "run", "shop", "show", "site", "social", "software", "space",
        "store", "studio", "style", "tech", "today", "tools", "top", "tv",
        "wiki", "work", "works", "world", "wtf", "xyz", "zone",
    }
)


def looks_like_domain(value: str | None) -> bool:
    """Whether a dotted string is a hostname rather than a handle.

    ``alice.dev`` is a domain; ``firstname.lastname`` is a username that
    happens to contain a dot. Treating every dotted string as a hostname sends
    the crawler looking for a site that does not exist and loses the account
    that does.
    """
    if not value:
        return False
    labels = value.strip().strip(".").lower().split(".")
    if len(labels) < 2 or not all(labels):
        return False
    if not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", part) for part in labels):
        return False
    tld = labels[-1]
    # Two letters is a country code; anything longer has to be a known generic.
    return (len(tld) == 2 and tld.isalpha()) or tld in KNOWN_GTLDS

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
    # A trailing dot or hyphen is punctuation picked up during extraction
    # ("Threads: @alice_dev." -> "alice_dev"). An underscore is not: "_alice"
    # and "alice_" are handles in their own right on most platforms, and
    # stripping one silently queries a different account.
    candidate = candidate.strip(".-").lower()

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


#: Hosts that two people can both link to without it meaning anything.
#:
#: A shared *personal* domain is strong evidence - it is a thing one person
#: owns.  A shared link shortener, mailbox provider, marketplace or
#: link-in-bio service is not: half the internet links to ``linktr.ee``.
#: Counting those as a shared website is a straightforward way to manufacture
#: false positives, so they earn nothing.
NON_IDENTIFYING_HOSTS: frozenset[str] = frozenset(
    {
        # Link shorteners and redirectors.
        "amzn.to", "bit.ly", "buff.ly", "cutt.ly", "goo.gl", "is.gd",
        "lnkd.in", "ow.ly", "rb.gy", "shorturl.at", "t.co", "tinyurl.com",
        # Link-in-bio services.
        "allmylinks.com", "beacons.ai", "carrd.co", "linkin.bio",
        "linktr.ee", "lnk.bio", "milkshake.app", "solo.to", "taplink.cc",
        # Mailbox providers.
        "aol.com", "gmail.com", "googlemail.com", "hotmail.com", "icloud.com",
        "mail.com", "outlook.com", "proton.me", "protonmail.com", "yahoo.com",
        "yandex.ru", "zoho.com",
        # Generic destinations and storage.
        "amazon.com", "discord.gg", "docs.google.com", "drive.google.com",
        "google.com", "paypal.me", "wa.me", "youtu.be",
    }
)


def is_identifying_host(value: str | None) -> bool:
    """True when a host is specific enough to tie two profiles together.

    Used by the correlation engine before it credits a shared website.
    """
    domain = normalize_domain(value)
    if not domain:
        return False
    if domain in NON_IDENTIFYING_HOSTS:
        return False
    # A subdomain of a generic host is just as generic: sites.google.com/x.
    return not any(
        domain.endswith(f".{host}") for host in NON_IDENTIFYING_HOSTS
    )


def identity_key(identifier: str | None) -> str:
    """The form two observations of the same thing must agree on.

    Handles are case-insensitive on every platform in the catalogue:
    ``PrashantRanjitkar`` and ``prashantranjitkar`` are one Instagram account,
    not two.  Keying entities on the raw identifier recorded them separately,
    which split one account into two nodes, doubled its relationships and made
    the same person look like a pair of matching strangers.

    Domains are case-insensitive by definition, and website identities are
    already lowercased upstream by ``website_identity``, so folding is correct
    for every identifier that currently reaches an entity.  Email local parts
    are case-sensitive in the RFC and insensitive in practice at every real
    provider; folding matches what an investigator means.

    If a source is ever added whose identifiers genuinely are case-sensitive,
    this is the single place that has to learn about it.
    """
    return (identifier or "").strip().casefold()


def name_token(value: str | None) -> str:
    """A name flattened for comparison: letters and digits only.

    ``beau.lebens``, ``beau_lebens`` and ``BeauLebens`` all become
    ``beaulebens``, so a handle written three ways compares equal.
    """
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def domain_belongs_to(domain: str | None, tokens: set[str]) -> bool:
    """Whether a domain is named after one of these identities.

    ``beaulebens.com`` beside an account called ``beaulebens`` is that
    person's own site; ``businessinsider.com`` beside the same account is a
    story they linked to. Offline, nothing else separates the two, and the
    difference decides whether a shared link means anything at all.

    Matched on the first label, exactly, except for a trailing run of digits
    on either side - ``alice.dev`` is the personal site of ``alice_98``, and
    a number stuck on the end of a handle is the commonest way somebody
    writes the same name twice.

    Anything looser fails badly.  Substring matching in either direction
    reads as the obvious generalisation, but given a few dozen discovered
    handles some token is a substring of nearly any domain, and the rule ends
    up announcing that ``apps.apple.com`` is somebody's personal site.
    """
    flat = name_token((domain or "").split(".")[0])
    # Two or three characters match far too much to mean anything.
    if len(flat) < 4:
        return False
    if flat in tokens:
        return True
    return any(
        (token.startswith(flat) and token[len(flat) :].isdigit())
        or (flat.startswith(token) and flat[len(token) :].isdigit() and len(token) >= 4)
        for token in tokens
    )
