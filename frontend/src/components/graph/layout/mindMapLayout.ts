/**
 * Turns the backend investigation graph into an investigation mind map.
 *
 * The database stores a true graph: one node per entity, one edge per
 * relationship. That is the right shape for querying and the wrong shape for
 * reading — forty individual nodes tell an analyst nothing at a glance.
 *
 * This layer regroups the same data into *information clusters*: a dominant
 * seed, categories around it, and the discovered entities as compact rows
 * inside those categories. Nothing is invented and nothing is dropped; every
 * item still carries its entity id, so selection, evidence and the analyst
 * workflow keep working against the real graph.
 *
 * Neo4j remains the source of truth. This is a view.
 */

import type {
  ConfidenceLevel,
  GraphEdge,
  GraphNode,
  InvestigationGraph,
} from '../../../types'

/** The clusters an investigation is read through. */
export type CategoryKey =
  | 'USERNAME'
  | 'EMAIL'
  | 'SOCIAL'
  | 'WEBSITE'
  | 'DOMAIN'
  | 'ORGANIZATION'
  | 'LOCATION'
  | 'RELATED'

export interface CategoryStyle {
  key: CategoryKey
  title: string
  /** Subtle accent — a colored edge on a dark card, never a colored card. */
  accent: string
  glyph: string
}

/**
 * Category identity, in the order they are laid out around the seed.
 *
 * The order is deliberate rather than alphabetical: identifiers sit above the
 * seed, the accounts they resolve to sit to its right, and the infrastructure
 * those accounts point at sits below. An analyst reading clockwise from the
 * top follows the investigation outward.
 */
export const CATEGORIES: CategoryStyle[] = [
  { key: 'USERNAME', title: 'Usernames', accent: '#a78bfa', glyph: '@' },
  { key: 'SOCIAL', title: 'Social accounts', accent: '#38bdf8', glyph: '◉' },
  { key: 'WEBSITE', title: 'Websites', accent: '#22d3ee', glyph: '▤' },
  { key: 'DOMAIN', title: 'Domains', accent: '#2dd4bf', glyph: '◈' },
  { key: 'ORGANIZATION', title: 'Organizations', accent: '#34d399', glyph: '▣' },
  { key: 'EMAIL', title: 'Email addresses', accent: '#fbbf24', glyph: '✉' },
  { key: 'LOCATION', title: 'Locations', accent: '#fb923c', glyph: '⌖' },
  { key: 'RELATED', title: 'Related entities', accent: '#f472b6', glyph: '⁂' },
]

export const CATEGORY_BY_KEY: Record<CategoryKey, CategoryStyle> =
  Object.fromEntries(CATEGORIES.map((entry) => [entry.key, entry])) as Record<
    CategoryKey,
    CategoryStyle
  >

/**
 * Which cluster an entity belongs in.
 *
 * Driven by entity type rather than platform, so a newly added source adapter
 * lands in the right category without touching this file.
 */
export function categoryFor(node: GraphNode): CategoryKey {
  switch (node.type) {
    case 'USERNAME':
      return 'USERNAME'
    case 'EMAIL':
      return 'EMAIL'
    case 'WEBSITE':
      return 'WEBSITE'
    case 'DOMAIN':
      return 'DOMAIN'
    case 'ORGANIZATION':
      return 'ORGANIZATION'
    case 'ACCOUNT':
      return 'SOCIAL'
    default:
      return 'RELATED'
  }
}

export interface MindMapItem {
  /** The real entity id — selection and evidence resolve against this. */
  id: string
  label: string
  /** Platform name for an account, or the discovery route for anything else. */
  sublabel: string | null
  node: GraphNode
  confidence: ConfidenceLevel | null
  depth: number
  resolved: boolean
}

export interface MindMapCategory {
  /** Node id on the canvas, distinct from any entity id. */
  id: string
  key: CategoryKey
  style: CategoryStyle
  items: MindMapItem[]
  /** Shallowest item, used for depth filtering and layout ordering. */
  minDepth: number
}

export interface MindMap {
  seed: GraphNode | null
  categories: MindMapCategory[]
  edges: GraphEdge[]
  /** Entity id -> the category node holding it, for edge re-pointing. */
  ownerOf: Map<string, string>
  maxDepth: number
}

/** Card geometry, shared by the layout and the node components. */
export const CARD_WIDTH = 236
export const CARD_HEADER_HEIGHT = 34
export const CARD_ITEM_HEIGHT = 30
export const CARD_PADDING = 8
export const SEED_WIDTH = 268
export const SEED_HEIGHT = 148

/**
 * Rows shown before a category offers to reveal the rest.
 *
 * A category holding thirty entities becomes a 900px column that dominates
 * the board and cannot be read anyway. Capping the rows keeps every card a
 * comparable size, which is what lets the radial layout stay legible as an
 * investigation grows.
 */
export const VISIBLE_ITEM_LIMIT = 10

/** Rows actually rendered for a category in its current state. */
export function visibleItems(
  category: MindMapCategory,
  expanded: boolean,
): MindMapItem[] {
  if (expanded || category.items.length <= VISIBLE_ITEM_LIMIT) {
    return category.items
  }
  return category.items.slice(0, VISIBLE_ITEM_LIMIT)
}

export function hiddenItemCount(
  category: MindMapCategory,
  expanded: boolean,
): number {
  return category.items.length - visibleItems(category, expanded).length
}

export function categoryHeight(
  category: MindMapCategory,
  collapsed: boolean,
  expanded = false,
): number {
  if (collapsed) return CARD_HEADER_HEIGHT + 20
  const rows = visibleItems(category, expanded).length
  const more = hiddenItemCount(category, expanded) > 0 ? CARD_ITEM_HEIGHT : 0
  return CARD_HEADER_HEIGHT + CARD_PADDING * 2 + rows * CARD_ITEM_HEIGHT + more
}

/**
 * Regroup an investigation graph into seed + categories + edges.
 *
 * The seed is lifted out of its category so it can be the dominant element;
 * showing it twice would be noise.
 */
export function investigationToMindMap(graph: InvestigationGraph): MindMap {
  const seed =
    graph.nodes.find((node) => node.is_seed) ??
    graph.nodes.find((node) => node.depth === 0) ??
    null

  const buckets = new Map<CategoryKey, MindMapItem[]>()
  const ownerOf = new Map<string, string>()
  let maxDepth = 0

  for (const node of graph.nodes) {
    maxDepth = Math.max(maxDepth, node.depth)
    if (seed && node.id === seed.id) continue

    const key = categoryFor(node)
    const item: MindMapItem = {
      id: node.id,
      label: node.identifier || node.label,
      sublabel:
        node.type === 'ACCOUNT'
          ? node.platform_name
          : node.display_name || null,
      node,
      confidence: node.confidence_level,
      depth: node.depth,
      resolved: node.resolved,
    }
    const bucket = buckets.get(key)
    if (bucket) bucket.push(item)
    else buckets.set(key, [item])
  }

  const categories: MindMapCategory[] = []
  // CATEGORIES order drives layout order, so iterate it rather than the map.
  for (const style of CATEGORIES) {
    const items = buckets.get(style.key)
    if (!items || items.length === 0) continue

    // Resolved entities first, then shallower, then alphabetical: what was
    // actually read outranks what was merely referenced.
    items.sort(
      (a, b) =>
        Number(b.resolved) - Number(a.resolved) ||
        a.depth - b.depth ||
        a.label.localeCompare(b.label),
    )

    const id = `category-${style.key}`
    for (const item of items) ownerOf.set(item.id, id)
    categories.push({
      id,
      key: style.key,
      style,
      items,
      minDepth: Math.min(...items.map((item) => item.depth)),
    })
  }

  if (seed) ownerOf.set(seed.id, 'seed')

  return { seed, categories, edges: graph.edges, ownerOf, maxDepth }
}

/**
 * The canvas node an entity is drawn inside.
 *
 * Edges are stored entity-to-entity but drawn card-to-card, so every edge
 * endpoint is translated through this before it reaches React Flow.
 */
export function canvasNodeFor(map: MindMap, entityId: string): string | null {
  return map.ownerOf.get(entityId) ?? null
}
