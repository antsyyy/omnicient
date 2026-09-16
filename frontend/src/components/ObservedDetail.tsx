/**
 * Everything a source published about an account, rendered as it was read.
 *
 * Adapters record whatever their platform happens to offer, so this is a
 * genuinely open set: a job title and pronouns from Gravatar, a chess title
 * and a follower count from Chess.com, karma from Lobsters, and from a
 * Facebook Intro a whole employment and education history. Hard-coding a
 * field list would mean every new adapter silently loses the interesting part
 * of what it read.
 *
 * Two rules hold it together. Values are shown as strings, never interpreted
 * — a count is a count because the platform said so, not because this decided
 * what it means. And anything that reads as a list of lines (the Intro rows)
 * is shown as those lines, verbatim, because an analyst reading "Former
 * Director of Engineering at TAI Inc." is reading what the profile actually
 * says rather than this module's summary of it.
 */

import { shortUrl } from '../lib/display'

interface Props {
  metadata: Record<string, unknown> | null | undefined
}

/** Keys the panel renders itself, or that are plumbing rather than findings. */
const HANDLED_ELSEWHERE = new Set([
  'notice',
  'og_type',
  'intro_location',
  'intro_organizations',
])

/** Analyst-facing wording for the keys adapters commonly record. */
const LABELS: Record<string, string> = {
  intro: 'Intro, as published',
  intro_hometown: 'Hometown',
  intro_joined: 'Joined',
  job_title: 'Job title',
  pronouns: 'Pronouns',
  gravatar_hash: 'Gravatar hash',
  verified_accounts: 'Verified accounts',
  published_links: 'Links published',
  tracks_played: 'Tracks played',
  date_joined: 'Joined',
  created_at: 'Created',
  creation_date: 'Created',
  numFollowers: 'Followers',
  numModels: 'Models',
  numDatasets: 'Datasets',
  isPro: 'Pro account',
  is_moderator: 'Moderator',
  talking_about: 'Talking about this',
  were_here: 'Were here',
  user_id: 'User id',
}

function humanise(key: string): string {
  if (LABELS[key]) return LABELS[key]
  return key
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/^./, (c) => c.toUpperCase())
}

function Value({ value }: { value: unknown }) {
  if (typeof value === 'boolean') return <>{value ? 'yes' : 'no'}</>
  if (value === null || value === undefined) return <>—</>

  if (Array.isArray(value)) {
    return (
      <ul className="space-y-0.5">
        {value.map((item, index) => (
          <li key={index} className="leading-snug">
            {String(item)}
          </li>
        ))}
      </ul>
    )
  }

  const text = String(value)
  if (/^https?:\/\//i.test(text)) {
    return (
      <a
        href={text}
        target="_blank"
        rel="noreferrer noopener"
        className="font-mono text-accent hover:underline"
      >
        {shortUrl(text, 44)}
      </a>
    )
  }
  if (typeof value === 'number') {
    return <span className="font-mono">{value.toLocaleString()}</span>
  }
  return <>{text}</>
}

export default function ObservedDetail({ metadata }: Props) {
  const entries = Object.entries(metadata ?? {}).filter(
    ([key, value]) =>
      !HANDLED_ELSEWHERE.has(key) &&
      value !== null &&
      value !== undefined &&
      value !== '' &&
      !(Array.isArray(value) && value.length === 0),
  )
  if (entries.length === 0) return null

  return (
    <section className="border-t border-line pt-3">
      <div className="panel-title mb-1.5">Published by the source</div>
      <dl className="space-y-2">
        {entries.map(([key, value]) => (
          <div key={key}>
            <dt className="font-mono text-[10px] uppercase tracking-wide text-faint">
              {humanise(key)}
            </dt>
            <dd className="mt-0.5 text-[12px] leading-snug text-dim">
              <Value value={value} />
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-[11px] leading-snug text-faint">
        Read from the page as written. Omnicient does not interpret these —
        they are here so you can.
      </p>
    </section>
  )
}
