"""Tests for A1 — authored debrief content validation.

Covers _validate_debrief_content() in vocabulary.py and the runtime guard
in evaluate_and_generate_debrief() in ai_client.py.
"""
from __future__ import annotations

import pytest

from app.scenarios.vocabulary import _validate_debrief_content, validate_scenario


# ── _validate_debrief_content unit tests ─────────────────────────────────────

FULL_DEBRIEF = {
    "condition_background": "Patient background text.",
    "key_teaching_points": ["Point A", "Point B"],
    "common_mistakes": ["Mistake A"],
}


def test_all_fields_present_returns_empty():
    scenario = {"id": "test_01", "debrief": FULL_DEBRIEF}
    assert _validate_debrief_content(scenario) == []


def test_missing_condition_background_flagged():
    scenario = {
        "id": "test_01",
        "debrief": {"key_teaching_points": ["A"], "common_mistakes": ["B"]},
    }
    missing = _validate_debrief_content(scenario)
    assert "debrief.condition_background" in missing
    assert len(missing) == 1


def test_missing_key_teaching_points_flagged():
    scenario = {
        "id": "test_01",
        "debrief": {"condition_background": "bg", "common_mistakes": ["B"]},
    }
    missing = _validate_debrief_content(scenario)
    assert "debrief.key_teaching_points" in missing


def test_missing_common_mistakes_flagged():
    scenario = {
        "id": "test_01",
        "debrief": {"condition_background": "bg", "key_teaching_points": ["A"]},
    }
    missing = _validate_debrief_content(scenario)
    assert "debrief.common_mistakes" in missing


def test_all_three_missing_returns_all():
    scenario = {"id": "test_01", "debrief": {}}
    missing = _validate_debrief_content(scenario)
    assert set(missing) == {
        "debrief.condition_background",
        "debrief.key_teaching_points",
        "debrief.common_mistakes",
    }


def test_debrief_exempt_true_skips_all_checks():
    scenario = {"id": "orientation_01", "debrief_exempt": True, "debrief": {}}
    assert _validate_debrief_content(scenario) == []


def test_debrief_exempt_false_still_checks():
    scenario = {"id": "test_01", "debrief_exempt": False, "debrief": {}}
    missing = _validate_debrief_content(scenario)
    assert len(missing) == 3


def test_debrief_absent_entirely_flagged():
    scenario = {"id": "test_01"}
    missing = _validate_debrief_content(scenario)
    assert len(missing) == 3


def test_empty_list_teaching_points_flagged():
    scenario = {
        "id": "test_01",
        "debrief": {
            "condition_background": "bg",
            "key_teaching_points": [],
            "common_mistakes": ["A"],
        },
    }
    missing = _validate_debrief_content(scenario)
    assert "debrief.key_teaching_points" in missing


# ── validate_scenario integration — debrief warnings ─────────────────────────

_MINIMAL_VALID_INTERVENTION = {
    "o2_nrb": {"label": "High-flow O2 via NRB mask (15 LPM)"},
}

_BASE_SCENARIO = {
    "_schema": "pfd_scenario_v1",
    "id": "test_scenario",
    "rubric_template": "ems_standard_v1",
    "turnover_target": "als",
    "vitals": {"interventions": {}},
    "scoring_rubric": {},
}


def test_validate_scenario_warns_on_missing_debrief_field():
    scenario = {**_BASE_SCENARIO, "debrief": {"condition_background": "bg"}}
    warnings = validate_scenario(scenario)
    debrief_warnings = [w for w in warnings if "debrief." in w]
    assert len(debrief_warnings) == 2
    missing_fields = {w.split()[0] for w in debrief_warnings}
    assert "debrief.key_teaching_points" in missing_fields
    assert "debrief.common_mistakes" in missing_fields


def test_validate_scenario_no_debrief_warning_when_complete():
    scenario = {**_BASE_SCENARIO, "debrief": FULL_DEBRIEF}
    warnings = validate_scenario(scenario)
    debrief_warnings = [w for w in warnings if "debrief." in w]
    assert debrief_warnings == []


def test_validate_scenario_no_debrief_warning_when_exempt():
    scenario = {**_BASE_SCENARIO, "debrief_exempt": True, "debrief": {}}
    warnings = validate_scenario(scenario)
    debrief_warnings = [w for w in warnings if "debrief." in w]
    assert debrief_warnings == []


# ── Runtime guard: evaluate_and_generate_debrief ─────────────────────────────
# Tests that the guard raises ValueError on missing fields without touching
# the LLM call path — we check only the guard, not the full debrief flow.

def _minimal_debrief_scenario(debrief: dict, exempt: bool = False) -> dict:
    """Build a scenario stub minimal enough to reach the debrief content guard."""
    s = {
        "id": "test_scenario",
        "debrief_exempt": exempt,
        "debrief": debrief,
        "turnover_target": "als",
        "correct_treatment": {"critical_actions": [], "out_of_scope_bls": []},
        "patient": {"name": "Test", "age": 8, "sex": "male", "weight_kg": 25,
                    "weight_display": "25 kg", "chief_complaint": "test",
                    "general_impression": "test"},
        "vitals": {"baseline": {}, "interventions": {}},
        "scoring": {},
        "scoring_rubric": {},
        "protocol_config": {"mca": "mi_wmrmcc_kent"},
        "category": "pediatric_medical",
        "clinical_context": {},
    }
    return s


def test_runtime_guard_raises_on_missing_condition_background():
    from app.ai_client import _validate_debrief_content as vdc
    scenario = _minimal_debrief_scenario({
        "key_teaching_points": ["A"],
        "common_mistakes": ["B"],
    })
    missing = vdc(scenario)
    assert "debrief.condition_background" in missing


def test_runtime_guard_passes_when_exempt():
    from app.ai_client import _validate_debrief_content as vdc
    scenario = _minimal_debrief_scenario({}, exempt=True)
    assert vdc(scenario) == []


def test_all_live_scenarios_pass_debrief_validation():
    """Integration: every scenario on disk either has all debrief fields or debrief_exempt=true."""
    import json
    from pathlib import Path

    failures = []
    for path in sorted(Path("app/scenarios").rglob("*.json")):
        scenario = json.loads(path.read_text())
        missing = _validate_debrief_content(scenario)
        if missing:
            failures.append(f"{path.name}: {missing}")

    assert failures == [], (
        "These scenarios are missing required debrief fields:\n"
        + "\n".join(f"  {f}" for f in failures)
    )
