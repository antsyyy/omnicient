"""Discovery sources.

Adding a platform means writing one :class:`SourceAdapter` and registering it
in :func:`build_registry` - the crawler, correlation engine and API do not
change.  Platforms without an adapter are still *discovered*: the crawler
records them as unresolved candidate entities, which is what lets a GitHub or
Reddit link become a node long before a GitHub or Reddit adapter exists.
"""

from __future__ import annotations

from ..config import Settings, get_settings
from ..utils.logging import get_logger
from .aggregators import BioLinkAdapter, LinktreeAdapter, SoloToAdapter
from .base import (
    FailureReason,
    JsonProfileAdapter,
    LookupResult,
    ObservedProfile,
    OpenGraphProfileAdapter,
    SafeFetcher,
    SourceAdapter,
    SourceCategory,
    SourceError,
    XmlProfileAdapter,
)
from .bluesky import BlueskyAdapter
from .dev import (
    CodebergAdapter,
    CratesIoAdapter,
    DockerHubAdapter,
    HackerNewsAdapter,
    HuggingFaceAdapter,
    LaunchpadAdapter,
    LobstersAdapter,
    StackOverflowAdapter,
)
from .devto import DevToAdapter
from .facebook import FacebookAdapter
from .gaming import ChessComAdapter, LichessAdapter, SteamAdapter
from .github import GitHubAdapter
from .gravatar import GravatarAdapter
from .identity_sites import AboutMeAdapter, MicroBlogAdapter
from .instagram import InstagramAdapter
from .keybase import KeybaseAdapter
from .learning import CodewarsAdapter, DuolingoAdapter, ScratchAdapter
from .mastodon import MastodonAdapter
from .music import LastFmAdapter, MixcloudAdapter, SoundCloudAdapter
from .reddit import RedditAdapter
from .social import MediumAdapter, TelegramAdapter
from .threads import ThreadsAdapter
from .video import YouTubeAdapter
from .website import WebsiteAdapter

logger = get_logger(__name__)

#: Adapters shipped with the MVP.  Future adapters (X, LinkedIn, YouTube,
#: Mastodon, GitLab) are registered here and nowhere else.
ADAPTER_CLASSES: tuple[type[SourceAdapter], ...] = (
    # Sources whose robots.txt permits anonymous lookups, so they work live.
    # Identity and general web.
    KeybaseAdapter,
    GravatarAdapter,
    AboutMeAdapter,
    WebsiteAdapter,
    # Link-in-bio pages. The single most productive source an identity
    # investigation has: a page whose whole purpose is to list its owner's
    # accounts, published by them.
    LinktreeAdapter,
    SoloToAdapter,
    BioLinkAdapter,
    # Developer platforms.
    GitHubAdapter,
    DevToAdapter,
    HackerNewsAdapter,
    HuggingFaceAdapter,
    StackOverflowAdapter,
    CratesIoAdapter,
    DockerHubAdapter,
    LaunchpadAdapter,
    LobstersAdapter,
    CodebergAdapter,
    # Social.
    MastodonAdapter,
    BlueskyAdapter,
    TelegramAdapter,
    MediumAdapter,
    YouTubeAdapter,
    MicroBlogAdapter,
    # Gaming.
    SteamAdapter,
    ChessComAdapter,
    LichessAdapter,
    # Music.
    SoundCloudAdapter,
    LastFmAdapter,
    MixcloudAdapter,
    # Learning.
    CodewarsAdapter,
    ScratchAdapter,
    DuolingoAdapter,
    # Sources that publish "Disallow: /" for everything.  Kept registered so a
    # discovered link still becomes a node and the refusal is reported, rather
    # than the platform silently vanishing from the investigation.
    InstagramAdapter,
    RedditAdapter,
    ThreadsAdapter,
    FacebookAdapter,
)


class SourceRegistry:
    """Platform -> adapter lookup used by the crawler."""

    def __init__(self, adapters: dict[str, SourceAdapter] | None = None) -> None:
        self._adapters: dict[str, SourceAdapter] = dict(adapters or {})

    def register(self, adapter: SourceAdapter) -> None:
        self._adapters[adapter.platform] = adapter

    def get(self, platform: str) -> SourceAdapter | None:
        return self._adapters.get(platform)

    def supports(self, platform: str) -> bool:
        return platform in self._adapters

    def platforms(self) -> list[str]:
        return sorted(self._adapters)

    async def aclose(self) -> None:
        """Close every fetcher the registry owns."""
        closed: set[int] = set()
        for adapter in self._adapters.values():
            fetcher = getattr(adapter, "fetcher", None)
            if fetcher is not None and id(fetcher) not in closed:
                closed.add(id(fetcher))
                await fetcher.aclose()


def build_registry(
    settings: Settings | None = None, fetcher: SafeFetcher | None = None
) -> SourceRegistry:
    """Instantiate every live adapter, sharing one polite HTTP client."""
    settings = settings or get_settings()
    shared = fetcher or SafeFetcher(settings)
    registry = SourceRegistry()
    for adapter_class in ADAPTER_CLASSES:
        registry.register(adapter_class(shared))  # type: ignore[call-arg]
    logger.info("source_registry_ready platforms=%s", ",".join(registry.platforms()))
    return registry


#: Adapters grouped by the kind of site they read, for the health endpoint
#: and anything else that wants to describe coverage rather than list it.
def adapters_by_category() -> dict[str, list[str]]:
    """``{"dev": ["github", "devto", ...], ...}`` across registered adapters."""
    grouped: dict[str, list[str]] = {}
    for adapter in ADAPTER_CLASSES:
        grouped.setdefault(str(adapter.category), []).append(adapter.platform)
    return {key: sorted(value) for key, value in sorted(grouped.items())}


__all__ = [
    "ADAPTER_CLASSES",
    "CodewarsAdapter",
    "CratesIoAdapter",
    "DockerHubAdapter",
    "DuolingoAdapter",
    "HackerNewsAdapter",
    "HuggingFaceAdapter",
    "LastFmAdapter",
    "LaunchpadAdapter",
    "MediumAdapter",
    "YouTubeAdapter",
    "ScratchAdapter",
    "SoundCloudAdapter",
    "SourceCategory",
    "StackOverflowAdapter",
    "SteamAdapter",
    "TelegramAdapter",
    "XmlProfileAdapter",
    "adapters_by_category",
    "BlueskyAdapter",
    "DevToAdapter",
    "FacebookAdapter",
    "FailureReason",
    "GitHubAdapter",
    "KeybaseAdapter",
    "MastodonAdapter",
    "InstagramAdapter",
    "JsonProfileAdapter",
    "LookupResult",
    "ObservedProfile",
    "OpenGraphProfileAdapter",
    "RedditAdapter",
    "SafeFetcher",
    "SourceAdapter",
    "SourceError",
    "SourceRegistry",
    "ThreadsAdapter",
    "WebsiteAdapter",
    "build_registry",
]
