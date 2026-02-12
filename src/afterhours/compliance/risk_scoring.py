"""Risk scoring and human-in-the-loop compliance safeguards.

Implements requirements from the Data (Use and Access) Act 2025 (UK GDPR
Article 22) – no automated binary blocking decisions. All high-risk matches
require human verification before they are surfaced publicly.
"""

from __future__ import annotations

import logging
from datetime import datetime

import duckdb

from afterhours.config.database import get_duckdb_connection
from afterhours.config.settings import settings

logger = logging.getLogger(__name__)


def compute_risk_score(match_probability: float) -> int:
    """Derive a 1–100 risk score from a Splink match probability.

    The mapping is intentionally non-linear to push borderline matches
    towards the review threshold:
      - 0.0–0.3  ->  1–20   (low risk, likely noise)
      - 0.3–0.7  ->  20–60  (moderate, needs context)
      - 0.7–0.9  ->  60–85  (high, likely genuine overlap)
      - 0.9–1.0  ->  85–100 (very high confidence match)
    """
    p = max(0.0, min(1.0, match_probability))
    if p < 0.3:
        return max(1, int(p / 0.3 * 20))
    elif p < 0.7:
        return 20 + int((p - 0.3) / 0.4 * 40)
    elif p < 0.9:
        return 60 + int((p - 0.7) / 0.2 * 25)
    else:
        return 85 + int((p - 0.9) / 0.1 * 15)


def flag_for_review(link_id: str, conn: duckdb.DuckDBPyConnection | None = None):
    """Mark a linkage record as pending human review."""
    conn = conn or get_duckdb_connection()
    conn.execute(
        "UPDATE linkage_table SET review_status = 'pending_review' WHERE link_id = ?",
        [link_id],
    )


def approve_link(
    link_id: str, reviewer: str, conn: duckdb.DuckDBPyConnection | None = None
):
    """Approve a linkage record after human verification."""
    conn = conn or get_duckdb_connection()
    conn.execute(
        """
        UPDATE linkage_table
        SET review_status = 'approved',
            reviewed_by = ?,
            reviewed_at = ?
        WHERE link_id = ?
        """,
        [reviewer, datetime.utcnow().isoformat(), link_id],
    )
    logger.info("Link %s approved by %s", link_id, reviewer)


def reject_link(
    link_id: str, reviewer: str, conn: duckdb.DuckDBPyConnection | None = None
):
    """Reject a linkage record after human verification."""
    conn = conn or get_duckdb_connection()
    conn.execute(
        """
        UPDATE linkage_table
        SET review_status = 'rejected',
            reviewed_by = ?,
            reviewed_at = ?
        WHERE link_id = ?
        """,
        [reviewer, datetime.utcnow().isoformat(), link_id],
    )
    logger.info("Link %s rejected by %s", link_id, reviewer)


def get_pending_reviews(
    limit: int = 50, conn: duckdb.DuckDBPyConnection | None = None
) -> list[dict]:
    """Fetch linkage records awaiting human review, ordered by risk score descending."""
    conn = conn or get_duckdb_connection()
    rows = conn.execute(
        """
        SELECT link_id, source_a_table, source_a_id, source_b_table, source_b_id,
               match_probability, risk_score, created_at
        FROM linkage_table
        WHERE review_status = 'pending_review'
        ORDER BY risk_score DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()

    columns = [
        "link_id", "source_a_table", "source_a_id", "source_b_table",
        "source_b_id", "match_probability", "risk_score", "created_at",
    ]
    return [dict(zip(columns, row)) for row in rows]
