/**
 * The organizations one profile listed, as a single node.
 *
 * A Facebook Intro with five jobs and three degrees put eight organization
 * nodes on the canvas for one account — two thirds of the graph, drawn as
 * peers of the accounts they swamped. They are worth keeping, because a
 * shared employer is evidence the correlation engine scores on, but they are
 * attributes of a profile rather than identities in their own right.
 *
 * So they live here instead: one node per profile, listing all of them, and
 * no organization is ever drawn loose on the canvas.
 */

import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { GraphNode } from '../types'

export interface OrgClusterData extends Record<string, unknown> {
  /** Every organization this profile listed. */
  members: GraphNode[]
  /** The profile that listed them, for the caption. */
  sourceLabel: string
  dimmed: boolean
}

export default function OrgClusterNode({ data, selected }: NodeProps) {
  const { members, sourceLabel, dimmed } = data as OrgClusterData

  return (
    <div
      className="rounded-md border bg-panel px-3 py-2 shadow-lg transition-opacity"
      style={{
        minWidth: 188,
        maxWidth: 232,
        opacity: dimmed ? 0.25 : 1,
        borderColor: selected ? 'var(--color-accent)' : 'var(--color-line-bright)',
        borderStyle: 'dashed',
        borderWidth: selected ? 2 : 1,
      }}
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
      </div>

      {/*
        All of them, not a preview. A list long enough to need scrolling is
        rare, and capping the height keeps one profile's career from setting
        the height of the whole canvas.
      */}
      <ul className="mt-1 max-h-[180px] space-y-0.5 overflow-y-auto">
        {members.map((member) => (
          <li
            key={member.id}
            className="truncate text-[11px] leading-snug text-dim"
            title={member.display_name || member.label}
          >
            {member.display_name || member.label}
          </li>
        ))}
      </ul>

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
