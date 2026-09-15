/**
 * Typed REST client.
 *
 * Every call goes through `request`, so error handling, JSON parsing and the
 * base URL are defined once.  In development Vite proxies `/api` to the
 * FastAPI server; in other deployments set `VITE_API_BASE`.
 */

import type {
  AliasList,
  CrawlEvent,
  CrawlResult,
  EntityDetail,
  EvidenceBundle,
  GlobalStats,
  Health,
  IdentityProfile,
  LeadList,
  PathResponse,
  Investigation,
  InvestigationDetail,
  InvestigationGraph,
  ManualLinkInput,
  Relationship,
  RelationshipDetail,
  SourceResults,
} from '../types'

const BASE = import.meta.env.VITE_API_BASE ?? '/api'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch (cause) {
    throw new ApiError(
      'Could not reach the Omnicient API. Is the backend running?',
      0,
    )
  }

  if (response.status === 204) {
    return undefined as T
  }

  const text = await response.text()
  const body = text ? JSON.parse(text) : null

  if (!response.ok) {
    const detail =
      typeof body?.detail === 'string'
        ? body.detail
        : Array.isArray(body?.detail)
          ? body.detail.map((item: { msg?: string }) => item.msg).join('; ')
          : response.statusText
    throw new ApiError(detail || 'Request failed', response.status)
  }
  return body as T
}

export interface CreateInvestigationInput {
  /**
   * The only required field: a username, email, profile URL or domain.
   * The backend detects which it is - the client never picks a platform.
   */
  identifier: string
  /** Optional override; normally omitted so every source is searched. */
  platform?: string
  name?: string
  demo?: boolean
  max_depth?: number
  max_pages?: number
  auto_crawl?: boolean
}

export const api = {
  health: () => request<Health>('/health'),

  stats: () => request<GlobalStats>('/stats'),

  listInvestigations: () => request<Investigation[]>('/investigations'),

  createInvestigation: (input: CreateInvestigationInput) =>
    request<Investigation>('/investigations', {
      method: 'POST',
      body: JSON.stringify(input),
    }),

  getInvestigation: (id: string) =>
    request<InvestigationDetail>(`/investigations/${id}`),

  deleteInvestigation: (id: string) =>
    request<void>(`/investigations/${id}`, { method: 'DELETE' }),

  crawl: (id: string, options: { max_depth?: number; max_pages?: number; reset?: boolean } = {}) =>
    request<CrawlResult>(`/investigations/${id}/crawl`, {
      method: 'POST',
      body: JSON.stringify(options),
    }),

  getActivity: (id: string) =>
    request<CrawlEvent[]>(`/investigations/${id}/activity`),

  getProfile: (id: string) =>
    request<IdentityProfile>(`/investigations/${id}/profile`),

  getAliases: (id: string) => request<AliasList>(`/investigations/${id}/aliases`),

  getLeads: (id: string) => request<LeadList>(`/investigations/${id}/leads`),

  /** What each source yielded, including the ones that yielded nothing. */
  getResults: (id: string) =>
    request<SourceResults>(`/investigations/${id}/results`),

  findPaths: (
    id: string,
    sourceEntityId: string,
    targetEntityId: string,
    options: { max_depth?: number; max_paths?: number } = {},
  ) => {
    const params = new URLSearchParams({
      source_entity_id: sourceEntityId,
      target_entity_id: targetEntityId,
    })
    if (options.max_depth) params.set('max_depth', String(options.max_depth))
    if (options.max_paths) params.set('max_paths', String(options.max_paths))
    return request<PathResponse>(`/investigations/${id}/paths?${params}`)
  },

  getGraph: (id: string) =>
    request<InvestigationGraph>(`/investigations/${id}/graph`),

  getRelationships: (id: string) =>
    request<Relationship[]>(`/investigations/${id}/relationships`),

  getEntity: (id: string) => request<EntityDetail>(`/entities/${id}`),

  getEntityRelationships: (id: string) =>
    request<Relationship[]>(`/entities/${id}/relationships`),

  getRelationship: (id: string) =>
    request<RelationshipDetail>(`/relationships/${id}`),

  getRelationshipEvidence: (id: string) =>
    request<EvidenceBundle>(`/relationships/${id}/evidence`),

  confirmRelationship: (id: string, note?: string) =>
    request<RelationshipDetail>(`/relationships/${id}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ note: note ?? null }),
    }),

  rejectRelationship: (id: string, note?: string) =>
    request<RelationshipDetail>(`/relationships/${id}/reject`, {
      method: 'POST',
      body: JSON.stringify({ note: note ?? null }),
    }),

  /**
   * Rule that an entity belongs to somebody else.
   *
   * An analyst's assertion, and the only identity claim the system stores.
   * It deletes nothing: the account, its observations and its evidence all
   * survive, and `resetEntityIdentity` undoes it.
   */
  markDifferentIdentity: (id: string, note?: string) =>
    request<EntityDetail>(`/entities/${id}/different-identity`, {
      method: 'POST',
      body: JSON.stringify({ note: note ?? null }),
    }),

  resetEntityIdentity: (id: string) =>
    request<EntityDetail>(`/entities/${id}/reset-identity`, { method: 'POST' }),

  /** Draw a link by hand. Stamped as analyst-asserted, and scores nothing. */
  createLink: (investigationId: string, input: ManualLinkInput) =>
    request<Relationship>(`/investigations/${investigationId}/links`, {
      method: 'POST',
      body: JSON.stringify(input),
    }),

  /** Remove a link an analyst drew. Engine-derived edges are refused. */
  deleteLink: (relationshipId: string) =>
    request<void>(`/relationships/${relationshipId}`, { method: 'DELETE' }),

  resetRelationship: (id: string) =>
    request<RelationshipDetail>(`/relationships/${id}/reset`, { method: 'POST' }),

  /** Download link for an investigation export (section 29). */
  exportUrl: (id: string, format: 'json' | 'csv' = 'json') =>
    `${BASE}/investigations/${id}/export?download=true&format=${format}`,
}
