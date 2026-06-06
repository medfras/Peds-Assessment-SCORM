import json
from datetime import date
from pathlib import Path

from app.scenario_engine import (
    IN_SCENARIO_LEXI_HINTS,
    _format_patient_dob,
    _patient_dob_from_relative,
    get_public_scenario_data,
)


STANDARD_BASELINE_VITAL_KEYS = {
    "hr",
    "rr",
    "spo2",
    "bp",
    "temp",
    "gcs",
    "blood_glucose",
    "skin_color",
    "cap_refill",
    "pupils",
    "lung_sounds",
    "work_of_breathing",
}


def _scenario_files():
    return sorted(Path("app/scenarios").rglob("*.json"))


def _playable_scenario_files():
    paths = []
    for path in _scenario_files():
        scenario = json.loads(path.read_text(encoding="utf-8"))
        vitals = scenario.get("vitals") or {}
        if {"id", "dispatch", "patient", "vitals"}.issubset(scenario) and "interventions" in vitals:
            paths.append(path)
    return paths


def test_all_scenarios_author_full_baseline_vital_set():
    missing_by_file = {}
    for path in _playable_scenario_files():
        scenario = json.loads(path.read_text(encoding="utf-8"))
        baseline = scenario.get("vitals", {}).get("baseline", {})
        missing = sorted(STANDARD_BASELINE_VITAL_KEYS - set(baseline))
        if missing:
            missing_by_file[str(path)] = missing

    assert missing_by_file == {}


def test_authored_gcs_matches_patient_gcs_assessment():
    mismatches = {}
    for path in _playable_scenario_files():
        scenario = json.loads(path.read_text(encoding="utf-8"))
        baseline_gcs = scenario.get("vitals", {}).get("baseline", {}).get("gcs", {})
        expected_gcs = scenario.get("patient", {}).get("gcs_assessment")
        if not expected_gcs:
            continue
        if not baseline_gcs:
            mismatches[str(path)] = "patient.gcs_assessment is present but vitals.baseline.gcs is missing"
            continue
        if int(baseline_gcs.get("value")) != int(expected_gcs.get("total")):
            mismatches[str(path)] = {
                "baseline": baseline_gcs.get("value"),
                "expected": expected_gcs.get("total"),
            }

    assert mismatches == {}


def test_authored_avpu_has_required_shape_when_present():
    invalid_by_file = {}
    valid_values = {"alert", "verbal", "pain", "unresponsive"}
    for path in _playable_scenario_files():
        scenario = json.loads(path.read_text(encoding="utf-8"))
        avpu = scenario.get("patient", {}).get("avpu_assessment")
        if avpu is None:
            continue
        if not isinstance(avpu, dict):
            invalid_by_file[str(path)] = "patient.avpu_assessment must be an object when present"
            continue
        value = str(avpu.get("value", "")).strip().lower()
        description = str(avpu.get("description", "")).strip()
        rationale = str(avpu.get("rationale", "")).strip()
        if value not in valid_values or not description or not rationale:
            invalid_by_file[str(path)] = {
                "value": avpu.get("value"),
                "description_present": bool(description),
                "rationale_present": bool(rationale),
            }

    assert invalid_by_file == {}


def test_gcs_assessment_has_component_level_authoring():
    gaps = {}
    for path in _playable_scenario_files():
        scenario = json.loads(path.read_text(encoding="utf-8"))
        gcs = scenario.get("patient", {}).get("gcs_assessment")
        if not gcs:
            continue
        missing = [key for key in ("e", "v", "m", "total", "rationale") if key not in gcs or gcs.get(key) in ("", None)]
        baseline = scenario.get("vitals", {}).get("baseline", {}).get("gcs", {})
        baseline_text = " ".join(str(baseline.get(k, "")) for k in ("detail", "display", "label"))
        if missing:
            gaps[str(path)] = {"missing": missing}
            continue
        if not any(token in baseline_text.lower() for token in ("e", "eye", "alert", "unresponsive", "opens")):
            gaps[str(path)] = {"baseline_gcs_detail": baseline_text}

    assert gaps == {}


def test_gcs_challenge_descriptions_cover_dynamic_gcs_states():
    gaps = {}
    for path in _playable_scenario_files():
        scenario = json.loads(path.read_text(encoding="utf-8"))
        gcs = scenario.get("patient", {}).get("gcs_assessment")
        if not gcs:
            continue
        if not str(gcs.get("challenge_description", "")).strip():
            gaps[str(path)] = "missing initial challenge_description"
            continue
        for idx, state in enumerate(gcs.get("after_interventions", []) or []):
            if not str(state.get("challenge_description", "")).strip():
                gaps[str(path)] = f"missing after_interventions[{idx}].challenge_description"
                break
        for idx, state in enumerate(gcs.get("deterioration_descriptions", []) or []):
            if not str(state.get("description", "")).strip():
                gaps[str(path)] = f"missing deterioration_descriptions[{idx}].description"
                break

    assert gaps == {}


def test_public_scenario_payload_exposes_gcs_and_avpu_answer_keys():
    missing_by_scenario = {}
    for path in _playable_scenario_files():
        scenario = json.loads(path.read_text(encoding="utf-8"))
        scenario_id = scenario["id"]
        public = get_public_scenario_data(scenario)
        patient = public.get("patient", {})
        missing = [key for key in ("age", "sex") if patient.get(key) in (None, "")]
        for optional_key in ("gcs_assessment", "avpu_assessment"):
            if optional_key in scenario.get("patient", {}) and patient.get(optional_key) in (None, ""):
                missing.append(optional_key)
        if missing:
            missing_by_scenario[scenario_id] = missing

    assert missing_by_scenario == {}


def test_public_scenario_payload_inserts_concrete_relative_infant_dob():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_febrile_seizure_01.json").read_text(encoding="utf-8"))
    public = get_public_scenario_data(scenario)
    expected_dob = _format_patient_dob(
        _patient_dob_from_relative("about 6 months before today's date", today=date.today())
    )

    assert public["patient"]["dob"] == expected_dob
    serialized_history = json.dumps(public["history_response_map"], ensure_ascii=False)
    assert f"Patient Date of Birth={expected_dob}" in serialized_history
    assert "Patient Date of Birth=about 6 months before today's date" not in serialized_history


def test_public_scenario_payload_inserts_concrete_month_day_dob():
    scenario = json.loads(Path("app/scenarios/pediatric/trauma/peds_trauma_01_soft_tissue.json").read_text(encoding="utf-8"))
    public = get_public_scenario_data(scenario)
    current_year = date.today().year
    expected_year = current_year - 4 - (1 if date(current_year, 4, 9) > date.today() else 0)
    expected_dob = f"Apr 9, {expected_year}"

    assert public["patient"]["dob"] == expected_dob
    serialized_history = json.dumps(public["history_response_map"], ensure_ascii=False)
    assert f"Patient Date of Birth={expected_dob}" in serialized_history
    assert "Patient Date of Birth=April 9" not in serialized_history


def test_public_scenario_payload_uses_generic_in_scenario_lexi_chips():
    for path in _playable_scenario_files():
        scenario = json.loads(path.read_text(encoding="utf-8"))
        public = get_public_scenario_data(scenario)

        assert public.get("lexi_hints") == IN_SCENARIO_LEXI_HINTS


def test_public_scenario_payload_includes_sanitized_speaker_roles():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_croup_01.json").read_text(encoding="utf-8"))
    public = get_public_scenario_data(scenario)

    sarah = public["personas"]["sarah"]
    assert sarah["name"] == "Sarah"
    assert sarah["role"] == "family"
    assert sarah["relation"] == "mother"
    assert "clinical_state_instructions" not in sarah
    assert "persona_rules" not in sarah
    assert public["scene"].get("bystanders", []) == scenario["scene"].get("bystanders", [])


def test_public_scenario_payload_does_not_expose_scenario_specific_lexi_hints():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_croup_01.json").read_text(encoding="utf-8"))
    public = get_public_scenario_data(scenario)
    live_chip_text = json.dumps(public.get("lexi_hints", []), sort_keys=True).lower()

    assert "croup" not in live_chip_text
    assert "asthma" not in live_chip_text
    assert "agitated infant" not in live_chip_text


def test_public_scenario_payload_masks_patient_name_in_deferred_address_hint():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_febrile_seizure_01.json").read_text(encoding="utf-8"))
    public = get_public_scenario_data(scenario)

    assert public["patient"]["pcr_demographics_deferred"] is True
    assert "Chloe" not in public.get("chat_address_hint", "")


def test_febrile_seizure_has_primary_impression_challenge():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_febrile_seizure_01.json").read_text(encoding="utf-8"))
    challenge = scenario.get("impression_challenge") or {}

    assert challenge.get("enabled") is True
    assert challenge.get("trigger_milestone") == "primary_survey_complete"
    assert challenge.get("correct") == "Active seizure / likely febrile seizure"
    assert "Hypoglycemic seizure" in challenge.get("options", [])
    assert "Meningitis / CNS infection" in challenge.get("options", [])
