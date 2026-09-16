"""Video platform adapters.

YouTube is the only one here so far. Its public channel pages serve an Open
Graph card to anonymous readers, and - unusually for a platform this size -
its robots.txt permits reading them: the Disallow list covers ``/api/``,
``/results``, ``/watch_*``, ``/feeds/`` and ``/youtubei/``, but not
``/@handle``, ``/channel/``, ``/c/`` or ``/user/``. So this one belongs in the
permitted column alongside GitHub and Mastodon rather than with Instagram and
Facebook.

Nothing here reads videos, comments, subscriber lists or the Data API. A
channel page is a public web page and is treated as one.
"""

from __future__ import annotations

import re

from .base import ObservedProfile, OpenGraphProfileAdapter, SourceCategory, parse_meta

#: The canonical channel id, which YouTube publishes as og:url even when the
#: page was reached by handle.
#:
#: Worth capturing because it is the only stable identifier a channel has: a
#: handle can be changed by its owner, ``UC...`` cannot. Recorded in metadata
#: rather than used as the entity key, because the handle is what an analyst
#: searched for and what they will recognise.
CHANNEL_ID_RE = re.compile(r"UC[\w-]{20,}")

#: The same id as it appears inside a canonical channel URL.
CHANNEL_URL_RE = re.compile(r"/channel/(UC[\w-]{20,})")

#: What YouTube serves when a handle has no channel behind it.
#:
#: It answers 404 for a missing handle, so this is belt and braces rather than
#: the load-bearing check Telegram needs - but the generic card does appear on
#: some interstitials, and a profile named "YouTube" is never a person.
GENERIC_TITLES = frozenset({"youtube", "youtube video", "before you continue"})


class YouTubeAdapter(OpenGraphProfileAdapter):
    """Public YouTube channels, read from the channel page's Open Graph card."""

    platform = "youtube"
    name = "YouTube"
    category = SourceCategory.SOCIAL
    url_template = "https://www.youtube.com/@{identifier}"
    generic_titles = GENERIC_TITLES
    probe_present = "youtube"
    # A login wall is not how YouTube refuses a missing channel; it 404s -
    # which is also what makes the canonical check below safe to skip.
    report_login_wall = False
    #: /@veritasium advertises its canonical as /channel/UCHnyfMqiRRG1u-2Ms...
    #: The handle and the id share nothing, so comparing them rejects every
    #: real channel. Safe here only because a missing handle 404s rather than
    #: returning a generic 200 page.
    canonical_is_opaque = True

    def profile_url(self, identifier: str) -> str:
        """Channel ids and handles live at different paths.

        ``/@UCxxxx`` is not a channel; ``/channel/UCxxxx`` is. A link found in
        somebody's bio is as likely to be one form as the other.
        """
        if CHANNEL_ID_RE.fullmatch(identifier):
            return f"https://www.youtube.com/channel/{identifier}"
        return self.url_template.format(identifier=identifier)

    #: Measured, not guessed. A channel page is 1.4-2.8MB of embedded player
    #: state, which is past the 2MB refusal limit for the larger channels -
    #: @veritasium failed outright before this. The Open Graph tags sit at
    #: roughly 768-772KB on every channel checked, so a megabyte captures them
    #: with headroom and leaves the rest of the document on YouTube's side of
    #: the wire.
    head_bytes = 1_000_000

    def parse_profile(
        self, identifier: str, html: str, url: str
    ) -> ObservedProfile | None:
        profile = super().parse_profile(identifier, html, url)
        if profile is None:
            return None
        meta = parse_meta(html)
        canonical = meta.get("og:url") or ""
        if match := CHANNEL_URL_RE.search(canonical):
            profile.metadata["channel_id"] = match.group(1)
            profile.metadata["channel_url"] = canonical
        return profile
