"""Ingest data from the UK Parliament Members and Interests APIs.

Parliament APIs used:
  - Members API v1: https://members-api.parliament.uk/
  - Interests API:  https://members-api.parliament.uk/ (interests endpoint)
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

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

BASE_URL = settings.parliament_api_base_url
_DEFAULT_TIMEOUT = 30.0
_PAGE_SIZE = 20


async def _get_json(client: httpx.AsyncClient, url: str, params: dict | None = None) -> dict:
    """Perform a GET request and return the parsed JSON body."""
    resp = await client.get(url, params=params, timeout=_DEFAULT_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Members (MPs & Lords)
# ---------------------------------------------------------------------------


def _parse_member(raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten the nested Parliament API member response into a row dict."""
    value = raw.get("value", raw)
    latest_party = (value.get("latestParty") or {}).get("name")
    latest_seat = (value.get("latestHouseMembership") or {})

    return {
        "member_id": value["id"],
        "name_display": value.get("nameDisplayAs", ""),
        "name_first": value.get("nameAddressAs", ""),
        "name_last": value.get("nameListAs", "").split(",")[0] if value.get("nameListAs") else "",
        "date_of_birth": value.get("dateOfBirth", "")[:10] or None,
        "gender": value.get("gender"),
        "party": latest_party,
        "constituency": latest_seat.get("membershipFrom"),
        "house": "Commons" if latest_seat.get("house") == 1 else "Lords",
        "start_date": (latest_seat.get("membershipStartDate") or "")[:10] or None,
        "end_date": (latest_seat.get("membershipEndDate") or "")[:10] or None,
        "thumbnail_url": value.get("thumbnailUrl"),
        "fetched_at": datetime.utcnow().isoformat(),
    }


async def fetch_members(house: int = 1, skip: int = 0) -> list[dict[str, Any]]:
    """Fetch a page of members from the Parliament API.

    Args:
        house: 1 = Commons, 2 = Lords.
        skip: Pagination offset.

    Returns:
        List of parsed member dicts.
    """
    async with httpx.AsyncClient() as client:
        data = await _get_json(
            client,
            f"{BASE_URL}/Members/Search",
            params={"House": house, "skip": skip, "take": _PAGE_SIZE, "IsCurrentMember": "true"},
        )
        items = data.get("items", [])
        return [_parse_member(item) for item in items]


async def fetch_all_members(house: int = 1) -> list[dict[str, Any]]:
    """Paginate through all current members of a house."""
    all_members: list[dict[str, Any]] = []
    skip = 0
    async with httpx.AsyncClient() as client:
        while True:
            data = await _get_json(
                client,
                f"{BASE_URL}/Members/Search",
                params={
                    "House": house,
                    "skip": skip,
                    "take": _PAGE_SIZE,
                    "IsCurrentMember": "true",
                },
            )
            items = data.get("items", [])
            if not items:
                break
            all_members.extend(_parse_member(item) for item in items)
            total = data.get("totalResults", 0)
            skip += _PAGE_SIZE
            if skip >= total:
                break
    logger.info("Fetched %d members from house=%d", len(all_members), house)
    return all_members


# ---------------------------------------------------------------------------
# Financial Interests
# ---------------------------------------------------------------------------


def _parse_interest(member_id: int, raw: dict[str, Any]) -> dict[str, Any]:
    """Parse a single interest entry from the Register of Financial Interests."""
    return {
        "interest_id": f"{member_id}-{raw.get('id', '')}",
        "member_id": member_id,
        "category": raw.get("category", {}).get("name", ""),
        "description": raw.get("interest", ""),
        "date_registered": (raw.get("createdWhen") or "")[:10] or None,
        "date_updated": (raw.get("lastAmendedWhen") or "")[:10] or None,
        "extracted_company_name": None,
        "extracted_role": None,
        "extracted_amount": None,
        "fetched_at": datetime.utcnow().isoformat(),
    }


async def fetch_interests(member_id: int) -> list[dict[str, Any]]:
    """Fetch all registered interests for a single member."""
    async with httpx.AsyncClient() as client:
        try:
            data = await _get_json(client, f"{BASE_URL}/Members/{member_id}/Interests")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.debug("No interests endpoint for member %d (404)", member_id)
                return []
            raise
        interests: list[dict[str, Any]] = []
        for category in data.get("value", []):
            for entry in category.get("interests", []):
                interests.append(_parse_interest(member_id, entry))
        return interests


# ---------------------------------------------------------------------------
# DuckDB persistence
# ---------------------------------------------------------------------------


def upsert_members(rows: list[dict[str, Any]], conn: duckdb.DuckDBPyConnection | None = None):
    """Insert or update parliament_members rows in DuckDB."""
    if not rows:
        return
    conn = conn or get_duckdb_connection()
    conn.executemany(
        """
        INSERT OR REPLACE INTO parliament_members
            (member_id, name_display, name_first, name_last, date_of_birth,
             gender, party, constituency, house, start_date, end_date,
             thumbnail_url, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["member_id"], r["name_display"], r["name_first"], r["name_last"],
                r["date_of_birth"], r["gender"], r["party"], r["constituency"],
                r["house"], r["start_date"], r["end_date"], r["thumbnail_url"],
                r["fetched_at"],
            )
            for r in rows
        ],
    )
    logger.info("Upserted %d parliament_members rows", len(rows))


def upsert_interests(rows: list[dict[str, Any]], conn: duckdb.DuckDBPyConnection | None = None):
    """Insert or update financial_interests rows in DuckDB."""
    if not rows:
        return
    conn = conn or get_duckdb_connection()
    conn.executemany(
        """
        INSERT OR REPLACE INTO financial_interests
            (interest_id, member_id, category, description, date_registered,
             date_updated, extracted_company_name, extracted_role,
             extracted_amount, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["interest_id"], r["member_id"], r["category"], r["description"],
                r["date_registered"], r["date_updated"], r["extracted_company_name"],
                r["extracted_role"], r["extracted_amount"], r["fetched_at"],
            )
            for r in rows
        ],
    )
    logger.info("Upserted %d financial_interests rows", len(rows))
