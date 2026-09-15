"""Evidence-first correlation engine.

The scoring model is deliberately small, additive and readable.  Each rule
contributes a fixed number of points *and* an evidence record explaining
itself, so an analyst can reconstruct any score by reading its evidence list.
Point values live in :class:`app.config.ScoringConfig` - not scattered through
this module - which is what makes the model retunable, and replaceable by a
probabilistic or learned ranker later (section 44).

Three principles hold throughout:

* A relationship is a *potential* association, never an identity claim.
* Contradictions are first-class: conflicting locations and websites subtract
  points and are shown to the analyst alongside supporting evidence.
* No evidence means no relationship.  "Insufficient evidence" is a valid and
  common outcome, and is better than a speculative edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from ..config import ScoringConfig, get_settings
from ..models.enums import (
    ConfidenceLevel,
    EvidenceType,
    RelationshipType,
)
from ..sources.base import ObservedProfile
from ..utils.logging import get_logger
from ..utils.normalization import (
    is_identifying_host,
    normalize_display_name,
    normalize_location,
    normalize_url,
    platform_label,
    text_similarity,
    username_similarity,
)
from ..utils.url_parser import website_identity
from ..utils.validation import clamp

logger = get_logger(__name__)

MAX_SCORE = 100.0

# Wording used when a relationship has no evidence at all.
INSUFFICIENT_EVIDENCE = "Insufficient evidence"


@dataclass
class EvidenceItem:
    """One reason a correlation scored what it scored."""

    type: EvidenceType
    description: str
    weight: float
    supports: bool = True
    source_url: str | None = None
    extracted_value: str | None = None
    #: The comparison form that actually matched, when it differs from the
    #: published value ("Alice R." -> "alice r", "https://alice.dev/" ->
    #: "alice.dev").  This is what makes a match explainable.
    normalized_value: str | None = None

    @property
    def signed_weight(self) -> float:
        return self.weight


@dataclass
class CorrelationResult:
    """The outcome of comparing two observed profiles."""

    source_key: tuple[str, str, str]
    target_key: tuple[str, str, str]
    relationship_type: RelationshipType
    score: float
    confidence_level: ConfidenceLevel
    evidence: list[EvidenceItem] = field(default_factory=list)
    summary: str = INSUFFICIENT_EVIDENCE

    @property
    def supporting(self) -> list[EvidenceItem]:
        return [item for item in self.evidence if item.supports]

    @property
    def contradicting(self) -> list[EvidenceItem]:
        return [item for item in self.evidence if not item.supports]

    @property
    def has_evidence(self) -> bool:
        return bool(self.evidence)


class CorrelationEngine:
    """Compares observed profiles and explains every point it awards."""

    def __init__(self, scoring: ScoringConfig | None = None) -> None:
        self.scoring = scoring or get_settings().scoring

    # -- public API --------------------------------------------------------

    def score_to_level(self, score: float) -> ConfidenceLevel:
        """Map a score onto its confidence band.

        Bands are presentation, not probability: a score of 72 means "the
        supporting evidence adds up to 72 points under the current model",
        never "72% likely to be the same person".
        """
        for threshold, label in self.scoring.bands:
            if score >= threshold:
                return ConfidenceLevel(label)
        return ConfidenceLevel.LOW

    def compare(
        self, source: ObservedProfile, target: ObservedProfile
    ) -> CorrelationResult:
        """Compare two profiles and return a scored, evidenced result."""
        evidence: list[EvidenceItem] = []
        for rule in (
            self._explicit_link,
            self._shared_email,
            self._shared_avatar,
            self._shared_website,
            self._similar_bio,
            self._username,
            self._display_name,
            self._shared_organization,
            self._contradictory_website,
            self._contradictory_location,
            self._conflicting_email,
        ):
            item = rule(source, target)
            if item is not None:
                evidence.append(item)

        raw = sum(item.signed_weight for item in evidence)
        score = clamp(raw, 0.0, MAX_SCORE)
        result = CorrelationResult(
            source_key=source.key,
            target_key=target.key,
            relationship_type=self._classify(evidence, score),
            score=round(score, 1),
            confidence_level=(
                self.score_to_level(score) if evidence else ConfidenceLevel.INSUFFICIENT
            ),
            evidence=evidence,
            summary=self._summarize(evidence),
        )
        logger.info(
            "correlation_scored source=%s target=%s score=%.0f level=%s evidence=%d",
            source.label,
            target.label,
            result.score,
            result.confidence_level,
            len(evidence),
        )
        return result

    def correlate(self, profiles: list[ObservedProfile]) -> list[CorrelationResult]:
        """Compare every pair of account profiles, strongest first.

        A result is returned only when at least one piece of *supporting*
        evidence exists.  Two profiles that merely contradict each other are
        not associated, so they get no edge; contradictions are recorded on
        the relationships they actually weaken.
        """
        accounts = [
            profile for profile in profiles if str(profile.entity_type) == "ACCOUNT"
        ]
        results: list[CorrelationResult] = []
        for first, second in combinations(accounts, 2):
            source, target = self._orient(first, second)
            result = self.compare(source, target)
            if result.supporting:
                results.append(result)
        results.sort(key=lambda item: (-item.score, item.target_key))
        logger.info(
            "correlation_completed candidates=%d relationships=%d",
            len(accounts),
            len(results),
        )
        return results

    # -- orientation and classification ------------------------------------

    def _orient(
        self, first: ObservedProfile, second: ObservedProfile
    ) -> tuple[ObservedProfile, ObservedProfile]:
        """Put the referencing profile first, else order deterministically."""
        if self._references(first, second):
            return first, second
        if self._references(second, first):
            return second, first
        return (first, second) if first.key <= second.key else (second, first)

    def _classify(
        self, evidence: list[EvidenceItem], score: float
    ) -> RelationshipType:
        """Choose the relationship type that best describes the evidence."""
        if not evidence:
            return RelationshipType.SHARED_ATTRIBUTE
        types = {item.type for item in evidence if item.supports}
        contradictions = [item for item in evidence if not item.supports]

        if contradictions and score <= 0:
            return RelationshipType.CONTRADICTORY
        if score >= self.scoring.bands[1][0]:  # HIGH or better
            return RelationshipType.POTENTIAL_SAME_IDENTITY
        if EvidenceType.SHARED_EMAIL in types:
            return RelationshipType.SHARED_EMAIL
        if EvidenceType.SAME_WEBSITE in types:
            return RelationshipType.SHARED_WEBSITE
        if EvidenceType.SAME_AVATAR in types:
            return RelationshipType.SHARED_AVATAR
        if types & {EvidenceType.SAME_USERNAME, EvidenceType.SIMILAR_USERNAME}:
            return RelationshipType.USES_USERNAME
        return RelationshipType.SHARED_ATTRIBUTE

    @staticmethod
    def _summarize(evidence: list[EvidenceItem]) -> str:
        """One-line description of what the relationship rests on."""
        if not evidence:
            return INSUFFICIENT_EVIDENCE
        labels = {
            EvidenceType.EXPLICIT_LINK: "explicit cross-platform link",
            EvidenceType.SHARED_EMAIL: "shared public email",
            EvidenceType.SAME_AVATAR: "same public avatar",
            EvidenceType.SAME_WEBSITE: "same external website",
            EvidenceType.SIMILAR_BIO: "similar biography",
            EvidenceType.SAME_USERNAME: "identical username",
            EvidenceType.SIMILAR_USERNAME: "similar username",
            EvidenceType.SAME_DISPLAY_NAME: "same display name",
            EvidenceType.SHARED_ORGANIZATION: "shared organization",
        }
        supporting = [
            labels.get(item.type, str(item.type).lower())
            for item in evidence
            if item.supports
        ]
        contradictions = len([item for item in evidence if not item.supports])
        if not supporting:
            return f"Contradictory evidence only ({contradictions} conflict(s))"
        summary = ", ".join(supporting).capitalize()
        if contradictions:
            summary += f"; {contradictions} contradiction(s)"
        return summary

    # -- individual rules --------------------------------------------------

    @staticmethod
    def _references(holder: ObservedProfile, target: ObservedProfile) -> str | None:
        """The snippet in ``holder`` that references ``target``, if any."""
        for reference in holder.references:
            if reference.key == (target.platform, target.identifier):
                return reference.context
        return None

    def _explicit_link(
        self, source: ObservedProfile, target: ObservedProfile
    ) -> EvidenceItem | None:
        """Strongest signal: one profile publicly points at the other."""
        forward = self._references(source, target)
        backward = self._references(target, source)
        if not forward and not backward:
            return None

        if forward:
            description = (
                f"{platform_label(source.platform)} profile @{source.identifier} "
                f"publicly links to {platform_label(target.platform)} "
                f"@{target.identifier} ({forward})"
            )
            if backward:
                description += " - and the link is reciprocated"
            url, value = source.url, forward
        else:
            description = (
                f"{platform_label(target.platform)} profile @{target.identifier} "
                f"publicly links to {platform_label(source.platform)} "
                f"@{source.identifier} ({backward})"
            )
            url, value = target.url, backward

        return EvidenceItem(
            type=EvidenceType.EXPLICIT_LINK,
            description=description,
            weight=self.scoring.explicit_link,
            source_url=url,
            extracted_value=value,
        )

    def _shared_email(
        self, source: ObservedProfile, target: ObservedProfile
    ) -> EvidenceItem | None:
        shared = sorted(set(source.emails) & set(target.emails))
        if not shared:
            return None
        return EvidenceItem(
            type=EvidenceType.SHARED_EMAIL,
            description=(
                f"Both profiles publish the same public email address: {shared[0]}"
            ),
            weight=self.scoring.shared_email,
            source_url=source.url,
            extracted_value=shared[0],
            normalized_value=shared[0].lower(),
        )

    def _shared_avatar(
        self, source: ObservedProfile, target: ObservedProfile
    ) -> EvidenceItem | None:
        """Same avatar image reference.

        The MVP compares normalized image URLs, which catches the common case
        of one image reused across platforms.  Perceptual hashing (matching
        re-encoded or resized copies) is a natural later addition and would
        slot in here without changing the evidence model.
        """
        first = normalize_url(source.avatar_url)
        second = normalize_url(target.avatar_url)
        if not first or not second or first != second:
            return None
        return EvidenceItem(
            type=EvidenceType.SAME_AVATAR,
            description=f"Both profiles use the same public avatar image: {first}",
            weight=self.scoring.shared_avatar,
            source_url=first,
            extracted_value=source.avatar_url,
            normalized_value=first,
        )

    @staticmethod
    def _website_identities(profile: ObservedProfile) -> dict[str, str]:
        """Canonical website identity -> original URL for a profile."""
        sites: dict[str, str] = {}
        for url in profile.websites or profile.external_links:
            identity = website_identity(url)
            if not identity or identity in sites:
                continue
            # A shortener or mailbox provider is not a shared identity.
            if not is_identifying_host(identity):
                continue
            sites[identity] = url
        return sites

    def _shared_website(
        self, source: ObservedProfile, target: ObservedProfile
    ) -> EvidenceItem | None:
        first = self._website_identities(source)
        second = self._website_identities(target)
        shared = sorted(set(first) & set(second))
        if not shared:
            return None
        return EvidenceItem(
            type=EvidenceType.SAME_WEBSITE,
            description=(
                f"Both profiles publish the same external website: {shared[0]}"
            ),
            weight=self.scoring.shared_website,
            source_url=first[shared[0]],
            extracted_value=first[shared[0]],
            normalized_value=shared[0],
        )

    def _similar_bio(
        self, source: ObservedProfile, target: ObservedProfile
    ) -> EvidenceItem | None:
        similarity = text_similarity(source.bio, target.bio)
        if similarity < self.scoring.bio_similarity_threshold:
            return None
        return EvidenceItem(
            type=EvidenceType.SIMILAR_BIO,
            description=(
                "Public biographies use substantially the same wording "
                f"(overlap {similarity:.2f})"
            ),
            weight=self.scoring.similar_bio,
            source_url=target.url,
            extracted_value=f"{similarity:.2f}",
        )

    def _username(
        self, source: ObservedProfile, target: ObservedProfile
    ) -> EvidenceItem | None:
        """Handle comparison - a weak signal, since handles are reused."""
        similarity = username_similarity(source.identifier, target.identifier)
        if similarity >= 1.0:
            return EvidenceItem(
                type=EvidenceType.SAME_USERNAME,
                description=(
                    f"Identical username '{target.identifier}' on "
                    f"{platform_label(source.platform)} and "
                    f"{platform_label(target.platform)} - weak on its own, "
                    "handles are commonly reused by unrelated people"
                ),
                weight=self.scoring.exact_username,
                source_url=target.url,
                extracted_value=target.identifier,
            )
        if similarity >= self.scoring.username_similarity_threshold:
            return EvidenceItem(
                type=EvidenceType.SIMILAR_USERNAME,
                description=(
                    f"Similar usernames '{source.identifier}' and "
                    f"'{target.identifier}' (similarity {similarity:.2f}) - "
                    "a weak lead, not an association on its own"
                ),
                weight=self.scoring.similar_username,
                source_url=target.url,
                extracted_value=f"{similarity:.2f}",
            )
        return None

    def _display_name(
        self, source: ObservedProfile, target: ObservedProfile
    ) -> EvidenceItem | None:
        first = normalize_display_name(source.display_name)
        second = normalize_display_name(target.display_name)
        if not first or not second or first != second:
            return None
        return EvidenceItem(
            type=EvidenceType.SAME_DISPLAY_NAME,
            description=(
                f"Same public display name ('{target.display_name}') - weak, "
                "many people share a name"
            ),
            weight=self.scoring.same_display_name,
            source_url=target.url,
            extracted_value=target.display_name,
            normalized_value=normalize_display_name(target.display_name),
        )

    def _shared_organization(
        self, source: ObservedProfile, target: ObservedProfile
    ) -> EvidenceItem | None:
        first = {name.lower() for name in source.organizations}
        second = {name.lower() for name in target.organizations}
        shared = sorted(first & second)
        if not shared:
            return None
        # Quote the name as it was published. The comparison is lowercased,
        # but an analyst reading "the organization 'cloudfactory'" is reading
        # this module's working form rather than what either profile said.
        published = next(
            (name for name in target.organizations if name.lower() == shared[0]),
            shared[0],
        )
        return EvidenceItem(
            type=EvidenceType.SHARED_ORGANIZATION,
            description=f"Both profiles reference the organization '{published}'",
            weight=self.scoring.shared_organization,
            source_url=target.url,
            extracted_value=published,
            normalized_value=shared[0],
        )

    # -- contradictions ----------------------------------------------------

    def _contradictory_website(
        self, source: ObservedProfile, target: ObservedProfile
    ) -> EvidenceItem | None:
        """Both profiles publish a website, and they have none in common."""
        first = self._website_identities(source)
        second = self._website_identities(target)
        if not first or not second or set(first) & set(second):
            return None
        return EvidenceItem(
            type=EvidenceType.CONTRADICTORY_ATTRIBUTE,
            description=(
                f"Different public websites: @{source.identifier} publishes "
                f"{sorted(first)[0]}, @{target.identifier} publishes "
                f"{sorted(second)[0]}"
            ),
            weight=self.scoring.contradictory_website,
            supports=False,
            source_url=target.url,
            extracted_value=f"{sorted(first)[0]} vs {sorted(second)[0]}",
        )

    def _contradictory_location(
        self, source: ObservedProfile, target: ObservedProfile
    ) -> EvidenceItem | None:
        first = normalize_location(source.location)
        second = normalize_location(target.location)
        if not first or not second or first == second:
            return None
        return EvidenceItem(
            type=EvidenceType.CONTRADICTORY_ATTRIBUTE,
            description=(
                f"Conflicting public locations: '{source.location}' and "
                f"'{target.location}'"
            ),
            weight=self.scoring.contradictory_location,
            supports=False,
            source_url=target.url,
            extracted_value=f"{source.location} vs {target.location}",
        )

    def _conflicting_email(
        self, source: ObservedProfile, target: ObservedProfile
    ) -> EvidenceItem | None:
        """Both publish contact addresses, and none of them match."""
        first, second = set(source.emails), set(target.emails)
        if not first or not second or first & second:
            return None
        return EvidenceItem(
            type=EvidenceType.CONTRADICTORY_ATTRIBUTE,
            description=(
                f"Different public contact addresses: {sorted(first)[0]} and "
                f"{sorted(second)[0]}"
            ),
            weight=self.scoring.metadata_conflict,
            supports=False,
            source_url=target.url,
            extracted_value=f"{sorted(first)[0]} vs {sorted(second)[0]}",
        )
