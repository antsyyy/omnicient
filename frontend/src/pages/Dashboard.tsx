import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import SearchBar from '../components/SearchBar'
import type { Health, Investigation } from '../types'
import { formatDay } from '../lib/display'

const STATUS_TONE: Record<string, string> = {
  COMPLETED: 'text-confirmed',
  FAILED: 'text-rejected',
  CRAWLING: 'text-accent',
  ANALYZING: 'text-accent',
  CREATED: 'text-faint',
}

/** Case list and investigation creation. */
export default function Dashboard() {
  const navigate = useNavigate()
  const [health, setHealth] = useState<Health | null>(null)
  const [investigations, setInvestigations] = useState<Investigation[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    const [status, cases] = await Promise.all([
      api.health(),
      api.listInvestigations(),
    ])
    setHealth(status)
    setInvestigations(cases)
  }, [])

  useEffect(() => {
    refresh().catch((cause: Error) => setError(cause.message))
  }, [refresh])

  async function start(input: { identifier: string; platform: string; demo: boolean }) {
    setBusy(true)
    setError(null)
    try {
      const created = await api.createInvestigation({ ...input, auto_crawl: true })
      navigate(`/investigations/${created.id}`)
    } catch (cause) {
      setError((cause as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function remove(id: string) {
    await api.deleteInvestigation(id)
    await refresh()
  }

  return (
    <div className="mx-auto flex h-full max-w-6xl flex-col gap-6 overflow-y-auto px-6 py-8">
      <header className="flex items-end justify-between gap-6 border-b border-line pb-5">
        <div>
          <h1 className="font-mono text-[26px] font-semibold tracking-[0.28em] text-accent">
            OMNICIENT
          </h1>
          <p className="mt-1 text-[13px] text-dim">
            Trace public identities. Follow the evidence.
          </p>
        </div>
        <div className="text-right font-mono text-[11px] text-faint">
          <div>v{health?.version ?? '—'}</div>
          <div>
            mode:{' '}
            <span className={health?.demo_mode ? 'text-demo' : 'text-band-medium'}>
              {health ? (health.demo_mode ? 'DEMO' : 'LIVE') : '—'}
            </span>
          </div>
          <div>sources: {health?.sources.join(', ') ?? '—'}</div>
        </div>
      </header>

      <section className="rounded border border-line bg-panel p-4">
        <h2 className="panel-title mb-3">New investigation</h2>
        <SearchBar health={health} busy={busy} onStart={start} />
        {error && <p className="mt-3 text-[12px] text-rejected">{error}</p>}
      </section>

      <section className="rounded border border-line bg-panel">
        <h2 className="panel-title border-b border-line px-4 py-2">
          Recent investigations · {investigations.length}
        </h2>

        {investigations.length === 0 ? (
          <p className="px-4 py-6 text-[13px] text-faint">
            No investigations yet. Start one above — demo mode needs no network
            access.
          </p>
        ) : (
          <table className="w-full text-left text-[12px]">
            <thead>
              <tr className="border-b border-line text-faint">
                <th className="px-4 py-2 font-normal">Name</th>
                <th className="px-2 py-2 font-normal">Seed</th>
                <th className="px-2 py-2 text-right font-normal">Entities</th>
                <th className="px-2 py-2 text-right font-normal">Evidence</th>
                <th className="px-2 py-2 font-normal">Status</th>
                <th className="px-2 py-2 font-normal">Date</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {investigations.map((investigation) => (
                <tr
                  key={investigation.id}
                  className="border-b border-line/60 last:border-b-0 hover:bg-raised"
                >
                  <td className="px-4 py-2">
                    <Link
                      to={`/investigations/${investigation.id}`}
                      className="text-ink hover:text-accent"
                    >
                      {investigation.name}
                    </Link>
                    {investigation.demo && (
                      <span className="ml-2 rounded border border-demo/40 px-1 font-mono text-[9px] tracking-wider text-demo">
                        DEMO
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-2 font-mono text-dim">
                    {investigation.seed_platform}/@{investigation.seed_identifier}
                  </td>
                  <td className="px-2 py-2 text-right font-mono text-dim">
                    {investigation.entity_count}
                  </td>
                  <td className="px-2 py-2 text-right font-mono text-dim">
                    {investigation.evidence_count}
                  </td>
                  <td
                    className={`px-2 py-2 font-mono text-[11px] ${
                      STATUS_TONE[investigation.status] ?? 'text-faint'
                    }`}
                  >
                    {investigation.status}
                  </td>
                  <td className="px-2 py-2 font-mono text-faint">
                    {formatDay(investigation.created_at)}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => void remove(investigation.id)}
                      className="font-mono text-[11px] text-faint hover:text-rejected"
                      title="Delete investigation"
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <footer className="border-t border-line pt-4 text-[11px] leading-snug text-faint">
        Omnicient reports <span className="text-dim">potential associations</span>{' '}
        supported by publicly observable evidence. It never claims that two
        accounts belong to the same person. For authorized OSINT, cybersecurity
        research, academic research, threat intelligence, defensive
        investigations and digital footprint analysis only.
      </footer>
    </div>
  )
}
