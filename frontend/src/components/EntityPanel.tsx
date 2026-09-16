import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { EntityDetail, Relationship } from '../types'
import {
  CONFIDENCE_COLOR,
  DISCOVERY_LABEL,
  formatDate,
  shortUrl,
} from '../lib/display'
import { platformOf } from '../lib/platforms'
import Avatar from './Avatar'
import ObservedDetail from './ObservedDetail'
import PlatformLogo from './PlatformLogo'

interface Props {
  entityId: string
  focused: boolean
  onClose: () => void
  onToggleFocus: (entityId: string) => void
  onSelectRelationship: (relationshipId: string) => void
  /** Re-read the graph, so the canvas picks up a ruling straight away. */
  onEntityChanged?: () => void
}

/**
 * Rule that an account belongs to somebody else, or take the ruling back.
 *
 * The one place a person may assert an identity in this system, so it says
 * out loud what it does and does not do. It is a judgement, recorded as the
 * analyst's; it deletes nothing; and the note is the only thing that makes it
 * reviewable later, which is why it is asked for rather than assumed.
 *
 * The seed has no control at all. It is what the investigation is about, the
 * server refuses to rule it out, and offering a button that always fails is
 * worse than offering none.
 */
function IdentityRuling({
  entity,
  onChanged,
}: {
  entity: EntityDetail
  onChanged: (updated: EntityDetail) => void
}) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const ruledOut = entity.analyst_verdict === 'DIFFERENT_IDENTITY'

  if (entity.is_seed) return null

  async function run(action: () => Promise<EntityDetail>) {
    setBusy(true)
    setFailed(null)
    try {
      onChanged(await action())
      setNote('')
    } catch (cause) {
      setFailed((cause as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (ruledOut) {
    return (
      <div className="rounded border border-rejected/40 bg-rejected/5 px-2.5 py-2">
        <div className="panel-title text-rejected">Different identity</div>
        <p className="mt-1 text-[11px] leading-snug text-dim">
          You judged this to be somebody else.
          {entity.reviewed_at && ` Recorded ${formatDate(entity.reviewed_at)}.`}
        </p>
        {entity.analyst_note && (
          <p className="mt-1 border-l border-line pl-2 text-[11px] leading-snug text-faint">
            {entity.analyst_note}
          </p>
        )}
        <p className="mt-1 text-[11px] leading-snug text-faint">
          Nothing was deleted — the evidence below still stands, and the filter
          panel can take it off the canvas.
        </p>
        <button
          disabled={busy}
          onClick={() => run(() => api.resetEntityIdentity(entity.id))}
          className="mt-2 rounded border border-line px-2 py-1 font-mono text-[11px] text-dim hover:text-ink disabled:opacity-50"
        >
          {busy ? 'working…' : 'undo this ruling'}
        </button>
        {failed && <p className="mt-1 text-[11px] text-rejected">{failed}</p>}
      </div>
    )
  }

  return (
    <details className="rounded border border-line bg-raised px-2.5 py-2">
      <summary className="cursor-pointer font-mono text-[11px] text-faint hover:text-ink">
        not the same person?
      </summary>
      <p className="mt-1.5 text-[11px] leading-snug text-faint">
        Records your judgement that this account belongs to a different party.
        It deletes nothing and can be undone.
      </p>
      <textarea
        value={note}
        onChange={(event) => setNote(event.target.value)}
        maxLength={2000}
        rows={2}
        placeholder="Why? e.g. different city and employer, handle is a common name"
        className="mt-1.5 w-full rounded border border-line bg-panel px-2 py-1 text-[11px] text-ink placeholder:text-faint"
      />
      <button
        disabled={busy}
        onClick={() =>
          run(() => api.markDifferentIdentity(entity.id, note.trim() || undefined))
        }
        className="mt-1.5 rounded border border-rejected/50 px-2 py-1 font-mono text-[11px] text-rejected hover:bg-rejected/10 disabled:opacity-50"
      >
        {busy ? 'working…' : 'mark as different identity'}
      </button>
      {failed && <p className="mt-1 text-[11px] text-rejected">{failed}</p>}
    </details>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="panel-title">{label}</div>
      <div className="mt-0.5 text-[12px] leading-snug text-dim">{children}</div>
    </div>
  )
}

/**
 * The entity inspector: everything publicly observed about one node, plus the
 * relationships it takes part in.
 */
export default function EntityPanel({
  entityId,
  focused,
  onClose,
  onToggleFocus,
  onSelectRelationship,
  onEntityChanged,
}: Props) {
  const [entity, setEntity] = useState<EntityDetail | null>(null)
  const [relationships, setRelationships] = useState<Relationship[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setEntity(null)
    setError(null)
    Promise.all([api.getEntity(entityId), api.getEntityRelationships(entityId)])
      .then(([detail, related]) => {
        if (!active) return
        setEntity(detail)
        setRelationships(related)
      })
      .catch((cause: Error) => active && setError(cause.message))
    return () => {
      active = false
    }
  }, [entityId])

  if (error) return <div className="p-4 text-[12px] text-rejected">{error}</div>
  if (!entity) return <div className="p-4 text-[12px] text-faint">Loading entity…</div>

  const isDemo = entity.metadata?.notice === 'DEMO DATA'

  /*
   * flex-1, not h-full. This panel is a flex child of the inspector section,
   * which also holds the tab bar - so h-full meant "the height of the whole
   * section", nav included, and the panel ran past the bottom by exactly the
   * nav's height. overflow-hidden on the section then clipped whatever came
   * last, which is the footer: on a 760px-tall window the Expand connections
   * button was sliced in half, and at 1000px it survived by three pixels,
   * which is why it looked fine here for so long.
   *
   * min-h-0 goes with it. A flex item's min-height defaults to auto, which
   * refuses to shrink below the content - the scrolling body would push the
   * footer straight back out of view without it.
   */
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex items-start justify-between gap-2 border-b border-line px-4 py-3">
        <div className="flex min-w-0 gap-3">
          <Avatar
            url={entity.avatar_url}
            platform={entity.platform}
            entityType={entity.type}
            size={44}
          />
          <div className="min-w-0">
            <div className="panel-title">Entity · {entity.type}</div>
            <div className="mt-0.5 truncate text-[13px] text-dim">
              {entity.platform_name}
            </div>
            <div className="truncate font-mono text-[15px] text-ink">{entity.name}</div>
            {entity.display_name && entity.display_name !== entity.name && (
              <div className="truncate text-[12px] text-dim">
                {entity.display_name}
              </div>
            )}
          </div>
        </div>
        <button
          onClick={onClose}
          className="rounded border border-line px-2 py-0.5 font-mono text-[11px] text-faint hover:text-ink"
        >
          ✕
        </button>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {isDemo && (
          <div className="rounded border border-demo/50 bg-demo/10 px-2 py-1 font-mono text-[10px] tracking-wider text-demo">
            DEMO DATA — synthetic, not a real person
          </div>
        )}
        {!entity.resolved && (
          <div className="rounded border border-line bg-raised px-2 py-1 text-[11px] text-faint">
            Unresolved candidate: this account was referenced publicly, but no
            public profile could be read for it.
          </div>
        )}

        <IdentityRuling
          entity={entity}
          onChanged={(updated) => {
            setEntity(updated)
            onEntityChanged?.()
          }}
        />

        {entity.bio && <Field label="Bio">{entity.bio}</Field>}
        {entity.location && <Field label="Location">{entity.location}</Field>}
        {entity.email && <Field label="Public email">{entity.email}</Field>}
        {entity.organization && <Field label="Organization">{entity.organization}</Field>}

        {entity.url && (
          <Field label="Profile">
            <a
              href={entity.url}
              target="_blank"
              rel="noreferrer noopener"
              className="font-mono text-accent hover:underline"
            >
              {shortUrl(entity.url, 46)}
            </a>
          </Field>
        )}

        {entity.external_links.length > 0 && (
          <Field label={`Published links · ${entity.external_links.length}`}>
            {/*
              A link-in-bio page is mostly this list, so it is worth reading
              at a glance: each row is marked with the platform it points at,
              which is the same thing the crawler followed it as.
            */}
            <ul className="space-y-1">
              {entity.external_links.map((link) => {
                const target = platformOf(link)
                return (
                  <li key={link} className="flex items-center gap-1.5">
                    <PlatformLogo
                      platform={target ?? 'website'}
                      size={12}
                      className="shrink-0 text-faint"
                    />
                    <a
                      href={link}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="min-w-0 truncate font-mono text-accent hover:underline"
                      title={link}
                    >
                      {shortUrl(link, 42)}
                    </a>
                  </li>
                )
              })}
            </ul>
          </Field>
        )}

        <Field label="How it was found">
          {DISCOVERY_LABEL[entity.discovery_method] ?? entity.discovery_method}
          {entity.discovered_via && (
            <div className="mt-0.5 text-[11px] text-faint">{entity.discovered_via}</div>
          )}
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="First seen">{formatDate(entity.first_seen)}</Field>
          <Field label="Last seen">{formatDate(entity.last_seen)}</Field>
        </div>
        <Field label="Crawl depth">{entity.depth}</Field>
        {entity.snapshots.length > 1 && (
          <Field label="Observations">{entity.snapshots.length} snapshots recorded</Field>
        )}

        <ObservedDetail metadata={entity.metadata} />

        <section className="border-t border-line pt-3">
          <div className="panel-title mb-1">Relationships · {relationships.length}</div>
          <ul className="space-y-1">
            {relationships.map((relationship) => (
              <li key={relationship.id}>
                <button
                  onClick={() => onSelectRelationship(relationship.id)}
                  className="w-full rounded border border-line bg-raised px-2 py-1 text-left hover:border-accent"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-[12px] text-dim">
                      {relationship.relationship_label}
                    </span>
                    <span
                      className="font-mono text-[11px]"
                      style={{ color: CONFIDENCE_COLOR[relationship.confidence_level] }}
                    >
                      {Math.round(relationship.confidence_score)}
                    </span>
                  </div>
                  <div className="truncate text-[10px] text-faint">
                    {relationship.evidence_count} evidence item
                    {relationship.evidence_count === 1 ? '' : 's'}
                    {relationship.analyst_status !== 'UNREVIEWED' &&
                      ` · ${relationship.analyst_status}`}
                  </div>
                </button>
              </li>
            ))}
            {relationships.length === 0 && (
              <li className="text-[12px] text-faint">No relationships recorded.</li>
            )}
          </ul>
        </section>
      </div>

      <footer className="border-t border-line p-3">
        <button
          onClick={() => onToggleFocus(entity.id)}
          className="w-full rounded border border-accent/60 bg-accent/10 px-2 py-1.5 text-[12px] font-medium text-accent hover:bg-accent/20"
        >
          {focused ? 'Collapse connections' : 'Expand connections'}
        </button>
      </footer>
    </div>
  )
}
