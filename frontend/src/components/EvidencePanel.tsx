import type { Evidence } from '../types'
import { formatDate, shortUrl } from '../lib/display'

interface Props {
  supporting: Evidence[]
  contradicting: Evidence[]
}

function EvidenceRow({ item }: { item: Evidence }) {
  const color = item.supports ? 'var(--color-confirmed)' : 'var(--color-contradiction)'
  return (
    <li className="border-b border-line/70 py-2 last:border-b-0">
      <div className="flex items-start gap-2">
        <span className="mt-[1px] font-mono text-[12px]" style={{ color }}>
          {item.supports ? '✓' : '✗'}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="panel-title" style={{ color }}>
              {item.type.replace(/_/g, ' ')}
            </span>
            <span className="font-mono text-[10px] text-faint">
              {item.weight > 0 ? `+${item.weight}` : item.weight}
            </span>
          </div>
          <p className="mt-0.5 text-[12px] leading-snug text-dim">{item.description}</p>
          {item.source_url && (
            <a
              href={item.source_url}
              target="_blank"
              rel="noreferrer noopener"
              className="mt-0.5 block truncate font-mono text-[10px] text-accent hover:underline"
              title={item.source_url}
            >
              {shortUrl(item.source_url, 54)}
            </a>
          )}
          <div className="mt-0.5 font-mono text-[9px] text-faint">
            Collected {formatDate(item.collected_at)}
          </div>
        </div>
      </div>
    </li>
  )
}

/**
 * Evidence, split into what supports a relationship and what argues against it.
 *
 * Contradictions are never hidden: reducing false positives depends on the
 * analyst seeing conflicting attributes as prominently as matching ones.
 */
export default function EvidencePanel({ supporting, contradicting }: Props) {
  if (supporting.length === 0 && contradicting.length === 0) {
    return (
      <p className="py-2 text-[12px] text-faint">
        Insufficient evidence — nothing observable connects these entities.
      </p>
    )
  }

  return (
    <div className="space-y-4">
      <section>
        <div className="panel-title mb-1 border-b border-line pb-1">
          Supporting evidence · {supporting.length}
        </div>
        {supporting.length ? (
          <ul>
            {supporting.map((item) => (
              <EvidenceRow key={item.id} item={item} />
            ))}
          </ul>
        ) : (
          <p className="py-1 text-[12px] text-faint">None.</p>
        )}
      </section>

      <section>
        <div className="panel-title mb-1 border-b border-line pb-1">
          Contradictions · {contradicting.length}
        </div>
        {contradicting.length ? (
          <ul>
            {contradicting.map((item) => (
              <EvidenceRow key={item.id} item={item} />
            ))}
          </ul>
        ) : (
          <p className="py-1 text-[12px] text-faint">None.</p>
        )}
      </section>
    </div>
  )
}
