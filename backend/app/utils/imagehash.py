"""Perceptual hashing, so the same face is recognised across platforms.

The correlation engine has always had a rule worth 25 points for two profiles
sharing an avatar, and until now it compared image *URLs*.  Instagram serves a
signed CDN address, GitHub serves ``avatars.githubusercontent.com/u/1234`` and
Gravatar serves a hash of an email; two platforms will essentially never
produce the same string.  The rule could only ever fire for two accounts on
the same site, which is not the case it exists for.

A difference hash fixes that.  The image is reduced to a 9x8 grey thumbnail
and each pixel compared with the one to its right, giving 64 bits that survive
re-encoding, rescaling and mild recompression - exactly what happens when one
photograph is uploaded to five different sites.

Two things this deliberately does not do.  It is not a similarity score for
*faces*: two different photographs of the same person will not match, and that
is correct, because guessing at that is a claim the evidence cannot support.
And it never decides anything on its own - it produces one observation, which
the engine scores alongside everything else.
"""

from __future__ import annotations

import io

from .logging import get_logger

logger = get_logger(__name__)

#: Side of the grey thumbnail. 9x8 pixels compared left-to-right gives 64 bits.
THUMBNAIL = (9, 8)

#: Hamming distance at or below which two hashes describe the same picture.
#:
#: Measured, not chosen. Across the labelled calibration pairs, one
#: photograph carried by several of a person's profiles sat between 7 and 12
#: bits apart - each platform crops and re-encodes what it is given - while
#: the closest pair of genuinely different pictures was 20 apart. Sweeping the
#: threshold: 6 matched nothing at all, 12 to 18 matched every true pair with
#: no false one, and 24 began matching strangers.
#:
#: Fourteen sits in the middle of that window. The first guess here was six,
#: which reproduced the very bug this rule was written to fix - a signal that
#: cannot fire - and only the calibration run revealed it.
#:
#: Worth revisiting as the dataset grows: it currently rests on one person's
#: avatars across five platforms, which is enough to place the threshold and
#: not enough to be confident of its edges.
MATCH_DISTANCE = 14

#: Below this many distinct bits, an image is too flat to identify anything.
#: Platform default avatars are usually a single colour or a silhouette on
#: one, and hashing them would link every account that never set a picture.
MIN_DETAIL_BITS = 8


#: Markers a platform puts in the address of its placeholder avatar.
#:
#: A real crawl produced "both profiles publish the same avatar" for two
#: unrelated Duolingo accounts, worth twenty-five points, because both had
#: *no* picture and the site served each the same
#: ``/avatar/default_2``. The image is a real drawing with real detail, so
#: neither the flat-image check nor the shared-by-many check would catch it -
#: but the platform says what it is in the URL.
DEFAULT_AVATAR_MARKERS = (
    "default",
    "placeholder",
    "anonymous",
    "mystery",
    "no_avatar",
    "no-avatar",
    "noavatar",
    "blank",
    "generic",
    "silhouette",
)


def looks_like_default_avatar(url: str | None) -> bool:
    """Whether an address is a platform's placeholder rather than a picture.

    Not evidence of anything: every account that never uploaded a photograph
    has this one, so matching on it links strangers.
    """
    if not url:
        return False
    lowered = url.lower()
    return any(marker in lowered for marker in DEFAULT_AVATAR_MARKERS)


def difference_hash(data: bytes) -> str | None:
    """A 16-character hex difference hash, or ``None`` if unusable.

    Returns ``None`` rather than raising for anything that is not a readable
    image: an adapter handing over an HTML error page, a truncated download, a
    format Pillow was not built with. A missing avatar hash costs one
    observation; an exception here would cost the crawl.
    """
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(data)) as image:
            # Orientation matters: the same photo saved with a different EXIF
            # rotation must still hash the same.
            image = ImageOps.exif_transpose(image)
            grey = image.convert("L").resize(THUMBNAIL, Image.Resampling.LANCZOS)
            pixels = list(grey.getdata())
    except Exception as error:  # noqa: BLE001 - any unreadable image is simply skipped
        logger.debug("avatar_hash_failed error=%s", error)
        return None

    width, height = THUMBNAIL
    bits = 0
    for row in range(height):
        for column in range(width - 1):
            left = pixels[row * width + column]
            right = pixels[row * width + column + 1]
            bits = (bits << 1) | int(left > right)

    if bin(bits).count("1") < MIN_DETAIL_BITS or bits == 0:
        # A flat image: a default avatar, a solid colour, a blank square.
        logger.debug("avatar_hash_featureless")
        return None
    return f"{bits:016x}"


def hamming_distance(first: str | None, second: str | None) -> int | None:
    """Bits that differ between two hashes, or ``None`` if either is missing."""
    if not first or not second:
        return None
    try:
        return bin(int(first, 16) ^ int(second, 16)).count("1")
    except ValueError:
        return None


def looks_like_same_image(first: str | None, second: str | None) -> bool:
    """Whether two hashes describe the same picture."""
    distance = hamming_distance(first, second)
    return distance is not None and distance <= MATCH_DISTANCE
