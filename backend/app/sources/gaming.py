"""Gaming-platform source adapters.

Steam is the one major gaming platform that serves a small, stable public
document to anonymous readers and permits it in robots.txt. Speedrun.com,
Chess.com and Lichess were checked and all three disallow crawling; Roblox
requires resolving a username to a numeric id through a POST endpoint, which
is more machinery than a public-data lookup should need.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from .base import (
    ObservedProfile,
    SourceCategory,
    XmlProfileAdapter,
    enrich_profile,
    xml_text,
)


class SteamAdapter(XmlProfileAdapter):
    """Steam community profiles, via the public XML view.

    Appending ``?xml=1`` to a community URL returns a compact document instead
    of a 200KB JavaScript-rendered page - lighter to fetch and far less likely
    to break on a redesign.

    Only vanity URLs are supported. A numeric ``/profiles/{id}`` URL is an
    account id rather than a handle, and guessing one is not discovery.
    """

    platform = "steam"
    name = "Steam"
    category = SourceCategory.GAMING
    api_template = "https://steamcommunity.com/id/{identifier}/?xml=1"
    url_template = "https://steamcommunity.com/id/{identifier}"

    def parse_xml(
        self, identifier: str, soup: BeautifulSoup, url: str
    ) -> ObservedProfile | None:
        handle = xml_text(soup, "steamID")
        steam_id = xml_text(soup, "steamID64")
        # A missing profile still returns XML, but with an error element and
        # no identity fields.
        if not handle or not steam_id:
            return None

        summary = xml_text(soup, "summary")
        if summary:
            # The summary is CDATA-wrapped HTML; keep the text and let the
            # shared extraction find any links inside it.
            summary = " ".join(
                BeautifulSoup(summary, "lxml").get_text(" ", strip=True).split()
            )

        return enrich_profile(
            ObservedProfile(
                platform=self.platform,
                identifier=identifier,
                name=f"@{identifier}",
                url=url,
                display_name=handle,
                bio=summary or None,
                location=xml_text(soup, "location") or None,
                avatar_url=xml_text(soup, "avatarFull") or None,
                source=self.platform,
                metadata={
                    key: value
                    for key, value in (
                        ("steam_id64", steam_id),
                        ("real_name", xml_text(soup, "realname")),
                        ("member_since", xml_text(soup, "memberSince")),
                        ("state", xml_text(soup, "stateMessage")),
                    )
                    if value
                },
            )
        )
