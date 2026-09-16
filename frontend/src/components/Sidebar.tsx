import { useMemo } from 'react'
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

  /*
   * Counted from the nodes, not from the backend's relationship tallies.
   * The filter narrows entities, so the number beside each band has to be
   * the number of entities it would hide - the edge counts said "Low 127"
   * next to a control that removed nineteen things from the canvas.
   */
  const confidenceCounts = useMemo(() => {
    const byConfidence: Record<string, number> = {}
    let unassociated = 0
    let differentIdentity = 0
    for (const node of graph?.nodes ?? []) {
      if (node.analyst_verdict === 'DIFFERENT_IDENTITY') differentIdentity += 1
      if (node.confidence_level === null) unassociated += 1
      else byConfidence[node.confidence_level] =
        (byConfidence[node.confidence_level] ?? 0) + 1
    }
    return {
      byEntityType: stats?.by_entity_type ?? {},
      byConfidence,
      unassociated,
      differentIdentity,
    }
  }, [graph?.nodes, stats?.by_entity_type])

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
          counts={confidenceCounts}
          onChange={onFiltersChange}
        />
      </section>
      )}
      </div>

    </aside>
  )
}
