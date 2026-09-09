"""Keybase source adapter.

Keybase is the single richest *legitimate* pivot in public-source OSINT,
because its whole purpose is publishing verified links between one person's
accounts.  A user signs a statement on each platform they own and Keybase
verifies it; the result is served at ``keybase.io/_/api/1.0/user/lookup.json``
to anonymous readers, and ``keybase.io/robots.txt`` permits it.

That matters for correlation: a Keybase proof is not an inference. The person
demonstrably controlled both accounts at signing time, which is exactly what
:data:`EvidenceType.EXPLICIT_LINK` is for - the strongest single piece of
evidence the engine recognises.

Omnicient still does not *claim* the identity on that basis.  A proof shows
control of the accounts, not who the human is, and it can be stale.  It is
presented as evidence, weighted, and left to the analyst.
"""

from __future__ import annotations

from typing import Any

from ..utils.url_parser import Reference
from .base import JsonProfileAdapter, ObservedProfile, enrich_profile

#: Keybase ``proof_type`` -> Omnicient platform.  Types absent from this map
#: (``dns``, ``generic_web_site``) are handled as websites instead.
PROOF_PLATFORMS: dict[str, str] = {
    "twitter": "x",
    "github": "github",
    "reddit": "reddit",
    "hackernews": "hackernews",
    "facebook": "facebook",
    "mastodon": "mastodon",
}

#: Proof types that name a domain the user controls rather than an account.
SITE_PROOFS = frozenset({"dns", "generic_web_site", "https", "http"})


class KeybaseAdapter(JsonProfileAdapter):
    """Looks up a public Keybase profile and its verified account proofs."""

    platform = "keybase"
    name = "Keybase"
    api_template = "https://keybase.io/_/api/1.0/user/lookup.json?username={identifier}"
    url_template = "https://keybase.io/{identifier}"

    def parse_json(
        self, identifier: str, payload: Any, url: str
    ) -> ObservedProfile | None:
        if not isinstance(payload, dict):
            return None
        # Keybase answers 200 with status.code != 0 for an unknown user.
        if (payload.get("status") or {}).get("code") not in (0, None):
            return None
        them = payload.get("them")
        if isinstance(them, list):
            them = them[0] if them else None
        if not isinstance(them, dict):
            return None

        basics = them.get("basics") or {}
        profile = them.get("profile") or {}
        username = basics.get("username") or identifier

        references, websites = self._proofs(them)

        observed = ObservedProfile(
            platform=self.platform,
            identifier=str(username),
            name=f"@{username}",
            url=self.profile_url(str(username)),
            display_name=profile.get("full_name") or None,
            bio=profile.get("bio") or None,
            location=profile.get("location") or None,
            avatar_url=((them.get("pictures") or {}).get("primary") or {}).get("url"),
            external_links=websites,
            source=self.platform,
            metadata={"proof_count": len(references) + len(websites)},
        )

        # enrich_profile derives references from free text; a verified proof
        # beats anything inferred from a bio, so proofs are merged in
        # afterwards and win where both name the same account.
        enrich_profile(observed)
        proven = {reference.key for reference in references}
        observed.references = [
            *references,
            *(r for r in observed.references if r.key not in proven),
        ]
        observed.websites = list(dict.fromkeys([*websites, *observed.websites]))
        return observed

    @staticmethod
    def _proofs(them: dict[str, Any]) -> tuple[list[Reference], list[str]]:
        """Split the proof list into account references and owned websites."""
        references: list[Reference] = []
        websites: list[str] = []
        summary = (them.get("proofs_summary") or {}).get("all") or []

        for proof in summary:
            if not isinstance(proof, dict):
                continue
            kind = (proof.get("proof_type") or "").lower()
            nametag = (proof.get("nametag") or "").strip()
            service_url = proof.get("service_url") or proof.get("proof_url")
            if not nametag:
                continue

            if kind in SITE_PROOFS:
                from ..utils.normalization import normalize_url

                candidate = normalize_url(
                    service_url or f"https://{nametag}"
                )
                if candidate and candidate not in websites:
                    websites.append(candidate)
                continue

            platform = PROOF_PLATFORMS.get(kind)
            if platform is None:
                continue
            references.append(
                Reference(
                    platform=platform,
                    identifier=nametag,
                    url=service_url,
                    context=(
                        f"Keybase proof: the account holder signed a statement "
                        f"on {platform} as '{nametag}', verified by Keybase"
                    ),
                    explicit=True,
                )
            )
        return references, websites
