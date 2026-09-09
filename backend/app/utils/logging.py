"""Structured logging.

Log lines are ``event key=value`` pairs so an investigation can be replayed
from the log::

    INFO investigation_started seed=instagram:alice_98
    INFO entity_discovered type=WEBSITE value=alice.dev
    INFO relationship_created type=LINKS_TO

Credentials are never handled by Omnicient, and :func:`log_event` additionally
redacts any field whose name looks sensitive so a future contributor cannot
accidentally log one.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

SENSITIVE_KEYS = (
    "password", "passwd", "secret", "token", "cookie", "session", "authorization",
    "auth", "api_key", "apikey", "credential",
)

REDACTED = "[redacted]"


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging once, writing to stderr."""
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level.upper())
        return
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # The driver reports every "IF NOT EXISTS" schema statement that was
    # already satisfied.  That is expected on each boot and would otherwise
    # bury the application's own startup lines.
    logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a module logger."""
    return logging.getLogger(name)


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_KEYS)


def format_event(event: str, **fields: Any) -> str:
    """Render an event and its fields as a single structured log line."""
    parts = [event]
    for key, value in fields.items():
        if value is None:
            continue
        if _is_sensitive(key):
            rendered = REDACTED
        else:
            rendered = str(value)
            if len(rendered) > 200:
                rendered = rendered[:197] + "..."
            if " " in rendered:
                rendered = f'"{rendered}"'
        parts.append(f"{key}={rendered}")
    return " ".join(parts)


def log_event(
    logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any
) -> str:
    """Log a structured event and return the rendered line.

    The returned line is also persisted as a crawl event, so the analyst-facing
    timeline and the server log always tell the same story.
    """
    line = format_event(event, **fields)
    logger.log(level, line)
    return line
