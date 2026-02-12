"""Graph query endpoints – serve the Political Graph to the frontend."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from neo4j import GraphDatabase
from pydantic import BaseModel

from afterhours.config.settings import settings

router = APIRouter()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class PersonNode(BaseModel):
    id: str
    name: str
    house: str | None = None
    party: str | None = None
    risk_score: int | None = None
    status: str | None = None


class CompanyNode(BaseModel):
    company_number: str
    name: str
    is_verified: bool = False


class DirectorshipEdge(BaseModel):
    person_id: str
    company_number: str
    role: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class PersonGraph(BaseModel):
    person: PersonNode
    directorships: list[DirectorshipEdge] = []
    companies: list[CompanyNode] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_driver():
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


def _run_read(query: str, **params: Any) -> list[dict[str, Any]]:
    driver = _get_driver()
    with driver.session() as session:
        result = session.run(query, **params)
        records = [dict(r) for r in result]
    driver.close()
    return records


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/persons/{person_id}", response_model=PersonGraph)
async def get_person_graph(person_id: str):
    """Return a person node with their company directorships."""
    person_records = _run_read(
        "MATCH (p:Person {id: $pid}) RETURN p", pid=person_id
    )
    if not person_records:
        raise HTTPException(status_code=404, detail="Person not found")

    p = person_records[0]["p"]
    person = PersonNode(
        id=p["id"],
        name=p["name"],
        house=p.get("house"),
        party=p.get("party"),
        risk_score=p.get("risk_score"),
        status=p.get("status"),
    )

    edges = _run_read(
        """
        MATCH (p:Person {id: $pid})-[r:DIRECTOR_OF]->(c:Company)
        RETURN r, c
        """,
        pid=person_id,
    )

    directorships = []
    companies = []
    for rec in edges:
        r = rec["r"]
        c = rec["c"]
        directorships.append(DirectorshipEdge(
            person_id=person_id,
            company_number=c["company_number"],
            role=r.get("role"),
            start_date=r.get("start_date"),
            end_date=r.get("end_date"),
        ))
        companies.append(CompanyNode(
            company_number=c["company_number"],
            name=c["name"],
            is_verified=c.get("is_verified", False),
        ))

    return PersonGraph(person=person, directorships=directorships, companies=companies)


@router.get("/search", response_model=list[PersonNode])
async def search_persons(
    q: str = Query(..., min_length=2, description="Name search query"),
    limit: int = Query(20, le=100),
):
    """Full-text search for persons in the graph."""
    records = _run_read(
        """
        MATCH (p:Person)
        WHERE toLower(p.name) CONTAINS toLower($q)
        RETURN p
        ORDER BY p.risk_score DESC
        LIMIT $limit
        """,
        q=q,
        limit=limit,
    )
    return [
        PersonNode(
            id=r["p"]["id"],
            name=r["p"]["name"],
            house=r["p"].get("house"),
            party=r["p"].get("party"),
            risk_score=r["p"].get("risk_score"),
            status=r["p"].get("status"),
        )
        for r in records
    ]


@router.get("/high-risk", response_model=list[PersonNode])
async def get_high_risk_persons(
    threshold: int = Query(70, ge=1, le=100, description="Minimum risk score"),
    limit: int = Query(50, le=200),
):
    """Return persons with risk score at or above the given threshold."""
    records = _run_read(
        """
        MATCH (p:Person)
        WHERE p.risk_score >= $threshold AND p.status = 'approved'
        RETURN p
        ORDER BY p.risk_score DESC
        LIMIT $limit
        """,
        threshold=threshold,
        limit=limit,
    )
    return [
        PersonNode(
            id=r["p"]["id"],
            name=r["p"]["name"],
            house=r["p"].get("house"),
            party=r["p"].get("party"),
            risk_score=r["p"].get("risk_score"),
            status=r["p"].get("status"),
        )
        for r in records
    ]
