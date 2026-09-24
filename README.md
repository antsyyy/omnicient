# Omnicient

**Trace public identities. Follow the evidence.**

Omnicient starts from a single public identifier — a username, an email address, a profile link or a domain — and maps what else on the public web appears to belong to the same person. A matching handle on another site proves very little, since people reuse names constantly; what genuinely ties accounts together is usually what people published themselves, like a link in a bio, a personal page listing their profiles, or the same photograph used in several places. Omnicient follows those trails, scores what it finds, and shows the evidence behind every connection. It never claims two accounts belong to the same person — that judgement is left to the analyst.

## Features

- **One input, no platform picker** — type a handle, email, link or domain and every relevant source is asked
- **36 public sources** — GitHub, Mastodon, Bluesky, YouTube, Keybase, Linktree and more
- **Evidence, not verdicts** — every connection lists what was observed and the page it came from
- **Explainable scoring** — simple weighted rules, measured against labelled real-world pairs
- **Avatar matching** — recognises the same profile photo across platforms
- **Graph view** — the investigation laid out as a tree from the starting identifier
- **Analyst review** — confirm or reject connections, rule out namesakes, draw links by hand; nothing is ever deleted
- **Export** — JSON and CSV

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | React, TypeScript, Vite, React Flow, Tailwind CSS |
| Backend | Python, FastAPI, httpx, BeautifulSoup |
| Database | Neo4j 5 |
| Deployment | Docker Compose |

## Quick start

### With Docker

```bash
cp .env.example .env        # set NEO4J_PASSWORD
docker compose up --build -d
```

Open **http://localhost:5173**. API docs are at http://localhost:8000/docs.

### Without Docker

Requires Python 3.12+, Node 22+ and Neo4j 5 running on `localhost:7687`.

```bash
# backend
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
NEO4J_PASSWORD=yourpassword uvicorn app.main:app --reload

# frontend (second terminal)
cd frontend
npm install
npm run dev
```

## Configuration

Set through environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEO4J_PASSWORD` | — | Database password (required) |
| `OMNICIENT_DEMO_MODE` | `true` (`false` in Docker Compose) | `true` uses a built-in synthetic dataset instead of live sources |
| `OMNICIENT_MAX_DEPTH` | `2` | How many hops to follow from the starting identifier |
| `OMNICIENT_MAX_PAGES` | `150` | Page budget per investigation |
| `OMNICIENT_REQUEST_DELAY` | `1.0` | Seconds between requests to the same site |
| `OMNICIENT_RESPECT_ROBOTS` | `false` | Whether to consult each site's robots.txt |

## Tests

The test suite needs its own Neo4j instance — it wipes the database it runs against, and refuses to run on one holding real investigations.

```bash
cd backend
bash scripts/scratch-neo4j.sh start
NEO4J_TEST_URI=bolt://localhost:7688 pytest
```

## Project structure

```
backend/     FastAPI app — crawler, source adapters, scoring, Neo4j access
frontend/    React app — search, results list, graph, evidence panels
docker-compose.yml
```

## License

MIT — see [LICENSE](LICENSE).

---

> **For educational purposes only.** Omnicient was built as a university capstone project to study how public-data identity correlation works. It reads only publicly available information and never asserts that accounts belong to the same person. Use it responsibly, lawfully, and only on subjects you are authorised to investigate — such as your own digital footprint.
