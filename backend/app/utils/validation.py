"""Input validation and SSRF protection.

Omnicient fetches URLs that were discovered during an investigation, which
means the crawler is a request-forgery primitive unless it is constrained.
Every outbound URL passes through :func:`validate_public_url` - both the
initial target and each redirect destination - so a profile that links to
``http://169.254.169.254/latest/meta-data/`` cannot make the server read its
own cloud credentials.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from .normalization import NormalizationError, normalize_url

ALLOWED_SCHEMES = frozenset({"http", "https"})

# Hostnames that always resolve to the local machine or an internal service.
BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    }
)

# Suffixes reserved for private/internal name resolution.
BLOCKED_HOST_SUFFIXES = ("localhost", ".local", ".internal", ".localdomain", ".home.arpa")

# Cloud instance metadata services.
BLOCKED_ADDRESSES = frozenset({"169.254.169.254", "fd00:ec2::254", "100.100.100.200"})

MAX_URL_LENGTH = 2048


class UnsafeURLError(ValueError):
    """Raised when a URL must not be requested by the crawler."""


@dataclass(frozen=True)
class ValidatedURL:
    """A URL that passed shape validation, with its normalized form."""

    url: str
    host: str
    scheme: str


def is_blocked_ip(address: str) -> bool:
    """True when an IP address is private, local, reserved or a metadata host."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return True
    if address in BLOCKED_ADDRESSES:
        return True
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (getattr(ip, "is_site_local", False))
    )


def is_blocked_hostname(host: str) -> bool:
    """True when a hostname is reserved for local or internal resolution."""
    lowered = host.strip().lower().rstrip(".")
    if not lowered:
        return True
    if lowered in BLOCKED_HOSTNAMES:
        return True
    return lowered.endswith(BLOCKED_HOST_SUFFIXES)


def validate_public_url(url: str, *, allow_private: bool = False) -> ValidatedURL:
    """Validate a URL's shape and host before it is requested.

    Raises :class:`UnsafeURLError` for non-http(s) schemes, over-long URLs,
    credentials embedded in the authority, loopback/private/link-local literals
    and known metadata endpoints.  DNS-level checks are applied separately by
    :func:`resolve_public_host`, because they require a name lookup.
    """
    if not url or len(url) > MAX_URL_LENGTH:
        raise UnsafeURLError("URL is empty or exceeds the maximum length")

    parsed = urlparse(url if "://" in url else f"https://{url}")
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"unsupported URL scheme: {parsed.scheme or 'none'!r}")
    if "@" in parsed.netloc:
        raise UnsafeURLError("URLs with embedded credentials are not fetched")

    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise UnsafeURLError("URL has no host")
    if allow_private:
        normalized = normalize_url(url, canonical=False)
        return ValidatedURL(normalized or url, host, parsed.scheme.lower())

    if is_blocked_hostname(host):
        raise UnsafeURLError(f"host {host!r} resolves to a local or internal service")

    literal = host.strip("[]")
    try:
        ipaddress.ip_address(literal)
    except ValueError:
        pass  # Not an IP literal; DNS resolution is checked at fetch time.
    else:
        if is_blocked_ip(literal):
            raise UnsafeURLError(
                f"host {host!r} is a private, loopback or reserved address"
            )

    # The host is preserved exactly as given: ``www.example.com`` must not be
    # requested as ``example.com``.  Canonicalisation for comparison happens
    # elsewhere, on the entity identity rather than on the request.
    normalized = normalize_url(url, canonical=False)
    if not normalized:
        raise UnsafeURLError(f"URL could not be normalized: {url!r}")
    return ValidatedURL(normalized, host, parsed.scheme.lower())


def resolve_public_host(host: str, port: int = 443) -> list[str]:
    """Resolve a hostname and reject it if any address is non-public.

    Every resolved address is checked, not just the first: a hostname that
    returns one public and one private address must not be fetched.
    """
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"host {host!r} could not be resolved: {exc}") from exc

    addresses = sorted({info[4][0] for info in infos})
    if not addresses:
        raise UnsafeURLError(f"host {host!r} resolved to no addresses")
    blocked = [address for address in addresses if is_blocked_ip(address)]
    if blocked:
        raise UnsafeURLError(
            f"host {host!r} resolves to a non-public address ({blocked[0]})"
        )
    return addresses


def validate_seed_identifier(value: str) -> str:
    """Validate a seed that is already known to be a handle.

    Investigation creation does **not** use this: it calls
    :func:`app.utils.identifier.detect_identifier`, which classifies the input
    first and so accepts email addresses, URLs and domains as well.  This
    remains for callers that specifically want handle validation.
    """
    from .normalization import normalize_username

    if value is None or not str(value).strip():
        raise NormalizationError("a seed identifier is required")
    if len(value) > MAX_URL_LENGTH:
        raise NormalizationError("seed identifier is too long")
    return normalize_username(value)


def clamp(value: float, low: float, high: float) -> float:
    """Clamp ``value`` into ``[low, high]``."""
    return max(low, min(high, value))
