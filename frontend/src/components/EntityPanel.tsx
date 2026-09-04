import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { EntityDetail, Relationship } from '../types'
import {
  CONFIDENCE_COLOR,
  DISCOVERY_LABEL,
  ENTITY_GLYPH,
  formatDate,
  shortUrl,
} from '../lib/display'

interface Props {
  entityId: string
  focused: boolean
  onClose: () => void
  onToggleFocus: (entityId: string) => void
  onSelectRelationship: (relationshipId: string) => void
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

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-start justify-between gap-2 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <div className="panel-title">
            Entity · {ENTITY_GLYPH[entity.type]} {entity.type}
          </div>
          <div className="mt-1 truncate text-[13px] text-dim">{entity.platform_name}</div>
          <div className="truncate font-mono text-[15px] text-ink">{entity.name}</div>
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

        {entity.display_name && <Field label="Display name">{entity.display_name}</Field>}
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
          <Field label="External links">
            <ul className="space-y-0.5">
              {entity.external_links.map((link) => (
                <li key={link}>
                  <a
                    href={link}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="font-mono text-accent hover:underline"
                  >
                    {shortUrl(link, 46)}
                  </a>
                </li>
              ))}
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
