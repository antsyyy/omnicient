import { useState } from 'react'
import type { NewInvestigationInput } from '../types'

interface Props {
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
 * Whether an investigation runs against live sources or the offline demo
 * dataset is a deployment setting (OMNICIENT_DEMO_MODE), not a per-search
 * choice, so there is no control for it here. The request omits the flag and
 * the server applies its own.
 */
export default function SearchBar({ busy, onStart }: Props) {
  const [identifier, setIdentifier] = useState('')
  const [name, setName] = useState('')
  const [touched, setTouched] = useState(false)

  function submit(event: React.FormEvent) {
    event.preventDefault()
    setTouched(true)
    const value = identifier.trim()
    if (!value) return
    onStart({
      identifier: value,
      name: name.trim() || undefined,
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

      {touched && !identifier.trim() && (
        <p className="text-[12px] text-rejected">
          Enter a username, email address, profile URL or domain.
        </p>
      )}
    </form>
  )
}
