import { useState } from 'react'
import type { Evidence, EntitySummary } from '../types'
import { formatDate, shortUrl } from '../lib/display'

interface Props {
  supporting: Evidence[]
  contradicting: Evidence[]
  neutral?: Evidence[]
  /** Endpoints of the relationship, so each item can name what it connects. */
  sourceEntity?: EntitySummary | null
  targetEntity?: EntitySummary | null
  onSelectEntity?: (entityId: string) => void
}

const STANCE_COLOR: Record<string, string> = {
  SUPPORTING: 'var(--color-confirmed)',
  CONTRADICTORY: 'var(--color-contradiction)',
  NEUTRAL: 'var(--color-dim)',
}

const STANCE_GLYPH: Record<string, string> = {
  SUPPORTING: '✓',
  CONTRADICTORY: '✗',
  NEUTRAL: '•',
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <span className="w-[74px] shrink-0 font-mono text-[9px] uppercase tracking-wider text-faint">
        {label}
      </span>
      <span className="min-w-0 flex-1 text-[11px] leading-snug text-dim">
        {children}
      </span>
    </div>
  )
}

/**
 * One observation, with its full provenance.
 *
 * The header line is always visible; expanding shows where the value came
 * from, when it was collected, which entities it connects and what it did to
 * the score. That chain is the point of the tool — a number an analyst cannot
 * trace back to an observation is not evidence.
 */
function EvidenceRow({
  item,
  sourceEntity,
  targetEntity,
  onSelectEntity,
}: {
  item: Evidence
  sourceEntity?: EntitySummary | null
  targetEntity?: EntitySummary | null
  onSelectEntity?: (entityId: string) => void
}) {
  const [open, setOpen] = useState(false)
  const color = STANCE_COLOR[item.stance] ?? STANCE_COLOR.NEUTRAL

  const entityButton = (entity: EntitySummary | null | undefined) => {
    if (!entity) return <span className="text-faint">—</span>
    return onSelectEntity ? (
      <button
        onClick={() => onSelectEntity(entity.id)}
        className="text-left font-mono text-[11px] text-accent hover:underline"
      >
        {entity.platform_name} {entity.name}
      </button>
    ) : (
      <span className="font-mono">
        {entity.platform_name} {entity.name}
      </span>
    )
  }

  return (
    <li className="border-b border-line/70 py-2 last:border-b-0">
      <button
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-start gap-2 text-left"
        aria-expanded={open}
      >
        <span className="mt-[1px] font-mono text-[12px]" style={{ color }}>
          {STANCE_GLYPH[item.stance] ?? '•'}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="panel-title" style={{ color }}>
              {item.type.replace(/_/g, ' ')}
            </span>
            <span className="font-mono text-[10px]" style={{ color }}>
              {item.score_impact}
            </span>
            <span className="ml-auto font-mono text-[9px] text-faint">
              {open ? '−' : '+'}
            </span>
          </span>
          <span className="mt-0.5 block text-[12px] leading-snug text-dim">
            {item.description}
          </span>
        </span>
      </button>

      {open && (
        <div className="mt-2 space-y-1 border-l border-line pl-3">
          {item.extracted_value && (
            <Field label="Observed">
              <span className="break-all font-mono text-[11px] text-ink">
                {item.extracted_value}
              </span>
            </Field>
          )}
          {item.normalized_value &&
            item.normalized_value !== item.extracted_value && (
              <Field label="Matched as">
                <span className="break-all font-mono text-[11px]">
                  {item.normalized_value}
                </span>
              </Field>
            )}
          <Field label="Connects">
            <span className="flex flex-wrap items-center gap-1">
              {entityButton(sourceEntity)}
              <span className="text-faint">↔</span>
              {entityButton(targetEntity)}
            </span>
          </Field>
          {item.source_url && (
            <Field label="Source">
              <a
                href={item.source_url}
                target="_blank"
                rel="noreferrer noopener"
                className="break-all font-mono text-[10px] text-accent hover:underline"
                title={item.source_url}
              >
                {shortUrl(item.source_url, 52)}
              </a>
            </Field>
          )}
          <Field label="Collected">
            <span className="font-mono text-[10px]">
              {formatDate(item.collected_at)}
            </span>
          </Field>
          <Field label="Effect">
            <span className="font-mono text-[10px]" style={{ color }}>
              {item.score_impact} correlation score
            </span>
          </Field>
        </div>
      )}
    </li>
  )
}

function Section({
  title,
  items,
  emptyNote,
  ...rest
}: {
  title: string
  items: Evidence[]
  emptyNote?: string
  sourceEntity?: EntitySummary | null
  targetEntity?: EntitySummary | null
  onSelectEntity?: (entityId: string) => void
}) {
  if (!items.length && !emptyNote) return null
  return (
    <section>
      <div className="panel-title mb-1 border-b border-line pb-1">
        {title} · {items.length}
      </div>
      {items.length ? (
        <ul>
          {items.map((item) => (
            <EvidenceRow key={item.id} item={item} {...rest} />
          ))}
        </ul>
      ) : (
        <p className="py-1 text-[12px] text-faint">{emptyNote}</p>
      )}
    </section>
  )
}

/**
 * Evidence, split by what it does to the relationship.
 *
 * Contradictions are never hidden: reducing false positives depends on the
 * analyst seeing conflicting attributes as prominently as matching ones.
 */
export default function EvidencePanel({
  supporting,
  contradicting,
  neutral = [],
  sourceEntity,
  targetEntity,
  onSelectEntity,
}: Props) {
  const shared = { sourceEntity, targetEntity, onSelectEntity }

  if (!supporting.length && !contradicting.length && !neutral.length) {
    return (
      <p className="py-2 text-[12px] text-faint">
        Insufficient evidence — nothing observable connects these entities.
      </p>
    )
  }

  return (
    <div className="space-y-4">
      <Section
        title="Supporting evidence"
        items={supporting}
        emptyNote="None."
        {...shared}
      />
      <Section
        title="Contradictions"
        items={contradicting}
        emptyNote="None."
        {...shared}
      />
      <Section title="Observed, no score effect" items={neutral} {...shared} />
    </div>
  )
}
