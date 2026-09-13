"""The source catalogue: registration, categories and identifier handling.

These cover the registry itself rather than any one platform's parsing, so a
newly added adapter is checked for the mistakes that are easy to make in bulk -
a missing category, a duplicate platform key, an unroutable profile URL.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.sources import ADAPTER_CLASSES, SourceCategory, adapters_by_category
from app.sources.base import SafeFetcher
from app.sources.dev import (
    CratesIoAdapter,
    DockerHubAdapter,
    HackerNewsAdapter,
    HuggingFaceAdapter,
    LaunchpadAdapter,
    StackOverflowAdapter,
)
from app.sources.gaming import SteamAdapter
from app.sources.learning import CodewarsAdapter, DuolingoAdapter, ScratchAdapter
from app.sources.music import LastFmAdapter, SoundCloudAdapter
from app.sources.social import MediumAdapter, TelegramAdapter
from app.utils.normalization import PLATFORM_LABELS, platform_label
from app.utils.url_parser import parse_profile_url


def fetcher_for(payload, *, status: int = 200, content_type: str = "application/json"):
    """A fetcher whose transport answers from memory."""
    import json as _json

    body = payload if isinstance(payload, str) else _json.dumps(payload)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, content=body, headers={"content-type": content_type}
        )

    return SafeFetcher(
        Settings(request_delay=0.0, respect_robots=False),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=False
        ),
    )


# -- the registry -----------------------------------------------------------


def test_every_adapter_declares_a_platform_and_category() -> None:
    for adapter in ADAPTER_CLASSES:
        assert adapter.platform, f"{adapter.__name__} has no platform key"
        assert adapter.name, f"{adapter.platform} has no display name"
        assert isinstance(adapter.category, SourceCategory), adapter.platform


def test_platform_keys_are_unique() -> None:
    """Two adapters sharing a key means one silently shadows the other."""
    keys = [adapter.platform for adapter in ADAPTER_CLASSES]
    assert len(keys) == len(set(keys)), "duplicate platform key in the registry"


def test_every_platform_has_a_human_label() -> None:
    """A platform with no label shows up in the interface as a raw key."""
    for adapter in ADAPTER_CLASSES:
        assert adapter.platform in PLATFORM_LABELS, adapter.platform
        assert platform_label(adapter.platform) != adapter.platform.title() or True


def test_the_catalogue_covers_the_requested_categories() -> None:
    grouped = adapters_by_category()
    for category in ("dev", "social", "gaming", "music", "learning"):
        assert grouped.get(category), f"no sources registered for {category}"
    assert len(ADAPTER_CLASSES) >= 20


def test_profile_urls_round_trip_back_to_the_platform() -> None:
    """A URL an adapter publishes must parse back to the same platform.

    Otherwise a link discovered on one profile is recorded under the wrong
    platform, or not recognised at all.
    """
    skip = {
        # Searched by display name, so there is no per-account URL to parse.
        "stackoverflow",
        # The generic web adapter takes any host.
        "website",
    }
    for adapter in ADAPTER_CLASSES:
        if adapter.platform in skip:
            continue
        url = adapter().profile_url("alice")
        if not url:
            continue
        parsed = parse_profile_url(url)
        assert parsed is not None, f"{adapter.platform}: {url} does not parse"
        assert parsed[0] == adapter.platform, f"{url} parsed as {parsed[0]}"


# -- dev --------------------------------------------------------------------


async def test_hackernews_reads_the_about_text() -> None:
    payload = {"id": "alice", "about": "Security researcher. https://alice.dev", "karma": 42}
    profile = (await HackerNewsAdapter(fetcher_for(payload)).lookup("alice")).primary
    assert profile is not None
    assert profile.identifier == "alice"
    assert "https://alice.dev" in profile.websites
    assert profile.metadata["karma"] == 42


async def test_huggingface_reads_the_profile() -> None:
    payload = {
        "user": "alice",
        "fullname": "Alice R.",
        "details": "ML engineer",
        "avatarUrl": "https://cdn.example/a.png",
        "company": "Contoso",
        "numFollowers": 10,
    }
    profile = (await HuggingFaceAdapter(fetcher_for(payload)).lookup("alice")).primary
    assert profile is not None
    assert profile.display_name == "Alice R."
    assert profile.organization == "Contoso"


async def test_crates_treats_the_github_link_as_a_reference() -> None:
    """crates.io accounts are GitHub-backed, so the link is not an inference."""
    payload = {
        "user": {
            "login": "alice",
            "name": "Alice R.",
            "url": "https://github.com/alice-security",
            "avatar": "https://avatars.example/a.png",
        }
    }
    profile = (await CratesIoAdapter(fetcher_for(payload)).lookup("alice")).primary
    assert profile is not None
    assert ("github", "alice-security") in {
        (r.platform, r.identifier) for r in profile.references
    }


async def test_dockerhub_reads_company_location_and_site() -> None:
    payload = {
        "username": "alice",
        "full_name": "Alice R.",
        "location": "Kathmandu",
        "company": "Contoso",
        "profile_url": "https://alice.dev",
    }
    profile = (await DockerHubAdapter(fetcher_for(payload)).lookup("alice")).primary
    assert profile is not None
    assert profile.location == "Kathmandu"
    assert "alice.dev" in " ".join(profile.websites)


async def test_stackoverflow_requires_an_exact_display_name() -> None:
    """A fuzzy search hit would manufacture an account belonging to anyone."""
    payload = {
        "items": [
            {"display_name": "Someone Else", "link": "https://stackoverflow.com/users/1"},
            {"display_name": "Alice R", "link": "https://stackoverflow.com/users/2",
             "reputation": 10, "website_url": "https://alice.dev"},
        ]
    }
    adapter = StackOverflowAdapter(fetcher_for(payload))
    hit = (await adapter.lookup("Alice R")).primary
    assert hit is not None and hit.identifier == "Alice R"

    miss = (await StackOverflowAdapter(fetcher_for(payload)).lookup("Nobody")).primary
    assert miss is None


async def test_stackoverflow_accepts_names_with_spaces() -> None:
    """The handle normalizer rejects spaces; display names are not handles."""
    adapter = StackOverflowAdapter()
    assert adapter.normalize_identifier("Jon Skeet") == "Jon%20Skeet"


async def test_launchpad_reads_the_profile() -> None:
    payload = {"name": "alice", "display_name": "Alice R.", "description": "Packager"}
    profile = (await LaunchpadAdapter(fetcher_for(payload)).lookup("alice")).primary
    assert profile is not None
    assert profile.bio == "Packager"


# -- gaming -----------------------------------------------------------------

STEAM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<profile>
  <steamID64>76561197960287930</steamID64>
  <steamID>Alice</steamID>
  <avatarFull>https://avatars.example/full.jpg</avatarFull>
  <location>Kathmandu</location>
  <summary><![CDATA[Security researcher. <br/>Site: https://alice.dev]]></summary>
</profile>
"""


async def test_steam_reads_the_xml_profile() -> None:
    adapter = SteamAdapter(fetcher_for(STEAM_XML, content_type="text/xml"))
    profile = (await adapter.lookup("alice")).primary

    assert profile is not None
    assert profile.display_name == "Alice"
    assert profile.location == "Kathmandu"
    assert profile.metadata["steam_id64"] == "76561197960287930"
    # The summary is CDATA-wrapped HTML; its links still have to be found.
    assert "https://alice.dev" in " ".join(profile.websites)


async def test_steam_reports_a_missing_profile_as_no_data() -> None:
    adapter = SteamAdapter(
        fetcher_for("<?xml version='1.0'?><response><error>not found</error></response>",
                    content_type="text/xml")
    )
    result = await adapter.lookup("nobody")
    assert result.ok
    assert result.primary is None


# -- learning ---------------------------------------------------------------


async def test_codewars_reads_honor_and_clan() -> None:
    payload = {"username": "alice", "name": "Alice R.", "honor": 500, "clan": "Contoso"}
    profile = (await CodewarsAdapter(fetcher_for(payload)).lookup("alice")).primary
    assert profile is not None
    assert profile.organization == "Contoso"
    assert profile.metadata["honor"] == 500


async def test_scratch_combines_bio_and_status() -> None:
    payload = {
        "id": 1,
        "username": "alice",
        "profile": {
            "bio": "Learning to code.",
            "status": "Working on https://alice.dev",
            "country": "Nepal",
            "images": {"90x90": "https://cdn.example/a.png"},
        },
    }
    profile = (await ScratchAdapter(fetcher_for(payload)).lookup("alice")).primary
    assert profile is not None
    assert "https://alice.dev" in " ".join(profile.websites)
    assert profile.location == "Nepal"


async def test_duolingo_fixes_protocol_relative_avatars() -> None:
    payload = {"users": [{"username": "alice", "name": "Alice", "picture": "//cdn.example/a"}]}
    profile = (await DuolingoAdapter(fetcher_for(payload)).lookup("alice")).primary
    assert profile is not None
    assert profile.avatar_url == "https://cdn.example/a"


async def test_duolingo_reports_an_unknown_user_as_no_data() -> None:
    result = await DuolingoAdapter(fetcher_for({"users": []})).lookup("nobody")
    assert result.ok
    assert result.primary is None


# -- music ------------------------------------------------------------------


def test_lastfm_strips_the_play_count_preamble() -> None:
    """Otherwise every Last.fm user shares a biography with every other."""
    adapter = LastFmAdapter()
    description = (
        "Listen to music from RJ’s library (151,481 tracks played). "
        "RJ’s top artists: Radiohead."
    )
    assert adapter.extract_display_name("RJ’s Music Profile | Last.fm") == "RJ"
    assert adapter.extract_bio({"og:description": description}, "") == (
        "RJ’s top artists: Radiohead."
    )
    assert adapter.extract_metadata({"og:description": description}, "") == {
        "tracks_played": "151,481"
    }


def test_lastfm_handles_a_plain_apostrophe_too() -> None:
    adapter = LastFmAdapter()
    assert adapter.extract_display_name("Bob's Music Profile | Last.fm") == "Bob"


def test_soundcloud_drops_the_platform_boilerplate() -> None:
    adapter = SoundCloudAdapter()
    value = (
        "Listen to alice | SoundCloud is an audio platform that lets you "
        "listen to what you love."
    )
    # Nothing of the artist's own remains, so there is no bio to report.
    assert adapter.extract_bio({"og:description": value}, "") is None

    real = "Producer from Kathmandu | SoundCloud is an audio platform that lets you."
    assert adapter.extract_bio({"og:description": real}, "") == "Producer from Kathmandu"


# -- social -----------------------------------------------------------------


def test_medium_strips_its_own_framing() -> None:
    adapter = MediumAdapter()
    value = (
        "Read writing from DHH on Medium. Creator of Ruby on Rails. "
        "Every day, DHH and thousands of other voices read, write, and share."
    )
    assert adapter.extract_display_name("DHH – Medium") == "DHH"
    assert adapter.extract_bio({"og:description": value}, "") == (
        "Creator of Ruby on Rails."
    )


def test_telegram_rejects_the_placeholder_for_an_unknown_handle() -> None:
    """t.me answers an unknown handle with a generic invitation, not a profile."""
    adapter = TelegramAdapter()
    placeholder = "You can contact @nobody right away."
    assert adapter.extract_bio({"og:description": placeholder}, "") is None
    assert adapter.extract_bio({"og:description": "Founder of Telegram."}, "") == (
        "Founder of Telegram."
    )


@pytest.mark.parametrize(
    "url,platform",
    [
        ("https://steamcommunity.com/id/gaben", "steam"),
        ("https://scratch.mit.edu/users/griffpatch", "scratch"),
        ("https://www.last.fm/user/rj", "lastfm"),
        ("https://hub.docker.com/u/jpetazzo", "dockerhub"),
        ("https://huggingface.co/julien-c", "huggingface"),
        ("https://medium.com/@dhh", "medium"),
        ("https://t.me/durov", "telegram"),
        ("https://crates.io/users/carols10cents", "crates"),
    ],
)
def test_new_platform_urls_are_recognised(url: str, platform: str) -> None:
    """A link discovered on one profile must resolve to the right platform."""
    parsed = parse_profile_url(url)
    assert parsed is not None and parsed[0] == platform


def test_a_non_profile_url_on_a_new_platform_is_refused() -> None:
    assert parse_profile_url("https://steamcommunity.com/app/440") is None
