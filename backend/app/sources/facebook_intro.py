"""The Intro block on a public Facebook profile.

What this is, and what it is not
--------------------------------

Facebook renders the Intro rows - employer, education, hometown, relationship,
joined date - into the HTML it serves to anonymous visitors, embedded in the
GraphQL payloads the page bootstraps itself from.  Reading them is ordinary
parsing of a page anyone can open logged out.  Nothing here logs in, replays a
cookie, calls a private endpoint or touches an authenticated GraphQL query.

That distinction decides how much you get.  Pages and public-figure profiles
ship their Intro in that anonymous HTML; ordinary personal profiles do not -
Facebook loads theirs over an authenticated request after login, so for a
private individual there is simply nothing here to read, and this returns
nothing rather than pretending otherwise.  Measured on real profiles: Mark
Zuckerberg 7 rows, Coca-Cola 3, Bill Gates 3, an ordinary personal profile 0.

Why it is worth parsing anyway
------------------------------

The rows carry exactly what the correlation engine is starved of.  "Works at
Biohub" is an organization the scorer already knows how to match across
platforms; "Lives in Palo Alto" is a location it already knows how to
contradict.  Both arrive as observations with a URL behind them, which is the
standard this project holds every point of every score to.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlparse

#: The GraphQL key wrapping one Intro row.
ROW_KEY = "timeline_context_item"

#: Rows are prose, not fields, so the leading phrase is what types them.
#: Ordered: the first pattern that matches wins, so the more specific
#: "Former ... at" is tried before the bare "... at".
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "education",
        re.compile(
            r"^Stud(?:ied|ies)\s+(?:(?P<detail>.+?)\s+)?at\s+(?P<value>.+)$", re.I
        ),
    ),
    ("education", re.compile(r"^Went to\s+(?P<value>.+)$", re.I)),
    ("past_work", re.compile(r"^Former\s+(?P<detail>.+?)\s+at\s+(?P<value>.+)$", re.I)),
    ("past_work", re.compile(r"^Worked at\s+(?P<value>.+)$", re.I)),
    ("work", re.compile(r"^Works? at\s+(?P<value>.+)$", re.I)),
    ("location", re.compile(r"^Lives in\s+(?P<value>.+)$", re.I)),
    ("hometown", re.compile(r"^From\s+(?P<value>.+)$", re.I)),
    (
        "relationship",
        re.compile(
            r"^(?P<detail>Married to|In a relationship with|Engaged to)"
            r"\s+(?P<value>.+)$",
            re.I,
        ),
    ),
    ("joined", re.compile(r"^Joined\s+(?P<value>.+)$", re.I)),
    ("category", re.compile(r"^(?:Profile|Page)\s*·\s*(?P<value>.+)$", re.I)),
    # "Founder and CEO at Meta" - a role with no leading verb. Last, because
    # every pattern above also contains " at ".
    ("work", re.compile(r"^(?P<detail>[^·]{2,60}?)\s+at\s+(?P<value>.+)$")),
)


@dataclass
class IntroRow:
    """One line of the Intro block, as published."""

    #: work / past_work / education / location / hometown / relationship /
    #: joined / category / other.
    kind: str
    #: The row exactly as Facebook wrote it, kept verbatim for evidence.
    text: str
    #: The thing the row is about: the employer, the school, the place.
    value: str | None = None
    #: The qualifier, where there was one: a job title, a degree.
    detail: str | None = None
    #: URLs the row linked to - Facebook entities, and occasionally an
    #: account on another platform.
    links: list[str] = field(default_factory=list)


@dataclass
class Intro:
    """The Intro block, sorted into the fields an investigation can use."""

    rows: list[IntroRow] = field(default_factory=list)

    @property
    def organizations(self) -> list[str]:
        """Employers and schools, current first, in published order."""
        wanted = ("work", "past_work", "education")
        seen: list[str] = []
        for kind in wanted:
            for row in self.rows:
                if row.kind == kind and row.value and row.value not in seen:
                    seen.append(row.value)
        return seen

    @property
    def current_organization(self) -> str | None:
        """Where they say they work now, if the Intro says so at all."""
        return next(
            (row.value for row in self.rows if row.kind == "work" and row.value), None
        )

    @property
    def location(self) -> str | None:
        return next(
            (row.value for row in self.rows if row.kind == "location" and row.value),
            None,
        )

    @property
    def hometown(self) -> str | None:
        return next(
            (row.value for row in self.rows if row.kind == "hometown" and row.value),
            None,
        )

    @property
    def external_links(self) -> list[str]:
        """Links to somewhere other than Facebook.

        This is the row an investigation most wants: a profile that lists its
        own Instagram or LinkedIn is an explicit, self-published connection,
        not an inference from a matching handle.
        """
        out: list[str] = []
        for row in self.rows:
            for link in row.links:
                if "facebook.com" in link or "fb.com" in link:
                    continue
                if link not in out:
                    out.append(link)
        return out

    def as_metadata(self) -> dict[str, object]:
        """The block in a form worth storing on the entity."""
        data: dict[str, object] = {}
        for key in ("organizations", "location", "hometown"):
            value = getattr(self, key)
            if value:
                data[f"intro_{key}"] = value
        joined = next(
            (row.value for row in self.rows if row.kind == "joined" and row.value), None
        )
        if joined:
            data["intro_joined"] = joined
        if self.rows:
            # The verbatim lines, so an analyst can read what was actually
            # published rather than only this module's reading of it.
            data["intro"] = [row.text for row in self.rows]
        return data

    def __bool__(self) -> bool:
        return bool(self.rows)


def unwrap_link(url: str) -> str:
    """Return the real destination behind a Facebook redirect wrapper.

    Outbound links are published as
    ``l.facebook.com/l.php?u=<urlencoded target>&h=...``.  Stored as-is they
    are worthless to an investigation: every external link on every profile
    would normalise to the same host, and the platform detector would read an
    Instagram account as a Facebook one.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    if not parsed.netloc.endswith("facebook.com"):
        return url
    if not parsed.path.endswith("/l.php"):
        return url
    target = parse_qs(parsed.query).get("u")
    if not target or not target[0]:
        return url
    return unquote(target[0])


def _remember(links: list[str], value: object) -> None:
    """Add one destination to a row's links, unwrapped and de-duplicated."""
    if not isinstance(value, str) or not value:
        return
    resolved = unwrap_link(value)
    if resolved and resolved not in links:
        links.append(resolved)


def _json_objects(html: str, key: str) -> list[str]:
    """Lift each JSON object that follows ``"key":`` out of the page.

    The payloads are megabyte-scale and deeply nested, so the object is found
    by balancing braces from the opening one rather than by parsing the whole
    document - string contents are skipped so a brace inside a bio cannot end
    the object early.
    """
    found: list[str] = []
    for match in re.finditer(re.escape(f'"{key}":') + r"\s*\{", html):
        start = html.index("{", match.end() - 1)
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(html)):
            char = html[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    found.append(html[start : index + 1])
                    break
    return found


def classify(text: str) -> tuple[str, str | None, str | None]:
    """Sort one Intro line into a kind, a value and a qualifier."""
    cleaned = " ".join(text.split())
    for kind, pattern in PATTERNS:
        match = pattern.match(cleaned)
        if match:
            groups = match.groupdict()
            value = (groups.get("value") or "").strip() or None
            detail = (groups.get("detail") or "").strip() or None
            return kind, value, detail
    return "other", None, None


def parse_intro(html: str) -> Intro:
    """Read the Intro block out of public profile HTML.

    Returns an empty :class:`Intro` when the page has none - which is the
    normal case for an ordinary personal profile, whose Intro Facebook only
    serves to a logged-in session.
    """
    intro = Intro()
    for raw in _json_objects(html, ROW_KEY):
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            # One malformed row must never cost the rest of the block.
            continue

        renderer = payload.get("renderer")
        if not isinstance(renderer, dict):
            continue
        item = renderer.get("context_item")
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        if not isinstance(title, dict):
            title = {}
        plain = item.get("plaintext_title")
        text = (title.get("text") or "").strip()
        if not text and isinstance(plain, dict):
            text = (plain.get("text") or "").strip()
        if not text:
            continue

        links: list[str] = []

        for entry in title.get("ranges") or []:
            entity = entry.get("entity") if isinstance(entry, dict) else None
            if not isinstance(entity, dict):
                continue
            # An outbound link publishes several spellings of the same
            # destination; the plain ``url`` is enough once unwrapped.
            _remember(links, entity.get("url"))
            _remember(links, entity.get("external_url"))
        # Some rows carry their target on the item rather than in a range.
        _remember(links, item.get("url"))

        # A row whose text is itself an address - "gatesnot.es/AI" - links
        # nowhere in the JSON but is still a published link.
        if not links:
            from ..utils.url_parser import extract_urls

            for found in extract_urls(text):
                _remember(links, found)

        kind, value, detail = classify(text)
        row = IntroRow(kind=kind, text=text, value=value, detail=detail, links=links)
        if not any(existing.text == row.text for existing in intro.rows):
            intro.rows.append(row)
    return intro
