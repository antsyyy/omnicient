"""Ask every source two questions it should already know the answer to.

Adapters rot silently.  A platform changes its markup and an adapter stops
finding anybody; or it starts answering 200 with a card for every URL and the
adapter starts finding *everybody*.  Both failures pass the test suite,
because the suite tests parsing against saved HTML - which is exactly the HTML
that has stopped arriving.

This project has now been bitten by both.  A hardcoded ``Accept`` header meant
GitHub answered 415 and no adapter worked live, while every mocked test
passed.  Telegram reported an account for every handle on earth for months,
because ``t.me`` never sends a 404.

So each adapter names a handle that genuinely exists on its platform and one
that does not, and this asks both.  Four outcomes:

``OK``
    Found the real one, refused the fake one.  The adapter can still be wrong
    about details, but it is discriminating.
``BLIND``
    Claimed to find the handle that does not exist.  The worst failure: every
    guess the crawler makes on this platform becomes a scored node.
``MISSING``
    Could not find the handle that does.  Either the site changed or the
    probe handle is gone; either way the source is contributing nothing.
``UNAVAILABLE``
    The platform refused, timed out, or rate limited.  Not a verdict on the
    adapter - it just could not be asked right now.

Run it with ``python -m app.selfcheck``, optionally naming platforms.  It
makes live requests, so it is deliberately not part of the test suite and not
exposed as an endpoint anybody can trigger.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from enum import StrEnum

from .config import get_settings
from .sources import ADAPTER_CLASSES
from .sources.base import SafeFetcher, SourceAdapter
from .utils.logging import get_logger

logger = get_logger(__name__)


class Health(StrEnum):
    OK = "OK"
    BLIND = "BLIND"
    MISSING = "MISSING"
    UNAVAILABLE = "UNAVAILABLE"
    UNCONFIGURED = "UNCONFIGURED"


#: What each verdict means, for whoever reads the output.
EXPLANATION: dict[str, str] = {
    Health.OK: "found the real handle, refused the fake one",
    Health.BLIND: "reported a profile for a handle that does not exist",
    Health.MISSING: "could not find a handle that is known to be there",
    Health.UNAVAILABLE: "the platform could not be reached",
    Health.UNCONFIGURED: "no probe handle declared, so nothing was checked",
}


@dataclass
class Result:
    """One adapter's verdict."""

    platform: str
    name: str
    health: Health
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.health in (Health.OK, Health.UNAVAILABLE, Health.UNCONFIGURED)


async def check(adapter: SourceAdapter) -> Result:
    """Ask one adapter about a handle that exists and one that does not."""
    if not adapter.probe_present:
        return Result(adapter.platform, adapter.name, Health.UNCONFIGURED)

    try:
        present = await adapter.lookup(adapter.probe_present)
    except Exception as error:  # noqa: BLE001 - a broken adapter must not stop the run
        return Result(
            adapter.platform, adapter.name, Health.UNAVAILABLE, repr(error)
        )

    if present.primary is None:
        # Distinguish "the site said no" from "the site would not answer".
        reason = str(present.reason or "no profile parsed")
        health = (
            Health.UNAVAILABLE
            if present.reason in ("BLOCKED", "RATE_LIMITED", "TIMEOUT", "NETWORK_ERROR")
            else Health.MISSING
        )
        return Result(
            adapter.platform,
            adapter.name,
            health,
            f"{adapter.probe_present}: {reason}",
        )

    try:
        absent = await adapter.lookup(adapter.probe_absent)
    except Exception as error:  # noqa: BLE001
        return Result(adapter.platform, adapter.name, Health.UNAVAILABLE, repr(error))

    if absent.primary is not None:
        return Result(
            adapter.platform,
            adapter.name,
            Health.BLIND,
            f"invented a profile for '{adapter.probe_absent}'",
        )

    return Result(adapter.platform, adapter.name, Health.OK, adapter.probe_present)


async def run(platforms: list[str] | None = None) -> list[Result]:
    """Check every registered adapter, or only the ones named."""
    settings = get_settings()
    fetcher = SafeFetcher(settings)
    wanted = {p.lower() for p in platforms or []}
    adapters = [
        cls(fetcher)  # type: ignore[call-arg]
        for cls in ADAPTER_CLASSES
        if not wanted or cls.platform.lower() in wanted
    ]
    try:
        # Sequential on purpose: this is a diagnostic, and hammering two dozen
        # platforms at once to diagnose rate limiting would be self-defeating.
        return [await check(adapter) for adapter in adapters]
    finally:
        await fetcher.aclose()


def report(results: list[Result]) -> int:
    """Print the verdicts, worst first. Returns a process exit code."""
    order = {
        Health.BLIND: 0,
        Health.MISSING: 1,
        Health.UNAVAILABLE: 2,
        Health.UNCONFIGURED: 3,
        Health.OK: 4,
    }
    for result in sorted(results, key=lambda r: (order[r.health], r.platform)):
        print(f"  {result.health.value:<13}{result.name:<16}{result.detail}")

    broken = [r for r in results if not r.ok]
    counts: dict[str, int] = {}
    for result in results:
        counts[result.health.value] = counts.get(result.health.value, 0) + 1
    print(f"\n  {len(results)} sources: " + ", ".join(
        f"{count} {health.lower()}" for health, count in sorted(counts.items())
    ))
    if broken:
        print("\n  Needs attention:")
        for result in broken:
            print(f"    {result.name}: {EXPLANATION[result.health]}")
    return 1 if broken else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.selfcheck",
        description="Check each source against a handle that exists and one that does not.",
    )
    parser.add_argument(
        "platforms",
        nargs="*",
        help="Platforms to check; defaults to all of them.",
    )
    args = parser.parse_args(argv)
    print("Checking sources against live pages...\n")
    return report(asyncio.run(run(args.platforms)))


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit(main())
