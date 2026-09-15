"""Music-platform source adapters.

Music platforms are thin ground for public, permitted lookups: Genius,
MusicBrainz and Mixcloud all disallow crawling, and Spotify requires a token.
SoundCloud and Last.fm permit it and serve Open Graph cards, so both read
through the shared card parser.

Both are HTML rather than JSON, which makes them heavier than the developer
sources; the response-size limit and the per-host delay apply as usual.
"""

from __future__ import annotations

import re
from typing import Any

from .base import (
    JsonProfileAdapter,
    ObservedProfile,
    OpenGraphProfileAdapter,
    SourceCategory,
    enrich_profile,
)

#: Apostrophe forms seen in the wild. Last.fm renders a typographic right
#: single quote, so a pattern matching only the ASCII form misses every
#: profile on the site.
APOSTROPHE = "['’ʼ´]"

# "Listen to music from RJ's library (151,481 tracks played). RJ's top ar..."
LASTFM_STATS_RE = re.compile(
    rf"^Listen to music from .*?{APOSTROPHE}s library"
    r"\s*\(([\d,]+)\s+tracks? played\)\.\s*",
    re.IGNORECASE,
)

# "RJ's Music Profile | Last.fm"
LASTFM_TITLE_RE = re.compile(
    rf"{APOSTROPHE}s\s+Music\s+Profile\s*\|\s*Last\.fm\s*$", re.IGNORECASE
)

# "Listen to octobersveryown | SoundCloud is an audio platform that lets..."
SOUNDCLOUD_BOILERPLATE_RE = re.compile(
    r"\s*\|\s*SoundCloud is an audio platform.*$", re.IGNORECASE | re.DOTALL
)


class SoundCloudAdapter(OpenGraphProfileAdapter):
    """SoundCloud, via the public Open Graph card on a profile page."""

    platform = "soundcloud"
    name = "SoundCloud"
    category = SourceCategory.MUSIC
    url_template = "https://soundcloud.com/{identifier}"
    generic_titles = frozenset({"soundcloud", "discover", "stream"})
    probe_present = "octobersveryown"

    def extract_bio(self, meta: dict[str, str], html: str) -> str | None:
        """Return the artist's own text, not SoundCloud's pitch for itself.

        Every profile description ends with the same paragraph about what
        SoundCloud is; left in place, any two artists would score a spurious
        SIMILAR_BIO against each other.
        """
        value = meta.get("og:description") or meta.get("description")
        if not value:
            return None
        trimmed = SOUNDCLOUD_BOILERPLATE_RE.sub("", value).strip()
        # What remains for a bare profile is "Listen to <handle>", which says
        # nothing about the person.
        if trimmed.lower().startswith("listen to ") and len(trimmed) < 40:
            return None
        return trimmed or None


class LastFmAdapter(OpenGraphProfileAdapter):
    """Last.fm listening profiles, via the public Open Graph card."""

    platform = "lastfm"
    name = "Last.fm"
    category = SourceCategory.MUSIC
    url_template = "https://www.last.fm/user/{identifier}"
    generic_titles = frozenset({"last.fm", "music profile | last.fm"})
    probe_present = "rj"

    def extract_display_name(self, title: str) -> str | None:
        """``RJ's Music Profile | Last.fm`` -> ``RJ``."""
        cleaned = LASTFM_TITLE_RE.sub("", title).strip()
        return cleaned or super().extract_display_name(title)

    def extract_bio(self, meta: dict[str, str], html: str) -> str | None:
        """Drop the play-count preamble Last.fm prefixes to every description."""
        value = meta.get("og:description") or meta.get("description")
        if not value:
            return None
        trimmed = LASTFM_STATS_RE.sub("", value).strip()
        return trimmed or None

    def extract_metadata(self, meta: dict[str, str], html: str) -> dict[str, Any]:
        """The scrobble count, as published on the profile."""
        match = LASTFM_STATS_RE.match(
            meta.get("og:description") or meta.get("description") or ""
        )
        return {"tracks_played": match.group(1)} if match else {}


class MixcloudAdapter(JsonProfileAdapter):
    """Mixcloud, via its public user API.

    The city and country fields are the interesting part: a location is
    evidence the correlation engine can contradict as well as corroborate,
    and few music platforms publish one at all.
    """

    platform = "mixcloud"
    name = "Mixcloud"
    category = SourceCategory.MUSIC
    api_template = "https://api.mixcloud.com/{identifier}/"
    url_template = "https://www.mixcloud.com/{identifier}/"
    probe_present = "spartacus"

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        if not isinstance(payload, dict) or not payload.get("username"):
            return None
        handle = str(payload["username"])

        pictures = payload.get("pictures")
        avatar = None
        if isinstance(pictures, dict):
            # Largest square first; the small ones are unreadable thumbnails.
            for key in ("extra_large", "large", "medium", "thumbnail"):
                if pictures.get(key):
                    avatar = pictures[key]
                    break

        location = ", ".join(
            part for part in (payload.get("city"), payload.get("country")) if part
        )
        return enrich_profile(
            ObservedProfile(
                platform=self.platform,
                identifier=handle,
                name=f"@{handle}",
                url=payload.get("url") or url,
                display_name=(payload.get("name") or "").strip() or None,
                bio=(payload.get("biog") or "").strip() or None,
                avatar_url=avatar,
                location=location or None,
                source=self.platform,
                metadata={
                    key: payload[key]
                    for key in ("follower_count", "cloudcast_count", "created_time")
                    if payload.get(key) is not None
                },
            )
        )
