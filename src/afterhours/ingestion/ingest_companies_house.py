"""Ingest data from the Companies House Public Data and Streaming APIs.

Public Data API: https://developer-specs.company-information.service.gov.uk/
Streaming API:  https://developer-specs.company-information.service.gov.uk/streaming-api/
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import duckdb
import httpx

from afterhours.config.database import get_duckdb_connection
from afterhours.config.settings import settings

logger = logging.getLogger(__name__)

CH_API_BASE = "https://api.company-information.service.gov.uk"
_DEFAULT_TIMEOUT = 30.0


def _auth() -> tuple[str, str]:
    """Return HTTP Basic auth tuple (API key as username, empty password)."""
    return (settings.companies_house_api_key, "")


# ---------------------------------------------------------------------------
# Public Data API – Company Profile
# ---------------------------------------------------------------------------


async def fetch_company_profile(company_number: str) -> dict[str, Any]:
    """Fetch a single company profile from Companies House."""
    async with httpx.AsyncClient(auth=_auth()) as client:
        resp = await client.get(
            f"{CH_API_BASE}/company/{company_number}",
            timeout=_DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        return _parse_company(resp.json())


def _parse_company(raw: dict[str, Any]) -> dict[str, Any]:
    addr = raw.get("registered_office_address") or {}
    return {
        "company_number": raw["company_number"],
        "company_name": raw.get("company_name", ""),
        "company_status": raw.get("company_status"),
        "company_type": raw.get("type"),
        "date_of_creation": raw.get("date_of_creation"),
        "date_of_cessation": raw.get("date_of_cessation"),
        "registered_office_address_line1": addr.get("address_line_1"),
        "registered_office_postcode": addr.get("postal_code"),
        "registered_office_locality": addr.get("locality"),
        "registered_office_region": addr.get("region"),
        "sic_codes": raw.get("sic_codes", []),
        "fetched_at": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Public Data API – Officers
# ---------------------------------------------------------------------------


async def fetch_officers(company_number: str) -> list[dict[str, Any]]:
    """Fetch officers list for a company, handling pagination."""
    officers: list[dict[str, Any]] = []
    start_index = 0

    async with httpx.AsyncClient(auth=_auth()) as client:
        while True:
            resp = await client.get(
                f"{CH_API_BASE}/company/{company_number}/officers",
                params={"start_index": start_index, "items_per_page": 100},
                timeout=_DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break
            for item in items:
                officers.append(_parse_officer(company_number, item))
            total = data.get("total_results", 0)
            start_index += len(items)
            if start_index >= total:
                break

    return officers


def _parse_officer(company_number: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Parse a single officer record.

    Handles the Identity Verification status flag introduced by the
    Companies House reform programme.
    """
    dob = raw.get("date_of_birth") or {}
    links = raw.get("links", {})
    officer_id = (links.get("officer", {}).get("appointments") or "").split("/")[2:3]
    return {
        "officer_id": officer_id[0] if officer_id else raw.get("name", ""),
        "company_number": company_number,
        "name": raw.get("name", ""),
        "date_of_birth_year": dob.get("year"),
        "date_of_birth_month": dob.get("month"),
        "role": raw.get("officer_role", ""),
        "appointed_on": raw.get("appointed_on"),
        "resigned_on": raw.get("resigned_on"),
        "nationality": raw.get("nationality"),
        "country_of_residence": raw.get("country_of_residence"),
        "address_locality": (raw.get("address") or {}).get("locality"),
        "address_postcode": (raw.get("address") or {}).get("postal_code"),
        "identity_verified": raw.get("identification", {}).get("identification_type") == "uk-limited-company",
        "fetched_at": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Streaming API – real-time filings
# ---------------------------------------------------------------------------


async def stream_filings():
    """Connect to the Companies House Streaming API for real-time filing events.

    Yields parsed filing event dicts. The stream uses HTTP chunked transfer
    encoding with newline-delimited JSON.
    """
    import json

    url = "https://stream.companieshouse.gov.uk/filings"
    async with httpx.AsyncClient(auth=(settings.companies_house_stream_key, "")) as client:
        async with client.stream("GET", url, timeout=None) as response:
            async for line in response.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    yield event
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed streaming line: %s", line[:200])


# ---------------------------------------------------------------------------
# DuckDB persistence
# ---------------------------------------------------------------------------


def upsert_companies(rows: list[dict[str, Any]], conn: duckdb.DuckDBPyConnection | None = None):
    """Insert or update ch_companies rows."""
    if not rows:
        return
    conn = conn or get_duckdb_connection()
    conn.executemany(
        """
        INSERT OR REPLACE INTO ch_companies
            (company_number, company_name, company_status, company_type,
             date_of_creation, date_of_cessation,
             registered_office_address_line1, registered_office_postcode,
             registered_office_locality, registered_office_region,
             sic_codes, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["company_number"], r["company_name"], r["company_status"],
                r["company_type"], r["date_of_creation"], r["date_of_cessation"],
                r["registered_office_address_line1"], r["registered_office_postcode"],
                r["registered_office_locality"], r["registered_office_region"],
                r["sic_codes"], r["fetched_at"],
            )
            for r in rows
        ],
    )
    logger.info("Upserted %d ch_companies rows", len(rows))


def upsert_officers(rows: list[dict[str, Any]], conn: duckdb.DuckDBPyConnection | None = None):
    """Insert or update ch_officers rows."""
    if not rows:
        return
    conn = conn or get_duckdb_connection()
    conn.executemany(
        """
        INSERT OR REPLACE INTO ch_officers
            (officer_id, company_number, name, date_of_birth_year,
             date_of_birth_month, role, appointed_on, resigned_on,
             nationality, country_of_residence, address_locality,
             address_postcode, identity_verified, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["officer_id"], r["company_number"], r["name"],
                r["date_of_birth_year"], r["date_of_birth_month"],
                r["role"], r["appointed_on"], r["resigned_on"],
                r["nationality"], r["country_of_residence"],
                r["address_locality"], r["address_postcode"],
                r["identity_verified"], r["fetched_at"],
            )
            for r in rows
        ],
    )
    logger.info("Upserted %d ch_officers rows", len(rows))
