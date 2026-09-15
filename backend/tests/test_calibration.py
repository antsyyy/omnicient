"""The correlation model, measured against pairs whose answer is known.

Two jobs. The harness has to compute honest numbers, and - once it does - the
numbers become a floor the scoring model may not drop below. A weight tweaked
by feel can otherwise quietly undo the separation it took a measurement to
establish, and nothing else in the suite would notice.
"""

from __future__ import annotations

import pytest

from app.calibration import DATASET, Report, evaluate, load_pairs


@pytest.fixture(scope="module")
def pairs():
    if not DATASET.exists():
        pytest.skip(f"no labelled dataset at {DATASET}")
    return load_pairs()


# ---------------------------------------------------------------------------
# The dataset itself
# ---------------------------------------------------------------------------


def test_every_positive_label_cites_how_it_was_established(pairs) -> None:
    """A label with no basis is an opinion, and calibrating on opinions is
    calibrating on nothing. Each 'same' says where the owner declared it."""
    for pair in pairs:
        if pair.same:
            assert pair.basis, f"{pair.name} claims same party with no stated basis"


def test_the_dataset_has_both_answers(pairs) -> None:
    assert sum(1 for p in pairs if p.same) >= 5
    assert sum(1 for p in pairs if not p.same) >= 10


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------


def test_the_model_separates_known_pairs(pairs) -> None:
    """With everything it observed, including the declared link."""
    report = evaluate(pairs, blind=False)
    same, different = report.separation()

    assert same > different * 3, f"{same:.1f} vs {different:.1f} is not separation"


def test_the_model_can_infer_a_link_it_was_not_told(pairs) -> None:
    """The measurement that matters, and the reason for the blind pass.

    Labels come from links the owner published, and the model scores an
    explicit link at seventy - so scoring those pairs *with* the link mostly
    measures whether it can read. Dropping it asks the real question: from a
    matching name, a reused photograph, a shared employer and a similar
    biography, can it recover a connection we independently know is there?
    """
    report = evaluate(pairs, blind=True)
    same, different = report.separation()

    assert same > 25, f"inferred score on known-same pairs is only {same:.1f}"
    assert different < 10, f"unrelated pairs are scoring {different:.1f}"


def test_a_usable_threshold_exists(pairs) -> None:
    """Some cut-off has to be worth using, or the score means nothing."""
    report = evaluate(pairs, blind=True)
    best = max(
        (report.at_threshold(t) for t in range(5, 80, 5)), key=lambda m: m["f1"]
    )

    assert best["f1"] >= 0.80, f"best F1 is only {best['f1']:.2f}"


def test_high_scores_are_not_wrong(pairs) -> None:
    """Precision at the top matters more than recall.

    An analyst can go looking for a link the model missed. A confident score
    on two strangers is the failure this project cannot afford.
    """
    report = evaluate(pairs, blind=True)

    assert report.at_threshold(50)["fp"] == 0, "a stranger scored 50 or more"


# ---------------------------------------------------------------------------
# The two faults this harness found the first time it ran
# ---------------------------------------------------------------------------


def test_the_avatar_rule_fires_on_real_pairs(pairs) -> None:
    """It fired on nothing at all until the threshold was measured.

    The rule had been comparing URLs, which never match across platforms;
    given hashes and a threshold picked by taste it still matched nothing,
    because the same photograph re-encoded by two sites sits further apart
    than the guess allowed.
    """
    report = evaluate(pairs, blind=True)
    usage = report.evidence_usage()
    fires_on_same, fires_on_different = usage.get("SAME_AVATAR", (0, 0))

    assert fires_on_same >= 3, "the avatar rule is not firing on known-same pairs"
    assert fires_on_different == 0, "the avatar rule is matching strangers"


def test_no_supporting_signal_favours_strangers(pairs) -> None:
    """A signal that fires more on unrelated pairs is worse than absent.

    The website contradiction did exactly this - it fired on three known-same
    pairs and two known-different ones, subtracting twenty points from the
    pairs it should have supported.
    """
    report = evaluate(pairs, blind=True)
    for kind, (same, different) in report.evidence_usage().items():
        if kind in Report.CONTRADICTING:
            # A contradiction is supposed to favour the different-party pairs.
            assert different >= same, f"{kind} favours true pairs"
        else:
            assert same > different, f"{kind} fires on {different} strangers, {same} true"
