import { Link } from 'react-router-dom'
import type { InvestigationDetail } from '../types'
import { api } from '../api/client'
import { formatDate } from '../lib/display'

interface Props {
  investigation: InvestigationDetail
  onRecrawl: () => void
  onResetLayout: () => void
  busy: boolean
}

const STATUS_STYLE: Record<string, string> = {
  CREATED: 'text-faint border-line',
  CRAWLING: 'text-accent border-accent/60',
  ANALYZING: 'text-accent border-accent/60',
  COMPLETED: 'text-confirmed border-confirmed/50',
  FAILED: 'text-rejected border-rejected/60',
}

/** Top bar of the investigation workspace. */
export default function InvestigationHeader({
  investigation,
  onRecrawl,
  onResetLayout,
  busy,
}: Props) {
  const running = ['CREATED', 'CRAWLING', 'ANALYZING'].includes(investigation.status)

  return (
    <header className="flex items-center justify-between gap-4 border-b border-line bg-panel px-4 py-2">
      <div className="flex min-w-0 items-center gap-4">
        <Link to="/" className="font-mono text-[15px] font-semibold tracking-[0.2em] text-accent">
          OMNICIENT
        </Link>
        <div className="min-w-0">
          <div className="truncate text-[13px] text-ink">{investigation.name}</div>
          <div className="truncate font-mono text-[11px] text-faint">
            seed: {investigation.seed_platform}/@{investigation.seed_identifier} ·
            depth {investigation.max_depth} · created {formatDate(investigation.created_at)}
          </div>
        </div>
        {investigation.demo && (
          <span className="rounded border border-demo/50 bg-demo/10 px-2 py-0.5 font-mono text-[10px] tracking-wider text-demo">
            DEMO DATA
          </span>
        )}
        <span
          className={`rounded border px-2 py-0.5 font-mono text-[10px] tracking-wider ${
            STATUS_STYLE[investigation.status] ?? 'text-faint border-line'
          }`}
        >
          {running && <span className="mr-1 animate-pulse">●</span>}
          {investigation.status}
        </span>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <button
          onClick={onResetLayout}
          className="rounded border border-line px-2 py-1 text-[12px] text-dim hover:border-line-bright hover:text-ink"
        >
          Reset layout
        </button>
        <button
          onClick={onRecrawl}
          disabled={busy || running}
          className="rounded border border-line px-2 py-1 text-[12px] text-dim hover:border-line-bright hover:text-ink disabled:opacity-40"
        >
          {busy ? 'Crawling…' : 'Re-run discovery'}
        </button>
        <a
          href={api.exportUrl(investigation.id, 'json')}
          className="rounded border border-line px-2 py-1 text-[12px] text-dim hover:border-line-bright hover:text-ink"
          title="Full record: entities, relationships, evidence, snapshots, timeline"
        >
          Export JSON
        </a>
        <a
          href={api.exportUrl(investigation.id, 'csv')}
          className="rounded border border-line px-2 py-1 text-[12px] text-dim hover:border-line-bright hover:text-ink"
          title="One row per relationship, with its evidence"
        >
          Export CSV
        </a>
        <Link
          to="/"
          className="rounded border border-accent/60 bg-accent/10 px-2 py-1 text-[12px] font-medium text-accent hover:bg-accent/20"
        >
          New investigation
        </Link>
      </div>
    </header>
  )
}
