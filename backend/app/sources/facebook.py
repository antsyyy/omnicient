"""Facebook source adapter.

Only public profile and page URLs are read.  Numeric ``profile.php?id=`` links
and any page that answers with a login wall are reported as unavailable rather
than guessed at, and no credential, cookie or private endpoint is ever used.
"""

from __future__ import annotations

from .base import OpenGraphProfileAdapter


class FacebookAdapter(OpenGraphProfileAdapter):
    """Looks up publicly available Facebook profile or page information."""

    platform = "facebook"
    name = "Facebook"
    url_template = "https://www.facebook.com/{identifier}"
