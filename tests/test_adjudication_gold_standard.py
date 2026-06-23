"""
Gold-standard adjudication fixtures — Phase 7 (§20).

Each fixture specifies a known set of mock inputs and the expected adjudication
state for every scenario-authored checklist item.  Inherited base patient-care
rubrics are covered in tests/test_checklist.py so every scenario fixture does
not need to duplicate the full NREMT medical/trauma assessment sheet.

Adding a new scenario checklist requires adding a corresponding fixture here.
Keeping fixtures current is mandatory: a fixture that tracks an old rule and
passes silently is worse than no fixture.

Fixture format
--------------
{
  "scenario_id": str,
  "description": str,
  "inputs": {
    "interventions": [str, ...],          # intervention keys applied
    "findings":  [{"key", "value", "finding_type"}, ...],
    "messages":  [str, ...],              # student (user) messages
    "scene_entry": dict,                  # scene_entry JSONB
    "dmist":  str,                        # submitted DMIST text
    "narrative": str,                     # submitted narrative text
  },
  "expected_states": {item_id: state, ...},
}

Valid states: "satisfied" | "not_satisfied" | "ambiguous" | "not_applicable"
"""

from __future__ import annotations

import json
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.checklist import load_checklist
from app.rubric_loader import compose_active_checklist, load_call_type_rubric, load_scenario_overlay
from app.scoring_service import adjudicate

# ── Scenario loading — raw JSON (no protocol resolution required) ─────────────

_SCENARIO_DIR = Path(__file__).parent.parent / "app" / "scenarios"


def _load_scenario_raw(scenario_id: str) -> dict:
    """Load scenario JSON directly, bypassing protocol resolution.

    Protocol files are not present in the test environment.  For adjudication
    tests we only need the checklist, scene_entry_scoring, and
    legacy_ai_categories fields — none of which require protocol resolution.
    """
    for path in _SCENARIO_DIR.rglob("*.json"):
        with path.open() as f:
            data = json.load(f)
        if data.get("id") == scenario_id:
            return data
    raise FileNotFoundError(f"Scenario {scenario_id!r} not found under {_SCENARIO_DIR}")


# ── Fixture helpers ───────────────────────────────────────────────────────────


def _iv(key: str):
    """Mock Intervention with the given key."""
    return types.SimpleNamespace(
        id=1,
        name=key,
        applied_at=datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc),
    )


def _finding(key: str, value: str, finding_type: str = "vital", source: str | None = None):
    return types.SimpleNamespace(
        id=1,
        key=key,
        value=value,
        finding_type=finding_type,
        source=source,
        captured_at=datetime(2025, 1, 1, 12, 3, 0, tzinfo=timezone.utc),
    )


def _msg(content: str):
    return types.SimpleNamespace(role="user", content=content, timestamp=None)


def _event(event_type: str, event_key: str, event_data: dict | None = None):
    return types.SimpleNamespace(
        id=1,
        event_type=event_type,
        event_key=event_key,
        event_data=event_data or {},
        source="backend_auto",
        occurred_at=datetime(2025, 1, 1, 12, 4, 0, tzinfo=timezone.utc),
    )


def _run(fixture: dict) -> dict[str, str]:
    """Run adjudication for a fixture and return {item_id: state}."""
    scenario = _load_scenario_raw(fixture["scenario_id"])
    inputs = fixture["inputs"]
    effective_checklist = load_checklist(
        scenario, level="EMT", mca="mi_base", agency_id=None
    )
    call_type = scenario.get("call_type")
    if call_type:
        rubric = load_call_type_rubric(call_type, deployment_context="training")
        if rubric is not None:
            overlay_ops = load_scenario_overlay(fixture["scenario_id"], call_type)
            effective_checklist = compose_active_checklist(
                base_items=effective_checklist,
                rubric=rubric,
                provider_level="EMT",
                overlay_ops=overlay_ops,
                overlay_id=f"{fixture['scenario_id']}_overlay" if overlay_ops else "",
                scenario=scenario,
            ).items
    item_states = adjudicate(
        effective_checklist,
        interventions=[_iv(n) for n in inputs["interventions"]],
        session_findings=[_finding(**f) for f in inputs["findings"]],
        session_events=[_event(**e) for e in inputs.get("events", [])],
        chat_messages=[_msg(m) for m in inputs["messages"]],
        scene_entry=inputs.get("scene_entry"),
        submitted_dmist=inputs.get("dmist", ""),
        submitted_narrative=inputs.get("narrative", ""),
        scenario=scenario,
    )
    return {s.item_id: s.state for s in item_states}


# ── peds_syncope_01 fixtures ──────────────────────────────────────────────────

_SYNCOPE_FULL_CREDIT = {
    "scenario_id": "peds_syncope_01",
    "description": "syncope — full-credit: all clinical/scope items satisfied",
    "inputs": {
        "interventions": ["positioning_supine", "o2_nc", "ekg_monitoring"],
        "findings": [
            {"key": "blood_glucose", "value": "88 mg/dL", "finding_type": "vital"},
            {"key": "resp_rate", "value": "16", "finding_type": "vital"},
        ],
        "messages": [
            "What happened? Any warning before she passed out? Dizziness, nausea, tunnel vision?",
            "Any family history of sudden cardiac death or heart problems?",
            "Did she have any shaking or seizure activity while she was out?",
            "Checking blood glucose now — applying the cardiac monitor.",
            "Reassessing vitals after positioning — BP improving.",
            "Transporting to hospital — ALS updating en route.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves", "Eye Protection"]},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":       "satisfied",
        "ems.medical.primary_assessment": "satisfied",
        "ems.medical.history_attempt":    "satisfied",
        "ems.medical.focused_assessment": "satisfied",
        "ems.medical.reassessment":       "satisfied",
        "ems.medical.handoff":            "satisfied",
        "peds_syncope_01.prodrome_history":       "satisfied",
        "peds_syncope_01.cardiac_red_flag_screen":"satisfied",
        "peds_syncope_01.blood_glucose_checked":  "satisfied",
        "peds_syncope_01.seizure_screen":         "satisfied",
        "peds_syncope_01.supine_positioning":     "satisfied",
        "peds_syncope_01.protocol_supine_positioning": "satisfied",
        "peds_syncope_01.scope_cardiac_monitor":  "satisfied",
        "peds_syncope_01.scope_no_iv_io":         "satisfied",
    },
}

_SYNCOPE_CLINICAL_GAP = {
    "scenario_id": "peds_syncope_01",
    "description": "syncope — gap: missed cardiac screen, prodrome, seizure screen",
    "inputs": {
        "interventions": ["positioning_supine", "o2_nc", "ekg_monitoring"],
        "findings": [
            {"key": "blood_glucose", "value": "92 mg/dL", "finding_type": "vital"},
            {"key": "resp_rate", "value": "18", "finding_type": "vital"},
        ],
        "messages": [
            "What happened?",
            "Are you feeling okay now?",
        ],
        "scene_entry": {"ppe_donned": ["Gloves", "Eye Protection"]},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":       "satisfied",
        "ems.medical.primary_assessment": "satisfied",
        "ems.medical.history_attempt":    "satisfied",
        "ems.medical.focused_assessment": "not_satisfied",
        "ems.medical.reassessment":       "not_satisfied",
        "ems.medical.handoff":            "not_satisfied",
        "peds_syncope_01.prodrome_history":       "not_satisfied",
        "peds_syncope_01.cardiac_red_flag_screen":"not_satisfied",
        "peds_syncope_01.blood_glucose_checked":  "satisfied",
        "peds_syncope_01.seizure_screen":         "not_satisfied",
        "peds_syncope_01.supine_positioning":     "satisfied",
        "peds_syncope_01.protocol_supine_positioning": "satisfied",
        "peds_syncope_01.scope_cardiac_monitor":  "satisfied",
        "peds_syncope_01.scope_no_iv_io":         "satisfied",
    },
}

_SYNCOPE_SCOPE_VIOLATION = {
    "scenario_id": "peds_syncope_01",
    "description": "syncope — scope violation: IV/IO attempted by BLS provider",
    "inputs": {
        "interventions": [
            "positioning_supine", "o2_nc", "ekg_monitoring",
            "iv_io_access",
        ],
        "findings": [
            {"key": "blood_glucose", "value": "80 mg/dL", "finding_type": "vital"},
            {"key": "resp_rate", "value": "14", "finding_type": "vital"},
        ],
        "messages": [
            "Any warning before she passed out? Feeling dizzy or sick?",
            "Family history of heart problems or sudden death?",
            "Any shaking or twitching?",
        ],
        "scene_entry": {"ppe_donned": ["Gloves", "Eye Protection"]},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":       "satisfied",
        "ems.medical.primary_assessment": "satisfied",
        "ems.medical.history_attempt":    "not_satisfied",
        "ems.medical.focused_assessment": "not_satisfied",
        "ems.medical.reassessment":       "not_satisfied",
        "ems.medical.handoff":            "not_satisfied",
        "peds_syncope_01.prodrome_history":       "satisfied",
        "peds_syncope_01.cardiac_red_flag_screen":"satisfied",
        "peds_syncope_01.blood_glucose_checked":  "satisfied",
        "peds_syncope_01.seizure_screen":         "satisfied",
        "peds_syncope_01.supine_positioning":     "satisfied",
        "peds_syncope_01.protocol_supine_positioning": "satisfied",
        "peds_syncope_01.scope_cardiac_monitor":  "satisfied",
        "peds_syncope_01.scope_no_iv_io":         "not_satisfied",
    },
}

_SYNCOPE_PPE_GAP = {
    "scenario_id": "peds_syncope_01",
    "description": "syncope — PPE gap: no PPE donned (missing required gloves)",
    "inputs": {
        "interventions": ["positioning_supine", "o2_nc", "ekg_monitoring"],
        "findings": [
            {"key": "blood_glucose", "value": "76 mg/dL", "finding_type": "vital"},
        ],
        "messages": [
            "Any warning before she fainted? Nausea or tunnel vision?",
            "Family history of cardiac issues or sudden death?",
            "Did she have any seizure activity?",
        ],
        "scene_entry": {"ppe_donned": []},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":       "not_satisfied",
        "ems.medical.primary_assessment": "satisfied",
        "ems.medical.history_attempt":    "not_satisfied",
        "ems.medical.focused_assessment": "not_satisfied",
        "ems.medical.reassessment":       "not_satisfied",
        "ems.medical.handoff":            "not_satisfied",
        "peds_syncope_01.prodrome_history":       "satisfied",
        "peds_syncope_01.cardiac_red_flag_screen":"satisfied",
        "peds_syncope_01.blood_glucose_checked":  "satisfied",
        "peds_syncope_01.seizure_screen":         "satisfied",
        "peds_syncope_01.supine_positioning":     "satisfied",
        "peds_syncope_01.protocol_supine_positioning": "satisfied",
        "peds_syncope_01.scope_cardiac_monitor":  "satisfied",
        "peds_syncope_01.scope_no_iv_io":         "satisfied",
    },
}

_SYNCOPE_SCREEN_VIA_DMIST = {
    "scenario_id": "peds_syncope_01",
    "description": "syncope — DMIST text does not back-credit cardiac screen",
    "inputs": {
        "interventions": ["positioning_supine", "o2_nc", "ekg_monitoring"],
        "findings": [
            {"key": "blood_glucose", "value": "82 mg/dL", "finding_type": "vital"},
        ],
        "messages": [
            "Any warning before fainting? Nausea or dizziness?",
            "Any seizure activity while she was out?",
        ],
        "scene_entry": {"ppe_donned": ["Gloves", "Eye Protection"]},
        "dmist": "Family history screened — denied sudden cardiac death, denied palpitations or exercise-related symptoms.",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":       "satisfied",
        "ems.medical.primary_assessment": "satisfied",
        "ems.medical.history_attempt":    "not_satisfied",
        "ems.medical.focused_assessment": "not_satisfied",
        "ems.medical.reassessment":       "not_satisfied",
        "ems.medical.handoff":            "not_satisfied",
        "peds_syncope_01.prodrome_history":       "satisfied",
        "peds_syncope_01.cardiac_red_flag_screen":"not_satisfied",
        "peds_syncope_01.blood_glucose_checked":  "satisfied",
        "peds_syncope_01.seizure_screen":         "satisfied",
        "peds_syncope_01.supine_positioning":     "satisfied",
        "peds_syncope_01.protocol_supine_positioning": "satisfied",
        "peds_syncope_01.scope_cardiac_monitor":  "satisfied",
        "peds_syncope_01.scope_no_iv_io":         "satisfied",
    },
}

# ── adult_acs_01_stemi fixtures ───────────────────────────────────────────────

_ACS_FULL_CREDIT = {
    "scenario_id": "adult_acs_01_stemi",
    "description": "ACS STEMI — full-credit: all items satisfied",
    "inputs": {
        "interventions": ["positioning", "ekg_monitoring", "12_lead_ecg", "aspirin_po", "load_and_go"],
        "findings": [{"key": "hr", "value": "88", "finding_type": "vital"}],
        "messages": [
            "What medications are you on? Any allergies to aspirin?",
            "Let me get the cardiac monitor on and check your rhythm.",
            "Notifying cath lab — activating STEMI alert for Central City.",
            "Reassessing vitals en route to the hospital.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"]},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":       "satisfied",
        "ems.medical.primary_assessment": "satisfied",
        "ems.medical.history_attempt":    "satisfied",
        "ems.medical.focused_assessment": "satisfied",
        "ems.medical.reassessment":       "satisfied",
        "ems.medical.handoff":            "satisfied",
        "adult_acs_01_stemi.cardiac_monitoring":    "satisfied",
        "adult_acs_01_stemi.twelve_lead_ecg":       "satisfied",
        "adult_acs_01_stemi.aspirin_admin":         "satisfied",
        "adult_acs_01_stemi.priority_transport":    "satisfied",
        "adult_acs_01_stemi.hospital_notification": "satisfied",
        "adult_acs_01_stemi.protocol_aspirin_admin":"satisfied",
        "adult_acs_01_stemi.scope_position_comfort":"satisfied",
        "adult_acs_01_stemi.scope_no_iv_io":        "satisfied",
    },
}

_ACS_12LEAD_GAP = {
    "scenario_id": "adult_acs_01_stemi",
    "description": "ACS STEMI — gap: missed 12-lead ECG and hospital notification",
    "inputs": {
        "interventions": ["positioning", "ekg_monitoring", "aspirin_po", "load_and_go"],
        "findings": [{"key": "hr", "value": "92", "finding_type": "vital"}],
        "messages": ["Okay, loading now."],
        "scene_entry": {"ppe_donned": ["Gloves"]},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":       "satisfied",
        "ems.medical.primary_assessment": "satisfied",
        "ems.medical.history_attempt":    "not_satisfied",
        "ems.medical.focused_assessment": "not_satisfied",
        "ems.medical.reassessment":       "not_satisfied",
        "ems.medical.handoff":            "not_satisfied",
        "adult_acs_01_stemi.cardiac_monitoring":    "satisfied",
        "adult_acs_01_stemi.twelve_lead_ecg":       "not_satisfied",
        "adult_acs_01_stemi.aspirin_admin":         "satisfied",
        "adult_acs_01_stemi.priority_transport":    "satisfied",
        "adult_acs_01_stemi.hospital_notification": "not_satisfied",
        "adult_acs_01_stemi.protocol_aspirin_admin":"satisfied",
        "adult_acs_01_stemi.scope_position_comfort":"satisfied",
        "adult_acs_01_stemi.scope_no_iv_io":        "satisfied",
    },
}

_ACS_SCOPE_VIOLATION = {
    "scenario_id": "adult_acs_01_stemi",
    "description": "ACS STEMI — scope violation: IV/IO access by BLS provider",
    "inputs": {
        "interventions": ["positioning", "ekg_monitoring", "12_lead_ecg", "aspirin_po", "load_and_go", "iv_io_access"],
        "findings": [{"key": "hr", "value": "88", "finding_type": "vital"}],
        "messages": ["Notifying cath lab — STEMI activation."],
        "scene_entry": {"ppe_donned": ["Gloves"]},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":       "satisfied",
        "ems.medical.primary_assessment": "satisfied",
        "ems.medical.history_attempt":    "not_satisfied",
        "ems.medical.focused_assessment": "not_satisfied",
        "ems.medical.reassessment":       "not_satisfied",
        "ems.medical.handoff":            "not_satisfied",
        "adult_acs_01_stemi.cardiac_monitoring":    "satisfied",
        "adult_acs_01_stemi.twelve_lead_ecg":       "satisfied",
        "adult_acs_01_stemi.aspirin_admin":         "satisfied",
        "adult_acs_01_stemi.priority_transport":    "satisfied",
        "adult_acs_01_stemi.hospital_notification": "satisfied",
        "adult_acs_01_stemi.protocol_aspirin_admin":"satisfied",
        "adult_acs_01_stemi.scope_position_comfort":"satisfied",
        "adult_acs_01_stemi.scope_no_iv_io":        "not_satisfied",
    },
}

# ── peds_anaphylaxis_01 fixtures ──────────────────────────────────────────────

_ANAPHYLAXIS_FULL_CREDIT = {
    "scenario_id": "peds_anaphylaxis_01",
    "description": "anaphylaxis — full-credit: all items satisfied",
    "inputs": {
        "interventions": ["epinephrine_im", "o2_nrb", "positioning_supine"],
        "findings": [{"key": "hr", "value": "130", "finding_type": "vital"}],
        "messages": [
            "Any allergies? What happened? How long ago was the sting?",
            "This is anaphylaxis — epinephrine IM now.",
            "How much does she weigh? Checking weight for dosing.",
            "Checking her lung sounds — any bronchospasm?",
            "Updating ALS medics — weight-based dose administered, time noted.",
            "Reassessing BP and SpO2 after epinephrine.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":                      "satisfied",
        "ems.medical.primary_assessment":                "satisfied",
        "ems.medical.history_attempt":                   "satisfied",
        "ems.medical.focused_assessment":                "satisfied",
        "ems.medical.reassessment":                      "satisfied",
        "ems.medical.handoff":                           "satisfied",
        "peds_anaphylaxis_01.pat_assessment":            "satisfied",
        "peds_anaphylaxis_01.anaphylaxis_recognition":   "satisfied",
        "peds_anaphylaxis_01.epinephrine_im":            "satisfied",
        "peds_anaphylaxis_01.weight_dosing_check":       "satisfied",
        "peds_anaphylaxis_01.scope_o2_nrb":              "satisfied",
        "peds_anaphylaxis_01.scope_positioning_supine":  "satisfied",
        "peds_anaphylaxis_01.scope_no_iv_io":            "satisfied",
    },
}

_ANAPHYLAXIS_EPI_GAP = {
    "scenario_id": "peds_anaphylaxis_01",
    "description": "anaphylaxis — gap: missed epinephrine, recognition, weight check; no reassessment, focused assessment, or handoff",
    "inputs": {
        "interventions": ["o2_nrb", "positioning_supine"],
        "findings": [{"key": "hr", "value": "130", "finding_type": "vital"}],
        "messages": [
            "She's having an allergic reaction.",
            "Let's get some oxygen on her.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":                      "satisfied",
        "ems.medical.primary_assessment":                "satisfied",
        "ems.medical.history_attempt":                   "satisfied",
        "ems.medical.focused_assessment":                "not_satisfied",
        "ems.medical.reassessment":                      "not_satisfied",
        "ems.medical.handoff":                           "not_satisfied",
        "peds_anaphylaxis_01.pat_assessment":            "satisfied",
        "peds_anaphylaxis_01.anaphylaxis_recognition":   "not_satisfied",
        "peds_anaphylaxis_01.epinephrine_im":            "not_satisfied",
        "peds_anaphylaxis_01.weight_dosing_check":       "not_satisfied",
        "peds_anaphylaxis_01.scope_o2_nrb":              "satisfied",
        "peds_anaphylaxis_01.scope_positioning_supine":  "satisfied",
        "peds_anaphylaxis_01.scope_no_iv_io":            "satisfied",
    },
}

_ANAPHYLAXIS_SCOPE_VIOLATION = {
    "scenario_id": "peds_anaphylaxis_01",
    "description": "anaphylaxis — scope violation: IV/IO access by BLS provider",
    "inputs": {
        "interventions": ["epinephrine_im", "o2_nrb", "positioning_supine", "iv_io_access"],
        "findings": [{"key": "hr", "value": "130", "finding_type": "vital"}],
        "messages": [
            "Anaphylaxis — epinephrine IM now.",
            "Checking weight for dosing.",
            "Notifying ALS — dose and time reported.",
            "Reassessing BP and SpO2 after epinephrine.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":                      "satisfied",
        "ems.medical.primary_assessment":                "satisfied",
        "ems.medical.history_attempt":                   "not_satisfied",
        "ems.medical.focused_assessment":                "not_satisfied",
        "ems.medical.reassessment":                      "satisfied",
        "ems.medical.handoff":                           "satisfied",
        "peds_anaphylaxis_01.pat_assessment":            "satisfied",
        "peds_anaphylaxis_01.anaphylaxis_recognition":   "satisfied",
        "peds_anaphylaxis_01.epinephrine_im":            "satisfied",
        "peds_anaphylaxis_01.weight_dosing_check":       "satisfied",
        "peds_anaphylaxis_01.scope_o2_nrb":              "satisfied",
        "peds_anaphylaxis_01.scope_positioning_supine":  "satisfied",
        "peds_anaphylaxis_01.scope_no_iv_io":            "not_satisfied",
    },
}

# ── peds_asthma_01 fixtures ───────────────────────────────────────────────────

_ASTHMA_FULL_CREDIT = {
    "scenario_id": "peds_asthma_01",
    "description": "asthma — full-credit: all items satisfied",
    "inputs": {
        "interventions": ["o2_nrb", "albuterol_svn", "positioning"],
        "findings": [
            {"key": "hr", "value": "110", "finding_type": "vital"},
            {"key": "breath_sounds", "value": "bilateral wheezing", "finding_type": "exam"},
        ],
        "messages": [
            "What happened? Any asthma history? Any chance he choked on something?",
            "Reassessing breath sounds after albuterol treatment.",
            "Ready for ALS handoff.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":                 "satisfied",
        "ems.medical.primary_assessment":           "satisfied",
        "ems.medical.history_attempt":              "satisfied",
        "ems.medical.focused_assessment":           "satisfied",
        "ems.medical.reassessment":                 "satisfied",
        "ems.medical.handoff":                      "satisfied",
        "peds_asthma_01.pat_assessment":            "satisfied",
        "peds_asthma_01.albuterol_svn":             "satisfied",
        "peds_asthma_01.foreign_body_screen":       "satisfied",
        "peds_asthma_01.scope_no_iv_io":            "satisfied",
    },
}

_ASTHMA_ALBUTEROL_GAP = {
    "scenario_id": "peds_asthma_01",
    "description": "asthma — gap: missed albuterol; no reassessment, focused assessment, or handoff",
    "inputs": {
        "interventions": ["o2_nrb", "positioning"],
        "findings": [
            {"key": "hr", "value": "110", "finding_type": "vital"},
            {"key": "auscultation", "value": "equal air entry bilaterally", "finding_type": "exam"},
        ],
        "messages": [
            "What happened? Any chance he swallowed something? Any asthma history?",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":                 "satisfied",
        "ems.medical.primary_assessment":           "satisfied",
        "ems.medical.history_attempt":              "satisfied",
        "ems.medical.focused_assessment":           "satisfied",
        "ems.medical.reassessment":                 "not_satisfied",
        "ems.medical.handoff":                      "not_satisfied",
        "peds_asthma_01.pat_assessment":            "satisfied",
        "peds_asthma_01.albuterol_svn":             "not_satisfied",
        "peds_asthma_01.foreign_body_screen":       "satisfied",
        "peds_asthma_01.scope_no_iv_io":            "satisfied",
    },
}

# ── peds_croup_01 fixtures ────────────────────────────────────────────────────

_CROUP_FULL_CREDIT = {
    "scenario_id": "peds_croup_01",
    "description": "croup — full-credit: all items satisfied",
    "inputs": {
        "interventions": ["positioning", "o2_blowby", "als_intercept"],
        "findings": [
            {"key": "hr", "value": "112", "finding_type": "vital"},
            {"key": "breath_sounds", "value": "inspiratory stridor, clear lower lung fields", "finding_type": "exam"},
        ],
        "messages": [
            "She has barking cough and stridor — this is croup.",
            "What happened and when did this start?",
            "Any drooling? Tripod positioning? High fever? Sudden onset?",
            "Auscultating lung sounds now.",
            "Reassessing stridor and SpO2 after oxygen now.",
            "Giving ALS report with her weight and current status.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":          "satisfied",
        "ems.medical.primary_assessment":    "satisfied",
        "ems.medical.history_attempt":       "satisfied",
        "ems.medical.focused_assessment":    "satisfied",
        "ems.medical.reassessment":          "satisfied",
        "ems.medical.handoff":               "satisfied",
        "peds_croup_01.pat_assessment":      "satisfied",
        "peds_croup_01.lung_sound_auscultation": "satisfied",
        "peds_croup_01.croup_recognition":   "satisfied",
        "peds_croup_01.positioning_calm":    "satisfied",
        "peds_croup_01.o2_blowby":           "satisfied",
        "peds_croup_01.epiglottitis_screen": "satisfied",
        "peds_croup_01.scope_no_albuterol":  "satisfied",
        "peds_croup_01.scope_no_iv_io":      "satisfied",
    },
}

_CROUP_ALS_GAP = {
    "scenario_id": "peds_croup_01",
    "description": "croup — gap: missed ALS intercept and epiglottitis screen",
    "inputs": {
        "interventions": ["positioning", "o2_blowby"],
        "findings": [{"key": "hr", "value": "112", "finding_type": "vital"}],
        "messages": [
            "Barking cough — classic croup presentation.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":          "satisfied",
        "ems.medical.primary_assessment":    "satisfied",
        "ems.medical.history_attempt":       "not_satisfied",
        "ems.medical.focused_assessment":    "not_satisfied",
        "ems.medical.reassessment":          "not_satisfied",
        "ems.medical.handoff":               "not_satisfied",
        "peds_croup_01.pat_assessment":      "satisfied",
        "peds_croup_01.lung_sound_auscultation": "not_satisfied",
        "peds_croup_01.croup_recognition":   "satisfied",
        "peds_croup_01.positioning_calm":    "satisfied",
        "peds_croup_01.o2_blowby":           "satisfied",
        "peds_croup_01.epiglottitis_screen": "not_satisfied",
        "peds_croup_01.scope_no_albuterol":  "satisfied",
        "peds_croup_01.scope_no_iv_io":      "satisfied",
    },
}

_CROUP_SPARSE_RECENT_RUN = {
    "scenario_id": "peds_croup_01",
    "description": "croup — sparse recent run: O2 only, docs cannot back-credit gaps",
    "inputs": {
        "interventions": ["o2_blowby"],
        "findings": [
            {"key": "SpO2", "value": "93 %", "finding_type": "vital"},
            {"key": "Heart Rate", "value": "148 bpm", "finding_type": "vital"},
            {"key": "WOB", "value": "abnormal forceful coughing with noisy airflow", "finding_type": "exam"},
        ],
        "messages": [
            "hi my name is John what's going on",
            "get spo2 and heart rate",
            "admin O2",
            "any better",
        ],
        "events": [
            {
                "event_type": "challenge_completed",
                "event_key": "impression:croup",
                "event_data": {"challenge_type": "impression", "result": "correct"},
            }
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": (
            "D - Lily, 10-month-old female, 9 kg. "
            "M - Suspected croup. "
            "I - Blow-by O2 at 15 LPM with NRB, infant in mother's arms, calm environment. "
            "S - SpO2 improved to 95%, RR 44, HR 155, temp 100.4. "
            "T - Patient improving and ready for ALS handoff."
        ),
        "narrative": (
            "Primary assessment: SpO2 94%, RR 38, HR 132, temp 100.4. "
            "Lung sounds clear bilaterally. Blow-by O2 at 15 LPM with NRB. "
            "Infant kept with mother in a calm environment. Reassessment: SpO2 improved to 95%. "
            "Weight communicated to ALS."
        ),
    },
    "expected_states": {
        "ems.medical.scene_safety":          "satisfied",
        "ems.medical.primary_assessment":    "satisfied",
        "ems.medical.history_attempt":       "satisfied",
        "ems.medical.focused_assessment":    "satisfied",
        "ems.medical.reassessment":          "satisfied",
        "ems.medical.handoff":               "not_satisfied",
        "peds_croup_01.pat_assessment":      "satisfied",
        "peds_croup_01.lung_sound_auscultation": "not_satisfied",
        "peds_croup_01.croup_recognition":   "satisfied",
        "peds_croup_01.positioning_calm":    "not_satisfied",
        "peds_croup_01.o2_blowby":           "satisfied",
        "peds_croup_01.epiglottitis_screen": "not_satisfied",
        "peds_croup_01.scope_no_albuterol":  "satisfied",
        "peds_croup_01.scope_no_iv_io":      "satisfied",
    },
}

_CROUP_SCOPE_VIOLATION = {
    "scenario_id": "peds_croup_01",
    "description": "croup — scope violation: albuterol given (wrong treatment for croup)",
    "inputs": {
        "interventions": ["positioning", "o2_blowby", "als_intercept", "albuterol_svn"],
        "findings": [
            {"key": "hr", "value": "112", "finding_type": "vital"},
            {"key": "breath_sounds", "value": "inspiratory stridor, clear lower lung fields", "finding_type": "exam"},
        ],
        "messages": [
            "Barking cough and stridor — this is croup.",
            "What happened and when did this start?",
            "Any drooling or high fever? Sudden onset?",
            "Auscultating lung sounds now.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":          "satisfied",
        "ems.medical.primary_assessment":    "satisfied",
        "ems.medical.history_attempt":       "satisfied",
        "ems.medical.focused_assessment":    "satisfied",
        "ems.medical.reassessment":          "not_satisfied",
        "ems.medical.handoff":               "not_satisfied",
        "peds_croup_01.pat_assessment":      "satisfied",
        "peds_croup_01.lung_sound_auscultation": "satisfied",
        "peds_croup_01.croup_recognition":   "satisfied",
        "peds_croup_01.positioning_calm":    "satisfied",
        "peds_croup_01.o2_blowby":           "satisfied",
        "peds_croup_01.epiglottitis_screen": "satisfied",
        "peds_croup_01.scope_no_albuterol":  "not_satisfied",
        "peds_croup_01.scope_no_iv_io":      "satisfied",
    },
}

# ── peds_diabetic_emergency_01 fixtures ───────────────────────────────────────

_DIABETIC_FULL_CREDIT = {
    "scenario_id": "peds_diabetic_emergency_01",
    "description": "diabetic emergency — full-credit: all items satisfied",
    "inputs": {
        "interventions": ["oral_glucose", "o2_supplemental"],
        "findings": [
            {"key": "hr", "value": "95", "finding_type": "vital"},
            {"key": "blood_glucose", "value": "42 mg/dL", "finding_type": "vital", "source": "glucometer_check"},
        ],
        "messages": [
            "What medications is she on? Does she have a history of diabetes or an insulin pump?",
            "Checking her blood glucose now — finger stick.",
            "Can she swallow? Is she alert enough to protect her airway?",
            "ALS update — patient is 38kg, BGL 42, oral glucose given.",
            "Reassessing mental status after oral glucose.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":                              "satisfied",
        "ems.medical.primary_assessment":                        "satisfied",
        "ems.medical.history_attempt":                           "satisfied",
        "ems.medical.focused_assessment":                        "satisfied",
        "ems.medical.reassessment":                              "satisfied",
        "ems.medical.handoff":                                   "satisfied",
        "ems.medical.repeat_vitals":                             "satisfied",
        "ems.medical.sample_history":                            "satisfied",
        "ems.medical.treatment_response":                        "satisfied",
        "peds_diabetic_emergency_01.pat_assessment":             "satisfied",
        "peds_diabetic_emergency_01.history_diabetes":           "satisfied",
        "hypoglycemia.blood_glucose_check":                      "satisfied",
        "hypoglycemia.swallow_assessment":                       "satisfied",
        "hypoglycemia.oral_glucose_administered":                "satisfied",
        "peds_diabetic_emergency_01.protocol_oral_glucose":      "satisfied",
        "peds_diabetic_emergency_01.scope_no_iv_io":             "satisfied",
    },
}

_DIABETIC_GLUCOSE_GAP = {
    "scenario_id": "peds_diabetic_emergency_01",
    "description": "diabetic emergency — gap: missed glucose check, swallow screen, oral glucose; no history, focused assessment, reassessment, or handoff",
    "inputs": {
        "interventions": ["o2_supplemental"],
        "findings": [{"key": "hr", "value": "95", "finding_type": "vital"}],
        "messages": ["She seems confused. Let's get her on O2."],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":                              "satisfied",
        "ems.medical.primary_assessment":                        "satisfied",
        "ems.medical.history_attempt":                           "not_satisfied",
        "ems.medical.focused_assessment":                        "not_satisfied",
        "ems.medical.reassessment":                              "not_satisfied",
        "ems.medical.handoff":                                   "not_satisfied",
        "ems.medical.repeat_vitals":                             "not_satisfied",
        "ems.medical.sample_history":                            "not_satisfied",
        "ems.medical.treatment_response":                        "not_satisfied",
        "peds_diabetic_emergency_01.pat_assessment":             "satisfied",
        "peds_diabetic_emergency_01.history_diabetes":           "not_satisfied",
        "hypoglycemia.blood_glucose_check":                      "not_satisfied",
        "hypoglycemia.swallow_assessment":                       "not_satisfied",
        "hypoglycemia.oral_glucose_administered":                "not_satisfied",
        "peds_diabetic_emergency_01.protocol_oral_glucose":      "not_satisfied",
        "peds_diabetic_emergency_01.scope_no_iv_io":             "satisfied",
    },
}

_DIABETIC_SCOPE_VIOLATION = {
    "scenario_id": "peds_diabetic_emergency_01",
    "description": "diabetic emergency — scope violation: attempted glucagon by BLS provider",
    "inputs": {
        "interventions": ["oral_glucose"],
        "findings": [
            {"key": "blood_glucose", "value": "42 mg/dL", "finding_type": "vital", "source": "glucometer_check"},
        ],
        "messages": [
            "What medications is she on? Does she have a history of diabetes or an insulin pump?",
            "Checking her blood glucose now — finger stick.",
            "Can she swallow? Is she alert enough to protect her airway?",
            "Give him glucagon now.",
            "Reassessing mental status after oral glucose.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.repeat_vitals":                             "satisfied",
        "ems.medical.sample_history":                            "satisfied",
        "ems.medical.treatment_response":                        "satisfied",
        "peds_diabetic_emergency_01.pat_assessment":             "satisfied",
        "peds_diabetic_emergency_01.history_diabetes":           "satisfied",
        "hypoglycemia.blood_glucose_check":                      "satisfied",
        "hypoglycemia.swallow_assessment":                       "satisfied",
        "hypoglycemia.oral_glucose_administered":                "satisfied",
        "peds_diabetic_emergency_01.protocol_oral_glucose":      "satisfied",
        "peds_diabetic_emergency_01.scope_no_iv_io":             "not_satisfied",
    },
}

_DIABETIC_CGM_ONLY_GAP = {
    "scenario_id": "peds_diabetic_emergency_01",
    "description": "diabetic emergency — gap: CGM history only does not satisfy on-scene glucometer check",
    "inputs": {
        "interventions": ["oral_glucose"],
        "findings": [
            {"key": "CGM", "value": "38 mg/dL", "finding_type": "history"},
        ],
        "messages": [
            "What medications is she on? Does she have a history of diabetes or an insulin pump?",
            "What was the CGM reading?",
            "Can she swallow? Is she alert enough to protect her airway?",
            "Administer oral glucose.",
            "Reassessing mental status after oral glucose.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.repeat_vitals":                             "satisfied",
        "ems.medical.sample_history":                            "satisfied",
        "ems.medical.treatment_response":                        "satisfied",
        "peds_diabetic_emergency_01.pat_assessment":             "satisfied",
        "peds_diabetic_emergency_01.history_diabetes":           "satisfied",
        "hypoglycemia.blood_glucose_check":                      "not_satisfied",
        "hypoglycemia.swallow_assessment":                       "satisfied",
        "hypoglycemia.oral_glucose_administered":                "satisfied",
        "peds_diabetic_emergency_01.protocol_oral_glucose":      "satisfied",
        "peds_diabetic_emergency_01.scope_no_iv_io":             "satisfied",
    },
}

# ── peds_febrile_seizure_01 fixtures ──────────────────────────────────────────

_FEBRILE_SEIZURE_FULL_CREDIT = {
    "scenario_id": "peds_febrile_seizure_01",
    "description": "febrile seizure — full-credit: all items satisfied",
    "inputs": {
        "interventions": ["recovery_position", "suction_airway", "o2_nrb"],
        "findings": [
            {"key": "hr", "value": "118", "finding_type": "vital"},
            {"key": "temperature", "value": "39.8C", "finding_type": "vital"},
        ],
        "messages": [
            "Clear the area, don't restrain her, and don't put anything in her mouth.",
            "How long has she been seizing? Any history of seizures? First time?",
            "Monitoring her airway and watching the active seizure activity.",
            "Reassessing her after suction and oxygen — checking vitals and responsiveness.",
            "ALS en route — updating them on the febrile seizure presentation.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":       "satisfied",
        "ems.medical.primary_assessment": "satisfied",
        "ems.medical.history_attempt":    "satisfied",
        "ems.medical.focused_assessment": "satisfied",
        "ems.medical.reassessment":       "satisfied",
        "ems.medical.handoff":            "satisfied",
        "peds_febrile_seizure_01.pat_assessment":         "satisfied",
        "peds_febrile_seizure_01.recovery_position":      "satisfied",
        "peds_febrile_seizure_01.suction_airway":          "satisfied",
        "peds_febrile_seizure_01.protect_from_injury":     "satisfied",
        "peds_febrile_seizure_01.seizure_history":        "satisfied",
        "peds_febrile_seizure_01.temperature_assessment": "satisfied",
        "peds_febrile_seizure_01.protocol_suction_airway": "satisfied",
        "peds_febrile_seizure_01.scope_o2_protocol":      "satisfied",
        "peds_febrile_seizure_01.scope_no_iv_io":         "satisfied",
    },
}

_FEBRILE_SEIZURE_AIRWAY_GAP = {
    "scenario_id": "peds_febrile_seizure_01",
    "description": "febrile seizure — gap: missed recovery position and O2",
    "inputs": {
        "interventions": [],
        "findings": [
            {"key": "hr", "value": "118", "finding_type": "vital"},
            {"key": "temperature", "value": "39.8C", "finding_type": "vital"},
        ],
        "messages": [
            "How long did the seizure last? Has she had seizures before?",
            "Keep monitoring her breathing.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.medical.scene_safety":       "satisfied",
        "ems.medical.primary_assessment": "satisfied",
        "ems.medical.history_attempt":    "satisfied",
        "ems.medical.focused_assessment": "satisfied",
        "ems.medical.reassessment":       "not_satisfied",
        "ems.medical.handoff":            "not_satisfied",
        "peds_febrile_seizure_01.pat_assessment":         "satisfied",
        "peds_febrile_seizure_01.recovery_position":      "not_satisfied",
        "peds_febrile_seizure_01.suction_airway":          "not_satisfied",
        "peds_febrile_seizure_01.protect_from_injury":     "not_satisfied",
        "peds_febrile_seizure_01.seizure_history":        "satisfied",
        "peds_febrile_seizure_01.temperature_assessment": "satisfied",
        "peds_febrile_seizure_01.protocol_suction_airway": "not_satisfied",
        "peds_febrile_seizure_01.scope_o2_protocol":      "not_satisfied",
        "peds_febrile_seizure_01.scope_no_iv_io":         "satisfied",
    },
}

# ── peds_trauma_01_soft_tissue fixtures ───────────────────────────────────────

_SOFT_TISSUE_FULL_CREDIT = {
    "scenario_id": "peds_trauma_01_soft_tissue",
    "description": "soft tissue trauma — full-credit: all items satisfied",
    "inputs": {
        "interventions": ["direct_pressure", "neuro_assessment"],
        "findings": [
            {"key": "hr", "value": "108", "finding_type": "vital"},
            {"key": "GCS", "value": "15 (E4 V5 M6)", "finding_type": "exam"},
            {"key": "Pupils", "value": "PERRL, equal and reactive", "finding_type": "exam"},
            {"key": "LOC", "value": "no loss of consciousness; cried immediately", "finding_type": "history"},
            {"key": "Events", "value": "running, tripped, fell and struck coffee table corner", "finding_type": "history"},
        ],
        "messages": [
            "How did she fall? How high? What surface did she land on?",
            "Applying direct pressure — pressure dressing in place.",
            "Checking pupils and neuro status — GCS assessment.",
            "We'll transport her to the pediatric emergency department for evaluation.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.trauma.scene_safety":          "satisfied",
        "ems.trauma.primary_assessment":    "satisfied",
        "ems.trauma.mechanism_assessment":  "satisfied",
        "ems.trauma.hemorrhage_control":    "satisfied",
        "ems.trauma.secondary_assessment":  "satisfied",
        "ems.trauma.priority_transport":    "satisfied",
        "ems.trauma.transport_handoff":     "satisfied",
        "peds_trauma_01_soft_tissue.pat_assessment":              "satisfied",
        "peds_trauma_01_soft_tissue.direct_pressure":             "satisfied",
        "peds_trauma_01_soft_tissue.neuro_baseline":              "satisfied",
        "peds_trauma_01_soft_tissue.neuro_history":               "satisfied",
        "peds_trauma_01_soft_tissue.mechanism_screen":            "satisfied",
        "peds_trauma_01_soft_tissue.transport_decision":          "satisfied",
        "peds_trauma_01_soft_tissue.scope_no_iv_pain_medication": "satisfied",
        "peds_trauma_01_soft_tissue.scope_hemorrhage_control":    "satisfied",
    },
}

_SOFT_TISSUE_HEMORRHAGE_GAP = {
    "scenario_id": "peds_trauma_01_soft_tissue",
    "description": "soft tissue trauma — gap: missed direct pressure, neuro assessment, mechanism screen, transport decision",
    "inputs": {
        "interventions": [],
        "findings": [{"key": "hr", "value": "108", "finding_type": "vital"}],
        "messages": ["Is she okay?"],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.trauma.scene_safety":          "satisfied",
        "ems.trauma.primary_assessment":    "satisfied",
        "ems.trauma.mechanism_assessment":  "not_satisfied",
        "ems.trauma.hemorrhage_control":    "not_satisfied",
        "ems.trauma.secondary_assessment":  "not_satisfied",
        "ems.trauma.priority_transport":    "not_satisfied",
        "ems.trauma.transport_handoff":     "not_satisfied",
        "peds_trauma_01_soft_tissue.pat_assessment":              "satisfied",
        "peds_trauma_01_soft_tissue.direct_pressure":             "not_satisfied",
        "peds_trauma_01_soft_tissue.neuro_baseline":              "not_satisfied",
        "peds_trauma_01_soft_tissue.neuro_history":               "not_satisfied",
        "peds_trauma_01_soft_tissue.mechanism_screen":            "not_satisfied",
        "peds_trauma_01_soft_tissue.transport_decision":          "not_satisfied",
        "peds_trauma_01_soft_tissue.scope_no_iv_pain_medication": "satisfied",
        "peds_trauma_01_soft_tissue.scope_hemorrhage_control":    "not_satisfied",
    },
}

# ── peds_trauma_02_partial_choking fixtures ────────────────────────────────────

_CHOKING_FULL_CREDIT = {
    "scenario_id": "peds_trauma_02_partial_choking",
    "description": "partial choking — full-credit: all items satisfied",
    "inputs": {
        "interventions": ["encourage_coughing", "o2_blowby"],
        "findings": [{"key": "hr", "value": "105", "finding_type": "vital"}],
        "messages": [
            "What happened? How long has she been choking on the grape?",
            "Partial obstruction — effective cough, moving air. Let her cough it out.",
            "Checking her head and neck — airway patent.",
            "Monitoring her airway closely for complete obstruction or worsening.",
            "We need to transport her to the emergency department now.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.trauma.scene_safety":          "satisfied",
        "ems.trauma.primary_assessment":    "satisfied",
        "ems.trauma.mechanism_assessment":  "satisfied",
        "ems.trauma.hemorrhage_control":    "not_satisfied",
        "ems.trauma.secondary_assessment":  "satisfied",
        "ems.trauma.transport_handoff":     "satisfied",
        "peds_trauma_02_partial_choking.pat_assessment":                     "satisfied",
        "peds_trauma_02_partial_choking.partial_obstruction_classification":  "satisfied",
        "peds_trauma_02_partial_choking.encourage_coughing":                 "satisfied",
        "peds_trauma_02_partial_choking.airway_monitoring":                  "satisfied",
        "peds_trauma_02_partial_choking.rapid_transport":                    "satisfied",
        "peds_trauma_02_partial_choking.scope_no_back_blows":                "satisfied",
        "peds_trauma_02_partial_choking.scope_o2_blowby":                    "satisfied",
    },
}

_CHOKING_CLASSIFICATION_GAP = {
    "scenario_id": "peds_trauma_02_partial_choking",
    "description": "partial choking — gap: missed obstruction classification, coughing intervention, monitoring, transport",
    "inputs": {
        "interventions": ["o2_blowby"],
        "findings": [{"key": "hr", "value": "105", "finding_type": "vital"}],
        # empty messages: rapid_transport T2 matches "go" as substring in many words,
        # so silence is the only safe way to keep all T2 items not_satisfied
        "messages": [],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.trauma.scene_safety":          "satisfied",
        "ems.trauma.primary_assessment":    "satisfied",
        "ems.trauma.mechanism_assessment":  "not_satisfied",
        "ems.trauma.hemorrhage_control":    "not_satisfied",
        "ems.trauma.secondary_assessment":  "not_satisfied",
        "ems.trauma.transport_handoff":     "not_satisfied",
        "peds_trauma_02_partial_choking.pat_assessment":                     "satisfied",
        "peds_trauma_02_partial_choking.partial_obstruction_classification":  "not_satisfied",
        "peds_trauma_02_partial_choking.encourage_coughing":                 "not_satisfied",
        "peds_trauma_02_partial_choking.airway_monitoring":                  "not_satisfied",
        "peds_trauma_02_partial_choking.rapid_transport":                    "not_satisfied",
        "peds_trauma_02_partial_choking.scope_no_back_blows":                "satisfied",
        "peds_trauma_02_partial_choking.scope_o2_blowby":                    "satisfied",
    },
}

_CHOKING_SCOPE_VIOLATION = {
    "scenario_id": "peds_trauma_02_partial_choking",
    "description": "partial choking — scope violation: back blows applied for partial obstruction",
    "inputs": {
        "interventions": ["encourage_coughing", "o2_blowby", "back_blows"],
        "findings": [{"key": "hr", "value": "105", "finding_type": "vital"}],
        "messages": [
            "Partial obstruction — effective cough, moving air. Let her cough.",
            "Monitoring her airway closely.",
            "Transport to emergency department now.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.trauma.scene_safety":          "satisfied",
        "ems.trauma.primary_assessment":    "satisfied",
        "ems.trauma.mechanism_assessment":  "not_satisfied",
        "ems.trauma.hemorrhage_control":    "not_satisfied",
        "ems.trauma.secondary_assessment":  "not_satisfied",
        "ems.trauma.transport_handoff":     "satisfied",
        "peds_trauma_02_partial_choking.pat_assessment":                     "satisfied",
        "peds_trauma_02_partial_choking.partial_obstruction_classification":  "satisfied",
        "peds_trauma_02_partial_choking.encourage_coughing":                 "satisfied",
        "peds_trauma_02_partial_choking.airway_monitoring":                  "satisfied",
        "peds_trauma_02_partial_choking.rapid_transport":                    "satisfied",
        "peds_trauma_02_partial_choking.scope_no_back_blows":                "not_satisfied",
        "peds_trauma_02_partial_choking.scope_o2_blowby":                    "satisfied",
    },
}

# ── peds_trauma_03_extremity fixtures ─────────────────────────────────────────

_EXTREMITY_FULL_CREDIT = {
    "scenario_id": "peds_trauma_03_extremity",
    "description": "extremity fracture — full-credit: all items satisfied",
    "inputs": {
        "interventions": ["assess_cms", "realign_fracture", "splinting", "assess_cms_post"],
        "findings": [{"key": "hr", "value": "98", "finding_type": "vital"}],
        "messages": [
            "She fell from the monkey bars — what happened and how high was the fall?",
            "CMS check before splinting — cap refill 3 sec, paresthesia in left hand.",
            "Gentle realignment performed — now securing with padded SAM splint and bandage.",
            "Transporting to ED — ALS notified of CMS findings and realignment performed.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.trauma.scene_safety":          "satisfied",
        "ems.trauma.primary_assessment":    "satisfied",
        "ems.trauma.mechanism_assessment":  "satisfied",
        "ems.trauma.hemorrhage_control":    "satisfied",
        "ems.trauma.secondary_assessment":  "satisfied",
        "ems.trauma.transport_handoff":     "satisfied",
        "peds_trauma_03_extremity.pat_assessment":               "satisfied",
        "peds_trauma_03_extremity.cms_pre_assessment":           "satisfied",
        "peds_trauma_03_extremity.fracture_realignment":         "satisfied",
        "peds_trauma_03_extremity.splinting":                    "satisfied",
        "peds_trauma_03_extremity.cms_post_assessment":          "satisfied",
        "peds_trauma_03_extremity.scope_no_iv_pain_medication":  "satisfied",
        "peds_trauma_03_extremity.scope_immobilization_applied": "satisfied",
    },
}

_EXTREMITY_CMS_GAP = {
    "scenario_id": "peds_trauma_03_extremity",
    "description": "extremity fracture — gap: missed pre and post CMS assessment",
    "inputs": {
        "interventions": ["realign_fracture", "splinting"],
        "findings": [{"key": "hr", "value": "98", "finding_type": "vital"}],
        "messages": [],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.trauma.scene_safety":          "satisfied",
        "ems.trauma.primary_assessment":    "satisfied",
        "ems.trauma.mechanism_assessment":  "not_satisfied",
        "ems.trauma.hemorrhage_control":    "not_satisfied",
        "ems.trauma.secondary_assessment":  "not_satisfied",
        "ems.trauma.transport_handoff":     "not_satisfied",
        "peds_trauma_03_extremity.pat_assessment":               "satisfied",
        "peds_trauma_03_extremity.cms_pre_assessment":           "not_satisfied",
        "peds_trauma_03_extremity.fracture_realignment":         "satisfied",
        "peds_trauma_03_extremity.splinting":                    "satisfied",
        "peds_trauma_03_extremity.cms_post_assessment":          "not_satisfied",
        "peds_trauma_03_extremity.scope_no_iv_pain_medication":  "satisfied",
        "peds_trauma_03_extremity.scope_immobilization_applied": "satisfied",
    },
}

# ── peds_trauma_04_burn fixtures ──────────────────────────────────────────────

_BURN_FULL_CREDIT = {
    "scenario_id": "peds_trauma_04_burn",
    "description": "burn — full-credit: all items satisfied",
    "inputs": {
        "interventions": ["remove_clothing", "airway_assessment", "dry_dressing", "prevent_hypothermia"],
        "findings": [{"key": "hr", "value": "105", "finding_type": "vital"}],
        "messages": [
            "What happened? Hot coffee onto his chest and arm.",
            "Removing wet coffee-soaked clothing immediately.",
            "Airway screen — checking soot and singed hairs.",
            "Applying dry sterile burn dressings to the burned areas.",
            "Transporting to pediatric burn center — ALS notified.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.trauma.scene_safety":          "satisfied",
        "ems.trauma.primary_assessment":    "satisfied",
        "ems.trauma.mechanism_assessment":  "satisfied",
        "ems.trauma.hemorrhage_control":    "satisfied",
        "ems.trauma.secondary_assessment":  "satisfied",
        "ems.trauma.transport_handoff":     "satisfied",
        "peds_trauma_04_burn.pat_assessment":              "satisfied",
        "peds_trauma_04_burn.stop_burning":                "satisfied",
        "peds_trauma_04_burn.airway_screen":               "satisfied",
        "peds_trauma_04_burn.dry_dressing":                "satisfied",
        "peds_trauma_04_burn.prevent_hypothermia":         "satisfied",
        "peds_trauma_04_burn.scope_no_wet_dressings":      "satisfied",
        "peds_trauma_04_burn.scope_no_iv_pain_medication": "satisfied",
    },
}

_BURN_STOP_BURNING_GAP = {
    "scenario_id": "peds_trauma_04_burn",
    "description": "burn — gap: missed clothing removal to stop burning process",
    "inputs": {
        "interventions": ["airway_assessment", "dry_dressing", "prevent_hypothermia"],
        "findings": [{"key": "hr", "value": "105", "finding_type": "vital"}],
        "messages": [],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.trauma.scene_safety":          "satisfied",
        "ems.trauma.primary_assessment":    "satisfied",
        "ems.trauma.mechanism_assessment":  "not_satisfied",
        "ems.trauma.hemorrhage_control":    "not_satisfied",
        "ems.trauma.secondary_assessment":  "not_satisfied",
        "ems.trauma.transport_handoff":     "not_satisfied",
        "peds_trauma_04_burn.pat_assessment":              "satisfied",
        "peds_trauma_04_burn.stop_burning":                "not_satisfied",
        "peds_trauma_04_burn.airway_screen":               "satisfied",
        "peds_trauma_04_burn.dry_dressing":                "satisfied",
        "peds_trauma_04_burn.prevent_hypothermia":         "satisfied",
        "peds_trauma_04_burn.scope_no_wet_dressings":      "satisfied",
        "peds_trauma_04_burn.scope_no_iv_pain_medication": "satisfied",
    },
}

_BURN_SCOPE_VIOLATION = {
    "scenario_id": "peds_trauma_04_burn",
    "description": "burn — scope violation: wet dressings applied (contraindicated)",
    "inputs": {
        "interventions": ["remove_clothing", "airway_assessment", "dry_dressing", "prevent_hypothermia", "wet_dressing"],
        "findings": [{"key": "hr", "value": "105", "finding_type": "vital"}],
        "messages": [],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.trauma.scene_safety":          "satisfied",
        "ems.trauma.primary_assessment":    "satisfied",
        "ems.trauma.mechanism_assessment":  "not_satisfied",
        "ems.trauma.hemorrhage_control":    "not_satisfied",
        "ems.trauma.secondary_assessment":  "not_satisfied",
        "ems.trauma.transport_handoff":     "not_satisfied",
        "peds_trauma_04_burn.pat_assessment":              "satisfied",
        "peds_trauma_04_burn.stop_burning":                "satisfied",
        "peds_trauma_04_burn.airway_screen":               "satisfied",
        "peds_trauma_04_burn.dry_dressing":                "satisfied",
        "peds_trauma_04_burn.prevent_hypothermia":         "satisfied",
        "peds_trauma_04_burn.scope_no_wet_dressings":      "not_satisfied",
        "peds_trauma_04_burn.scope_no_iv_pain_medication": "satisfied",
    },
}

# ── peds_trauma_05_auto_ped fixtures ──────────────────────────────────────────

_AUTO_PED_FULL_CREDIT = {
    "scenario_id": "peds_trauma_05_auto_ped",
    "description": "auto-pedestrian — full-credit: all items satisfied",
    "inputs": {
        "interventions": ["bvm", "pelvic_binder", "load_and_go"],
        "findings": [{"key": "resp_rate", "value": "30", "finding_type": "vital"}],
        "messages": [
            "She was struck by an SUV — tire rolled over her lower body.",
            "Decompensated shock — mottled skin, hypotension, HR elevated, cap refill 4 sec.",
            "Pelvic binder applied at trochanters — secured with bandage wrap.",
            "Checking pupils, head, and abdomen — full primary assessment.",
            "Load and go — transporting to trauma center, ALS en route.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.trauma.scene_safety":          "satisfied",
        "ems.trauma.primary_assessment":    "satisfied",
        "ems.trauma.mechanism_assessment":  "satisfied",
        "ems.trauma.hemorrhage_control":    "satisfied",
        "ems.trauma.secondary_assessment":  "satisfied",
        "ems.trauma.transport_handoff":     "satisfied",
        "peds_trauma_05_auto_ped.pat_assessment":     "satisfied",
        "peds_trauma_05_auto_ped.airway_bvm":         "satisfied",
        "peds_trauma_05_auto_ped.shock_recognition":  "satisfied",
        "peds_trauma_05_auto_ped.pelvic_binder":      "satisfied",
        "peds_trauma_05_auto_ped.load_and_go":        "satisfied",
        "peds_trauma_05_auto_ped.scope_no_iv_fluids": "satisfied",
        "peds_trauma_05_auto_ped.scope_bvm_required": "satisfied",
    },
}

_AUTO_PED_PELVIC_GAP = {
    "scenario_id": "peds_trauma_05_auto_ped",
    "description": "auto-pedestrian — gap: missed pelvic binder and shock recognition",
    "inputs": {
        "interventions": ["bvm", "load_and_go"],
        "findings": [{"key": "resp_rate", "value": "30", "finding_type": "vital"}],
        "messages": ["Let's get moving."],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.trauma.scene_safety":          "satisfied",
        "ems.trauma.primary_assessment":    "satisfied",
        "ems.trauma.mechanism_assessment":  "not_satisfied",
        "ems.trauma.hemorrhage_control":    "not_satisfied",
        "ems.trauma.secondary_assessment":  "not_satisfied",
        "ems.trauma.transport_handoff":     "not_satisfied",
        "peds_trauma_05_auto_ped.pat_assessment":     "satisfied",
        "peds_trauma_05_auto_ped.airway_bvm":         "satisfied",
        "peds_trauma_05_auto_ped.shock_recognition":  "not_satisfied",
        "peds_trauma_05_auto_ped.pelvic_binder":      "not_satisfied",
        "peds_trauma_05_auto_ped.load_and_go":        "satisfied",
        "peds_trauma_05_auto_ped.scope_no_iv_fluids": "satisfied",
        "peds_trauma_05_auto_ped.scope_bvm_required": "satisfied",
    },
}

# ── peds_trauma_06_handlebar fixtures ─────────────────────────────────────────

_HANDLEBAR_FULL_CREDIT = {
    "scenario_id": "peds_trauma_06_handlebar",
    "description": "handlebar injury — full-credit: all items satisfied",
    "inputs": {
        "interventions": ["abdominal_assessment", "o2_nrb", "rapid_transport"],
        "findings": [{"key": "hr", "value": "130", "finding_type": "vital"}],
        "messages": [
            "He fell off his bike — handlebar hit his upper abdomen.",
            "HR 130, pale, cool — compensated shock pattern.",
            "Palpating abdomen gently — tender at epigastric region.",
            "Transporting to trauma center — ALS intercept en route.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.trauma.scene_safety":          "satisfied",
        "ems.trauma.primary_assessment":    "satisfied",
        "ems.trauma.mechanism_assessment":  "satisfied",
        "ems.trauma.hemorrhage_control":    "not_satisfied",
        "ems.trauma.secondary_assessment":  "satisfied",
        "ems.trauma.transport_handoff":     "satisfied",
        "peds_trauma_06_handlebar.pat_assessment":                "satisfied",
        "peds_trauma_06_handlebar.handlebar_sign":                "satisfied",
        "peds_trauma_06_handlebar.shock_recognition":             "satisfied",
        "peds_trauma_06_handlebar.high_flow_o2":                  "satisfied",
        "peds_trauma_06_handlebar.priority_transport":            "satisfied",
        "peds_trauma_06_handlebar.scope_no_aggressive_palpation": "satisfied",
        "peds_trauma_06_handlebar.scope_no_iv_fluids":            "satisfied",
    },
}

_HANDLEBAR_ASSESSMENT_GAP = {
    "scenario_id": "peds_trauma_06_handlebar",
    "description": "handlebar injury — gap: missed abdominal assessment and shock recognition",
    "inputs": {
        "interventions": ["o2_nrb", "rapid_transport"],
        "findings": [{"key": "resp_rate", "value": "22", "finding_type": "vital"}],
        "messages": ["Let's get moving quickly."],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.trauma.scene_safety":          "satisfied",
        "ems.trauma.primary_assessment":    "satisfied",
        "ems.trauma.mechanism_assessment":  "not_satisfied",
        "ems.trauma.hemorrhage_control":    "not_satisfied",
        "ems.trauma.secondary_assessment":  "not_satisfied",
        "ems.trauma.transport_handoff":     "not_satisfied",
        "peds_trauma_06_handlebar.pat_assessment":                "satisfied",
        "peds_trauma_06_handlebar.handlebar_sign":                "not_satisfied",
        "peds_trauma_06_handlebar.shock_recognition":             "not_satisfied",
        "peds_trauma_06_handlebar.high_flow_o2":                  "satisfied",
        "peds_trauma_06_handlebar.priority_transport":            "satisfied",
        "peds_trauma_06_handlebar.scope_no_aggressive_palpation": "satisfied",
        "peds_trauma_06_handlebar.scope_no_iv_fluids":            "satisfied",
    },
}

_HANDLEBAR_SCOPE_VIOLATION = {
    "scenario_id": "peds_trauma_06_handlebar",
    "description": "handlebar injury — scope violation: aggressive abdominal palpation (contraindicated)",
    "inputs": {
        "interventions": ["abdominal_assessment", "o2_nrb", "rapid_transport", "aggressive_palpation"],
        "findings": [{"key": "hr", "value": "130", "finding_type": "vital"}],
        "messages": ["HR 130, pale, cool — compensated shock."],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "ems.trauma.scene_safety":          "satisfied",
        "ems.trauma.primary_assessment":    "satisfied",
        "ems.trauma.mechanism_assessment":  "not_satisfied",
        "ems.trauma.hemorrhage_control":    "not_satisfied",
        "ems.trauma.secondary_assessment":  "not_satisfied",
        "ems.trauma.transport_handoff":     "not_satisfied",
        "peds_trauma_06_handlebar.pat_assessment":                "satisfied",
        "peds_trauma_06_handlebar.handlebar_sign":                "satisfied",
        "peds_trauma_06_handlebar.shock_recognition":             "satisfied",
        "peds_trauma_06_handlebar.high_flow_o2":                  "satisfied",
        "peds_trauma_06_handlebar.priority_transport":            "satisfied",
        "peds_trauma_06_handlebar.scope_no_aggressive_palpation": "not_satisfied",
        "peds_trauma_06_handlebar.scope_no_iv_fluids":            "satisfied",
    },
}


# ── peds_trauma_07_head_injury fixtures ──────────────────────────────────────

_HEAD_INJURY_FULL_CREDIT = {
    "scenario_id": "peds_trauma_07_head_injury",
    "description": "head injury — full-credit: PAT performed, neuro assessment, transport decision",
    "inputs": {
        "interventions": ["spine_immobilization", "o2_blowby"],
        "findings": [
            {"key": "gcs", "value": "14", "finding_type": "vital"},
            {"key": "hr", "value": "92", "finding_type": "vital"},
        ],
        "messages": [
            "How did he fall? How high? Did he lose consciousness on impact?",
            "Checking GCS — eye opening to voice, confused verbal, localizes to pain. GCS 14.",
            "Pupils: right slightly sluggish, left briskly reactive — asymmetric.",
            "Spinal motion restriction in place, supplemental O2 applied.",
            "Priority transport — ALS updating en route to pediatric trauma center.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": True},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "peds_trauma_07_head_injury.pat_assessment": "satisfied",
    },
}

_HEAD_INJURY_PAT_GAP = {
    "scenario_id": "peds_trauma_07_head_injury",
    "description": "head injury — gap: PAT not performed at scene entry",
    "inputs": {
        "interventions": [],
        "findings": [],
        "messages": ["What happened?"],
        "scene_entry": {"ppe_donned": ["Gloves"], "pat_assessment": False},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "peds_trauma_07_head_injury.pat_assessment": "not_satisfied",
    },
}


# ── peds_cardiac_arrest_01_bls fixtures ──────────────────────────────────────

_CARDIAC_ARREST_FULL_CREDIT = {
    "scenario_id": "peds_cardiac_arrest_01_bls",
    "description": "pediatric cardiac arrest — full-credit: arrest recognized, CPR challenge completed, no ALS interventions",
    "inputs": {
        "interventions": [],
        "findings": [],
        "events": [
            {"event_type": "challenge_completed", "event_key": "cpr:peds_cardiac_arrest_01_bls_cpr"},
        ],
        "messages": [
            "This child is pulseless and apneic — this is a cardiac arrest.",
            "Initiating CPR, 30:2 ratio, 100-120 compressions per minute.",
            "AED attached and powered on — analyzing rhythm now.",
            "Shock delivered — immediately resuming compressions.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"]},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "peds_cardiac_arrest_01_bls.arrest_recognition":     "satisfied",
        "peds_cardiac_arrest_01_bls.cpr_challenge_management": "satisfied",
        "peds_cardiac_arrest_01_bls.scope_no_als_interventions": "satisfied",
    },
}

_CARDIAC_ARREST_RECOGNITION_GAP = {
    "scenario_id": "peds_cardiac_arrest_01_bls",
    "description": "pediatric cardiac arrest — gap: arrest not verbally recognized, CPR challenge not completed",
    "inputs": {
        "interventions": [],
        "findings": [],
        "events": [],
        "messages": [
            "Checking him out.",
            "He looks unconscious.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"]},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "peds_cardiac_arrest_01_bls.arrest_recognition":        "not_satisfied",
        "peds_cardiac_arrest_01_bls.cpr_challenge_management":  "not_satisfied",
        "peds_cardiac_arrest_01_bls.scope_no_als_interventions": "satisfied",
    },
}

_CARDIAC_ARREST_SCOPE_VIOLATION = {
    "scenario_id": "peds_cardiac_arrest_01_bls",
    "description": "pediatric cardiac arrest — scope violation: cardiac monitor applied by BLS provider",
    "inputs": {
        "interventions": ["ekg_monitoring"],
        "findings": [],
        "events": [
            {"event_type": "challenge_completed", "event_key": "cpr:peds_cardiac_arrest_01_bls_cpr"},
        ],
        "messages": [
            "Patient is pulseless and unresponsive — cardiac arrest.",
            "Starting CPR and attaching the cardiac monitor.",
        ],
        "scene_entry": {"ppe_donned": ["Gloves"]},
        "dmist": "",
        "narrative": "",
    },
    "expected_states": {
        "peds_cardiac_arrest_01_bls.arrest_recognition":        "satisfied",
        "peds_cardiac_arrest_01_bls.cpr_challenge_management":  "satisfied",
        "peds_cardiac_arrest_01_bls.scope_no_als_interventions": "not_satisfied",
    },
}


# ── Master fixture registry ───────────────────────────────────────────────────

_FIXTURES_BY_SCENARIO: dict[str, list[dict]] = {
    "peds_syncope_01": [
        _SYNCOPE_FULL_CREDIT,
        _SYNCOPE_CLINICAL_GAP,
        _SYNCOPE_SCOPE_VIOLATION,
        _SYNCOPE_PPE_GAP,
        _SYNCOPE_SCREEN_VIA_DMIST,
    ],
    "adult_acs_01_stemi": [
        _ACS_FULL_CREDIT,
        _ACS_12LEAD_GAP,
        _ACS_SCOPE_VIOLATION,
    ],
    "peds_anaphylaxis_01": [
        _ANAPHYLAXIS_FULL_CREDIT,
        _ANAPHYLAXIS_EPI_GAP,
        _ANAPHYLAXIS_SCOPE_VIOLATION,
    ],
    "peds_asthma_01": [
        _ASTHMA_FULL_CREDIT,
        _ASTHMA_ALBUTEROL_GAP,
    ],
    "peds_croup_01": [
        _CROUP_FULL_CREDIT,
        _CROUP_ALS_GAP,
        _CROUP_SPARSE_RECENT_RUN,
        _CROUP_SCOPE_VIOLATION,
    ],
    "peds_diabetic_emergency_01": [
        _DIABETIC_FULL_CREDIT,
        _DIABETIC_GLUCOSE_GAP,
        _DIABETIC_SCOPE_VIOLATION,
        _DIABETIC_CGM_ONLY_GAP,
    ],
    "peds_febrile_seizure_01": [
        _FEBRILE_SEIZURE_FULL_CREDIT,
        _FEBRILE_SEIZURE_AIRWAY_GAP,
    ],
    "peds_trauma_01_soft_tissue": [
        _SOFT_TISSUE_FULL_CREDIT,
        _SOFT_TISSUE_HEMORRHAGE_GAP,
    ],
    "peds_trauma_02_partial_choking": [
        _CHOKING_FULL_CREDIT,
        _CHOKING_CLASSIFICATION_GAP,
        _CHOKING_SCOPE_VIOLATION,
    ],
    "peds_trauma_03_extremity": [
        _EXTREMITY_FULL_CREDIT,
        _EXTREMITY_CMS_GAP,
    ],
    "peds_trauma_04_burn": [
        _BURN_FULL_CREDIT,
        _BURN_STOP_BURNING_GAP,
        _BURN_SCOPE_VIOLATION,
    ],
    "peds_trauma_05_auto_ped": [
        _AUTO_PED_FULL_CREDIT,
        _AUTO_PED_PELVIC_GAP,
    ],
    "peds_trauma_06_handlebar": [
        _HANDLEBAR_FULL_CREDIT,
        _HANDLEBAR_ASSESSMENT_GAP,
        _HANDLEBAR_SCOPE_VIOLATION,
    ],
    "peds_trauma_07_head_injury": [
        _HEAD_INJURY_FULL_CREDIT,
        _HEAD_INJURY_PAT_GAP,
    ],
    "peds_cardiac_arrest_01_bls": [
        _CARDIAC_ARREST_FULL_CREDIT,
        _CARDIAC_ARREST_RECOGNITION_GAP,
        _CARDIAC_ARREST_SCOPE_VIOLATION,
    ],
}

_ALL_FIXTURES_FLAT = [
    fixture
    for fixtures in _FIXTURES_BY_SCENARIO.values()
    for fixture in fixtures
]


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "fixture",
    _ALL_FIXTURES_FLAT,
    ids=[f["description"] for f in _ALL_FIXTURES_FLAT],
)
def test_gold_standard_fixture(fixture: dict):
    """Adjudication output must match all expected states in the fixture."""
    actual = _run(fixture)
    mismatches = []
    for item_id, expected in fixture["expected_states"].items():
        if item_id.startswith(("ems.medical.", "ems.trauma.")):
            # Base patient-care rubric items are inherited globally and tested
            # once in test_checklist.py. Scenario gold fixtures focus overlays.
            continue
        got = actual.get(item_id, "<missing>")
        if got != expected:
            mismatches.append(f"  {item_id}: expected={expected!r} got={got!r}")
    assert not mismatches, (
        f"Fixture {fixture['description']!r} — {len(mismatches)} mismatch(es):\n"
        + "\n".join(mismatches)
    )


@pytest.mark.parametrize(
    "scenario_id,fixtures",
    list(_FIXTURES_BY_SCENARIO.items()),
)
def test_all_fixture_items_have_expected_coverage(
    scenario_id: str, fixtures: list[dict]
):
    """Every non-legacy item in the scenario checklist must appear in each fixture.

    Fails if a checklist item is added to a covered scenario without updating
    the corresponding fixture.  Passing silently with stale coverage is worse
    than no coverage.
    """
    scenario = _load_scenario_raw(scenario_id)
    effective_checklist = load_checklist(
        scenario, level="EMT", mca="mi_base", agency_id=None
    )
    from app.scoring_service import _get_legacy_ai_categories
    legacy_cats = _get_legacy_ai_categories(scenario)
    required_ids = {
        i.id for i in effective_checklist
        if i.category not in legacy_cats and i.provenance != "base_patient_care_rubric"
    }

    for fixture in fixtures:
        covered = set(fixture["expected_states"].keys())
        missing = required_ids - covered
        assert not missing, (
            f"Scenario {scenario_id!r} fixture {fixture['description']!r} "
            f"does not cover items: {sorted(missing)}. "
            "Add expected states for these items or mark them not_applicable."
        )
