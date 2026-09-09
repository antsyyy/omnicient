import { useState } from 'react'
import type { Health, NewInvestigationInput } from '../types'

interface Props {
  health: Health | null
  busy: boolean
  onStart: (input: NewInvestigationInput) => void
}

/**
 * Investigation creation.
 *
 * One input, no platform picker.  The analyst types a username, an email
 * address, a profile URL or a domain, and the backend works out which it is
 * and which sources to ask.  Offering a platform dropdown here would push a
 * decision onto the analyst that the tool is meant to make for them.
 *
 * Demo mode is the default the server reports; switching it off is an explicit
 * act, because it means querying live public sources.
 */
export default function SearchBar({ health, busy, onStart }: Props) {
  const [identifier, setIdentifier] = useState('')
  const [name, setName] = useState('')
  const [demo, setDemo] = useState(true)
  const [touched, setTouched] = useState(false)

  const demoSeed = health?.demo_seed
  const effectiveDemo = health ? demo : true

  function submit(event: React.FormEvent) {
    event.preventDefault()
    setTouched(true)
    const value = identifier.trim()
    if (!value) return
    onStart({
      identifier: value,
      demo: effectiveDemo,
      name: name.trim() || undefined,
    })
  }

  /** Section 30: one click to a fully populated, offline investigation. */
  function launchDemo() {
    const seed = demoSeed?.identifier ?? 'alice_98'
    setIdentifier(`@${seed}`)
    setDemo(true)
    onStart({
      identifier: seed,
      demo: true,
      name: `DEMO investigation · @${seed}`,
    })
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="min-w-[300px] flex-[2]">
          <span className="panel-title">Username, email, profile URL, or domain</span>
          <input
            value={identifier}
            onChange={(event) => setIdentifier(event.target.value)}
            placeholder="alice_98"
            spellCheck={false}
            autoComplete="off"
            className="mt-1 w-full rounded border border-line bg-void px-3 py-2 font-mono text-[13px] text-ink outline-none focus:border-accent"
          />
        </label>

        <label className="min-w-[180px] flex-1">
          <span className="panel-title">Investigation name (optional)</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Alice Investigation"
            className="mt-1 w-full rounded border border-line bg-void px-3 py-2 text-[13px] text-ink outline-none focus:border-accent"
          />
        </label>

        <button
          type="submit"
          disabled={busy}
          className="rounded border border-accent/60 bg-accent/15 px-4 py-2 text-[13px] font-medium text-accent hover:bg-accent/25 disabled:opacity-50"
        >
          {busy ? 'Starting…' : 'Investigate'}
        </button>
      </div>

      <p className="text-[11px] leading-snug text-faint">
        No platform to choose. Omnicient detects what you typed — a handle, an
        address, a link or a domain — and asks every source that can answer for
        it.
      </p>

      <div className="flex flex-wrap items-center gap-4">
        <button
          type="button"
          onClick={launchDemo}
          disabled={busy}
          className="rounded border border-demo/50 bg-demo/10 px-3 py-1.5 font-mono text-[12px] tracking-wide text-demo hover:bg-demo/20 disabled:opacity-50"
        >
          ▶ Launch demo investigation
        </button>

        <label className="flex items-center gap-2 text-[12px] text-dim">
          <input
            type="checkbox"
            checked={effectiveDemo}
            onChange={(event) => setDemo(event.target.checked)}
            className="h-3 w-3 accent-[var(--color-accent)]"
          />
          Demo mode (offline synthetic dataset)
        </label>

        {!effectiveDemo && (
          <span className="text-[11px] text-band-medium">
            Live mode queries public pages only. Platforms that require a login
            will be reported as unavailable.
          </span>
        )}
      </div>

      {touched && !identifier.trim() && (
        <p className="text-[12px] text-rejected">
          Enter a username, email address, profile URL or domain.
        </p>
      )}
    </form>
  )
}
