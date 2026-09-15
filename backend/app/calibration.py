"""Measure the correlation model instead of asserting it.

Every weight in :class:`ScoringConfig` is a number somebody chose.  An
explicit cross-platform link is worth seventy points, a similar username five,
and until now the only argument for either was that they seemed about right.
This turns that into a measurement: given pairs of profiles whose relationship
is already known, how well does the score separate the pairs that belong
together from the pairs that do not, and where should the confidence bands
sit.

Where the labels come from
--------------------------

From the accounts themselves.  A profile that publishes a link to another -
in a Gravatar's verified accounts, a Linktree, a Keybase proof - has declared
the connection, and a declaration by the owner is the strongest ground truth
public data offers.  Negative pairs are accounts that are demonstrably
different parties: different people who happen to share a first name, an
employer, or a handle pattern.

The circularity, and what is done about it
------------------------------------------

If the label comes from an explicit link and the model scores explicit links
at seventy, then measuring the model on those pairs mostly measures whether it
can read a link it was told about.  That is not a finding.

So the harness runs twice.  *With* the explicit link, which says whether the
model works at all, and - the interesting one - *without* it, which asks
whether the remaining signals could have recovered a connection we know is
real from a matching name, a shared employer, a reused photograph and a
similar biography alone.  The second number is the one worth quoting, and the
one that says whether the inferential half of the model earns its place.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .config import ScoringConfig, get_settings
from .services.correlation import CorrelationEngine
from .sources.base import ObservedProfile
from .utils.logging import get_logger

logger = get_logger(__name__)

#: Labelled pairs live beside the code so a run is reproducible and offline.
DATASET = Path(__file__).resolve().parent.parent / "calibration" / "pairs.json"

#: Evidence that simply restates the label, excluded in the blind pass.
DECLARED_TYPES = frozenset({"EXPLICIT_LINK"})


@dataclass
class Pair:
    """Two profiles and whether they are known to be the same party."""

    name: str
    same: bool
    source: ObservedProfile
    target: ObservedProfile
    #: How the label was established, so a reader can check it.
    basis: str = ""


@dataclass
class Outcome:
    """What the model said about one pair."""

    pair: Pair
    score: float
    level: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class Report:
    """Scores for every pair, and the measurements drawn from them."""

    outcomes: list[Outcome]
    blind: bool

    @property
    def positives(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.pair.same]

    @property
    def negatives(self) -> list[Outcome]:
        return [o for o in self.outcomes if not o.pair.same]

    def at_threshold(self, threshold: float) -> dict[str, float]:
        """Precision, recall and F1 if this score were the cut-off."""
        true_positive = sum(1 for o in self.positives if o.score >= threshold)
        false_negative = len(self.positives) - true_positive
        false_positive = sum(1 for o in self.negatives if o.score >= threshold)
        true_negative = len(self.negatives) - false_positive

        precision = true_positive / (true_positive + false_positive or 1)
        recall = true_positive / (true_positive + false_negative or 1)
        f1 = 2 * precision * recall / ((precision + recall) or 1)
        return {
            "threshold": threshold,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "tp": true_positive,
            "fp": false_positive,
            "fn": false_negative,
            "tn": true_negative,
        }

    def separation(self) -> tuple[float, float]:
        """Mean score of the pairs that match, and of the pairs that do not."""
        def mean(items: list[Outcome]) -> float:
            return sum(o.score for o in items) / (len(items) or 1)

        return mean(self.positives), mean(self.negatives)

    #: Evidence that argues *against* a pair, and is therefore meant to fire
    #: on the different-party ones.
    CONTRADICTING = frozenset({"CONTRADICTORY_ATTRIBUTE"})

    def evidence_usage(self) -> dict[str, tuple[int, int]]:
        """How often each evidence type fires on a true pair, and a false one.

        The actionable column, and the one that found two real faults the
        first time it was read. Read it by direction: a supporting signal
        should favour the same-party column, and a contradiction should favour
        the other. A supporting signal that fires as readily on strangers is
        contributing noise whatever weight it carries - and one that fires
        *more* on true pairs than false ones, as the website contradiction
        did, is subtracting points from the pairs it should support.
        """
        usage: dict[str, list[int]] = {}
        for outcome in self.outcomes:
            for kind in set(outcome.evidence):
                counts = usage.setdefault(kind, [0, 0])
                counts[0 if outcome.pair.same else 1] += 1
        return {kind: (yes, no) for kind, (yes, no) in usage.items()}


def load_pairs(path: Path | None = None) -> list[Pair]:
    """Read the labelled dataset."""
    source = path or DATASET
    raw = json.loads(source.read_text())
    pairs = []
    for entry in raw["pairs"]:
        pairs.append(
            Pair(
                name=entry["name"],
                same=bool(entry["same"]),
                basis=entry.get("basis", ""),
                source=ObservedProfile(**entry["a"]),
                target=ObservedProfile(**entry["b"]),
            )
        )
    return pairs


def evaluate(
    pairs: list[Pair], *, blind: bool = False, scoring: ScoringConfig | None = None
) -> Report:
    """Score every pair.

    ``blind`` drops the evidence that merely restates the label, leaving the
    model to recover the connection from what it inferred.
    """
    engine = CorrelationEngine(scoring or get_settings().scoring)
    outcomes = []
    for pair in pairs:
        result = engine.compare(pair.source, pair.target)
        items = [
            item
            for item in result.evidence
            if not (blind and str(item.type) in DECLARED_TYPES)
        ]
        score = max(0.0, min(100.0, sum(item.weight for item in items)))
        outcomes.append(
            Outcome(
                pair=pair,
                score=score,
                level=_band(score, scoring or get_settings().scoring),
                evidence=[str(item.type) for item in items],
            )
        )
    return Report(outcomes=outcomes, blind=blind)


def _band(score: float, scoring: ScoringConfig) -> str:
    for minimum, label in scoring.bands:
        if score >= minimum:
            return label
    return "LOW"


def render(report: Report) -> None:
    """Print one pass of the measurement."""
    heading = (
        "WITHOUT the declared link (can the model infer it?)"
        if report.blind
        else "WITH every signal (does the model work at all?)"
    )
    print(f"\n  {heading}")
    print(f"  {len(report.positives)} pairs known same, {len(report.negatives)} known different")

    same_mean, different_mean = report.separation()
    print(f"  mean score: {same_mean:.1f} when same, {different_mean:.1f} when different")

    print("\n    threshold  precision  recall     F1     tp  fp  fn  tn")
    for threshold in (20, 35, 50, 65, 75):
        m = report.at_threshold(threshold)
        print(
            f"    {m['threshold']:>9.0f}  {m['precision']:>9.2f}  {m['recall']:>6.2f}"
            f"  {m['f1']:>6.2f}  {m['tp']:>3} {m['fp']:>3} {m['fn']:>3} {m['tn']:>3}"
        )

    print("\n    evidence type              fires on same  on different")
    for kind, (yes, no) in sorted(
        report.evidence_usage().items(), key=lambda kv: -kv[1][0]
    ):
        contradicting = kind in Report.CONTRADICTING
        if contradicting:
            # Wanted on the right-hand column: that is its job.
            flag = "" if no > yes else "  <- a contradiction that favours true pairs"
        else:
            flag = "  <- fires as readily on strangers" if no >= yes and yes else ""
        print(f"    {kind:<26}{yes:>13}  {no:>12}{flag}")

    missed = [o for o in report.positives if o.score < 50]
    if missed:
        print("\n    known-same pairs the model scored under 50:")
        for outcome in sorted(missed, key=lambda o: o.score)[:6]:
            print(f"      {outcome.score:>5.0f}  {outcome.pair.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.calibration",
        description="Measure how well the correlation model separates known pairs.",
    )
    parser.add_argument("--dataset", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        pairs = load_pairs(args.dataset)
    except FileNotFoundError:
        print(f"No dataset at {args.dataset or DATASET}", file=sys.stderr)
        return 2

    print(f"Calibrating against {len(pairs)} labelled pairs.")
    render(evaluate(pairs, blind=False))
    render(evaluate(pairs, blind=True))
    print(
        "\n  The second table is the one worth quoting: the first largely\n"
        "  measures whether the model can read a link it was handed."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit(main())
