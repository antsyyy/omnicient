"""Investigation leads: what is worth looking at next.

Every lead is derived from something already in the graph - a value two
accounts both published, an association nobody has reviewed, a contradiction
sitting under a strong score. Nothing here searches, infers or concludes; it
points, and says what it is pointing at.

The framing matters. These are *suggestions for an analyst*, not findings. A
lead that says "alice.dev connects three accounts" is reporting an observation
and proposing a pivot; it is not claiming those accounts share an owner.

Each rule is a small function returning zero or more leads, so adding a signal
means adding one function to :data:`RULES` and nothing else. Priority comes
from a deterministic score, not from the order the rules happen to run in.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import blake2s

from ..models.entity import Entity
from ..models.enums import (
    AnalystStatus,
    ConfidenceLevel,
    EntityType,
    EvidenceType,
    RelationshipType,
)
from ..models.evidence import Evidence
from ..models.investigation import Investigation
from ..models.relationship import Relationship
from ..repository import Neo4jRepository
from ..schemas.entity import EntitySummary
from ..schemas.lead import Lead, LeadList, LeadPriority, LeadType
from ..utils.logging import get_logger
from ..utils.normalization import (
    domain_belongs_to,
    is_identifying_host,
    name_token,
    normalize_domain,
)
from ..utils.url_parser import detect_platform

logger = get_logger(__name__)

#: Score at or above which a lead is HIGH, then MEDIUM.  Tunable in one place
#: so "why is this HIGH?" is answerable by reading two numbers.
HIGH_THRESHOLD = 70.0
MEDIUM_THRESHOLD = 40.0

#: A value shared by at least this many entities is a cluster worth a pivot.
CLUSTER_MIN_ENTITIES = 2

#: Above this many accounts, a shared value stops identifying anybody.
#:
#: This is the correction to a rule that had it exactly backwards. A domain
#: published by two or three accounts is a strong personal pivot - somebody
#: controls it, and the accounts that point at it are probably theirs. A
#: domain published by twenty-eight is an employer, a platform or a link
#: shortener nobody has listed yet. Scoring by "more sharers is stronger"
#: filled the lead list with automattic.com, wordpress.com and apps.apple.com,
#: each described as "the strongest publicly observable pivot", each marked
#: HIGH, and every one of them useless for telling one person from another.
CLUSTER_MAX_ENTITIES = 8

#: Sharers a domain needs before it is worth reporting on its own.
#:
#: Only applies when nothing else connects the domain to the subject. Two
#: accounts linking to the same news story is a coincidence; four accounts
#: converging on one small site is a pattern.
CLUSTER_NOTEWORTHY = 4


def _identity_tokens(entities: list[Entity]) -> set[str]:
    """The names belonging to the person this investigation is about.

    Handles and display names, flattened to letters and digits so that
    ``beau.lebens``, ``beau_lebens`` and ``BeauLebens`` all compare equal.

    Only the seed and what the seed handle itself found - not the whole
    graph. A crawl reaches dozens of accounts belonging to companies and
    products the subject merely links to, and taking names from those made
    the rule decide that tumblr.com, woocommerce.com and 404media.co were all
    "their own site", because accounts by those names had been discovered.
    """
    tokens: set[str] = set()
    for entity in entities:
        if entity.depth > 0 and not entity.is_seed:
            continue
        for value in (entity.identifier, entity.display_name):
            if not value:
                continue
            flat = name_token(value)
            if len(flat) >= 4:
                tokens.add(flat)
    return tokens


def _cluster_score(base: float, sharers: int) -> float:
    """How much a value shared by ``sharers`` accounts identifies a person.

    Peaks at the small end and falls away: the whole worth of a shared value
    is that few things carry it.
    """
    if sharers > CLUSTER_MAX_ENTITIES:
        return 0.0
    # Two sharers scores highest and each additional one dilutes it, gently
    # enough that a personal domain listed on half a dozen of somebody's
    # profiles still reads as the strong lead it is.
    return max(0.0, base - 6.0 * (sharers - CLUSTER_MIN_ENTITIES))


@dataclass
class LeadContext:
    """Everything the rules read, fetched once."""

    investigation: Investigation
    entities: list[Entity]
    relationships: list[Relationship]
    evidence: list[Evidence]

    @property
    def by_id(self) -> dict[str, Entity]:
        return {entity.id: entity for entity in self.entities}


def _lead_id(investigation_id: str, kind: str, key: str) -> str:
    """Stable id, so the same lead keeps its identity between requests."""
    digest = blake2s(
        f"{investigation_id}:{kind}:{key}".encode(), digest_size=8
    ).hexdigest()
    return f"lead-{digest}"


def _priority(score: float) -> LeadPriority:
    if score >= HIGH_THRESHOLD:
        return LeadPriority.HIGH
    if score >= MEDIUM_THRESHOLD:
        return LeadPriority.MEDIUM
    return LeadPriority.LOW


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def shared_website_cluster(context: LeadContext) -> list[Lead]:
    """A personal domain published by several accounts is the strongest pivot."""
    clusters: dict[str, set[str]] = defaultdict(set)
    for entity in context.entities:
        for url in list(entity.external_links or []) + list(
            (entity.meta or {}).get("websites", []) or []
        ):
            domain = normalize_domain(url)
            # A platform host is an account, and a shortener is nobody's site.
            if not domain or detect_platform(url) or not is_identifying_host(domain):
                continue
            clusters[domain].add(entity.id)

    tokens = _identity_tokens(context.entities)
    leads: list[Lead] = []
    for domain, entity_ids in clusters.items():
        if len(entity_ids) < CLUSTER_MIN_ENTITIES:
            continue
        count = len(entity_ids)
        personal = domain_belongs_to(domain, tokens)
        # Two accounts both linking to a news site is not a finding. Without
        # a name tying the domain to the subject, a cluster has to be large
        # enough to be surprising before it is worth an analyst's attention -
        # otherwise the list fills with nytimes.com and every WordPress
        # subdomain two of the discovered accounts happen to mention.
        if not personal and count < CLUSTER_NOTEWORTHY:
            continue
        # A site named after somebody here is a lead however many accounts
        # link to it; that only strengthens the case. Anything else is worth
        # far less, and worth less still the more accounts share it.
        score = 95.0 if personal else _cluster_score(60.0, count)
        if score <= 0:
            # Linked by too many unrelated accounts to point at one person.
            continue
        leads.append(
            Lead(
                id=_lead_id(context.investigation.id, "website", domain),
                type=LeadType.SHARED_WEBSITE_CLUSTER,
                priority=_priority(score),
                title=(
                    f"{domain} looks like their own site"
                    if personal
                    else f"{domain} is linked by {count} accounts"
                ),
                description=(
                    (
                        f"{domain} is named after a handle in this "
                        f"investigation and {count} of the accounts found "
                        f"here link to it. A site somebody controls is the "
                        f"best place to look for who they are."
                    )
                    if personal
                    else (
                        f"{count} of the accounts found here link to "
                        f"{domain}. Worth a look, but shared links are often "
                        f"just something both parties read."
                    )
                ),
                suggested_action=(
                    f"Open {domain} and look for the names, contact addresses "
                    f"or profile links it publishes."
                ),
                related_entity_ids=sorted(entity_ids),
                score=score,
                pivot_value=domain,
            )
        )
    return leads


def repeated_email(context: LeadContext) -> list[Lead]:
    """A public address on more than one entity is a direct pivot."""
    clusters: dict[str, set[str]] = defaultdict(set)
    for entity in context.entities:
        addresses = [entity.email] if entity.email else []
        addresses += list((entity.meta or {}).get("emails", []) or [])
        if entity.type == str(EntityType.EMAIL):
            addresses.append(entity.identifier)
        for address in addresses:
            if address:
                clusters[str(address).lower()].add(entity.id)

    leads: list[Lead] = []
    for address, entity_ids in clusters.items():
        if len(entity_ids) < CLUSTER_MIN_ENTITIES:
            continue
        score = 55.0 + 15.0 * len(entity_ids)
        leads.append(
            Lead(
                id=_lead_id(context.investigation.id, "email", address),
                type=LeadType.REPEATED_EMAIL,
                priority=_priority(score),
                title="Public email address appears on multiple entities",
                description=(
                    f"{address} was published by {len(entity_ids)} discovered "
                    f"entities."
                ),
                suggested_action=(
                    "Review the entities publishing this address and the "
                    "websites associated with its domain."
                ),
                related_entity_ids=sorted(entity_ids),
                score=score,
                pivot_value=address,
            )
        )
    return leads


def shared_avatar(context: LeadContext) -> list[Lead]:
    """The same image on two profiles is a deliberate act by the account holder."""
    clusters: dict[str, set[str]] = defaultdict(set)
    for entity in context.entities:
        if entity.avatar_url:
            clusters[entity.avatar_url].add(entity.id)

    leads: list[Lead] = []
    for avatar, entity_ids in clusters.items():
        if len(entity_ids) < CLUSTER_MIN_ENTITIES:
            continue
        score = 45.0 + 10.0 * len(entity_ids)
        leads.append(
            Lead(
                id=_lead_id(context.investigation.id, "avatar", avatar),
                type=LeadType.SHARED_AVATAR,
                priority=_priority(score),
                title="Accounts share a public avatar",
                description=(
                    f"{len(entity_ids)} accounts publish the same avatar image. "
                    f"Reusing an image across platforms is a deliberate act, "
                    f"though the image itself may be reposted by anyone."
                ),
                suggested_action=(
                    "Review additional public links and metadata on these "
                    "accounts for corroborating evidence."
                ),
                related_entity_ids=sorted(entity_ids),
                score=score,
                pivot_value=avatar,
            )
        )
    return leads


#: Individual "awaiting review" leads to raise before rolling the rest up.
UNREVIEWED_DETAIL_LIMIT = 3


def unreviewed_strong_association(context: LeadContext) -> list[Lead]:
    """Confident associations nobody has looked at yet.

    Emitting one lead per relationship turns the panel into a second copy of
    the relationship list - a dozen identical titles an analyst has to read
    past. The strongest few are named individually; the rest are rolled into a
    single lead that still carries every entity and relationship id, so
    highlighting and navigation lose nothing.
    """
    entities = context.by_id
    candidates: dict[frozenset[str], Relationship] = {}
    for relationship in context.relationships:
        if relationship.analyst_status != AnalystStatus.UNREVIEWED:
            continue
        if str(relationship.confidence_level) not in (
            ConfidenceLevel.HIGH,
            ConfidenceLevel.VERY_HIGH,
        ):
            continue
        if (
            relationship.source_entity_id not in entities
            or relationship.target_entity_id not in entities
        ):
            continue
        # One lead per pair: two edges between the same accounts are one
        # question for the analyst.
        pair = frozenset(
            {relationship.source_entity_id, relationship.target_entity_id}
        )
        best = candidates.get(pair)
        if best is None or relationship.confidence_score > best.confidence_score:
            candidates[pair] = relationship

    ranked = sorted(
        candidates.values(), key=lambda r: -r.confidence_score
    )
    leads: list[Lead] = []
    for relationship in ranked[:UNREVIEWED_DETAIL_LIMIT]:
        source = entities[relationship.source_entity_id]
        target = entities[relationship.target_entity_id]
        score = 50.0 + min(relationship.confidence_score, 100.0) * 0.3
        leads.append(
            Lead(
                id=_lead_id(context.investigation.id, "unreviewed", relationship.id),
                type=LeadType.UNREVIEWED_STRONG_ASSOCIATION,
                priority=_priority(score),
                title="Strong association awaiting review",
                description=(
                    f"{source.label} and {target.label} scored "
                    f"{relationship.confidence_score:.0f} "
                    f"({relationship.confidence_level}) and have not been "
                    f"reviewed."
                ),
                suggested_action=(
                    "Inspect the supporting evidence and confirm or reject "
                    "the association."
                ),
                related_entity_ids=[source.id, target.id],
                related_relationship_ids=[relationship.id],
                score=score,
            )
        )

    remainder = ranked[UNREVIEWED_DETAIL_LIMIT:]
    if remainder:
        entity_ids = sorted(
            {
                entity_id
                for relationship in remainder
                for entity_id in (
                    relationship.source_entity_id,
                    relationship.target_entity_id,
                )
            }
        )
        score = 40.0 + min(len(remainder), 10) * 1.5
        leads.append(
            Lead(
                id=_lead_id(context.investigation.id, "unreviewed", "remainder"),
                type=LeadType.UNREVIEWED_STRONG_ASSOCIATION,
                priority=_priority(score),
                title=f"{len(remainder)} further associations await review",
                description=(
                    f"{len(remainder)} additional associations scored HIGH or "
                    f"above and have not been reviewed."
                ),
                suggested_action=(
                    "Work through the relationship list, confirming or "
                    "rejecting each on its evidence."
                ),
                related_entity_ids=entity_ids,
                related_relationship_ids=[r.id for r in remainder],
                score=score,
            )
        )
    return leads


def contradiction_review(context: LeadContext) -> list[Lead]:
    """A contradiction sitting underneath a score an analyst may trust."""
    by_relationship: dict[str, list[Evidence]] = defaultdict(list)
    for item in context.evidence:
        if not item.supports and item.relationship_id:
            by_relationship[item.relationship_id].append(item)

    relationships = {r.id: r for r in context.relationships}
    entities = context.by_id
    leads: list[Lead] = []
    for relationship_id, items in by_relationship.items():
        relationship = relationships.get(relationship_id)
        if relationship is None:
            continue
        source = entities.get(relationship.source_entity_id)
        target = entities.get(relationship.target_entity_id)
        if source is None or target is None:
            continue

        # A contradiction matters most where the score is still high enough
        # that someone might act on it.
        score = 45.0 + relationship.confidence_score * 0.4 + 5.0 * len(items)
        leads.append(
            Lead(
                id=_lead_id(context.investigation.id, "contradiction", relationship_id),
                type=LeadType.CONTRADICTION_REVIEW,
                priority=_priority(score),
                title="Association contains contradictory evidence",
                description=(
                    f"{source.label} and {target.label} are associated at "
                    f"{relationship.confidence_score:.0f} "
                    f"({relationship.confidence_level}) but "
                    f"{len(items)} observation(s) argue against it: "
                    + "; ".join(item.description for item in items[:2])
                ),
                suggested_action=(
                    "Review the contradictory observations before treating "
                    "this association as supported."
                ),
                related_entity_ids=[source.id, target.id],
                related_relationship_ids=[relationship_id],
                supporting_evidence_ids=[item.id for item in items],
                score=score,
            )
        )
    return leads


def potential_alias(context: LeadContext) -> list[Lead]:
    """A handle variant found on another platform."""
    entities = context.by_id
    leads: list[Lead] = []
    for relationship in context.relationships:
        if str(relationship.relationship_type) != str(
            RelationshipType.POTENTIAL_ALIAS
        ):
            continue
        if relationship.analyst_status != AnalystStatus.UNREVIEWED:
            continue
        source = entities.get(relationship.source_entity_id)
        target = entities.get(relationship.target_entity_id)
        if source is None or target is None:
            continue

        score = 25.0 + relationship.confidence_score * 0.35
        leads.append(
            Lead(
                id=_lead_id(context.investigation.id, "alias", relationship.id),
                type=LeadType.POTENTIAL_ALIAS,
                priority=_priority(score),
                title="Username variant on another platform",
                description=(
                    f"'{target.identifier}' is a potential alias of "
                    f"'{source.identifier}'. This is a claim about the "
                    f"handles, not about the people behind them."
                ),
                suggested_action=(
                    "Review the alias evidence and look for corroborating "
                    "public attributes before treating them as related."
                ),
                related_entity_ids=[source.id, target.id],
                related_relationship_ids=[relationship.id],
                score=score,
                pivot_value=target.identifier,
            )
        )
    return leads


def bridge_entity(context: LeadContext) -> list[Lead]:
    """An entity many others connect through is where the graph pivots."""
    degree: dict[str, set[str]] = defaultdict(set)
    for relationship in context.relationships:
        degree[relationship.source_entity_id].add(relationship.target_entity_id)
        degree[relationship.target_entity_id].add(relationship.source_entity_id)

    entities = context.by_id
    leads: list[Lead] = []
    for entity_id, neighbours in degree.items():
        entity = entities.get(entity_id)
        if entity is None or entity.is_seed or len(neighbours) < 3:
            continue
        # Accounts are expected to be well connected; a *website* or an email
        # joining several accounts is the interesting structural case.
        if entity.type == str(EntityType.ACCOUNT):
            continue

        # Same correction as the website clusters: a website joining four
        # accounts is a lead, one joining twenty-two is a company homepage.
        score = _cluster_score(88.0, len(neighbours))
        if score <= 0:
            continue
        leads.append(
            Lead(
                id=_lead_id(context.investigation.id, "bridge", entity_id),
                type=LeadType.BRIDGE_ENTITY,
                priority=_priority(score),
                title=f"{entity.label} connects {len(neighbours)} accounts",
                description=(
                    f"Nothing else in this investigation joins these "
                    f"{len(neighbours)} accounts together. Whatever links "
                    f"them runs through {entity.label}."
                ),
                suggested_action=(
                    "Expand this entity's connections and review what each "
                    "link is based on."
                ),
                related_entity_ids=sorted({entity_id, *neighbours}),
                score=score,
                pivot_value=entity.identifier,
            )
        )
    return leads


def unresolved_entity(context: LeadContext) -> list[Lead]:
    """A candidate recorded but never read - incomplete, not absent."""
    unresolved = [
        entity
        for entity in context.entities
        if not entity.resolved and entity.type == str(EntityType.ACCOUNT)
    ]
    if not unresolved:
        return []
    score = 20.0 + min(len(unresolved), 5) * 2.0
    return [
        Lead(
            id=_lead_id(context.investigation.id, "unresolved", "accounts"),
            type=LeadType.UNRESOLVED_ENTITY,
            priority=_priority(score),
            title="Discovered accounts with no public data",
            description=(
                f"{len(unresolved)} account(s) were discovered but returned no "
                f"public data - the profile may be private, removed, or the "
                f"platform may have declined the request."
            ),
            suggested_action=(
                "Check the activity log for the exact reason, and consider "
                "whether another public source covers the same handle."
            ),
            related_entity_ids=sorted(entity.id for entity in unresolved),
            score=score,
        )
    ]


def shared_organization(context: LeadContext) -> list[Lead]:
    """A named organization on more than one entity."""
    clusters: dict[str, set[str]] = defaultdict(set)
    for item in context.evidence:
        if str(item.type) != str(EvidenceType.SHARED_ORGANIZATION):
            continue
        key = (item.normalized_value or item.extracted_value or "").lower()
        if not key:
            continue
        clusters[key].add(item.source_entity_id)
        if item.target_entity_id:
            clusters[key].add(item.target_entity_id)

    leads: list[Lead] = []
    for name, entity_ids in clusters.items():
        if len(entity_ids) < CLUSTER_MIN_ENTITIES:
            continue
        # Deliberately low: many unrelated people work at the same place.
        score = 22.0 + 4.0 * len(entity_ids)
        leads.append(
            Lead(
                id=_lead_id(context.investigation.id, "organization", name),
                type=LeadType.SHARED_ORGANIZATION,
                priority=_priority(score),
                title="Accounts reference the same organization",
                description=(
                    f"{len(entity_ids)} entities reference '{name}'. Weak on "
                    f"its own - an employer is shared by many unrelated people."
                ),
                suggested_action=(
                    "Treat as corroboration only alongside stronger evidence."
                ),
                related_entity_ids=sorted(entity_ids),
                score=score,
                pivot_value=name,
            )
        )
    return leads


#: Every rule the engine runs.  Adding a signal means adding a function here.
RULES: tuple[Callable[[LeadContext], list[Lead]], ...] = (
    shared_website_cluster,
    repeated_email,
    shared_avatar,
    unreviewed_strong_association,
    contradiction_review,
    potential_alias,
    bridge_entity,
    unresolved_entity,
    shared_organization,
)


class LeadService:
    """Generates investigation leads from the stored graph."""

    def __init__(self, repo: Neo4jRepository) -> None:
        self.repo = repo

    def generate(self, investigation: Investigation, limit: int = 15) -> LeadList:
        """Run every rule and return the leads, highest priority first.

        Deliberately short. A lead list is a list of things to do next, and
        fifty of them is not a list of things to do next - it is the same
        inventory the results view already holds, sorted differently. The cap
        is low enough that the bottom of the list is still worth reading.

        Computed on request rather than stored: a lead is a statement about the
        graph's *current* state, and a stored one would go stale the moment an
        analyst confirmed or rejected something.
        """
        context = LeadContext(
            investigation=investigation,
            entities=self.repo.list_entities(investigation.id),
            relationships=self.repo.list_relationships(investigation.id),
            evidence=self.repo.list_evidence(investigation.id),
        )

        leads: list[Lead] = []
        for rule in RULES:
            try:
                leads.extend(rule(context))
            except Exception:  # noqa: BLE001 - one bad rule must not blank the panel
                logger.exception("lead_rule_failed rule=%s", rule.__name__)

        leads.sort(key=lambda lead: (-lead.score, str(lead.type), lead.title))
        leads = leads[:limit]
        self._attach_entities(leads, context.by_id)

        logger.info(
            "leads_generated investigation=%s count=%d", investigation.id, len(leads)
        )
        return LeadList(investigation_id=investigation.id, leads=leads)

    @staticmethod
    def _attach_entities(leads: list[Lead], entities: dict[str, Entity]) -> None:
        """Resolve entity ids so the interface can render and navigate."""
        for lead in leads:
            lead.related_entities = [
                EntitySummary.model_validate(entities[entity_id])
                for entity_id in lead.related_entity_ids
                if entity_id in entities
            ]
