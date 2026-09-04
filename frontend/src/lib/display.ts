/**
 * Presentation helpers shared by the panels and the graph.
 *
 * Confidence bands, analyst verdicts and entity types each own one colour and
 * one wording, defined here so the graph and the panels can never disagree.
 */

import type {
  ConfidenceLevel,
  AnalystStatus,
  EntityType,
  RelationshipType,
} from '../types'

export const CONFIDENCE_COLOR: Record<ConfidenceLevel, string> = {
  VERY_HIGH: 'var(--color-band-very-high)',
  HIGH: 'var(--color-band-high)',
  MEDIUM: 'var(--color-band-medium)',
  LOW: 'var(--color-band-low)',
  INSUFFICIENT: 'var(--color-band-insufficient)',
}

export const CONFIDENCE_LABEL: Record<ConfidenceLevel, string> = {
  VERY_HIGH: 'Very High',
  HIGH: 'High',
  MEDIUM: 'Medium',
  LOW: 'Low',
  INSUFFICIENT: 'Insufficient evidence',
}

export const CONFIDENCE_ORDER: ConfidenceLevel[] = [
  'VERY_HIGH',
  'HIGH',
  'MEDIUM',
  'LOW',
]

export const ENTITY_TYPES: EntityType[] = [
  'ACCOUNT',
  'WEBSITE',
  'DOMAIN',
  'EMAIL',
  'ORGANIZATION',
]

export const ENTITY_LABEL: Record<string, string> = {
  ACCOUNT: 'Accounts',
  WEBSITE: 'Websites',
  DOMAIN: 'Domains',
  EMAIL: 'Emails',
  ORGANIZATION: 'Organizations',
  PERSON: 'People',
  USERNAME: 'Usernames',
}

export const RELATIONSHIP_TYPES: RelationshipType[] = [
  'LINKS_TO',
  'REFERENCES',
  'POTENTIAL_SAME_IDENTITY',
  'SHARED_WEBSITE',
  'SHARED_EMAIL',
  'SHARED_AVATAR',
  'SHARED_ATTRIBUTE',
  'USES_USERNAME',
  'CONTRADICTORY',
]

export const RELATIONSHIP_LABEL: Record<RelationshipType, string> = {
  LINKS_TO: 'Links To',
  REFERENCES: 'References',
  USES_USERNAME: 'Uses Username',
  SHARED_WEBSITE: 'Shared Website',
  SHARED_EMAIL: 'Shared Email',
  SHARED_AVATAR: 'Shared Avatar',
  SHARED_ATTRIBUTE: 'Shared Attribute',
  POTENTIAL_SAME_IDENTITY: 'Potential Same Identity',
  CONTRADICTORY: 'Contradictory',
}

export const STATUS_COLOR: Record<AnalystStatus, string> = {
  UNREVIEWED: 'var(--color-faint)',
  CONFIRMED: 'var(--color-confirmed)',
  REJECTED: 'var(--color-rejected)',
}

/** A short glyph per entity type — legible at graph zoom levels. */
export const ENTITY_GLYPH: Record<string, string> = {
  ACCOUNT: '◉',
  WEBSITE: '▤',
  DOMAIN: '◈',
  EMAIL: '✉',
  ORGANIZATION: '▣',
  PERSON: '☗',
  USERNAME: '@',
}

export const DISCOVERY_LABEL: Record<string, string> = {
  SEED: 'Seed identifier',
  DIRECT: 'Directly linked from the seed',
  INDIRECT: 'Discovered through another entity',
  SIMILARITY: 'Weak lead: similar handle',
  DEMO: 'Demo dataset',
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatDay(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  })
}

export function formatTime(value: string): string {
  return new Date(value).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/** Strip the scheme so links read as identifiers, not addresses. */
export function shortUrl(url: string | null | undefined, max = 42): string {
  if (!url) return '—'
  const trimmed = url.replace(/^https?:\/\//, '').replace(/\/$/, '')
  return trimmed.length > max ? `${trimmed.slice(0, max - 1)}…` : trimmed
}
