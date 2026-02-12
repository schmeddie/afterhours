"""After Hours management CLI.

Usage:
    python manage.py init-db          Initialise DuckDB schema
    python manage.py init-neo4j       Create Neo4j constraints and indexes
    python manage.py ingest-parliament  Fetch MPs, Lords, and their interests
    python manage.py ingest-company <NUMBER>  Fetch a company and its officers
    python manage.py ingest-procurement <FILE>  Ingest an OCDS JSON file
    python manage.py extract-pdf <FILE>  Extract council data from a PDF
    python manage.py resolve           Run entity resolution (Splink)
    python manage.py sync-graph        Push approved links to Neo4j
    python manage.py serve             Start the API server
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("manage")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_init_db(args: argparse.Namespace) -> None:
    """Create or reset the DuckDB analytical schema."""
    from afterhours.config.database import get_duckdb_connection

    sql_path = Path("schemas/duckdb/001_create_tables.sql")
    if not sql_path.exists():
        logger.error("Schema file not found: %s", sql_path)
        sys.exit(1)

    conn = get_duckdb_connection()
    conn.execute(sql_path.read_text())
    conn.close()
    logger.info("DuckDB schema created.")


def cmd_init_neo4j(args: argparse.Namespace) -> None:
    """Create Neo4j constraints and indexes."""
    from afterhours.config.database import get_neo4j_driver

    cypher_path = Path("schemas/neo4j/001_create_constraints.cypher")
    if not cypher_path.exists():
        logger.error("Schema file not found: %s", cypher_path)
        sys.exit(1)

    stmts = [
        s.strip()
        for s in cypher_path.read_text().split(";")
        if s.strip() and not s.strip().startswith("//")
    ]

    driver = get_neo4j_driver()
    with driver.session() as session:
        for stmt in stmts:
            session.run(stmt)
            logger.info("OK: %s...", stmt[:60])
    driver.close()
    logger.info("Neo4j constraints created.")


def cmd_ingest_parliament(args: argparse.Namespace) -> None:
    """Fetch all current MPs, Lords, and their financial interests."""
    from afterhours.config.database import get_duckdb_connection
    from afterhours.ingestion.ingest_parliament import (
        fetch_all_members,
        fetch_interests,
        upsert_interests,
        upsert_members,
    )

    async def _run() -> None:
        commons = await fetch_all_members(house=1)
        lords = await fetch_all_members(house=2)

        conn = get_duckdb_connection()
        upsert_members(commons + lords, conn)
        logger.info("Ingested %d MPs + %d Lords", len(commons), len(lords))

        count = 0
        total = len(commons) + len(lords)
        for i, member in enumerate(commons + lords, 1):
            interests = await fetch_interests(member["member_id"])
            if interests:
                upsert_interests(interests, conn)
                count += len(interests)
            if i % 100 == 0:
                logger.info("  progress: %d/%d members processed", i, total)

        conn.close()
        logger.info("Ingested %d financial interests.", count)

    asyncio.run(_run())


def cmd_ingest_company(args: argparse.Namespace) -> None:
    """Fetch a company profile and its officers from Companies House."""
    from afterhours.ingestion.ingest_companies_house import (
        fetch_company_profile,
        fetch_officers,
        upsert_companies,
        upsert_officers,
    )

    async def _run() -> None:
        profile = await fetch_company_profile(args.company_number)
        upsert_companies([profile])
        logger.info("Ingested company: %s", profile.get("company_name", args.company_number))

        officers = await fetch_officers(args.company_number)
        upsert_officers(officers)
        logger.info("Ingested %d officers.", len(officers))

    asyncio.run(_run())


def cmd_ingest_procurement(args: argparse.Namespace) -> None:
    """Ingest an OCDS JSON file into DuckDB."""
    from afterhours.ingestion.ingest_procurement import ingest_ocds_file

    path = Path(args.file)
    if not path.exists():
        logger.error("File not found: %s", path)
        sys.exit(1)

    count = ingest_ocds_file(path)
    logger.info("Inserted %d contracts from %s", count, path.name)


def cmd_extract_pdf(args: argparse.Namespace) -> None:
    """Extract council meeting data from a PDF via Gemini."""
    from afterhours.extract.extract_council_pdf import process_pdf

    path = Path(args.file)
    if not path.exists():
        logger.error("File not found: %s", path)
        sys.exit(1)

    records = process_pdf(path)
    logger.info("Extracted %d records from %s", records, path.name)


def cmd_resolve(args: argparse.Namespace) -> None:
    """Run Splink entity resolution between Parliament and Companies House."""
    from afterhours.intelligence.resolve_entities import run_entity_resolution

    links = run_entity_resolution()
    logger.info("Produced %d candidate links.", links)


def cmd_sync_graph(args: argparse.Namespace) -> None:
    """Sync approved/auto-approved links to Neo4j."""
    from afterhours.graph.sync import sync_approved_links

    sync_approved_links()
    logger.info("Graph sync complete.")


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the FastAPI development server."""
    import uvicorn

    uvicorn.run(
        "afterhours.api.app:app",
        host=args.host,
        port=args.port,
        reload=True,
        app_dir="src",
    )


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manage.py",
        description="After Hours management CLI",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init-db", help="Initialise DuckDB schema")
    sub.add_parser("init-neo4j", help="Create Neo4j constraints and indexes")
    sub.add_parser("ingest-parliament", help="Fetch MPs, Lords, and interests")

    p_company = sub.add_parser("ingest-company", help="Fetch a company and its officers")
    p_company.add_argument("company_number", help="Companies House number (e.g. 00000006)")

    p_procurement = sub.add_parser("ingest-procurement", help="Ingest an OCDS JSON file")
    p_procurement.add_argument("file", help="Path to the OCDS JSON file")

    p_pdf = sub.add_parser("extract-pdf", help="Extract council data from a PDF")
    p_pdf.add_argument("file", help="Path to the council minutes PDF")

    sub.add_parser("resolve", help="Run entity resolution (Splink)")
    sub.add_parser("sync-graph", help="Push approved links to Neo4j")

    p_serve = sub.add_parser("serve", help="Start the API server")
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")

    return parser


COMMANDS = {
    "init-db": cmd_init_db,
    "init-neo4j": cmd_init_neo4j,
    "ingest-parliament": cmd_ingest_parliament,
    "ingest-company": cmd_ingest_company,
    "ingest-procurement": cmd_ingest_procurement,
    "extract-pdf": cmd_extract_pdf,
    "resolve": cmd_resolve,
    "sync-graph": cmd_sync_graph,
    "serve": cmd_serve,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    COMMANDS[args.command](args)


if __name__ == "__main__":
    main()
