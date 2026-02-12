"""Entity resolution between Parliament and Companies House datasets using Splink.

Implements the Fellegi-Sunter probabilistic linkage model with:
  - Jaro-Winkler fuzzy name matching
  - Fuzzy date-of-birth matching (YYYY-MM-DD vs YYYY-MM)
  - Geographic proximity matching (constituency vs registered office)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

import duckdb
import splink.comparison_library as cl
from splink import Linker, SettingsCreator

from afterhours.compliance.risk_scoring import compute_risk_score
from afterhours.config.database import get_duckdb_connection
from afterhours.config.settings import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Staging: prepare unified frames for Splink
# ---------------------------------------------------------------------------


def _prepare_parliament_frame(conn: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyRelation:
    """Build a Splink-ready frame from parliament_members."""
    return conn.sql("""
        SELECT
            'parliament-' || CAST(member_id AS VARCHAR) AS unique_id,
            'parliament' AS source_dataset,
            name_display AS full_name,
            name_first AS first_name,
            name_last AS last_name,
            EXTRACT(YEAR FROM date_of_birth) AS dob_year,
            EXTRACT(MONTH FROM date_of_birth) AS dob_month,
            EXTRACT(DAY FROM date_of_birth) AS dob_day,
            constituency AS geo_label
        FROM parliament_members
        WHERE name_display IS NOT NULL
    """)


def _prepare_companies_house_frame(conn: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyRelation:
    """Build a Splink-ready frame from ch_officers."""
    return conn.sql("""
        SELECT
            'ch-' || officer_id AS unique_id,
            'companies_house' AS source_dataset,
            name AS full_name,
            -- Companies House names are "SURNAME, Forename(s)"
            CASE WHEN CONTAINS(name, ',')
                 THEN TRIM(SPLIT_PART(name, ',', 2))
                 ELSE NULL END AS first_name,
            CASE WHEN CONTAINS(name, ',')
                 THEN TRIM(SPLIT_PART(name, ',', 1))
                 ELSE name END AS last_name,
            date_of_birth_year AS dob_year,
            date_of_birth_month AS dob_month,
            NULL AS dob_day,
            address_locality AS geo_label
        FROM ch_officers
        WHERE name IS NOT NULL
    """)


# ---------------------------------------------------------------------------
# Splink configuration
# ---------------------------------------------------------------------------


def build_splink_settings() -> dict[str, Any]:
    """Create the Splink settings dict for Parliament <-> Companies House linkage.

    Uses the Fellegi-Sunter model with comparisons tuned for UK political data:
      - full_name:  Jaro-Winkler at thresholds 0.95 / 0.88
      - first_name: Jaro-Winkler at threshold 0.92
      - last_name:  Jaro-Winkler at threshold 0.92
      - dob_year:   Exact match
      - dob_month:  Exact match
      - geo_label:  Jaro-Winkler at threshold 0.88
    """
    return SettingsCreator(
        link_type="link_only",
        comparisons=[
            cl.JaroWinklerAtThresholds("full_name", score_threshold_or_thresholds=[0.95, 0.88]),
            cl.JaroWinklerAtThresholds("first_name", score_threshold_or_thresholds=0.92),
            cl.JaroWinklerAtThresholds("last_name", score_threshold_or_thresholds=0.92),
            cl.ExactMatch("dob_year"),
            cl.ExactMatch("dob_month"),
            cl.JaroWinklerAtThresholds("geo_label", score_threshold_or_thresholds=0.88),
        ],
        blocking_rules_to_generate_predictions=[
            "l.dob_year = r.dob_year AND l.dob_month = r.dob_month",
            "l.last_name = r.last_name",
        ],
        retain_intermediate_calculation_columns=False,
    )


# ---------------------------------------------------------------------------
# Run linkage
# ---------------------------------------------------------------------------


def run_entity_resolution(conn: duckdb.DuckDBPyConnection | None = None) -> int:
    """Execute end-to-end entity resolution and persist results.

    Steps:
      1. Prepare staging frames from DuckDB tables.
      2. Configure and train the Splink model (EM algorithm).
      3. Predict pairwise match probabilities.
      4. Apply compliance risk scoring.
      5. Persist to the linkage_table.

    Returns:
        Number of links written.
    """
    conn = conn or get_duckdb_connection()

    parliament_df = _prepare_parliament_frame(conn)
    ch_df = _prepare_companies_house_frame(conn)

    splink_settings = build_splink_settings()
    linker = Linker(
        [parliament_df, ch_df],
        splink_settings,
        db_api=conn,
    )

    # Train match weights using Expectation-Maximisation
    linker.training.estimate_u_using_random_sampling(max_pairs=1_000_000)
    linker.training.estimate_parameters_using_expectation_maximisation(
        "l.dob_year = r.dob_year AND l.dob_month = r.dob_month",
        fix_u_probabilities=False,
    )
    linker.training.estimate_parameters_using_expectation_maximisation(
        "l.last_name = r.last_name",
        fix_u_probabilities=False,
    )

    # Predict
    predictions = linker.inference.predict(threshold_match_probability=0.5)
    results_df = predictions.as_duckdbpyrelation()

    # Convert to list and persist
    rows = conn.sql(f"""
        SELECT
            unique_id_l,
            unique_id_r,
            match_probability
        FROM results_df
        ORDER BY match_probability DESC
    """).fetchall()

    link_rows = _build_link_rows(rows)
    _persist_links(link_rows, conn)

    logger.info("Entity resolution complete: %d links produced", len(link_rows))
    return len(link_rows)


def _build_link_rows(raw_rows: list[tuple]) -> list[tuple]:
    """Convert Splink prediction rows into linkage_table tuples with risk scores."""
    link_rows: list[tuple] = []
    threshold = settings.risk_score_review_threshold
    auto_approve = settings.auto_approve_below

    for uid_l, uid_r, match_prob in raw_rows:
        source_a_table = "parliament_members" if uid_l.startswith("parliament-") else "ch_officers"
        source_b_table = "ch_officers" if uid_r.startswith("ch-") else "parliament_members"
        source_a_id = uid_l.split("-", 1)[1]
        source_b_id = uid_r.split("-", 1)[1]

        risk_score = compute_risk_score(match_prob)

        if risk_score >= threshold:
            status = "pending_review"
        elif risk_score < auto_approve:
            status = "auto_approved"
        else:
            status = "pending_review"

        link_rows.append((
            str(uuid.uuid4()),
            source_a_table,
            source_a_id,
            source_b_table,
            source_b_id,
            match_prob,
            risk_score,
            status,
            None,  # reviewed_by
            None,  # reviewed_at
            datetime.utcnow().isoformat(),
        ))

    return link_rows


def _persist_links(rows: list[tuple], conn: duckdb.DuckDBPyConnection):
    """Write linkage rows to DuckDB."""
    if not rows:
        return
    conn.executemany(
        """
        INSERT OR REPLACE INTO linkage_table
            (link_id, source_a_table, source_a_id, source_b_table, source_b_id,
             match_probability, risk_score, review_status, reviewed_by,
             reviewed_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
