import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Lead, LeadList, PathHighlight } from '../types'

interface Props {
  investigationId: string
  onSelectEntity: (entityId: string) => void
  onSelectRelationship: (relationshipId: string) => void
  onHighlight: (highlight: PathHighlight | null) => void
  revision: number
}

const PRIORITY_COLOR: Record<string, string> = {
  HIGH: 'var(--color-contradiction)',
  MEDIUM: 'var(--color-band-medium)',
  LOW: 'var(--color-dim)',
}

function LeadCard({
  lead,
  active,
  onSelectEntity,
  onSelectRelationship,
  onHighlight,
}: {
  lead: Lead
  active: boolean
  onSelectEntity: (id: string) => void
  onSelectRelationship: (id: string) => void
  onHighlight: (highlight: PathHighlight | null) => void
}) {
  const color = PRIORITY_COLOR[lead.priority] ?? PRIORITY_COLOR.LOW

  return (
    <li
      className="border-b border-line px-3 py-2.5 last:border-b-0"
      style={active ? { background: 'var(--color-raised)' } : undefined}
    >
      <div className="flex items-center gap-2">
        <span
          className="rounded border px-1 font-mono text-[9px] tracking-wider"
          style={{ color, borderColor: color }}
        >
          {lead.priority}
        </span>
        <span className="font-mono text-[9px] uppercase tracking-wide text-faint">
          {lead.label}
        </span>
      </div>

      <h4 className="mt-1 text-[12px] font-medium text-ink">{lead.title}</h4>
      <p className="mt-0.5 text-[11px] leading-snug text-dim">{lead.description}</p>
      <p className="mt-1 border-l border-line pl-2 text-[11px] leading-snug text-faint">
        {lead.suggested_action}
      </p>

      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        <button
          onClick={() =>
            onHighlight(
              active
                ? null
                : {
                    nodeIds: new Set(lead.related_entity_ids),
                    edgeIds: new Set(lead.related_relationship_ids),
                  },
            )
          }
          className="rounded border border-line px-1.5 py-0.5 font-mono text-[10px] text-dim hover:border-accent hover:text-accent"
        >
          {active ? 'clear highlight' : 'highlight graph'}
        </button>
        {lead.related_relationship_ids[0] && (
          <button
            onClick={() => onSelectRelationship(lead.related_relationship_ids[0])}
            className="rounded border border-line px-1.5 py-0.5 font-mono text-[10px] text-dim hover:border-accent hover:text-accent"
          >
            view evidence
          </button>
        )}
        {lead.related_entities.slice(0, 3).map((entity) => (
          <button
            key={entity.id}
            onClick={() => onSelectEntity(entity.id)}
            className="font-mono text-[10px] text-accent hover:underline"
            title={`${entity.platform_name} ${entity.name}`}
          >
            {entity.name}
          </button>
        ))}
        {lead.entity_count > 3 && (
          <span className="font-mono text-[10px] text-faint">
            +{lead.entity_count - 3}
          </span>
        )}
      </div>
    </li>
  )
}

/**
 * Investigation leads: what is worth looking at next.
 *
 * Every card is a suggestion derived from evidence already collected, never an
 * autonomous conclusion — and nothing here starts a new external search. The
 * analyst decides what to pursue.
 */
export default function LeadsPanel({
  investigationId,
  onSelectEntity,
  onSelectRelationship,
  onHighlight,
  revision,
}: Props) {
  const [data, setData] = useState<LeadList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [activeId, setActiveId] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    api
      .getLeads(investigationId)
      .then((result) => active && setData(result))
      .catch((cause: Error) => active && setError(cause.message))
    return () => {
      active = false
    }
  }, [investigationId, revision])

  if (error) return <p className="p-3 text-[12px] text-rejected">{error}</p>
  if (!data) return <p className="p-3 text-[12px] text-faint">Loading…</p>

  if (!data.leads.length) {
    return (
      <p className="p-3 text-[12px] leading-snug text-faint">
        No leads yet. Leads are derived from discovered evidence — run
        discovery, or expand the investigation, and they will appear here.
      </p>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="flex items-center gap-2 border-b border-line px-3 py-2">
        {(['HIGH', 'MEDIUM', 'LOW'] as const).map((priority) => (
          <span
            key={priority}
            className="font-mono text-[10px]"
            style={{ color: PRIORITY_COLOR[priority] }}
          >
            {data.by_priority[priority] ?? 0} {priority.toLowerCase()}
          </span>
        ))}
      </div>

      <ul>
        {data.leads.map((lead) => (
          <LeadCard
            key={lead.id}
            lead={lead}
            active={activeId === lead.id}
            onSelectEntity={onSelectEntity}
            onSelectRelationship={onSelectRelationship}
            onHighlight={(highlight) => {
              setActiveId(highlight ? lead.id : null)
              onHighlight(highlight)
            }}
          />
        ))}
      </ul>
    </div>
  )
}
