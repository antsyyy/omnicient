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
    RelationshipType.CONTRADICTORY: "Contradictory",
}


class ConfidenceLevel(StrEnum):
    """Bands over the correlation score.  Not probabilities."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"
    INSUFFICIENT = "INSUFFICIENT"


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


# Evidence that argues against a relationship rather than for it.
NEGATIVE_EVIDENCE_TYPES = frozenset({EvidenceType.CONTRADICTORY_ATTRIBUTE})


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
