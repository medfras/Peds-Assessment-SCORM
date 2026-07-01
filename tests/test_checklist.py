from __future__ import annotations

import json
import re
from pathlib import Path

from app.checklist import get_base_rubric_version, load_checklist
from app.rubric_loader import compose_active_checklist, load_call_type_rubric, load_scenario_overlay
from app.scenario_engine import adapt_scenario_to_context


def _load_active_checklist(scenario: dict, level: str = "EMT"):
    base_items = load_checklist(scenario, level=level, mca="mi_base", agency_id=None)
    call_type = scenario.get("call_type")
    if not call_type:
        return base_items
    rubric = load_call_type_rubric(call_type, deployment_context="training")
    if rubric is None:
        return base_items
    overlay_ops = load_scenario_overlay(scenario.get("id", ""), call_type)
    return compose_active_checklist(
        base_items=base_items,
        rubric=rubric,
        provider_level=level,
        overlay_ops=overlay_ops,
        overlay_id=f"{scenario.get('id', '')}_overlay" if overlay_ops else "",
        scenario=scenario,
    ).items


def _raw_item(item_id: str = "custom.item", point_value: int = 3) -> dict:
    return {
        "id": item_id,
        "description": "Custom observable behavior",
        "subtype": "assessment",
        "category": "clinical_performance",
        "point_value": point_value,
        "allowed_tiers": [2],
        "preferred_tier": 2,
        "tier3_permitted": False,
        "tier2_patterns": [r"(?i)custom"],
    }


def test_load_checklist_without_base_rubric_returns_scenario_items_only():
    scenario = {
        "id": "unit_test_scenario",
        "category": "pediatric_medical",
        "turnover_target": "als",
        "checklist": [_raw_item()],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)

    assert [i.id for i in items] == ["custom.item"]
    assert items[0].provenance == "scenario_overlay"


def test_medical_base_rubric_items_are_inherited_for_opt_in_scenario():
    scenario = {
        "id": "unit_test_medical",
        "category": "pediatric_medical",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_e202_medical_v1",
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    ids = {i.id for i in items}

    assert "ems.medical.ppe" in ids
    assert "ems.medical.airway_breathing_o2" in ids
    assert "ems.medical.opqrst_onset" in ids
    assert "ems.medical.patient_name" in ids
    assert "ems.medical.patient_age_dob" in ids
    assert "ems.medical.patient_count" not in ids
    assert "ems.medical.spine_considered" not in ids
    assert "ems.medical.opqrst_radiation" not in ids
    assert "ems.medical.diagnostics" not in ids
    assert all(i.provenance == "base_patient_care_rubric" for i in items)
    assert "ems.medical.repeat_primary" not in ids
    assert "ems.medical.repeat_secondary" not in ids
    assert sum(i.point_value for i in items) == 42


def test_medical_vital_signs_item_excludes_avpu_and_gcs_only():
    scenario = {
        "id": "unit_test_medical",
        "category": "pediatric_medical",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_e202_medical_v1",
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    item = next(i for i in items if i.id == "ems.medical.vital_signs")
    key_pattern = item.tier1_match.finding_key_pattern
    text_pattern = item.tier2_patterns[0]

    assert re.search(key_pattern, "SpO2")
    assert re.search(key_pattern, "Heart Rate")
    assert re.search(key_pattern, "Respiratory Rate")
    assert re.search(key_pattern, "Blood Pressure")
    assert re.search(key_pattern, "Temperature")
    assert not re.search(key_pattern, "Pulse")
    assert not re.search(key_pattern, "Airway")
    assert not re.search(key_pattern, "Breathing")
    assert not re.search(key_pattern, "Breath Sounds")
    assert not re.search(key_pattern, "WOB")
    assert not re.search(key_pattern, "Work of Breathing")
    assert not re.search(key_pattern, "AVPU")
    assert not re.search(key_pattern, "GCS")
    assert not re.search(text_pattern, "manual pulse check")
    assert not re.search(text_pattern, "pulse quality")
    assert not re.search(text_pattern, "check breathing")
    assert not re.search(text_pattern, "work of breathing")
    assert not re.search(text_pattern, "AVPU")
    assert not re.search(text_pattern, "GCS")
    assert item.allowed_tiers == [1]
    assert item.tier1_match.require_source is True
    assert set(item.tier1_match.eligible_sources or []) == {"authored_vitals", "glucometer_check"}


def test_medical_vital_signs_requires_numeric_value_for_tier1():
    """Qualitative vital findings (e.g. 'Resp Rate=irregular') must not credit vital_signs.

    Without this guard, a breathing assessment that emits [[VITAL: Resp Rate=irregular]]
    would match the key pattern and incorrectly score vital_signs as Done even though the
    student obtained no quantitative measurement.
    """
    scenario = {
        "id": "unit_test_medical",
        "category": "pediatric_medical",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_e202_medical_v1",
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    item = next(i for i in items if i.id == "ems.medical.vital_signs")
    val_pattern = item.tier1_match.finding_value_pattern

    assert val_pattern, "vital_signs tier1 must have a finding_value_pattern"

    # Numeric values must match — these represent real vital sign measurements.
    assert re.search(val_pattern, "98")           # SpO2 percentage
    assert re.search(val_pattern, "98%")          # SpO2 with unit
    assert re.search(val_pattern, "120/80")       # blood pressure
    assert re.search(val_pattern, "72 bpm")       # heart rate
    assert re.search(val_pattern, "24")           # respiratory rate
    assert re.search(val_pattern, "37.2")         # temperature
    assert re.search(val_pattern, "110 mg/dL")    # blood glucose

    # Non-numeric / qualitative values must NOT match.
    assert not re.search(val_pattern, "irregular")   # qualitative pulse or resp description
    assert not re.search(val_pattern, "labored")     # qualitative WOB
    assert not re.search(val_pattern, "regular")     # qualitative rhythm
    assert not re.search(val_pattern, "elevated")    # qualitative assessment
    assert not re.search(val_pattern, "")            # empty value


def test_medical_secondary_assessment_credits_neuro_exam_findings():
    scenario = {
        "id": "unit_test_medical",
        "category": "pediatric_medical",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_e202_medical_v1",
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    item = next(i for i in items if i.id == "ems.medical.secondary_assessment")
    key_pattern = item.tier1_match.finding_key_pattern

    assert re.search(key_pattern, "Level of Consciousness")
    assert re.search(key_pattern, "Mental Status")
    assert re.search(key_pattern, "AVPU")
    assert re.search(key_pattern, "GCS")
    assert re.search(key_pattern, "Pupils")
    assert item.allowed_tiers == [1]


def test_cardiac_arrest_base_rubric_replaces_general_medical_assessment():
    scenario = {
        "id": "unit_test_arrest",
        "category": "adult_medical",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_cardiac_arrest_aed_v1",
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    ids = {i.id for i in items}

    assert "ems.cardiac_arrest.ppe" in ids
    assert "ems.cardiac_arrest.high_quality_cpr" in ids
    assert "ems.cardiac_arrest.aed_attach" in ids
    assert "ems.cardiac_arrest.resume_compressions" in ids
    assert "ems.medical.opqrst_onset" not in ids
    assert "ems.medical.patient_name" not in ids
    assert sum(i.point_value for i in items) == 16


def test_medical_scenario_can_add_secondary_cardiac_arrest_rubric_for_deterioration():
    scenario = {
        "id": "unit_test_medical_to_arrest",
        "category": "adult_medical",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_e202_medical_v1",
        "additional_patient_care_rubrics": ["nremt_cardiac_arrest_aed_v1"],
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    ids = {i.id for i in items}

    assert "ems.medical.ppe" in ids
    assert "ems.medical.opqrst_onset" in ids
    assert "ems.medical.patient_name" in ids
    assert "ems.cardiac_arrest.breathing_pulse" in ids
    assert "ems.cardiac_arrest.high_quality_cpr" in ids
    assert "ems.cardiac_arrest.aed_attach" in ids
    assert "ems.cardiac_arrest.resume_compressions" in ids
    assert "ems.cardiac_arrest.ppe" not in ids
    assert "ems.cardiac_arrest.scene_safety" not in ids
    assert sum(i.point_value for i in items) == 56


def test_trauma_scenario_can_add_secondary_cardiac_arrest_rubric_for_deterioration():
    scenario = {
        "id": "unit_test_trauma_to_arrest",
        "category": "adult_trauma",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_trauma_v1",
        "additional_patient_care_rubrics": ["nremt_cardiac_arrest_aed_v1"],
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    ids = {i.id for i in items}

    assert "ems.trauma.ppe" in ids
    assert "ems.trauma.airway" in ids
    assert "ems.trauma.circulation" in ids
    assert "ems.cardiac_arrest.breathing_pulse" in ids
    assert "ems.cardiac_arrest.high_quality_cpr" in ids
    assert "ems.cardiac_arrest.aed_attach" in ids
    assert "ems.cardiac_arrest.ppe" not in ids
    assert "ems.cardiac_arrest.scene_safety" not in ids
    assert sum(i.point_value for i in items) == 55


def test_medical_scenario_can_add_secondary_trauma_rubric_without_duplicate_shared_assessment():
    scenario = {
        "id": "unit_test_medical_with_trauma",
        "category": "adult_medical",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_e202_medical_v1",
        "additional_patient_care_rubrics": ["nremt_trauma_v1"],
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    ids = {i.id for i in items}

    assert "ems.medical.ppe" in ids
    assert "ems.medical.patient_name" in ids
    assert "ems.medical.vital_signs" in ids
    assert "ems.medical.opqrst_onset" in ids
    assert "ems.trauma.moi_noi" in ids
    assert "ems.trauma.chest_inspect" in ids
    assert "ems.trauma.chest_palpate" in ids
    assert "ems.trauma.chest_auscultate" in ids
    assert "ems.trauma.abdomen_inspect_palpate" in ids
    assert "ems.trauma.pelvis_assess" in ids
    assert "ems.trauma.secondary_wounds" in ids
    assert "ems.trauma.ppe" not in ids
    assert "ems.trauma.patient_name" not in ids
    assert "ems.trauma.airway" not in ids
    assert "ems.trauma.baseline_vitals" not in ids


def test_medical_trauma_scenario_can_add_secondary_cardiac_arrest_rubric():
    scenario = {
        "id": "unit_test_medical_trauma_to_arrest",
        "category": "adult_medical",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_e202_medical_v1",
        "additional_patient_care_rubrics": [
            "nremt_trauma_v1",
            "nremt_cardiac_arrest_aed_v1",
        ],
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    ids = {i.id for i in items}

    assert "ems.medical.opqrst_onset" in ids
    assert "ems.trauma.chest_inspect" in ids
    assert "ems.trauma.chest_palpate" in ids
    assert "ems.trauma.chest_auscultate" in ids
    assert "ems.cardiac_arrest.breathing_pulse" in ids
    assert "ems.cardiac_arrest.high_quality_cpr" in ids
    assert "ems.trauma.ppe" not in ids
    assert "ems.cardiac_arrest.ppe" not in ids
    assert "ems.trauma.patient_name" not in ids
    assert "ems.cardiac_arrest.scene_safety" not in ids


def test_additional_patient_care_rubrics_must_be_a_list():
    scenario = {
        "id": "unit_test_bad_additional_base",
        "category": "adult_medical",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_e202_medical_v1",
        "additional_patient_care_rubrics": "nremt_cardiac_arrest_aed_v1",
        "checklist": [],
    }

    try:
        load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    except ValueError as exc:
        assert "additional_patient_care_rubrics must be a list" in str(exc)
    else:
        raise AssertionError("Expected additional_patient_care_rubrics validation failure")


def test_additional_patient_care_rubrics_requires_primary_base_rubric():
    scenario = {
        "id": "unit_test_additional_without_primary",
        "category": "adult_medical",
        "turnover_target": "als",
        "additional_patient_care_rubrics": ["nremt_trauma_v1"],
        "checklist": [],
    }

    try:
        load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    except ValueError as exc:
        assert "additional_patient_care_rubrics requires base_patient_care_rubric" in str(exc)
    else:
        raise AssertionError("Expected additional_patient_care_rubrics base validation failure")


def test_medical_secondary_assessment_requires_focused_exam_evidence():
    scenario = {
        "id": "unit_test_medical_secondary",
        "category": "pediatric_medical",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_e202_medical_v1",
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    secondary = next(i for i in items if i.id == "ems.medical.secondary_assessment")
    pattern = secondary.tier1_match.finding_key_pattern

    assert pattern
    assert re.search(pattern, "Mental Status", re.IGNORECASE)
    assert re.search(pattern, "LOC", re.IGNORECASE)
    assert re.search(pattern, "Level of Consciousness", re.IGNORECASE)
    assert re.search(pattern, "AVPU", re.IGNORECASE)
    assert re.search(pattern, "GCS", re.IGNORECASE)
    assert not re.search(pattern, "Focused Secondary Assessment", re.IGNORECASE)
    assert not re.search(pattern, "Secondary Assessment", re.IGNORECASE)
    assert not re.search(pattern, "WOB", re.IGNORECASE)
    assert not re.search(pattern, "Work of Breathing", re.IGNORECASE)
    assert re.search(pattern, "Breath Sounds", re.IGNORECASE)
    assert re.search(pattern, "Lung Sounds", re.IGNORECASE)
    assert re.search(pattern, "Pupils", re.IGNORECASE)
    assert re.search(pattern, "Abdomen", re.IGNORECASE)
    assert secondary.allowed_tiers == [1]


def test_trauma_base_rubric_items_are_filtered_by_scenario_category():
    scenario = {
        "id": "unit_test_trauma",
        "category": "pediatric_trauma",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_trauma_v1",
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    ids = {i.id for i in items}

    assert "ems.trauma.airway" in ids
    assert "ems.trauma.breathing" in ids
    assert "ems.trauma.patient_name" in ids
    assert "ems.trauma.patient_age_dob" in ids
    assert "ems.trauma.patient_count" not in ids
    assert "ems.trauma.spine_protection" not in ids
    assert "ems.trauma.general_impression" in ids
    assert "ems.medical.airway_breathing_o2" not in ids
    assert sum(i.point_value for i in items) == 41


def test_trauma_transport_decision_is_filtered_for_non_transport_agencies():
    scenario = {
        "id": "unit_test_trauma_nontransport",
        "category": "pediatric_trauma",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_trauma_v1",
        "non_transport_agency": True,
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    ids = {i.id for i in items}

    assert "ems.trauma.priority_transport" not in ids


def test_trauma_primary_survey_gaps_do_not_trigger_station_fail_by_default():
    scenario = {
        "id": "unit_test_trauma_critical_flags",
        "category": "pediatric_trauma",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_trauma_v1",
        "non_transport_agency": False,
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    airway = next(i for i in items if i.id == "ems.trauma.airway")
    breathing = next(i for i in items if i.id == "ems.trauma.breathing")
    circulation = next(i for i in items if i.id == "ems.trauma.circulation")

    assert airway.critical_failure is False
    assert breathing.critical_failure is False
    assert circulation.critical_failure is False


def test_pediatric_trauma_scenarios_do_not_inherit_generic_airway_or_transport_critical_failures():
    scenario_dir = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/trauma"
    for scenario_path in scenario_dir.glob("*.json"):
        scenario = json.loads(scenario_path.read_text())
        if scenario.get("base_patient_care_rubric") != "nremt_trauma_v1":
            continue

        items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
        critical_by_id = {item.id: item for item in items if item.critical_failure}

        assert "ems.trauma.airway" not in critical_by_id, scenario_path.name
        assert "ems.trauma.priority_transport" not in critical_by_id, scenario_path.name


def test_trauma_extremity_patterns_require_assessment_language():
    scenario = {
        "id": "unit_test_trauma_extremity_patterns",
        "category": "pediatric_trauma",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_trauma_v1",
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    upper_left = next(i for i in items if i.id == "ems.trauma.upper_left_pmsc")
    upper_right = next(i for i in items if i.id == "ems.trauma.upper_right_pmsc")
    lower_left = next(i for i in items if i.id == "ems.trauma.lower_left_pmsc")
    lower_right = next(i for i in items if i.id == "ems.trauma.lower_right_pmsc")

    assert re.search(upper_left.tier2_patterns[0], "Check all extremities for PMS, radial pulses, motor, and sensation")
    assert re.search(upper_right.tier2_patterns[0], "Check all extremities for PMS, radial pulses, motor, and sensation")
    assert re.search(lower_left.tier2_patterns[0], "Assess both legs for PMS, pedal pulses, motor, and sensation")
    assert re.search(lower_right.tier2_patterns[0], "Assess both legs for PMS, pedal pulses, motor, and sensation")
    assert not re.search(upper_left.tier2_patterns[0], "Mom is holding his hand and he is sitting still")
    assert not re.search(lower_left.tier2_patterns[0], "He fell near the playground and his feet are on the grass")


def test_trauma_region_patterns_require_exam_language():
    scenario = {
        "id": "unit_test_trauma_region_patterns",
        "category": "pediatric_trauma",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_trauma_v1",
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    head_scalp = next(i for i in items if i.id == "ems.trauma.head_scalp_ears")
    posterior = next(i for i in items if i.id == "ems.trauma.posterior_thorax")
    head_pattern = head_scalp.tier2_patterns[0]
    posterior_pattern = posterior.tier2_patterns[0]

    assert re.search(head_pattern, "I am inspecting and palpating the head and scalp for DCAP-BTLS")
    assert not re.search(head_pattern, "He fell and hit his head; his head hurts")
    assert re.search(posterior_pattern, "Log roll with inline stabilization to inspect his back and posterior thorax")
    assert not re.search(posterior_pattern, "Hold c-spine and apply spinal motion restriction")


def test_trauma_head_assessment_structured_exam_matches_head_and_eye_items():
    scenario = {
        "id": "unit_test_trauma_structured_head_exam",
        "category": "pediatric_trauma",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_trauma_v1",
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    head_scalp = next(i for i in items if i.id == "ems.trauma.head_scalp_ears")
    head_eyes = next(i for i in items if i.id == "ems.trauma.head_eyes")

    assert head_scalp.tier1_match is not None
    assert head_scalp.tier1_match.finding_type == "exam"
    assert re.search(head_scalp.tier1_match.finding_key_pattern or "", "DCAP-BTLS Head")
    assert not re.search(head_scalp.tier1_match.finding_key_pattern or "", "Headache")

    assert head_eyes.tier1_match is not None
    assert head_eyes.tier1_match.finding_type == "exam"
    assert re.search(head_eyes.tier1_match.finding_key_pattern or "", "Pupils")
    assert not re.search(head_eyes.tier1_match.finding_key_pattern or "", "GCS")


def test_trauma_secondary_assessment_is_atomic_nremt_point_breakdown():
    scenario = {
        "id": "unit_test_trauma_secondary_atomic",
        "category": "pediatric_trauma",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_trauma_v1",
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    secondary_ids = {
        "ems.trauma.head_scalp_ears",
        "ems.trauma.head_eyes",
        "ems.trauma.head_mouth_nose_face",
        "ems.trauma.neck_trachea",
        "ems.trauma.neck_jugular_veins",
        "ems.trauma.neck_c_spine",
        "ems.trauma.chest_inspect",
        "ems.trauma.chest_palpate",
        "ems.trauma.chest_auscultate",
        "ems.trauma.abdomen_inspect_palpate",
        "ems.trauma.pelvis_assess",
        "ems.trauma.genitalia_perineum_as_needed",
        "ems.trauma.lower_left_pmsc",
        "ems.trauma.lower_right_pmsc",
        "ems.trauma.upper_left_pmsc",
        "ems.trauma.upper_right_pmsc",
        "ems.trauma.posterior_thorax",
        "ems.trauma.lumbar_buttocks",
        "ems.trauma.secondary_wounds",
    }
    by_id = {item.id: item for item in items}

    assert secondary_ids.issubset(by_id)
    assert sum(by_id[item_id].point_value for item_id in secondary_ids) == 19
    assert all(by_id[item_id].point_value == 1 for item_id in secondary_ids)


def test_croup_uses_medical_rubric_only_and_als_handoff_is_not_checklist_scored():
    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/medical/peds_croup_01.json"
    scenario = json.loads(scenario_path.read_text())
    scenario["non_transport_agency"] = True

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    ids = {i.id for i in items}

    assert "ems.medical.airway_breathing_o2" in ids
    assert "ems.medical.chief_life_threats" in ids
    assert "ems.medical.field_impression" in ids
    assert "ems.medical.patient_count" not in ids
    assert "ems.medical.spine_considered" not in ids
    assert "ems.medical.opqrst_radiation" not in ids
    assert "ems.medical.diagnostics" not in ids
    assert "ems.medical.priority_transport" not in ids
    assert "ems.medical.transport_reevaluated" not in ids
    assert "ems.medical.repeat_primary" not in ids
    assert "ems.medical.repeat_secondary" not in ids
    assert not any(item_id.startswith("ems.trauma.") for item_id in ids)
    assert "peds_croup_01.als_intercept" not in ids


def test_croup_active_rubric_credits_scene_entry_pat_and_simulator_wob_sources():
    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/medical/peds_croup_01.json"
    scenario = json.loads(scenario_path.read_text())

    items = _load_active_checklist(scenario)
    by_id = {item.id: item for item in items}

    croup_pat = by_id["croup.pat_assessment"]
    assert croup_pat.tier1_match is not None
    assert croup_pat.tier1_match.source == "scene_entry"
    assert croup_pat.tier1_match.scene_entry_path == "pat_assessment"

    rr_wob = by_id["croup.rr_wob_assessed"]
    assert rr_wob.requirement_logic == "all"
    assert len(rr_wob.tier1_matches) == 2
    wob = next(match for match in rr_wob.tier1_matches if match.finding_type == "exam")
    assert set(wob.eligible_sources or []) >= {
        "partner_reported_exam",
        "student_stated_exam",
        "lung_sound_challenge",
    }


def test_diabetic_screen_and_oral_glucose_sequence_follow_protocol_exception():
    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json"
    scenario = json.loads(scenario_path.read_text())

    items = _load_active_checklist(scenario)
    by_id = {item.id: item for item in items}
    swallow = by_id["hypoglycemia.swallow_assessment"]
    oral_glucose = by_id["hypoglycemia.oral_glucose_administered"]
    protocol_oral_glucose = by_id["peds_diabetic_emergency_01.protocol_oral_glucose"]

    assert swallow.subtype == "screen"
    assert swallow.allowed_tiers == [1, 2]
    assert swallow.tier3_permitted is False
    assert swallow.timing_constraint is not None
    assert swallow.timing_constraint.reference_item_id == "hypoglycemia.oral_glucose_administered"
    assert oral_glucose.timing_constraint is not None
    assert oral_glucose.timing_constraint.reference_item_id == "hypoglycemia.swallow_assessment"
    assert protocol_oral_glucose.timing_constraint is not None
    assert protocol_oral_glucose.timing_constraint.reference_item_id == "hypoglycemia.swallow_assessment"
    assert "peds_diabetic_emergency_01.blood_glucose_check" not in by_id
    assert "peds_diabetic_emergency_01.swallow_assessment" not in by_id
    assert "peds_diabetic_emergency_01.oral_glucose" not in by_id


def test_medical_loc_credits_orientation_questions():
    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json"
    scenario = json.loads(scenario_path.read_text())

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    loc = next(item for item in items if item.id == "ems.medical.loc")
    assert any(
        re.search(pattern, "Do you know where you are Marcus? What day is it?")
        for pattern in loc.tier2_patterns
    )


def test_medical_loc_tier1_requires_avpu_quick_action_source():
    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json"
    scenario = json.loads(scenario_path.read_text())

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    loc = next(item for item in items if item.id == "ems.medical.loc")

    assert loc.tier1_match is not None
    assert loc.tier1_match.require_source is True
    assert loc.tier1_match.eligible_sources == ["avpu_quick_action"]
    assert any(
        re.search(pattern, "Do you know where you are Marcus? What day is it?")
        for pattern in loc.tier2_patterns
    )


def test_medical_patient_name_credits_direct_patient_question():
    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json"
    scenario = json.loads(scenario_path.read_text())

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    patient_name = next(item for item in items if item.id == "ems.medical.patient_name")

    assert any(
        re.search(pattern, "Marcus, what's your name?")
        for pattern in patient_name.tier2_patterns
    )


def test_medical_airway_breathing_credits_resp_effort_findings():
    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json"
    scenario = json.loads(scenario_path.read_text())

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    airway_breathing = next(item for item in items if item.id == "ems.medical.airway_breathing_o2")

    assert airway_breathing.tier1_match is not None
    assert airway_breathing.tier1_match.finding_type == "vital"
    assert re.search(airway_breathing.tier1_match.finding_key_pattern, "Respiratory Effort")
    assert re.search(airway_breathing.tier1_match.finding_key_pattern, "WOB")


def test_medical_associated_symptoms_credits_other_signs_or_symptoms():
    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json"
    scenario = json.loads(scenario_path.read_text())

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    associated = next(item for item in items if item.id == "ems.medical.associated_symptoms")

    assert any(
        re.search(pattern, "Any other signs or symptoms?")
        for pattern in associated.tier2_patterns
    )


def test_medical_provocation_credits_literal_provocation_wording():
    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json"
    scenario = json.loads(scenario_path.read_text())

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    provocation = next(item for item in items if item.id == "ems.medical.opqrst_provocation")

    assert any(
        re.search(pattern, "What about onset, provocation, quality, radiation, and time?")
        for pattern in provocation.tier2_patterns
    )


def test_medical_radiation_and_diagnostics_apply_only_when_clinically_relevant():
    acs_path = Path(__file__).resolve().parents[1] / "app/scenarios/adult/medical/adult_acs_01_stemi.json"
    acs = json.loads(acs_path.read_text())

    items = load_checklist(acs, level="EMT", mca="mi_base", agency_id=None)
    ids = {i.id for i in items}

    assert "ems.medical.opqrst_radiation" in ids
    assert "ems.medical.diagnostics" in ids


def test_context_flags_include_patient_count_and_spine_when_relevant():
    scenario = {
        "id": "unit_test_multi_patient_trauma",
        "category": "pediatric_trauma",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_trauma_v1",
        "multiple_patients_possible": True,
        "spinal_injury_possible": True,
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    ids = {i.id for i in items}

    assert "ems.trauma.patient_count" in ids
    assert "ems.trauma.spine_protection" in ids


def test_scenario_overlay_item_overrides_inherited_item_with_same_id():
    scenario = {
        "id": "unit_test_override",
        "category": "adult_medical",
        "turnover_target": "hospital",
        "base_patient_care_rubric": "nremt_e202_medical_v1",
        "checklist": [
            {
                **_raw_item("ems.medical.sample_history", point_value=11),
                "description": "Scenario-specific override of inherited history item",
            }
        ],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    history_item = next(i for i in items if i.id == "ems.medical.sample_history")

    assert history_item.point_value == 11
    assert history_item.description == "Scenario-specific override of inherited history item"
    assert history_item.provenance == "scenario_overlay"


def test_medical_base_rubric_exposes_declared_version_and_critical_flag():
    scenario = {
        "id": "unit_test_medical_version",
        "category": "pediatric_medical",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_e202_medical_v1",
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    scene_safety = next(i for i in items if i.id == "ems.medical.scene_safety")
    airway_breathing = next(i for i in items if i.id == "ems.medical.airway_breathing_o2")
    circulation = next(i for i in items if i.id == "ems.medical.circulation")
    priority_transport = next(i for i in items if i.id == "ems.medical.priority_transport")

    assert get_base_rubric_version(scenario) == "2026.05"
    assert scene_safety.critical_failure is True
    assert "scene safety" in (scene_safety.critical_failure_label or "").lower()
    assert airway_breathing.critical_failure is False
    assert circulation.critical_failure is False
    assert priority_transport.critical_failure is False


def test_soft_tissue_head_injury_suppresses_transport_critical_fail_for_non_transport_agency():
    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/trauma/peds_trauma_01_soft_tissue.json"
    scenario = json.loads(scenario_path.read_text())
    scenario["non_transport_agency"] = True

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    ids = {i.id for i in items}

    assert "ems.trauma.priority_transport" not in ids
    assert "peds_trauma_01_soft_tissue.transport_decision" not in ids

    scenario["non_transport_agency"] = False
    transport_items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    priority_transport = next(i for i in transport_items if i.id == "ems.trauma.priority_transport")

    assert priority_transport.critical_failure is False


def test_soft_tissue_head_injury_uses_focused_secondary_survey_not_full_body_survey():
    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/trauma/peds_trauma_01_soft_tissue.json"
    scenario = json.loads(scenario_path.read_text())

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    ids = {i.id for i in items}

    assert "ems.trauma.head_scalp_ears" in ids
    assert "ems.trauma.head_eyes" in ids
    assert "ems.trauma.neck_c_spine" in ids
    assert "ems.trauma.spine_protection" not in ids
    assert "peds_trauma_01_soft_tissue.neuro_baseline" in ids
    assert "peds_trauma_01_soft_tissue.neuro_history" in ids
    assert "peds_trauma_01_soft_tissue.direct_pressure" in ids

    suppressed_full_body_ids = {
        "ems.trauma.neck_trachea",
        "ems.trauma.neck_jugular_veins",
        "ems.trauma.chest_inspect",
        "ems.trauma.chest_palpate",
        "ems.trauma.chest_auscultate",
        "ems.trauma.abdomen_inspect_palpate",
        "ems.trauma.pelvis_assess",
        "ems.trauma.genitalia_perineum_as_needed",
        "ems.trauma.lower_left_pmsc",
        "ems.trauma.lower_right_pmsc",
        "ems.trauma.upper_left_pmsc",
        "ems.trauma.upper_right_pmsc",
        "ems.trauma.posterior_thorax",
        "ems.trauma.lumbar_buttocks",
    }
    assert ids.isdisjoint(suppressed_full_body_ids)


def test_pilot_focused_trauma_scenarios_suppress_irrelevant_full_body_survey_rows():
    scenario_root = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/trauma"
    broad_survey_ids = {
        "ems.trauma.head_scalp_ears",
        "ems.trauma.head_eyes",
        "ems.trauma.head_mouth_nose_face",
        "ems.trauma.neck_trachea",
        "ems.trauma.neck_jugular_veins",
        "ems.trauma.neck_c_spine",
        "ems.trauma.chest_inspect",
        "ems.trauma.chest_palpate",
        "ems.trauma.chest_auscultate",
        "ems.trauma.abdomen_inspect_palpate",
        "ems.trauma.pelvis_assess",
        "ems.trauma.genitalia_perineum_as_needed",
        "ems.trauma.lower_left_pmsc",
        "ems.trauma.lower_right_pmsc",
        "ems.trauma.upper_left_pmsc",
        "ems.trauma.upper_right_pmsc",
        "ems.trauma.posterior_thorax",
        "ems.trauma.lumbar_buttocks",
    }

    choking = json.loads((scenario_root / "peds_trauma_02_partial_choking.json").read_text())
    choking_ids = {i.id for i in load_checklist(choking, level="EMT", mca="mi_base", agency_id=None)}
    assert choking_ids.isdisjoint(broad_survey_ids)

    extremity = json.loads((scenario_root / "peds_trauma_03_extremity.json").read_text())
    extremity_ids = {i.id for i in load_checklist(extremity, level="EMT", mca="mi_base", agency_id=None)}
    assert "ems.trauma.upper_left_pmsc" in extremity_ids
    assert extremity_ids.isdisjoint(broad_survey_ids - {"ems.trauma.upper_left_pmsc"})

    head_injury = json.loads((scenario_root / "peds_trauma_07_head_injury.json").read_text())
    head_injury_ids = {i.id for i in _load_active_checklist(head_injury)}
    assert head_injury_ids.isdisjoint(broad_survey_ids)
    assert "head_injury.neuro_assessment" in head_injury_ids
    assert "head_injury.pupil_assessment" in head_injury_ids
    assert "head_injury.dcap_btls_head" in head_injury_ids


def test_head_injury_uses_reusable_call_type_rubric_for_focused_items():
    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json"
    scenario = json.loads(scenario_path.read_text())

    items = _load_active_checklist(scenario)
    ids = {i.id for i in items}

    assert "ems.trauma.scene_safety" in ids
    assert "head_injury.neuro_assessment" in ids
    assert "head_injury.pupil_assessment" in ids
    assert "head_injury.high_flow_o2" in ids
    assert not any(i.startswith("peds_trauma_07_head_injury.") and i != "peds_trauma_07_head_injury.pat_assessment" for i in ids)
    assert not any(i.startswith("nremt_trauma.") for i in ids)


def test_head_injury_neuro_and_pupil_assessment_are_separate_items():
    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json"
    scenario = json.loads(scenario_path.read_text())

    items = _load_active_checklist(scenario)
    neuro = next(i for i in items if i.id == "head_injury.neuro_assessment")
    pupils = next(i for i in items if i.id == "head_injury.pupil_assessment")

    assert neuro.point_value == 7
    assert pupils.point_value == 3
    assert "pupil" not in neuro.description.lower()
    assert "pupil" in pupils.description.lower()


def test_head_injury_requires_high_flow_o2_protocol_item():
    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json"
    scenario = json.loads(scenario_path.read_text())

    items = _load_active_checklist(scenario)
    high_flow_o2 = next(i for i in items if i.id == "head_injury.high_flow_o2")

    assert high_flow_o2.category == "protocols_treatment"
    assert high_flow_o2.point_value == 2
    assert high_flow_o2.tier1_match.intervention_key == "o2_nrb"
    assert "high-flow" in high_flow_o2.missed_feedback.lower()


def test_head_injury_base_spine_item_credits_smr_intervention():
    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json"
    scenario = json.loads(scenario_path.read_text())

    items = _load_active_checklist(scenario)
    spine = next(i for i in items if i.id == "ems.trauma.spine_protection")

    assert spine.tier1_match.source == "intervention"
    assert spine.tier1_match.intervention_key == "smr"


def test_medical_noi_moi_can_be_satisfied_by_primary_impression_challenge():
    scenario = {
        "id": "unit_test_medical_noi_impression",
        "category": "pediatric_medical",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_e202_medical_v1",
        "checklist": [],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    noi_moi = next(i for i in items if i.id == "ems.medical.noi_moi")

    assert noi_moi.preferred_tier == 1
    assert noi_moi.tier1_match.source == "session_event"
    assert noi_moi.tier1_match.event_type == "challenge_completed"
    assert noi_moi.tier1_match.event_key_pattern == r"(?i)^impression:"


def test_applicability_filter_can_exclude_non_transport_agencies():
    scenario = {
        "id": "unit_test_transport_context",
        "category": "pediatric_medical",
        "turnover_target": "hospital",
        "non_transport_agency": True,
        "checklist": [
            {
                **_raw_item("transport_agency_only"),
                "subtype": "transport",
                "applicable_if": {"non_transport_agency": False},
            },
            {
                **_raw_item("non_transport_disposition"),
                "subtype": "transport",
                "applicable_if": {"non_transport_agency": True},
            },
        ],
    }

    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)

    assert {i.id for i in items} == {"non_transport_disposition"}


def test_additional_ems_base_items_are_suppressed_when_als_codispatched():
    trauma_scenario = {
        "id": "unit_test_trauma_als_codispatched",
        "category": "pediatric_trauma",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_trauma_v1",
        "als_codispatched": True,
        "checklist": [],
    }
    medical_scenario = {
        "id": "unit_test_medical_als_codispatched",
        "category": "pediatric_medical",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_e202_medical_v1",
        "als_codispatched": True,
        "checklist": [],
    }

    trauma_ids = {
        i.id for i in load_checklist(trauma_scenario, level="EMT", mca="mi_base", agency_id=None)
    }
    medical_ids = {
        i.id for i in load_checklist(medical_scenario, level="EMT", mca="mi_base", agency_id=None)
    }

    assert "ems.trauma.additional_ems" not in trauma_ids
    assert "ems.medical.additional_help" not in medical_ids


def test_pediatric_asthma_suppresses_additional_help_because_als_codispatched():
    scenario_path = Path("app/scenarios/pediatric/medical/peds_asthma_01.json")
    scenario = json.loads(scenario_path.read_text())
    agency = {
        "service_type": {"transport": False},
        "als_dispatch": {"co_dispatched": True, "arrival_minutes": 12, "unit_name": "ALS"},
    }
    adapted = adapt_scenario_to_context(scenario, agency, "mi_base")

    item_ids = {
        i.id for i in load_checklist(adapted, level="EMT", mca="mi_base", agency_id=None)
    }

    assert "als_codispatched" not in scenario
    assert adapted["als_codispatched"] is True
    assert "ems.medical.additional_help" not in item_ids


def test_agency_without_als_codispatch_still_suppresses_additional_help_when_no_resource_need():
    scenario_path = Path("app/scenarios/pediatric/medical/peds_asthma_01.json")
    scenario = json.loads(scenario_path.read_text())
    agency = {
        "service_type": {"transport": True},
        "als_dispatch": {"co_dispatched": False},
    }
    adapted = adapt_scenario_to_context(scenario, agency, "mi_base")

    item_ids = {
        i.id for i in load_checklist(adapted, level="EMT", mca="mi_base", agency_id=None)
    }

    assert adapted["als_codispatched"] is False
    assert "ems.medical.additional_help" not in item_ids


def test_additional_help_base_item_requires_true_resource_need():
    scenario = {
        "id": "unit_test_medical_mci",
        "category": "pediatric_medical",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_e202_medical_v1",
        "als_codispatched": False,
        "additional_help_needed": True,
        "checklist": [],
    }

    item_ids = {
        i.id for i in load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    }

    assert "ems.medical.additional_help" in item_ids


def test_agency_codispatch_suppresses_call_type_als_request_items():
    croup = json.loads(Path("app/scenarios/pediatric/medical/peds_croup_01.json").read_text())
    diabetic = json.loads(
        Path("app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json").read_text()
    )
    agency = {
        "service_type": {"transport": False},
        "als_dispatch": {"co_dispatched": True, "arrival_minutes": 12, "unit_name": "ALS"},
    }

    croup_ids = {i.id for i in _load_active_checklist(adapt_scenario_to_context(croup, agency))}
    diabetic_ids = {
        i.id for i in _load_active_checklist(adapt_scenario_to_context(diabetic, agency))
    }

    assert "croup.als_request_if_severe" not in croup_ids
    assert "hypoglycemia.als_request_if_indicated" not in diabetic_ids


def test_croup_secured_nrb_guidance_does_not_imply_withholding_oxygen():
    croup = json.loads(Path("app/scenarios/pediatric/medical/peds_croup_01.json").read_text())
    nrb = croup["vitals"]["interventions"]["o2_nrb"]

    assert nrb["label"] == "Secured NRB mask strapped to face (15 LPM)"
    assert "High-flow O2 via NRB mask" not in nrb["label"]
    reason = nrb["indication_gate"]["reason"]
    assert "Oxygen is appropriate" in reason
    assert "least-agitating tolerated method" in reason
    assert "high-flow blow-by with the NRB held near the face" in reason


def test_pfd_codispatch_suppresses_hypoglycemia_als_request_item():
    diabetic = json.loads(
        Path("app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json").read_text()
    )
    agency = json.loads(Path("app/agencies/pfd.json").read_text())

    adapted = adapt_scenario_to_context(diabetic, agency)
    item_ids = {i.id for i in _load_active_checklist(adapted)}

    assert adapted["als_codispatched"] is True
    assert "hypoglycemia.als_request_if_indicated" not in item_ids


def test_anaphylaxis_codispatched_als_and_short_scene_items_are_conditional():
    scenario = json.loads(
        Path("app/scenarios/pediatric/medical/peds_anaphylaxis_01.json").read_text()
    )
    critical = {
        item["id"]: item
        for item in scenario["correct_treatment"]["critical_actions"]
    }
    recommended_ids = {
        item["id"]
        for item in scenario["correct_treatment"]["recommended_actions"]
    }

    als_item = critical["als_intercept"]
    assert als_item["required"] is False
    assert als_item["als_grace"] is True
    assert "already auto-dispatches ALS" in als_item["description"]
    assert "reassessment" not in recommended_ids
    assert "crew is still on scene" in scenario["correct_treatment"]["clinical_decision_points"]["repeat_epi"]
    assert "scene ends before the 3\u20135 minute reassessment window" in scenario["correct_treatment"]["clinical_decision_points"]["repeat_epi"]


def test_agency_without_codispatch_keeps_call_type_als_request_items_when_not_scenario_suppressed():
    croup = json.loads(Path("app/scenarios/pediatric/medical/peds_croup_01.json").read_text())
    diabetic = json.loads(
        Path("app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json").read_text()
    )
    agency = {
        "service_type": {"transport": True},
        "als_dispatch": {"co_dispatched": False},
    }

    croup_ids = {i.id for i in _load_active_checklist(adapt_scenario_to_context(croup, agency))}
    # Croup: ALS is codispatched for this scenario (severe croup warrants ALS, item requires als_codispatched=false)
    assert "croup.als_request_if_severe" not in croup_ids

    # Hypoglycemia ALS item now requires BOTH als_codispatched=false AND additional_help_needed=true.
    # When a patient responds to oral glucose (default: additional_help_needed=false) → item suppressed.
    diabetic_success_ids = {
        i.id for i in _load_active_checklist(adapt_scenario_to_context(diabetic, agency))
    }
    assert "hypoglycemia.als_request_if_indicated" not in diabetic_success_ids

    # When treatment fails or patient can't swallow (additional_help_needed=true) → item included.
    diabetic_als_needed = dict(diabetic, additional_help_needed=True)
    diabetic_als_ids = {
        i.id for i in _load_active_checklist(adapt_scenario_to_context(diabetic_als_needed, agency))
    }
    assert "hypoglycemia.als_request_if_indicated" in diabetic_als_ids


def test_call_type_als_request_items_require_codispatch_and_resource_need_gates():
    rubric_paths = Path("app/rubrics/nasemso").glob("*_v*.json")
    checked = []

    for path in rubric_paths:
        rubric = json.loads(path.read_text(encoding="utf-8"))
        for item in rubric.get("checklist_items", []):
            item_id = str(item.get("id", ""))
            description = str(item.get("description", ""))
            if "als_request" not in item_id and not re.search(
                r"(?i)\brequests?\s+als\s+(?:intercept|response|unit|crew)?",
                description,
            ):
                continue

            checked.append(item_id)
            applicable_if = item.get("applicable_if") or {}
            assert applicable_if.get("als_codispatched") is False, item_id
            assert applicable_if.get("additional_help_needed") is True, item_id

    assert {
        "hypoglycemia.als_request_if_indicated",
        "croup.als_request_if_severe",
    }.issubset(set(checked))


def test_additional_help_needed_is_inferred_from_high_acuity_concepts():
    scenario = {
        "id": "unit_test_respiratory_failure",
        "category": "pediatric_medical",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_e202_medical_v1",
        "als_codispatched": False,
        "clinical_context": {"concepts": ["respiratory_failure"]},
        "checklist": [],
    }

    item_ids = {
        i.id for i in load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    }

    assert "ems.medical.additional_help" in item_ids


def test_croup_initial_lung_sound_challenge_requires_stridor_answer():
    croup = json.loads(Path("app/scenarios/pediatric/medical/peds_croup_01.json").read_text())

    accepted = {answer.lower() for answer in croup["lung_sound_challenge"]["accepted_answers"]}

    assert "stridor" in accepted
    assert "inspiratory stridor" in accepted
    assert croup["lung_sound_challenge"]["correct_choice_id"] == "inspiratory_stridor"
    assert "clear bilaterally" not in accepted
    assert "clear lung fields" not in accepted


def test_asthma_initial_lung_sound_challenge_requires_wheeze_answer():
    asthma = json.loads(Path("app/scenarios/pediatric/medical/peds_asthma_01.json").read_text())

    initial = asthma["lung_sound_challenge"]
    accepted = {answer.lower() for answer in initial["accepted_answers"]}
    post_treatment_accepted = {
        answer.lower()
        for answer in initial["post_treatment"]["accepted_answers"]
    }

    assert initial["correct_choice_id"] == "expiratory_wheeze"
    assert "wheeze" in accepted
    assert "expiratory wheeze" in accepted
    assert "clear bilaterally" not in accepted
    assert "clear bilaterally" in post_treatment_accepted
    assert initial["post_treatment"]["requires_intervention_id"] == "albuterol_svn"


def test_croup_recommended_reassessment_id_matches_call_type_checklist_item():
    croup = json.loads(Path("app/scenarios/pediatric/medical/peds_croup_01.json").read_text())
    rec_ids = {
        item["id"]
        for item in croup["correct_treatment"]["recommended_actions"]
    }

    assert "reassess_post_treatment" in rec_ids


def test_additional_ems_base_items_remain_when_als_is_not_codispatched():
    trauma_scenario = {
        "id": "unit_test_trauma_no_als_codispatch",
        "category": "pediatric_trauma",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_trauma_v1",
        "als_codispatched": False,
        "additional_help_needed": True,
        "checklist": [],
    }

    item_ids = {
        i.id for i in load_checklist(trauma_scenario, level="EMT", mca="mi_base", agency_id=None)
    }

    assert "ems.trauma.additional_ems" in item_ids


def test_legacy_dispatch_text_can_suppress_additional_ems_item():
    scenario = {
        "id": "unit_test_trauma_legacy_dispatch_als",
        "category": "pediatric_trauma",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_trauma_v1",
        "dispatch": {"text": "Squad 1 respond for head injury. ALS intercept is en route."},
        "checklist": [],
    }

    item_ids = {
        i.id for i in load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    }

    assert "ems.trauma.additional_ems" not in item_ids


def test_additional_ems_pattern_does_not_false_positive_on_medications():
    """'medications' contains 'medic' — word-boundary guard must prevent false credit."""
    trauma_scenario = {
        "id": "unit_test_trauma_additional_ems",
        "category": "pediatric_trauma",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_trauma_v1",
        "additional_help_needed": True,
        "checklist": [],
    }
    medical_scenario = {
        "id": "unit_test_medical_additional_help",
        "category": "pediatric_medical",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_e202_medical_v1",
        "additional_help_needed": True,
        "checklist": [],
    }

    trauma_items = load_checklist(trauma_scenario, level="EMT", mca="mi_base", agency_id=None)
    medical_items = load_checklist(medical_scenario, level="EMT", mca="mi_base", agency_id=None)

    trauma_additional = next(i for i in trauma_items if i.id == "ems.trauma.additional_ems")
    medical_additional = next(i for i in medical_items if i.id == "ems.medical.additional_help")

    # "medications" must NOT match — medic is only a substring, not a whole word
    medications_utterance = "Does he have any allergies, medications or medical history?"
    assert not any(re.search(p, medications_utterance) for p in trauma_additional.tier2_patterns), (
        "ems.trauma.additional_ems falsely credited for 'medications'"
    )
    assert not any(re.search(p, medications_utterance) for p in medical_additional.tier2_patterns), (
        "ems.medical.additional_help falsely credited for 'medications'"
    )

    # Legitimate ALS intercept requests MUST match
    als_utterance = "I need medic 2 to intercept us at the park"
    assert any(re.search(p, als_utterance) for p in trauma_additional.tier2_patterns), (
        "ems.trauma.additional_ems failed to credit 'medic 2' intercept request"
    )
    assert any(re.search(p, als_utterance) for p in medical_additional.tier2_patterns), (
        "ems.medical.additional_help failed to credit 'medic 2' intercept request"
    )

    # Generic ALS backup also matches
    backup_utterance = "Dispatch, request ALS backup please"
    assert any(re.search(p, backup_utterance) for p in trauma_additional.tier2_patterns)
    assert any(re.search(p, backup_utterance) for p in medical_additional.tier2_patterns)


# ---------------------------------------------------------------------------
# MCA expansion filter correctness
# ---------------------------------------------------------------------------

def _expansion_scenario(expansions: list[str]) -> dict:
    """Minimal scenario with one requires_mca_expansion checklist item."""
    return {
        "id": "unit_test_expansion",
        "category": "pediatric_medical",
        "turnover_target": "hospital",
        "mca_expansions": expansions,
        "checklist": [
            {
                "id": "unit_test_expansion.narcan_admin",
                "description": "Naloxone administered per MCA expansion",
                "subtype": "intervention",
                "category": "clinical_performance",
                "point_value": 5,
                "required": "required",
                "applicable_levels": [],
                "allowed_tiers": [1, 2],
                "preferred_tier": 1,
                "tier3_permitted": False,
                "schema_version": "1.0",
                "requires_mca_expansion": "narcan_expansion",
                "tier2_patterns": ["(?i)(naloxone|narcan)"],
                "done_feedback": "Naloxone administered correctly per expansion.",
                "missed_feedback": "Naloxone not administered — required under this MCA.",
            }
        ],
    }


def test_mca_expansion_item_included_when_expansion_is_active():
    """Item with requires_mca_expansion is included when that expansion is in mca_expansions."""
    scenario = _expansion_scenario(expansions=["narcan_expansion"])
    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    ids = {i.id for i in items}
    assert "unit_test_expansion.narcan_admin" in ids, (
        "Expansion item should be included when the expansion key is active"
    )


def test_mca_expansion_item_excluded_when_expansion_not_active():
    """Item with requires_mca_expansion is excluded when that expansion is absent from mca_expansions."""
    scenario = _expansion_scenario(expansions=[])
    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    ids = {i.id for i in items}
    assert "unit_test_expansion.narcan_admin" not in ids, (
        "Expansion item should be excluded when the expansion key is not active"
    )


def test_mca_expansion_filter_does_not_compare_against_mca_string():
    """The MCA string ('mi_base') must not match an expansion key ('narcan_expansion').
    Regression guard against the pre-fix behaviour where the filter compared
    requires_mca_expansion directly to the mca parameter."""
    scenario = _expansion_scenario(expansions=[])
    # Passing mca="narcan_expansion" simulates the pre-fix bug where the MCA string
    # happened to equal the expansion key — it must still be excluded because
    # mca_expansions (the resolved set) is empty.
    items = load_checklist(scenario, level="EMT", mca="narcan_expansion", agency_id=None)
    ids = {i.id for i in items}
    assert "unit_test_expansion.narcan_admin" not in ids, (
        "MCA string must not substitute for expansion key — filter must use mca_expansions set"
    )


def test_febrile_seizure_recovery_position_and_history_have_structured_credit_paths():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_febrile_seizure_01.json").read_text(encoding="utf-8"))
    items = {item.id: item for item in load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)}

    protect = items["peds_febrile_seizure_01.protect_from_injury"]
    assert protect.tier1_match.source == "intervention"
    assert set(protect.tier1_match.intervention_keys) == {"protect_from_injury", "recovery_position"}

    seizure_history = items["peds_febrile_seizure_01.seizure_history"]
    assert seizure_history.requirement_logic == "all"
    assert len(seizure_history.tier1_matches) == 2
    assert all(match.source == "finding" for match in seizure_history.tier1_matches)
    assert all(match.finding_type == "history" for match in seizure_history.tier1_matches)
    patterns = "\n".join(match.finding_key_pattern for match in seizure_history.tier1_matches)
    assert "seizure duration" in patterns
    assert "medications" in patterns
