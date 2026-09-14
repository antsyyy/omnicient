import { Handle, Position, type NodeProps } from '@xyflow/react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import CategoryItem from './CategoryItem'
import type { MindMapCategory, MindMapItem } from './layout/mindMapLayout'
import {
  CARD_ITEM_HEIGHT,
  CARD_PADDING,
  CARD_WIDTH,
  hiddenItemCount,
  visibleItems,
} from './layout/mindMapLayout'

export interface CategoryGroupNodeData extends Record<string, unknown> {
  category: MindMapCategory
  collapsed: boolean
  /** Showing every row, past the display cap. */
  expanded: boolean
  selectedEntityId: string | null
  dimmedItems: Set<string> | null
  matchedItems: Set<string>
  onToggle: (categoryId: string) => void
  onToggleExpanded: (categoryId: string) => void
  onSelectEntity: (entityId: string) => void
  onItemContextMenu: (event: React.MouseEvent, item: MindMapItem) => void
}

/**
 * A cluster of discovered entities, as one card on the investigation board.
 *
 * This is the central idea of the redesign. Forty entities drawn as forty
 * circles is a network diagram and tells an analyst nothing; the same forty
 * grouped into "Social accounts", "Websites" and "Email addresses" is an
 * investigation they can read. The card is the unit of comprehension, the
 * rows inside it are the unit of interaction.
 *
 * Collapsing keeps the card and its connections while hiding the rows, so a
 * large investigation stays navigable without losing its shape.
 */
export default function CategoryGroupNode({ data }: NodeProps) {
  const {
    category,
    collapsed,
    expanded,
    selectedEntityId,
    dimmedItems,
    matchedItems,
    onToggle,
    onToggleExpanded,
    onSelectEntity,
    onItemContextMenu,
  } = data as CategoryGroupNodeData

  const rows = visibleItems(category, expanded)
  const hiddenCount = hiddenItemCount(category, expanded)

  const accent = category.style.accent
  const hasMatch = category.items.some((item) => matchedItems.has(item.id))

  return (
    <div
      className="rounded-lg border bg-panel transition-all"
      style={{
        width: CARD_WIDTH,
        borderColor: hasMatch ? 'var(--color-band-medium)' : 'var(--color-line)',
        boxShadow: '0 10px 30px rgba(0,0,0,0.45)',
        // The accent lives on one edge, so the card stays dark and the
        // category is still identifiable at a glance.
        borderLeft: `3px solid ${accent}`,
      }}
    >
      {/* Card-level anchors, used when the card is collapsed and its rows
          have no handles of their own. */}
      {(['Top', 'Right', 'Bottom', 'Left'] as const).map((side) => (
        <div key={side}>
          <Handle
            id={`group-${side.toLowerCase()}`}
            type="source"
            position={Position[side]}
            style={{ opacity: 0, pointerEvents: 'none' }}
          />
          <Handle
            id={`group-${side.toLowerCase()}-in`}
            type="target"
            position={Position[side]}
            style={{ opacity: 0, pointerEvents: 'none' }}
          />
        </div>
      ))}

      <button
        onClick={(event) => {
          event.stopPropagation()
          onToggle(category.id)
        }}
        className="flex w-full items-center gap-2 rounded-t-lg px-2.5 py-2 text-left transition-colors hover:bg-raised"
        style={{ background: 'rgba(255,255,255,0.02)' }}
        aria-expanded={!collapsed}
      >
        <span className="font-mono text-[11px]" style={{ color: accent }}>
          {category.style.glyph}
        </span>
        <span
          className="flex-1 truncate font-mono text-[10px] font-medium uppercase tracking-[0.12em]"
          style={{ color: accent }}
        >
          {category.style.title}
        </span>
        <span className="font-mono text-[9px] text-faint">
          {category.items.length}
        </span>
        {collapsed ? (
          <ChevronRight size={12} className="text-faint" />
        ) : (
          <ChevronDown size={12} className="text-faint" />
        )}
      </button>

      {collapsed ? (
        <div className="px-2.5 pb-2 font-mono text-[9.5px] text-faint">
          {category.items.length} item{category.items.length === 1 ? '' : 's'} hidden
        </div>
      ) : (
        <div
          className="border-t border-line"
          style={{ paddingTop: CARD_PADDING, paddingBottom: CARD_PADDING }}
        >
          {rows.map((item) => (
            <CategoryItem
              key={item.id}
              item={item}
              accent={accent}
              selected={selectedEntityId === item.id}
              dimmed={dimmedItems ? dimmedItems.has(item.id) : false}
              matched={matchedItems.has(item.id)}
              onSelect={onSelectEntity}
              onContextMenu={onItemContextMenu}
            />
          ))}

          {(hiddenCount > 0 || expanded) && (
            <button
              onClick={(event) => {
                event.stopPropagation()
                onToggleExpanded(category.id)
              }}
              className="flex w-full items-center px-2 text-left font-mono text-[10px] text-faint transition-colors hover:text-accent"
              style={{ height: CARD_ITEM_HEIGHT }}
            >
              {hiddenCount > 0 ? `+${hiddenCount} more` : 'show fewer'}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
