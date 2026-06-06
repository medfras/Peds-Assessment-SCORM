"""Tests for A2 — subscore range validation in _extract_required_debrief_subscores().

Covers:
  - In-range values accepted
  - Out-of-range values rejected with ERROR log, fall to authoritative fallback
  - Out-of-range with no fallback, fall to regex recovery
  - subscore_maxima overrides the table ceiling
  - Non-integer values hit the existing int() cast error path (covered by prior tests)
"""
from __future__ import annotations

import pytest

from app.ai_client import _extract_required_debrief_subscores, _SUBSCORE_RANGES


# ── _SUBSCORE_RANGES sanity ───────────────────────────────────────────────────

def test_subscore_ranges_has_all_required_keys():
    required = {"clinical_performance", "scope_adherence", "protocols_treatment",
                "dmist", "professionalism", "narrative"}
    assert required.issubset(_SUBSCORE_RANGES.keys())


def test_dmist_range_is_0_to_10():
    assert _SUBSCORE_RANGES["dmist"] == (0, 10)


def test_narrative_range_is_0_to_20():
    assert _SUBSCORE_RANGES["narrative"] == (0, 20)


# ── In-range values accepted ──────────────────────────────────────────────────

def test_in_range_dmist_accepted():
    ss = _extract_required_debrief_subscores(
        "", {"dmist": 8, "clinical_performance": 80, "scope_adherence": 90,
             "protocols_treatment": 85, "professionalism": 9},
        include_narrative=False,
    )
    assert ss["dmist"] == 8


def test_boundary_zero_accepted():
    ss = _extract_required_debrief_subscores(
        "", {"dmist": 0, "clinical_performance": 0, "scope_adherence": 0,
             "protocols_treatment": 0, "professionalism": 0},
        include_narrative=False,
    )
    assert ss["dmist"] == 0


def test_boundary_max_dmist_accepted():
    ss = _extract_required_debrief_subscores(
        "", {"dmist": 10, "clinical_performance": 80, "scope_adherence": 90,
             "protocols_treatment": 85, "professionalism": 9},
        include_narrative=False,
    )
    assert ss["dmist"] == 10


# ── Out-of-range values rejected ─────────────────────────────────────────────

def test_dmist_above_range_uses_authoritative_fallback(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        ss = _extract_required_debrief_subscores(
            "",
            {"dmist": 15, "clinical_performance": 80, "scope_adherence": 90,
             "protocols_treatment": 85, "professionalism": 9},
            include_narrative=False,
            authoritative_fallbacks={"dmist": 7},
        )
    assert ss["dmist"] == 7
    assert "subscore_out_of_range" in caplog.text, (
        "expected ERROR log for out-of-range value in logs"
    )


def test_dmist_below_range_uses_authoritative_fallback(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        ss = _extract_required_debrief_subscores(
            "",
            {"dmist": -1, "clinical_performance": 80, "scope_adherence": 90,
             "protocols_treatment": 85, "professionalism": 9},
            include_narrative=False,
            authoritative_fallbacks={"dmist": 5},
        )
    assert ss["dmist"] == 5
    assert "subscore_out_of_range" in caplog.text


def test_out_of_range_no_fallback_uses_regex_recovery(caplog):
    import logging
    debrief = "DMIST Quality: 8\nClinical Performance: 80\nScope Adherence: 90\nTreatment Protocols: 85\nProfessionalism: 9"
    with caplog.at_level(logging.WARNING):
        ss = _extract_required_debrief_subscores(
            debrief,
            {"dmist": 99},  # out of range, no fallback
            include_narrative=False,
        )
    assert ss["dmist"] == 8  # recovered from regex
    assert "subscore_out_of_range" in caplog.text


def test_out_of_range_no_fallback_no_regex_raises():
    with pytest.raises(ValueError, match="missing required subscores"):
        _extract_required_debrief_subscores(
            "",
            {"dmist": 99},  # out of range, no fallback, no regex match
            include_narrative=False,
        )


def test_regex_recovery_rejects_repeated_out_of_range_value():
    # Structured JSON has dmist=99 (rejected). Markdown also has DMIST Quality: 99.
    # Regex recovery must range-validate and also reject 99, so the function raises.
    debrief = "DMIST Quality: 99\nClinical Performance: 80\nScope Adherence: 90\nTreatment Protocols: 85\nProfessionalism: 9"
    with pytest.raises(ValueError, match="missing required subscores"):
        _extract_required_debrief_subscores(
            debrief,
            {"dmist": 99},
            include_narrative=False,
        )


def test_authoritative_fallback_takes_priority_over_regex(capsys):
    # Authoritative fallback (step 2) must win over regex (step 3).
    # Structured JSON has dmist=99 (rejected). Markdown has DMIST Quality: 8 (in range).
    # Fallback supplies dmist=5. Result must be 5, not 8.
    debrief = "DMIST Quality: 8\nClinical Performance: 80\nScope Adherence: 90\nTreatment Protocols: 85\nProfessionalism: 9"
    ss = _extract_required_debrief_subscores(
        debrief,
        {"dmist": 99},
        include_narrative=False,
        authoritative_fallbacks={"dmist": 5},
    )
    assert ss["dmist"] == 5, "authoritative fallback must take priority over regex recovery"


# ── subscore_maxima overrides table ceiling ───────────────────────────────────

def test_subscore_maxima_overrides_clinical_ceiling():
    # clinical_performance table ceiling is 100; pass maxima of 60
    # value of 65 would be in-range under table but rejected under maxima
    with pytest.raises(ValueError):
        _extract_required_debrief_subscores(
            "",
            {"clinical_performance": 65, "scope_adherence": 90,
             "protocols_treatment": 85, "dmist": 8, "professionalism": 9},
            include_narrative=False,
            subscore_maxima={"clinical_performance": 60},
        )


def test_subscore_maxima_tighter_ceiling_rejects_value(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        ss = _extract_required_debrief_subscores(
            "",
            {"clinical_performance": 65, "scope_adherence": 90,
             "protocols_treatment": 85, "dmist": 8, "professionalism": 9},
            include_narrative=False,
            subscore_maxima={"clinical_performance": 60},
            authoritative_fallbacks={"clinical_performance": 55},
        )
    assert ss["clinical_performance"] == 55
    assert "subscore_out_of_range" in caplog.text


def test_subscore_maxima_exact_boundary_accepted():
    ss = _extract_required_debrief_subscores(
        "",
        {"clinical_performance": 60, "scope_adherence": 90,
         "protocols_treatment": 85, "dmist": 8, "professionalism": 9},
        include_narrative=False,
        subscore_maxima={"clinical_performance": 60},
    )
    assert ss["clinical_performance"] == 60


# ── narrative included path ───────────────────────────────────────────────────

def test_narrative_in_range_accepted():
    ss = _extract_required_debrief_subscores(
        "",
        {"clinical_performance": 80, "scope_adherence": 90,
         "protocols_treatment": 85, "dmist": 8, "professionalism": 9,
         "narrative": 17},
        include_narrative=True,
    )
    assert ss["narrative"] == 17


def test_narrative_above_range_uses_fallback(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        ss = _extract_required_debrief_subscores(
            "",
            {"clinical_performance": 80, "scope_adherence": 90,
             "protocols_treatment": 85, "dmist": 8, "professionalism": 9,
             "narrative": 25},
            include_narrative=True,
            authoritative_fallbacks={"narrative": 15},
        )
    assert ss["narrative"] == 15
    assert "subscore_out_of_range" in caplog.text
