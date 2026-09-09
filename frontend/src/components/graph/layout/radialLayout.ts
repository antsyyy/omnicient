/**
 * Radial layout for the investigation canvas.
 *
 * The seed sits at the origin and category cards are distributed around it.
 * Nothing here is hardcoded to a particular investigation: the ring expands
 * to fit whatever cards exist, so a two-category investigation and a
 * nine-category one both read as a mind map rather than a pile.
 *
 * The algorithm is deterministic — same input, same positions — so a layout
 * reset returns the analyst to exactly the arrangement they knew.
 */

import {
  CARD_WIDTH,
  SEED_HEIGHT,
  SEED_WIDTH,
  categoryHeight,
  type MindMapCategory,
} from './mindMapLayout'

export interface Point {
  x: number
  y: number
}

export interface LayoutResult {
  seed: Point
  categories: Map<string, Point>
  /** Bounding box, so the canvas can fit the view without guessing. */
  bounds: { width: number; height: number }
}

/** Gap between the seed card and the nearest edge of a category card. */
const RING_GAP = 150
/** Minimum clearance between two adjacent cards on the ring. */
const CARD_GAP = 44
/** Where the first category is placed: straight up from the seed. */
const START_ANGLE = -Math.PI / 2

/**
 * Distance from the seed centre to each card centre.
 *
 * Grown until every card fits on the ring without touching its neighbours.
 * Solving this analytically for mixed card heights is fiddly and brittle;
 * stepping outward converges in a handful of iterations and is obvious to
 * read, which matters more here than micro-optimisation.
 */
function resolveRadius(
  categories: MindMapCategory[],
  collapsed: Set<string>,
  expanded: Set<string>,
): number {
  const count = categories.length
  if (count === 0) return 0

  const heights = categories.map((category) =>
    categoryHeight(category, collapsed.has(category.id), expanded.has(category.id)),
  )
  // Two adjacent cards can meet corner to corner, so clearance is measured
  // against the circle that encloses a card, not against its width or its
  // height alone. Anything less lets tall cards overlap on a crowded ring.
  const widestReach = Math.max(
    ...heights.map((height) => Math.hypot(CARD_WIDTH / 2, height / 2)),
  )

  // Start clear of the seed card itself.
  let radius = SEED_WIDTH / 2 + RING_GAP + CARD_WIDTH / 2
  if (count === 1) return radius

  // Every card needs an arc wide enough for its diagonal footprint plus a gap.
  const step = (2 * Math.PI) / count
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const chord = 2 * radius * Math.sin(step / 2)
    if (chord >= widestReach * 2 + CARD_GAP) break
    radius += 40
  }
  return radius
}

/**
 * Place the seed at the origin and the categories on a ring around it.
 *
 * Cards are anchored by their centre, then converted to the top-left origin
 * React Flow expects.
 */
export function calculateInvestigationLayout(
  categories: MindMapCategory[],
  collapsed: Set<string> = new Set(),
  expanded: Set<string> = new Set(),
): LayoutResult {
  const positions = new Map<string, Point>()
  const seed: Point = { x: -SEED_WIDTH / 2, y: -SEED_HEIGHT / 2 }

  if (categories.length === 0) {
    return { seed, categories: positions, bounds: { width: SEED_WIDTH, height: SEED_HEIGHT } }
  }

  const radius = resolveRadius(categories, collapsed, expanded)
  const step = (2 * Math.PI) / categories.length

  let minX = -SEED_WIDTH / 2
  let maxX = SEED_WIDTH / 2
  let minY = -SEED_HEIGHT / 2
  let maxY = SEED_HEIGHT / 2

  categories.forEach((category, index) => {
    const angle = START_ANGLE + index * step
    const height = categoryHeight(
      category,
      collapsed.has(category.id),
      expanded.has(category.id),
    )
    const centreX = Math.cos(angle) * radius
    const centreY = Math.sin(angle) * radius

    const point: Point = {
      x: centreX - CARD_WIDTH / 2,
      y: centreY - height / 2,
    }
    positions.set(category.id, point)

    minX = Math.min(minX, point.x)
    maxX = Math.max(maxX, point.x + CARD_WIDTH)
    minY = Math.min(minY, point.y)
    maxY = Math.max(maxY, point.y + height)
  })

  return {
    seed,
    categories: positions,
    bounds: { width: maxX - minX, height: maxY - minY },
  }
}

/**
 * Which side of a card an edge should leave from.
 *
 * Connecting a card on the left of the seed via its right edge, and one below
 * via its top edge, is what makes the curves read as spokes rather than as
 * arbitrary ribbon. Angle is measured from the seed.
 */
export function anchorFor(point: Point, height: number): 'top' | 'bottom' | 'left' | 'right' {
  const centreX = point.x + CARD_WIDTH / 2
  const centreY = point.y + height / 2
  if (Math.abs(centreX) > Math.abs(centreY)) {
    return centreX > 0 ? 'left' : 'right'
  }
  return centreY > 0 ? 'top' : 'bottom'
}
