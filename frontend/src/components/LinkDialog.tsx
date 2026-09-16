/**
 * Asks why, before a link is drawn.
 *
 * An analyst-drawn link is the one association in Omnicient with no
 * observation behind it — the reason given here *is* its provenance, which is
 * why the dialog will not submit without one. An investigation that cannot
 * say why a connection was drawn is not one anybody should have to trust.
 *
 * The wording throughout stays in the project's register: the analyst is
 * recording a potential association they judge to hold, not declaring an
 * identity.
 */

import { useEffect, useMemo, useState } from 'react'
import type { GraphNode, RelationshipType } from '../types'
import { ANALYST_LINKABLE_TYPES } from '../types'
import { RELATIONSHIP_LABEL } from '../lib/display'
import PlatformLogo from './PlatformLogo'

interface Props {
  source: GraphNode
  target: GraphNode
  busy: boolean
  error: string | null
  onCancel: () => void
  onSubmit: (type: RelationshipType, rationale: string) => void
}

/** What each drawable type claims, in the analyst's own terms. */
const TYPE_NOTE: Record<string, string> = {
  POTENTIAL_SAME_IDENTITY:
    'You judge these two accounts to plausibly belong to the same person. This records your judgement, not a proven identity.',
  POTENTIAL_ALIAS:
    'You judge one handle to be a naming variant of the other. A claim about the handles, not about the people behind them.',
  LINKS_TO: 'One of these publicly points at the other.',
  REFERENCES: 'One of these mentions the other without linking to it.',
}

function Endpoint({ node, role }: { node: GraphNode; role: string }) {
  return (
    <div className="min-w-0 flex-1 rounded border border-line bg-raised px-2 py-1.5">
      <div className="panel-title">{role}</div>
      <div className="mt-0.5 flex items-center gap-1.5">
        <PlatformLogo
          platform={node.platform}
          entityType={node.type}
          size={13}
          className="text-dim"
        />
        <span className="truncate font-mono text-[12px] text-ink" title={node.label}>
          {node.label}
        </span>
      </div>
      <div className="truncate text-[10px] text-faint">{node.platform_name}</div>
    </div>
  )
}

export default function LinkDialog({
  source,
  target,
  busy,
  error,
  onCancel,
  onSubmit,
}: Props) {
  const [type, setType] = useState<RelationshipType>('POTENTIAL_SAME_IDENTITY')
  const [rationale, setRationale] = useState('')

  // Escape is the expected way out of a modal.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])

  const ready = useMemo(() => rationale.trim().length >= 3, [rationale])

  return (
    <div
      className="absolute inset-0 z-30 flex items-center justify-center bg-void/80 backdrop-blur-[2px]"
      onClick={onCancel}
    >
      <div
        className="w-[440px] max-w-[92vw] rounded-lg border border-line bg-panel p-4 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Draw a link"
      >
        <div className="panel-title" style={{ color: 'var(--color-asserted)' }}>
          Draw a link
        </div>
        <p className="mt-1 text-[11px] leading-snug text-dim">
          This link will be recorded as{' '}
          <span style={{ color: 'var(--color-asserted)' }}>asserted by you</span>,
          kept separate from what the engine observed, and carries no
          confidence score — because nothing was observed to score.
        </p>

        <div className="mt-3 flex items-stretch gap-2">
          <Endpoint node={source} role="From" />
          <div className="self-center font-mono text-[14px] text-faint">→</div>
          <Endpoint node={target} role="To" />
        </div>

        <label className="mt-3 block">
          <span className="panel-title">Relationship</span>
          <select
            value={type}
            onChange={(event) => setType(event.target.value as RelationshipType)}
            className="mt-1 w-full rounded border border-line bg-raised px-2 py-1.5 font-mono text-[12px] text-ink outline-none focus:border-accent"
          >
            {ANALYST_LINKABLE_TYPES.map((value) => (
              <option key={value} value={value}>
                {RELATIONSHIP_LABEL[value]}
              </option>
            ))}
          </select>
        </label>
        <p className="mt-1 text-[11px] leading-snug text-faint">{TYPE_NOTE[type]}</p>

        <label className="mt-3 block">
          <span className="panel-title">
            Why — required, and stored with the link
          </span>
          <textarea
            value={rationale}
            onChange={(event) => setRationale(event.target.value)}
            rows={3}
            autoFocus
            placeholder="e.g. Both handles appear on an archived page the crawler could not reach."
            className="mt-1 w-full resize-none rounded border border-line bg-raised px-2 py-1.5 text-[12px] text-ink outline-none placeholder:text-faint focus:border-accent"
          />
        </label>
        <p className="mt-1 text-[11px] leading-snug text-faint">
          Whoever reads this investigation later will see this reason in place
          of evidence. Write what you would want to read.
        </p>

        {error && (
          <div className="mt-2 rounded border border-rejected/50 bg-rejected/10 px-2 py-1.5 text-[11px] leading-snug text-rejected">
            {error}
          </div>
        )}

        <div className="mt-3 flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded border border-line px-2.5 py-1 text-[12px] text-dim hover:border-line-bright hover:text-ink"
          >
            Cancel
          </button>
          <button
            disabled={!ready || busy}
            onClick={() => onSubmit(type, rationale.trim())}
            className="rounded border px-2.5 py-1 text-[12px] font-medium disabled:opacity-40"
            style={{
              borderColor: 'var(--color-asserted)',
              color: 'var(--color-asserted)',
            }}
            title={ready ? undefined : 'A reason is required'}
          >
            {busy ? 'Drawing…' : 'Draw link'}
          </button>
        </div>
      </div>
    </div>
  )
}
