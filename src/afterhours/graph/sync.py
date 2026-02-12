"""Sync approved linkage data from DuckDB into Neo4j.

Only links with review_status='approved' (or 'auto_approved' below the
threshold) are pushed to the graph. This enforces the human-in-the-loop
requirement for high-risk matches.
"""

from __future__ import annotations

import logging
from typing import Any

import duckdb
from neo4j import Session as Neo4jSession

from afterhours.config.database import get_duckdb_connection, get_neo4j_driver

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Node merge helpers
# ---------------------------------------------------------------------------


def _merge_person(tx, person: dict[str, Any]):
    tx.run(
        """
        MERGE (p:Person {id: $id})
        SET p.name        = $name,
            p.house       = $house,
            p.party       = $party,
            p.risk_score  = $risk_score,
            p.status      = $status
        """,
        **person,
    )


def _merge_company(tx, company: dict[str, Any]):
    tx.run(
        """
        MERGE (c:Company {company_number: $company_number})
        SET c.name        = $name,
            c.is_verified = $is_verified
        """,
        **company,
    )


def _merge_constituency(tx, name: str):
    tx.run("MERGE (:Constituency {name: $name})", name=name)


def _merge_contract(tx, contract: dict[str, Any]):
    tx.run(
        """
        MERGE (ct:Contract {ocid: $ocid})
        SET ct.value = $value,
            ct.date  = $date
        """,
        **contract,
    )


def _merge_council(tx, name: str, region: str | None = None):
    tx.run(
        "MERGE (co:Council {name: $name}) SET co.region = $region",
        name=name,
        region=region,
    )


# ---------------------------------------------------------------------------
# Relationship merge helpers
# ---------------------------------------------------------------------------


def _link_mp_for(tx, person_id: str, constituency: str, start_date: str | None):
    tx.run(
        """
        MATCH (p:Person {id: $pid})
        MATCH (c:Constituency {name: $con})
        MERGE (p)-[r:MP_FOR]->(c)
        SET r.start_date = $sd
        """,
        pid=person_id,
        con=constituency,
        sd=start_date,
    )


def _link_director_of(
    tx,
    person_id: str,
    company_number: str,
    start_date: str | None,
    end_date: str | None,
    role: str | None,
):
    tx.run(
        """
        MATCH (p:Person {id: $pid})
        MATCH (c:Company {company_number: $cn})
        MERGE (p)-[r:DIRECTOR_OF]->(c)
        SET r.start_date = $sd, r.end_date = $ed, r.role = $role
        """,
        pid=person_id,
        cn=company_number,
        sd=start_date,
        ed=end_date,
        role=role,
    )


def _link_awarded_contract(tx, company_number: str, ocid: str, award_date: str | None):
    tx.run(
        """
        MATCH (c:Company {company_number: $cn})
        MATCH (ct:Contract {ocid: $ocid})
        MERGE (c)-[r:AWARDED_CONTRACT]->(ct)
        SET r.award_date = $ad
        """,
        cn=company_number,
        ocid=ocid,
        ad=award_date,
    )


# ---------------------------------------------------------------------------
# Full sync pipeline
# ---------------------------------------------------------------------------


def sync_approved_links(conn: duckdb.DuckDBPyConnection | None = None):
    """Push all approved/auto-approved links to Neo4j as graph relationships.

    Reads approved linkage rows from DuckDB, resolves the underlying entities,
    and merges Person, Company nodes with DIRECTOR_OF relationships.
    """
    conn = conn or get_duckdb_connection()
    driver = get_neo4j_driver()

    # Fetch approved links that join a parliament member to a CH officer
    links = conn.execute("""
        SELECT
            lt.source_a_id,
            lt.source_b_id,
            lt.match_probability,
            lt.risk_score,
            pm.name_display,
            pm.party,
            pm.house,
            pm.constituency,
            pm.start_date AS mp_start_date,
            co.company_number,
            co.name AS officer_name,
            co.role AS officer_role,
            co.appointed_on,
            co.resigned_on
        FROM linkage_table lt
        JOIN parliament_members pm
            ON lt.source_a_id = CAST(pm.member_id AS VARCHAR)
        JOIN ch_officers co
            ON lt.source_b_id = co.officer_id
        WHERE lt.review_status IN ('approved', 'auto_approved')
          AND lt.source_a_table = 'parliament_members'
          AND lt.source_b_table = 'ch_officers'
    """).fetchall()

    logger.info("Syncing %d approved links to Neo4j", len(links))

    with driver.session() as session:
        for row in links:
            (
                member_id, officer_id, match_prob, risk_score,
                name, party, house, constituency, mp_start,
                company_number, officer_name, role, appointed, resigned,
            ) = row

            person_id = f"parliament-{member_id}"

            # Merge person
            session.execute_write(
                _merge_person,
                {
                    "id": person_id,
                    "name": name,
                    "house": house,
                    "party": party,
                    "risk_score": risk_score,
                    "status": "approved",
                },
            )

            # Merge constituency + relationship
            if constituency:
                session.execute_write(_merge_constituency, constituency)
                session.execute_write(_link_mp_for, person_id, constituency, mp_start)

            # Merge company (fetch profile for full node)
            company = conn.execute(
                "SELECT * FROM ch_companies WHERE company_number = ?",
                [company_number],
            ).fetchone()

            if company:
                session.execute_write(
                    _merge_company,
                    {
                        "company_number": company_number,
                        "name": company[1],  # company_name
                        "is_verified": False,
                    },
                )
            else:
                session.execute_write(
                    _merge_company,
                    {
                        "company_number": company_number,
                        "name": officer_name,
                        "is_verified": False,
                    },
                )

            # Link person -> company
            session.execute_write(
                _link_director_of,
                person_id,
                company_number,
                appointed,
                resigned,
                role,
            )

    driver.close()
    logger.info("Neo4j sync complete")
