# Omnicient

> **Trace public identities. Follow the evidence.**

Omnicient is an **evidence-backed OSINT crawling and identity correlation
platform**. It starts from a single publicly observable identifier, discovers
other publicly observable entities and relationships, scores potential
associations with a transparent rule-based model, and presents the whole
investigation as an interactive graph an analyst can interrogate, confirm or
reject.

The central principle:

```
Don't claim the identity.
Show the evidence.
```

Omnicient never states that two accounts belong to the same person. It reports
*potential associations* — with the observations behind them, the points each
observation contributed, and the contradictions that argue against them.

---

## Table of contents

- [Problem statement](#problem-statement)
- [Features](#features)
- [Architecture](#architecture)
- [Technology stack](#technology-stack)
- [Installation](#installation)
- [Running the application](#running-the-application)
- [Environment variables](#environment-variables)
- [Demo mode](#demo-mode)
- [API documentation](#api-documentation)
- [Identifier detection](#identifier-detection)
- [Investigation canvas](#investigation-canvas)
- [Analysis layer](#analysis-layer)
- [Correlation methodology](#correlation-methodology)
  - [Calibration](#calibration)
- [Confidence scoring](#confidence-scoring)
- [Crawler behaviour and limitations](#crawler-behaviour-and-limitations)
- [Security protections](#security-protections)
- [Ethical and legal considerations](#ethical-and-legal-considerations)
- [Project structure](#project-structure)
- [Testing](#testing)
- [Working in a two-person team](#working-in-a-two-person-team)
- [Future architecture](#future-architecture)
- [License](#license)

---

## Problem statement

Given a known public account — say `Instagram: @alice_98` — an analyst wants to
know which other publicly observable entities are plausibly connected to it,
and *why*.

The usernames rarely match. The connection usually runs through something else:

```
Instagram @alice_98
        │ bio links to
        ▼
     alice.dev
      ╱   │   ╲
     ▼    ▼    ▼
 GitHub Threads Reddit
```

A username search engine answers "does this handle exist elsewhere?", which is
the wrong question — handles are reused by unrelated people all the time.
Omnicient answers a different one: **what publicly observable evidence connects
these entities, and how strong is it?**

That is why the pipeline is split into distinct stages, with the analyst — not
the tool — making the final call:

```
DISCOVERY → ENTITY EXTRACTION → CANDIDATE GENERATION
          → CORRELATION → EVIDENCE → INVESTIGATION GRAPH → ANALYST
```

---

## Features

**Investigation**

- Create an investigation from **one** input — username, email address,
  profile URL or domain — with **no platform to choose**: the identifier type
  is detected and every source that can answer is searched
- Controlled breadth-first crawl of permitted public sources
- Entity extraction, candidate generation and correlation in one run
- Persisted timeline of every crawl event, including source failures
- Re-runnable discovery that preserves analyst decisions
- JSON and CSV export, including analyst decisions and snapshots
- **Identity Intelligence Profile** — an evidence-backed summary of everything
  observed, computed from the graph rather than stored beside it
- **Alias detection** — named, deterministic handle transformations, resistant
  to the `alex`/`alexander` class of false positive
- **Relationship path explorer** — bounded Cypher traversal answering "how are
  these two connected?", ranked deterministically and highlighted in the graph
- **Investigation leads** — deterministic pivots derived from stored evidence,
  banded HIGH / MEDIUM / LOW

**Evidence and correlation**

- Ten evidence types, including negative (contradictory) evidence
- Transparent additive scoring with configurable point values
- Four confidence bands, never presented as probabilities
- Every point traceable to an evidence row with the URL it came from
- "Insufficient evidence" is a first-class, common outcome

**Interface**

- Dark, dense investigation console
- Interactive React Flow graph with zoom, pan, drag, fit, reset layout
- Entity, relationship and evidence panels
- Filters for entity type, relationship type, confidence band and score
- Focus mode (expand/collapse an entity's connections)
- Analyst confirm / reject / undo workflow

**Sources**

- **Six sources that work live**, chosen because their robots.txt permits
  anonymous lookups: GitHub, Keybase, Mastodon, Bluesky, DEV and websites
- Instagram, Reddit, Threads and Facebook adapters, which report their refusal
  rather than working around it
- Platform-aware URL parsing for X, LinkedIn, YouTube and Hacker News —
  discovered as candidate entities before adapters exist for them
- Adapter interface designed so a new platform is one new class

---

## Architecture

```mermaid
flowchart TD
    UI["React Client<br/>graph · panels · filters"]
    API["FastAPI<br/>REST / JSON"]
    CR["Crawler Service<br/>breadth-first, budgeted"]
    CO["Correlation Engine<br/>rule-based scoring"]
    GR["Graph Service<br/>NetworkX layout + stats"]
    DB[("Neo4j<br/>native property graph")]
    SRC["Source Adapters<br/>GitHub · Keybase · Mastodon · Bluesky · DEV · Website<br/>(+ Instagram · Reddit · Threads · Facebook, robots-blocked)"]

    UI -- "REST" --> API
    API --> CR
    API --> CO
    API --> GR
    CR --> SRC
    CR --> DB
    CO --> DB
    GR --> DB
    DB --- E1["(:Account) (:Website) (:Domain)<br/>(:Username) (:Email) (:Organization)"]
    DB --- E2["[:LINKS_TO] [:REFERENCES]<br/>[:POTENTIAL_SAME_IDENTITY] [:CONTRADICTORY]"]
    DB --- E3["(:Evidence)"]
    DB --- E4["(:Snapshot) (:CrawlEvent)"]
```

The investigation pipeline:

```mermaid
flowchart LR
    S["Seed<br/>alice_98"] --> D["Identifier detection<br/>USERNAME · EMAIL · PROFILE_URL · DOMAIN"]
    D --> SD["Source discovery<br/>every adapter that can answer"]
    SD --> L["Adapter lookup"]
    L --> X["Entity extraction<br/>links · handles · emails · orgs"]
    X --> C["Candidate generation<br/>DIRECT · INDIRECT · SIMILARITY"]
    C -->|"depth < MAX_DEPTH"| L
    X --> P["Observed profiles"]
    P --> CORR["Correlation engine"]
    CORR --> EV["Evidence + score + band"]
    EV --> G["Investigation graph"]
    G --> A["Analyst<br/>confirm / reject"]
```

**Separation of concerns.** The crawler *finds* information. The correlation
engine *evaluates* relationships. The graph service *shapes* them for display.
The frontend *renders* them. The analyst *decides*. The frontend never learns
how crawling works — it consumes entities, relationships, evidence and a graph.

---

## Technology stack

| Layer     | Choice                                                              |
| --------- | ------------------------------------------------------------------- |
| Backend   | Python 3.12+, FastAPI, Pydantic v2, Neo4j 5 (official driver)        |
| Crawling  | httpx (async), BeautifulSoup4, lxml                                  |
| Graph     | NetworkX (processing), React Flow (visualisation)                    |
| Frontend  | React 18, TypeScript, Vite, Tailwind CSS v4, `@xyflow/react`         |
| Testing   | pytest, pytest-asyncio, Ruff                                         |

No Kubernetes, Kafka, Redis, Celery, Elasticsearch or microservices. The MVP
is a single API process, one Neo4j instance and a static frontend —
deliberately. The seams that would let those be introduced later are described
under [Future architecture](#future-architecture).

**Why Neo4j.** An investigation *is* a graph, so storing it as one removes a
translation layer: the nodes an analyst sees in the interface are the nodes on
disk. "Which accounts are two hops from this website?" is a query rather than a
join plan, and the relationship types in the data model
(`POTENTIAL_SAME_IDENTITY`, `SHARED_WEBSITE`, `CONTRADICTORY`) are the real
edge types in the database, not rows in a table that describe edges.

---

## Installation

Requirements: **Python 3.12+**, **Node.js 20+**, and a **Neo4j 5** instance.

```bash
git clone <repository>
cd omnicient
```

### Neo4j

The quickest option is the container, which is also what
`docker compose up` runs:

```bash
docker run -d --name omnicient-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/<choose-a-password> \
  neo4j:5.26-community
```

Neo4j Desktop or a package install works equally well; Omnicient only needs a
Bolt endpoint and credentials. The browser at <http://localhost:7474> is useful
for inspecting an investigation graph directly in Cypher.

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt   # runtime deps + pytest and ruff
cp .env.example .env                 # then set NEO4J_PASSWORD
```

`requirements.txt` holds the runtime dependencies alone, pinned exactly, and
is what the Docker image installs; `requirements-dev.txt` pulls those in and
adds the test tooling. The pins are deliberate — the constraints used to be
`>=`, so an image rebuilt a month later resolved whatever was newest that day
and could have taken a major version without a line of this project changing.
To move a pin: bump it, run the suite, commit the new version with the result.

`NEO4J_PASSWORD` is the only value without a working default — no password is
hardcoded anywhere in the repository.

### Frontend

```bash
cd frontend
npm install
```

---

## Running the application

Two terminals:

```bash
# Terminal 1 — API on http://127.0.0.1:8000
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

```bash
# Terminal 2 — interface on http://localhost:5173
cd frontend
npm run dev
```

Open <http://localhost:5173>, enter `@alice_98`, and press **Start
investigation**. Demo mode is on by default, so this works with no network
access and no credentials of any kind.

**Schema setup is automatic.** On startup the API waits for Neo4j (retrying,
since a container is often still recovering), then applies its constraints and
indexes. Every statement is `IF NOT EXISTS`, so it is safe on every boot and
there is no migration step. If Neo4j never answers, the API still starts and
`GET /api/health` reports `status: degraded` with `database.connected: false`
rather than the process dying silently.

### Docker

```bash
cp .env.example .env      # set NEO4J_PASSWORD
docker compose up --build
# interface:     http://localhost:5173
# API docs:      http://localhost:8000/docs
# Neo4j browser: http://localhost:7474
```

Compose starts Neo4j first and holds the backend until Bolt actually answers a
query, so first boot works without a retry.

---

## Environment variables

All are optional except `NEO4J_PASSWORD`; see `backend/.env.example`.

| Variable                            | Default                      | Purpose                                                |
| ----------------------------------- | ---------------------------- | ------------------------------------------------------ |
| `NEO4J_URI`                         | `bolt://localhost:7687`      | Bolt endpoint                                          |
| `NEO4J_USERNAME`                    | `neo4j`                      | Neo4j user                                             |
| `NEO4J_PASSWORD`                    | *(required)*                 | Neo4j password — never hardcoded                       |
| `NEO4J_DATABASE`                    | `neo4j`                      | Target database inside the DBMS                        |
| `NEO4J_STARTUP_TIMEOUT`             | `30`                         | Seconds to wait for Neo4j at boot                      |
| `OMNICIENT_DEMO_MODE`               | `true`                       | Use the offline synthetic dataset                      |
| `OMNICIENT_MAX_DEPTH`               | `2`                          | Maximum crawl depth from the seed                      |
| `OMNICIENT_MAX_PAGES`               | `150`                        | Page budget for one investigation                      |
| `OMNICIENT_CRAWL_CONCURRENCY`       | `10`                         | Sources fetched at once within a crawl level           |
| `OMNICIENT_REQUEST_TIMEOUT`         | `10`                         | Per-request timeout, seconds                           |
| `OMNICIENT_REQUEST_DELAY`           | `1.0`                        | Minimum delay between requests to one host             |
| `OMNICIENT_MAX_RESPONSE_BYTES`      | `2000000`                    | Response size limit                                    |
| `OMNICIENT_MAX_REDIRECTS`           | `3`                          | Redirect hops, each re-validated                       |
| `OMNICIENT_RESPECT_ROBOTS`          | `true`                       | Honour `robots.txt` where available                    |
| `OMNICIENT_ALLOW_PRIVATE_NETWORKS`  | `false`                      | **Disables the SSRF guard.** Isolated test networks only |
| `OMNICIENT_USER_AGENT`              | `Omnicient/0.1 …`            | Identifying User-Agent                                 |
| `OMNICIENT_CORS_ORIGINS`            | `http://localhost:5173,…`    | Allowed browser origins                                |
| `OMNICIENT_LOG_LEVEL`               | `INFO`                       | Log level                                              |

---

## Demo mode

Demo mode is mandatory to the design: Omnicient must demonstrate the entire
pipeline without contacting any external service. It ships a synthetic dataset
built to exercise every class of evidence.

| Entity                        | Role in the demonstration                                   |
| ----------------------------- | ----------------------------------------------------------- |
| Instagram `@alice_98`         | Seed; links to Threads, the website, and a private profile   |
| Threads `@alice_dev`          | Explicitly linked — strongest possible evidence              |
| Website `alice.dev`           | The pivot: links to GitHub, Reddit, Threads, Instagram, Facebook |
| GitHub `@alice-security`      | Same avatar, same website, similar bio → **HIGH**            |
| Reddit `@alice_security`      | Shares the website only → **MEDIUM**                         |
| Facebook `Alice Example`      | Shares the website and display name → **MEDIUM**             |
| Facebook `alice.private`      | Cannot be read publicly → demonstrates graceful failure      |
| X `@alice98`                  | Similar handle, **different website, conflicting location** → contradictory |
| `alice@alice.dev`, `Contoso Labs` | Email and organization pivots                           |

Everything in it is fictional and every entity carries a **`DEMO DATA`** badge
in the interface and a `notice` field in the API. It describes no real person.

Switching demo mode off (per investigation, or with `OMNICIENT_DEMO_MODE=false`)
makes the same pipeline query live public pages. Platforms that require a login
are reported as unavailable rather than worked around.

---

## API documentation

FastAPI publishes interactive OpenAPI docs at <http://localhost:8000/docs>.

| Method   | Path                                        | Purpose                                  |
| -------- | ------------------------------------------- | ---------------------------------------- |
| `GET`    | `/api/health`                               | Status, mode, database, sources, bands   |
| `GET`    | `/api/stats`                                | Dashboard totals across investigations   |
| `POST`   | `/api/investigations`                       | Create (and by default start) one        |
| `GET`    | `/api/investigations`                       | List, newest first                       |
| `GET`    | `/api/investigations/{id}`                  | Detail with timeline and source issues   |
| `DELETE` | `/api/investigations/{id}`                  | Delete an investigation and its data     |
| `POST`   | `/api/investigations/{id}/crawl`            | Run discovery + correlation synchronously |
| `GET`    | `/api/investigations/{id}/entities`         | Entities (optional `?type=`)             |
| `GET`    | `/api/investigations/{id}/relationships`    | Relationships (optional `?min_score=`)   |
| `GET`    | `/api/investigations/{id}/graph`            | Nodes, edges, layout hints, statistics   |
| `GET`    | `/api/investigations/{id}/profile`          | Identity Intelligence Profile            |
| `GET`    | `/api/investigations/{id}/aliases`          | Potential aliases, with transformations  |
| `GET`    | `/api/investigations/{id}/paths`            | Ranked routes between two entities       |
| `GET`    | `/api/investigations/{id}/leads`            | Suggested investigation leads            |
| `GET`    | `/api/investigations/{id}/events`           | Crawl timeline                           |
| `GET`    | `/api/investigations/{id}/activity`         | Alias of `/events` (section 27 wording)  |
| `GET`    | `/api/investigations/{id}/evidence`         | All evidence for the investigation       |
| `GET`    | `/api/investigations/{id}/export`           | Export (`?format=json\|csv`, `?download=true`) |
| `GET`    | `/api/entities/{id}`                        | Entity with snapshot history             |
| `GET`    | `/api/entities/{id}/relationships`          | Relationships touching an entity         |
| `GET`    | `/api/entities/{id}/snapshots`              | Observation history for an entity        |
| `GET`    | `/api/relationships/{id}`                   | Relationship with endpoints and evidence |
| `GET`    | `/api/relationships/{id}/evidence`          | Evidence split into support / contradiction |
| `POST`   | `/api/relationships/{id}/confirm`           | Analyst: evidence reviewed and supportive |
| `POST`   | `/api/relationships/{id}/reject`            | Analyst: false positive                  |
| `POST`   | `/api/relationships/{id}/reset`             | Analyst: undo a decision                 |

### The contract between backend and frontend

The backend hands over an investigation graph; the frontend renders it:

```json
{
  "nodes": [{ "id": "…", "type": "ACCOUNT", "platform": "github", "position": { "x": 0, "y": 220 } }],
  "edges": [{ "id": "…", "source": "…", "target": "…", "confidence_score": 65, "evidence_count": 5 }],
  "stats": { "entities": 11, "relationships": 22, "evidence": 45, "contradictions": 2 }
}
```

---

## Identifier detection

Omnicient asks for one thing, and never for a platform:

```
Start Investigation

[ username, email, profile URL, or domain ]

                              [ Investigate ]
```

`app/utils/identifier.py` classifies whatever arrives. Detection is ordered
most-specific first and refuses to guess:

| Input                                | Detected       | Platform    | Searched                        |
| ------------------------------------ | -------------- | ----------- | ------------------------------- |
| `alice_98`                           | `USERNAME`     | *(none)*    | every account source            |
| `alice@example.com`                  | `EMAIL`        | `email`     | public references to the address |
| `https://github.com/alice-security`  | `PROFILE_URL`  | `github`    | that account, then outward      |
| `alice.dev`                          | `DOMAIN`       | `website`   | the site, then what it links to |
| `https://alice.dev/about`            | `WEBSITE_URL`  | `website`   | that page, then what it links to |
| `not a valid identifier`             | *rejected*     | —           | nothing (HTTP 422)              |

A bare username has **no** platform, and that is the point: the seed becomes a
`(:Username)` pivot node and `discover_sources()` fans out to every registered
account adapter. Each source is *asked*; none is assumed to hold the handle,
and a source that returns nothing leaves no node behind — so the graph shows
where the handle actually exists rather than where it might.

A URL with a non-HTTP scheme (`javascript:`, `file:`, `ftp:`) is rejected
outright rather than falling through to be read as a handle, and a known
platform host whose path is not a profile (`instagram.com/p/XYZ`) is treated as
a website, never as an account.

---

## Investigation canvas

The graph is not a network diagram. Forty entities drawn as forty circles is
a topology picture that tells an analyst nothing at a glance, so the canvas
regroups the same data into an investigation board:

```
                    ┌──────────────────┐
                    │ SOCIAL ACCOUNTS  │
                    │ @alice_98    IG  │
                    │ @alice_dev   TH  │
                    └────────┬─────────┘
                             │ potential same identity
   ┌─────────────┐   ┌───────▼────────┐   ┌──────────────┐
   │ EMAILS      │◄──│   @alice_98    │──►│ WEBSITES     │
   │ alice@…     │   │   SEED ENTITY  │   │ alice.dev    │
   └─────────────┘   └───────┬────────┘   └──────────────┘
                             │
                    ┌────────▼─────────┐
                    │ ORGANIZATIONS    │
                    └──────────────────┘
```

**The card is the unit of comprehension; the row is the unit of interaction.**
Each row carries its own React Flow handle, so a relationship is drawn from
the *entity* it concerns rather than from the box containing it — the curve
between `@alice_98` and `alice.dev` lands on those two rows.

`investigationToMindMap()` does the regrouping in the frontend. **Neo4j is
untouched**: the backend returns the same entities, relationships and evidence
it always did, and every row still carries its real entity id, so selection,
evidence and the analyst workflow work against the true graph.

### The stroke carries the claim

This is where the product philosophy becomes visual. A confirmed association
and an unreviewed inference must not look alike, or the graph quietly turns a
guess into a fact. Two channels carry that, and each carries exactly one thing:

**Colour is the confidence band**, and nothing else — the same scale as
everywhere else in the interface, with rejected, contradicted and
analyst-asserted edges taking their own hues.

**Stroke is who stands behind the line:**

| Treatment | Meaning |
| --- | --- |
| solid, heavier | an analyst reviewed the evidence and agreed, or drew the link themselves |
| solid | read off a page — `LINKS_TO`, `REFERENCES` — where no inference is involved |
| thin, dashed, faint | an inference the tool is proposing, not asserting |
| dashed, red | contradicted, or rejected by an analyst |

Confirming an association deliberately does **not** turn the edge green.
`--color-confirmed` and `--color-band-high` are the same value, so a green edge
would say "an analyst agreed" and "the engine scored this 50–74" in one stroke —
collapsing the exact distinction this interface exists to preserve. Dashed to
solid also survives greyscale, a screenshot and a colourblind reader, none of
which green-on-green does.

Proposals are drawn by default. The canvas is where an analyst reviews what the
crawl found, and it cannot be that while the engine's output is hidden: the
earlier confirm-to-connect behaviour drew **one edge out of sixty-one** on a
real investigation, and put observed links behind the same gate — asking an
analyst to confirm that a page contains a link the crawler read from it.
`hide candidates` collapses the view back to what a person stands behind, which
is the right picture to export or present from.

The key on the canvas is split the same way — colour under *Confidence*,
stroke under *Standing* — and it draws its samples as real SVG lines carrying
the same dash constants the canvas uses, so it cannot drift out of step with
what it describes. It collapses to a single row (the connection count stays
visible), and the choice is remembered per browser: it is a key, not a
control, and once an analyst has learned it they want the corner back.

### Ruling an entity out

A crawl that searches a handle finds everyone who uses it, and some of them
are other people. The analyst can say so: **mark as different identity**
records that an account belongs to a different party — a namesake, a reused
handle, a coincidence the evidence happened to surface.

This is the only identity claim the system stores, and it is stored as what it
is: an analyst's assertion, with their reasoning, timestamped. The engine never
sets it. It is separate from the confirm/reject verdict on a *relationship*,
which rules on whether evidence supports an association between two entities;
this rules on the entity itself.

**It deletes nothing.** The account, its observations, its evidence and its
relationships all survive, and the ruling can be undone — because the analyst
may be wrong, and a later reviewer has to be able to see what was ruled out and
why. On the canvas the card is muted, its border goes dashed red, the handle is
struck through and the confidence band is replaced by `DIFFERENT IDENTITY`: a
band describes how strongly the *engine* associated an entity, and once a
person has said it is not the same party, that number answers a question nobody
is asking. A filter row under **Your rulings** takes them off the canvas for
anyone who wants them out of the way — it appears only once there is something
in it.

The seed cannot be ruled out. It is what the investigation is about rather than
a finding in it, and ruling it out would leave an investigation of nobody with
every other entity still hanging off it. The API returns 409 and the interface
offers no control.

The verdict survives a re-crawl. A re-run re-observes every entity it finds and
overwrites the observed fields; if it overwrote this too, an analyst would have
to rule out the same namesake after every run.

### The layout is a tree

An investigation is a rooted, shallow thing — a starting handle and what was
found from it — and a tree says that directly. The seed sits at the top, each
hop is a level below the one before, and every card hangs from the card it was
reached through, so depth reads down the screen. Each node is centred over its
children, which keeps a branch together as one shape.

Levels are **hop distance from the seed, not crawl depth.** They usually agree,
but a bare handle asks every source about itself at depth zero, so depth alone
would put the seed shoulder to shoulder with the two dozen accounts it found.

Spacing is set from the measured card, which renders about 185x109 — nearly
twice as wide as it is tall. Spacing levels as generously as columns therefore
looked wrong: the gutter came out at 171px down the screen against 55px
across, so the tree read as three times airier vertically than horizontally
for no reason anyone had checked. Both are about 60px now.

The cost of a tree is width: a wide fan-out is a wide row. A crowded level is
therefore stepped alternately up and down, which keeps labels apart and lets
cards sit closer than a dead-straight row allows — and level baselines
accumulate rather than multiply, so a stepped level does not eat the gap below
it. Entities no relationship reaches are parked in a grid underneath the tree
rather than hung off the root, since drawing them as children would assert a
parentage that does not exist.

Edges are routed straight, which suits a tree: a line runs from a parent down
to a child and reads as one stroke. Labels appear on selection, on hover, and
on relationships an analyst should not miss; labelling every edge produces a
wall of text nobody reads.

### Staying legible as it grows

A category holding thirty entities becomes a 900px column that dominates the
board and cannot be read anyway, so cards cap at ten rows with `+N more`, and
rows past the cap anchor their edges to the card. Categories collapse to a
header and a count.

Layout is deterministic: the same investigation always produces the same
board, so *reset layout* returns the analyst to the arrangement they knew.

---

## Analysis layer

Four services read the investigation graph without changing it. None of them
stores a second copy: a profile, an alias list, a route or a lead is always a
statement about the graph's *current* state, and a stored one would go stale
the moment an analyst confirmed something.

### Identity Intelligence Profile

`GET /api/investigations/{id}/profile` aggregates what was observed - platforms,
websites, emails, organizations, locations, timeline, statistics - and every
value names the entities that published it, so the interface can navigate back
to the source. Two rules keep it from becoming an identity claim:

* **Attribution, not assertion.** `alice.dev` is not "the subject's website".
  It is a value that six named entities published, with a count to prove it.
* **Rejected means rejected.** An entity reachable only through relationships
  the analyst rejected stops contributing its attributes, so a discarded false
  positive cannot keep shaping the summary from behind the scenes.

Platform hosts are excluded from "public websites": a profile linking to
`github.com` is an *account*, already shown under platforms.

### Alias detection

`app/services/alias_detection.py` separates two questions that are easy to
conflate:

1. **Which deterministic transformation relates these handles?** Case,
   separator substitution/removal/addition, numeric suffix, a known role
   suffix, a shared root token. A *named* transformation is explainable; a
   distance score is not.
2. **Does anything corroborate it?** Shared website, email, avatar,
   organization or display name - evidence the correlation engine already
   collected, reused rather than recomputed.

Resemblance alone is capped well below the confident bands, so an alias cannot
reach HIGH on spelling. The false-positive gate is explicit: `alex`/`alexander`
and `sam`/`samantha` produce **no** transformation, because a shared prefix is
not one. Aliases are stored as their own `POTENTIAL_ALIAS` edge - a narrower
claim than `POTENTIAL_SAME_IDENTITY`, being about the handles rather than the
people.

### Relationship path explorer

`GET /api/investigations/{id}/paths?source_entity_id=…&target_entity_id=…`
runs a bounded, parameterized traversal (`MAX_DEPTH=5`, `MAX_PATHS=5`, both
configurable and hard-capped) scoped to a single investigation. Ranking is
deterministic and stated openly:

* a rejected step sinks a route outright - the analyst already said no
* fewer contradictions beat more
* shorter beats longer; every hop is another inference
* confirmed steps beat unreviewed ones

Evidence counts toward the score **per hop, not in total** — summing rewards
length, which is how a two-hop detour ends up outranking the direct connection
it detours around. Selecting a route highlights exactly its nodes and edges in
React Flow.

### Investigation leads

`GET /api/investigations/{id}/leads` runs nine deterministic rules over the
stored graph — shared website clusters, repeated emails, shared avatars,
potential aliases, unreviewed strong associations, contradictions needing
review, bridge entities, unresolved candidates and shared organizations — and
bands them HIGH / MEDIUM / LOW from one score with two thresholds.

Leads are *suggestions*, never conclusions, and nothing here starts a new
external search: the analyst stays in control. Unreviewed associations are
summarised rather than enumerated, because one lead per relationship is just
the relationship list again.

---

## Correlation methodology

Correlation runs over the *observed profiles* the crawler collected — never
over raw HTML — and compares every pair of account entities. Each rule that
fires produces one evidence row: a type, a human-readable description, the
value it extracted, the URL it came from, and its point contribution.

```mermaid
flowchart TD
    A["Profile A"] --> R{"Rules"}
    B["Profile B"] --> R
    R --> S1["Explicit link +70"]
    R --> S2["Shared email +40"]
    R --> S3["Same avatar +25"]
    R --> S4["Same website +20"]
    R --> S5["Similar bio +10"]
    R --> S6["Same / similar username +10 / +5"]
    R --> S7["Same display name +5"]
    R --> S8["Shared organization +5"]
    R --> N1["Metadata conflict −20"]
    R --> N2["Conflicting location −15"]
    S1 & S2 & S3 & S4 & S5 & S6 & S7 & S8 & N1 & N2 --> SUM["Sum, clamped to 0–100"]
    SUM --> BAND["Confidence band"]
    BAND --> TYPE["Relationship type"]
```

Design decisions worth knowing:

- **Positive evidence is required.** A pair that only contradicts each other is
  not a relationship and gets no edge; contradictions instead weaken the
  relationships they actually touch.
- **Structural edges are separate.** `LINKS_TO` / `REFERENCES` edges record an
  observed public link (A's bio links to B). Correlation edges
  (`POTENTIAL_SAME_IDENTITY`, `SHARED_WEBSITE`, …) record an inference *about*
  identity. Both can exist between the same pair, and they mean different things.
- **Provenance is preserved.** Every entity records whether it was reached by an
  explicit link (`DIRECT`), through another entity (`INDIRECT`), or generated
  from a handle variant (`SIMILARITY`). A similarity candidate earns nothing by
  existing.
- **Weak signals are labelled weak.** Evidence text for username and display
  name matches says so explicitly, in the analyst's own words, not just numerically.
- **Avatar matching compares perceptual hashes, not URLs.** Every platform
  serves the same photograph from a different address — a signed Instagram CDN
  URL, `avatars.githubusercontent.com/u/1234`, a hash of an email at Gravatar —
  so URL comparison could only ever fire for two accounts on the *same* site,
  which is not the case the rule exists for. Each avatar is reduced to a 64-bit
  difference hash (`backend/app/utils/imagehash.py`) that survives the
  rescaling and re-encoding an upload goes through, and two profiles match when
  the hashes are within 14 bits. Flat images, addresses that name themselves a
  default, and any picture carried by more than four accounts are all refused,
  because a platform's placeholder would otherwise link every account that
  never uploaded a photograph. This deliberately does **not** compare faces:
  two different photographs of the same person will not match, and guessing at
  that is a claim the evidence cannot support.

All point values live in one place, `ScoringConfig` in `backend/app/config.py`.

### Calibration

Every weight above is a number somebody chose. `python -m app.calibration`
turns that into a measurement: it scores 52 labelled pairs drawn from 45 real
public profiles and reports how well the model separates the ones that belong
together from the ones that do not.

The labels come from the accounts themselves — a Gravatar's verified accounts,
a Keybase proof, a website named on a profile — because a connection the owner
published is the strongest ground truth public data offers. Which creates an
obvious circularity: if the label comes from an explicit link and the model
scores explicit links at seventy, the run mostly measures whether it can read a
link it was handed. So the harness runs **twice**, and the second pass drops
`EXPLICIT_LINK` entirely and asks whether the remaining signals could have
recovered a connection we know is real. That blind number is the one worth
quoting:

```
  WITHOUT the declared link (can the model infer it?)
  22 pairs known same, 30 known different
  mean score: 21.6 when same, 1.3 when different

    evidence type              fires on same  on different
    SAME_DISPLAY_NAME                    14             0
    SAME_AVATAR                           7             0
    SAME_WEBSITE                          7             1
    SAME_USERNAME                         7             4
    SIMILAR_BIO                           4             0
    CONTRADICTORY_ATTRIBUTE               2             8
```

The most valuable pairs are the ones where **neither profile links to the
other** — `github:simonw` and `bluesky:simonwillison.net`, or `github:ornicar`
and `lichess:thibault`, whose handles share nothing at all. Both are tied
together by a chain of declarations that passes through a third page, so the
model cannot read the answer anywhere; it has to recover it from a name, a
photograph, a biography. A dataset of directly declared pairs alone cannot test
that, which is why `capture.py` reports implied pairs separately.

That last column is the actionable one, and it found two real faults the first
time it was read:

- **The avatar threshold matched nothing.** It was set to 6 bits by guess. The
  same photograph across platforms actually sits 7–12 bits apart, so the rule
  written to catch re-encoded copies could not fire on a single true pair — the
  very bug it existed to fix. Raised to 14, measured.
- **The website contradiction was backwards.** "These profiles publish
  different websites" fired on three known-same pairs and two known-different
  ones — it was subtracting twenty points from the pairs it should have
  supported. One person listing their blog on GitHub and their shop on
  Instagram is ordinary, not a conflict. Removing it took F1 from 0.67 to 0.93.

Both findings were invisible to the test suite, which could only confirm that
the rules did what they were written to do, not whether what they were written
to do was right.

**Two things the run is careful to be honest about.**

Six known-same pairs score **zero** blind, and they are counted as misses in
the headline number. Every one ties an account to its owner's personal
website — which has no username, no avatar and no display name — so the
declaration was not merely the best evidence available but the only evidence
that could ever have existed. Excluding those, the account-to-account pairs
average 29.7 against 1.3 for strangers. Both figures are printed, and a test
(`test_the_uninferable_pairs_are_exactly_the_website_ones`) fails if that
exclusion ever grows to cover a pair of *accounts*, which would mean the model
had quietly stopped observing something.

The one remaining false positive is worth naming rather than fixing by feel: an
Automattic employee and the WordPress brand account score 20 for publishing the
same website, `wordpress.com`. A shared *personal* domain is strong evidence and
a shared *employer* domain is close to none, which is the same distinction the
avatar rule already makes when it ignores a picture carried by many accounts.
One counter-example is not enough to fit a rule to, so it is recorded here and
left alone — tuning a weight against a single pair is what this harness exists
to replace.

### Extending the dataset

```bash
python -m calibration.capture fetch github:simonw bluesky:simonwillison.net
python -m calibration.capture suggest
```

`fetch` runs the project's own adapters, so a captured profile is exactly what
a crawl would have seen, avatar hash included. `suggest` then reads the
captured profiles and reports where one declares another — and, separately, the
pairs implied by a chain of declarations. It proposes; a human disposes. Nothing
is written into the labelled set without review, because a mislabelled pair is
worse than a missing one: it teaches the calibration the wrong thing and every
measurement downstream inherits it.

The tool's first version got this wrong in an instructive way. It treated any
shared URL as a declaration, and promptly matched two Automattic employees
through `wordpress.com`. A shared employer is a link both profiles publish and
neither one asserts, so a declaration now has to point at the other profile
itself.

Negative pairs cannot be discovered this way — nobody publishes a list of
people they are not — so they are chosen by hand, and the useful ones are
hard: `github:ben` (Ben Straub, Portland) against `devto:ben` (Ben Halpern, New
York); `github:hikaru` (Hikaru Maeshiro) against `chess:hikaru` (the
grandmaster Hikaru Nakamura), where the stranger really is a chess player.

Profiles live in `backend/calibration/profiles.json` and the labelled pairs
reference them by key, so one profile can appear in many pairs without being
copied into each. The regression tests in `backend/tests/test_calibration.py`
hold the floor.

---

## Confidence scoring

| Score    | Band          |
| -------- | ------------- |
| 0–19     | `LOW`         |
| 20–49    | `MEDIUM`      |
| 50–74    | `HIGH`        |
| 75–100   | `VERY HIGH`   |
| no evidence | `INSUFFICIENT` |

**These are not probabilities.** A score of 72 means "the evidence found adds
up to 72 points under the current model" — not "72% likely to be the same
person". The interface always shows the band, the score and the reasons
together, for example:

```
Instagram @alice_98  ↕  GitHub @alice-security
Potential Same Identity · Confidence HIGH · Score 65

Supporting evidence
  ✓ SAME_AVATAR          +25  Both profiles use the same public avatar image
  ✓ SAME_WEBSITE         +20  Both profiles publish the same external website: alice.dev
  ✓ SIMILAR_BIO          +10  Public biographies use substantially the same wording
  ✓ SAME_DISPLAY_NAME     +5  Same public display name ('Alice R.') — weak, many people share a name
  ✓ SHARED_ORGANIZATION   +5  Both profiles reference the organization 'contoso labs'

Contradictions
  None

Analyst status: UNREVIEWED   [Confirm] [Reject]
```

`CONFIRMED` means **an analyst reviewed the evidence and judged it supportive**.
It never asserts real-world identity certainty, and the wording in the UI, the
API and the export all say so.

---

## Crawler behaviour and limitations

The crawler is breadth-first and bounded in every direction: depth
(`MAX_DEPTH=2`), pages (`MAX_PAGES=150`), per-request timeout, response size,
redirect hops, and a polite per-host delay.

Each level is fetched **concurrently** — a fan-out across two dozen different
hosts has no reason to be sequential — and the results are then folded in
*in candidate order*, so what a run produces never depends on which host
answered first. Politeness is unaffected: the delay is held per host, so
repeat requests to any single service are still spaced. Measured on a bare
username against 23 live sources, this took a complete crawl from 93s to 23s. It follows only URLs discovered
during the investigation, de-duplicates entities by `(type, platform,
identifier)`, and honours `robots.txt` where it is available.

### Which sources work live, and why

Measured, not assumed — each platform's robots.txt was checked against
Omnicient's user agent, and every permitted endpoint was then probed:

**24 adapters across six categories**, every one checked against its
robots.txt before it was written:

| Category | Sources |
| --- | --- |
| **Developer** | GitHub, DEV, Hacker News, Hugging Face, Stack Overflow, crates.io, Docker Hub, Launchpad |
| **Social** | Mastodon, Bluesky, Telegram, Medium (+ Instagram, Reddit, Threads, Facebook below) |
| **Gaming** | Steam |
| **Music** | SoundCloud, Last.fm |
| **Learning** | Codewars, Scratch, Duolingo |
| **Identity** | Keybase |
| **Web** | any site, robots permitting |

Adapters declare a `SourceCategory`, so `/api/health` reports coverage grouped
rather than as a flat list of two dozen platform names.

| Source | Live? | Endpoint |
| --- | --- | --- |
| GitHub | ✅ | `api.github.com/users/{u}` — documented, anonymous |
| Keybase | ✅ | `keybase.io/_/api/1.0/user/lookup.json` — verified proofs |
| Mastodon | ✅ | `/api/v1/accounts/lookup` on an allow-listed instance |
| Bluesky | ✅ | `public.api.bsky.app` AT Protocol appview |
| DEV | ✅ | `dev.to/api/users/by_username` |
| Hacker News | ✅ | `hacker-news.firebaseio.com/v0/user/{u}.json` |
| Hugging Face | ✅ | `huggingface.co/api/users/{u}/overview` |
| Stack Overflow | ✅ | Stack Exchange API — searched by display name |
| crates.io | ✅ | `crates.io/api/v1/users/{u}` — GitHub-backed |
| Docker Hub | ✅ | `hub.docker.com/v2/users/{u}/` |
| Launchpad | ✅ | `api.launchpad.net/1.0/~{u}` |
| Steam | ✅ | `steamcommunity.com/id/{u}/?xml=1` |
| SoundCloud / Last.fm | ✅ | Open Graph card on the profile page |
| Codewars / Scratch / Duolingo | ✅ | documented public JSON |
| Telegram / Medium | ✅ | Open Graph card |
| Websites | ✅ | the page itself, robots permitting |
| Instagram | robots off | `Disallow: /`, but the public profile parses |
| Facebook | robots off | `Disallow: /`, but public pages parse |
| Threads | robots off | `Disallow: /`, but the public profile parses |
| Reddit | ❌ | `Disallow: /` — and HTTP 403 to non-browser clients |
| GitLab, Codeberg, Gitee, Gravatar, Lobsters | ❌ | `Disallow:` on the API path |
| Speedrun, Chess.com, Lichess, HackerRank | ❌ | `Disallow:` — gaming and learning |
| Genius, MusicBrainz, Mixcloud | ❌ | `Disallow:` — music |
| Pinterest, Flickr, Patreon, Linktree | ❌ | `Disallow:` — social |
| LeetCode, Exercism, NameMC | ❌ | HTTP 403 to non-browser clients |

**"robots off"** means the source is reachable only when the operator sets
`OMNICIENT_RESPECT_ROBOTS=false`. Nothing else changes: Omnicient still sends
its own identifying user agent, keeps the per-host delay and the crawl budget,
and does not impersonate a browser's TLS fingerprint, rotate user agents or
proxies, or call private endpoints. robots.txt is an advisory protocol, so
whether to consult it is the operator's call — but these platforms' terms of
service restrict automated collection independently of it, and that judgement
is the operator's too. Reddit is unreachable either way: it answers a
non-browser client with HTTP 403.

The interface shows `robots: ignored` on the dashboard whenever the setting is
off, so an analyst always knows which policy produced the graph they are
reading.

**Keybase is the strongest legitimate pivot in the set.** Its entire purpose is
publishing *verified* links between one person's accounts: the user signs a
statement on each platform and Keybase checks it. One lookup of `keybase/chris`
yields X, GitHub, Reddit and Hacker News handles plus a personal domain — as
`EXPLICIT_LINK` evidence (+70), because the account holder demonstrably
controlled both ends. Omnicient still does not *claim* the identity on that
basis: a proof shows control of accounts, not who the human is, and it can be
stale.

### Instagram, Threads and Facebook cannot be crawled live

This is worth stating up front, because it is the first thing you will hit.
All three publish the same rule:

```
# instagram.com/robots.txt, facebook.com/robots.txt, threads.com/robots.txt
User-agent: *
Disallow: /
```

Omnicient honours `robots.txt`, so a live investigation seeded with an
Instagram handle stops immediately with:

```
instagram:<handle> could not be read: robots.txt at https://instagram.com disallows this path
```

That is the tool working as designed, not a failure. The options are:

1. **Demo mode** (the default) — the full pipeline, offline, on synthetic data.
2. **Seed a domain instead** — just type `alice.dev`; the identifier detector
   does the rest. Personal sites usually permit crawling, and a personal site
   is the strongest pivot in a public-source investigation anyway: it is where
   people list their own accounts. This path works live today and yields
   GitHub, Reddit, X, LinkedIn, Mastodon and Threads accounts, emails and
   organizations.
3. **Seed a GitHub or Reddit handle** — both adapters read the documented
   public JSON those platforms publish for anonymous readers, so they work live
   without any of the problems above.
4. `OMNICIENT_RESPECT_ROBOTS=false` — the operator's call, and their
   responsibility. Be clear about what this does and does not buy you. Measured
   against the live sources:

   | Source | robots respected | robots disabled |
   | --- | --- | --- |
   | GitHub | works | works (robots permits it) |
   | Website | works | works |
   | Instagram | `ROBOTS_DISALLOWED` | a *prominent* public profile parsed |
   | Reddit | `ROBOTS_DISALLOWED` | `BLOCKED` (HTTP 403) |

   So disabling robots does not reliably unlock these platforms. Reddit refuses
   a non-browser client outright, and Instagram's terms separately prohibit
   automated collection whatever robots.txt says. Getting consistently past
   either needs TLS-fingerprint impersonation, rotating user agents, proxy pools
   or undocumented private endpoints — every one of which is out of scope by
   design (section 5). Omnicient reports the refusal and moves on.

**Other known limitations, stated plainly:**

- Only the first page of a website is fetched, and only links to *other* hosts
  become new entities — a site's own internal pages are not identities.
- X, LinkedIn, YouTube and Mastodon are *recognised* (their URLs parse into
  platform + identifier) but have no adapter yet, so they appear as unresolved
  candidate entities in live mode.
- GitHub and Reddit rate limit anonymous clients. Omnicient reports the limit
  and moves on rather than working around it, so a large live investigation may
  see `RATE_LIMITED` on those sources.
- Avatar comparison is URL-based (see above).
- Organization extraction is conservative and worth few points by design.
- A failing source never fails an investigation: the reason is recorded in the
  timeline, surfaced in the sidebar, and the run completes with what it has.

---

## Security protections

Omnicient fetches URLs found inside untrusted content, which makes the crawler
a request-forgery primitive unless it is constrained. It is constrained:

- **SSRF guard** on the initial URL *and every redirect hop*: only `http(s)`,
  no embedded credentials, and hostnames rejected when they are `localhost`,
  `*.local` / `*.internal`, or resolve to loopback, RFC1918, link-local,
  multicast, reserved or cloud-metadata addresses (`169.254.169.254` and
  friends). Every address a hostname resolves to is checked, not just the first.
- **Response size limits** enforced while streaming, so an oversized body is
  abandoned rather than buffered.
- **Timeouts, redirect caps, depth caps and page budgets** on every crawl.
- **Input validation** on seed identifiers and platform names before anything
  is queried.
- **Safe HTML parsing** with lxml through BeautifulSoup; parse failures become
  structured errors instead of exceptions.
- **Structured logging** with automatic redaction of any field whose name looks
  like a credential. Omnicient handles no passwords, tokens, cookies or
  sessions at all.
- **Uniqueness enforced by the database.** Neo4j constraints make an entity
  unique per `(investigation, type, platform, identifier)`, so de-duplication
  cannot drift from what the crawler assumes.
- **No Cypher injection.** Every query is parameterized. The two places Cypher
  cannot take a parameter — node labels and relationship types — are resolved
  through fixed allow-lists derived from the enums.

Tests cover the SSRF guard, the redirect re-validation path and the size limit.

---

## Ethical and legal considerations

Omnicient is intended for:

- authorized OSINT
- cybersecurity research
- academic research
- threat intelligence
- defensive investigations
- digital footprint analysis

Omnicient **does not and will not** implement authentication or authentication
bypass, private-account access, credential harvesting, CAPTCHA bypass,
rate-limit evasion, cookie or session reuse, session hijacking, unauthorized
API access, private-information extraction, or unrestricted mass scraping.
These are not missing features; excluding them is a design commitment.

The tool reports *potential associations* from public data. Attributing a
digital identity to a real person is a consequential act with real
consequences for that person. Omnicient deliberately stops short of it, shows
its evidence, and leaves the judgement — and the responsibility — with the
analyst. Users are responsible for complying with applicable law, platform
terms and data-protection regulation.

---

## Project structure

```
omnicient/
├── backend/
│   ├── app/
│   │   ├── main.py             FastAPI application, CORS, error handlers
│   │   ├── config.py           Settings + ScoringConfig (all point values)
│   │   ├── database.py         Neo4j driver, constraints, indexes
│   │   ├── repository.py       All Cypher: the only module that queries
│   │   ├── demo_data.py        Synthetic dataset and offline adapters
│   │   ├── api/                health, investigations, entities,
│   │   │                       relationships, evidence
│   │   ├── models/             Domain records (plain dataclasses) + enums
│   │   ├── schemas/            Pydantic request/response contract
│   │   │                       (+ profile, alias, path, lead)
│   │   ├── services/           crawler, discovery, correlation,
│   │   │                       alias_detection, identity_profile, paths,
│   │   │                       leads, graph, investigation (orchestration)
│   │   ├── sources/            base + per-platform adapters (github,
│   │   │                       keybase, mastodon, bluesky, devto, website,
│   │   │                       instagram, reddit, threads, facebook) and
│   │   │                       category modules (dev, gaming, music,
│   │   │                       learning, social)
│   │   └── utils/              identifier, normalization, url_parser,
│   │                           validation, logging
│   ├── tests/                  identifier, normalization, url_parser,
│   │                           correlation, alias_detection,
│   │                           identity_profile, paths, leads, graph,
│   │                           sources, api
│   ├── requirements.txt        # runtime, pinned — what Docker installs
│   ├── requirements-dev.txt    # the above plus pytest and ruff
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/         EntityPanel,
│   │   │                       RelationshipPanel, EvidencePanel, Sidebar,
│   │   │                       Filters, SearchBar, ActivityLog,
│   │   │                       IdentityProfilePanel, LeadsPanel,
│   │   │                       PathExplorer, InvestigationHeader
│   │   ├── components/graph/   InvestigationCanvas, SeedNode,
│   │   │                       CategoryGroupNode, CategoryItem,
│   │   │                       RelationshipEdge, GraphToolbar,
│   │   │                       GraphSearch, GraphLegend, ContextMenu
│   │   │   └── layout/         mindMapLayout, radialLayout
│   │   ├── pages/              Dashboard, Investigation
│   │   ├── api/client.ts       Typed REST client
│   │   ├── types/index.ts      The API contract in TypeScript
│   │   └── lib/display.ts      Shared presentation vocabulary
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml
├── README.md
└── LICENSE
```

### Data model

Everything is a node or a relationship in Neo4j:

```
(:Investigation)-[:DISCOVERED]->(:Entity:Account|Website|Domain|Username|Email|Organization)
(:Entity)-[:LINKS_TO|REFERENCES|SHARED_WEBSITE|
           POTENTIAL_SAME_IDENTITY|CONTRADICTORY|...]->(:Entity)
(:Entity)-[:HAS_SNAPSHOT]->(:Snapshot)
(:Investigation)-[:COLLECTED]->(:Evidence)-[:CONCERNS]->(:Entity)
(:Investigation)-[:LOGGED]->(:CrawlEvent)
```

Each entity carries the shared `:Entity` label *and* one for its type, so
`MATCH (a:Account)` works exactly as the data model describes while uniform
traversals stay simple.

**Where evidence lives.** A scored association is a native Neo4j relationship —
that is the whole point of using a graph database. But a Neo4j relationship
cannot itself be the endpoint of another relationship, so the `SUPPORTED_BY`
edge in the conceptual model is realised as an `(:Evidence)` node carrying the
`relationship_id` of the edge it explains, indexed for exactly that lookup.
Every observation behind a score is one indexed query away, and the graph stays
traversable.

Useful queries once an investigation has run:

```cypher
// Every association an analyst confirmed, strongest first
MATCH (a:Entity)-[r:POTENTIAL_SAME_IDENTITY]->(b:Entity)
WHERE r.analyst_status = 'CONFIRMED'
RETURN a.name, b.name, r.confidence_score, r.confidence_level
ORDER BY r.confidence_score DESC;

// The evidence behind one relationship
MATCH (v:Evidence {relationship_id: $id})
RETURN v.type, v.description, v.weight, v.supports, v.source_url
ORDER BY v.weight DESC;

// Accounts reachable from a website, two hops out
MATCH (w:Website {identifier: 'alice.dev'})-[*1..2]-(a:Account)
RETURN DISTINCT a.platform, a.identifier;
```

Entity types: `ACCOUNT`, `WEBSITE`, `DOMAIN`, `USERNAME`, `EMAIL`, `PERSON`,
`ORGANIZATION`. Relationship types: `LINKS_TO`, `REFERENCES`, `USES_USERNAME`,
`SHARED_WEBSITE`, `SHARED_EMAIL`, `SHARED_AVATAR`, `SHARED_ATTRIBUTE`,
`POTENTIAL_SAME_IDENTITY`, `POTENTIAL_ALIAS`, `CONTRADICTORY`. Evidence types: `EXPLICIT_LINK`,
`SAME_WEBSITE`, `SAME_USERNAME`, `SIMILAR_USERNAME`, `SAME_DISPLAY_NAME`,
`SAME_AVATAR`, `SIMILAR_BIO`, `SHARED_EMAIL`, `SHARED_ORGANIZATION`,
`CONTRADICTORY_ATTRIBUTE`, `USERNAME_TRANSFORMATION`, `SHARED_ROOT_TOKEN`.

Every evidence item carries its full provenance — what was observed
(`extracted_value`), the comparison form that actually matched
(`normalized_value`), where (`source_url`, `source_entity_id`), when
(`collected_at`), which entities it connects, and what it did to the score
(`weight`, `stance`). `stance` is `SUPPORTING`, `CONTRADICTORY` or `NEUTRAL`;
neutral covers observations that are recorded provenance but move no score,
such as an alias transformation.

A **snapshot** is written every time an entity is observed. The MVP only stores
them; keeping the history from day one is what makes temporal analysis
possible later without a migration.

---

## Testing

```bash
cd backend
source .venv/bin/activate
./scripts/scratch-neo4j.sh start                  # a throwaway database
NEO4J_TEST_URI=bolt://localhost:7688 pytest       # 519 tests
ruff check .                                      # lint
```

```bash
cd frontend
npm run typecheck
npm run build
```

The suite covers identifier detection (usernames, emails, profile URLs,
domains, invalid input and rejected URL schemes), normalization, URL parsing
across nine platforms plus the SSRF guard, every correlation rule including
contradictions and the no-evidence case, the source adapters against recorded
payloads, entity and relationship de-duplication, evidence attachment, snapshot
writing, graph layout determinism, preservation of analyst decisions across a
re-crawl, and the full API contract — creation, crawling, graph retrieval,
evidence, confirm/reject and export.

No test touches the network. The persistence and API tests need Neo4j and are
**skipped with an explanatory message** when none is reachable, so the
pure-logic tests still run for a contributor without a database:

```bash
NEO4J_TEST_URI=bolt://localhost:7688 NEO4J_TEST_PASSWORD=… pytest
```

### Why the suite needs its own database

The database those point at is **wiped** at the start of the session — the
persistence tests start from an empty graph, so the first thing they do is
`MATCH (n) DETACH DELETE n`.

Neo4j Community serves exactly one database per instance, so with
`NEO4J_TEST_URI` unset the tests fall through to the application's own
connection settings and land on precisely the graph the application is using.
That destroyed real investigations several times during development, which is
not a mistake worth relying on discipline to avoid. So the suite now refuses:

```
Refusing to wipe the database at bolt://localhost:7687 (database neo4j).

It holds 1 investigation(s) and 137 node(s) that this suite did not create,
and the first thing the suite does is `MATCH (n) DETACH DELETE n`.
```

An empty graph is always safe and runs without ceremony. A graph with data in
it runs only when the caller has named a test target — `NEO4J_TEST_URI` or
`NEO4J_TEST_DATABASE` — or set `OMNICIENT_TEST_WIPE_ANYWAY=1` to say the data
is disposable.

Two ways to get a scratch instance:

```bash
docker compose --profile test up -d neo4j-test    # if you run Neo4j in Docker
./scripts/scratch-neo4j.sh start                  # if you run it from a tarball
```

Both listen on **7688** and hold nothing but test fixtures.

---

## Working in a two-person team

The API contract is the seam, so the two halves can be built independently.

| Developer 1 — OSINT / backend                            | Developer 2 — interface                                   |
| -------------------------------------------------------- | --------------------------------------------------------- |
| `app/sources/`, `services/crawler.py`, `discovery.py`     | `frontend/src/components/`, `pages/`                       |
| `services/correlation.py`, `utils/normalization.py`       | React Flow graph, entity/relationship/evidence panels       |
| `models/`, `repository.py`, `api/`, backend tests          | filters, analyst workflow, dashboard                        |
| *Owns: discovery, extraction, correlation, evidence*      | *Owns: investigation interface and analyst experience*      |

The frontend never needs to know how crawling works: it receives
`{ entities, relationships, evidence }` and a laid-out graph. `frontend/src/types/index.ts`
mirrors the backend schemas and is the document both sides agree on.

---

## Future architecture

None of the following is implemented — the MVP is deliberately small — but the
code is shaped so each can be added without a rewrite.

**More sources.** A new platform is one class:

```python
class GitHubAdapter(SourceAdapter):
    platform = "github"

    async def lookup(self, identifier: str) -> LookupResult:
        ...
```

Register it in `ADAPTER_CLASSES` and the crawler, correlation engine and API
are untouched. URL parsing for GitHub, Reddit, X, LinkedIn, YouTube and
Mastodon already exists, so those entities are discovered today and simply
become resolvable when an adapter appears.

**Retrieval-augmented investigation assistant.**

```mermaid
flowchart LR
    DB[("Investigation database")] --> G["Graph store"]
    DB --> V["Vector store"]
    G --> RAG["Retrieval"]
    V --> RAG
    RAG --> LLM["LLM"]
    LLM --> ASSIST["Investigation assistant"]
```

The evidence model is already flat, self-describing and individually
addressable — each row carries its type, description, extracted value, source
URL and timestamp — which is exactly what a retrieval layer needs to answer
"why are these two accounts connected?" or "what changed since the first
observation?". An assistant would **retrieve and summarise stored evidence**;
it must never independently determine identity.

**Machine learning.** `CorrelationEngine` is isolated behind a small interface
and its weights live in a configuration object, so rule-based scoring can be
replaced by probabilistic entity resolution or a learned ranker while the
evidence model, API and interface stay as they are. Confirmed and rejected
relationships accumulate as labelled training data from day one.

**Scale.** In-process services are the MVP's deliberate choice. The seams for
growth are already there: `Neo4jRepository` is the only module that touches the
database, so query tuning, read replicas or a caching layer land in one file,
and `InvestigationService.run` can move behind a task queue — none of which
changes the REST contract the frontend depends on.

**Graph analytics.** Storing the investigation as a real graph means shortest
path, centrality, community detection and bridge-entity analysis are Cypher
queries against data that already exists, rather than features needing a new
store first.

**Export formats.** JSON (the complete record — entities, relationships,
evidence, snapshots, analyst decisions and timeline) and CSV (one row per
relationship, with its supporting and contradicting evidence) are implemented.
The bundle is intentionally flat so HTML/PDF reporting and STIX can be
generated from it without re-querying.

---

## License

MIT — see [LICENSE](LICENSE), which also states the intended-use restrictions.

---

<div align="center">

**Omnicient** — *Don't claim the identity. Show the evidence.*

</div>
