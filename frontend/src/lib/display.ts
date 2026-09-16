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
  SourceOutcome,
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

/**
 * Entity types the graph draws, and therefore the ones its filter offers.
 *
 * ORGANIZATION is deliberately absent: an employer or a school is an
 * attribute of a profile rather than an identity, and one Facebook Intro puts
 * eight of them on the canvas. They are still collected, still scored, and
 * still listed on the profile panel - a filter row for them would just be a
 * control with nothing to control.
 */
export const ENTITY_TYPES: EntityType[] = [
  'ACCOUNT',
  'WEBSITE',
  'DOMAIN',
  'EMAIL',
  // A bare handle seeds a USERNAME pivot node. Leaving it out of this list
  // filtered the seed off its own canvas: an investigation started from a
  // username drew every account it found and not the handle they came from.
  'USERNAME',
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
  'POTENTIAL_ALIAS',
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
  POTENTIAL_ALIAS: 'Potential Alias',
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

// ---------------------------------------------------------------------------
// Per-source results
// ---------------------------------------------------------------------------

/**
 * Outcomes are grouped, not merely coloured.
 *
 * "Nothing found" and "Source unavailable" both leave the list empty-handed,
 * so the interface has to work to keep them apart: a refusal is an open
 * question an analyst can still pursue, an absence is a closed one.
 */
export const OUTCOME_ORDER: SourceOutcome[] = [
  'FOUND',
  'REFERENCED_ONLY',
  'UNAVAILABLE',
  'NOT_FOUND',
  'NOT_QUERIED',
]

export const OUTCOME_COLOR: Record<SourceOutcome, string> = {
  FOUND: 'var(--color-confirmed)',
  REFERENCED_ONLY: 'var(--color-band-medium)',
  UNAVAILABLE: 'var(--color-contradiction)',
  NOT_FOUND: 'var(--color-faint)',
  NOT_QUERIED: 'var(--color-band-insufficient)',
}

/** Section headings: what the group means, not just what it is called. */
export const OUTCOME_HEADING: Record<SourceOutcome, string> = {
  FOUND: 'Accounts found',
  REFERENCED_ONLY: 'Referenced, not read',
  UNAVAILABLE: 'Could not be searched',
  NOT_FOUND: 'Searched, nothing found',
  NOT_QUERIED: 'Not searched',
}

export const OUTCOME_NOTE: Record<SourceOutcome, string> = {
  FOUND: 'Public data was returned. Each row shows the evidence behind it.',
  REFERENCED_ONLY:
    'Another account linked to these, but they were never read directly.',
  UNAVAILABLE:
    'These sources did not answer. The question stays open — a result here is absence of evidence, not evidence of absence.',
  NOT_FOUND: 'These sources answered: the identifier is not on them.',
  NOT_QUERIED: 'Registered sources this run did not reach.',
}

export const CATEGORY_LABEL: Record<string, string> = {
  social: 'Social',
  dev: 'Developer',
  gaming: 'Gaming',
  music: 'Music',
  learning: 'Learning',
  web: 'Web',
  identity: 'Identity',
}

/** Why a source could not be read, in an analyst's words. */
export const REASON_LABEL: Record<string, string> = {
  NOT_FOUND: 'No public profile at that address',
  PRIVATE: 'Private, or behind a login wall',
  BLOCKED: 'The platform declined the request',
  RATE_LIMITED: 'Rate limited — Omnicient stops rather than evading',
  TIMEOUT: 'The request timed out',
  NETWORK_ERROR: 'The host could not be reached',
  ROBOTS_DISALLOWED: 'robots.txt disallows crawling this path',
  UNSAFE_URL: 'Rejected by the SSRF guard',
  TOO_LARGE: 'The response exceeded the size limit',
  PARSE_ERROR: 'The response could not be parsed',
  UNSUPPORTED: 'No adapter for this source',
  BUDGET_EXHAUSTED: 'The crawl budget was spent before reaching it',
}

// ---------------------------------------------------------------------------
// Where a link came from
// ---------------------------------------------------------------------------

/**
 * An analyst-drawn link is not a weak engine finding — it is a different kind
 * of thing, resting on a person's judgement instead of an observation. It gets
 * its own colour so it can never be read as a point on the confidence scale.
 */
export const ASSERTED_COLOR = 'var(--color-asserted)'

export const ORIGIN_LABEL: Record<string, string> = {
  ENGINE: 'Derived from evidence',
  ANALYST: 'Asserted by an analyst',
}
