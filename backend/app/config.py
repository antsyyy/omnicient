"""Runtime configuration for Omnicient.

Everything is read from the environment (optionally via a ``.env`` file) so the
application runs with zero configuration in demo mode.  Two configuration
objects live here:

``Settings``
    Process-wide settings: database location, crawler budget, HTTP behaviour.

``ScoringConfig``
    The correlation model's point values.  They are kept in one object rather
    than scattered through the engine so the model can be retuned - or later
    replaced by a learned ranker - without touching correlation logic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class ScoringConfig:
    """Point values for the deterministic correlation model.

    Positive values are supporting evidence, negative values are contradictions.
    Scores are summed and clamped to ``[0, 100]``; they are *not* probabilities.
    """

    explicit_link: int = 70
    shared_email: int = 40
    shared_avatar: int = 25
    shared_website: int = 20
    similar_bio: int = 10
    exact_username: int = 10
    similar_username: int = 5
    same_display_name: int = 5
    shared_organization: int = 5

    contradictory_location: int = -15
    contradictory_website: int = -20
    metadata_conflict: int = -20

    # Confidence bands: (inclusive lower bound, label).  Ordered high to low.
    bands: tuple[tuple[int, str], ...] = (
        (75, "VERY_HIGH"),
        (50, "HIGH"),
        (20, "MEDIUM"),
        (0, "LOW"),
    )

    # A username pair at or above this ratio (but not identical) is "similar".
    username_similarity_threshold: float = 0.82
    # Bio token overlap (Jaccard) at or above this counts as a similar biography.
    bio_similarity_threshold: float = 0.35

    def weight(self, evidence_type: str) -> int:
        """Points for an evidence type, keyed by :class:`EvidenceType` value."""
        return _EVIDENCE_WEIGHT_FIELDS.get(evidence_type, lambda self: 0)(self)


# Maps EvidenceType values onto ScoringConfig fields.  Kept next to the config
# so adding an evidence type is a two-line change in one file.
_EVIDENCE_WEIGHT_FIELDS = {
    "EXPLICIT_LINK": lambda c: c.explicit_link,
    "SHARED_EMAIL": lambda c: c.shared_email,
    "SAME_AVATAR": lambda c: c.shared_avatar,
    "SAME_WEBSITE": lambda c: c.shared_website,
    "SIMILAR_BIO": lambda c: c.similar_bio,
    "SAME_USERNAME": lambda c: c.exact_username,
    "SIMILAR_USERNAME": lambda c: c.similar_username,
    "SAME_DISPLAY_NAME": lambda c: c.same_display_name,
    "SHARED_ORGANIZATION": lambda c: c.shared_organization,
}


@dataclass(frozen=True)
class Settings:
    """Process-wide settings."""

    app_name: str = "Omnicient"
    tagline: str = "Trace public identities. Follow the evidence."
    version: str = "0.1.0"

    # Neo4j is the primary and only datastore.  Entities and relationships are
    # native nodes and edges, so the graph the analyst reads is the graph the
    # database stores - no object-relational translation in between.
    neo4j_uri: str = field(
        default_factory=lambda: _env_str("NEO4J_URI", "bolt://localhost:7687")
    )
    neo4j_username: str = field(
        default_factory=lambda: _env_str("NEO4J_USERNAME", "neo4j")
    )
    neo4j_password: str = field(
        default_factory=lambda: _env_str("NEO4J_PASSWORD", "")
    )
    #: Target database inside the DBMS.  Tests point this at a scratch database
    #: so a run never touches investigation data.
    neo4j_database: str = field(
        default_factory=lambda: _env_str("NEO4J_DATABASE", "neo4j")
    )
    neo4j_max_connection_pool_size: int = field(
        default_factory=lambda: _env_int("NEO4J_MAX_POOL_SIZE", 25)
    )
    #: Seconds to wait for the DBMS at startup.  Neo4j in Docker is usually
    #: still recovering when the API container starts.
    neo4j_startup_timeout: float = field(
        default_factory=lambda: _env_float("NEO4J_STARTUP_TIMEOUT", 30.0)
    )

    # Path explorer bounds.  A graph query with no ceiling is a denial of
    # service waiting to happen, so both limits are enforced server-side and
    # the API clamps whatever a client asks for into these ranges.
    path_max_depth: int = field(
        default_factory=lambda: _env_int("OMNICIENT_PATH_MAX_DEPTH", 5)
    )
    path_max_paths: int = field(
        default_factory=lambda: _env_int("OMNICIENT_PATH_MAX_PATHS", 5)
    )
    #: Hard ceiling a request may never exceed, whatever it asks for.
    path_depth_ceiling: int = field(
        default_factory=lambda: _env_int("OMNICIENT_PATH_DEPTH_CEILING", 8)
    )
    path_result_ceiling: int = field(
        default_factory=lambda: _env_int("OMNICIENT_PATH_RESULT_CEILING", 25)
    )

    # Crawler budget (section 15 of the specification).
    max_depth: int = field(default_factory=lambda: _env_int("OMNICIENT_MAX_DEPTH", 2))
    max_pages: int = field(default_factory=lambda: _env_int("OMNICIENT_MAX_PAGES", 50))
    request_timeout: float = field(
        default_factory=lambda: _env_float("OMNICIENT_REQUEST_TIMEOUT", 10.0)
    )
    request_delay: float = field(
        default_factory=lambda: _env_float("OMNICIENT_REQUEST_DELAY", 1.0)
    )
    max_response_bytes: int = field(
        default_factory=lambda: _env_int("OMNICIENT_MAX_RESPONSE_BYTES", 2_000_000)
    )
    max_redirects: int = field(
        default_factory=lambda: _env_int("OMNICIENT_MAX_REDIRECTS", 3)
    )
    respect_robots: bool = field(
        default_factory=lambda: _env_bool("OMNICIENT_RESPECT_ROBOTS", True)
    )
    allow_private_networks: bool = field(
        default_factory=lambda: _env_bool("OMNICIENT_ALLOW_PRIVATE_NETWORKS", False)
    )

    user_agent: str = field(
        default_factory=lambda: _env_str(
            "OMNICIENT_USER_AGENT",
            "Omnicient/0.1 (OSINT research tool; public data only; "
            "+https://github.com/omnicient)",
        )
    )

    # Live crawling is opt-in: the shipped default is the offline demo dataset.
    demo_mode: bool = field(
        default_factory=lambda: _env_bool("OMNICIENT_DEMO_MODE", True)
    )

    cors_origins: list[str] = field(
        default_factory=lambda: _env_list(
            "OMNICIENT_CORS_ORIGINS",
            ["http://localhost:5173", "http://127.0.0.1:5173"],
        )
    )

    log_level: str = field(
        default_factory=lambda: _env_str("OMNICIENT_LOG_LEVEL", "INFO")
    )

    scoring: ScoringConfig = field(default_factory=ScoringConfig)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached process settings."""
    return Settings()
