"""Link-in-bio pages and the profile sources that publish an avatar.

A link-in-bio page exists to list its owner's other accounts, which makes it
the most productive thing an identity investigation can read: one fetch, a
set of handles the person published themselves. These tests hold the two
ways that goes wrong - reading the page's furniture as accounts, and missing
the links entirely.
"""

from __future__ import annotations

import json

import pytest

from app.sources.aggregators import BioLinkAdapter, LinktreeAdapter, SoloToAdapter
from app.sources.dev import LobstersAdapter
from app.sources.gaming import ChessComAdapter
from app.sources.gravatar import GravatarAdapter


def linktree_page(**account) -> str:
    """A page shaped like the JSON Linktree bootstraps itself from."""
    links = account.pop("links", [])
    payload = {
        "props": {
            "pageProps": {
                "account": {"username": "github", "isActive": True, **account},
                "links": links,
            }
        }
    }
    return (
        '<html><head><meta property="og:title" content="github | Linktree">'
        '</head><body><script id="__NEXT_DATA__" type="application/json" '
        f'crossorigin="anonymous">{json.dumps(payload)}</script></body></html>'
    )


# ---------------------------------------------------------------------------
# Linktree
# ---------------------------------------------------------------------------


def test_linktree_reads_every_account_the_page_lists() -> None:
    html = linktree_page(
        pageTitle="@github",
        description="The complete developer platform.",
        profilePictureUrl="https://ugc.production.linktr.ee/abc",
        links=[
            {"title": "GitHub", "url": "https://github.com/github"},
            {"title": "Twitter", "url": "https://twitter.com/github"},
            {"title": "Instagram", "url": "https://instagram.com/github"},
            {"title": "Blog", "url": "https://github.blog/"},
        ],
    )
    profile = LinktreeAdapter().parse_profile(
        "github", html, "https://linktr.ee/github"
    )

    assert profile is not None
    assert profile.display_name == "github"
    assert profile.bio == "The complete developer platform."
    assert profile.avatar_url == "https://ugc.production.linktr.ee/abc"

    # The point of the source: handles to go and investigate.
    found = {(r.platform, r.identifier) for r in profile.references}
    assert ("github", "github") in found
    assert ("x", "github") in found
    assert ("instagram", "github") in found
    assert all(r.explicit for r in profile.references), "the page published these"


def test_linktree_refuses_a_page_that_was_taken_down() -> None:
    """A blocked page publishes nothing, and proves nothing about the handle."""
    html = linktree_page(isActive=False, pageTitle="@github")

    assert LinktreeAdapter().parse_profile(
        "github", html, "https://linktr.ee/github"
    ) is None


def test_linktree_needs_an_account_in_the_page() -> None:
    plain = "<html><head><title>Linktree</title></head><body></body></html>"

    assert LinktreeAdapter().parse_profile(
        "github", plain, "https://linktr.ee/github"
    ) is None


# ---------------------------------------------------------------------------
# What is on these pages that is not an account
# ---------------------------------------------------------------------------


SOLO_PAGE = """
<html><head>
<meta property="og:title" content="NASA · solo.to">
<meta property="og:image" content="https://cdn.solo.to/og/nasa.jpg">
</head><body>
  <a href="https://instagram.com/nasamuzic">Instagram</a>
  <a href="https://youtu.be/ZEcV55ftyR0">A song</a>
  <a href="https://www.facebook.com/sharer/sharer.php?u=https://solo.to/nasa">Share</a>
  <a href="https://x.com/intent/tweet?text=Check%20this">Tweet</a>
  <a href="https://cdn.solo.to/images/favicon.png">icon</a>
  <a href="https://fonts.googleapis.com/css2?family=Inter">font</a>
</body></html>
"""


def test_a_share_button_is_not_an_account() -> None:
    """Every one of these pages says "share this on Facebook".

    Read naively that becomes an account called "sharer", on every single
    profile the crawl ever reads.
    """
    profile = SoloToAdapter().parse_profile("nasa", SOLO_PAGE, "https://solo.to/nasa")

    assert profile is not None
    platforms = {r.platform for r in profile.references}
    assert "facebook" not in platforms
    assert not any(r.identifier == "sharer" for r in profile.references)


def test_a_video_link_is_not_a_youtube_account() -> None:
    """``youtu.be/ZEcV55ftyR0`` is a song, not a person called ZEcV55ftyR0."""
    profile = SoloToAdapter().parse_profile("nasa", SOLO_PAGE, "https://solo.to/nasa")

    assert not any(r.platform == "youtube" for r in profile.references)


def test_the_real_account_on_the_page_still_comes_through() -> None:
    profile = SoloToAdapter().parse_profile("nasa", SOLO_PAGE, "https://solo.to/nasa")

    assert ("instagram", "nasamuzic") in {
        (r.platform, r.identifier) for r in profile.references
    }
    assert profile.display_name == "NASA", "the site name is stripped from the title"
    assert profile.avatar_url == "https://cdn.solo.to/og/nasa.jpg"


def test_assets_and_infrastructure_are_not_accounts() -> None:
    profile = SoloToAdapter().parse_profile("nasa", SOLO_PAGE, "https://solo.to/nasa")

    for link in profile.external_links:
        assert "favicon" not in link
        assert "googleapis" not in link


def test_bio_link_reads_the_same_shape() -> None:
    page = (
        '<html><head><meta property="og:title" content="nasa8448">'
        '<meta property="og:description" content="Space stuff.">'
        "</head><body>"
        '<a href="https://instagram.com/nasa">IG</a>'
        "</body></html>"
    )
    profile = BioLinkAdapter().parse_profile("nasa", page, "https://bio.link/nasa")

    assert profile is not None
    assert ("instagram", "nasa") in {
        (r.platform, r.identifier) for r in profile.references
    }


# ---------------------------------------------------------------------------
# Gravatar: an avatar service that is quietly an identity directory
# ---------------------------------------------------------------------------


GRAVATAR_JSON = {
    "entry": [
        {
            "hash": "27205e5c",
            "preferredUsername": "beau",
            "displayName": "Beau Lebens",
            "aboutMe": "Lead of WooCommerce, at Automattic.",
            "currentLocation": "Golden, CO",
            "company": "Automattic",
            "job_title": "Lead, WooCommerce",
            "pronouns": "he/him",
            "thumbnailUrl": "https://0.gravatar.com/avatar/27205e5c",
            "profileUrl": "https://gravatar.com/beau",
            "emails": [{"value": "beau@automattic.com", "primary": "true"}],
            "accounts": [
                {"shortname": "github", "url": "https://github.com/beaulebens"},
                {"shortname": "linkedin", "url": "https://linkedin.com/in/beaulebens"},
            ],
        }
    ]
}


def test_gravatar_publishes_a_whole_identity() -> None:
    profile = GravatarAdapter().parse_json(
        "beau", GRAVATAR_JSON, "https://gravatar.com/beau"
    )

    assert profile is not None
    assert profile.display_name == "Beau Lebens"
    assert profile.location == "Golden, CO"
    assert profile.organization == "Automattic"
    assert profile.avatar_url == "https://0.gravatar.com/avatar/27205e5c"
    assert profile.metadata["job_title"] == "Lead, WooCommerce"
    assert "beau@automattic.com" in profile.emails


def test_gravatar_accounts_become_handles_to_investigate() -> None:
    """Attached accounts are self-declared, like a link-in-bio page."""
    profile = GravatarAdapter().parse_json(
        "beau", GRAVATAR_JSON, "https://gravatar.com/beau"
    )

    found = {(r.platform, r.identifier) for r in profile.references}
    assert ("github", "beaulebens") in found
    assert ("linkedin", "beaulebens") in found


def test_gravatar_without_an_entry_is_not_a_profile() -> None:
    assert GravatarAdapter().parse_json("nobody", {"entry": []}, "u") is None
    assert GravatarAdapter().parse_json("nobody", {}, "u") is None


# ---------------------------------------------------------------------------
# The other new profile sources
# ---------------------------------------------------------------------------


def test_chess_com_reads_name_title_and_region() -> None:
    payload = {
        "username": "hikaru",
        "name": "Hikaru Nakamura",
        "title": "GM",
        "location": "Florida",
        "country": "https://api.chess.com/pub/country/US",
        "avatar": "https://images.chesscomfiles.com/a.png",
        "url": "https://www.chess.com/member/Hikaru",
        "twitch_url": "https://twitch.tv/gmhikaru",
    }
    profile = ChessComAdapter().parse_json("hikaru", payload, "x")

    assert profile.display_name == "Hikaru Nakamura"
    assert profile.location == "Florida, US"
    assert profile.avatar_url == "https://images.chesscomfiles.com/a.png"
    assert profile.metadata["title"] == "GM"
    assert ("twitch", "gmhikaru") in {
        (r.platform, r.identifier) for r in profile.references
    }


def test_lobsters_publishes_its_bio_as_html() -> None:
    """Stored as the text a person wrote, not as markup."""
    payload = {
        "username": "jcs",
        "about": "<p>hello, cyberpals</p>",
        "avatar_url": "/avatars/jcs-100.png",
        "github_username": "jcs",
        "karma": 16855,
    }
    profile = LobstersAdapter().parse_json("jcs", payload, "https://lobste.rs/u/jcs")

    assert profile.bio == "hello, cyberpals"
    # Published relative to the site root, stored so it resolves anywhere.
    assert profile.avatar_url == "https://lobste.rs/avatars/jcs-100.png"
    assert ("github", "jcs") in {(r.platform, r.identifier) for r in profile.references}


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://linktr.ee/github", ("linktree", "github")),
        ("https://solo.to/nasa", ("solo", "nasa")),
        ("https://bio.link/nasa", ("biolink", "nasa")),
        ("https://gravatar.com/beau", ("gravatar", "beau")),
        ("https://www.chess.com/member/Hikaru", ("chess", "hikaru")),
        ("https://lobste.rs/u/jcs", ("lobsters", "jcs")),
        ("https://www.twitch.tv/gmhikaru", ("twitch", "gmhikaru")),
        # Not profiles.
        ("https://youtu.be/ZEcV55ftyR0", None),
        ("https://linktr.ee/", None),
        ("https://www.chess.com/news", None),
    ],
)
def test_a_link_to_one_of_these_sites_is_recognised(url, expected) -> None:
    """A crawl has to know a Linktree link when another profile publishes one."""
    from app.utils.url_parser import parse_profile_url

    assert parse_profile_url(url) == expected
