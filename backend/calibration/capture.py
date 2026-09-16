"""Capture public profiles, and find the pairs their owners have declared.

The calibration dataset needs two things that are awkward to write by hand:
real profiles, and labels that do not come from the model under test.  This
produces both.

Capturing is the easy half - it runs the project's own adapters, so a captured
profile is exactly what a crawl would have seen, including the avatar hash.

The labels are the interesting half.  ``--suggest`` reads the captured
profiles and looks for one profile linking to another's canonical URL: a
Gravatar's verified accounts, a Linktree's list, a bio that names a handle
elsewhere.  That link is a statement by the account owner, made before this
project existed and for their own reasons, which is the strongest ground truth
public data offers and - crucially - is not something the correlation model
produced.  Suggestions are printed for a human to accept, never written
straight into the dataset: the tool proposes, the reviewer disposes.

Negative pairs cannot be discovered this way, because nobody publishes a list
of people they are not.  Those are chosen deliberately - accounts that share a
first name, an employer or a handle pattern and are demonstrably different
parties - and are the harder half of the dataset to build.

  python -m calibration.capture fetch github:simonw mastodon:simon@simonwillison.net
  python -m calibration.capture suggest

Politeness: this goes out over the network to real sites, through the same
SafeFetcher the crawler uses, with the same per-host delay.  It fetches each
profile once and caches, and is meant to be run occasionally to extend the
dataset - not in a loop, and not in CI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
PROFILES = HERE / "profiles.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


def _canonical(url: str | None) -> str:
    """A URL reduced to the part that identifies who it points at.

    Scheme, ``www.`` and trailing slashes vary between the address a site
    publishes and the one it links to; none of that changes whose profile it
    is.
    """
    if not url:
        return ""
    parts = urlsplit(url.strip().lower())
    host = parts.netloc.removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}"


async def fetch(targets: list[str]) -> int:
    """Fetch each ``platform:identifier`` and record what it returned."""
    os.environ["OMNICIENT_DEMO_MODE"] = "false"

    from app.services.avatars import AvatarHasher
    from app.sources import build_registry

    registry = build_registry()
    profiles = _load(PROFILES)
    captured = []
    failed = []

    try:
        for target in targets:
            platform, _, identifier = target.partition(":")
            adapter = registry.get(platform)
            if adapter is None:
                failed.append(f"{target} (no adapter for {platform!r})")
                continue
            try:
                result = await adapter.lookup(identifier)
            except Exception as error:  # noqa: BLE001 - one bad target must not end the run
                failed.append(f"{target} ({type(error).__name__}: {error})")
                continue
            if not result.ok or not result.primary:
                failed.append(f"{target} ({result.reason or 'nothing public found'})")
                continue
            captured.append(result.primary)
            print(f"  captured {target}: {result.primary.display_name or '-'}")

        if captured:
            # The hash is part of the observation, so it belongs in the
            # dataset rather than being recomputed at scoring time.
            hashed = await AvatarHasher().apply(captured)
            print(f"  hashed {hashed} avatar(s)")
    finally:
        await registry.aclose()

    for profile in captured:
        key = f"{profile.platform}:{profile.identifier}"
        profiles[key] = json.loads(profile.model_dump_json())

    if captured:
        _save(PROFILES, profiles)
        print(f"\n{len(captured)} captured, {len(profiles)} profiles on file.")
    for line in failed:
        print(f"  no capture: {line}", file=sys.stderr)
    return 0 if captured else 1


def suggest() -> int:
    """Print pairs where one profile's owner has linked to the other."""
    profiles = _load(PROFILES)
    if not profiles:
        print("No profiles captured yet.", file=sys.stderr)
        return 1

    # Only a profile's own canonical address counts as somewhere to be
    # declared. Indexing the websites it lists as well seems helpful and is
    # not: the first run of this matched two Automattic employees through
    # wordpress.com and two more through automattic.com, because a shared
    # employer is a link both profiles publish and neither one asserts. A
    # declaration has to point at the *person*.
    addresses: dict[str, str] = {}
    for key, profile in profiles.items():
        if canonical := _canonical(profile.get("url")):
            addresses.setdefault(canonical, key)

    found: dict[tuple[str, str], list[str]] = {}
    for key, profile in profiles.items():
        for link in list(profile.get("external_links") or []):
            other = addresses.get(_canonical(link))
            if not other or other == key:
                continue
            # Same platform is not a cross-platform declaration.
            if profile.get("platform") == profiles[other].get("platform"):
                continue
            found.setdefault(tuple(sorted((key, other))), []).append(link)

    if not found:
        print("No declared links among the captured profiles.")
        print("Capture more of one person's accounts, or ones that publish a link list.")
        return 0

    print(f"{len(found)} directly declared link(s):\n")
    for (a, b), links in sorted(found.items()):
        print(f"  {a}  <->  {b}")
        print(f"      declared by: {links[0]}")

    clusters = _clusters(found)
    indirect = []
    for members in clusters:
        ordered = sorted(members)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                if (a, b) not in found:
                    indirect.append((a, b))

    if indirect:
        print(f"\n{len(indirect)} pair(s) implied by a chain of declarations:\n")
        for a, b in indirect:
            print(f"  {a}  <->  {b}")
        print(
            "\nThese are the valuable ones. Neither profile links to the other, so\n"
            "the model cannot read the answer off the page - it has to recover the\n"
            "connection from a name, a photograph, a handle, a biography. That is\n"
            "exactly what the blind pass measures, and a dataset of directly\n"
            "declared pairs alone cannot test it."
        )

    print(
        "\nReview each before adding it to pairs.json, with a basis naming the\n"
        "declaration. A link is a strong claim, not a certain one: shared team\n"
        "accounts and 'my other project' links both look like this, and a chain\n"
        "of them inherits every doubt in the chain."
    )
    return 0


def _clusters(found: dict[tuple[str, str], list[str]]) -> list[set[str]]:
    """Group profiles that a chain of declarations ties together.

    If A declares B and B declares C, then A and C are the same party even
    though neither mentions the other - which makes that pair worth far more
    to the dataset than either declared one.
    """
    groups: list[set[str]] = []
    for a, b in found:
        touching = [g for g in groups if a in g or b in g]
        merged = {a, b}
        for group in touching:
            merged |= group
            groups.remove(group)
        groups.append(merged)
    return [g for g in groups if len(g) > 2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m calibration.capture")
    sub = parser.add_subparsers(dest="command", required=True)
    grab = sub.add_parser("fetch", help="capture profiles from live sources")
    grab.add_argument("targets", nargs="+", metavar="platform:identifier")
    sub.add_parser("suggest", help="find owner-declared links among captured profiles")

    args = parser.parse_args(argv)
    if args.command == "fetch":
        return asyncio.run(fetch(args.targets))
    return suggest()


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit(main())
