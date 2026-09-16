"""Recognising one photograph across platforms that each re-serve it.

The rule this supports is worth twenty-five points and, until now, compared
image URLs - so it could only ever fire for two accounts on the same site.
Instagram serves a signed CDN address, GitHub an /u/<id> path and Gravatar a
hash of an email: the case the rule exists for could never reach it.
"""

from __future__ import annotations

import io

import pytest

from app.utils.imagehash import (
    MATCH_DISTANCE,
    difference_hash,
    hamming_distance,
    looks_like_default_avatar,
    looks_like_same_image,
)


def picture(seed: int = 0, size: tuple[int, int] = (400, 400)):
    """A synthetic image with structure - not a flat colour."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", size, (30, 40, 60))
    draw = ImageDraw.Draw(image)
    for index in range(12):
        x = (index * 37 + seed * 53) % size[0]
        y = (index * 61 + seed * 29) % size[1]
        draw.ellipse(
            [x, y, x + 90, y + 70],
            fill=(200 - index * 8, 60 + index * 12, 120 + seed * 30),
        )
    draw.rectangle(
        [size[0] // 4, size[1] // 3, size[0] // 2, size[1] // 2], fill=(240, 230, 200)
    )
    return image


def encode(image, fmt: str = "PNG", **options) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, fmt, **options)
    return buffer.getvalue()


@pytest.mark.parametrize(
    "label,transform",
    [
        ("re-encoded as JPEG", lambda i: encode(i, "JPEG", quality=85)),
        ("heavily compressed", lambda i: encode(i, "JPEG", quality=40)),
        ("resized down", lambda i: encode(i.resize((150, 150)))),
        ("thumbnailed", lambda i: encode(i.resize((64, 64)))),
        ("resized and compressed", lambda i: encode(i.resize((128, 128)), "JPEG", quality=60)),
    ],
)
def test_one_picture_survives_what_platforms_do_to_it(label, transform) -> None:
    """Every platform re-encodes what it is given; the hash has to survive it."""
    original = picture()
    before = difference_hash(encode(original))
    after = difference_hash(transform(original))

    assert looks_like_same_image(before, after), label


def test_a_different_picture_does_not_match() -> None:
    first = difference_hash(encode(picture(seed=0)))
    second = difference_hash(encode(picture(seed=5)))

    assert not looks_like_same_image(first, second)
    assert hamming_distance(first, second) > MATCH_DISTANCE


def test_a_flat_image_is_refused() -> None:
    """A blank square is every account that never uploaded a picture."""
    from PIL import Image

    for colour in ((128, 128, 128), (255, 255, 255), (0, 0, 0)):
        assert difference_hash(encode(Image.new("RGB", (200, 200), colour))) is None


def test_anything_that_is_not_an_image_is_refused() -> None:
    """An error page served where a picture was expected must not raise."""
    assert difference_hash(b"<html>404 not found</html>") is None
    assert difference_hash(b"") is None
    assert difference_hash(b"\x89PNG\r\n\x1a\n truncated") is None


def test_a_missing_hash_is_not_a_match() -> None:
    real = difference_hash(encode(picture()))

    assert hamming_distance(real, None) is None
    assert not looks_like_same_image(real, None)
    assert not looks_like_same_image(None, None)


@pytest.mark.parametrize(
    "url,expected",
    [
        # The case that produced a false positive on a real crawl: two
        # unrelated accounts, both with no picture, both served this.
        ("https://simg-ssl.duolingo.com/avatar/default_2", True),
        ("https://cdn.example.com/img/no-avatar.png", True),
        ("https://example.com/assets/placeholder-user.jpg", True),
        ("https://avatars.githubusercontent.com/u/1024025", False),
        ("https://0.gravatar.com/avatar/27205e5c51cb", False),
        (None, False),
    ],
)
def test_a_platform_placeholder_is_never_evidence(url, expected) -> None:
    assert looks_like_default_avatar(url) is expected
