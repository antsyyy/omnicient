import { useState } from 'react'
import type { Health } from '../types'

interface Props {
  health: Health | null
  busy: boolean
  onStart: (input: { identifier: string; platform: string; demo: boolean }) => void
}

const PLATFORMS = [
  { value: 'instagram', label: 'Instagram' },
  { value: 'threads', label: 'Threads' },
  { value: 'facebook', label: 'Facebook' },
  { value: 'website', label: 'Website' },
]

/**
 * Investigation creation.
 *
 * Demo mode is the default the server reports; switching it off is an explicit
 * act, because it means querying live public sources.
 */
export default function SearchBar({ health, busy, onStart }: Props) {
  const [identifier, setIdentifier] = useState('')
  const [platform, setPlatform] = useState('instagram')
  const [demo, setDemo] = useState(true)
  const [touched, setTouched] = useState(false)

  const demoSeed = health?.demo_seed
  const effectiveDemo = health ? demo : true

  function submit(event: React.FormEvent) {
    event.preventDefault()
    setTouched(true)
    const value = identifier.trim()
    if (!value) return
    onStart({ identifier: value, platform, demo: effectiveDemo })
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="min-w-[260px] flex-1">
          <span className="panel-title">Identifier</span>
          <input
            value={identifier}
            onChange={(event) => setIdentifier(event.target.value)}
            placeholder="@alice_98 or https://instagram.com/alice_98"
            className="mt-1 w-full rounded border border-line bg-void px-3 py-2 font-mono text-[13px] text-ink outline-none focus:border-accent"
          />
        </label>

        <label>
          <span className="panel-title">Platform</span>
          <select
            value={platform}
            onChange={(event) => setPlatform(event.target.value)}
            className="mt-1 rounded border border-line bg-void px-3 py-2 text-[13px] text-ink outline-none focus:border-accent"
          >
            {PLATFORMS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <button
          type="submit"
          disabled={busy}
          className="rounded border border-accent/60 bg-accent/15 px-4 py-2 text-[13px] font-medium text-accent hover:bg-accent/25 disabled:opacity-50"
        >
          {busy ? 'Starting…' : 'Start investigation'}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-[12px] text-dim">
          <input
            type="checkbox"
            checked={effectiveDemo}
            onChange={(event) => setDemo(event.target.checked)}
            className="h-3 w-3 accent-[var(--color-accent)]"
          />
          Demo mode (offline synthetic dataset)
        </label>
        {demoSeed && effectiveDemo && (
          <button
            type="button"
            onClick={() => setIdentifier(`@${demoSeed.identifier}`)}
            className="font-mono text-[11px] text-accent hover:underline"
          >
            use demo seed @{demoSeed.identifier}
          </button>
        )}
        {!effectiveDemo && (
          <span className="text-[11px] text-band-medium">
            Live mode queries public pages only. Platforms that require a login
            will be reported as unavailable.
          </span>
        )}
      </div>

      {touched && !identifier.trim() && (
        <p className="text-[12px] text-rejected">Enter a username or profile URL.</p>
      )}
    </form>
  )
}
