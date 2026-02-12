"""Compliance endpoints – human-in-the-loop review workflow."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from afterhours.compliance.risk_scoring import (
    approve_link,
    get_pending_reviews,
    reject_link,
)

router = APIRouter()


class ReviewAction(BaseModel):
    reviewer: str
    action: str  # "approve" | "reject"


class PendingLink(BaseModel):
    link_id: str
    source_a_table: str
    source_a_id: str
    source_b_table: str
    source_b_id: str
    match_probability: float
    risk_score: int
    created_at: str


@router.get("/pending", response_model=list[PendingLink])
async def list_pending_reviews(limit: int = 50):
    """List linkage records awaiting human review."""
    rows = get_pending_reviews(limit=limit)
    return [PendingLink(**r) for r in rows]


@router.post("/review/{link_id}")
async def review_link(link_id: str, body: ReviewAction):
    """Approve or reject a pending linkage record.

    This endpoint enforces the Data (Use and Access) Act 2025 requirement
    that high-risk automated decisions receive human oversight.
    """
    if body.action == "approve":
        approve_link(link_id, body.reviewer)
    elif body.action == "reject":
        reject_link(link_id, body.reviewer)
    else:
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    return {"link_id": link_id, "new_status": body.action + "d"}
