import { useEffect, useRef } from 'react'
import type { CrawlEvent } from '../types'

interface Props {
  events: CrawlEvent[]
  /** True while a crawl is running, so the log can say it is still going. */
  live?: boolean
}

/** Glyph and tone per severity — the log is scanned, not read line by line. */
const LEVEL_STYLE: Record<string, { glyph: string; tone: string }> = {
  INFO: { glyph: '✓', tone: 'text-confirmed' },
  WARNING: { glyph: '!', tone: 'text-band-medium' },
  ERROR: { glyph: '✕', tone: 'text-rejected' },
}

/** Events worth pulling out of the stream when an analyst skims. */
const KEY_EVENTS = new Set([
  'identifier_detected',
  'sources_discovered',
  'correlation_completed',
  'investigation_completed',
])

function clockTime(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '--:--:--'
  return parsed.toLocaleTimeString(undefined, { hour12: false })
}

/**
 * The investigation activity log (section 27).
 *
 * Shows what the crawler actually did, in order, including the sources that
 * failed and why. It is the audit trail behind the graph: every node and every
 * score has a line here explaining where it came from.
 */
export default function ActivityLog({ events, live = false }: Props) {
  const endRef = useRef<HTMLDivElement>(null)

  // Follow the tail while a crawl is running, so new lines stay visible.
  useEffect(() => {
    if (live) endRef.current?.scrollIntoView({ block: 'nearest' })
  }, [events.length, live])

  return (
    <section className="flex min-h-0 flex-col">
      <h3 className="panel-title flex items-center justify-between px-3 py-2">
        <span>Investigation activity</span>
        <span className="font-mono text-[10px] text-faint">
          {live ? 'running…' : `${events.length}`}
        </span>
      </h3>

      {events.length === 0 ? (
        <p className="px-3 pb-3 text-[12px] text-faint">
          No activity recorded yet.
        </p>
      ) : (
        <ol className="min-h-0 flex-1 overflow-y-auto px-3 pb-3 font-mono text-[11px] leading-relaxed">
          {events.map((event) => {
            const style = LEVEL_STYLE[event.level] ?? LEVEL_STYLE.INFO
            return (
              <li key={event.id} className="flex gap-2 py-[3px]">
                <time
                  className="shrink-0 text-faint tabular-nums"
                  dateTime={event.timestamp}
                >
                  {clockTime(event.timestamp)}
                </time>
                <span className={`shrink-0 ${style.tone}`} aria-hidden>
                  {style.glyph}
                </span>
                <span
                  className={
                    KEY_EVENTS.has(event.event) ? 'text-ink' : 'text-dim'
                  }
                >
                  {event.message}
                </span>
              </li>
            )
          })}
          <div ref={endRef} />
        </ol>
      )}
    </section>
  )
}
