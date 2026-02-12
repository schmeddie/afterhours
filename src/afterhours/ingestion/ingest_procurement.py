"""Ingest Open Contracting Data Standard (OCDS) releases from Find a Tender.

Source: https://www.find-tender.service.gov.uk/
OCDS spec: https://standard.open-contracting.org/latest/en/
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from afterhours.config.database import get_duckdb_connection

logger = logging.getLogger(__name__)


def parse_ocds_release(release: dict[str, Any]) -> dict[str, Any] | None:
    """Extract a contract row from a single OCDS release JSON object."""
    tender = release.get("tender", {})
    awards = release.get("awards", [])
    if not awards:
        return None

    award = awards[0]
    suppliers = award.get("suppliers", [])
    buyer = release.get("buyer", {})

    return {
        "ocid": release.get("ocid", ""),
        "title": tender.get("title"),
        "description": tender.get("description"),
        "status": award.get("status"),
        "tender_value": (tender.get("value") or {}).get("amount"),
        "tender_currency": (tender.get("value") or {}).get("currency", "GBP"),
        "award_date": award.get("date", "")[:10] or None,
        "buyer_name": buyer.get("name"),
        "buyer_id": buyer.get("id"),
        "supplier_name": suppliers[0].get("name") if suppliers else None,
        "supplier_id": suppliers[0].get("id") if suppliers else None,
        "procurement_method": tender.get("procurementMethod"),
        "fetched_at": datetime.utcnow().isoformat(),
    }


def ingest_ocds_file(path: Path, conn: duckdb.DuckDBPyConnection | None = None) -> int:
    """Read an OCDS JSON file and upsert contracts into DuckDB.

    Supports both single-release and release-package formats.

    Returns:
        Number of rows upserted.
    """
    import json

    conn = conn or get_duckdb_connection()
    data = json.loads(path.read_text(encoding="utf-8"))

    releases = data.get("releases", [data] if "ocid" in data else [])
    rows = [r for rel in releases if (r := parse_ocds_release(rel)) is not None]

    if not rows:
        logger.warning("No awardable releases found in %s", path)
        return 0

    conn.executemany(
        """
        INSERT OR REPLACE INTO procurement_contracts
            (ocid, title, description, status, tender_value, tender_currency,
             award_date, buyer_name, buyer_id, supplier_name, supplier_id,
             procurement_method, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["ocid"], r["title"], r["description"], r["status"],
                r["tender_value"], r["tender_currency"], r["award_date"],
                r["buyer_name"], r["buyer_id"], r["supplier_name"],
                r["supplier_id"], r["procurement_method"], r["fetched_at"],
            )
            for r in rows
        ],
    )
    logger.info("Upserted %d procurement_contracts from %s", len(rows), path.name)
    return len(rows)
