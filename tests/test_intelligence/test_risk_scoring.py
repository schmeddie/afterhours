"""Tests for risk scoring module."""

from afterhours.compliance.risk_scoring import compute_risk_score


def test_low_probability_gives_low_score():
    assert compute_risk_score(0.1) < 20


def test_high_probability_gives_high_score():
    assert compute_risk_score(0.95) >= 85


def test_boundary_values():
    assert compute_risk_score(0.0) == 1
    assert compute_risk_score(1.0) == 100


def test_mid_range():
    score = compute_risk_score(0.5)
    assert 20 <= score <= 60


def test_clamps_out_of_range():
    assert compute_risk_score(-0.5) == 1
    assert compute_risk_score(1.5) == 100
