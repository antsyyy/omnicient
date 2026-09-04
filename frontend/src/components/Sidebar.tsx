import type { FilterState, InvestigationDetail, InvestigationGraph } from '../types'
import Filters from './Filters'
import { formatTime } from '../lib/display'

interface Props {
  investigation: InvestigationDetail
  graph: InvestigationGraph | null
  filters: FilterState
  onFiltersChange: (next: FilterState) => void
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

/** Left rail: what this investigation found, what to show, and what happened. */
export default function Sidebar({
  investigation,
  graph,
  filters,
  onFiltersChange,
}: Props) {
  const stats = graph?.stats
  const events = investigation.events.slice(-40).reverse()

  return (
    <aside className="flex w-[280px] shrink-0 flex-col overflow-y-auto border-r border-line bg-panel">
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

      {investigation.issues.length > 0 && (
        <section className="border-b border-line px-3 py-3">
          <div className="panel-title mb-1">Sources unavailable</div>
          <ul className="space-y-2">
            {investigation.issues.map((issue, index) => (
              <li
                key={`${issue.platform}-${index}`}
                className="rounded border border-band-medium/40 bg-band-medium/5 px-2 py-1"
              >
                <div className="font-mono text-[11px] text-band-medium">
                  {issue.platform}
                  {issue.identifier ? `/@${issue.identifier}` : ''} · {issue.reason}
                </div>
                <p className="mt-0.5 text-[11px] leading-snug text-faint">
                  {issue.detail}
                </p>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] leading-snug text-faint">
            The investigation continues using the evidence already discovered.
          </p>
        </section>
      )}

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

      <section className="px-3 py-3">
        <div className="panel-title mb-1">Activity</div>
        <ul className="space-y-1">
          {events.map((event) => (
            <li key={event.id} className="flex gap-2 text-[11px] leading-snug">
              <span className="shrink-0 font-mono text-faint">
                {formatTime(event.timestamp)}
              </span>
              <span
                className={
                  event.level === 'WARNING'
                    ? 'text-band-medium'
                    : event.level === 'ERROR'
                      ? 'text-rejected'
                      : 'text-dim'
                }
              >
                {event.message}
              </span>
            </li>
          ))}
          {events.length === 0 && (
            <li className="text-[11px] text-faint">No activity recorded yet.</li>
          )}
        </ul>
      </section>
    </aside>
  )
}
