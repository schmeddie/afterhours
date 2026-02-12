"""Extract structured data from council meeting PDFs using Gemini 2.0 Flash.

Pipeline:
  1. Load PDF with PyMuPDF and render each page to an image.
  2. Send page images to Gemini 2.0 Flash with a structured-output prompt.
  3. Validate the JSON response against a strict schema.
  4. Persist valid records to DuckDB.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

import duckdb
import fitz  # PyMuPDF
import jsonschema
from google import genai
from google.genai import types as genai_types

from afterhours.config.database import get_duckdb_connection
from afterhours.config.settings import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON Schema for council extraction output
# ---------------------------------------------------------------------------

COUNCIL_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "council_name": {"type": "string"},
        "meeting_date": {"type": ["string", "null"], "format": "date"},
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "councillor_name": {"type": "string"},
                    "vote_direction": {
                        "type": ["string", "null"],
                        "enum": ["for", "against", "abstain", None],
                    },
                    "planning_decision": {"type": ["string", "null"]},
                    "motion_text": {"type": ["string", "null"]},
                    "confidence_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["councillor_name"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["council_name", "records"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------


def render_pdf_pages(pdf_path: Path, dpi: int = 200) -> list[bytes]:
    """Render each page of a PDF as a PNG byte buffer.

    Uses PyMuPDF for fast, dependency-light rendering. For pages with complex
    layouts a dedicated layout parser (e.g. LayoutParser / Detectron2) could
    replace this step.
    """
    doc = fitz.open(str(pdf_path))
    images: list[bytes] = []
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    for page in doc:
        pix = page.get_pixmap(matrix=matrix)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


# ---------------------------------------------------------------------------
# Gemini 2.0 Flash integration
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = """\
You are an expert UK local-government analyst. You are given an image of a page
from a council meeting minutes PDF.

Extract ALL councillor actions visible on this page. Return a JSON object with
the following schema:

{
  "council_name": "<name of the council>",
  "meeting_date": "<YYYY-MM-DD or null>",
  "records": [
    {
      "councillor_name": "<full name>",
      "vote_direction": "for" | "against" | "abstain" | null,
      "planning_decision": "<description or null>",
      "motion_text": "<the motion text or null>",
      "confidence_score": <0.0-1.0>
    }
  ]
}

Rules:
- Return ONLY the JSON object, no markdown fences or commentary.
- If a field is unclear, set it to null.
- confidence_score reflects how certain you are about the extraction (1.0 = certain).
- If no councillor actions are visible, return {"council_name": "...", "meeting_date": null, "records": []}.
"""


def _get_gemini_client() -> genai.Client:
    """Return an authenticated Gemini client."""
    return genai.Client(api_key=settings.gemini_api_key)


def extract_page(image_png: bytes) -> dict[str, Any] | None:
    """Send a single page image to Gemini 2.0 Flash and parse the response.

    Returns:
        Parsed JSON dict on success, None if extraction or validation fails.
    """
    client = _get_gemini_client()

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            genai_types.Content(
                parts=[
                    genai_types.Part.from_text(text=_EXTRACTION_PROMPT),
                    genai_types.Part.from_bytes(data=image_png, mime_type="image/png"),
                ],
            ),
        ],
        config=genai_types.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json",
        ),
    )

    raw_text = response.text.strip()
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error("Gemini returned invalid JSON: %s", raw_text[:500])
        return None

    # Validate against strict schema
    try:
        jsonschema.validate(instance=parsed, schema=COUNCIL_EXTRACTION_SCHEMA)
    except jsonschema.ValidationError as exc:
        logger.error("Gemini output failed schema validation: %s", exc.message)
        return None

    return parsed


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


def process_pdf(
    pdf_path: Path,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> int:
    """Run the full extract pipeline on a council PDF.

    1. Render pages to images.
    2. Send each to Gemini for extraction.
    3. Validate and persist to DuckDB.

    Returns:
        Number of records inserted.
    """
    conn = conn or get_duckdb_connection()
    page_images = render_pdf_pages(pdf_path)
    logger.info("Rendered %d pages from %s", len(page_images), pdf_path.name)

    total_inserted = 0
    for idx, img in enumerate(page_images):
        result = extract_page(img)
        if result is None:
            logger.warning("Skipping page %d – extraction failed", idx + 1)
            continue

        rows = _to_rows(pdf_path.name, result)
        if rows:
            _insert_rows(rows, conn)
            total_inserted += len(rows)

    logger.info("Extracted %d total records from %s", total_inserted, pdf_path.name)
    return total_inserted


def _to_rows(source_pdf: str, result: dict[str, Any]) -> list[tuple]:
    """Convert a validated Gemini result into DuckDB-ready row tuples."""
    council_name = result.get("council_name")
    meeting_date = result.get("meeting_date")
    rows: list[tuple] = []

    for rec in result.get("records", []):
        rows.append((
            str(uuid.uuid4()),
            source_pdf,
            council_name,
            meeting_date,
            rec["councillor_name"],
            rec.get("vote_direction"),
            rec.get("planning_decision"),
            rec.get("motion_text"),
            "gemini-2.0-flash",
            rec.get("confidence_score"),
        ))
    return rows


def _insert_rows(rows: list[tuple], conn: duckdb.DuckDBPyConnection):
    """Persist extraction rows to the council_extracted table."""
    conn.executemany(
        """
        INSERT INTO council_extracted
            (record_id, source_pdf, council_name, meeting_date,
             councillor_name, vote_direction, planning_decision,
             motion_text, extraction_model, confidence_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
