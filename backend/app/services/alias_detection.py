"""Alias detection: explainable username-variant analysis.

Two handles being *similar* is a weak signal. Handles are short, reused, and
built from common words, so string similarity alone produces false positives at
an embarrassing rate - ``alex`` and ``alexander`` share a prefix and nothing
else. This module therefore does two separate things and keeps them separate:

1. **Identify the transformation.** Which deterministic edit turns one handle
   into the other - case, separator substitution, separator removal, a numeric
   suffix, a known role suffix? A named transformation is explainable; a
   distance score is not.
2. **Weigh it against context.** A transformation earns a *potential alias*.
   Whether it rises above that depends on evidence the correlation engine
   already collected: a shared website, email, avatar, organization or display
   name.

The output is always ``POTENTIAL_ALIAS`` - a claim about the *handles*, never
about the people behind them. Analyst confirmation is what promotes it, and
even then it means "the evidence was reviewed and judged supportive".

No machine learning and no LLM: every result names the rule that produced it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import StrEnum
from itertools import combinations

from ..config import ScoringConfig, get_settings
from ..models.enums import ConfidenceLevel, EvidenceType
from ..sources.base import ObservedProfile
from ..utils.logging import get_logger
from ..utils.normalization import SEPARATORS
from .correlation import CorrelationResult, EvidenceItem

logger = get_logger(__name__)

#: A root token shorter than this proves nothing: "al", "dev", "the".
MIN_ROOT_TOKEN = 4

#: Two handles must reach this normalized similarity before any transformation
#: is even considered.  Deliberately high - this is the false-positive gate.
MIN_SIMILARITY = 0.62

#: Role/context words people append to a handle on a second platform.
COMMON_SUFFIXES = (
    "security", "sec", "dev", "devs", "code", "codes", "official", "real",
    "the", "hq", "team", "art", "arts", "photo", "photos", "music", "gaming",
    "tv", "yt", "live", "blog", "io", "app", "labs", "studio", "work",
)

#: Words people prepend.
COMMON_PREFIXES = ("the", "real", "official", "im", "iam", "its", "mr", "ms")

#: Tokens too generic to count as a shared root even when long enough.
GENERIC_TOKENS = frozenset(
    {
        "admin", "user", "users", "team", "info", "mail", "email", "test",
        "official", "support", "contact", "hello", "there", "root", "guest",
        "security", "developer", "design", "media", "online", "world",
    }
)

_SPLIT_RE = re.compile(r"[._\-]+")
_TRAILING_DIGITS_RE = re.compile(r"^(?P<stem>.*?)(?P<digits>\d{1,6})$")


class Transformation(StrEnum):
    """A named, deterministic edit between two handles."""

    IDENTICAL = "IDENTICAL"
    CASE_ONLY = "CASE_ONLY"
    SEPARATOR_SUBSTITUTION = "SEPARATOR_SUBSTITUTION"
    SEPARATOR_REMOVED = "SEPARATOR_REMOVED"
    SEPARATOR_ADDED = "SEPARATOR_ADDED"
    NUMERIC_SUFFIX_ADDED = "NUMERIC_SUFFIX_ADDED"
    NUMERIC_SUFFIX_REMOVED = "NUMERIC_SUFFIX_REMOVED"
    NUMERIC_SUFFIX_CHANGED = "NUMERIC_SUFFIX_CHANGED"
    COMMON_SUFFIX_ADDED = "COMMON_SUFFIX_ADDED"
    COMMON_PREFIX_ADDED = "COMMON_PREFIX_ADDED"
    SHARED_ROOT_TOKEN = "SHARED_ROOT_TOKEN"
    EDIT_SIMILARITY = "EDIT_SIMILARITY"


#: How much each transformation contributes to alias similarity.  A rename that
#: preserves every character (case, separators) is far stronger than one that
#: adds a whole new word.
TRANSFORMATION_WEIGHT: dict[str, float] = {
    Transformation.IDENTICAL: 1.00,
    Transformation.CASE_ONLY: 0.95,
    Transformation.SEPARATOR_SUBSTITUTION: 0.90,
    Transformation.SEPARATOR_REMOVED: 0.88,
    Transformation.SEPARATOR_ADDED: 0.88,
    Transformation.NUMERIC_SUFFIX_REMOVED: 0.72,
    Transformation.NUMERIC_SUFFIX_ADDED: 0.72,
    Transformation.NUMERIC_SUFFIX_CHANGED: 0.45,
    Transformation.COMMON_SUFFIX_ADDED: 0.60,
    Transformation.COMMON_PREFIX_ADDED: 0.60,
    Transformation.SHARED_ROOT_TOKEN: 0.50,
    Transformation.EDIT_SIMILARITY: 0.35,
}

#: Human-readable explanation shown next to each detected transformation.
TRANSFORMATION_LABEL: dict[str, str] = {
    Transformation.IDENTICAL: "Identical handle",
    Transformation.CASE_ONLY: "Differs only by letter case",
    Transformation.SEPARATOR_SUBSTITUTION: "Separator substitution (_ ↔ - ↔ .)",
    Transformation.SEPARATOR_REMOVED: "Separator removed",
    Transformation.SEPARATOR_ADDED: "Separator added",
    Transformation.NUMERIC_SUFFIX_ADDED: "Numeric suffix added",
    Transformation.NUMERIC_SUFFIX_REMOVED: "Numeric suffix removed",
    Transformation.NUMERIC_SUFFIX_CHANGED: "Different numeric suffix",
    Transformation.COMMON_SUFFIX_ADDED: "Common suffix added",
    Transformation.COMMON_PREFIX_ADDED: "Common prefix added",
    Transformation.SHARED_ROOT_TOKEN: "Shared root token",
    Transformation.EDIT_SIMILARITY: "Close edit similarity",
}


class AliasStrength(StrEnum):
    """How strongly the handles resemble one another.

    Separate from :class:`ConfidenceLevel`, which bands the *overall* score
    once contextual evidence is folded in.  A pair can look alike and still be
    unconvincing, which is exactly the case this vocabulary has to express.
    """

    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    NONE = "NONE"


@dataclass
class AliasSignal:
    """One reason a pair was proposed, and what it was worth."""

    kind: str
    label: str
    detail: str
    weight: float = 0.0


@dataclass
class AliasCandidate:
    """A potential alias pair, with everything behind it."""

    source_identifier: str
    target_identifier: str
    similarity: float
    strength: AliasStrength
    transformations: list[str] = field(default_factory=list)
    signals: list[AliasSignal] = field(default_factory=list)
    supporting_evidence: list[EvidenceItem] = field(default_factory=list)
    contradicting_evidence: list[EvidenceItem] = field(default_factory=list)
    score: float = 0.0
    confidence: str = ConfidenceLevel.LOW
    #: Always UNREVIEWED here; the analyst owns promotion.
    status: str = "UNREVIEWED"
    source_entity_id: str | None = None
    target_entity_id: str | None = None
    source_platform: str | None = None
    target_platform: str | None = None

    @property
    def summary(self) -> str:
        """One line an analyst can read without opening the detail."""
        labels = ", ".join(
            TRANSFORMATION_LABEL.get(name, name).lower()
            for name in self.transformations[:2]
        )
        return (
            f"'{self.target_identifier}' is a potential alias of "
            f"'{self.source_identifier}' ({labels or 'similar spelling'})"
        )


# ---------------------------------------------------------------------------
# Reusable primitives
# ---------------------------------------------------------------------------


def normalize_alias_candidate(value: str | None) -> str:
    """Canonical comparison form for a handle: lowercase, trimmed edges."""
    if not value:
        return ""
    return str(value).strip().strip("".join(SEPARATORS)).lower()


def strip_separators(value: str) -> str:
    """``alice_98`` -> ``alice98``: the separator-blind skeleton."""
    return _SPLIT_RE.sub("", normalize_alias_candidate(value))


def extract_username_tokens(value: str | None) -> list[str]:
    """Split a handle into its word tokens.

    ``alice-security`` -> ``["alice", "security"]``. Digits are split off so a
    numeric suffix never hides the root: ``alice98`` -> ``["alice", "98"]``.
    """
    normalized = normalize_alias_candidate(value)
    if not normalized:
        return []
    tokens: list[str] = []
    for part in _SPLIT_RE.split(normalized):
        if not part:
            continue
        # Break letter/digit runs apart: "alice98" -> "alice", "98".
        tokens.extend(piece for piece in re.findall(r"[a-z]+|\d+", part) if piece)
    return tokens


def root_token(value: str | None) -> str | None:
    """The token a handle is built around, when there is a substantial one.

    Takes the *first* qualifying token rather than the longest: people put the
    name first and the role after it, so ``alice-security`` is rooted on
    "alice", not on the longer but far more generic "security".
    """
    for token in extract_username_tokens(value):
        if not token.isalpha():
            continue
        if len(token) >= MIN_ROOT_TOKEN and token not in GENERIC_TOKENS:
            return token
    return None


def calculate_username_similarity(a: str | None, b: str | None) -> float:
    """Similarity of two handles in ``[0.0, 1.0]``, separator-aware.

    Differs from :func:`app.utils.normalization.username_similarity` in that it
    compares the separator-blind skeletons, so ``alice_98`` and ``alice-98``
    score as the near-identical strings they are.
    """
    first, second = normalize_alias_candidate(a), normalize_alias_candidate(b)
    if not first or not second:
        return 0.0
    if first == second:
        return 1.0
    skeleton_a, skeleton_b = strip_separators(first), strip_separators(second)
    if skeleton_a and skeleton_a == skeleton_b:
        return 0.95
    return round(SequenceMatcher(None, skeleton_a, skeleton_b).ratio(), 3)


def _numeric_split(value: str) -> tuple[str, str | None]:
    """``alice98`` -> ``("alice", "98")``; ``alice`` -> ``("alice", None)``."""
    match = _TRAILING_DIGITS_RE.match(value)
    if not match:
        return value, None
    return match.group("stem"), match.group("digits")


def detect_transformations(a: str | None, b: str | None) -> list[str]:
    """Name every deterministic edit that relates two handles.

    Returns an empty list when nothing explainable connects them - which is the
    answer for ``alex`` / ``alexander``: a shared prefix is not a
    transformation, and this module refuses to invent one.
    """
    first, second = normalize_alias_candidate(a), normalize_alias_candidate(b)
    if not first or not second:
        return []
    if first == second:
        # Compare the raw spellings: normalization has already folded case, so
        # this is the only point at which a case-only difference is visible.
        return [
            str(
                Transformation.IDENTICAL
                if (a or "").strip() == (b or "").strip()
                else Transformation.CASE_ONLY
            )
        ]

    found: list[str] = []
    skeleton_a, skeleton_b = strip_separators(first), strip_separators(second)
    has_sep_a = any(sep in first for sep in SEPARATORS)
    has_sep_b = any(sep in second for sep in SEPARATORS)

    if skeleton_a == skeleton_b:
        if has_sep_a and has_sep_b:
            found.append(str(Transformation.SEPARATOR_SUBSTITUTION))
        elif has_sep_a:
            found.append(str(Transformation.SEPARATOR_REMOVED))
        else:
            found.append(str(Transformation.SEPARATOR_ADDED))
        return found

    stem_a, digits_a = _numeric_split(skeleton_a)
    stem_b, digits_b = _numeric_split(skeleton_b)
    if stem_a == stem_b and stem_a:
        if digits_a and digits_b:
            found.append(str(Transformation.NUMERIC_SUFFIX_CHANGED))
        elif digits_b:
            found.append(str(Transformation.NUMERIC_SUFFIX_ADDED))
        elif digits_a:
            found.append(str(Transformation.NUMERIC_SUFFIX_REMOVED))

    # A whole word appended or prepended, on top of a shared root.
    tokens_a, tokens_b = extract_username_tokens(first), extract_username_tokens(second)
    shared_root = root_token(first)
    if shared_root and shared_root == root_token(second):
        extra_a = [t for t in tokens_a if t != shared_root and t.isalpha()]
        extra_b = [t for t in tokens_b if t != shared_root and t.isalpha()]
        if any(token in COMMON_SUFFIXES for token in extra_b + extra_a):
            found.append(str(Transformation.COMMON_SUFFIX_ADDED))
        if tokens_a and tokens_b and (
            tokens_a[0] in COMMON_PREFIXES or tokens_b[0] in COMMON_PREFIXES
        ):
            found.append(str(Transformation.COMMON_PREFIX_ADDED))
        if str(Transformation.COMMON_SUFFIX_ADDED) not in found:
            found.append(str(Transformation.SHARED_ROOT_TOKEN))

    if not found:
        # Nothing named applies. Fall back to raw similarity only when it is
        # high enough to be worth an analyst's attention, and never for a mere
        # shared prefix: "alex"/"alexander" must not survive this.
        similarity = calculate_username_similarity(first, second)
        if similarity >= 0.85 and _not_merely_a_prefix(skeleton_a, skeleton_b):
            found.append(str(Transformation.EDIT_SIMILARITY))
    return found


def _not_merely_a_prefix(a: str, b: str) -> bool:
    """Reject pairs whose only relationship is that one starts with the other.

    ``alex``/``alexander`` and ``sam``/``samantha`` are different names, not
    variants of one handle.
    """
    shorter, longer = sorted((a, b), key=len)
    if not shorter or not longer.startswith(shorter):
        return True
    # A long common stem with a short tail is a plausible truncation; a short
    # stem with a long tail is two different words.
    return len(longer) - len(shorter) <= 2


def alias_strength(similarity: float, transformations: list[str]) -> AliasStrength:
    """Band the handle resemblance alone, before contextual evidence."""
    if not transformations:
        return AliasStrength.NONE
    best = max(
        (TRANSFORMATION_WEIGHT.get(name, 0.0) for name in transformations),
        default=0.0,
    )
    combined = (best * 0.7) + (similarity * 0.3)
    if combined >= 0.82:
        return AliasStrength.STRONG
    if combined >= 0.58:
        return AliasStrength.MODERATE
    return AliasStrength.WEAK


class AliasDetector:
    """Proposes potential aliases and explains every one of them."""

    #: Contextual evidence that corroborates a handle resemblance, and what a
    #: match is worth on top of the transformation itself.
    CONTEXT_WEIGHTS: dict[str, int] = {
        EvidenceType.EXPLICIT_LINK: 40,
        EvidenceType.SHARED_EMAIL: 30,
        EvidenceType.SAME_AVATAR: 20,
        EvidenceType.SAME_WEBSITE: 20,
        EvidenceType.SHARED_ORGANIZATION: 10,
        EvidenceType.SAME_DISPLAY_NAME: 10,
        EvidenceType.SIMILAR_BIO: 5,
    }

    def __init__(self, scoring: ScoringConfig | None = None) -> None:
        self.scoring = scoring or get_settings().scoring

    def compare(
        self,
        source_identifier: str,
        target_identifier: str,
        *,
        evidence: list[EvidenceItem] | None = None,
    ) -> AliasCandidate | None:
        """Assess one handle pair, folding in evidence already collected.

        Returns ``None`` when nothing explainable relates the two handles -
        similarity alone is never enough.
        """
        similarity = calculate_username_similarity(
            source_identifier, target_identifier
        )
        if similarity < MIN_SIMILARITY:
            return None

        transformations = detect_transformations(source_identifier, target_identifier)
        if not transformations:
            return None
        # The same handle on two platforms is not an alias - it is the same
        # handle, which the correlation engine already scores as SAME_USERNAME.
        # Case is not a variant either: platforms fold it.
        if transformations in (
            [str(Transformation.IDENTICAL)],
            [str(Transformation.CASE_ONLY)],
        ):
            return None

        signals = [
            AliasSignal(
                kind=name,
                label=TRANSFORMATION_LABEL.get(name, name),
                detail=(
                    f"'{source_identifier}' → '{target_identifier}': "
                    f"{TRANSFORMATION_LABEL.get(name, name).lower()}"
                ),
                weight=TRANSFORMATION_WEIGHT.get(name, 0.0),
            )
            for name in transformations
        ]
        shared_root = root_token(source_identifier)
        if shared_root and shared_root == root_token(target_identifier):
            signals.append(
                AliasSignal(
                    kind=str(EvidenceType.SHARED_ROOT_TOKEN),
                    label="Shared root token",
                    detail=f"Both handles are built on '{shared_root}'",
                    weight=TRANSFORMATION_WEIGHT[Transformation.SHARED_ROOT_TOKEN],
                )
            )

        strength = alias_strength(similarity, transformations)
        supporting: list[EvidenceItem] = []
        contradicting: list[EvidenceItem] = []
        for item in evidence or []:
            if not item.supports:
                contradicting.append(item)
            elif str(item.type) in self.CONTEXT_WEIGHTS:
                supporting.append(item)

        score = self._score(strength, similarity, supporting, contradicting)
        for item in supporting:
            signals.append(
                AliasSignal(
                    kind=str(item.type),
                    label=str(item.type).replace("_", " ").title(),
                    detail=item.description,
                    weight=float(self.CONTEXT_WEIGHTS.get(str(item.type), 0)),
                )
            )

        candidate = AliasCandidate(
            source_identifier=source_identifier,
            target_identifier=target_identifier,
            similarity=similarity,
            strength=strength,
            transformations=transformations,
            signals=signals,
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            score=score,
            confidence=str(self._confidence(score)),
        )
        logger.debug(
            "alias_candidate %s~%s similarity=%.2f strength=%s score=%.0f",
            source_identifier,
            target_identifier,
            similarity,
            strength,
            score,
        )
        return candidate

    def detect(
        self,
        profiles: list[ObservedProfile],
        correlations: list[CorrelationResult] | None = None,
    ) -> list[AliasCandidate]:
        """Propose alias pairs across every observed account.

        Contextual evidence is taken from the correlation results that were
        already computed for the same pairs, so this pass adds no extra
        comparison work and cannot disagree with the relationship the analyst
        sees on the edge.
        """
        accounts = [
            profile for profile in profiles if str(profile.entity_type) == "ACCOUNT"
        ]
        evidence_by_pair: dict[frozenset[tuple[str, str, str]], list[EvidenceItem]] = {}
        for result in correlations or []:
            evidence_by_pair[frozenset({result.source_key, result.target_key})] = (
                result.evidence
            )

        candidates: list[AliasCandidate] = []
        for first, second in combinations(accounts, 2):
            evidence = evidence_by_pair.get(frozenset({first.key, second.key}), [])
            candidate = self.compare(
                first.identifier, second.identifier, evidence=evidence
            )
            if candidate is None:
                continue
            candidate.source_platform = first.platform
            candidate.target_platform = second.platform
            candidates.append(candidate)

        candidates.sort(
            key=lambda item: (-item.score, item.source_identifier, item.target_identifier)
        )
        logger.info(
            "alias_detection accounts=%d candidates=%d", len(accounts), len(candidates)
        )
        return candidates

    def _score(
        self,
        strength: AliasStrength,
        similarity: float,
        supporting: list[EvidenceItem],
        contradicting: list[EvidenceItem],
    ) -> float:
        """Handle resemblance plus corroboration, minus contradictions.

        The handle can never carry the result on its own: the resemblance is
        capped well below the confident bands, so reaching HIGH requires
        independent evidence.
        """
        base = {
            AliasStrength.STRONG: 35.0,
            AliasStrength.MODERATE: 20.0,
            AliasStrength.WEAK: 8.0,
            AliasStrength.NONE: 0.0,
        }[strength]
        base += similarity * 5
        base += sum(
            self.CONTEXT_WEIGHTS.get(str(item.type), 0) for item in supporting
        )
        base += sum(item.weight for item in contradicting)  # already negative
        return round(max(0.0, min(100.0, base)), 1)

    def _confidence(self, score: float) -> ConfidenceLevel:
        """Reuse the project-wide confidence bands rather than inventing new ones."""
        for threshold, level in self.scoring.bands:
            if score >= threshold:
                return ConfidenceLevel(level)
        return ConfidenceLevel.LOW


__all__ = [
    "AliasCandidate",
    "AliasDetector",
    "AliasSignal",
    "AliasStrength",
    "Transformation",
    "calculate_username_similarity",
    "detect_transformations",
    "extract_username_tokens",
    "normalize_alias_candidate",
    "root_token",
]
