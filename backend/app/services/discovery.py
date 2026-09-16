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

from collections.abc import Iterable
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
    #: True for candidates that are guesses rather than observations.  When a
    #: guess does not resolve it leaves no node behind, so a handle that simply
    #: does not exist on a platform never becomes graph noise.
    drop_if_unresolved: bool = False
    #: True when this candidate stands in for the seed.  A bare handle seeds a
    #: ``(:Username)`` pivot with no profile of its own, so the accounts found
    #: for it are what handle-variant expansion has to work from.
    seed_equivalent: bool = False

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
    "username": EntityType.USERNAME,
    "organization": EntityType.ORGANIZATION,
}

#: Platforms that are pivots rather than something an adapter fetches.
PSEUDO_PLATFORMS: frozenset[str] = frozenset(
    {"username", "email", "domain", "organization"}
)


def seed_candidate(platform: str, identifier: str) -> Candidate:
    """The starting point of an investigation."""
    return Candidate(
        entity_type=SEED_ENTITY_TYPES.get(platform, EntityType.ACCOUNT),
        platform=platform,
        identifier=identifier,
        method=DiscoveryMethod.SEED,
        reason="Seed identifier supplied by the analyst",
        depth=0,
        seed_equivalent=True,
    )


def discover_sources(
    identifier: str,
    *,
    platforms: Iterable[str],
    parent_key: EntityKey,
    depth: int = 0,
) -> list[Candidate]:
    """Search candidates for a bare handle, one per supported account source.

    This is what lets an analyst type ``alice_98`` and nothing else (section
    3.2).  Every supported source is *asked*; none is assumed to hold the
    handle.  A source that returns nothing leaves no node behind, so the graph
    shows the platforms where the handle actually exists.

    The candidates sit at the same depth as the seed: querying a second
    platform for the same handle is not a hop of evidence, it is the same
    question asked elsewhere.
    """
    candidates: list[Candidate] = []
    for platform in platforms:
        if platform in PSEUDO_PLATFORMS or platform == "website":
            continue
        candidates.append(
            Candidate(
                entity_type=EntityType.ACCOUNT,
                platform=platform,
                identifier=identifier,
                method=DiscoveryMethod.DIRECT,
                reason=(
                    f"{platform} searched for the seed handle '{identifier}' "
                    f"(no platform was specified by the analyst)"
                ),
                depth=depth,
                parent_key=parent_key,
                link_context=identifier,
                drop_if_unresolved=True,
                seed_equivalent=True,
            )
        )
    logger.info(
        "sources_discovered identifier=%s platforms=%d", identifier, len(candidates)
    )
    return candidates


def fanout_candidates(
    identifier: str,
    *,
    platforms: Iterable[str],
    depth: int,
    discovered_on: str,
    source_platform: str,
) -> list[Candidate]:
    """Search every source for a handle discovered mid-crawl.

    The seed handle is asked of every source at the start.  A handle that
    turns up later - a Facebook Intro linking to ``linkedin.com/in/prabhatach``
    when the investigation began at ``prabhatacharya19`` - deserves the same
    treatment, and is in one way a better lead: the profile published the
    connection itself, so the handles are tied together by something the
    person wrote rather than by them happening to look alike.

    Without this the new handle is only ever tried on the one platform that
    named it, and the accounts it holds elsewhere are never found.

    What is published, and what is guessed, are different things and are kept
    apart.  The profile published *one* link - a LinkedIn - and these
    candidates are the handle from it tried everywhere else.  So they carry no
    parent and no link context: an account found this way is a handle match on
    a handle somebody else published, never a reference the profile made.
    Recording it as one would have the graph assert that a Facebook page
    linked to a Duolingo account it has never heard of.  Like any other
    similarity lead, it earns nothing by existing and the correlation engine
    still has to find real evidence for it.

    These sit one hop deeper than the profile that revealed them, so the
    depth budget still bounds how far a chain of handles can run.
    """
    candidates: list[Candidate] = []
    for platform in platforms:
        if platform in PSEUDO_PLATFORMS or platform == "website":
            continue
        # The platform that published the handle already has its own account
        # for it, reached by the explicit link rather than by guessing.
        if platform == source_platform:
            continue
        candidates.append(
            Candidate(
                entity_type=EntityType.ACCOUNT,
                platform=platform,
                identifier=identifier,
                method=DiscoveryMethod.SIMILARITY,
                reason=(
                    f"Handle '{identifier}' was published by {discovered_on} "
                    f"as its {source_platform} account; this is the same handle "
                    f"looked for on {platform} - a weak lead, not evidence"
                ),
                depth=depth,
                # A guess: this handle need not exist here. Unresolved
                # guesses leave no node, so a miss never becomes graph noise.
                drop_if_unresolved=True,
            )
        )
    logger.info(
        "handle_fanout identifier=%s discovered_on=%s platforms=%d",
        identifier,
        discovered_on,
        len(candidates),
    )
    return candidates


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
                    drop_if_unresolved=True,
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
