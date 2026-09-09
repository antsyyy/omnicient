"""Synthetic demo dataset.

Demo mode is mandatory (section 31): Omnicient must demonstrate the full
pipeline - discovery, candidate generation, correlation, evidence, graph -
without contacting a single external service.

Everything below is FICTIONAL.  The handles, website, avatars and biographies
describe no real person, and every entity created from this dataset is tagged
``DEMO DATA`` in the API and in the interface.

The dataset is built to exercise every class of evidence:

* strong        - explicit cross-platform links, a shared website, a shared
                  avatar, a shared public email
* medium        - similar biography, same display name, shared organization
* weak          - a similar username and nothing else
* contradictory - a different public website and a conflicting location
* unavailable   - a profile that cannot be read publicly, so the
                  "source unavailable" path is demonstrated as well
"""

from __future__ import annotations

from .models.enums import EntityType
from .sources import SourceRegistry
from .sources.base import (
    FailureReason,
    LookupResult,
    ObservedProfile,
    SourceAdapter,
    SourceError,
    enrich_profile,
)
from .utils.logging import get_logger
from .utils.normalization import NormalizationError, normalize_username

logger = get_logger(__name__)

DEMO_SEED_PLATFORM = "instagram"
DEMO_SEED_IDENTIFIER = "alice_98"
DEMO_LABEL = "DEMO DATA"

AVATAR_MAIN = "https://alice.dev/media/avatar-512.png"
AVATAR_OTHER = "https://alice.dev/media/photo-alt.png"

# Handles that deliberately fail, to exercise graceful error handling.
DEMO_UNAVAILABLE: dict[tuple[str, str], tuple[FailureReason, str]] = {
    ("facebook", "alice.private"): (
        FailureReason.PRIVATE,
        "Facebook served a login wall for 'alice.private'; the profile is not "
        "publicly readable.",
    ),
}


def _profile(**kwargs) -> ObservedProfile:
    """Build a demo profile and tag it as synthetic."""
    metadata = dict(kwargs.pop("metadata", {}))
    metadata["demo"] = True
    metadata["notice"] = DEMO_LABEL
    profile = ObservedProfile(source="demo", metadata=metadata, **kwargs)
    return enrich_profile(profile)


def build_demo_profiles() -> dict[tuple[str, str], ObservedProfile]:
    """The synthetic profiles served by the demo adapters."""
    profiles = [
        _profile(
            platform="instagram",
            identifier="alice_98",
            name="@alice_98",
            url="https://instagram.com/alice_98",
            display_name="Alice R.",
            bio=(
                "Security researcher at Contoso Labs. Threads: @alice_dev. "
                "FB: alice.private. Portfolio https://alice.dev"
            ),
            avatar_url=AVATAR_MAIN,
            location="Kathmandu",
            external_links=["https://alice.dev"],
        ),
        _profile(
            platform="threads",
            identifier="alice_dev",
            name="@alice_dev",
            url="https://threads.net/@alice_dev",
            display_name="Alice R.",
            bio=(
                "Security researcher at Contoso Labs. Writing about detection "
                "engineering. https://alice.dev"
            ),
            avatar_url=AVATAR_MAIN,
            location="Kathmandu",
            external_links=["https://alice.dev"],
        ),
        _profile(
            platform="facebook",
            identifier="alice.example",
            name="Alice Example",
            url="https://facebook.com/alice.example",
            display_name="Alice R.",
            bio="Security researcher. Portfolio: https://alice.dev",
            avatar_url=AVATAR_OTHER,
            external_links=["https://alice.dev"],
        ),
        _profile(
            entity_type=EntityType.WEBSITE,
            platform="website",
            identifier="alice.dev",
            name="alice.dev",
            url="https://alice.dev",
            display_name="alice.dev - Alice R.",
            bio=(
                "Personal site of Alice R., security researcher at Contoso Labs. "
                "Contact: alice@alice.dev"
            ),
            external_links=[
                "https://github.com/alice-security",
                "https://reddit.com/u/alice_security",
                "https://threads.net/@alice_dev",
                "https://instagram.com/alice_98",
                "https://facebook.com/alice.example",
            ],
            metadata={"identity_links": ["https://github.com/alice-security"]},
        ),
        # GitHub and Reddit have live adapters; X does not.  All three are
        # served synthetically here so the demo runs identically with no
        # network, and so correlation across a not-yet-adapted platform (X) is
        # demonstrated end to end.
        _profile(
            platform="github",
            identifier="alice-security",
            name="@alice-security",
            url="https://github.com/alice-security",
            display_name="Alice R.",
            bio=(
                "Security researcher at Contoso Labs. Detection engineering and "
                "OSINT tooling. alice@alice.dev"
            ),
            avatar_url=AVATAR_MAIN,
            location="Kathmandu",
            external_links=["https://alice.dev"],
        ),
        _profile(
            platform="reddit",
            identifier="alice_security",
            name="@alice_security",
            url="https://reddit.com/u/alice_security",
            display_name="alice_security",
            bio="Posting about detection engineering. Blog: https://alice.dev",
            external_links=["https://alice.dev"],
        ),
        # A deliberate near miss: a similar handle belonging to someone else.
        _profile(
            platform="x",
            identifier="alice98",
            name="@alice98",
            url="https://x.com/alice98",
            display_name="Alice Bennett",
            bio="Landscape photographer. Prints: https://unrelated.example",
            location="London",
            external_links=["https://unrelated.example"],
        ),
    ]
    return {(profile.platform, profile.identifier): profile for profile in profiles}


DEMO_PROFILES = build_demo_profiles()


class DemoAdapter(SourceAdapter):
    """Offline stand-in for a live adapter, serving :data:`DEMO_PROFILES`."""

    def __init__(self, platform: str) -> None:
        self.platform = platform
        self.name = f"{platform.title()} (demo)"

    def profile_url(self, identifier: str) -> str | None:
        profile = DEMO_PROFILES.get((self.platform, identifier))
        return profile.url if profile else None

    async def lookup(self, identifier: str) -> LookupResult:
        """Serve a synthetic profile, a synthetic failure, or nothing."""
        if self.platform != "website":
            try:
                identifier = normalize_username(identifier)
            except NormalizationError as exc:
                return LookupResult.failure(
                    SourceError(FailureReason.NOT_FOUND, str(exc))
                )

        failure = DEMO_UNAVAILABLE.get((self.platform, identifier))
        if failure is not None:
            reason, detail = failure
            logger.info(
                "demo_source_unavailable platform=%s identifier=%s reason=%s",
                self.platform,
                identifier,
                reason,
            )
            return LookupResult.failure(SourceError(reason, detail))

        profile = DEMO_PROFILES.get((self.platform, identifier))
        if profile is None:
            logger.info(
                "demo_not_found platform=%s identifier=%s", self.platform, identifier
            )
            return LookupResult(pages_fetched=0)
        logger.info(
            "demo_profile_served platform=%s identifier=%s", self.platform, identifier
        )
        return LookupResult(entities=[profile.model_copy(deep=True)], pages_fetched=1)


def demo_platforms() -> list[str]:
    """Platforms the demo dataset can answer for."""
    return sorted({platform for platform, _ in DEMO_PROFILES})


def build_demo_registry() -> SourceRegistry:
    """A registry whose adapters never touch the network."""
    registry = SourceRegistry()
    platforms = set(demo_platforms()) | {platform for platform, _ in DEMO_UNAVAILABLE}
    for platform in sorted(platforms):
        registry.register(DemoAdapter(platform))
    logger.info("demo_registry_ready platforms=%s", ",".join(sorted(platforms)))
    return registry
