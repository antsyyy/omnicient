/**
 * The organizations one profile listed, as a single node.
 *
 * A Facebook Intro with five jobs and three degrees puts eight organization
 * nodes on the canvas for one account. They are worth keeping — a shared
 * employer is evidence the correlation engine scores on — but they are
 * attributes of a profile, not identities in their own right, and drawn as
 * peers of the accounts they swamp them.
 *
 * So they collapse into one node attached to the profile that listed them,
 * and open on click when an analyst actually wants to read them.
 */

import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { GraphNode } from '../types'

export interface OrgClusterData extends Record<string, unknown> {
  /** The organizations gathered here. */
  members: GraphNode[]
  /** The profile that listed them, for the caption. */
  sourceLabel: string
  expanded: boolean
  dimmed: boolean
  onToggle: () => void
}

export default function OrgClusterNode({ data, selected }: NodeProps) {
  const { members, sourceLabel, expanded, dimmed, onToggle } =
    data as OrgClusterData
  const preview = members.slice(0, 3)
  const rest = members.length - preview.length

  return (
    <div
      onClick={onToggle}
      className="cursor-pointer rounded-md border bg-panel px-3 py-2 shadow-lg transition-opacity"
      style={{
        minWidth: 172,
        maxWidth: 208,
        opacity: dimmed ? 0.25 : 1,
        borderColor: selected ? 'var(--color-accent)' : 'var(--color-line-bright)',
        borderStyle: 'dashed',
        borderWidth: selected ? 2 : 1,
      }}
      title={members.map((member) => member.label).join('\n')}
    >
      <Handle
        type="target"
        position={Position.Top}
        style={{
          width: 7,
          height: 7,
          background: 'var(--color-panel)',
          border: '1px solid var(--color-line-bright)',
        }}
      />

      <div className="panel-title flex items-center gap-1.5">
        <span aria-hidden>▣</span>
        <span>
          {members.length} {members.length === 1 ? 'organization' : 'organizations'}
        </span>
        <span className="ml-auto font-mono text-[9px]" aria-hidden>
          {expanded ? '▾' : '▸'}
        </span>
      </div>

      <div className="mt-1 space-y-0.5">
        {preview.map((member) => (
          <div
            key={member.id}
            className="truncate text-[11px] text-dim"
            title={member.label}
          >
            {member.display_name || member.label}
          </div>
        ))}
        {rest > 0 && (
          <div className="text-[11px] text-faint">and {rest} more</div>
        )}
      </div>

      <div className="mt-1.5 truncate border-t border-line pt-1 font-mono text-[9px] text-faint">
        listed on {sourceLabel}
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        style={{
          width: 7,
          height: 7,
          background: 'var(--color-panel)',
          border: '1px solid var(--color-line-bright)',
        }}
      />
    </div>
  )
}
