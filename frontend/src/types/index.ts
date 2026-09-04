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
  demo_seed: { platform: string; identifier: string }
  sources: string[]
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
  id: number
  investigation_id: string
  timestamp: string
  level: string
  event: string
  message: string
  data: Record<string, unknown> | null
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
  weight: number
  supports: boolean
  context: Record<string, unknown> | null
  collected_at: string
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

/** Client-side graph filter state. */
export interface FilterState {
  entityTypes: Set<EntityType>
  relationshipTypes: Set<RelationshipType>
  confidenceLevels: Set<ConfidenceLevel>
  hideRejected: boolean
  minScore: number
}
