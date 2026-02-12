"""Tests for council PDF extraction schema validation."""

import jsonschema
import pytest

from afterhours.extract.extract_council_pdf import COUNCIL_EXTRACTION_SCHEMA


def test_valid_extraction_passes():
    data = {
        "council_name": "Test Borough Council",
        "meeting_date": "2025-03-15",
        "records": [
            {
                "councillor_name": "John Doe",
                "vote_direction": "for",
                "planning_decision": "Approved application 2025/001",
                "motion_text": "Motion to approve",
                "confidence_score": 0.95,
            }
        ],
    }
    jsonschema.validate(instance=data, schema=COUNCIL_EXTRACTION_SCHEMA)


def test_missing_councillor_name_fails():
    data = {
        "council_name": "Test Council",
        "meeting_date": None,
        "records": [{"vote_direction": "for"}],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=data, schema=COUNCIL_EXTRACTION_SCHEMA)


def test_invalid_vote_direction_fails():
    data = {
        "council_name": "Test Council",
        "meeting_date": None,
        "records": [
            {"councillor_name": "Jane", "vote_direction": "maybe"},
        ],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=data, schema=COUNCIL_EXTRACTION_SCHEMA)
