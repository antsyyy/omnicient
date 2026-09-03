"""Threads source adapter.

Threads profiles are discovered either directly (the analyst seeded one) or,
far more often, because an Instagram bio or a personal website explicitly
pointed at ``threads.net/@handle``.  Ownership is never inferred from name
similarity alone - that only ever produces a weak candidate for the
correlation engine to judge.
"""

from __future__ import annotations

from .base import OpenGraphProfileAdapter


class ThreadsAdapter(OpenGraphProfileAdapter):
    """Looks up publicly available Threads profile information."""

    platform = "threads"
    name = "Threads"
    url_template = "https://www.threads.net/@{identifier}"
