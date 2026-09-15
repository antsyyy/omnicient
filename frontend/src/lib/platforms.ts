/**
 * Which platform a URL points at.
 *
 * The backend does this properly — it is what decides whether a published
 * link becomes an account to investigate. This is the interface's much
 * smaller version of the same question, used only to put the right mark
 * beside a link in a list. It never decides anything: a URL it does not
 * recognise simply gets the generic website mark.
 */

const HOSTS: Record<string, string> = {
  'instagram.com': 'instagram',
  'instagr.am': 'instagram',
  'threads.net': 'threads',
  'threads.com': 'threads',
  'facebook.com': 'facebook',
  'fb.com': 'facebook',
  'fb.me': 'facebook',
  'github.com': 'github',
  'reddit.com': 'reddit',
  'redd.it': 'reddit',
  'x.com': 'x',
  'twitter.com': 'x',
  'linkedin.com': 'linkedin',
  'youtube.com': 'youtube',
  'youtu.be': 'youtube',
  'mastodon.social': 'mastodon',
  'bsky.app': 'bluesky',
  'bsky.social': 'bluesky',
  'dev.to': 'devto',
  'keybase.io': 'keybase',
  'news.ycombinator.com': 'hackernews',
  'pypi.org': 'pypi',
  't.me': 'telegram',
  'telegram.me': 'telegram',
  'huggingface.co': 'huggingface',
  'crates.io': 'crates',
  'hub.docker.com': 'dockerhub',
  'stackoverflow.com': 'stackoverflow',
  'launchpad.net': 'launchpad',
  'steamcommunity.com': 'steam',
  'soundcloud.com': 'soundcloud',
  'last.fm': 'lastfm',
  'codewars.com': 'codewars',
  'scratch.mit.edu': 'scratch',
  'duolingo.com': 'duolingo',
  'medium.com': 'medium',
  'linktr.ee': 'linktree',
  'solo.to': 'solo',
  'bio.link': 'biolink',
  'gravatar.com': 'gravatar',
  'chess.com': 'chess',
  'lobste.rs': 'lobsters',
  'twitch.tv': 'twitch',
  'tiktok.com': 'tiktok',
}

export function platformOf(url: string): string | null {
  let host: string
  try {
    host = new URL(url).hostname.toLowerCase()
  } catch {
    return null
  }
  host = host.replace(/^www\./, '').replace(/^m\./, '')
  if (HOSTS[host]) return HOSTS[host]
  // A subdomain of a known host: "0.gravatar.com", "en.gravatar.com".
  const match = Object.keys(HOSTS).find((known) => host.endsWith(`.${known}`))
  return match ? HOSTS[match] : null
}
