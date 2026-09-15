"""Controlled vocabularies shared by the models, services and API.

The wording matters: Omnicient never states that two accounts belong to the
same person.  Relationship types and confidence levels are phrased as
*potential* associations, and ``CONFIRMED`` means "an analyst agrees the
evidence supports this relationship", not "this identity is proven".
"""

from __future__ import annotations

from enum import StrEnum


class EntityType(StrEnum):
    """Kinds of node in the investigation graph."""

    ACCOUNT = "ACCOUNT"
    WEBSITE = "WEBSITE"
    DOMAIN = "DOMAIN"
    USERNAME = "USERNAME"
    EMAIL = "EMAIL"
    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"


class RelationshipType(StrEnum):
    """Kinds of edge in the investigation graph."""

    LINKS_TO = "LINKS_TO"
    REFERENCES = "REFERENCES"
    USES_USERNAME = "USES_USERNAME"
    SHARED_WEBSITE = "SHARED_WEBSITE"
    SHARED_EMAIL = "SHARED_EMAIL"
    SHARED_AVATAR = "SHARED_AVATAR"
    SHARED_ATTRIBUTE = "SHARED_ATTRIBUTE"
    POTENTIAL_SAME_IDENTITY = "POTENTIAL_SAME_IDENTITY"
    #: One handle is a plausible naming variant of the other.  Narrower than
    #: POTENTIAL_SAME_IDENTITY: it is a claim about the *handles*, not about
    #: the people behind them, and it never asserts an identity on its own.
    POTENTIAL_ALIAS = "POTENTIAL_ALIAS"
    CONTRADICTORY = "CONTRADICTORY"


# Analyst-facing wording for each relationship type.
RELATIONSHIP_LABELS: dict[str, str] = {
    RelationshipType.LINKS_TO: "Links To",
    RelationshipType.REFERENCES: "References",
    RelationshipType.USES_USERNAME: "Uses Username",
    RelationshipType.SHARED_WEBSITE: "Shared Website",
    RelationshipType.SHARED_EMAIL: "Shared Email",
    RelationshipType.SHARED_AVATAR: "Shared Avatar",
    RelationshipType.SHARED_ATTRIBUTE: "Shared Attribute",
    RelationshipType.POTENTIAL_SAME_IDENTITY: "Potential Same Identity",
    RelationshipType.POTENTIAL_ALIAS: "Potential Alias",
    RelationshipType.CONTRADICTORY: "Contradictory",
}


class ConfidenceLevel(StrEnum):
    """Bands over the correlation score.  Not probabilities."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"
    INSUFFICIENT = "INSUFFICIENT"


class RelationshipOrigin(StrEnum):
    """Who first asserted a relationship.

    The distinction has to survive into exports.  A reader of an investigation
    is entitled to know which connections the engine derived from public
    observations and which ones a person drew by hand - they carry very
    different warrant, and a graph that blurs them is making a claim it cannot
    support.

    An edge keeps the origin of whoever asserted it first.  Evidence still
    accumulates either way: if a later crawl finds real observations behind a
    link an analyst drew, the edge gains that evidence and keeps saying that a
    person put it there.
    """

    #: Derived by the correlation engine from observed evidence.
    ENGINE = "ENGINE"
    #: Drawn by an analyst, with a stated rationale.
    ANALYST = "ANALYST"


class AnalystStatus(StrEnum):
    """Analyst's verdict on a relationship.

    ``CONFIRMED`` means the analyst agrees the displayed evidence supports the
    relationship - it never asserts real-world identity certainty.
    """

    UNREVIEWED = "UNREVIEWED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class EvidenceType(StrEnum):
    """Why a relationship scored what it scored."""

    EXPLICIT_LINK = "EXPLICIT_LINK"
    SAME_WEBSITE = "SAME_WEBSITE"
    SAME_USERNAME = "SAME_USERNAME"
    SIMILAR_USERNAME = "SIMILAR_USERNAME"
    SAME_DISPLAY_NAME = "SAME_DISPLAY_NAME"
    SAME_AVATAR = "SAME_AVATAR"
    SIMILAR_BIO = "SIMILAR_BIO"
    SHARED_EMAIL = "SHARED_EMAIL"
    SHARED_ORGANIZATION = "SHARED_ORGANIZATION"
    CONTRADICTORY_ATTRIBUTE = "CONTRADICTORY_ATTRIBUTE"
    #: A handle is a deterministic transformation of another (section: alias
    #: detection).  The transformation itself is recorded in ``context``.
    USERNAME_TRANSFORMATION = "USERNAME_TRANSFORMATION"
    #: Both handles share a substantial root token ("alice" in alice_98 /
    #: alice-security).  Weak on its own; meaningful alongside context.
    SHARED_ROOT_TOKEN = "SHARED_ROOT_TOKEN"
    #: An analyst drew this link themselves and gave a reason.  It is
    #: provenance, not an observation: it records who asserted the connection
    #: and why, and carries no weight, because the engine observed nothing.
    ANALYST_ASSERTION = "ANALYST_ASSERTION"


# Evidence that argues against a relationship rather than for it.
NEGATIVE_EVIDENCE_TYPES = frozenset({EvidenceType.CONTRADICTORY_ATTRIBUTE})


class EvidenceStance(StrEnum):
    """What an observation does to a relationship.

    ``supports`` alone cannot express an observation that was recorded but
    changed nothing - a zero-weight item is real provenance (it was seen, at a
    URL, at a time) without being an argument either way.
    """

    SUPPORTING = "SUPPORTING"
    CONTRADICTORY = "CONTRADICTORY"
    NEUTRAL = "NEUTRAL"


def evidence_stance(weight: float, supports: bool) -> EvidenceStance:
    """Classify an observation from its weight and direction."""
    if not supports:
        return EvidenceStance.CONTRADICTORY
    if weight == 0:
        return EvidenceStance.NEUTRAL
    return EvidenceStance.SUPPORTING


class InvestigationStatus(StrEnum):
    """Lifecycle of an investigation."""

    CREATED = "CREATED"
    CRAWLING = "CRAWLING"
    ANALYZING = "ANALYZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DiscoveryMethod(StrEnum):
    """How an entity entered the investigation (section 18: candidates).

    Preserved per entity so an analyst can tell an explicitly linked account
    from one that merely has a similar handle.
    """

    SEED = "SEED"
    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"
    SIMILARITY = "SIMILARITY"
    DEMO = "DEMO"
