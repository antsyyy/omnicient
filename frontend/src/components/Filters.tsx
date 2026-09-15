import type { ConfidenceLevel, EntityType, FilterState } from '../types'
import {
  CONFIDENCE_COLOR,
  CONFIDENCE_LABEL,
  CONFIDENCE_ORDER,
  ENTITY_LABEL,
  ENTITY_TYPES,
} from '../lib/display'

interface Props {
  filters: FilterState
  counts: {
    byEntityType: Record<string, number>
    /** Entities per band, and how many nothing has associated yet. */
    byConfidence: Record<string, number>
    unassociated: number
  }
  onChange: (next: FilterState) => void
}

function toggle<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set)
  if (next.has(value)) next.delete(value)
  else next.add(value)
  return next
}

function Row({
  label,
  checked,
  count,
  color,
  onToggle,
}: {
  label: string
  checked: boolean
  count?: number
  color?: string
  onToggle: () => void
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 py-[3px] text-[12px] text-dim hover:text-ink">
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        className="h-3 w-3 accent-[var(--color-accent)]"
      />
      {color && (
        <span
          className="inline-block h-[7px] w-[7px] rounded-full"
          style={{ background: color }}
        />
      )}
      <span className="flex-1 truncate">{label}</span>
      <span className="font-mono text-[10px] text-faint">{count ?? 0}</span>
    </label>
  )
}

/**
 * Filter panel: the graph updates as soon as anything here changes.
 *
 * Both filters narrow the *entities* on the canvas, which is what an analyst
 * is actually looking at. The relationship-type and minimum-score controls
 * that used to live here narrowed edges instead, and since the canvas only
 * draws associations somebody has confirmed, they spent most of their life
 * filtering lines that were already hidden.
 */
export default function Filters({ filters, counts, onChange }: Props) {
  return (
    <div className="space-y-4">
      <section>
        <div className="panel-title mb-1">Entity type</div>
        {ENTITY_TYPES.map((type: EntityType) => (
          <Row
            key={type}
            label={ENTITY_LABEL[type] ?? type}
            checked={filters.entityTypes.has(type)}
            count={counts.byEntityType[type]}
            onToggle={() =>
              onChange({ ...filters, entityTypes: toggle(filters.entityTypes, type) })
            }
          />
        ))}
      </section>

      <section>
        <div className="panel-title mb-1">Strongest association</div>
        {CONFIDENCE_ORDER.map((level: ConfidenceLevel) => (
          <Row
            key={level}
            label={CONFIDENCE_LABEL[level]}
            color={CONFIDENCE_COLOR[level]}
            checked={filters.confidenceLevels.has(level)}
            count={counts.byConfidence[level]}
            onToggle={() =>
              onChange({
                ...filters,
                confidenceLevels: toggle(filters.confidenceLevels, level),
              })
            }
          />
        ))}
        {/*
          The seed, and anything found but not yet tied to anything. Without a
          row of its own it would disappear the moment a band was unchecked,
          taking the starting point of the investigation with it.
        */}
        <Row
          label="Not associated yet"
          checked={filters.showUnassociated}
          count={counts.unassociated}
          onToggle={() =>
            onChange({ ...filters, showUnassociated: !filters.showUnassociated })
          }
        />
        <p className="mt-1 text-[11px] leading-snug text-faint">
          The band of the strongest association touching an entity.
        </p>
      </section>
    </div>
  )
}
