/**
 * A platform's mark, drawn in the interface's own palette.
 *
 * Every logo renders in `currentColor`, so it takes the colour of whatever it
 * sits in — the confidence band on a graph node, the muted ink of a list row.
 * That is deliberate. Omnicient uses colour for one thing only: how strong the
 * evidence is. Thirty brand palettes on one canvas would drown that out, and
 * an analyst would be reading Instagram's purple instead of the score.
 *
 * A platform with no mark falls back to its entity-type glyph, so an account
 * on a site Omnicient has never heard of still renders as something.
 */

import { PLATFORM_LOGO_PATHS } from '../lib/platformLogos'
import { ENTITY_GLYPH } from '../lib/display'

interface Props {
  platform: string
  /** Used for the fallback glyph when the platform has no mark. */
  entityType?: string
  size?: number
  className?: string
  /** Accessible label; omit for marks sitting next to their own name. */
  title?: string
  style?: React.CSSProperties
}

export function hasPlatformLogo(platform: string): boolean {
  return platform.toLowerCase() in PLATFORM_LOGO_PATHS
}

export default function PlatformLogo({
  platform,
  entityType,
  size = 14,
  className,
  title,
  style,
}: Props) {
  const path = PLATFORM_LOGO_PATHS[platform.toLowerCase()]

  if (!path) {
    return (
      <span
        className={className}
        style={{ fontSize: size, lineHeight: 1, ...style }}
        title={title}
        aria-hidden={title ? undefined : true}
      >
        {ENTITY_GLYPH[entityType ?? ''] ?? '◉'}
      </span>
    )
  }

  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="currentColor"
      className={className}
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      style={{ flexShrink: 0, ...style }}
    >
      {title && <title>{title}</title>}
      <path d={path} />
    </svg>
  )
}
