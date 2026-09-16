/**
 * The profile picture an account publishes, where it can still be fetched.
 *
 * Most of these URLs come from a social CDN, and a good number of them will
 * not load: Instagram and Facebook sign their image URLs and expire them,
 * some hosts refuse a request that did not come from their own page, and an
 * unresolved candidate never had a picture in the first place.
 *
 * So the image is never the only thing drawn. The platform mark sits
 * underneath it and stays if the image fails, which means a broken avatar
 * costs an analyst nothing and a working one is a bonus. It is *not* evidence
 * either way — two accounts showing the same face is something the engine has
 * to observe and score, not something the interface may imply by putting two
 * pictures side by side.
 */

import { useEffect, useState } from 'react'
import PlatformLogo from './PlatformLogo'

interface Props {
  url: string | null | undefined
  platform: string
  entityType?: string
  /** Pixel size of the square. */
  size?: number
  className?: string
}

export default function Avatar({
  url,
  platform,
  entityType,
  size = 40,
  className,
}: Props) {
  const [failed, setFailed] = useState(false)

  // A different entity is a different picture: without this, selecting a
  // second account keeps the first one's failure and hides a good image.
  useEffect(() => setFailed(false), [url])

  const showImage = Boolean(url) && !failed

  return (
    <div
      className={`relative shrink-0 overflow-hidden rounded border border-line bg-raised ${className ?? ''}`}
      style={{ width: size, height: size }}
    >
      {/* Always rendered, so there is something to see the moment the image
          fails or while it is still loading. */}
      <div
        className="absolute inset-0 flex items-center justify-center text-faint"
        aria-hidden
      >
        <PlatformLogo
          platform={platform}
          entityType={entityType}
          size={Math.round(size * 0.45)}
        />
      </div>

      {showImage && (
        <img
          src={url ?? undefined}
          alt=""
          loading="lazy"
          // The image is decoration over a mark that already identifies the
          // platform, so it carries no alt text of its own.
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
          className="absolute inset-0 h-full w-full object-cover"
        />
      )}
    </div>
  )
}
