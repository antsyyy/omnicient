/**
 * The results list: one row per source, including the sources that yielded
 * nothing.
 *
 * A graph can only draw what exists. The sources that came back empty and the
 * sources that refused to answer leave no node behind, so on the canvas they
 * are identically invisible — yet they are different findings, and this is
 * where an analyst reads that difference.
 *
 * Every row that claims an account has to justify it in the same breath: the
 * confidence band, the score, how many pieces of evidence stand behind it and
 * whether any of them contradict. A row never asserts an identity; it reports
 * a potential association and offers the evidence.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import PlatformLogo from './PlatformLogo'
import type { SourceOutcome, SourceResult, SourceResults } from '../types'
import {
  CATEGORY_LABEL,
  CONFIDENCE_COLOR,
  CONFIDENCE_LABEL,
  OUTCOME_COLOR,
  OUTCOME_HEADING,
  OUTCOME_NOTE,
  OUTCOME_ORDER,
  REASON_LABEL,
  STATUS_COLOR,
} from '../lib/display'

interface Props {
  investigationId: string
  revision: number
  selectedEntityId: string | null
  onSelectEntity: (entityId: string) => void
  onSelectRelationship: (relationshipId: string) => void
  /** Called after a verdict, so the graph and analysis panels stay in step. */
  onUpdated: () => void
}

/** Sections an analyst has usually finished with, collapsed by default. */
const COLLAPSED_BY_DEFAULT: SourceOutcome[] = ['NOT_FOUND', 'NOT_QUERIED']

function Chip({ color, children }: { color: string; children: React.ReactNode }) {
  return (
    <span
      className="rounded border px-1 font-mono text-[9px] tracking-wider"
      style={{ color, borderColor: color }}
    >
      {children}
    </span>
  )
}

/**
 * One source, and what it yielded.
 *
 * Found rows carry their evidence and the verdict controls; the rest state
 * plainly what happened and why, which is the whole reason they are listed.
 */
function ResultRow({
  result,
  selected,
  busy,
  onSelectEntity,
  onSelectRelationship,
  onVerdict,
}: {
  result: SourceResult
  selected: boolean
  busy: boolean
  onSelectEntity: (id: string) => void
  onSelectRelationship: (id: string) => void
  onVerdict: (relationshipId: string, verdict: 'confirm' | 'reject' | 'reset') => void
}) {
  const found = result.outcome === 'FOUND'
  const confidence = result.confidence

  return (
    <li
      className="border-b border-line px-3 py-2 last:border-b-0"
      style={selected ? { background: 'var(--color-raised)' } : undefined}
    >
      <div className="flex items-center gap-2">
        {/*
          The mark takes the outcome's colour rather than the brand's. A row
          that found nothing should read as muted at a glance, and a wall of
          brand palette would make every source look equally alive.
        */}
        <PlatformLogo
          platform={result.platform}
          entityType={result.entity?.type}
          size={15}
          title={result.platform_name}
          style={{
            color: OUTCOME_COLOR[result.outcome],
            opacity: found ? 1 : 0.55,
          }}
        />

        <span
          className={`shrink-0 text-[12px] ${found ? 'text-ink' : 'text-dim'}`}
        >
          {result.platform_name}
        </span>

        {result.identifier && (
          <button
            onClick={() => result.entity && onSelectEntity(result.entity.id)}
            disabled={!result.entity}
            className="min-w-0 truncate font-mono text-[11px] text-accent hover:underline disabled:cursor-default disabled:no-underline"
            title={result.display_name ?? result.identifier}
          >
            {result.identifier}
          </button>
        )}

        <span className="ml-auto shrink-0 font-mono text-[9px] uppercase tracking-wide text-faint">
          {CATEGORY_LABEL[result.category] ?? result.category}
        </span>

        {confidence && (
          <Chip color={CONFIDENCE_COLOR[confidence]}>
            {CONFIDENCE_LABEL[confidence]}
            {result.score !== null && ` ${Math.round(result.score)}`}
          </Chip>
        )}
      </div>

      {/*
        The justification line. A confidence with nothing behind it is a
        claim, so the evidence count sits next to the band that rests on it.
      */}
      {result.actionable && (
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 pl-4 font-mono text-[10px] text-faint">
          <span>
            {result.evidence_count}{' '}
            {result.evidence_count === 1 ? 'item of evidence' : 'items of evidence'}
          </span>
          {result.contradiction_count > 0 && (
            <span style={{ color: 'var(--color-contradiction)' }}>
              {result.contradiction_count} contradicting
            </span>
          )}
          {result.analyst_status && result.analyst_status !== 'UNREVIEWED' && (
            <span style={{ color: STATUS_COLOR[result.analyst_status] }}>
              {result.analyst_status.toLowerCase()} by analyst
            </span>
          )}
          {result.display_name && (
            <span className="text-dim">{result.display_name}</span>
          )}
        </div>
      )}

      {/* Why a source gave nothing back — the point of listing it at all. */}
      {result.reason && (
        <div className="mt-0.5 pl-4 text-[11px] leading-snug text-faint">
          {REASON_LABEL[result.reason] ?? result.detail ?? result.reason}
        </div>
      )}

      {result.actionable && (
        <div className="mt-1 flex flex-wrap items-center gap-1.5 pl-4">
          <button
            onClick={() => onSelectRelationship(result.relationship_id!)}
            className="rounded border border-line px-1.5 py-0.5 font-mono text-[10px] text-dim hover:border-accent hover:text-accent"
          >
            view evidence
          </button>
          {result.analyst_status === 'UNREVIEWED' ? (
            <>
              <button
                disabled={busy}
                onClick={() => onVerdict(result.relationship_id!, 'confirm')}
                className="rounded border border-line px-1.5 py-0.5 font-mono text-[10px] text-dim hover:border-confirmed hover:text-confirmed disabled:opacity-40"
                title="Record that you judge this association to hold"
              >
                confirm
              </button>
              <button
                disabled={busy}
                onClick={() => onVerdict(result.relationship_id!, 'reject')}
                className="rounded border border-line px-1.5 py-0.5 font-mono text-[10px] text-dim hover:border-rejected hover:text-rejected disabled:opacity-40"
                title="Record that you judge this association not to hold"
              >
                reject
              </button>
            </>
          ) : (
            <button
              disabled={busy}
              onClick={() => onVerdict(result.relationship_id!, 'reset')}
              className="rounded border border-line px-1.5 py-0.5 font-mono text-[10px] text-faint hover:border-line-bright hover:text-dim disabled:opacity-40"
            >
              clear verdict
            </button>
          )}
          {result.url && (
            <a
              href={result.url}
              target="_blank"
              rel="noreferrer noopener"
              className="font-mono text-[10px] text-faint hover:text-accent"
              title="Open the public page this was read from"
            >
              open ↗
            </a>
          )}
        </div>
      )}
    </li>
  )
}

export default function ResultsList({
  investigationId,
  revision,
  selectedEntityId,
  onSelectEntity,
  onSelectRelationship,
  onUpdated,
}: Props) {
  const [data, setData] = useState<SourceResults | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [category, setCategory] = useState<string>('all')
  const [collapsed, setCollapsed] = useState<Set<SourceOutcome>>(
    () => new Set(COLLAPSED_BY_DEFAULT),
  )

  const load = useCallback(async () => {
    try {
      setData(await api.getResults(investigationId))
    } catch (cause) {
      setError((cause as Error).message)
    }
  }, [investigationId])

  useEffect(() => {
    void load()
  }, [load, revision])

  const verdict = useCallback(
    async (relationshipId: string, choice: 'confirm' | 'reject' | 'reset') => {
      setBusy(true)
      try {
        if (choice === 'confirm') await api.confirmRelationship(relationshipId)
        else if (choice === 'reject') await api.rejectRelationship(relationshipId)
        else await api.resetRelationship(relationshipId)
        await load()
        onUpdated()
      } catch (cause) {
        setError((cause as Error).message)
      } finally {
        setBusy(false)
      }
    },
    [load, onUpdated],
  )

  const categories = useMemo(() => {
    const seen = new Map<string, number>()
    for (const row of data?.results ?? []) {
      seen.set(row.category, (seen.get(row.category) ?? 0) + 1)
    }
    return [...seen.entries()].sort((a, b) => b[1] - a[1])
  }, [data])

  const grouped = useMemo(() => {
    const rows = (data?.results ?? []).filter(
      (row) => category === 'all' || row.category === category,
    )
    return OUTCOME_ORDER.map((outcome) => ({
      outcome,
      rows: rows.filter((row) => row.outcome === outcome),
    })).filter((group) => group.rows.length > 0)
  }, [data, category])

  if (error) {
    return (
      <div className="p-4 font-mono text-[12px] text-rejected">{error}</div>
    )
  }

  if (!data) {
    return (
      <div className="p-4 text-[12px] text-faint">Reading source results…</div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="shrink-0 border-b border-line px-4 py-2.5">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="font-mono text-[13px] text-ink">
            {data.seed_identifier}
          </span>
          <span className="font-mono text-[10px] uppercase tracking-wide text-faint">
            {data.seed_type}
          </span>
          <span className="text-[12px] text-dim">
            <span style={{ color: 'var(--color-confirmed)' }}>{data.found}</span>{' '}
            found across {data.queried}{' '}
            {data.queried === 1 ? 'source' : 'sources'} searched
          </span>
        </div>
        {/*
          The standing caveat. The list is a set of potential associations, and
          the interface should say so where the counts are read, not only in
          the detail panels.
        */}
        <p className="mt-1 text-[11px] leading-snug text-faint">
          Potential associations, ranked by the evidence behind them. Nothing
          here asserts that one person owns these accounts.
        </p>

        {categories.length > 1 && (
          <div className="mt-2 flex flex-wrap gap-1">
            <button
              onClick={() => setCategory('all')}
              className="rounded border px-1.5 py-0.5 font-mono text-[10px]"
              style={{
                color:
                  category === 'all' ? 'var(--color-accent)' : 'var(--color-dim)',
                borderColor:
                  category === 'all' ? 'var(--color-accent)' : 'var(--color-line)',
              }}
            >
              all {data.results.length}
            </button>
            {categories.map(([name, count]) => (
              <button
                key={name}
                onClick={() => setCategory(name)}
                className="rounded border px-1.5 py-0.5 font-mono text-[10px]"
                style={{
                  color:
                    category === name ? 'var(--color-accent)' : 'var(--color-dim)',
                  borderColor:
                    category === name ? 'var(--color-accent)' : 'var(--color-line)',
                }}
              >
                {CATEGORY_LABEL[name] ?? name} {count}
              </button>
            ))}
          </div>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {grouped.length === 0 && (
          <div className="p-4 text-[12px] text-faint">
            No sources in this category.
          </div>
        )}

        {grouped.map(({ outcome, rows }) => {
          const shut = collapsed.has(outcome)
          return (
            <section key={outcome}>
              <button
                onClick={() =>
                  setCollapsed((current) => {
                    const next = new Set(current)
                    if (next.has(outcome)) next.delete(outcome)
                    else next.add(outcome)
                    return next
                  })
                }
                className="flex w-full items-center gap-2 border-b border-line bg-raised/60 px-3 py-1.5 text-left hover:bg-raised"
              >
                <span
                  className="font-mono text-[9px] text-faint"
                  aria-hidden
                >
                  {shut ? '▸' : '▾'}
                </span>
                <span
                  className="font-mono text-[10px] uppercase tracking-[0.14em]"
                  style={{ color: OUTCOME_COLOR[outcome] }}
                >
                  {OUTCOME_HEADING[outcome]}
                </span>
                <span className="font-mono text-[10px] text-faint">
                  {rows.length}
                </span>
              </button>

              {!shut && (
                <>
                  <p className="border-b border-line px-3 py-1.5 text-[11px] leading-snug text-faint">
                    {OUTCOME_NOTE[outcome]}
                  </p>
                  <ul>
                    {rows.map((row) => (
                      <ResultRow
                        key={`${row.platform}:${row.identifier ?? row.outcome}`}
                        result={row}
                        selected={
                          row.entity !== null &&
                          row.entity.id === selectedEntityId
                        }
                        busy={busy}
                        onSelectEntity={onSelectEntity}
                        onSelectRelationship={onSelectRelationship}
                        onVerdict={verdict}
                      />
                    ))}
                  </ul>
                </>
              )}
            </section>
          )
        })}
      </div>
    </div>
  )
}
