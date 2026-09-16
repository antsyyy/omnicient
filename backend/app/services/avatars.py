"""Fetch the avatars a crawl found, and reduce each to a perceptual hash.

Runs between the crawl and the correlation, because the engine compares
observed profiles and the hash has to be on them before it does.

Two guards decide whether a hash is worth having at all, and both exist
because an avatar is the easiest place in this system to manufacture a false
positive.

*Flat images are refused* by the hasher itself: a platform's default avatar is
usually a silhouette on one colour, and hashing it would link every account
that never uploaded a picture.

*Images shared by many accounts are dropped here*, which catches the defaults
the first guard misses - a site whose placeholder happens to carry enough
detail to hash. The reasoning is the one this project already applies to
shared domains: a picture two accounts use is a strong sign they are the same
party, and a picture twenty accounts use is a logo, a stock photo, or a
default. The more accounts carry it, the less it identifies any of them.
"""

from __future__ import annotations

import asyncio
from collections import Counter

from ..config import Settings, get_settings
from ..sources.base import ObservedProfile, SafeFetcher, SourceError
from ..utils.imagehash import difference_hash, looks_like_default_avatar
from ..utils.logging import get_logger

logger = get_logger(__name__)

#: An image on more accounts than this is not anybody's face.
MAX_SHARERS = 4


class AvatarHasher:
    """Downloads avatars and records a perceptual hash on each profile."""

    def __init__(
        self, fetcher: SafeFetcher | None = None, settings: Settings | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self.fetcher = fetcher or SafeFetcher(self.settings)

    async def apply(self, profiles: list[ObservedProfile]) -> int:
        """Hash what can be hashed. Returns how many profiles gained one."""
        wanted = [
            profile
            for profile in profiles
            if profile.avatar_url and not looks_like_default_avatar(profile.avatar_url)
        ]
        budget = max(0, self.settings.max_avatar_fetches)
        if not wanted or not budget:
            return 0
        wanted = wanted[:budget]

        # One download per distinct URL: the same picture is commonly served
        # to several of a person's profiles, and re-fetching it would spend
        # the budget on work already done.
        by_url: dict[str, list[ObservedProfile]] = {}
        for profile in wanted:
            by_url.setdefault(str(profile.avatar_url), []).append(profile)

        semaphore = asyncio.Semaphore(max(1, self.settings.crawl_concurrency))

        async def hash_one(url: str) -> tuple[str, str | None]:
            async with semaphore:
                try:
                    data = await self.fetcher.get_bytes(url)
                except SourceError as error:
                    logger.debug("avatar_unavailable url=%s reason=%s", url, error.reason)
                    return url, None
                except Exception as error:  # noqa: BLE001 - never end a run
                    logger.debug("avatar_failed url=%s error=%s", url, error)
                    return url, None
            return url, difference_hash(data)

        results = dict(
            await asyncio.gather(*(hash_one(url) for url in by_url))
        )

        # Drop any image that turned up on too many accounts to be a face.
        counts = Counter(
            digest
            for url, digest in results.items()
            if digest
            for _ in by_url[url]
        )
        common = {digest for digest, count in counts.items() if count > MAX_SHARERS}
        if common:
            logger.info("avatar_defaults_ignored count=%d", len(common))

        applied = 0
        for url, digest in results.items():
            if not digest or digest in common:
                continue
            for profile in by_url[url]:
                profile.avatar_hash = digest
                applied += 1

        logger.info(
            "avatars_hashed fetched=%d hashed=%d profiles=%d",
            len(by_url),
            sum(1 for d in results.values() if d),
            applied,
        )
        return applied
