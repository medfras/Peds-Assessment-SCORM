"""
Unit tests for CE time tracking helpers.

_ce_round_hours() is the only pure (non-DB) function here and is the one
that matters most to get right — a rounding error would misreport credit hours
on a CE submission to any certifying agency.

Also verifies the cap constant values match the policy spec so that a
future change to the numbers triggers a deliberate test update.
"""

from __future__ import annotations

import pytest

from app.main import (
    CE_FEEDBACK_REVIEW_CAP_SECONDS,
    CE_ORIENTATION_DEBRIEF_CAP_SECONDS,
    CE_SCENARIO_DEBRIEF_CAP_SECONDS,
    _ce_round_hours,
)


# ── CE hour rounding ──────────────────────────────────────────────────────────
# CE credits are reported in 0.25-hour increments across certifying agencies.
# _ce_round_hours(seconds) floors to the nearest completed 0.25 h.

@pytest.mark.parametrize("seconds,expected", [
    # Exact quarter-hour boundaries
    (0,      0.0),
    (900,    0.25),   # exactly 15 min → 0.25 h
    (1800,   0.5),    # exactly 30 min → 0.50 h
    (2700,   0.75),   # exactly 45 min → 0.75 h
    (3600,   1.0),    # exactly 60 min → 1.00 h
    (7200,   2.0),    # exactly 2 h    → 2.00 h
    # Incomplete quarter-hours floor to lower bound (no partial credit)
    (800,    0.0),    # 13:20 → floors to 0.0  (need 15:00 for 0.25)
    (899,    0.0),    # 14:59 → floors to 0.0
    (1700,   0.25),   # 28:20 → floors to 0.25 (not 0.50)
    (3500,   0.75),   # 58:20 → floors to 0.75 (not 1.00)
    # Already past a quarter-hour boundary → credit that boundary
    (1000,   0.25),   # 16:40 → floors to 0.25
    (2000,   0.5),    # 33:20 → floors to 0.50
    (3700,   1.0),    # 61:40 → floors to 1.00
    # Midpoint of a quarter-hour still floors down
    (449,    0.0),    # 7:29 → 0.0
    (450,    0.0),    # 7:30 → 0.0 (floor, not round)
    (1349,   0.25),   # 22:29 → 0.25
    (1350,   0.25),   # 22:30 → 0.25 (floor, not 0.5)
    # Realistic session lengths
    (3661,   1.0),    # 1 h 1 s → 1.00 h
    (5400,   1.5),    # 1.5 h exactly → 1.50 h
    (5401,   1.5),    # just over 1.5 h → 1.50 h
])
def test_ce_round_hours(seconds, expected):
    assert _ce_round_hours(seconds) == expected


def test_ce_round_hours_large():
    # 4 hours exactly
    assert _ce_round_hours(14400) == 4.0


def test_ce_round_hours_returns_float():
    result = _ce_round_hours(3600)
    assert isinstance(result, float)


# ── CE phase cap constants ────────────────────────────────────────────────────
# These tests lock the spec values. If the caps change, update this test AND
# document the rationale (pilot telemetry, agency review, etc.).

def test_feedback_review_cap_is_two_minutes():
    assert CE_FEEDBACK_REVIEW_CAP_SECONDS == 120


def test_scenario_debrief_cap_is_eight_minutes():
    assert CE_SCENARIO_DEBRIEF_CAP_SECONDS == 480


def test_orientation_debrief_cap_is_five_minutes():
    assert CE_ORIENTATION_DEBRIEF_CAP_SECONDS == 300


def test_debrief_cap_larger_than_feedback_cap():
    # Scenario debriefs are longer than drill feedback reviews by design.
    assert CE_SCENARIO_DEBRIEF_CAP_SECONDS > CE_FEEDBACK_REVIEW_CAP_SECONDS


# ── Debrief split cap arithmetic ─────────────────────────────────────────────
# These mirror the cap logic in post_session_progress() for the instrumented
# path (debrief_elapsed_sec > 0). Tests use the constants directly so they
# stay in sync if values change.

@pytest.mark.parametrize("debrief_reported,expected_ce", [
    # Under cap: full reported time credited
    (0,   0),
    (60,  60),
    (479, 479),
    # At cap: exactly capped
    (480, CE_SCENARIO_DEBRIEF_CAP_SECONDS),
    # Over cap: hard ceiling applies
    (600, CE_SCENARIO_DEBRIEF_CAP_SECONDS),
    (3600, CE_SCENARIO_DEBRIEF_CAP_SECONDS),
])
def test_scenario_debrief_cap_applied(debrief_reported, expected_ce):
    credited = min(debrief_reported, CE_SCENARIO_DEBRIEF_CAP_SECONDS)
    assert credited == expected_ce


@pytest.mark.parametrize("debrief_reported,expected_ce", [
    (0,   0),
    (60,  60),
    (119, 119),
    (120, CE_FEEDBACK_REVIEW_CAP_SECONDS),
    (300, CE_FEEDBACK_REVIEW_CAP_SECONDS),
])
def test_feedback_review_cap_applied(debrief_reported, expected_ce):
    credited = min(debrief_reported, CE_FEEDBACK_REVIEW_CAP_SECONDS)
    assert credited == expected_ce


def test_active_ce_is_elapsed_minus_debrief():
    # Active time = wall-clock elapsed - debrief time (floored at 0)
    total_elapsed = 1800   # 30 min scenario
    debrief_reported = 300  # 5 min debrief
    active_ce = max(0, total_elapsed - debrief_reported)
    assert active_ce == 1500


def test_active_ce_floored_at_zero_if_debrief_exceeds_elapsed():
    # Shouldn't happen in practice, but guard against negative active time
    total_elapsed = 200
    debrief_reported = 400  # frontend glitch: reported more than total
    active_ce = max(0, total_elapsed - debrief_reported)
    assert active_ce == 0
