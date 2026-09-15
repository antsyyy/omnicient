import type { FilterState, InvestigationDetail, InvestigationGraph } from '../types'
import Filters from './Filters'

interface Props {
  investigation: InvestigationDetail
  graph: InvestigationGraph | null
  filters: FilterState
  onFiltersChange: (next: FilterState) => void
  /** Filters shape the graph; the results list has its own. */
  showFilters: boolean
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded border border-line bg-raised px-2 py-1.5">
      <div className="panel-title">{label}</div>
      <div
        className="font-mono text-[18px] leading-tight"
        style={{ color: tone ?? 'var(--color-ink)' }}
      >
        {value}
      </div>
    </div>
  )
}

/**
 * Left rail: what this investigation found, and what to show of it.
 *
 * Deliberately thin. It used to carry the full activity log and a list of
 * every source that declined, which between them filled the rail with several
 * hundred lines an analyst had to scroll past - and both said, less clearly,
 * what the results view already says per source and in context.
 */
export default function Sidebar({
  investigation,
  graph,
  filters,
  onFiltersChange,
  showFilters,
}: Props) {
  const stats = graph?.stats

  return (
    <aside className="flex w-[260px] shrink-0 flex-col overflow-y-auto border-r border-line bg-panel">
      <div className="flex flex-col">
      <section className="border-b border-line px-3 py-3">
        <div className="panel-title">Seed</div>
        <div className="mt-0.5 font-mono text-[13px] text-ink">
          @{investigation.seed_identifier}
        </div>
        <div className="font-mono text-[11px] text-faint">
          {investigation.seed_platform}
        </div>
      </section>

      <section className="grid grid-cols-2 gap-2 border-b border-line px-3 py-3">
        <Stat label="Entities" value={stats?.entities ?? investigation.entity_count} />
        <Stat
          label="Relationships"
          value={stats?.relationships ?? investigation.relationship_count}
        />
        <Stat label="Evidence" value={stats?.evidence ?? investigation.evidence_count} />
        <Stat
          label="Contradictions"
          value={stats?.contradictions ?? 0}
          tone="var(--color-contradiction)"
        />
      </section>

      {showFilters && (
      <section className="border-b border-line px-3 py-3">
        <div className="panel-title mb-2">Filters</div>
        <Filters
          filters={filters}
          counts={{
            byEntityType: stats?.by_entity_type ?? {},
            byRelationshipType: stats?.by_relationship_type ?? {},
            byConfidence: stats?.by_confidence ?? {},
          }}
          onChange={onFiltersChange}
        />
      </section>
      )}
      </div>

    </aside>
  )
}
