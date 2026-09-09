import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AnalystStatus, RelationshipDetail } from '../types'
import { CONFIDENCE_COLOR, CONFIDENCE_LABEL, STATUS_COLOR } from '../lib/display'
import EvidencePanel from './EvidencePanel'

interface Props {
  relationshipId: string
  onClose: () => void
  onUpdated: () => void
  onSelectEntity: (entityId: string) => void
}

/**
 * The relationship inspector.
 *
 * A relationship is never shown as a bare line between two nodes: the type,
 * the score, the band and every piece of evidence behind it are presented
 * together, and the analyst's verdict is recorded against that evidence.
 */
export default function RelationshipPanel({
  relationshipId,
  onClose,
  onUpdated,
  onSelectEntity,
}: Props) {
  const [detail, setDetail] = useState<RelationshipDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let active = true
    setDetail(null)
    setError(null)
    api
      .getRelationship(relationshipId)
      .then((value) => {
        if (!active) return
        setDetail(value)
        setNote(value.analyst_note ?? '')
      })
      .catch((cause: Error) => active && setError(cause.message))
    return () => {
      active = false
    }
  }, [relationshipId])

  async function decide(verdict: AnalystStatus) {
    setBusy(true)
    try {
      const updated =
        verdict === 'CONFIRMED'
          ? await api.confirmRelationship(relationshipId, note || undefined)
          : verdict === 'REJECTED'
            ? await api.rejectRelationship(relationshipId, note || undefined)
            : await api.resetRelationship(relationshipId)
      setDetail(updated)
      onUpdated()
    } catch (cause) {
      setError((cause as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (error) {
    return <div className="p-4 text-[12px] text-rejected">{error}</div>
  }
  if (!detail) {
    return <div className="p-4 text-[12px] text-faint">Loading relationship…</div>
  }

  const color = CONFIDENCE_COLOR[detail.confidence_level]
  const supporting = detail.evidence.filter((item) => item.stance === 'SUPPORTING')
  const contradicting = detail.evidence.filter(
    (item) => item.stance === 'CONTRADICTORY',
  )
  const neutral = detail.evidence.filter((item) => item.stance === 'NEUTRAL')

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-start justify-between gap-2 border-b border-line px-4 py-3">
        <div>
          <div className="panel-title">Relationship</div>
          <div className="mt-1 font-mono text-[13px] text-ink">
            <button
              className="hover:text-accent"
              onClick={() => detail.source_entity && onSelectEntity(detail.source_entity.id)}
            >
              {detail.source_entity?.platform_name} {detail.source_entity?.name}
            </button>
            <span className="mx-2 text-faint">↕</span>
            <button
              className="hover:text-accent"
              onClick={() => detail.target_entity && onSelectEntity(detail.target_entity.id)}
            >
              {detail.target_entity?.platform_name} {detail.target_entity?.name}
            </button>
          </div>
        </div>
        <button
          onClick={onClose}
          className="rounded border border-line px-2 py-0.5 font-mono text-[11px] text-faint hover:text-ink"
        >
          ✕
        </button>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3">
        <section className="grid grid-cols-2 gap-3">
          <div>
            <div className="panel-title">Type</div>
            <div className="mt-0.5 text-[13px] text-ink">{detail.relationship_label}</div>
          </div>
          <div>
            <div className="panel-title">Confidence</div>
            <div className="mt-0.5 text-[13px] font-semibold" style={{ color }}>
              {CONFIDENCE_LABEL[detail.confidence_level]}
            </div>
          </div>
          <div>
            <div className="panel-title">Score</div>
            <div className="mt-0.5 font-mono text-[13px]" style={{ color }}>
              {Math.round(detail.confidence_score)}
              <span className="text-faint"> / 100</span>
            </div>
          </div>
          <div>
            <div className="panel-title">Analyst status</div>
            <div
              className="mt-0.5 font-mono text-[12px]"
              style={{ color: STATUS_COLOR[detail.analyst_status] }}
            >
              {detail.analyst_status}
            </div>
          </div>
        </section>

        <div className="h-1 w-full overflow-hidden rounded-full bg-line">
          <div
            className="h-full rounded-full"
            style={{ width: `${detail.confidence_score}%`, background: color }}
          />
        </div>

        {detail.summary && (
          <p className="text-[12px] leading-snug text-dim">{detail.summary}</p>
        )}

        <EvidencePanel
          supporting={supporting}
          contradicting={contradicting}
          neutral={neutral}
          sourceEntity={detail.source_entity}
          targetEntity={detail.target_entity}
          onSelectEntity={onSelectEntity}
        />

        <section className="space-y-2 border-t border-line pt-3">
          <div className="panel-title">Analyst decision</div>
          <p className="text-[11px] leading-snug text-faint">
            Confirming records that you reviewed the evidence and judged it
            supportive. It does not assert that these accounts belong to the same
            person.
          </p>
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Rationale (optional)"
            rows={2}
            className="w-full resize-none rounded border border-line bg-void px-2 py-1 text-[12px] text-ink outline-none focus:border-accent"
          />
          <div className="flex gap-2">
            <button
              disabled={busy}
              onClick={() => decide('CONFIRMED')}
              className="flex-1 rounded border border-confirmed/60 bg-confirmed/10 px-2 py-1.5 text-[12px] font-medium text-confirmed hover:bg-confirmed/20 disabled:opacity-50"
            >
              Confirm
            </button>
            <button
              disabled={busy}
              onClick={() => decide('REJECTED')}
              className="flex-1 rounded border border-rejected/60 bg-rejected/10 px-2 py-1.5 text-[12px] font-medium text-rejected hover:bg-rejected/20 disabled:opacity-50"
            >
              Reject
            </button>
            {detail.analyst_status !== 'UNREVIEWED' && (
              <button
                disabled={busy}
                onClick={() => decide('UNREVIEWED')}
                className="rounded border border-line px-2 py-1.5 text-[12px] text-faint hover:text-ink disabled:opacity-50"
              >
                Undo
              </button>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}
