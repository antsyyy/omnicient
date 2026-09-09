import { Handle, Position } from '@xyflow/react'
import type { MindMapItem } from './layout/mindMapLayout'
import { CARD_ITEM_HEIGHT } from './layout/mindMapLayout'
import { CONFIDENCE_COLOR } from '../../lib/display'

interface Props {
  item: MindMapItem
  accent: string
  selected: boolean
  dimmed: boolean
  matched: boolean
  onSelect: (entityId: string) => void
  onContextMenu: (event: React.MouseEvent, item: MindMapItem) => void
}

/**
 * One discovered entity, as a row inside its category card.
 *
 * Rows carry their own React Flow handles, so a relationship is drawn from the
 * *entity* it actually concerns rather than from the card that happens to
 * contain it. That is what keeps the mind map honest: the curve between
 * `@alice_98` and `alice.dev` lands on those two rows, not on two boxes.
 *
 * An unresolved entity — referenced somewhere but never publicly read — is
 * drawn muted with a hollow marker, so a lead is never mistaken for an
 * observation.
 */
export default function CategoryItem({
  item,
  accent,
  selected,
  dimmed,
  matched,
  onSelect,
  onContextMenu,
}: Props) {
  const confidenceColor = item.confidence
    ? CONFIDENCE_COLOR[item.confidence]
    : 'var(--color-faint)'

  return (
    <div
      className="group relative"
      style={{ height: CARD_ITEM_HEIGHT, opacity: dimmed ? 0.28 : 1 }}
    >
      {/* Anchors for edges into and out of this specific entity. */}
      <Handle
        id={item.id}
        type="source"
        position={Position.Left}
        style={{ opacity: 0, pointerEvents: 'none', top: '50%' }}
      />
      <Handle
        id={`${item.id}-in`}
        type="target"
        position={Position.Right}
        style={{ opacity: 0, pointerEvents: 'none', top: '50%' }}
      />

      <button
        onClick={(event) => {
          event.stopPropagation()
          onSelect(item.id)
        }}
        onContextMenu={(event) => onContextMenu(event, item)}
        className="flex h-full w-full items-center gap-2 rounded px-2 text-left transition-colors"
        style={{
          background: selected
            ? 'rgba(34,211,238,0.12)'
            : matched
              ? 'rgba(251,191,36,0.12)'
              : 'transparent',
          boxShadow: selected ? `inset 2px 0 0 ${accent}` : undefined,
        }}
        title={item.node.url ?? item.label}
      >
        <span
          className="shrink-0 font-mono text-[9px]"
          style={{ color: item.resolved ? confidenceColor : 'var(--color-faint)' }}
        >
          {item.resolved ? '●' : '○'}
        </span>

        <span className="min-w-0 flex-1 truncate">
          <span
            className="font-mono text-[11.5px]"
            style={{ color: selected ? 'var(--color-ink)' : 'var(--color-dim)' }}
          >
            {item.label}
          </span>
        </span>

        {item.sublabel && (
          <span className="shrink-0 truncate text-[9.5px] text-faint" style={{ maxWidth: 82 }}>
            {item.sublabel}
          </span>
        )}
      </button>
    </div>
  )
}
