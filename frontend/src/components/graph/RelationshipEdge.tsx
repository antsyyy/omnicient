import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@xyflow/react'
import type { GraphEdge } from '../../types'
import { CONFIDENCE_COLOR } from '../../lib/display'

export interface RelationshipEdgeData extends Record<string, unknown> {
  edge: GraphEdge
  dimmed: boolean
  /** Label is shown on selection, hover, or when the relationship is strong. */
  showLabel: boolean
  onHover: (edgeId: string | null) => void
}

/**
 * How the stroke communicates what kind of claim an edge is making.
 *
 * This is the part of the redesign that carries the product philosophy. A
 * confirmed association and an unreviewed inference must not look alike, or
 * the graph quietly turns a guess into a fact:
 *
 *   solid          an analyst reviewed the evidence and agreed
 *   dashed         an inference the tool is proposing, not asserting
 *   dotted + red   contradicted, or rejected by an analyst
 *
 * Directly observed links (LINKS_TO, REFERENCES) are solid because they were
 * read off a page — no inference is involved in saying a profile links to a
 * site.
 */
function strokeFor(edge: GraphEdge): {
  color: string
  dash: string | undefined
  width: number
  animated: boolean
} {
  if (edge.analyst_status === 'REJECTED') {
    return { color: 'var(--color-rejected)', dash: '2 6', width: 1.2, animated: false }
  }
  if (edge.relationship_type === 'CONTRADICTORY' || edge.contradiction_count > 0) {
    return { color: 'var(--color-contradiction)', dash: '2 5', width: 1.6, animated: false }
  }
  if (edge.analyst_status === 'CONFIRMED') {
    return { color: 'var(--color-confirmed)', dash: undefined, width: 2.6, animated: false }
  }

  const inferred =
    edge.relationship_type === 'POTENTIAL_SAME_IDENTITY' ||
    edge.relationship_type === 'POTENTIAL_ALIAS'
  return {
    color: CONFIDENCE_COLOR[edge.confidence_level],
    // An inference is drawn as a proposal, never as an observation.
    dash: inferred ? '7 5' : undefined,
    width: inferred ? 1.8 : 1.4,
    animated: inferred && edge.confidence_level === 'VERY_HIGH',
  }
}

/**
 * A relationship, drawn as a smooth curve between two entities.
 *
 * Labels are deliberately conditional. Labelling every edge in a
 * forty-entity investigation produces a wall of text nobody reads, so a label
 * appears when the edge is selected or hovered, or when the relationship is
 * one an analyst should not miss.
 */
export default function RelationshipEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
}: EdgeProps) {
  const { edge, dimmed, showLabel, onHover } = data as RelationshipEdgeData
  const stroke = strokeFor(edge)

  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    // A gentle curve reads as a mind map; a tight one reads as a flowchart.
    curvature: 0.34,
  })

  const visible = showLabel || selected

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        style={{
          stroke: selected ? 'var(--color-accent)' : stroke.color,
          strokeWidth: selected ? stroke.width + 1.4 : stroke.width,
          strokeDasharray: stroke.dash,
          opacity: dimmed ? 0.08 : selected ? 1 : 0.75,
          transition: 'opacity 160ms ease, stroke-width 160ms ease',
        }}
        className={stroke.animated && !dimmed ? 'omni-edge-flow' : undefined}
      />

      {/* A wide transparent stroke makes a 1.5px curve practical to hover. */}
      <path
        d={path}
        fill="none"
        stroke="transparent"
        strokeWidth={18}
        style={{ pointerEvents: dimmed ? 'none' : 'stroke', cursor: 'pointer' }}
        onMouseEnter={() => onHover(edge.id)}
        onMouseLeave={() => onHover(null)}
      />

      {visible && !dimmed && (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan pointer-events-none absolute rounded border px-1.5 py-0.5"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              background: 'var(--color-void)',
              borderColor: selected ? 'var(--color-accent)' : 'var(--color-line)',
              color: selected ? 'var(--color-accent)' : stroke.color,
              fontSize: 9,
              fontFamily: 'var(--font-mono, ui-monospace)',
              letterSpacing: '0.04em',
              whiteSpace: 'nowrap',
            }}
          >
            {edge.relationship_label.toLowerCase()}
            {edge.relationship_type === 'POTENTIAL_SAME_IDENTITY' && (
              <span className="ml-1 opacity-70">
                {Math.round(edge.confidence_score)}
              </span>
            )}
            {edge.contradiction_count > 0 && (
              <span className="ml-1 text-contradiction">
                ⚠{edge.contradiction_count}
              </span>
            )}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}
