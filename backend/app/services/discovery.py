"""Candidate generation.

Discovery answers one question: given something we have already observed, what
else is worth looking at?  Every candidate records *how* it was found, because
that provenance is what separates "the profile links to this account" from
"this account merely has a similar handle" (section 18):

``DIRECT``
    Explicitly linked from the seed profile.
``INDIRECT``
    Reached through another entity - typically a personal website.
``SIMILARITY``
    Generated from a weak signal such as a handle variant.  A similarity
    candidate earns no score by existing; the correlation engine still has to
    find real evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models.enums import DiscoveryMethod, EntityType
from ..sources.base import ObservedProfile
from ..utils.logging import get_logger
from ..utils.normalization import normalize_domain, username_variants
from ..utils.url_parser import website_identity

logger = get_logger(__name__)

#: Platforms a similarity candidate may be generated for.  Deliberately small:
#: guessing handles on every platform produces noise, not evidence.
SIMILARITY_PLATFORMS: tuple[str, ...] = ("instagram", "threads", "facebook")

EntityKey = tuple[str, str, str]


@dataclass(frozen=True)
class Candidate:
    """Something worth looking up, and the reason we think so."""

    entity_type: EntityType
    platform: str
    identifier: str
    method: DiscoveryMethod
    reason: str
    depth: int = 0
    url: str | None = None
    parent_key: EntityKey | None = None
    #: Evidence describing the link from the parent, if there is one.
    link_context: str | None = None
    #: Human-readable name, when it differs from the canonical identifier.
    display_name: str | None = None

    @property
    def key(self) -> EntityKey:
        return (str(self.entity_type), self.platform, self.identifier)

    @property
    def label(self) -> str:
        return f"{self.platform}:{self.identifier}"


@dataclass
class DiscoveryResult:
    """Candidates derived from one observed profile."""

    candidates: list[Candidate] = field(default_factory=list)

    def extend(self, others: list[Candidate]) -> None:
        self.candidates.extend(others)


#: Seed platforms that are not accounts.
SEED_ENTITY_TYPES: dict[str, EntityType] = {
    "website": EntityType.WEBSITE,
    "domain": EntityType.DOMAIN,
    "email": EntityType.EMAIL,
}


def seed_candidate(platform: str, identifier: str) -> Candidate:
    """The starting point of an investigation."""
    return Candidate(
        entity_type=SEED_ENTITY_TYPES.get(platform, EntityType.ACCOUNT),
        platform=platform,
        identifier=identifier,
        method=DiscoveryMethod.SEED,
        reason="Seed identifier supplied by the analyst",
        depth=0,
    )


def candidates_from_profile(
    profile: ObservedProfile,
    *,
    parent_key: EntityKey,
    depth: int,
    from_seed: bool,
) -> list[Candidate]:
    """Derive every candidate an observed profile points at.

    Accounts, websites, email addresses and organizations are all returned as
    candidates; the crawler decides which of them a source adapter can resolve.
    """
    method = DiscoveryMethod.DIRECT if from_seed else DiscoveryMethod.INDIRECT
    candidates: list[Candidate] = []

    for reference in profile.references:
        candidates.append(
            Candidate(
                entity_type=EntityType.ACCOUNT,
                platform=reference.platform,
                identifier=reference.identifier,
                method=method,
                reason=(
                    f"Explicit reference published by {profile.label}: "
                    f"{reference.context}"
                ),
                depth=depth,
                url=reference.url,
                parent_key=parent_key,
                link_context=reference.context,
            )
        )

    for url in profile.websites:
        identity = website_identity(url)
        if not identity:
            continue
        candidates.append(
            Candidate(
                entity_type=EntityType.WEBSITE,
                platform="website",
                identifier=identity,
                method=method,
                reason=f"External website published by {profile.label}: {url}",
                depth=depth,
                url=url,
                parent_key=parent_key,
                link_context=url,
            )
        )

    for address in profile.emails:
        candidates.append(
            Candidate(
                entity_type=EntityType.EMAIL,
                platform="email",
                identifier=address,
                method=method,
                reason=f"Public email address published by {profile.label}",
                depth=depth,
                url=None,
                parent_key=parent_key,
                link_context=address,
            )
        )

    for organization in profile.organizations:
        candidates.append(
            Candidate(
                entity_type=EntityType.ORGANIZATION,
                platform="organization",
                identifier=organization.lower(),
                display_name=organization,
                method=method,
                reason=f"Organization referenced by {profile.label}: {organization}",
                depth=depth,
                url=None,
                parent_key=parent_key,
                link_context=organization,
            )
        )

    logger.info(
        "candidates_generated from=%s method=%s count=%d",
        profile.label,
        method,
        len(candidates),
    )
    return candidates


def similarity_candidates(
    profile: ObservedProfile,
    *,
    depth: int,
    platforms: tuple[str, ...] = SIMILARITY_PLATFORMS,
    known: set[EntityKey] | None = None,
) -> list[Candidate]:
    """Weak handle-reuse leads for the seed profile.

    These are guesses.  They are kept separate from explicit references so the
    interface can tell an analyst that a node arrived on a weak signal, and so
    they can be filtered out entirely.
    """
    known = known or set()
    candidates: list[Candidate] = []
    for platform in platforms:
        if platform == profile.platform:
            continue
        for variant in username_variants(profile.identifier):
            key = (str(EntityType.ACCOUNT), platform, variant)
            if key in known:
                continue
            known.add(key)
            candidates.append(
                Candidate(
                    entity_type=EntityType.ACCOUNT,
                    platform=platform,
                    identifier=variant,
                    method=DiscoveryMethod.SIMILARITY,
                    reason=(
                        f"Handle '{variant}' is a variant of the seed handle "
                        f"'{profile.identifier}' - a weak lead, not evidence"
                    ),
                    depth=depth,
                )
            )
    return candidates


def email_domain_candidate(address: str, *, depth: int, parent_key: EntityKey) -> Candidate | None:
    """The domain half of a public email address, as a pivot entity."""
    domain = normalize_domain(address.split("@")[-1]) if "@" in address else None
    if not domain:
        return None
    return Candidate(
        entity_type=EntityType.DOMAIN,
        platform="domain",
        identifier=domain,
        method=DiscoveryMethod.INDIRECT,
        reason=f"Domain of the public email address {address}",
        depth=depth,
        url=f"https://{domain}",
        parent_key=parent_key,
        link_context=address,
    )
