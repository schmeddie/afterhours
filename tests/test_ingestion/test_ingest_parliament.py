"""Tests for Parliament API ingestion module."""

from afterhours.ingestion.ingest_parliament import _parse_member, _parse_interest


def test_parse_member_commons():
    raw = {
        "value": {
            "id": 42,
            "nameDisplayAs": "Jane Smith",
            "nameAddressAs": "Jane",
            "nameListAs": "Smith, Jane",
            "dateOfBirth": "1975-06-15T00:00:00",
            "gender": "F",
            "latestParty": {"name": "Labour"},
            "latestHouseMembership": {
                "house": 1,
                "membershipFrom": "Bristol West",
                "membershipStartDate": "2019-12-12T00:00:00",
                "membershipEndDate": None,
            },
            "thumbnailUrl": "https://example.com/photo.jpg",
        }
    }
    result = _parse_member(raw)
    assert result["member_id"] == 42
    assert result["name_display"] == "Jane Smith"
    assert result["house"] == "Commons"
    assert result["constituency"] == "Bristol West"
    assert result["date_of_birth"] == "1975-06-15"


def test_parse_member_lords():
    raw = {
        "value": {
            "id": 99,
            "nameDisplayAs": "Lord Test",
            "nameAddressAs": "Test",
            "nameListAs": "Test",
            "dateOfBirth": None,
            "gender": "M",
            "latestParty": None,
            "latestHouseMembership": {"house": 2},
        }
    }
    result = _parse_member(raw)
    assert result["house"] == "Lords"
    assert result["party"] is None


def test_parse_interest():
    raw = {
        "id": 555,
        "category": {"name": "Employment and earnings"},
        "interest": "Director of Acme Corp",
        "createdWhen": "2020-01-15T00:00:00",
        "lastAmendedWhen": None,
    }
    result = _parse_interest(42, raw)
    assert result["interest_id"] == "42-555"
    assert result["category"] == "Employment and earnings"
    assert "Acme Corp" in result["description"]
