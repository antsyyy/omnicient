import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { CATEGORIES } from './layout/mindMapLayout'

interface Props {
  /** Only categories actually present in this investigation. */
  activeKeys: Set<string>
}

/**
 * What the canvas's visual language means.
 *
 * The edge treatments matter more than the colours: an analyst has to be able
 * to tell a confirmed association from a proposed one without clicking, and
 * the legend is where that convention is stated.
 *
 * Collapsed by default — it is a reference, not a fixture.
 */
export default function GraphLegend({ activeKeys }: Props) {
  const [open, setOpen] = useState(false)
  const categories = CATEGORIES.filter((entry) => activeKeys.has(entry.key))

  return (
    <div
      className="absolute bottom-3 left-3 z-20 overflow-hidden rounded-lg border border-line"
      style={{
        background: 'rgba(12,17,24,0.92)',
        backdropFilter: 'blur(8px)',
        boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
      }}
    >
      <button
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5"
        aria-expanded={open}
      >
        <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-faint">
          Legend
        </span>
        {open ? (
          <ChevronDown size={11} className="text-faint" />
        ) : (
          <ChevronUp size={11} className="text-faint" />
        )}
      </button>

      {open && (
        <div className="space-y-2.5 border-t border-line px-2.5 py-2">
          {categories.length > 0 && (
            <div>
              <div className="mb-1 font-mono text-[8.5px] uppercase tracking-wider text-faint">
                Categories
              </div>
              <ul className="space-y-0.5">
                {categories.map((entry) => (
                  <li key={entry.key} className="flex items-center gap-1.5">
                    <span
                      className="h-2 w-2 rounded-sm"
                      style={{ background: entry.accent }}
                    />
                    <span className="text-[10px] text-dim">{entry.title}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <div className="mb-1 font-mono text-[8.5px] uppercase tracking-wider text-faint">
              Relationships
            </div>
            <ul className="space-y-1">
              <LegendLine
                color="var(--color-confirmed)"
                dash={undefined}
                label="Confirmed by analyst"
              />
              <LegendLine
                color="var(--color-band-high)"
                dash="7 5"
                label="Potential — inferred"
              />
              <LegendLine
                color="var(--color-contradiction)"
                dash="2 5"
                label="Contradictory evidence"
              />
              <LegendLine
                color="var(--color-rejected)"
                dash="2 6"
                label="Rejected by analyst"
              />
            </ul>
          </div>

          <div>
            <div className="mb-1 font-mono text-[8.5px] uppercase tracking-wider text-faint">
              Entities
            </div>
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1 text-[10px] text-dim">
                <span className="font-mono text-[9px] text-band-high">●</span>
                read publicly
              </span>
              <span className="flex items-center gap-1 text-[10px] text-dim">
                <span className="font-mono text-[9px] text-faint">○</span>
                referenced only
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function LegendLine({
  color,
  dash,
  label,
}: {
  color: string
  dash: string | undefined
  label: string
}) {
  return (
    <li className="flex items-center gap-1.5">
      <svg width={26} height={6} aria-hidden>
        <line
          x1={0}
          y1={3}
          x2={26}
          y2={3}
          stroke={color}
          strokeWidth={2}
          strokeDasharray={dash}
        />
      </svg>
      <span className="text-[10px] text-dim">{label}</span>
    </li>
  )
}
