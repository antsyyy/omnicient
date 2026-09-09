import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Alias, IdentityProfile, ObservedValue } from '../types'
import { CONFIDENCE_COLOR, formatDay } from '../lib/display'

interface Props {
  investigationId: string
  onSelectEntity: (entityId: string) => void
  onSelectRelationship: (relationshipId: string) => void
  /** Bumped by the parent when the graph changes, to force a refresh. */
  revision: number
}

function Section({
  title,
  count,
  children,
}: {
  title: string
  count?: number
  children: React.ReactNode
}) {
  return (
    <section className="border-b border-line px-3 py-2.5 last:border-b-0">
      <div className="panel-title mb-1.5 flex items-center justify-between">
        <span>{title}</span>
        {count !== undefined && (
          <span className="font-mono text-[10px] text-faint">{count}</span>
        )}
      </div>
      {children}
    </section>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] italic text-faint">{children}</p>
}

/**
 * A value with the entities that published it.
 *
 * Clicking navigates to the source, which is the point: an aggregated value is
 * only meaningful if the analyst can get back to what published it.
 */
function ValueRow({
  item,
  onSelectEntity,
}: {
  item: ObservedValue
  onSelectEntity: (entityId: string) => void
}) {
  return (
    <li className="flex items-baseline justify-between gap-2 py-[3px]">
      <button
        onClick={() => item.entity_ids[0] && onSelectEntity(item.entity_ids[0])}
        disabled={!item.entity_ids.length}
        className="min-w-0 flex-1 truncate text-left font-mono text-[12px] text-ink hover:text-accent disabled:hover:text-ink"
        title={item.label ?? item.value}
      >
        {item.label ?? item.value}
      </button>
      <span
        className="shrink-0 font-mono text-[9px]"
        style={{
          color: item.corroborated
            ? 'var(--color-confirmed)'
            : 'var(--color-faint)',
        }}
        title={
          item.corroborated
            ? `Published by ${item.observation_count} entities`
            : 'Seen once'
        }
      >
        ×{item.observation_count}
      </span>
    </li>
  )
}

function AliasRow({
  alias,
  onSelectEntity,
  onSelectRelationship,
}: {
  alias: Alias
  onSelectEntity: (id: string) => void
  onSelectRelationship: (id: string) => void
}) {
  return (
    <li className="border-b border-line/60 py-1.5 last:border-b-0">
      <div className="flex items-baseline justify-between gap-2">
        <button
          onClick={() =>
            alias.target_entity_id && onSelectEntity(alias.target_entity_id)
          }
          className="truncate font-mono text-[12px] text-ink hover:text-accent"
        >
          {alias.target_identifier}
        </button>
        <span
          className="shrink-0 font-mono text-[9px]"
          style={{ color: CONFIDENCE_COLOR[alias.confidence] }}
        >
          {alias.confidence}
        </span>
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-1">
        <span className="font-mono text-[9px] uppercase tracking-wide text-faint">
          {alias.strength} resemblance
        </span>
        {alias.contradiction_count > 0 && (
          <span className="font-mono text-[9px] text-contradiction">
            · {alias.contradiction_count} contradiction
            {alias.contradiction_count > 1 ? 's' : ''}
          </span>
        )}
      </div>
      <ul className="mt-0.5">
        {alias.signals.slice(0, 3).map((signal, index) => (
          <li key={`${signal.kind}-${index}`} className="text-[11px] text-dim">
            • {signal.label}
          </li>
        ))}
      </ul>
      {alias.relationship_id && (
        <button
          onClick={() => onSelectRelationship(alias.relationship_id!)}
          className="mt-0.5 font-mono text-[10px] text-accent hover:underline"
        >
          view evidence →
        </button>
      )}
    </li>
  )
}

/**
 * Identity Intelligence Profile.
 *
 * A structured reading of what the investigation observed, so an analyst does
 * not have to click every node to see the shape of it. It is a summary of
 * *observations*, not a dossier on a person — every value names the entities
 * that published it, and the aliases stay potential.
 */
export default function IdentityProfilePanel({
  investigationId,
  onSelectEntity,
  onSelectRelationship,
  revision,
}: Props) {
  const [profile, setProfile] = useState<IdentityProfile | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    api
      .getProfile(investigationId)
      .then((data) => active && setProfile(data))
      .catch((cause: Error) => active && setError(cause.message))
    return () => {
      active = false
    }
  }, [investigationId, revision])

  if (error) return <p className="p-3 text-[12px] text-rejected">{error}</p>
  if (!profile) return <p className="p-3 text-[12px] text-faint">Loading…</p>

  const stats = profile.statistics
  const primary = profile.primary_identifier

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <Section title="Primary identifier">
        <button
          onClick={() => primary.entity_id && onSelectEntity(primary.entity_id)}
          disabled={!primary.entity_id}
          className="font-mono text-[15px] text-accent hover:underline disabled:hover:no-underline"
        >
          {primary.value}
        </button>
        <div className="mt-0.5 font-mono text-[10px] text-faint">
          {primary.type}
          {primary.platform ? ` · ${primary.platform}` : ''}
        </div>
      </Section>

      <Section title="Potential aliases" count={profile.potential_aliases.length}>
        {profile.potential_aliases.length ? (
          <ul>
            {profile.potential_aliases.map((alias, index) => (
              <AliasRow
                key={alias.relationship_id ?? index}
                alias={alias}
                onSelectEntity={onSelectEntity}
                onSelectRelationship={onSelectRelationship}
              />
            ))}
          </ul>
        ) : (
          <Empty>No handle variants proposed.</Empty>
        )}
      </Section>

      <Section title="Observed platforms" count={profile.platforms.length}>
        {profile.platforms.length ? (
          <ul>
            {profile.platforms.map((platform) => (
              <li
                key={platform.platform}
                className="flex items-baseline justify-between gap-2 py-[3px]"
              >
                <button
                  onClick={() =>
                    platform.entity_ids[0] && onSelectEntity(platform.entity_ids[0])
                  }
                  className="text-left text-[12px] text-ink hover:text-accent"
                >
                  {platform.platform_name}
                </button>
                <span className="font-mono text-[9px] text-faint">
                  {platform.resolved}/{platform.total} read
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <Empty>No accounts observed.</Empty>
        )}
      </Section>

      <Section title="Public websites" count={profile.websites.length}>
        {profile.websites.length ? (
          <ul>
            {profile.websites.map((item) => (
              <ValueRow key={item.value} item={item} onSelectEntity={onSelectEntity} />
            ))}
          </ul>
        ) : (
          <Empty>None observed.</Empty>
        )}
      </Section>

      <Section title="Public email references" count={profile.emails.length}>
        {profile.emails.length ? (
          <ul>
            {profile.emails.map((item) => (
              <ValueRow key={item.value} item={item} onSelectEntity={onSelectEntity} />
            ))}
          </ul>
        ) : (
          <Empty>None observed.</Empty>
        )}
      </Section>

      <Section title="Organizations" count={profile.organizations.length}>
        {profile.organizations.length ? (
          <ul>
            {profile.organizations.map((item) => (
              <ValueRow key={item.value} item={item} onSelectEntity={onSelectEntity} />
            ))}
          </ul>
        ) : (
          <Empty>None observed.</Empty>
        )}
      </Section>

      <Section title="Observed locations" count={profile.locations.length}>
        {profile.locations.length ? (
          <>
            <ul>
              {profile.locations.map((item) => (
                <ValueRow
                  key={item.value}
                  item={item}
                  onSelectEntity={onSelectEntity}
                />
              ))}
            </ul>
            {profile.locations.length > 1 && (
              <p className="mt-1 text-[10px] leading-snug text-band-medium">
                Multiple locations were published. These are separate
                observations, not a movement history.
              </p>
            )}
          </>
        ) : (
          <Empty>None published. Locations are never inferred.</Empty>
        )}
      </Section>

      <Section title="Timeline">
        <dl className="grid grid-cols-2 gap-2">
          <div>
            <dt className="font-mono text-[9px] uppercase text-faint">
              First observed
            </dt>
            <dd className="font-mono text-[12px] text-ink">
              {profile.first_observed ? formatDay(profile.first_observed) : '—'}
            </dd>
          </div>
          <div>
            <dt className="font-mono text-[9px] uppercase text-faint">
              Last observed
            </dt>
            <dd className="font-mono text-[12px] text-ink">
              {profile.last_observed ? formatDay(profile.last_observed) : '—'}
            </dd>
          </div>
        </dl>
        <p className="mt-1 font-mono text-[10px] text-faint">
          {profile.snapshot_count} snapshot
          {profile.snapshot_count === 1 ? '' : 's'} recorded
        </p>
      </Section>

      <Section title="Investigation statistics">
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[11px]">
          {[
            ['Entities', stats.entities],
            ['Accounts', stats.accounts],
            ['Potential relationships', stats.potential_relationships],
            ['High confidence', stats.high_confidence],
            ['Medium confidence', stats.medium_confidence],
            ['Low confidence', stats.low_confidence],
            ['Contradictions', stats.contradictions],
            ['Confirmed', stats.confirmed],
          ].map(([label, value]) => (
            <div key={label as string} className="flex justify-between gap-2">
              <dt className="truncate text-faint">{label}</dt>
              <dd
                style={{
                  color:
                    label === 'Contradictions' && Number(value) > 0
                      ? 'var(--color-contradiction)'
                      : 'var(--color-ink)',
                }}
              >
                {value}
              </dd>
            </div>
          ))}
        </dl>
      </Section>

      {profile.contradictions.length > 0 && (
        <Section title="Contradictions" count={profile.contradictions.length}>
          <ul className="space-y-1">
            {profile.contradictions.slice(0, 6).map((line, index) => (
              <li
                key={index}
                className="border-l border-contradiction/50 pl-2 text-[11px] leading-snug text-dim"
              >
                {line}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Evidence coverage">
        <div className="flex flex-wrap gap-x-3 gap-y-1 font-mono text-[11px]">
          <span className="text-confirmed">
            {profile.evidence_summary.supporting} supporting
          </span>
          <span className="text-contradiction">
            {profile.evidence_summary.contradicting} contradicting
          </span>
          <span className="text-faint">
            {profile.evidence_summary.neutral} neutral
          </span>
        </div>
        <p
          className="mt-1 text-[10px] leading-snug"
          style={{
            color: profile.evidence_summary.traceable
              ? 'var(--color-confirmed)'
              : 'var(--color-contradiction)',
          }}
        >
          {profile.evidence_summary.traceable
            ? 'Every relationship traces back to at least one observation.'
            : `${profile.evidence_summary.unexplained_relationships} relationship(s) have no evidence attached.`}
        </p>
      </Section>

      <p className="px-3 py-2.5 text-[10px] leading-snug text-faint">
        {profile.disclaimer}
      </p>
    </div>
  )
}
