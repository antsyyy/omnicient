"""Gravatar: the avatar service that is quietly an identity directory.

Gravatar publishes a documented JSON profile for any account that has one, and
it is unusually rich for a single unauthenticated request: display name,
biography, location, job title, employer, pronouns - and ``accounts``, a list
of other platforms the owner has attached to their profile.

Those attached accounts are the valuable part.  They are self-declared, the
same class of evidence as a link-in-bio page, and Gravatar is reached from an
email address as well as a username, which is a bridge almost nothing else in
the catalogue offers.

It is also where an avatar comes from most reliably.  Gravatar serves images
to anonymous callers by design, so unlike a social CDN the URL still works
when an analyst opens the investigation tomorrow.
"""

from __future__ import annotations

from typing import Any

from .base import JsonProfileAdapter, ObservedProfile, SourceCategory, enrich_profile


class GravatarAdapter(JsonProfileAdapter):
    """Reads the public Gravatar profile for a username."""

    platform = "gravatar"
    name = "Gravatar"
    category = SourceCategory.IDENTITY
    api_template = "https://gravatar.com/{identifier}.json"
    url_template = "https://gravatar.com/{identifier}"

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        entries = payload.get("entry") if isinstance(payload, dict) else None
        if not isinstance(entries, list) or not entries:
            return None
        entry = entries[0]
        if not isinstance(entry, dict):
            return None

        handle = entry.get("preferredUsername") or identifier

        # Accounts the owner attached to their profile, and any personal sites
        # listed alongside them. Both are published links to somewhere else.
        links: list[str] = []
        for account in entry.get("accounts") or []:
            target = account.get("url") if isinstance(account, dict) else None
            if isinstance(target, str) and target and target not in links:
                links.append(target)
        for site in entry.get("urls") or []:
            target = site.get("value") if isinstance(site, dict) else None
            if isinstance(target, str) and target and target not in links:
                links.append(target)

        emails = [
            address.get("value")
            for address in entry.get("emails") or []
            if isinstance(address, dict) and address.get("value")
        ]

        metadata: dict[str, Any] = {}
        for key, name in (
            ("job_title", "job_title"),
            ("pronouns", "pronouns"),
            ("hash", "gravatar_hash"),
        ):
            value = entry.get(key)
            if value:
                metadata[name] = value
        if entry.get("accounts"):
            metadata["verified_accounts"] = [
                account.get("shortname")
                for account in entry["accounts"]
                if isinstance(account, dict) and account.get("shortname")
            ]

        profile = enrich_profile(
            ObservedProfile(
                platform=self.platform,
                identifier=str(handle),
                name=f"@{handle}",
                url=entry.get("profileUrl") or url,
                display_name=(entry.get("displayName") or "").strip() or None,
                bio=(entry.get("aboutMe") or "").strip() or None,
                # The photo Gravatar serves for this profile. Public by
                # design, which is why it still resolves later.
                avatar_url=entry.get("thumbnailUrl") or None,
                location=(entry.get("currentLocation") or "").strip() or None,
                organization=(entry.get("company") or "").strip() or None,
                external_links=links,
                source=self.platform,
                metadata=metadata,
            )
        )
        # A published address is worth more than one inferred from bio text.
        for address in emails:
            if address not in profile.emails:
                profile.emails.append(address)
        if profile.emails and not profile.email:
            profile.email = profile.emails[0]
        return profile
