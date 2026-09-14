/**
 * The API contract, mirrored from the backend Pydantic schemas.
 *
 * The frontend knows nothing about how crawling or correlation work: it
 * receives entities, relationships, evidence and a graph, and renders them.
 */

export type EntityType =
  | 'ACCOUNT'
  | 'WEBSITE'
  | 'DOMAIN'
  | 'USERNAME'
  | 'EMAIL'
  | 'PERSON'
  | 'ORGANIZATION'

export type RelationshipType =
  | 'LINKS_TO'
  | 'REFERENCES'
  | 'USES_USERNAME'
  | 'SHARED_WEBSITE'
  | 'SHARED_EMAIL'
  | 'SHARED_AVATAR'
  | 'SHARED_ATTRIBUTE'
  | 'POTENTIAL_SAME_IDENTITY'
  | 'POTENTIAL_ALIAS'
  | 'CONTRADICTORY'

export type ConfidenceLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'VERY_HIGH' | 'INSUFFICIENT'

export type AnalystStatus = 'UNREVIEWED' | 'CONFIRMED' | 'REJECTED'

export type DiscoveryMethod = 'SEED' | 'DIRECT' | 'INDIRECT' | 'SIMILARITY' | 'DEMO'

export type InvestigationStatus =
  | 'CREATED'
  | 'CRAWLING'
  | 'ANALYZING'
  | 'COMPLETED'
  | 'FAILED'

export type EvidenceType =
  | 'EXPLICIT_LINK'
  | 'SAME_WEBSITE'
  | 'SAME_USERNAME'
  | 'SIMILAR_USERNAME'
  | 'SAME_DISPLAY_NAME'
  | 'SAME_AVATAR'
  | 'SIMILAR_BIO'
  | 'SHARED_EMAIL'
  | 'SHARED_ORGANIZATION'
  | 'CONTRADICTORY_ATTRIBUTE'

export interface Health {
  status: string
  app: string
  tagline: string
  version: string
  demo_mode: boolean
  database: { engine: string; connected: boolean; error: string | null }
  demo_seed: { platform: string; identifier: string }
  sources: string[]
  /** Sources grouped by the kind of site they read. */
  sources_by_category: Record<string, string[]>
  source_count: number
  demo_sources: string[]
  crawler: {
    max_depth: number
    max_pages: number
    request_timeout: number
    respect_robots: boolean
  }
  confidence_bands: { min_score: number; level: ConfidenceLevel }[]
}

export interface Investigation {
  id: string
  name: string
  seed_platform: string
  seed_identifier: string
  status: InvestigationStatus
  status_message: string | null
  demo: boolean
  max_depth: number
  max_pages: number
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
  entity_count: number
  relationship_count: number
  evidence_count: number
}

export interface CrawlEvent {
  id: string
  investigation_id: string
  timestamp: string
  level: string
  event: string
  message: string
  data: Record<string, unknown> | null
  /** Monotonic position in the timeline; orders events sharing a timestamp. */
  sequence: number
}

export interface SourceIssue {
  platform: string
  identifier: string | null
  reason: string
  detail: string | null
  url: string | null
}

export interface InvestigationDetail extends Investigation {
  seed_entity_id: string | null
  events: CrawlEvent[]
  issues: SourceIssue[]
}

export interface Snapshot {
  id: string
  entity_id: string
  timestamp: string
  username: string | null
  display_name: string | null
  bio: string | null
  avatar_url: string | null
  external_links: string[]
  metadata: Record<string, unknown>
}

export interface Entity {
  id: string
  investigation_id: string
  type: EntityType
  platform: string
  platform_name: string
  name: string
  identifier: string
  url: string | null
  display_name: string | null
  bio: string | null
  avatar_url: string | null
  location: string | null
  email: string | null
  organization: string | null
  external_links: string[]
  source: string | null
  discovery_method: DiscoveryMethod
  discovered_via: string | null
  depth: number
  is_seed: boolean
  resolved: boolean
  first_seen: string
  last_seen: string
  created_at: string
  updated_at: string
  metadata: Record<string, unknown>
}

export interface EntityDetail extends Entity {
  snapshots: Snapshot[]
}

export interface EntitySummary {
  id: string
  type: EntityType
  platform: string
  platform_name: string
  name: string
  identifier: string
  url: string | null
}

export interface Evidence {
  id: string
  investigation_id: string
  relationship_id: string | null
  source_entity_id: string
  target_entity_id: string | null
  type: EvidenceType
  description: string
  source_url: string | null
  extracted_value: string | null
  /** The comparison form that actually matched, when it differs from the raw value. */
  normalized_value: string | null
  weight: number
  supports: boolean
  context: Record<string, unknown> | null
  collected_at: string
  stance: EvidenceStance
  /** Analyst-facing effect on the score, e.g. "+20". */
  score_impact: string
}

export type EvidenceStance = 'SUPPORTING' | 'CONTRADICTORY' | 'NEUTRAL'

export interface EvidenceBundle {
  relationship_id: string
  supporting: Evidence[]
  contradicting: Evidence[]
  neutral: Evidence[]
  total: number
}

export interface Relationship {
  id: string
  investigation_id: string
  source_entity_id: string
  target_entity_id: string
  relationship_type: RelationshipType
  relationship_label: string
  confidence_score: number
  confidence_level: ConfidenceLevel
  analyst_status: AnalystStatus
  analyst_note: string | null
  reviewed_at: string | null
  summary: string | null
  evidence_ids: string[]
  evidence_count: number
  created_at: string
  updated_at: string
}

export interface RelationshipDetail extends Relationship {
  source_entity: EntitySummary | null
  target_entity: EntitySummary | null
  evidence: Evidence[]
  contradiction_count: number
}

export interface GraphNode {
  id: string
  type: EntityType
  platform: string
  platform_name: string
  label: string
  identifier: string
  url: string | null
  display_name: string | null
  avatar_url: string | null
  is_seed: boolean
  resolved: boolean
  depth: number
  discovery_method: DiscoveryMethod
  degree: number
  confidence_level: ConfidenceLevel | null
  confidence_score: number | null
  position: { x: number; y: number }
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  relationship_type: RelationshipType
  relationship_label: string
  confidence_score: number
  confidence_level: ConfidenceLevel
  analyst_status: AnalystStatus
  evidence_count: number
  contradiction_count: number
  summary: string | null
}

export interface GraphStats {
  entities: number
  relationships: number
  evidence: number
  contradictions: number
  max_depth: number
  by_entity_type: Record<string, number>
  by_relationship_type: Record<string, number>
  by_confidence: Record<string, number>
  by_analyst_status: Record<string, number>
}

export interface InvestigationGraph {
  investigation_id: string
  generated_at: string
  seed_entity_id: string | null
  nodes: GraphNode[]
  edges: GraphEdge[]
  stats: GraphStats
}

export interface CrawlResult {
  investigation: Investigation
  entities_discovered: number
  relationships_created: number
  evidence_items: number
  pages_fetched: number
  issues: SourceIssue[]
}

/** Dashboard headline totals across every investigation (section 19). */
export interface GlobalStats {
  investigations: number
  entities: number
  relationships: number
  /** Relationships an analyst reviewed and judged supportive. */
  confirmed: number
  rejected: number
  by_platform: Record<string, number>
}

/** What the analyst typed, plus the options on the creation form. */
export interface NewInvestigationInput {
  identifier: string
  demo: boolean
  name?: string
}

/** Client-side graph filter state. */
export interface FilterState {
  entityTypes: Set<EntityType>
  relationshipTypes: Set<RelationshipType>
  confidenceLevels: Set<ConfidenceLevel>
  hideRejected: boolean
  minScore: number
}

// ---------------------------------------------------------------------------
// Identity Intelligence Profile
// ---------------------------------------------------------------------------

/** One publicly observed attribute, and the entities that published it. */
export interface ObservedValue {
  value: string
  label: string | null
  entity_ids: string[]
  platforms: string[]
  source_urls: string[]
  observation_count: number
  /** True when more than one entity published it independently. */
  corroborated: boolean
}

export interface PrimaryIdentifier {
  value: string
  type: string
  platform: string | null
  entity_id: string | null
}

export interface ObservedPlatform {
  platform: string
  platform_name: string
  entity_ids: string[]
  resolved: number
  total: number
}

export interface ProfileStatistics {
  entities: number
  accounts: number
  websites: number
  relationships: number
  potential_relationships: number
  high_confidence: number
  medium_confidence: number
  low_confidence: number
  contradictions: number
  evidence: number
  confirmed: number
  rejected: number
  unreviewed: number
  by_entity_type: Record<string, number>
}

export interface EvidenceSummary {
  by_type: Record<string, number>
  supporting: number
  contradicting: number
  neutral: number
  unexplained_relationships: number
  traceable: boolean
}

export interface IdentityProfile {
  investigation_id: string
  investigation_name: string
  demo: boolean
  disclaimer: string
  primary_identifier: PrimaryIdentifier
  potential_aliases: Alias[]
  platforms: ObservedPlatform[]
  websites: ObservedValue[]
  emails: ObservedValue[]
  organizations: ObservedValue[]
  locations: ObservedValue[]
  display_names: ObservedValue[]
  first_observed: string | null
  last_observed: string | null
  snapshot_count: number
  statistics: ProfileStatistics
  evidence_summary: EvidenceSummary
  contradictions: string[]
  has_aliases: boolean
}

// ---------------------------------------------------------------------------
// Aliases
// ---------------------------------------------------------------------------

export type AliasStrength = 'STRONG' | 'MODERATE' | 'WEAK' | 'NONE'

export interface AliasSignal {
  kind: string
  label: string
  detail: string
  weight: number
}

export interface Alias {
  relationship_id: string | null
  source_entity_id: string | null
  target_entity_id: string | null
  source_entity: EntitySummary | null
  target_entity: EntitySummary | null
  source_identifier: string
  target_identifier: string
  source_platform: string | null
  target_platform: string | null
  similarity: number
  strength: AliasStrength
  transformations: string[]
  signals: AliasSignal[]
  score: number
  confidence: ConfidenceLevel
  analyst_status: AnalystStatus
  supporting_evidence: Evidence[]
  contradicting_evidence: Evidence[]
  /** Always "Potential Alias" — never a confirmed one. */
  label: string
  contradiction_count: number
}

export interface AliasList {
  investigation_id: string
  primary_identifier: string | null
  aliases: Alias[]
  total: number
}

// ---------------------------------------------------------------------------
// Relationship paths
// ---------------------------------------------------------------------------

export interface PathStep {
  relationship_id: string
  relationship_type: RelationshipType
  relationship_label: string
  confidence_score: number
  confidence_level: ConfidenceLevel
  analyst_status: AnalystStatus
  evidence_count: number
  reversed: boolean
  entity: EntitySummary
}

export interface RelationshipPath {
  rank: number
  length: number
  start: EntitySummary
  steps: PathStep[]
  strength_score: number
  strength: string
  total_evidence: number
  contradictions: number
  confirmed_steps: number
  rejected_steps: number
  node_ids: string[]
  relationship_ids: string[]
  has_contradictions: boolean
  relationship_types: string[]
  summary: string
}

export interface PathResponse {
  investigation_id: string
  source_entity_id: string
  target_entity_id: string
  source_entity: EntitySummary | null
  target_entity: EntitySummary | null
  max_depth: number
  max_paths: number
  paths: RelationshipPath[]
  found: number
  message: string
}

/** What the graph should highlight, when a path is selected. */
export interface PathHighlight {
  nodeIds: Set<string>
  edgeIds: Set<string>
}

// ---------------------------------------------------------------------------
// Investigation leads
// ---------------------------------------------------------------------------

export type LeadPriority = 'HIGH' | 'MEDIUM' | 'LOW'

export interface Lead {
  id: string
  type: string
  priority: LeadPriority
  title: string
  description: string
  suggested_action: string
  related_entity_ids: string[]
  related_entities: EntitySummary[]
  related_relationship_ids: string[]
  supporting_evidence_ids: string[]
  score: number
  pivot_value: string | null
  label: string
  entity_count: number
}

export interface LeadList {
  investigation_id: string
  leads: Lead[]
  total: number
  by_priority: Record<string, number>
}

// ---------------------------------------------------------------------------
// Per-source results
// ---------------------------------------------------------------------------

/**
 * What happened when a source was queried.
 *
 * The two that matter most are the ones a graph cannot tell apart:
 * `NOT_FOUND` means the source answered and the handle is not there, while
 * `UNAVAILABLE` means it never answered at all. Both leave no node behind.
 */
export type SourceOutcome =
  | 'FOUND'
  | 'NOT_FOUND'
  | 'UNAVAILABLE'
  | 'REFERENCED_ONLY'
  | 'NOT_QUERIED'

export interface SourceResult {
  platform: string
  platform_name: string
  category: string
  outcome: SourceOutcome
  outcome_label: string

  entity: EntitySummary | null
  identifier: string | null
  display_name: string | null
  url: string | null

  confidence: ConfidenceLevel | null
  score: number | null
  analyst_status: AnalystStatus | null
  relationship_id: string | null
  evidence_count: number
  contradiction_count: number

  reason: string | null
  detail: string | null
  /** Whether there is an association here an analyst could rule on. */
  actionable: boolean
}

export interface SourceResults {
  investigation_id: string
  seed_identifier: string
  seed_type: string
  results: SourceResult[]
  summary: Record<string, number>
  found: number
  queried: number
}
