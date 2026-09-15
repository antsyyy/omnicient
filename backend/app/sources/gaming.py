"""Gaming-platform source adapters.

Steam is the one major gaming platform that serves a small, stable public
document to anonymous readers and permits it in robots.txt. Speedrun.com,
Chess.com and Lichess were checked and all three disallow crawling; Roblox
requires resolving a username to a numeric id through a POST endpoint, which
is more machinery than a public-data lookup should need.
"""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from .base import (
    JsonProfileAdapter,
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
    probe_present = "gaben"

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


class ChessComAdapter(JsonProfileAdapter):
    """chess.com, via its documented public player API.

    Unusually forthcoming for a games site: the player's real name, the
    country and region they play under, the title they hold and an avatar
    that is served to anyone. The published profile URL also carries the
    canonical capitalisation of the handle, which is what gets displayed.
    """

    platform = "chess"
    name = "Chess.com"
    category = SourceCategory.GAMING
    api_template = "https://api.chess.com/pub/player/{identifier}"
    url_template = "https://www.chess.com/member/{identifier}"
    probe_present = "hikaru"

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        if not isinstance(payload, dict) or not payload.get("username"):
            return None
        handle = str(payload["username"])
        # "https://api.chess.com/pub/country/US" -> "US"
        country = str(payload.get("country") or "").rstrip("/").rsplit("/", 1)[-1]
        location = ", ".join(
            part for part in (payload.get("location"), country or None) if part
        )
        streaming = payload.get("twitch_url")
        return enrich_profile(
            ObservedProfile(
                platform=self.platform,
                identifier=handle,
                name=f"@{handle}",
                url=payload.get("url") or url,
                display_name=(payload.get("name") or "").strip() or None,
                avatar_url=payload.get("avatar") or None,
                location=location or None,
                # A linked Twitch channel is an account on another platform,
                # published by this one.
                external_links=[streaming] if streaming else [],
                source=self.platform,
                metadata={
                    key: payload[key]
                    for key in ("title", "followers", "joined", "status")
                    if payload.get(key) is not None
                },
            )
        )
