# After Hours

A UK political transparency platform that aggregates data from Parliament, Companies House, and Local Councils to detect conflicts of interest and the revolving door between public office and private business.

Built on a feasibility study for linking the Register of Members' Financial Interests to corporate officer records using probabilistic entity resolution, with human-in-the-loop compliance safeguards.

## Prerequisites

> **Windows** is the primary development platform. All instructions below use PowerShell.
> macOS/Linux alternatives are noted where commands differ.

| Dependency | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Runtime ([python.org/downloads](https://www.python.org/downloads/) -- tick "Add to PATH" during install) |
| Neo4j | 5.x | Graph database for the Political Graph ([neo4j.com/download](https://neo4j.com/download/)) |
| DuckDB | (bundled) | Embedded analytical database, no install needed |
| Git | latest | Source control ([git-scm.com](https://git-scm.com/)) |
| API keys | See below | Companies House, Google Gemini |

**API keys you will need:**

- **Companies House** -- register at [developer.company-information.service.gov.uk](https://developer.company-information.service.gov.uk/) for both a REST API key and a Streaming API key.
- **Google Gemini** -- get an API key from [aistudio.google.com](https://aistudio.google.com/).
- **Parliament API** -- no key required; the Members API is open.

## Quick Start (Windows)

All commands use **PowerShell**. A macOS/Linux alternative is noted where it differs.

```powershell
# 1. Clone and enter the repo
git clone <repo-url>
cd afterhours

# 2. Create a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy the environment template and fill in your keys
Copy-Item .env.example .env
# macOS/Linux: cp .env.example .env
# Then edit .env with your API keys and Neo4j credentials

# 5. Set PYTHONPATH so Python can find the afterhours package
$env:PYTHONPATH = "src"
# macOS/Linux: export PYTHONPATH=src

# 6. Initialise the DuckDB schema
python manage.py init-db

# 7. Initialise Neo4j constraints (requires a running Neo4j instance)
python manage.py init-neo4j

# 8. Start the API server
python manage.py serve
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

## Configuration

All settings are loaded from environment variables (or a `.env` file). See `.env.example` for the full list:

| Variable | Default | Description |
|---|---|---|
| `PARLIAMENT_API_BASE_URL` | `https://members-api.parliament.uk/api` | Parliament Members API base |
| `COMPANIES_HOUSE_API_KEY` | -- | REST API key |
| `COMPANIES_HOUSE_STREAM_KEY` | -- | Streaming API key |
| `GEMINI_API_KEY` | -- | Google Gemini API key |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | -- | Neo4j password |
| `DUCKDB_PATH` | `data/afterhours.duckdb` | Path to DuckDB file |
| `RISK_SCORE_REVIEW_THRESHOLD` | `70` | Score at or above which links require human review |
| `AUTO_APPROVE_BELOW` | `30` | Score below which links are auto-approved |

## Usage

All pipelines are accessible through `manage.py`. **Stop the API server before running pipelines** (DuckDB only allows one process at a time).

```powershell
python manage.py <command> [options]
```

| Command | Description |
|---|---|
| `init-db` | Create/reset the DuckDB schema |
| `init-neo4j` | Create Neo4j constraints and indexes |
| `ingest-parliament` | Fetch all MPs, Lords, and financial interests |
| `ingest-company <NUMBER>` | Fetch a company profile and officers |
| `ingest-procurement <FILE>` | Ingest an OCDS JSON file |
| `extract-pdf <FILE>` | Extract council data from a PDF via Gemini |
| `resolve` | Run Splink entity resolution |
| `sync-graph` | Push approved links to Neo4j |
| `serve [--host HOST] [--port PORT]` | Start the API server |

### Step 1 -- Ingest Parliament Data

Pull current MPs, Lords, and their registered financial interests into DuckDB:

```powershell
python manage.py ingest-parliament
```

### Step 2 -- Ingest Companies House Data

Pull company profiles and officer lists for companies of interest (requires `COMPANIES_HOUSE_API_KEY` in `.env`):

```powershell
python manage.py ingest-company 00000006
```

To listen for real-time filings via the Streaming API, use the Python API directly:

```python
import asyncio
from afterhours.ingestion.ingest_companies_house import stream_filings

async def watch_filings():
    async for event in stream_filings():
        print(event["resource_uri"], event.get("event", {}).get("type"))

asyncio.run(watch_filings())
```

### Step 3 -- Ingest Procurement Data (OCDS)

Parse Open Contracting Data Standard JSON files (e.g. from Find a Tender):

```powershell
python manage.py ingest-procurement data/raw/procurement/tender_2025.json
```

### Step 4 -- Extract Council Meeting Data from PDFs

Process council minutes PDFs through the Gemini 2.0 Flash vision pipeline (requires `GEMINI_API_KEY` in `.env`):

```powershell
python manage.py extract-pdf data/raw/council_pdfs/minutes_2025_03.pdf
```

The pipeline:
1. Renders each PDF page to a PNG image (via PyMuPDF).
2. Sends each image to Gemini 2.0 Flash with a structured-output prompt.
3. Validates the JSON response against a strict schema (councillor name, vote direction, planning decision).
4. Only inserts records that pass validation.

### Step 5 -- Run Entity Resolution

Match Parliament members against Companies House officers using Splink:

```powershell
python manage.py resolve
```

This trains a Fellegi-Sunter model with:
- **Name**: Jaro-Winkler similarity at 0.95/0.88 thresholds
- **Date of birth**: Exact match on year and month (handles Companies House month-only DOBs)
- **Geography**: Jaro-Winkler on constituency vs. registered office locality

Results land in the `linkage_table` with a `match_probability` (0.0--1.0) and a derived `risk_score` (1--100). Links scoring at or above the review threshold (default 70) are flagged `pending_review`.

### Step 6 -- Human Review

High-risk links must be reviewed before they appear in the graph. Use the API endpoints (server must be running):

**PowerShell:**

```powershell
# List pending reviews (highest risk first)
Invoke-RestMethod http://localhost:8000/api/v1/compliance/pending

# Approve a link
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/compliance/review/LINK_ID `
  -ContentType "application/json" `
  -Body '{"reviewer": "alice@example.com", "action": "approve"}'

# Reject a link
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/compliance/review/LINK_ID `
  -ContentType "application/json" `
  -Body '{"reviewer": "alice@example.com", "action": "reject"}'
```

**curl (macOS/Linux):**

```bash
curl http://localhost:8000/api/v1/compliance/pending

curl -X POST http://localhost:8000/api/v1/compliance/review/LINK_ID \
  -H "Content-Type: application/json" \
  -d '{"reviewer": "alice@example.com", "action": "approve"}'
```

### Step 7 -- Sync to the Graph

Push approved links to Neo4j:

```powershell
python manage.py sync-graph
```

This creates/updates `Person`, `Company`, and `Constituency` nodes with `MP_FOR` and `DIRECTOR_OF` relationships. Only links with status `approved` or `auto_approved` are synced.

### Step 8 -- Query the Graph API

Start the server and query (server must be running):

```powershell
python manage.py serve

# In another terminal:
Invoke-RestMethod "http://localhost:8000/api/v1/graph/search?q=Smith&limit=10"
Invoke-RestMethod http://localhost:8000/api/v1/graph/persons/parliament-4321
Invoke-RestMethod "http://localhost:8000/api/v1/graph/high-risk?threshold=75&limit=20"
```

**curl (macOS/Linux):**

```bash
curl "http://localhost:8000/api/v1/graph/search?q=Smith&limit=10"
curl http://localhost:8000/api/v1/graph/persons/parliament-4321
curl "http://localhost:8000/api/v1/graph/high-risk?threshold=75&limit=20"
```

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/api/v1/graph/persons/{person_id}` | Person node with directorships and companies |
| `GET` | `/api/v1/graph/search?q=&limit=` | Full-text person search |
| `GET` | `/api/v1/graph/high-risk?threshold=&limit=` | Persons above risk score threshold |
| `GET` | `/api/v1/compliance/pending?limit=` | Linkage records awaiting review |
| `POST` | `/api/v1/compliance/review/{link_id}` | Approve or reject a link |

Full interactive documentation is available at `/docs` (Swagger UI) and `/redoc` when the server is running.

## Architecture

```
                    +-----------------+
                    |  Parliament API |
                    +--------+--------+
                             |
  +----------------+         |         +-------------------+
  | Companies House|---+     |     +---| Council PDFs      |
  | (REST+Stream)  |   |     |     |   | (Gemini 2.0 Flash)|
  +----------------+   |     |     |   +-------------------+
                        v     v     v
                   +--------------------+
                   |       DuckDB       |
                   | (Analytical Store) |
                   +----+----------+----+
                        |          |
                        v          |
                   +----------+    |
                   |  Splink  |    |
                   | (Entity  |    |
                   | Resoln.) |    |
                   +----+-----+    |
                        |          |
                        v          v
                   +--------------------+
                   |   linkage_table    |
                   | (pending_review /  |
                   |  auto_approved)    |
                   +--------+-----------+
                            |
                    Human Review (API)
                            |
                            v
                   +--------------------+
                   |      Neo4j         |
                   |  (Political Graph) |
                   +--------+-----------+
                            |
                            v
                   +--------------------+
                   |    FastAPI         |
                   | /api/v1/graph/*    |
                   +--------------------+
                            |
                            v
                     Mobile / Web App
```

## Graph Schema

**Nodes:**

| Label | Key Properties |
|---|---|
| `Person` | `id`, `name`, `house`, `party`, `risk_score`, `status` |
| `Company` | `company_number`, `name`, `is_verified` |
| `Contract` | `ocid`, `value`, `date` |
| `Constituency` | `name` |
| `Council` | `name`, `region` |
| `Motion` | `id` |

**Relationships:**

| Pattern | Properties |
|---|---|
| `(Person)-[:MP_FOR]->(Constituency)` | `start_date` |
| `(Person)-[:DIRECTOR_OF]->(Company)` | `start_date`, `end_date`, `role` |
| `(Company)-[:AWARDED_CONTRACT]->(Contract)` | `award_date` |
| `(Person)-[:VOTED_ON]->(Motion)` | `direction` |
| `(Person)-[:COUNCILLOR_AT]->(Council)` | |

## Compliance

This platform implements safeguards required by the Data (Use and Access) Act 2025 (UK GDPR Article 22):

- **No binary blocking.** Entity matches produce a continuous `risk_score` (1--100), not a pass/fail flag.
- **Human-in-the-loop.** All links scoring at or above the configurable threshold (default 70) are held as `pending_review` and will not appear in the public graph until a human reviewer approves them.
- **Low-risk auto-approval.** Links scoring below the auto-approve threshold (default 30) are marked `auto_approved` and synced to the graph without manual intervention. This is configurable.
- **Audit trail.** Every review action records the reviewer identity and timestamp in the `linkage_table`.

## Testing

**PowerShell:**

```powershell
# Run the full test suite
$env:PYTHONPATH = "src"
pytest

# With coverage
pytest --cov=afterhours --cov-report=term-missing

# Run a specific module's tests
pytest tests\test_intelligence\test_risk_scoring.py -v
```

**macOS/Linux:**

```bash
PYTHONPATH=src pytest
PYTHONPATH=src pytest --cov=afterhours --cov-report=term-missing
```

## Project Structure

```
afterhours/
├── schemas/
│   ├── duckdb/001_create_tables.sql        # DuckDB table definitions
│   └── neo4j/
│       ├── 001_create_constraints.cypher   # Uniqueness constraints & indexes
│       └── 002_create_graph.cypher         # Relationship reference
├── src/afterhours/
│   ├── config/
│   │   ├── settings.py                     # Pydantic Settings (.env loader)
│   │   └── database.py                     # DuckDB + Neo4j connection factories
│   ├── ingestion/
│   │   ├── ingest_parliament.py            # Parliament Members + Interests API
│   │   ├── ingest_companies_house.py       # Companies House REST + Streaming
│   │   └── ingest_procurement.py           # OCDS / Find a Tender
│   ├── extract/
│   │   └── extract_council_pdf.py          # PDF -> Gemini 2.0 Flash -> DuckDB
│   ├── intelligence/
│   │   └── resolve_entities.py             # Splink entity resolution
│   ├── compliance/
│   │   └── risk_scoring.py                 # Risk scores + review workflow
│   ├── graph/
│   │   └── sync.py                         # DuckDB -> Neo4j sync
│   └── api/
│       ├── app.py                          # FastAPI application
│       └── routes/
│           ├── health.py                   # GET /health
│           ├── graph.py                    # Graph query endpoints
│           └── compliance.py               # Review workflow endpoints
├── tests/
├── data/raw/                               # Raw ingested data (git-ignored)
├── requirements.txt
├── pyproject.toml
└── .env.example
```

## License

TBD
