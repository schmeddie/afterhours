# After Hours

A UK political transparency platform that aggregates data from Parliament, Companies House, and Local Councils to detect conflicts of interest and the revolving door between public office and private business.

Built on a feasibility study for linking the Register of Members' Financial Interests to corporate officer records using probabilistic entity resolution, with human-in-the-loop compliance safeguards.

## Prerequisites

| Dependency | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Runtime |
| Neo4j | 5.x | Graph database for the Political Graph |
| DuckDB | (bundled) | Embedded analytical database, no install needed |
| API keys | See below | Companies House, Google Gemini |

**API keys you will need:**

- **Companies House** -- register at [developer.company-information.service.gov.uk](https://developer.company-information.service.gov.uk/) for both a REST API key and a Streaming API key.
- **Google Gemini** -- get an API key from [aistudio.google.com](https://aistudio.google.com/).
- **Parliament API** -- no key required; the Members API is open.

## Quick Start

```bash
# 1. Clone and enter the repo
git clone <repo-url> && cd afterhours

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy the environment template and fill in your keys
cp .env.example .env
# Edit .env with your API keys and Neo4j credentials

# 5. Initialise the DuckDB schema
python -c "
from afterhours.config.database import get_duckdb_connection
from pathlib import Path
conn = get_duckdb_connection()
conn.execute(Path('schemas/duckdb/001_create_tables.sql').read_text())
conn.close()
print('DuckDB schema created.')
"

# 6. Initialise Neo4j constraints (requires a running Neo4j instance)
cat schemas/neo4j/001_create_constraints.cypher | cypher-shell -u neo4j -p <password>

# 7. Start the API server
uvicorn afterhours.api.app:app --reload --app-dir src
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

The platform has five pipelines that run in sequence. Each can be run independently.

### Step 1 -- Ingest Parliament Data

Pull current MPs, Lords, and their registered financial interests into DuckDB:

```python
import asyncio
from afterhours.ingestion.ingest_parliament import (
    fetch_all_members,
    fetch_interests,
    upsert_members,
    upsert_interests,
)

async def ingest_parliament():
    # Fetch all current MPs
    commons = await fetch_all_members(house=1)
    lords = await fetch_all_members(house=2)
    upsert_members(commons + lords)

    # Fetch financial interests for each member
    for member in commons + lords:
        interests = await fetch_interests(member["member_id"])
        upsert_interests(interests)

asyncio.run(ingest_parliament())
```

### Step 2 -- Ingest Companies House Data

Pull company profiles and officer lists for companies of interest:

```python
import asyncio
from afterhours.ingestion.ingest_companies_house import (
    fetch_company_profile,
    fetch_officers,
    upsert_companies,
    upsert_officers,
)

async def ingest_company(company_number: str):
    profile = await fetch_company_profile(company_number)
    upsert_companies([profile])

    officers = await fetch_officers(company_number)
    upsert_officers(officers)

# Example: ingest a specific company
asyncio.run(ingest_company("00000006"))
```

To listen for real-time filings via the Streaming API:

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

```python
from pathlib import Path
from afterhours.ingestion.ingest_procurement import ingest_ocds_file

# Ingest a single OCDS release package
count = ingest_ocds_file(Path("data/raw/procurement/tender_2025.json"))
print(f"Inserted {count} contracts")
```

### Step 4 -- Extract Council Meeting Data from PDFs

Process council minutes PDFs through the Gemini 2.0 Flash vision pipeline:

```python
from pathlib import Path
from afterhours.extract.extract_council_pdf import process_pdf

# Extract councillor votes and planning decisions
records = process_pdf(Path("data/raw/council_pdfs/minutes_2025_03.pdf"))
print(f"Extracted {records} records")
```

The pipeline:
1. Renders each PDF page to a PNG image (via PyMuPDF).
2. Sends each image to Gemini 2.0 Flash with a structured-output prompt.
3. Validates the JSON response against a strict schema (councillor name, vote direction, planning decision).
4. Only inserts records that pass validation.

### Step 5 -- Run Entity Resolution

Match Parliament members against Companies House officers using Splink:

```python
from afterhours.intelligence.resolve_entities import run_entity_resolution

links = run_entity_resolution()
print(f"Produced {links} candidate links")
```

This trains a Fellegi-Sunter model with:
- **Name**: Jaro-Winkler similarity at 0.95/0.88 thresholds
- **Date of birth**: Exact match on year and month (handles Companies House month-only DOBs)
- **Geography**: Jaro-Winkler on constituency vs. registered office locality

Results land in the `linkage_table` with a `match_probability` (0.0--1.0) and a derived `risk_score` (1--100). Links scoring at or above the review threshold (default 70) are flagged `pending_review`.

### Step 6 -- Human Review

High-risk links must be reviewed before they appear in the graph. Use the API or call the functions directly:

```bash
# List pending reviews (highest risk first)
curl http://localhost:8000/api/v1/compliance/pending

# Approve a link
curl -X POST http://localhost:8000/api/v1/compliance/review/LINK_ID \
  -H "Content-Type: application/json" \
  -d '{"reviewer": "alice@example.com", "action": "approve"}'

# Reject a link
curl -X POST http://localhost:8000/api/v1/compliance/review/LINK_ID \
  -H "Content-Type: application/json" \
  -d '{"reviewer": "alice@example.com", "action": "reject"}'
```

### Step 7 -- Sync to the Graph

Push approved links to Neo4j:

```python
from afterhours.graph.sync import sync_approved_links

sync_approved_links()
```

This creates/updates `Person`, `Company`, and `Constituency` nodes with `MP_FOR` and `DIRECTOR_OF` relationships. Only links with status `approved` or `auto_approved` are synced.

### Step 8 -- Query the Graph API

```bash
# Search for a person by name
curl "http://localhost:8000/api/v1/graph/search?q=Smith&limit=10"

# Get a person's full graph (directorships, companies)
curl http://localhost:8000/api/v1/graph/persons/parliament-4321

# List high-risk persons above a given threshold
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

```bash
# Run the full test suite
PYTHONPATH=src pytest

# With coverage
PYTHONPATH=src pytest --cov=afterhours --cov-report=term-missing

# Run a specific module's tests
PYTHONPATH=src pytest tests/test_intelligence/test_risk_scoring.py -v
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
