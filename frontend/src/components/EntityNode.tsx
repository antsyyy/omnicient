import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { GraphNode } from '../types'
import {
  CONFIDENCE_COLOR,
  CONFIDENCE_LABEL,
  ENTITY_GLYPH,
} from '../lib/display'

export interface EntityNodeData extends Record<string, unknown> {
  node: GraphNode
  dimmed: boolean
}

/**
 * A graph node.
 *
 * Shows what the analyst needs before clicking: entity type, platform,
 * identifier, and the strongest confidence attached to it. Unresolved
 * candidates - referenced but never read publicly - are drawn dashed, so a
 * lead is never mistaken for an observation.
 */
export default function EntityNode({ data, selected }: NodeProps) {
  const { node, dimmed } = data as EntityNodeData
  const accent = node.confidence_level
    ? CONFIDENCE_COLOR[node.confidence_level]
    : 'var(--color-line-bright)'

  return (
    <div
      className="rounded-md border bg-panel px-3 py-2 shadow-lg transition-opacity"
      style={{
        minWidth: 168,
        maxWidth: 208,
        opacity: dimmed ? 0.25 : 1,
        borderColor: selected ? 'var(--color-accent)' : accent,
        borderStyle: node.resolved ? 'solid' : 'dashed',
        borderWidth: node.is_seed || selected ? 2 : 1,
        boxShadow: selected
          ? '0 0 0 3px rgba(34, 211, 238, 0.18)'
          : '0 6px 18px rgba(0, 0, 0, 0.45)',
      }}
    >
      <Handle type="target" position={Position.Top} />

      <div className="flex items-center justify-between gap-2">
        <span className="panel-title truncate" title={node.type}>
          <span style={{ color: accent }}>{ENTITY_GLYPH[node.type] ?? '◉'}</span>{' '}
          {node.platform_name}
        </span>
        {node.is_seed && (
          <span
            className="rounded-sm px-1 font-mono text-[9px] tracking-wider"
            style={{ background: 'var(--color-accent-dim)', color: '#04222a' }}
          >
            SEED
          </span>
        )}
      </div>

      <div
        className="mt-1 truncate font-mono text-[13px] text-ink"
        title={node.identifier}
      >
        {node.label}
      </div>

      {node.display_name && node.display_name !== node.label && (
        <div className="truncate text-[11px] text-faint" title={node.display_name}>
          {node.display_name}
        </div>
      )}

      <div className="mt-1.5 flex items-center justify-between gap-2">
        {node.confidence_level ? (
          <span
            className="font-mono text-[10px] tracking-wide"
            style={{ color: accent }}
            title={`Strongest association touching this entity: ${
              CONFIDENCE_LABEL[node.confidence_level]
            }`}
          >
            {CONFIDENCE_LABEL[node.confidence_level].toUpperCase()}
            {node.confidence_score !== null && ` · ${Math.round(node.confidence_score)}`}
          </span>
        ) : (
          <span className="font-mono text-[10px] text-faint">NO ASSOCIATION</span>
        )}
        {!node.resolved && (
          <span
            className="font-mono text-[9px] text-faint"
            title="Referenced publicly, but no public profile could be read"
          >
            UNRESOLVED
          </span>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}
