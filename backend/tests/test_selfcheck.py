"""The self-check: asking every source two questions it should know.

Borrowed from Maigret, which validates each site in its database against a
username known to be claimed and one known to be free. This project needed it
for the same reason Maigret does, and had already been bitten twice: a
hardcoded Accept header once made every adapter fail live while every mocked
test passed, and Telegram reported an account for every handle on earth for
months because t.me never sends a 404.

Parsing tests cannot catch either. They run against saved HTML, which is
precisely the HTML that stopped arriving.
"""

from __future__ import annotations

import pytest

from app.selfcheck import Health, check, report
from app.sources.base import (
    FailureReason,
    LookupResult,
    ObservedProfile,
    SourceAdapter,
    SourceError,
)


class Stub(SourceAdapter):
    """An adapter whose answers the test decides."""

    platform = "stub"
    name = "Stub"
    probe_present = "somebody"
    probe_absent = "nobody-at-all"

    def __init__(self, *, finds: set[str] | None = None, raises=None, fails=None):
        self.finds = finds if finds is not None else {"somebody"}
        self.raises = raises
        self.fails = fails

    async def lookup(self, identifier: str) -> LookupResult:
        if self.raises:
            raise self.raises
        if self.fails:
            return LookupResult.failure(SourceError(self.fails, "nope"))
        if identifier in self.finds:
            return LookupResult(
                entities=[
                    ObservedProfile(
                        platform=self.platform, identifier=identifier, name=identifier
                    )
                ]
            )
        return LookupResult()


async def test_a_working_source_passes() -> None:
    result = await check(Stub())

    assert result.health is Health.OK
    assert result.ok


async def test_a_source_that_finds_everybody_is_the_worst_case() -> None:
    """Telegram, for months. Every guess becomes a scored node on the graph."""
    result = await check(Stub(finds={"somebody", "nobody-at-all"}))

    assert result.health is Health.BLIND
    assert not result.ok
    assert "nobody-at-all" in result.detail


async def test_a_source_that_finds_nobody_is_reported() -> None:
    """The site changed its markup and the adapter stopped working."""
    result = await check(Stub(finds=set()))

    assert result.health is Health.MISSING
    assert not result.ok


@pytest.mark.parametrize(
    "reason",
    [
        FailureReason.BLOCKED,
        FailureReason.RATE_LIMITED,
        FailureReason.TIMEOUT,
        FailureReason.NETWORK_ERROR,
    ],
)
async def test_a_platform_that_would_not_answer_is_not_a_verdict(reason) -> None:
    """Being blocked today says nothing about whether the adapter works."""
    result = await check(Stub(fails=reason))

    assert result.health is Health.UNAVAILABLE
    assert result.ok, "not something to fix in the adapter"


async def test_a_broken_adapter_does_not_stop_the_run() -> None:
    result = await check(Stub(raises=RuntimeError("boom")))

    assert result.health is Health.UNAVAILABLE
    assert "boom" in result.detail


async def test_a_source_with_no_probe_declares_itself_unchecked() -> None:
    """Better than silently passing: the website adapter takes a URL."""

    class NoProbe(Stub):
        probe_present = ""

    result = await check(NoProbe())

    assert result.health is Health.UNCONFIGURED
    assert result.ok


def test_the_report_fails_the_process_when_a_source_is_broken(capsys) -> None:
    from app.selfcheck import Result

    healthy = [Result("a", "A", Health.OK)]
    broken = [Result("a", "A", Health.OK), Result("b", "B", Health.BLIND)]

    assert report(healthy) == 0
    assert report(broken) == 1
    assert "Needs attention" in capsys.readouterr().out


def test_every_registered_adapter_declares_a_probe() -> None:
    """A source nobody can check is a source that can rot unnoticed."""
    from app.sources import ADAPTER_CLASSES

    unchecked = [
        adapter.platform
        for adapter in ADAPTER_CLASSES
        if not adapter.probe_present
        # The website adapter is handed a URL, not a handle, so there is no
        # single page that stands for "this source works".
        and adapter.platform != "website"
    ]

    assert unchecked == [], f"no probe handle for: {unchecked}"
