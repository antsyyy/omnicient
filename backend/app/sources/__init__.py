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
from .base import (
    FailureReason,
    JsonProfileAdapter,
    LookupResult,
    ObservedProfile,
    OpenGraphProfileAdapter,
    SafeFetcher,
    SourceAdapter,
    SourceError,
)
from .bluesky import BlueskyAdapter
from .devto import DevToAdapter
from .facebook import FacebookAdapter
from .github import GitHubAdapter
from .instagram import InstagramAdapter
from .keybase import KeybaseAdapter
from .mastodon import MastodonAdapter
from .reddit import RedditAdapter
from .threads import ThreadsAdapter
from .website import WebsiteAdapter

logger = get_logger(__name__)

#: Adapters shipped with the MVP.  Future adapters (X, LinkedIn, YouTube,
#: Mastodon, GitLab) are registered here and nowhere else.
ADAPTER_CLASSES: tuple[type[SourceAdapter], ...] = (
    # Sources whose robots.txt permits anonymous lookups, so they work live.
    GitHubAdapter,
    KeybaseAdapter,
    MastodonAdapter,
    BlueskyAdapter,
    DevToAdapter,
    WebsiteAdapter,
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


__all__ = [
    "ADAPTER_CLASSES",
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
