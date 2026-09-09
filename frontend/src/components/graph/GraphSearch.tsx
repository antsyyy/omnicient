import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'

interface Props {
  value: string
  matchCount: number
  onChange: (value: string) => void
  onSubmit: () => void
  onClose: () => void
}

/**
 * Search across everything the investigation discovered.
 *
 * Matches are highlighted in place and the rest of the board is dimmed rather
 * than filtered away, so a match is always seen in its context — which is the
 * whole reason to search a graph rather than a list.
 */
export default function GraphSearch({
  value,
  matchCount,
  onChange,
  onSubmit,
  onClose,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  return (
    <div
      className="absolute left-1/2 top-3 z-20 flex w-[340px] -translate-x-1/2 items-center gap-2 rounded-lg border border-line px-2.5 py-1.5"
      style={{
        background: 'rgba(12,17,24,0.94)',
        backdropFilter: 'blur(8px)',
        boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
      }}
    >
      <input
        ref={inputRef}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') onSubmit()
          if (event.key === 'Escape') onClose()
        }}
        placeholder="Search entities, handles, domains…"
        className="min-w-0 flex-1 bg-transparent font-mono text-[12px] text-ink outline-none placeholder:text-faint"
        spellCheck={false}
      />
      {value && (
        <span className="shrink-0 font-mono text-[10px] text-faint">
          {matchCount} match{matchCount === 1 ? '' : 'es'}
        </span>
      )}
      <button
        onClick={onClose}
        aria-label="Close search"
        className="shrink-0 text-faint transition-colors hover:text-ink"
      >
        <X size={13} />
      </button>
    </div>
  )
}
