import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { GraphNode } from '../types'
import { CONFIDENCE_COLOR, CONFIDENCE_LABEL } from '../lib/display'
import Avatar from './Avatar'
import PlatformLogo from './PlatformLogo'

export interface EntityNodeData extends Record<string, unknown> {
  node: GraphNode
  dimmed: boolean
  /** On the selected path, or named by the selected lead. */
  highlighted?: boolean
}

/**
 * A graph node.
 *
 * Shows what the analyst needs before clicking: platform, identifier, and the
 * strongest confidence attached to it. Unresolved candidates - referenced but
 * never read publicly - are drawn dashed, so a lead is never mistaken for an
 * observation.
 *
 * The platform mark carries the confidence colour rather than its own brand
 * palette: at a glance across a hundred nodes, the logo says *where* and the
 * colour says *how strongly*.
 */
export default function EntityNode({ data, selected }: NodeProps) {
  const { node, dimmed, highlighted } = data as EntityNodeData
  /*
   * An entity the analyst has ruled to be somebody else.
   *
   * It is drawn set aside rather than removed, and the treatment says which
   * of the two it is. The confidence colour goes - a band describes how
   * strongly the *engine* associated this entity, and once a person has said
   * it is not the same party that number is answering a question nobody is
   * asking any more. What replaces it is the analyst's own mark: a muted
   * card, a struck-through handle, and the verdict spelled out where the
   * score used to be.
   *
   * Deliberately still legible. Fading it to near-nothing would make the
   * ruling feel like a delete, and the whole point is that it is not one.
   */
  const ruledOut = node.analyst_verdict === 'DIFFERENT_IDENTITY'
  const accent = ruledOut
    ? 'var(--color-rejected)'
    : node.confidence_level
      ? CONFIDENCE_COLOR[node.confidence_level]
      : 'var(--color-line-bright)'

  return (
    <div
      className="rounded-md border bg-panel px-3 py-2 shadow-lg transition-opacity"
      style={{
        minWidth: 168,
        maxWidth: 208,
        opacity: dimmed ? 0.25 : ruledOut ? 0.62 : 1,
        borderColor:
          selected || highlighted ? 'var(--color-accent)' : accent,
        borderStyle: node.resolved && !ruledOut ? 'solid' : 'dashed',
        borderWidth: node.is_seed || selected || highlighted ? 2 : 1,
        boxShadow:
          selected || highlighted
            ? '0 0 0 3px rgba(34, 211, 238, 0.18)'
            : '0 6px 18px rgba(0, 0, 0, 0.45)',
      }}
      title={
        ruledOut
          ? node.analyst_note
            ? `You ruled this a different party: ${node.analyst_note}`
            : 'You ruled this a different party.'
          : undefined
      }
    >
      {/*
        The connection points are how a link gets drawn, so they are visible
        rather than hidden until hover - an affordance nobody can find is one
        nobody uses.
      */}
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

      <div className="flex items-center justify-between gap-2">
        <span className="panel-title flex min-w-0 items-center gap-1.5" title={node.type}>
          <PlatformLogo
            platform={node.platform}
            entityType={node.type}
            size={13}
            className="shrink-0"
            title={node.platform_name}
            style={{ color: accent }}
          />
          <span className="truncate">{node.platform_name}</span>
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

      {/*
        The face beside the handle. It is decoration, not evidence: two
        accounts showing the same picture is something the engine has to
        observe and score, never something the canvas may imply by putting
        them side by side.
      */}
      <div className="mt-1 flex items-center gap-2">
        {node.avatar_url && (
          <Avatar
            url={node.avatar_url}
            platform={node.platform}
            entityType={node.type}
            size={26}
          />
        )}
        <div className="min-w-0">
          <div
            className={`truncate font-mono text-[13px] ${
              ruledOut ? 'text-dim line-through decoration-1' : 'text-ink'
            }`}
            title={node.identifier}
          >
            {node.label}
          </div>
          {node.display_name && node.display_name !== node.label && (
            <div className="truncate text-[11px] text-faint" title={node.display_name}>
              {node.display_name}
            </div>
          )}
        </div>
      </div>

      <div className="mt-1.5 flex items-center justify-between gap-2">
        {ruledOut ? (
          <span
            className="font-mono text-[10px] tracking-wide"
            style={{ color: 'var(--color-rejected)' }}
            title={node.analyst_note ?? undefined}
          >
            DIFFERENT IDENTITY
          </span>
        ) : node.confidence_level ? (
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

      <Handle
        type="source"
        position={Position.Bottom}
        style={{
          width: 7,
          height: 7,
          background: 'var(--color-panel)',
          border: '1px solid var(--color-asserted)',
        }}
        title="Drag onto another entity to draw a link"
      />
    </div>
  )
}
