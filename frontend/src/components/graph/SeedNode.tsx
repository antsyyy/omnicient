import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { GraphNode } from '../../types'
import { CONFIDENCE_COLOR, CONFIDENCE_LABEL } from '../../lib/display'
import { SEED_HEIGHT, SEED_WIDTH } from './layout/mindMapLayout'

export interface SeedNodeData extends Record<string, unknown> {
  node: GraphNode
  dimmed: boolean
  matched: boolean
}

/**
 * The investigation's origin, and the visual anchor of the canvas.
 *
 * Deliberately the largest element: an analyst opening a case should see what
 * it started from before anything else.
 *
 * When the seed is a bare handle no person is named. Inventing "Alice
 * Example" from `alice_98` would be exactly the unfounded identity claim this
 * tool exists to avoid, so the handle stands on its own and the type label
 * says what it actually is.
 */
export default function SeedNode({ data, selected }: NodeProps) {
  const { node, dimmed, matched } = data as SeedNodeData
  const hasPerson = Boolean(node.display_name)

  return (
    <div
      className="relative rounded-lg border transition-all"
      style={{
        width: SEED_WIDTH,
        minHeight: SEED_HEIGHT,
        opacity: dimmed ? 0.3 : 1,
        background:
          'radial-gradient(120% 120% at 50% 0%, #16202e 0%, var(--color-panel) 70%)',
        borderColor: matched
          ? 'var(--color-band-medium)'
          : selected
            ? 'var(--color-accent)'
            : 'var(--color-accent-dim)',
        borderWidth: 2,
        boxShadow: selected
          ? '0 0 0 4px rgba(34, 211, 238, 0.16), 0 18px 44px rgba(0,0,0,0.55)'
          : '0 0 0 1px rgba(34,211,238,0.08), 0 18px 44px rgba(0,0,0,0.5)',
      }}
    >
      {/* One handle per side so spokes leave toward their category. */}
      {(['top', 'right', 'bottom', 'left'] as const).map((side) => (
        <div key={side}>
          <Handle
            id={`seed-${side}`}
            type="source"
            position={Position[
              (side.charAt(0).toUpperCase() + side.slice(1)) as
                | 'Top'
                | 'Right'
                | 'Bottom'
                | 'Left'
            ]}
            style={{ opacity: 0, pointerEvents: 'none' }}
          />
          <Handle
            id={`seed-${side}-in`}
            type="target"
            position={Position[
              (side.charAt(0).toUpperCase() + side.slice(1)) as
                | 'Top'
                | 'Right'
                | 'Bottom'
                | 'Left'
            ]}
            style={{ opacity: 0, pointerEvents: 'none' }}
          />
        </div>
      ))}

      <div className="px-4 pb-3 pt-3.5">
        <div className="flex items-center gap-1.5">
          <span
            className="rounded-sm px-1.5 py-0.5 font-mono text-[9px] font-medium tracking-[0.14em]"
            style={{
              color: 'var(--color-accent)',
              background: 'rgba(34,211,238,0.1)',
            }}
          >
            SEED ENTITY
          </span>
          {!node.resolved && (
            <span className="font-mono text-[9px] tracking-wider text-faint">
              UNRESOLVED
            </span>
          )}
        </div>

        {hasPerson ? (
          <>
            <div className="mt-2 truncate text-[17px] font-semibold leading-tight text-ink">
              {node.display_name}
            </div>
            <div className="mt-0.5 font-mono text-[10px] uppercase tracking-wider text-faint">
              Potential digital entity
            </div>
          </>
        ) : (
          <div className="mt-2 truncate font-mono text-[19px] font-semibold leading-tight text-ink">
            @{node.identifier}
          </div>
        )}

        <div className="mt-2.5 space-y-1 border-t border-line pt-2">
          {hasPerson && (
            <Row label="Identifier" value={`@${node.identifier}`} mono />
          )}
          <Row
            label={node.type === 'ACCOUNT' ? 'Platform' : 'Type'}
            value={node.type === 'ACCOUNT' ? node.platform_name : node.type}
          />
          {node.url && <Row label="Profile" value={node.url} mono truncate />}
          {node.confidence_level && (
            <Row
              label="Confidence"
              value={CONFIDENCE_LABEL[node.confidence_level]}
              color={CONFIDENCE_COLOR[node.confidence_level]}
            />
          )}
        </div>
      </div>
    </div>
  )
}

function Row({
  label,
  value,
  mono,
  truncate,
  color,
}: {
  label: string
  value: string
  mono?: boolean
  truncate?: boolean
  color?: string
}) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="w-[62px] shrink-0 font-mono text-[9px] uppercase tracking-wider text-faint">
        {label}
      </span>
      <span
        className={`min-w-0 flex-1 text-[11px] ${mono ? 'font-mono' : ''} ${
          truncate ? 'truncate' : ''
        }`}
        style={{ color: color ?? 'var(--color-dim)' }}
        title={value}
      >
        {value}
      </span>
    </div>
  )
}
