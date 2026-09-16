"""The YouTube adapter, and the two things about YouTube that break assumptions.

A channel page is an Open Graph card wrapped in 1.4-2.8MB of embedded player
state, and it advertises its canonical URL as a channel id rather than the
handle that was asked for. Both of those defeat machinery that works fine for
every other Open Graph source, so both are pinned here.
"""

from __future__ import annotations

import pytest

from app.sources.video import YouTubeAdapter
from app.utils.url_parser import parse_profile_url

CHANNEL_HTML = """
<html><head>
<meta property="og:title" content="Veritasium">
<meta property="og:description" content="An element of truth. Also on https://twitter.com/veritasium">
<meta property="og:image" content="https://yt3.googleusercontent.com/abc">
<meta property="og:url" content="https://www.youtube.com/channel/UCHnyfMqiRRG1u-2MsSQLbXA">
</head><body></body></html>
"""


def test_a_channel_page_parses_into_a_profile() -> None:
    adapter = YouTubeAdapter()

    profile = adapter.parse_profile(
        "veritasium", CHANNEL_HTML, "https://www.youtube.com/@veritasium"
    )

    assert profile is not None
    assert profile.display_name == "Veritasium"
    assert profile.avatar_url
    assert profile.metadata["channel_id"] == "UCHnyfMqiRRG1u-2MsSQLbXA"


def test_the_canonical_channel_id_does_not_reject_the_page() -> None:
    """The failure that made every real channel look like a miss.

    Open Graph sources are verified by comparing the page's advertised
    canonical against the handle that was requested - which catches the
    interstitials Meta serves for unknown handles. YouTube canonicalises
    /@veritasium to /channel/UCHnyfMqiRRG1u-2MsSQLbXA, and the two strings
    share nothing, so that check refused every channel that existed.

    Skipping it is safe only because YouTube 404s a handle with no channel
    behind it, which the adapter relies on instead.
    """
    assert YouTubeAdapter.canonical_is_opaque is True

    profile = YouTubeAdapter().parse_profile(
        "veritasium", CHANNEL_HTML, "https://www.youtube.com/@veritasium"
    )

    assert profile is not None


def test_a_bio_link_still_becomes_a_reference() -> None:
    """The pivot: what the channel says about its accounts elsewhere."""
    profile = YouTubeAdapter().parse_profile(
        "veritasium", CHANNEL_HTML, "https://www.youtube.com/@veritasium"
    )

    assert ("x", "veritasium") in {(r.platform, r.identifier) for r in profile.references}


def test_only_the_head_of_a_channel_page_is_read() -> None:
    """A channel page is past the 2MB refusal limit for the larger channels.

    The Open Graph tags sit at roughly 768-772KB on every channel measured, so
    a megabyte captures them with headroom. Without this the adapter did not
    fail gracefully - @veritasium was refused outright as TOO_LARGE.
    """
    assert YouTubeAdapter.head_bytes == 1_000_000


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://youtube.com/@veritasium", ("youtube", "veritasium")),
        ("https://www.youtube.com/@MrBeast", ("youtube", "mrbeast")),
        ("https://youtube.com/c/Veritasium", ("youtube", "veritasium")),
        ("https://youtube.com/user/1veritasium", ("youtube", "1veritasium")),
        # Case is preserved for a channel id: it is not a handle, and folding
        # it produces a string that resolves to nothing.
        (
            "https://youtube.com/channel/UCHnyfMqiRRG1u-2MsSQLbXA",
            ("youtube", "UCHnyfMqiRRG1u-2MsSQLbXA"),
        ),
    ],
)
def test_channel_urls_parse(url: str, expected: tuple[str, str]) -> None:
    assert parse_profile_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        # These parsed as channels named "results" and "playlist" before
        # YouTube got its own reserved-path list - the same fault as a help
        # centre article parsing as an Instagram account.
        "https://www.youtube.com/results?search_query=osint",
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/shorts/abc123",
        "https://www.youtube.com/music",
    ],
)
def test_non_profile_urls_are_not_channels(url: str) -> None:
    assert parse_profile_url(url) is None


def test_a_channel_id_is_fetched_at_its_own_path() -> None:
    """/@UCxxxx is not a channel; /channel/UCxxxx is."""
    adapter = YouTubeAdapter()

    assert adapter.profile_url("UCHnyfMqiRRG1u-2MsSQLbXA").endswith(
        "/channel/UCHnyfMqiRRG1u-2MsSQLbXA"
    )
    assert adapter.profile_url("veritasium").endswith("/@veritasium")
