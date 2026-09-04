import type { ConfidenceLevel, EntityType, FilterState, RelationshipType } from '../types'
import {
  CONFIDENCE_COLOR,
  CONFIDENCE_LABEL,
  CONFIDENCE_ORDER,
  ENTITY_LABEL,
  ENTITY_TYPES,
  RELATIONSHIP_LABEL,
  RELATIONSHIP_TYPES,
} from '../lib/display'

interface Props {
  filters: FilterState
  counts: {
    byEntityType: Record<string, number>
    byRelationshipType: Record<string, number>
    byConfidence: Record<string, number>
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

/** Filter panel: the graph updates as soon as anything here changes. */
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
        <div className="panel-title mb-1">Confidence</div>
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
      </section>

      <section>
        <div className="panel-title mb-1">Relationship</div>
        {RELATIONSHIP_TYPES.filter(
          (type) => (counts.byRelationshipType[type] ?? 0) > 0,
        ).map((type: RelationshipType) => (
          <Row
            key={type}
            label={RELATIONSHIP_LABEL[type]}
            checked={filters.relationshipTypes.has(type)}
            count={counts.byRelationshipType[type]}
            onToggle={() =>
              onChange({
                ...filters,
                relationshipTypes: toggle(filters.relationshipTypes, type),
              })
            }
          />
        ))}
      </section>

      <section className="space-y-2 border-t border-line pt-3">
        <label className="flex items-center justify-between gap-2 text-[12px] text-dim">
          <span>Minimum score</span>
          <span className="font-mono text-[11px] text-accent">{filters.minScore}</span>
        </label>
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={filters.minScore}
          onChange={(event) =>
            onChange({ ...filters, minScore: Number(event.target.value) })
          }
          className="w-full accent-[var(--color-accent)]"
        />
        <Row
          label="Hide rejected relationships"
          checked={filters.hideRejected}
          onToggle={() => onChange({ ...filters, hideRejected: !filters.hideRejected })}
        />
      </section>
    </div>
  )
}
