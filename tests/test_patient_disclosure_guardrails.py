from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET


from app.ai_client import (  # noqa: E402
    _NON_EMS_PERSONA_BOUNDARY,
    _PROFESSIONALISM_AFFECTIVE_DOMAIN_GUIDANCE,
    _UNIVERSAL_PATIENT_DISCLOSURE_CONTRACT,
    authored_history_findings_from_text,
    _build_history_response_map_prompt,
    _build_initial_complaint_prompt,
    _build_auto_intervention_directive,
    _build_deterministic_history_response,
    _build_realism_rules,
    _build_resolved_history_directive,
    _build_scene_routing_directive,
    _build_standard_exam_findings_prompt,
    _compute_professionalism_hardened_constraints,
    _professionalism_floor_for_transcript,
    _infer_scene_addressee,
    _infer_scene_followup_addressee,
    _message_looks_like_explicit_assessment_action,
    _resolve_history_response_entry,
)
from app.pediatric_length_based_tape import band_for_weight
from app.scenario_engine import (
    _public_intervention_fto_guidance,
    adapt_scenario_to_context,
    get_public_scenario_data,
    load_scenario,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_universal_patient_disclosure_contract_blocks_unsolicited_coaching():
    contract = _UNIVERSAL_PATIENT_DISCLOSURE_CONTRACT

    assert "apply to every scenario" in contract
    assert "override scenario-specific persona notes" in contract
    assert "information sources, not instructors" in contract
    assert "must not coach the learner" in contract
    assert "must not" in contract and "recommend EMS actions" in contract
    assert "what can we do for you?" in contract.lower()
    assert "not an EMS care plan" in contract
    assert "Do not emit HISTORY or EXAM tags" in contract


def test_authored_history_findings_extracts_only_scenario_map_tags():
    scenario = load_scenario("peds_trauma_01_soft_tissue")

    text = (
        "He was running in the living room and tripped. "
        "[[HISTORY: Events=running in the living room, tripped on the rug, struck the corner of the coffee table]] "
        "[[HISTORY: Allergies=made up allergy]]"
    )

    findings = authored_history_findings_from_text(text, scenario)

    assert findings == [
        {
            "key": "Events",
            "value": "running in the living room, tripped on the rug, struck the corner of the coffee table",
        }
    ]


def test_pediatric_length_based_tape_reference_is_deterministic_for_patient_weight():
    scenario = load_scenario("peds_anaphylaxis_01")
    adapted = adapt_scenario_to_context(scenario, {}, "mi_base")

    ref = adapted["patient"]["length_based_tape"]

    assert ref["color"] == "Orange"
    assert ref["weight_kg_range"] == "24-29 kg"
    assert ref["weight_lb_range"] == "52-64 lb"
    assert ref["age_range"] == "7-9 years"
    public = get_public_scenario_data(adapted)
    assert public["patient"]["length_based_tape"]["color"] == "Orange"


def test_michigan_length_based_tape_black_adult_band_is_open_ended():
    assert band_for_weight(36)["color"] == "Green"
    assert band_for_weight(37)["color"] == "Black"
    assert band_for_weight(37)["weight_kg_range"] == ">36 kg"
    assert band_for_weight(37)["age_range"] == ">14 years"


def test_pediatric_length_based_tape_supports_agency_band_overrides():
    agency = {
        "pediatric_length_based_tape": {
            "id": "local_tape_v1",
            "label": "Local pediatric tape",
            "band_overrides": {
                "orange": {
                    "length_cm_range": "local orange measurement",
                    "equipment_note": "local kit shelf 4",
                }
            },
        }
    }

    band = band_for_weight(27, agency)

    assert band["system_id"] == "local_tape_v1"
    assert band["system_label"] == "Local pediatric tape"
    assert band["color"] == "Orange"
    assert band["length_cm_range"] == "local orange measurement"
    assert band["equipment_note"] == "local kit shelf 4"


def test_broselow_history_question_uses_adapted_tape_measurement_context():
    scenario = load_scenario("peds_croup_01")
    adapted = adapt_scenario_to_context(scenario, {}, "mi_base")

    resolved = _resolve_history_response_entry("what broselow color and measurement is she", adapted)

    assert resolved is not None
    _, entry = resolved
    payload = json.dumps(entry, ensure_ascii=False).lower()
    assert "red" in payload
    assert "17-20 lb" in payload
    assert "7-10 months" in payload


def test_realism_rules_include_universal_contract_for_all_personas():
    rules = _build_realism_rules(
        {
            "sarah": {
                "name": "Sarah",
                "speaking_style": "Scared parent.",
                "role": "family",
            }
        }
    )

    assert "Universal patient/family/bystander disclosure contract" in rules
    assert "Sarah: Scared parent." in rules
    assert "Broad openers" in rules
    assert "one short lay sentence" in rules
    assert "stridor" in rules
    assert "croup" in rules


def test_non_ems_persona_boundary_blocks_clinical_role_bleed():
    boundary = _NON_EMS_PERSONA_BOUNDARY

    assert "not acting as EMS or medical control" in boundary
    assert "Use lay language" in boundary
    assert "do not recommend treatments" in boundary
    assert "do not suggest protocols or next steps" in boundary
    assert "do not use clinical terminology" in boundary


def test_opqrst_prompt_no_longer_maps_broad_openers_to_events():
    source = open("app/ai_client.py", encoding="utf-8").read()

    assert '"What happened?" / "What\'s going on?"' not in source
    assert '"What happened right before this?"' in source
    assert "If the answer is only a broad chief-concern sentence" in source


def test_opqrst_quality_includes_reflective_confirmation():
    source = open("app/ai_client.py", encoding="utf-8").read()

    assert "Reflective confirmation of symptom character also counts as Quality" in source
    assert "loud barking cough with a high pitch" in source
    assert "[[EXAM: Quality=...]]" in source


def test_physical_exam_prompt_uses_authored_exam_findings_and_neutral_fallback():
    source = open("app/ai_client.py", encoding="utf-8").read()

    assert "AUTHORED STANDARD EXAM FINDINGS" in source
    assert "no scenario-specific abnormal finding noted" in source
    assert "do NOT invent a specific abnormality" in source


def test_standard_exam_findings_prompt_formats_authored_answer_key():
    prompt = _build_standard_exam_findings_prompt(
        {
            "standard_exam_findings": {
                "dcap_btls_head": {
                    "label": "DCAP-BTLS Head",
                    "exam_key": "DCAP-BTLS Head",
                    "aliases": ["head DCAP", "inspect and palpate head"],
                    "finding": "laceration; no deformity",
                    "notes": "Keep terms separate.",
                }
            }
        }
    )

    assert "## AUTHORED STANDARD EXAM FINDINGS" in prompt
    assert "[[EXAM: DCAP-BTLS Head=laceration; no deformity]]" in prompt
    assert "head DCAP" in prompt
    assert "Keep terms separate" in prompt


def test_body_map_extremities_use_patient_anatomical_left_right():
    body_map_dir = PROJECT_ROOT / "static" / "img" / "body-map"
    extremity_regions = {
        "arm-upper-left",
        "arm-upper-right",
        "arm-lower-left",
        "arm-lower-right",
        "hand-left",
        "hand-right",
        "leg-upper-left",
        "leg-upper-right",
        "leg-lower-left",
        "leg-lower-right",
        "foot-left",
        "foot-right",
    }

    for svg_path in [
        body_map_dir / "body-map-adult.svg",
        body_map_dir / "body-map-pediatric.svg",
        body_map_dir / "body-map-infant.svg",
    ]:
        root = ET.parse(svg_path).getroot()
        ns = {"svg": "http://www.w3.org/2000/svg"}
        for group in root.findall(".//svg:g[@data-region]", ns):
            region = group.attrib["data-region"]
            if region not in extremity_regions:
                continue
            child = next(iter(group))
            if child.tag.endswith("rect"):
                center_x = float(child.attrib["x"]) + float(child.attrib["width"]) / 2
            elif child.tag.endswith("ellipse"):
                center_x = float(child.attrib["cx"])
            else:
                continue

            # Front-facing patient: screen-left is the patient's right side.
            expected_side = "right" if center_x < 100 else "left"
            assert region.endswith(expected_side), f"{svg_path.name}: {region} at x={center_x}"


def test_body_map_extremity_exams_include_movement_motor_options():
    source = (PROJECT_ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")

    for payload in [
        "I am assessing left hand and forearm movement, motor function, and grip strength.",
        "I am assessing right hand and forearm movement, motor function, and grip strength.",
        "I am assessing left hand and finger movement and motor function.",
        "I am assessing right hand and finger movement and motor function.",
        "I am assessing left lower leg, ankle, and toe movement and motor function.",
        "I am assessing right lower leg, ankle, and toe movement and motor function.",
        "I am assessing left foot and toe movement and motor function.",
        "I am assessing right foot and toe movement and motor function.",
    ]:
        assert payload in source


def test_extremity_scenario_authors_pain_and_side_specific_exam_aliases():
    source = (PROJECT_ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    scenario = json.loads((PROJECT_ROOT / "app/scenarios/pediatric/trauma/peds_trauma_03_extremity.json").read_text(encoding="utf-8"))

    assert "function _handleAuthoredStandardExamAction" in source
    assert "function _maybeRecordCmsAssessmentFromMessage" in source
    assert "function _scenarioCmsTargetMatchesMessage" in source
    assert "function _hasAppliedOrRecordedIntervention" in source
    assert "_maybeRecordCmsAssessmentFromMessage(" in source
    assert '"action-menu-exam"' in source
    assert "assess_cms_post" in source
    assert scenario["chat_placeholder"] == "Ask questions or give EMS instructions..."
    assert scenario["vitals"]["baseline"]["pain"]["value"].startswith("9/10")
    left_aliases = scenario["standard_exam_findings"]["left_hand_cms"]["aliases"]
    right_aliases = scenario["standard_exam_findings"]["right_forearm_normal"]["aliases"]
    assert "left hand and forearm sensation" in left_aliases
    assert "left hand and forearm movement" in left_aliases
    assert "right hand and forearm sensation" in right_aliases
    assert "right hand and forearm movement" in right_aliases


def test_head_injury_history_map_and_neuro_trigger_are_pilot_safe():
    scenario = json.loads((PROJECT_ROOT / "app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json").read_text(encoding="utf-8"))

    assert scenario["chat_placeholder"] == "Ask questions or give EMS instructions..."
    assert "Use roles like patient" in scenario["chat_address_hint"]
    assert "Marcus" not in scenario["chat_placeholder"]
    assert "Susan" not in scenario["chat_address_hint"]
    response_map = scenario["history_response_map"]
    assert "mechanism" in response_map
    assert "loc_history" in response_map
    assert "vomiting_history" in response_map
    assert "threw up once" in response_map["chief_concern"]["answer"]
    assert "vomited once" in response_map["vomiting_history"]["answer"]
    assert any("[[HISTORY: LOC=" in tag for tag in response_map["loc_history"]["tags"])
    assert any("[[HISTORY: Vomiting=" in tag for tag in response_map["vomiting_history"]["tags"])
    neuro_patterns = scenario["vitals"]["interventions"]["neuro_assessment"]["detection_patterns"]
    assert "confused" not in neuro_patterns
    critical_ids = {item["id"] for item in scenario["correct_treatment"]["critical_actions"]}
    recommended_ids = {item["id"] for item in scenario["correct_treatment"]["recommended_actions"]}
    assert "head_injury.high_flow_o2" in critical_ids
    assert "o2_administration" not in recommended_ids
    rubric = json.loads((PROJECT_ROOT / "app/rubrics/nasemso/head_injury_v1.json").read_text(encoding="utf-8"))
    assert "ai_roleplay_tag" in rubric["source_role_map"]["history_obtained"]["training"]
    assert "ai_roleplay_tag" not in rubric["source_role_map"]["ems_performed_exam"]["training"]


def test_native_tts_honors_authored_scenario_speed():
    source = (PROJECT_ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    scenario = json.loads((PROJECT_ROOT / "app/scenarios/pediatric/trauma/peds_trauma_03_extremity.json").read_text(encoding="utf-8"))
    emily_tts = scenario["personas"]["emily"]["tts"]
    laura_tts = scenario["personas"]["laura"]["tts"]

    assert "function _makeUtterance(text, gender, age, speed = null)" in source
    assert "slot._speed = tts.payload.speed" in source
    assert "_makeUtterance(slot._text, slot._gender, slot._age, slot._speed)" in source
    assert "child:   { pitch: 1.16, rate: 1.04 }" in source
    assert 'const timeoutMs = tts.payload.speaker_role === "alex" ? 6500 : 12000' in source
    assert "Cloud TTS ${reason}; falling back to browser synthesis" in source
    assert "skipping synthesized speech to avoid voice mismatch" not in source
    assert emily_tts["enabled"] is True
    assert emily_tts["voice_role"] == "patient"
    assert emily_tts["gender"] == "female"
    assert emily_tts["age_band"] == "child"
    assert 1.05 <= emily_tts["speed"] <= 1.15
    assert "clear distress" in emily_tts["delivery"]
    assert "not robotic or exaggerated" in emily_tts["delivery"]
    assert "robotic" in emily_tts["avoid"]
    assert "provider_voice" not in emily_tts
    assert 1.0 <= laura_tts["speed"] <= 1.2
    assert "Avoid calm" in scenario["personas"]["emily"]["speaking_style"]
    assert "monotone" in scenario["personas"]["emily"]["speaking_style"]
    assert "emphasized pain words" in scenario["personas"]["emily"]["speaking_style"]
    assert "Avoid calm, slow" in scenario["personas"]["emily"]["speaking_style"]
    assert "adult-like sentences" in scenario["personas"]["emily"]["speaking_style"]


def test_history_response_map_prompt_renders_tags_and_boundaries():
    prompt = _build_history_response_map_prompt(
        {
            "history_response_map": {
                "quality": {
                    "label": "OPQRST Quality",
                    "triggers": ["you said it's a loud barking cough with a high pitch"],
                    "answer": "Yes. It sounds harsh and barky.",
                    "tag": "[[EXAM: Quality=harsh bark-like cough]]",
                    "do_not_include": ["onset time", "treatment suggestions"],
                }
            }
        }
    )

    assert "SCENARIO-SPECIFIC HISTORY RESPONSE MAP" in prompt
    assert "OPQRST Quality" in prompt
    assert "loud barking cough with a high pitch" in prompt
    assert "[[EXAM: Quality=harsh bark-like cough]]" in prompt
    assert "Do NOT include: onset time; treatment suggestions" in prompt


def test_initial_complaint_prompt_renders_broad_opener_boundary():
    prompt = _build_initial_complaint_prompt(
        {
            "initial_complaint": {
                "speaker": "Sarah",
                "lay_summary": "She has a bad cough and she's having trouble breathing.",
                "do_not_include": ["onset time", "full OPQRST/SAMPLE"],
            }
        }
    )

    assert "INITIAL COMPLAINT" in prompt
    assert "Speaker: Sarah" in prompt
    assert "She has a bad cough and she's having trouble breathing." in prompt
    assert "how can we help" in prompt
    assert "Do NOT include: onset time; full OPQRST/SAMPLE" in prompt


def test_croup_history_response_map_covers_quality_and_help_goal():
    with open("app/scenarios/pediatric/medical/peds_croup_01.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    initial = scenario["initial_complaint"]
    assert initial["lay_summary"] == "She has a bad cough and she's having trouble breathing."
    assert "barking" in initial["do_not_include"]
    assert "full OPQRST/SAMPLE" in initial["do_not_include"]

    response_map = scenario["history_response_map"]
    assert response_map["chief_concern"]["answer"] == initial["lay_summary"]
    assert response_map["quality"]["tag"].startswith("[[EXAM: Quality=")
    assert "okay you said it's loud barking cough with high pitch" in response_map["quality"]["triggers"]
    assert "how long has it been going on" in response_map["time_prior_episode"]["triggers"]
    assert "continuous since about 01:50" in response_map["time_prior_episode"]["tag"]
    assert response_map["help_goal"]["tags"] == []
    assert "oxygen" in response_map["help_goal"]["do_not_include"]
    assert "last time she had anything to eat or drink" in response_map["last_oral_intake"]["triggers"]
    assert "work of breathing" in response_map["associated_uri_fever"]["do_not_include"]
    assert "lungs sound clear" in response_map["associated_uri_fever"]["do_not_include"]
    assert "If asked broadly about other signs or symptoms" in scenario["personas"]["sarah"]["clinical_state_instructions"]
    assert "keep Lily calm and upright" in scenario["personas"]["alex"]["description"]


def test_asthma_history_response_map_covers_compound_sample_request():
    with open("app/scenarios/pediatric/medical/peds_asthma_01.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    response_map = scenario["history_response_map"]
    sample_full = response_map["sample_full"]

    assert "signs and symptoms allergies medications past medical history last oral intake events" in sample_full["triggers"]
    assert "two ER visits" in sample_full["answer"]
    assert "mac and cheese" in sample_full["answer"]
    assert any(tag.startswith("[[HISTORY: PMH=") for tag in sample_full["tags"])
    assert any(tag.startswith("[[HISTORY: Last Oral Intake=") for tag in sample_full["tags"])
    assert any(tag.startswith("[[HISTORY: Events=") for tag in sample_full["tags"])


def test_diabetic_history_response_map_covers_compound_sample_request():
    with open("app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    sample_full = scenario["history_response_map"]["sample_full"]

    assert "signs and symptoms allergies medications medical history last oral intake events" in sample_full["triggers"]
    assert "Omnipod" in sample_full["answer"]
    assert "CGM alarm" in sample_full["answer"]
    assert any(tag.startswith("[[HISTORY: Signs and Symptoms=") for tag in sample_full["tags"])
    assert any(tag.startswith("[[HISTORY: Allergies=") for tag in sample_full["tags"])
    assert any(tag.startswith("[[HISTORY: Medications=") for tag in sample_full["tags"])
    assert any(tag.startswith("[[HISTORY: PMH=") for tag in sample_full["tags"])
    assert any(tag.startswith("[[HISTORY: Last Oral Intake=") for tag in sample_full["tags"])
    assert any(tag.startswith("[[HISTORY: Events=") for tag in sample_full["tags"])
    assert "Priority entry" in sample_full["notes"]

    onset_time = scenario["history_response_map"]["onset_time"]
    assert "when did this start" in onset_time["triggers"]
    assert any(tag.startswith("[[HISTORY: Onset=") for tag in onset_time["tags"])
    assert any(tag.startswith("[[HISTORY: Time=") for tag in onset_time["tags"])


def test_deferred_pcr_demographic_scenarios_have_patient_scoped_header_tags():
    scenario_paths = Path("app/scenarios").rglob("*.json")
    checked = []
    for path in scenario_paths:
        with open(path, encoding="utf-8") as fh:
            scenario = json.load(fh)
        patient = scenario.get("patient") or {}
        if not patient.get("pcr_demographics_deferred"):
            continue
        checked.append(path.name)
        response_map = scenario.get("history_response_map") or {}
        tags = []
        for entry in response_map.values():
            if not isinstance(entry, dict):
                continue
            if entry.get("tag"):
                tags.append(entry["tag"])
            tags.extend(entry.get("tags") or [])
        joined = "\n".join(tags)

        assert "[[HISTORY: Patient Name=" in joined, path
        assert "[[HISTORY: Patient Age=" in joined or "[[HISTORY: Patient Date of Birth=" in joined, path
        assert "[[HISTORY: Patient Date of Birth=" in joined, path
        if patient.get("weight_kg") or patient.get("weight_display"):
            assert "[[HISTORY: Patient Weight=" in joined, path

    assert {
        "adult_cardiac_arrest_01_bls.json",
        "newborn_resus_01_nrp.json",
        "peds_cardiac_arrest_01_bls.json",
        "peds_asthma_01.json",
        "peds_croup_01.json",
        "peds_diabetic_emergency_01.json",
        "peds_trauma_01_soft_tissue.json",
    }.issubset(set(checked))


def test_all_clinical_scenarios_author_patient_dob_month_day_contract():
    month_day = re.compile(
        r"^(January|February|March|April|May|June|July|August|September|October|November|December) [1-9][0-9]?$"
    )
    stale_unknown_phrases = (
        "don't have his date of birth",
        "don't have her date of birth",
        "don't have my exact date of birth",
        "don't have his exact date of birth",
        "don't have her exact date of birth",
        "don't know my exact date of birth",
    )

    checked = []
    for path in Path("app/scenarios").rglob("*.json"):
        with open(path, encoding="utf-8") as fh:
            scenario = json.load(fh)
        patient = scenario.get("patient") or {}
        if not patient.get("pcr_demographics_deferred"):
            continue
        checked.append(path.name)

        dob_month_day = patient.get("dob_month_day")
        dob_relative = patient.get("dob_relative")
        assert dob_month_day or dob_relative, path
        age_years = patient.get("age")
        age_months = patient.get("age_months")
        is_under_18_months = (
            isinstance(age_months, (int, float)) and age_months < 18
        ) or (
            isinstance(age_years, (int, float)) and age_years < 1.5
        )
        if is_under_18_months:
            assert dob_relative, path
            assert not dob_month_day, path
            assert "before today's date" in dob_relative or dob_relative == "today", path
        elif dob_month_day:
            assert month_day.match(dob_month_day), path
            assert not (dob_relative and "before today's date" in dob_relative), path
        else:
            assert dob_relative == "today", path

        serialized = json.dumps(scenario, ensure_ascii=False).lower()
        for phrase in stale_unknown_phrases:
            assert phrase not in serialized, path

    assert checked


def test_scenario_design_documents_pcr_header_demographic_contract():
    text = Path("docs/SCENARIO_DESIGN_EMS.md").read_text(encoding="utf-8")

    assert "PCR header behavior is intentionally universal" in text
    assert "pcr_demographics_deferred" in text
    assert "patient.dob_month_day" in text
    assert "Patient Date of Birth=May 13" in text
    assert "PCR header demographics are part of the patient care record" in text
    assert "DMIST/turnover is a separate verbal handoff artifact" in text


def test_diabetic_cgm_history_response_is_not_a_vital():
    with open("app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    cgm_reading = scenario["history_response_map"]["cgm_reading"]
    prompt = _build_history_response_map_prompt(scenario)

    assert "what was his last blood sugar" in cgm_reading["triggers"]
    assert cgm_reading["tag"].startswith("[[HISTORY: CGM Reading=38 mg/dL")
    assert "[[VITAL:" not in cgm_reading["tag"]
    assert "not an EMS-obtained vital sign" in cgm_reading["notes"]
    assert "Historical CGM / pump-app reading" in prompt
    assert "[[HISTORY: CGM Reading=38 mg/dL alarm about 20 minutes ago]]" in prompt


def test_ai_prompt_keeps_reported_cgm_values_out_of_vitals_log():
    source = open("app/ai_client.py", encoding="utf-8").read()

    assert "CGM alarm values" in source
    assert "NEVER emit [[VITAL: Blood Glucose=...]] for those reports" in source
    assert "Only an on-scene EMS glucometer/finger-stick check" in source
    assert "Historically reported vitals belong in HISTORY only" in source


def test_frontend_rejects_vital_tags_from_non_ems_sources():
    source = open("static/js/app.js", encoding="utf-8").read()

    assert "function _vitalTagSourceAllowed" in source
    assert "Ignoring VITAL tag from non-EMS/history source" in source
    assert "role === \"partner\"" in source
    assert "last|prior|previous|home|before ems" in source


def test_frontend_derives_relative_dob_from_age_display_when_age_missing():
    source = open("static/js/app.js", encoding="utf-8").read()

    assert "function _scenarioPatientAgeYears" in source
    assert "patient.age_display" in source
    assert "year-old" in source
    assert "const years = _scenarioPatientAgeYears(scenario)" in source
    assert "const patientAge = _scenarioPatientAgeYears()" in source


def test_frontend_prefers_authored_patient_dob_month_day_contract():
    source = open("static/js/app.js", encoding="utf-8").read()
    dob_function = source[source.index("function _scenarioPatientDobDate"):source.index("function _pcrDemographicsDeferred")]

    assert "patient.dob_month_day" in dob_function
    assert "patient.dob_relative" in dob_function
    assert "relativeDob === \"today\"" in dob_function
    assert "_derivePatientDobFromMonthDay" in dob_function


def test_frontend_deferred_pcr_header_does_not_prepopulate_authored_age():
    source = open("static/js/app.js", encoding="utf-8").read()

    deferred_branch = source[source.index("function _renderPcrHeader"):source.index("function _deferredPatientInfoParts")]

    assert "const idParts = []" in deferred_branch
    assert "if (h.age) idParts.push(h.age)" in deferred_branch
    assert "|| \"Patient\"" in deferred_branch


def test_frontend_plain_text_demographic_capture_requires_matching_question():
    source = open("static/js/app.js", encoding="utf-8").read()

    capture_fn = source[source.index("function _captureDeferredPcrHeaderFromPlainText"):source.index("function processAiTags")]

    assert "_lastUserMessageRequestsPatientName() && ptName" in capture_fn
    assert "_lastUserMessageRequestsPatientDob() && bornMatch" in capture_fn


def test_frontend_deferred_pcr_history_tags_require_supported_demographic_context():
    source = open("static/js/app.js", encoding="utf-8").read()

    process_fn = source[source.index("function processAiTags"):source.index("function _stripUnrequestedVitalLines")]

    assert "patientHeaderTag && !_historyMapTagAllowedForContext" in process_fn
    assert "Ignoring deferred PCR demographic tag not supported by user/chat context" in process_fn


def test_frontend_patient_name_header_capture_persists_scoring_evidence():
    source = open("static/js/app.js", encoding="utf-8").read()

    capture_fn = source[source.index("function _capturePcrHeaderFinding"):source.index("function _pcrFindingShouldRenderOnlyInHeader")]

    assert '_postFinding("history", "Patient Name", v, "ai_roleplay_tag");' in capture_fn
    assert capture_fn.index("state.pcrHeader.name = v;") < capture_fn.index('_postFinding("history", "Patient Name", v, "ai_roleplay_tag");')


def test_frontend_pcr_notes_sort_opqrst_and_sample_items_canonically():
    source = open("static/js/app.js", encoding="utf-8").read()

    rank_fn = source[
        source.index("function _pcrCanonicalMnemonicRank"):
        source.index("function _pcrCanonicalHistoryLabel")
    ]
    label_fn = source[
        source.index("function _pcrCanonicalHistoryLabel"):
        source.index("function _sortPcrMnemonicItems")
    ]
    sort_fn = source[
        source.index("function _sortPcrMnemonicItems"):
        source.index("function _removePcrHeaderOnlyRows")
    ]
    exam_fn = source[
        source.index("function addPcrExam"):
        source.index("// Always appends")
    ]
    raw_exam_fn = source[
        source.index("function addPcrExamRaw"):
        source.index("function addPcrHistory")
    ]
    history_fn = source[
        source.index("function addPcrHistory"):
        source.index("function addPcrTreatment")
    ]

    expected_order = [
        "onset", "provocation", "quality", "radiation", "severity", "time",
        "symptoms", "allerg", "med", "pmh", "last", "events",
    ]
    cursor = -1
    rank_lower = rank_fn.lower()
    for token in expected_order:
        next_pos = rank_lower.index(token, cursor + 1)
        assert next_pos > cursor
        cursor = next_pos

    assert "_pcrCanonicalMnemonicRank(aLabel)" in sort_fn
    assert "_pcrCanonicalMnemonicRank(bLabel)" in sort_fn
    assert 'container.appendChild(item)' in sort_fn
    assert '_sortPcrMnemonicItems("pcr-exam")' in exam_fn
    assert '_sortPcrMnemonicItems("pcr-exam")' in raw_exam_fn
    assert '_sortPcrMnemonicItems("pcr-history")' in history_fn
    assert '"Onset"' in label_fn
    assert '"Time"' in label_fn
    assert '"Signs and Symptoms"' in label_fn
    assert '"LOI"' in label_fn
    assert "seizure\\s+duration|seizure\\s+status" in label_fn
    assert "dataset.canonicalHistorySource" in history_fn
    assert 'return _postFinding("history", rawKey, value, source);' in history_fn


def test_frontend_timeline_formats_clocked_rows_as_mm_ss_and_prestart_as_done():
    source = open("static/js/app.js", encoding="utf-8").read()

    timeline_renderer = source[
        source.index("const _renderNormalEntry = entry =>"):
        source.index("timelineEl.innerHTML = _tlSegments.map")
    ]

    assert "function _formatTimelineClock" not in timeline_renderer
    assert 'return `${mm}:${ss}`;' in source
    assert "entry.pre_start" in timeline_renderer
    assert "not done" in timeline_renderer
    assert "${clock}</span>" in timeline_renderer
    assert "entry.elapsed_min}m" not in timeline_renderer
    assert 'isApplied    ? `<span class="text-green-500 w-12 shrink-0 italic">—</span>`' in timeline_renderer


def test_frontend_medical_control_summarizes_once_when_call_ends():
    source = open("static/js/app.js", encoding="utf-8").read()

    record_fn = source[
        source.index("function _recordMedicalControlTurn"):
        source.index("function appendMedicalControlSummaryInfo")
    ]
    summary_fn = source[
        source.index("function appendMedicalControlSummaryInfo"):
        source.index("function appendMedicalControlInfo")
    ]
    append_fn = source[
        source.index("function appendMedicalControlInfo"):
        source.index("function scrollChat")
    ]
    close_fn = source[
        source.index("function _mcClose"):
        source.index("function _mcUpdateTtsBtn")
    ]
    send_fn = source[
        source.index("async function _mcSend"):
        source.index('el("btn-med-control")')
    ]

    assert "summaryTurns" in source
    assert "_mc.summaryTurns.push" in record_fn
    assert "Medical Control Summary @" in summary_fn
    assert "appendAssessmentInfo" in summary_fn
    assert "appendAssessmentInfo" not in append_fn
    assert "appendMedicalControlSummaryInfo();" in close_fn
    assert "appendMedicalControlInfo(message, reply);" in send_fn


def test_frontend_notes_panel_keeps_scene_image_lightbox_only():
    source = open("static/js/app.js", encoding="utf-8").read()

    start_fn = source[
        source.index("function startSim"):
        source.index("  // Reset state")
    ]
    reset_fn = source[
        source.index("  // Reset patient photo"):
        source.index("  // Reset Lexi panel")
    ]

    assert "Keep the notes panel compact" in start_fn
    assert 'hide("scene-image-container");' in start_fn
    assert 'show("scene-image-container")' not in start_fn
    assert 'hide("scene-image-container");' in reset_fn


def test_frontend_manual_pulse_check_reports_quality_not_heart_rate():
    source = open("static/js/app.js", encoding="utf-8").read()

    defs_block = source[source.index("const _AUTHORED_VITAL_DEFS"):source.index("function _authoredVitalsBaseline")]
    request_fn = source[source.index("function _authoredVitalsRequestedDefs"):source.index("function _isLikelyAuthoredVitalsRequest")]

    assert '{ key: "pulse_quality"' in defs_block
    assert '{ key: "hr", label: "Heart Rate", type: "vital", patterns: [/\\bheart\\s+rate\\b/i, /\\bhr\\b/i] }' in defs_block
    assert 'def.key === "pulse_quality"' in request_fn
    assert 'def.key === "hr"' in request_fn
    assert '!/\\bpulse\\s*ox' in request_fn


def test_frontend_pain_questions_do_not_trigger_avpu_shortcut():
    source = open("static/js/app.js", encoding="utf-8").read()

    defs_block = source[source.index("const _AUTHORED_VITAL_DEFS"):source.index("function _authoredVitalsBaseline")]
    avpu_fn = source[source.index("function _userRequestedAvpu"):source.index("async function _recordAvpuAssessment")]

    assert '{ key: "pain"' in defs_block
    assert "painful stimuli?" in avpu_fn
    assert "respond(?:ing|s)? to (?:voice|verbal|pain)" in avpu_fn
    assert "|alert|verbal|pain|unresponsive|" not in avpu_fn


def test_frontend_suction_unit_quick_action_prompts_for_suction_confirmation():
    source = open("static/js/app.js", encoding="utf-8").read()

    assert 'let _suctionReadyConfirmationPending = false;' in source
    assert 'function _userPreparingSuctionOnly' in source
    assert 'function _userAsksPartnerToPrepareSuction' in source
    assert 'payload: "Alex, prepare suction."' in source
    assert 'Suction is ready. Do you want me to suction the airway?' in source
    assert 'applyInterventionAndRecord("suction_airway"' in source
    send_prefix = source[source.index("async function sendMessage"):source.index("const authoredVitalsDefs")]
    assert "_handleSuctionReadyConfirmation" in send_prefix
    assert "_handleSuctionReadyAction" in send_prefix
    confirmation_fn = source[source.index("async function _handleSuctionReadyConfirmation"):source.index("async function _recordAuthoredVitalsRequest")]
    assert 'if (!_isYesMessage(message) && !_isNoMessage(message)) return false;' in confirmation_fn


def test_frontend_self_assessment_actions_do_not_address_alex():
    source = open("static/js/app.js", encoding="utf-8").read()

    quick_actions = source[source.index("const _CHAT_QUICK_ACTIONS"):source.index("Object.entries(_CHAT_QUICK_ACTIONS)")]

    assert "I am assessing AVPU and level of consciousness." in quick_actions
    assert "I am assessing airway and breathing" in quick_actions
    assert "I am manually checking for a pulse and assessing pulse quality." in quick_actions
    assert "Alex, check AVPU" not in quick_actions
    assert "Alex, check breathing" not in quick_actions
    assert "Alex, manually check for a pulse" not in quick_actions


def test_frontend_lung_sound_challenge_is_user_exam_info_box_not_alex_voice():
    source = open("static/js/app.js", encoding="utf-8").read()

    lung_fn = source[source.index("function _openLungSoundChallengeFromChat"):source.index("function _scenarioSuggestsRespiratoryOrCardiacArrest")]

    assert "I am auscultating bilateral lung sounds." in source
    assert 'appendAssessmentInfo("Lung Sounds", "Listen to the recording and identify what you hear.")' in lung_fn
    assert "I'm auscultating lung sounds now" not in lung_fn


def test_all_enabled_lung_sound_challenges_have_correct_choice_id():
    """
    Contract: every enabled lung sound challenge with a finding must declare
    correct_choice_id so the choice modal pre-selects and validates deterministically.
    """
    violations = []
    for path in sorted(Path("app/scenarios").rglob("*.json")):
        with open(path, encoding="utf-8") as fh:
            scenario = json.load(fh)
        lsc = scenario.get("lung_sound_challenge")
        if not isinstance(lsc, dict) or not lsc.get("enabled"):
            continue
        if lsc.get("finding") and not lsc.get("correct_choice_id"):
            violations.append(f"{path.name}: missing correct_choice_id")
        pt = lsc.get("post_treatment")
        if isinstance(pt, dict) and pt.get("finding") and not pt.get("correct_choice_id"):
            violations.append(f"{path.name}: post_treatment missing correct_choice_id")
    assert not violations, (
        "These lung sound challenges are missing correct_choice_id:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_frontend_lexi_assisted_treatment_info_box_uses_bone_icon():
    source = open("static/js/app.js", encoding="utf-8").read()

    treatment_fn = source[source.index("function addPcrTreatment"):source.index("function _isUnscoredCprCompletedTreatmentLabel")]

    assert 'lexiAssisted ? "🦴" : _treatmentInfoIcon(interventionId, label)' in treatment_fn


def test_frontend_fto_guidance_card_blocks_inappropriate_interventions():
    source = open("static/js/app.js", encoding="utf-8").read()
    css = open("static/css/style.css", encoding="utf-8").read()

    assert "function _ftoGuidanceIconHtml" in source
    assert "function appendFtoGuidanceInfo" in source
    assert "orientation-cue-msg--fto" in css

    apply_fn = source[
        source.index("async function applyInterventionAndRecord"):
        source.index("function appendSuggestionChips")
    ]
    tag_fn = source[
        source.index("function processAiTags"):
        source.index("function _stripUnrequestedVitalLines")
    ]

    assert "_showFtoGuidanceForIntervention(interventionMeta, pcrLabel)" in apply_fn
    assert "_showFtoGuidanceForIntervention(iv, label)" in tag_fn
    assert "function _recordInappropriateInterventionAttempt" in source
    assert '"inappropriate_intervention_attempted"' in source
    assert '"clinical_decision"' in source
    assert "Do not perform:" in source


def test_frontend_current_events_orientation_questions_get_fto_guidance():
    source = open("static/js/app.js", encoding="utf-8").read()

    assert "function _volatileCurrentEventsOrientationQuestion" in source
    assert "function _handleVolatileCurrentEventsOrientationQuestion" in source
    assert "_handleVolatileCurrentEventsOrientationQuestion(message)" in source
    assert "appendFtoGuidanceInfo(" in source
    assert "Who is the president?" in source
    assert "person, place, time, and event" in source
    assert "upcoming-holiday prompts" in source


def test_frontend_inappropriate_cpr_attempt_gets_fto_guidance_before_ai_path():
    source = open("static/js/app.js", encoding="utf-8").read()

    assert "function _userAttemptsCpr" in source
    assert "function _handleInappropriateCprAction" in source
    assert "Do not start CPR. CPR is for a patient who is pulseless" in source
    assert "the patient is responsive, breathing, and has a pulse" in source
    assert 'attemptType: "cpr_not_indicated"' in source
    assert 'category: "clinical_performance"' in source
    assert "she is awake, breathing" not in source

    send_prefix = source[source.index("async function sendMessage"):source.index("const authoredVitalsDefs")]
    cpr_guard_pos = send_prefix.index("_handleInappropriateCprAction")
    recovery_pos = send_prefix.index("_handleRecoveryPositionAction")

    assert cpr_guard_pos < recovery_pos


def test_frontend_raw_action_fto_gate_blocks_inappropriate_interventions_before_ai_path():
    source = open("static/js/app.js", encoding="utf-8").read()

    assert "function _handleFtoBlockedInterventionAttempt" in source
    assert "findInterventionByLabel(message)" in source
    assert "function _unsupportedProcedureFtoGuidance" in source
    assert "function _ftoAttemptPenaltyCategory" in source
    assert "A traction splint is for an indicated femur/femoral shaft fracture" in source

    send_prefix = source[source.index("async function sendMessage"):source.index("const authoredVitalsDefs")]
    fto_gate_pos = send_prefix.index("_handleFtoBlockedInterventionAttempt")
    recovery_pos = send_prefix.index("_handleRecoveryPositionAction")

    assert fto_gate_pos < recovery_pos


def test_public_interventions_expose_fto_guidance_only_for_blocked_or_inappropriate_actions():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_croup_01.json").read_text(encoding="utf-8"))

    public = get_public_scenario_data(scenario)
    interventions = {iv["id"]: iv for iv in public["available_interventions"]}

    assert "not a BLS medication" in interventions["racepinephrine_svn"]["fto_guidance"]
    assert "upper airway obstruction" in interventions["albuterol_svn"]["fto_guidance"]
    assert "not indicated" in interventions["bvm"]["fto_guidance"]
    assert "maintaining her airway" in interventions["bvm"]["fto_guidance"]
    assert interventions["positioning"]["fto_guidance"] == ""


def test_indication_gate_populates_fto_guidance_from_structured_reason():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_asthma_01.json").read_text(encoding="utf-8"))

    public = get_public_scenario_data(scenario)
    interventions = {iv["id"]: iv for iv in public["available_interventions"]}

    bvm = interventions["bvm"]
    # FTO guidance comes from indication_gate.reason, not regex-parsed notes
    assert "not indicated" in bvm["fto_guidance"]
    assert "breathing adequately" in bvm["fto_guidance"]
    # indication_gate is passed through with allowed_when for future engine use
    assert bvm["indication_gate"] is not None
    assert bvm["indication_gate"]["status"] == "not_indicated_now"
    assert "apnea" in bvm["indication_gate"]["allowed_when"]
    assert "inadequate_ventilations" in bvm["indication_gate"]["allowed_when"]
    # Correctly indicated interventions have no gate
    assert interventions["albuterol_svn"]["fto_guidance"] == ""
    assert interventions["albuterol_svn"]["indication_gate"] is None


def test_indication_gate_reason_used_over_notes_regex():
    """indication_gate.reason takes priority over regex-detected notes text."""
    entry = {
        "notes": "General clinical description with no FTO trigger.",
        "indication_gate": {
            "status": "not_indicated_now",
            "reason": "Not appropriate until patient is apneic.",
            "allowed_when": ["apnea"],
        },
    }
    result = _public_intervention_fto_guidance(entry)
    assert result == "Not appropriate until patient is apneic."


def test_indication_gate_contraindicated_status_also_surfaces_reason():
    entry = {
        "indication_gate": {
            "status": "contraindicated",
            "reason": "Oral glucose is contraindicated — patient cannot protect airway.",
            "allowed_when": [],
        },
    }
    result = _public_intervention_fto_guidance(entry)
    assert "contraindicated" in result
    assert "airway" in result


def test_indication_gate_with_empty_reason_falls_back_to_notes_regex():
    entry = {
        "notes": "BVM is not yet indicated at this time.",
        "indication_gate": {
            "status": "not_indicated_now",
            "reason": "",
            "allowed_when": ["apnea"],
        },
    }
    result = _public_intervention_fto_guidance(entry)
    assert "not yet indicated" in result


def test_no_indication_gate_uses_notes_regex_fallback():
    entry = {"notes": "This intervention is not yet indicated right now."}
    result = _public_intervention_fto_guidance(entry)
    assert "not yet indicated" in result


def test_indication_gate_unknown_status_is_ignored():
    """An unrecognized status string does not accidentally expose FTO guidance."""
    entry = {
        "notes": "Routine monitoring notes without any FTO trigger.",
        "indication_gate": {
            "status": "deferred",
            "reason": "Some internal state note.",
            "allowed_when": [],
        },
    }
    result = _public_intervention_fto_guidance(entry)
    assert result == ""


def test_all_fto_triggering_interventions_have_indication_gate():
    """
    Contract: any intervention whose notes text would trigger the FTO regex must
    instead have a structured indication_gate field. This prevents new scenarios
    from encoding clinical indication logic in free-text notes.
    """
    import re as _re
    FTO_RE = _re.compile(
        r"(^|\.\s+)[^.]{0,120}\b(?:not indicated|not yet indicated|contraindicated|not recommended|premature)\b"
        r"|\bindicated for [^.;]+,\s*not\b",
        _re.IGNORECASE,
    )
    violations = []
    for path in sorted(Path("app/scenarios").rglob("*.json")):
        with open(path, encoding="utf-8") as fh:
            scenario = json.load(fh)
        ivs = scenario.get("vitals", {}).get("interventions", {})
        for iid, idata in ivs.items():
            if not isinstance(idata, dict):
                continue
            notes = str(idata.get("notes") or "").strip()
            has_gate = isinstance(idata.get("indication_gate"), dict)
            if notes and FTO_RE.search(notes) and not has_gate:
                violations.append(f"{path.name}:{iid}")
    assert not violations, (
        "These interventions use FTO-trigger language in notes but are missing indication_gate:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


_SAMPLE_COMPONENT_KEYS = frozenset({
    "onset", "provocation", "quality", "radiation", "severity", "time",
    "symptoms", "signs_symptoms", "chief_concern",
    "allergies", "medications", "pmh", "pmh_birth_immunizations",
    "last_oral_intake", "events", "associated_uri_fever",
    "diabetes_history", "cgm_reading",
})


def test_rich_history_response_maps_have_compound_sample_priority_entry():
    """
    Contract: any scenario with 5+ individual SAMPLE-component HRM entries must
    also have a compound priority entry so the resolver can pick it for broad requests.
    """
    violations = []
    for path in sorted(Path("app/scenarios").rglob("*.json")):
        with open(path, encoding="utf-8") as fh:
            scenario = json.load(fh)
        hrm = scenario.get("history_response_map")
        if not isinstance(hrm, dict):
            continue
        component_count = sum(
            1 for k in hrm if k in _SAMPLE_COMPONENT_KEYS
        )
        if component_count < 5:
            continue
        has_priority = any(
            isinstance(v, dict) and (
                v.get("priority") or
                str(v.get("notes") or "").lower().startswith("priority")
            )
            for v in hrm.values()
        )
        if not has_priority:
            violations.append(f"{path.name} ({component_count} SAMPLE-component entries)")
    assert not violations, (
        "These scenarios have rich SAMPLE history maps but no compound priority entry:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_frontend_recovery_position_action_has_deterministic_partner_response():
    source = open("static/js/app.js", encoding="utf-8").read()

    assert "function _userRequestsRecoveryPosition" in source
    assert "async function _handleRecoveryPositionAction" in source
    assert 'applyInterventionAndRecord("recovery_position"' in source
    assert "patient now in recovery position" in source
    recovery_fn = source[source.index("async function _handleRecoveryPositionAction"):source.index("async function _handleSuctionReadyAction")]
    assert "selfPerformed" in recovery_fn
    assert "return true;" in recovery_fn
    send_prefix = source[source.index("async function sendMessage"):source.index("const authoredVitalsDefs")]
    assert "_handleRecoveryPositionAction" in send_prefix


def test_febrile_seizure_suction_credit_requires_actual_suctioning_not_preparation():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_febrile_seizure_01.json").read_text(encoding="utf-8"))
    source = open("static/js/app.js", encoding="utf-8").read()

    suction_patterns = scenario["vitals"]["interventions"]["suction_airway"]["detection_patterns"]
    assert "\\bsuction\\b" not in suction_patterns

    critical_action = next(
        action for action in scenario["correct_treatment"]["critical_actions"]
        if action["id"] == "suction_airway"
    )
    checklist_item = next(
        item for item in scenario["checklist"]
        if item["id"] == "peds_febrile_seizure_01.suction_airway"
    )

    critical_patterns = "\n".join(critical_action["evidence"]["transcript_patterns"])
    checklist_patterns = "\n".join(checklist_item["tier2_patterns"])
    assert "(suction|" not in critical_patterns
    assert "(suction|" not in checklist_patterns
    suction_fn = source[source.index("function _userRequestsSuctionAirway"):source.index("function _userRequestsProtectFromInjury")]
    assert "patient|pt|child|infant|baby|chloe" in suction_fn
    assert "suction(?:ing|ed)?" in suction_fn


def test_febrile_seizure_age_question_does_not_reveal_name_or_dob():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_febrile_seizure_01.json").read_text(encoding="utf-8"))

    age_entry = scenario["history_response_map"]["patient_age"]
    age_payload = json.dumps(
        {"answer": age_entry.get("answer"), "tags": age_entry.get("tags")},
        ensure_ascii=False,
    ).lower()

    assert "chloe" not in age_payload
    assert "date of birth" not in age_payload
    assert "patient name" not in age_payload
    assert "patient date of birth" not in age_payload
    assert "[[history: patient age=" in age_payload


def test_febrile_seizure_opening_surfaces_do_not_reveal_airway_secretions():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_febrile_seizure_01.json").read_text(encoding="utf-8"))

    opening_payload = json.dumps(
        {
            "subtitle": scenario.get("subtitle"),
            "dispatch": scenario.get("dispatch", {}).get("text"),
            "scene": scenario.get("scene", {}).get("description"),
            "chief_complaint": scenario.get("patient", {}).get("chief_complaint"),
            "general_impression": scenario.get("patient", {}).get("general_impression"),
            "pat": scenario.get("patient", {}).get("pat"),
            "initial_complaint": scenario.get("initial_complaint", {}).get("lay_summary"),
            "chief_concern": scenario.get("history_response_map", {}).get("chief_concern", {}).get("answer"),
            "chat_placeholder": scenario.get("chat_placeholder"),
            "chat_address_hint": scenario.get("chat_address_hint"),
            "lexi_hints": scenario.get("lexi_hints"),
        },
        ensure_ascii=False,
    ).lower()

    assert "saliva" not in opening_payload
    assert "spit" not in opening_payload
    assert "gurgling" not in opening_payload
    assert "wet sounds" not in opening_payload
    assert "airway secretions" not in opening_payload

    airway_payload = json.dumps(scenario["patient"]["airway_assessment"], ensure_ascii=False).lower()
    assert "oral secretions" in airway_payload
    assert "gurgling" in airway_payload


def test_febrile_seizure_public_payload_exposes_authored_pat_and_airway_assessment():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_febrile_seizure_01.json").read_text(encoding="utf-8"))

    public = get_public_scenario_data(scenario)

    assert public["patient"]["pat"]["impression"] == scenario["patient"]["pat"]["impression"]
    assert public["patient"]["airway_assessment"]["status"] == "compromised"
    assert "gurgling" in public["patient"]["airway_assessment"]["description"].lower()


def test_public_history_response_map_includes_deterministic_dialogue_fields():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_febrile_seizure_01.json").read_text(encoding="utf-8"))

    public = get_public_scenario_data(scenario)
    entry = public["history_response_map"]["chief_concern"]

    assert entry["speaker"] == "Jennifer"
    assert entry["answer"] == "She's seizing. She started shaking and her eyes rolled up."
    assert "[[HISTORY: Patient Chief Complaint=active seizure]]" in entry["tags"]


def test_febrile_seizure_compound_history_questions_are_authored_complete_answers():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_febrile_seizure_01.json").read_text(encoding="utf-8"))
    response_map = scenario["history_response_map"]

    opqrst = response_map["opqrst_full"]
    assert "onset provocation quality radiation severity time" in opqrst["triggers"]
    assert any(tag.startswith("[[HISTORY: Onset=") for tag in opqrst["tags"])
    assert any(tag.startswith("[[HISTORY: Provocation=") for tag in opqrst["tags"])
    assert any(tag.startswith("[[HISTORY: Quality=") for tag in opqrst["tags"])
    assert any(tag.startswith("[[HISTORY: Radiation=") for tag in opqrst["tags"])
    assert any(tag.startswith("[[HISTORY: Severity=") for tag in opqrst["tags"])
    assert any(tag.startswith("[[HISTORY: Time=") for tag in opqrst["tags"])

    sample = response_map["sample_full"]
    assert "signs and symptoms allergies medications past medical history last oral intake events" in sample["triggers"]
    assert "signs and symptoms allergies medications past medical history intake events" in sample["triggers"]
    assert any(tag.startswith("[[HISTORY: Signs and Symptoms=") for tag in sample["tags"])
    assert any(tag.startswith("[[HISTORY: Allergies=") for tag in sample["tags"])
    assert any(tag.startswith("[[HISTORY: Medications=") for tag in sample["tags"])
    assert any(tag.startswith("[[HISTORY: PMH=") for tag in sample["tags"])
    assert any(tag.startswith("[[HISTORY: Last Oral Intake=") for tag in sample["tags"])
    assert any(tag.startswith("[[HISTORY: Events=") for tag in sample["tags"])

    last_oral = response_map["last_oral_intake"]
    assert "last oral" in last_oral["triggers"]
    assert "formula about an hour and a half ago" in last_oral["answer"]
    assert last_oral["tag"].startswith("[[HISTORY: Last Oral Intake=")

    demographics = response_map["patient_age_dob_weight"]
    demo_payload = json.dumps(demographics, ensure_ascii=False).lower()
    assert "patient name" not in demo_payload
    assert "chloe" not in demo_payload
    assert "[[history: patient age=" in demo_payload
    assert "[[history: patient date of birth=" in demo_payload
    assert "[[history: patient weight=" in demo_payload

    demographics_with_weight = response_map["patient_identity_full_with_weight"]
    demo_weight_payload = json.dumps(demographics_with_weight, ensure_ascii=False).lower()
    assert "name age date of birth and weight" in demographics_with_weight["triggers"]
    assert "chloe" in demo_weight_payload
    assert "[[history: patient name=" in demo_weight_payload
    assert "[[history: patient age=" in demo_weight_payload
    assert "[[history: patient date of birth=" in demo_weight_payload
    assert "[[history: patient weight=" in demo_weight_payload


def test_croup_allergies_medications_pair_records_both_sample_fields():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_croup_01.json").read_text(encoding="utf-8"))
    entry = scenario["history_response_map"]["allergies_medications"]

    assert "allergies and medications" in entry["triggers"]
    assert any(tag.startswith("[[HISTORY: Allergies=") for tag in entry["tags"])
    assert any(tag.startswith("[[HISTORY: Medications=") for tag in entry["tags"])


def test_frontend_patient_name_history_map_requires_patient_name_context():
    source = open("static/js/app.js", encoding="utf-8").read()

    tag_guard = source[source.index("function _historyMapTagAllowedForContext"):source.index("function _applyScenarioHistoryResponseMapTags")]
    assert "function _messageRequestsPatientName" in tag_guard
    assert "state.scenarioData?.patient?.name" in tag_guard
    assert "_messageRequestsPatientName(message) || Boolean(expected && response.includes(expected))" in tag_guard
    assert "_historyMapEntryAllowedForContext(entry, message)" in source


def test_diabetic_chief_concern_can_volunteer_patient_name_when_authored():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json").read_text(encoding="utf-8"))
    chief = scenario["history_response_map"]["chief_concern"]

    assert "Marcus seems confused" in chief["answer"]
    assert "[[HISTORY: Patient Name=Marcus]]" in chief["tags"]
    assert "[[HISTORY: Patient Chief Complaint=acting strange and confused]]" in chief["tags"]


def test_head_injury_name_question_does_not_reveal_age_or_dob():
    scenario = json.loads((PROJECT_ROOT / "app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json").read_text(encoding="utf-8"))

    entry = scenario["history_response_map"]["patient_name"]
    payload = json.dumps({"answer": entry["answer"], "tags": entry["tags"]}, ensure_ascii=False).lower()

    assert "marcus" in payload
    assert "8 years old" not in payload
    assert "8-year-old" not in payload
    assert "birthday" not in payload
    assert "date of birth" not in payload
    assert "may 13" not in payload

    resolved = _resolve_history_response_entry("what's his name?", scenario, preferred_addressee="family")
    assert resolved is not None
    key, narrowed = resolved
    assert key == "patient_name"
    assert narrowed["answer"] == "His name is Marcus."
    assert narrowed["tags"] == ["[[HISTORY: Patient Name=Marcus]]"]


def test_head_injury_full_demographics_requires_explicit_bundled_request():
    scenario = json.loads((PROJECT_ROOT / "app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json").read_text(encoding="utf-8"))

    resolved = _resolve_history_response_entry("can I get his name age and date of birth?", scenario, preferred_addressee="family")
    assert resolved is not None
    key, entry = resolved

    assert key == "patient_identity_full"
    assert "Marcus" in entry["answer"]
    assert "8 years old" in entry["answer"]
    assert "May 13" in entry["answer"]
    assert "[[HISTORY: Patient Name=Marcus]]" in entry["tags"]
    assert "[[HISTORY: Patient Age=8-year-old male]]" in entry["tags"]
    assert "[[HISTORY: Patient Date of Birth=May 13]]" in entry["tags"]


def test_frontend_history_response_map_prefers_complete_sample_entry():
    source = open("static/js/app.js", encoding="utf-8").read()
    entry_lookup = source[source.index("function _historyMapEntryMatchScore"):source.index("function _applyHistoryResponseEntryTags")]
    trigger_lookup = source[source.index("function _historyMapTriggerMatches"):source.index("function _historyMapMessageRequestsCompoundSample")]
    scenario_entry_lookup = source[source.index("function _scenarioHistoryResponseMapEntry"):source.index("function _applyHistoryResponseEntryTags")]

    assert "function _historyMapMessageRequestsCompoundSample" in source
    assert "function _bareHowMechanismHistoryEntry" in source
    assert "function _historyMapOrderedTokenMatch" in trigger_lookup
    assert "msgPhrase.includes(trigPhrase)" in trigger_lookup
    assert "trigPhrase.includes(msgPhrase)" in trigger_lookup
    assert "messageTokens.length < 2 && msg !== trig" in trigger_lookup
    assert "msg.includes(trig)" not in trigger_lookup
    assert "trig.includes(msg)" not in trigger_lookup
    assert "if (isCompleteSampleEntry && !_historyMapMessageRequestsCompoundSample(message)) return null;" in entry_lookup
    assert "priorityBonus" in entry_lookup
    assert "completeSampleBonus" in entry_lookup
    assert "Signs and Symptoms" in entry_lookup
    assert "_bareHowMechanismHistoryEntry(responseMap, message)" in scenario_entry_lookup
    assert "Last Oral Intake" in entry_lookup
    assert "Events" in entry_lookup
    assert "candidates.sort" in entry_lookup


def test_frontend_dialogue_parser_does_not_treat_sample_labels_as_speakers():
    source = open("static/js/app.js", encoding="utf-8").read()
    parser = source[source.index("function _parseLeadingSpeakerLine"):source.index("function _parseAiDialogueChunks")]

    assert "function _looksLikeHistorySectionLabel" in parser
    assert "if (_looksLikeHistorySectionLabel(fallbackMatch[1])) return null;" in parser
    assert "signs(?: and symptoms)?" in parser
    assert "last oral intake" in parser
    assert "events(?: leading up)?" in parser


def test_croup_compound_sample_answer_is_caregiver_speech_not_form_labels():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_croup_01.json").read_text(encoding="utf-8"))
    sample = scenario["history_response_map"]["sample_full"]

    assert sample.get("priority") is True
    assert "signs and symptoms allergies medications past medical history last oral intake events" in sample["triggers"]
    assert not sample["answer"].startswith("Signs and symptoms:")
    assert "She has no known allergies" in sample["answer"]
    assert any(tag.startswith("[[HISTORY: Signs and Symptoms=") for tag in sample["tags"])
    assert any(tag.startswith("[[HISTORY: Last Oral Intake=") for tag in sample["tags"])
    assert any(tag.startswith("[[HISTORY: Events=") for tag in sample["tags"])


def test_febrile_seizure_sample_trigger_covers_spoken_and_events_phrase():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_febrile_seizure_01.json").read_text(encoding="utf-8"))
    sample = scenario["history_response_map"]["sample_full"]

    assert "signs and symptoms allergies medications past medical history last oral intake and events leading up to" in sample["triggers"]
    assert any(tag.startswith("[[HISTORY: Signs and Symptoms=") for tag in sample["tags"])
    assert any(tag.startswith("[[HISTORY: Last Oral Intake=") for tag in sample["tags"])
    assert any(tag.startswith("[[HISTORY: Events=") for tag in sample["tags"])


def test_frontend_protect_from_injury_accepts_prevent_and_safe_phrasing():
    source = open("static/js/app.js", encoding="utf-8").read()
    protect_helper = source[source.index("function _userRequestsProtectFromInjury"):source.index("function _userRequestsRecoveryPosition")]

    assert "prevent" in protect_helper
    assert "safe" in protect_helper
    assert "from" in protect_helper


def test_professionalism_counts_peds_intro_and_airway_safety_explanation():
    transcript = (
        "hi my name is John with the fire department what's going on\n"
        "okay just keep her on her side protect her from injury and protect her Airway"
    )

    ceiling, reasons = _compute_professionalism_hardened_constraints(
        student_transcript=transcript,
        greeting_detected=True,
        prof_ceiling=10,
        is_peds=True,
    )
    floor = _professionalism_floor_for_transcript(
        text=transcript.lower(),
        greeting_detected=True,
        agency_intro_detected=True,
        is_peds=True,
        ceiling=ceiling,
    )

    assert "no agency or responder-role introduction detected" not in reasons
    assert "no explanation of actions or care plan detected" not in reasons
    assert "no direct caregiver acknowledgment or address detected" not in reasons
    assert ceiling >= 9
    assert floor >= 7


def test_professionalism_gives_partial_floor_for_intro_without_agency():
    transcript = (
        "hi my name is John what's going on\n"
        "okay keep her on her side protect her Airway and prevent injuries"
    )

    ceiling, reasons = _compute_professionalism_hardened_constraints(
        student_transcript=transcript,
        greeting_detected=True,
        prof_ceiling=10,
        is_peds=True,
    )
    floor = _professionalism_floor_for_transcript(
        text=transcript.lower(),
        greeting_detected=True,
        agency_intro_detected=False,
        is_peds=True,
        ceiling=ceiling,
    )

    assert "no greeting or self-introduction detected" not in reasons
    assert "no explanation of actions or care plan detected" not in reasons
    assert "no direct caregiver acknowledgment or address detected" not in reasons
    assert "no agency or responder-role introduction detected" in reasons
    assert ceiling >= 8
    assert floor >= 6


def test_frontend_blood_glucose_treatment_is_reported_with_vitals_not_info_card():
    source = open("static/js/app.js", encoding="utf-8").read()

    treatment_fn = source[source.index("function addPcrTreatment"):source.index("function _isUnscoredCprCompletedTreatmentLabel")]
    helper_fn = source[source.index("function _treatmentIsReportedAsVital"):source.index("function _treatmentInfoTitle")]

    assert "if (!_treatmentIsReportedAsVital(interventionId, label))" in treatment_fn
    assert "blood_glucose_check" in helper_fn
    assert "glucometer" in helper_fn


def test_frontend_debrief_uses_server_reference_markdown_for_learn_more():
    source = open("static/js/app.js", encoding="utf-8").read()
    show_fn = source[source.index("function showDebrief"):source.index("// ── Layer 2: Key Takeaways")]
    process_fn = source[source.index("async function processDebrief"):source.index("function showDebrief")]

    assert "referenceMarkdown: data.reference_markdown || \"\"" in source
    assert "referenceMarkdown:    blufData?.referenceMarkdown" in process_fn
    assert "let refMarkdown = debriefSections.referenceMarkdown || blufData?.referenceMarkdown || \"\";" in show_fn


def test_frontend_debrief_strips_generated_takeaways_and_reflection_from_main_prose():
    source = open("static/js/app.js", encoding="utf-8").read()
    split_fn = source[source.index("function _splitDebriefForModal"):source.index("function _demoteCaseLearningSubsectionNumbers")]

    assert "function _stripGeneratedDebriefAuxiliarySections" in source
    assert "_stripGeneratedDebriefAuxiliarySections(_normalizeDebriefText(input))" in split_fn
    assert "Key\\s+Takeaways|Reflection\\s+Prompts" in source
    assert "Case\\\\s+Study" in source


def test_frontend_debrief_normalizes_inline_missed_item_lists():
    source = open("static/js/app.js", encoding="utf-8").read()
    normalize_fn = source[source.index("function _normalizeDebriefText"):source.index("function _normalizeDebriefSectionHeadersForDisplay")]
    inline_fn = source[source.index("function _normalizeDebriefInlineListsForDisplay"):source.index("function _splitDebriefForModal")]

    assert "_normalizeDebriefInlineListsForDisplay" in normalize_fn
    assert "What Went Well|What Could Be Better" in inline_fn
    assert "looksLikeGap(part)" in inline_fn
    assert "## What Could Be Better" in inline_fn
    assert "out.push(`- ${part}`);" in inline_fn


def test_professionalism_prompt_uses_nasemso_affective_domain_attributes():
    source = open("app/ai_client.py", encoding="utf-8").read()
    prof_fn = source[source.index("async def _run_professionalism_review"):source.index("def _build_evidence_packet")]
    anchor_fn = source[source.index("def _professionalism_rubric_anchor_block"):source.index("def _build_vital_constraint_block")]
    guidance = _PROFESSIONALISM_AFFECTIVE_DOMAIN_GUIDANCE

    for phrase in [
        "Empathy",
        "Communications",
        "Teamwork and Diplomacy",
        "Respect",
        "Patient Advocacy",
        "Self-Confidence",
        "Integrity/documentation accuracy belongs to narrative/CHART",
        "Careful Delivery of Service belongs to protocols_treatment and scope_adherence",
        "single affective data point",
    ]:
        assert phrase in guidance
    assert "_PROFESSIONALISM_AFFECTIVE_DOMAIN_GUIDANCE" in prof_fn
    assert "professionalism_rubric" in prof_fn
    assert "_professionalism_rubric_anchor_block(professionalism_rubric)" in prof_fn
    assert "SCENARIO-SPECIFIC PROFESSIONALISM ANCHORS" in anchor_fn
    assert "Full-credit behaviors" in anchor_fn
    assert "using the six affective attributes above" in prof_fn
    assert "Do NOT adjust for documentation accuracy" in prof_fn


def test_professionalism_framework_keeps_integrity_out_of_professionalism_bucket():
    framework = Path("docs/PROFESSIONALISM_FRAMEWORK.md").read_text(encoding="utf-8")

    assert "| Integrity | Partially — documentation accuracy, no fabricated findings | Narrative / CHART |" in framework
    assert "Do not re-score it under professionalism" in framework
    assert "Careful Delivery of Service" in framework
    assert "Do not re-score it under professionalism" in framework


def test_frontend_deferred_sim_header_uses_generic_context_not_authored_title():
    source = open("static/js/app.js", encoding="utf-8").read()

    header_branch = source[source.index("function _scenarioHeaderTitle"):source.index("function _deferredPatientInfoParts")]

    assert "if (!_pcrDemographicsDeferred()) return s.display_title || s.title" in header_branch
    assert "return \"Pediatric Trauma\"" in header_branch
    assert "return \"Pediatric Medical\"" in header_branch
    assert "setText(\"sim-title\", _scenarioHeaderTitle())" in source


def test_pat_gateway_round_timer_is_one_minute():
    source = open("static/js/app.js", encoding="utf-8").read()

    assert "const PAT_GAME_DURATION_SEC = 60;" in source


def test_category_start_and_retake_clear_previous_session_state():
    source = open("static/js/app.js", encoding="utf-8").read()
    start_block = source[source.index("// Wire start buttons"):source.index("// Wire debrief buttons")]

    assert "btn-cat-start" in start_block
    assert "resetSessionState();" in start_block
    assert "startScenario(btn.dataset.scenario)" in start_block


def test_debrief_uses_critical_miss_language_not_fail_language():
    source = open("static/js/app.js", encoding="utf-8").read()
    start = source.index("function showDebrief")
    end = source.index("function showBadgeToast", start)
    debrief_block = source[start:end]

    assert "Critical Misses" in debrief_block
    assert "Critical Failure" not in debrief_block
    assert "FAIL" not in debrief_block
    assert "station-fail" not in debrief_block
    assert "does not change assessment status" in debrief_block


def test_manual_cspine_chat_command_uses_manual_stabilization_not_collar():
    source = open("static/js/app.js", encoding="utf-8").read()

    assert "function _manualCspineCommandRequested" in source
    assert "function _cspineExamRequested" in source
    assert "function _handleCspineExamAction" in source
    assert "if (_cspineExamRequested(itemText)) return null;" in source
    assert "if (_cspineExamRequested(msg)) return false;" in source
    assert "Spinal Motion Restriction — manual in-line stabilization" in source
    assert "holding manual in-line cervical stabilization now" in source
    response_line = 'const display = "*Alex:* Copy — holding manual in-line cervical stabilization now.";'
    assert response_line in source
    cspine_exam_pos = source.index("await _handleCspineExamAction(message, chipId, isAction)")
    manual_pos = source.index("await _handleManualCspineCommand(message, chipId, isAction)")
    assert cspine_exam_pos < manual_pos


def test_head_injury_smr_patterns_do_not_match_cspine_exam_only():
    scenario = json.loads((PROJECT_ROOT / "app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json").read_text(encoding="utf-8"))
    patterns = scenario["vitals"]["interventions"]["smr"]["detection_patterns"]
    joined = "\n".join(patterns).lower()

    assert "\nspinal\n" not in f"\n{joined}\n"
    assert "\ncervical\n" not in f"\n{joined}\n"
    assert "\nc-spine\n" not in f"\n{joined}\n"
    assert "spinal motion restriction" in patterns
    assert "cervical spine precautions?" in patterns


def test_pcr_treatment_rows_dedupe_by_intervention_id():
    source = open("static/js/app.js", encoding="utf-8").read()

    assert "detectedTreatmentIds: []" in source
    assert "function addPcrTreatment(label, interventionId = null)" in source
    assert "state.detectedTreatmentIds.includes(interventionId)" in source
    assert "item.dataset.interventionId = interventionId" in source
    assert "addPcrTreatment(pcrLabel, interventionId)" in source
    assert "addPcrTreatment(iv.label, ivId)" in source


def test_action_menu_procedure_buttons_record_matching_interventions_before_chat():
    source = open("static/js/app.js", encoding="utf-8").read()

    candidate_fn = source[
        source.index("function _actionMenuInterventionCandidate"):
        source.index("async function _handleActionMenuInterventionItem")
    ]
    handler_fn = source[
        source.index("async function _handleActionMenuInterventionItem"):
        source.index("// O2 device")
    ]
    main_action_block = source[
        source.index("function _renderActionModal"):
        source.index("function _inventoryHasAny")
    ]
    body_map_block = source[
        source.index("function makeItemBtn"):
        source.index("function getPatientSilhouetteType")
    ]

    assert 'fallbackIds.push("dry_dressing", "direct_pressure")' in candidate_fn
    assert 'if (/\\bprimary\\s+survey\\b/i.test(itemText)) return null;' in candidate_fn
    assert "findInterventionByLabel(String(text))" in candidate_fn
    assert "applyInterventionAndRecord(intervention.id" in handler_fn
    assert 'await _handleActionMenuInterventionItem(item, "action_menu")' in main_action_block
    assert 'await _handleActionMenuInterventionItem(item, "body-map-procedure")' in body_map_block


def test_primary_survey_action_does_not_say_addressing_or_match_dressing_substring():
    source = open("static/js/app.js", encoding="utf-8").read()
    scenario_text = open("app/scenarios/pediatric/trauma/peds_trauma_01_soft_tissue.json", encoding="utf-8").read()
    scenario = json.loads(scenario_text)

    assert "I am performing a primary survey and checking for immediate life threats." in source
    assert "I am performing a primary survey and addressing immediate life threats." not in source

    direct_pressure = scenario["vitals"]["interventions"]["direct_pressure"]
    patterns = "\n".join(direct_pressure["detection_patterns"])
    assert "\ndressing\n" not in f"\n{patterns}\n"
    assert "\\bdress(?:ing)?\\b" in patterns
    assert '"(?i)(direct\\\\s+(?:manual\\\\s+)?pressure|pressure\\\\s+(?:dressing|bandage)|\\\\bdress(?:ing)?\\\\b' in scenario_text


def test_body_map_pupil_exam_persists_scoring_finding_and_head_menu_omits_gcs():
    source = open("static/js/app.js", encoding="utf-8").read()
    head_menu = source[
        source.index('"head": { label: "Head", items: ['):
        source.index('], procedures: [', source.index('"head": { label: "Head", items: ['))
    ]
    standard_exam_matcher = source[
        source.index("function _messageLooksLikeStandardExam"):
        source.index("function _standardExamAliasScore")
    ]
    authored_exam_handler = source[
        source.index("async function _handleAuthoredStandardExamAction"):
        source.index("function _historyResponseMapSpeaker")
    ]
    authored_vitals_request = source[
        source.index("async function _recordAuthoredVitalsRequest"):
        source.index("function _cprAdditionalActionFindingSpec")
    ]
    intervention_exam_helper = source[
        source.index("async function _recordStructuredExamFindingsForIntervention"):
        source.index("function appendSuggestionChips")
    ]

    assert 'label: "Pupils"' in head_menu
    assert "I am assessing pupils for size, equality, and reactivity to light." in head_menu
    assert 'label: "GCS"' not in head_menu
    assert "pupils?" in standard_exam_matcher
    assert 'await addPcrExam(key, value, "student_stated_exam");' in authored_exam_handler
    assert '"authored_standard_exam"' not in authored_exam_handler
    assert 'addPcrExam(formatted.label, formatted.value, "partner_reported_exam")' in authored_vitals_request
    assert 'id === "neuro_assessment"' in intervention_exam_helper
    assert 'recordExam("Pupils", pupilsText)' in intervention_exam_helper
    assert 'flushVitalsBlock({ GCS: "gcs_modal", default: "gcs_modal" })' in intervention_exam_helper
    assert 'addPcrHistory("LOC", eventsText, "ai_roleplay_tag")' in intervention_exam_helper
    assert 'id === "dcap_btls_head_neck"' in intervention_exam_helper
    assert 'recordExam("DCAP-BTLS Head"' in intervention_exam_helper
    assert "appendExamFindingInfo(key, value)" in source


def test_standard_exam_actions_have_normal_fallback_findings_for_unmapped_regions():
    source = open("static/js/app.js", encoding="utf-8").read()
    standard_exam_matcher = source[
        source.index("function _messageLooksLikeStandardExam"):
        source.index("function _standardExamAliasScore")
    ]
    fallback_handler = source[
        source.index("function _defaultStandardExamFindingForMessage"):
        source.index("function _messageLooksLikeCmsAssessment")
    ]
    authored_exam_handler = source[
        source.index("async function _handleAuthoredStandardExamAction"):
        source.index("function _historyResponseMapSpeaker")
    ]

    assert "face|chest|thorax" in standard_exam_matcher
    assert "DCAP-BTLS Head" in fallback_handler
    assert "Facial / Mouth / Nose Assessment" in fallback_handler
    assert "Jugular Veins / JVD" in fallback_handler
    assert "Tracheal Position" in fallback_handler
    assert "Neck / Cervical Spine Assessment" in fallback_handler
    assert "no facial droop, asymmetry, deformity, tenderness, swelling, or visible injury noted" in fallback_handler
    assert "Chest Assessment" in fallback_handler
    assert "no chest wall deformity, tenderness, crepitus, instability, or visible trauma noted" in fallback_handler
    assert "_defaultStandardExamFindingForMessage(message)" in authored_exam_handler
    assert 'appendExamFindingInfo(key, value)' in authored_exam_handler


def test_head_injury_exemplar_uses_high_flow_nrb_not_nasal_cannula():
    with open("app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    exemplar_text = f"{scenario.get('exemplar_dmist', '')}\n{scenario.get('exemplar_narrative', '')}".lower()

    assert "high-flow o2 via nrb" in exemplar_text
    assert "nasal cannula" not in exemplar_text


def test_scene_chat_does_not_surface_system_recommendations_or_suggestion_chips():
    source = open("static/js/app.js", encoding="utf-8").read()
    main_source = open("app/main.py", encoding="utf-8").read()

    assert "parsed.suggestions" not in source
    assert "appendSuggestionChips(_pendingSuggestions" not in source
    assert "O2 first — you're thinking like an EMT" not in source
    assert "Don't forget to assess vitals" not in source
    assert "Looking thorough!" not in source
    assert "ALS is here! Turnover patient care" not in source
    assert "Give your DMIST report" not in source
    assert "'suggestions':" not in main_source
    assert "_detect_intervention_suggestions(" not in main_source


def test_frontend_scene_name_reveal_handles_who_are_you_and_titled_names():
    source = open("static/js/app.js", encoding="utf-8").read()

    assert "function _messageRequestsAnySceneName" in source
    assert "who\\s+(?:are|r)\\s+(?:you|u)" in source
    assert "function _sceneNameRegex" in source
    assert 'parts.join("\\\\s+")' in source
    assert "_sceneNameRegex(candidate.name)" in source
    assert 'candidate.role === "patient" && _pcrDemographicsDeferred()' in source
    assert "state.pcrHeader.name = candidate.name" in source


def test_partner_prompt_forbids_recommending_actions():
    source = open("app/ai_client.py", encoding="utf-8").read()

    assert "The partner NEVER recommends next actions" in source
    assert "ask ONE clarifying question about the delivery method rather than choosing one independently" in source


def test_design_docs_forbid_scene_time_recommendations_and_oxygen_defaulting():
    scenario_design = Path("docs/SCENARIO_DESIGN_EMS.md").read_text(encoding="utf-8")
    ai_architecture = Path("docs/AI_ARCHITECTURE.md").read_text(encoding="utf-8")
    combined = f"{scenario_design}\n{ai_architecture}"

    assert "must never volunteer or recommend interventions" in scenario_design
    assert "Runtime scene chat, actors, Alex, and scene UI must not surface" in scenario_design
    assert "Do not author broad treatment phrases as device-specific detection patterns" in scenario_design
    assert "No live coaching or recommendations" in ai_architecture
    assert "asks one clarifying question" in ai_architecture

    assert "DEFAULT OXYGEN RULE" not in combined
    assert "clinically appropriate default" not in combined
    assert "default oxygen method" not in combined


def test_frontend_silent_refresh_is_single_flight():
    source = open("static/js/app.js", encoding="utf-8").read()

    assert "let _silentRefreshPromise = null" in source
    assert "if (_silentRefreshPromise) return _silentRefreshPromise" in source
    assert "_silentRefreshPromise = (async () =>" in source
    assert "_silentRefreshPromise = null" in source


def test_frontend_auth_fetch_repairs_active_agency_context_403_once():
    source = open("static/js/app.js", encoding="utf-8").read()
    auth_block = source[source.index("async function authFetch"):source.index("// ── Base JWT")]
    restore_block = source[source.index("async function _restoreActiveAgencyContext"):source.index("async function authFetch")]

    assert "function _responseNeedsActiveAgencyContext" in source
    assert "active agency context required" in source.lower()
    assert 'res.status === 403 && _retry && !String(url || "").includes("/api/token/switch")' in auth_block
    assert "_responseNeedsActiveAgencyContext(res, detail)" in auth_block
    assert "return authFetch(url, options, false)" in auth_block
    assert "JSON.stringify({ agency_id: state.agency_id })" in restore_block


def test_croup_history_questions_route_to_caregiver_not_partner_or_nonverbal_patient():
    with open("app/scenarios/pediatric/medical/peds_croup_01.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    family_questions = [
        "and how severe is it",
        "has it been constant",
        "any other signs or symptoms",
        "last time she had anything to eat or drink",
    ]

    for question in family_questions:
        assert _infer_scene_addressee(question, scenario) == "family"


def test_partner_role_alias_is_routed_as_ems_partner():
    scenario = {
        "personas": {
            "alex": {
                "name": "Alex",
                "role": "partner",
                "aliases": ["Alex"],
                "description": "EMS partner",
                "speaking_style": "Concise.",
            },
            "sarah": {
                "name": "Sarah",
                "role": "family",
                "aliases": ["Sarah"],
                "relation": "mother",
            },
        }
    }

    assert _infer_scene_addressee("Alex, please check lung sounds", scenario) == "ems_partner"
    assert _infer_scene_addressee("let's get a set of vitals", scenario) == "ems_partner"


def test_short_followup_inherits_last_valid_caregiver_speaker():
    with open("app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    assert _infer_scene_addressee("confused how", scenario) is None
    assert _infer_scene_followup_addressee(
        "confused how",
        scenario,
        last_scene_speaker="Diane",
    ) == "family"
    assert _infer_scene_followup_addressee(
        "what's he acting like",
        scenario,
        last_scene_speaker="Diane",
    ) == "family"


def test_ambiguous_name_followup_inherits_last_valid_bystander_speaker():
    with open("app/scenarios/pediatric/medical/peds_anaphylaxis_01.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    assert _infer_scene_followup_addressee(
        "your name",
        scenario,
        last_scene_speaker="Ms. Hernandez",
    ) == "bystander"
    assert _infer_scene_followup_addressee(
        "what's your name",
        scenario,
        last_scene_speaker="Ms. Hernandez",
    ) == "bystander"
    assert _infer_scene_followup_addressee(
        "Jayden, what's your name?",
        scenario,
        last_scene_speaker="Ms. Hernandez",
    ) is None
    assert _infer_scene_addressee("Jayden, what's your name?", scenario) == "patient"


def test_caregiver_followup_routing_blocks_exam_tags_without_assessment_action():
    directive = _build_scene_routing_directive("what's he acting like", "family")

    assert "reply as family" in directive
    assert "not an EMS physical exam" in directive
    assert "Do NOT emit [[EXAM]], [[VITAL]], or [[ACTION]] tags" in directive
    assert "Level of Consciousness" in directive
    assert _message_looks_like_explicit_assessment_action("what's he acting like") is False
    assert _message_looks_like_explicit_assessment_action("confused how") is False


def test_explicit_assessment_action_can_still_emit_exam_tags():
    directive = _build_scene_routing_directive(
        "I am assessing AVPU and level of consciousness.",
        "family",
    )

    assert _message_looks_like_explicit_assessment_action(
        "I am assessing AVPU and level of consciousness."
    ) is True
    assert "Do NOT emit [[EXAM]]" not in directive


def test_short_followup_does_not_override_partner_tasks():
    with open("app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    assert _infer_scene_followup_addressee(
        "check blood glucose",
        scenario,
        last_scene_speaker="Diane",
    ) is None
    assert _infer_scene_addressee("check blood glucose", scenario) == "ems_partner"


def test_followup_speaker_hint_is_validated_against_scenario_personas():
    with open("app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    assert _infer_scene_followup_addressee(
        "confused how",
        scenario,
        last_scene_speaker="Someone Else",
    ) is None


def test_responsive_patient_second_person_questions_route_to_patient():
    with open("app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    patient_questions = [
        "where does it hurt?",
        "do you have any pain?",
        "what's your name?",
        "do you know where you are and what day it is?",
        "do you remember what happened?",
        "can you remember what happened?",
        "do you feel dizzy or lightheaded or nauseous?",
        "are you dizzy?",
    ]

    for question in patient_questions:
        assert _infer_scene_addressee(question, scenario) == "patient"

    assert _resolve_history_response_entry(
        "do you remember what happened?",
        scenario,
        preferred_addressee="patient",
    )[0] == "patient_memory"
    assert _resolve_history_response_entry(
        "do you feel dizzy or lightheaded or nauseous?",
        scenario,
        preferred_addressee="patient",
    )[0] == "patient_symptoms"


def test_patient_followup_after_marcus_speaks_resolves_to_marcus_memory():
    with open("app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    assert _infer_scene_followup_addressee(
        "can you tell me what happened",
        scenario,
        last_scene_speaker="Marcus",
    ) == "patient"
    assert _resolve_history_response_entry(
        "can you tell me what happened",
        scenario,
        preferred_addressee="patient",
    )[0] == "patient_memory"


def test_pediatric_intro_event_openers_prefer_caregiver_first():
    with open("app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    caregiver_openers = [
        "hi im jon what happened",
        "hi im jon, what's going on tonight?",
        "hi, what's going on?",
        "can you tell me what happened?",
        "why did you call?",
        "when did it start?",
        "ever happen before?",
    ]

    for opener in caregiver_openers:
        assert _infer_scene_addressee(opener, scenario) == "family"


def test_direct_named_child_opener_routes_to_communicative_patient_not_caregiver_map():
    with open("app/scenarios/pediatric/trauma/peds_trauma_01_soft_tissue.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    message = "hi Leo, can you tell me what happened?"

    assert _infer_scene_addressee(message, scenario) == "patient"
    assert _resolve_history_response_entry(
        message,
        scenario,
        preferred_addressee="patient",
    ) is None


def test_soft_tissue_mechanism_and_loc_history_map_emit_structured_tags():
    with open("app/scenarios/pediatric/trauma/peds_trauma_01_soft_tissue.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    mechanism = _resolve_history_response_entry(
        "how did he trip and what did he hit",
        scenario,
        preferred_addressee="family",
    )
    loc = _resolve_history_response_entry(
        "did he lose concioucness",
        scenario,
        preferred_addressee="family",
    )

    assert mechanism is not None
    assert mechanism[0] == "mechanism_details"
    assert "[[HISTORY: Events=" in json.dumps(mechanism[1])
    assert loc is not None
    assert loc[0] == "loc_status"
    assert "[[HISTORY: LOC=" in json.dumps(loc[1])


def test_short_how_followup_in_trauma_routes_to_mechanism_not_weight():
    with open("app/scenarios/pediatric/trauma/peds_trauma_01_soft_tissue.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    mechanism = _resolve_history_response_entry(
        "how",
        scenario,
        preferred_addressee="family",
    )
    greeting = _resolve_history_response_entry(
        "how are you",
        scenario,
        preferred_addressee="patient",
    )

    assert mechanism is not None
    assert mechanism[0] == "mechanism_details"
    assert "coffee table" in mechanism[1]["answer"]
    assert greeting is None


def test_soft_tissue_bare_how_after_broad_opener_stays_on_mechanism():
    with open("app/scenarios/pediatric/trauma/peds_trauma_01_soft_tissue.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    messages = [
        {"role": "user", "content": "hi im jon what happened"},
        {"role": "assistant", "content": "(father)\nHe fell and cut his head."},
    ]
    addressee = _infer_scene_followup_addressee(
        "how",
        scenario,
        messages=messages,
    )
    mechanism = _resolve_history_response_entry(
        "how",
        scenario,
        preferred_addressee=addressee,
    )

    assert addressee == "family"
    assert mechanism is not None
    assert mechanism[0] == "mechanism_details"
    assert "coffee table" in mechanism[1]["answer"]
    assert "weighs" not in mechanism[1]["answer"].lower()


def test_soft_tissue_bare_how_ignores_stale_patient_hint_after_trauma_opener():
    with open("app/scenarios/pediatric/trauma/peds_trauma_01_soft_tissue.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    mechanism = _resolve_history_response_entry(
        "how",
        scenario,
        preferred_addressee="patient",
    )

    assert mechanism is not None
    assert mechanism[0] == "mechanism_details"
    assert "coffee table" in mechanism[1]["answer"]
    assert "weighs" not in mechanism[1]["answer"].lower()


def test_soft_tissue_bare_how_deterministic_response_cannot_drift_to_weight():
    with open("app/scenarios/pediatric/trauma/peds_trauma_01_soft_tissue.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    mechanism = _resolve_history_response_entry(
        "how",
        scenario,
        preferred_addressee="family",
    )

    assert mechanism is not None
    text = _build_deterministic_history_response(mechanism[0], mechanism[1], scenario)
    assert text is not None
    assert "(father)" in text
    assert "coffee table" in text
    assert "[[HISTORY: Events=" in text
    assert "weigh" not in text.lower()
    assert "length-based" not in text.lower()


def test_auto_detected_apply_dressing_intervention_is_forced_into_chat_tag():
    with open("app/scenarios/pediatric/trauma/peds_trauma_01_soft_tissue.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    directive = _build_auto_intervention_directive(
        {"auto_interventions_from_message": ["direct_pressure"]},
        scenario,
    )

    assert "backend has just recorded" in directive
    assert "Direct Pressure & Pressure Dressing" in directive
    assert "[[INTERVENTION: Direct Pressure & Pressure Dressing]]" in directive
    assert "already done by someone else" in directive


def test_orientation_questions_route_to_communicative_patient_before_partner_or_family():
    with open("app/scenarios/pediatric/trauma/peds_trauma_01_soft_tissue.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    patient_questions = [
        "can you tell me your name and what day it is",
        "what day is today",
        "Leo what day of the week is it",
        "do you know what holiday we have coming up next week",
        "okay do you know your dad's name",
    ]

    for question in patient_questions:
        assert _infer_scene_addressee(question, scenario) == "patient"


def test_ai_prompt_recommends_against_current_events_orientation_trivia():
    source = open("app/ai_client.py", encoding="utf-8").read()

    assert "volatile current-world trivia" in source
    assert "president/governor/mayor" in source
    assert "person/place/time/event questions" in source
    assert "do not invent an answer" in source


def test_orientation_question_does_not_trigger_patient_dob_demographics():
    with open("app/scenarios/adult/medical/adult_acs_01_stemi.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    result = _resolve_history_response_entry(
        "what's your name and what day is it",
        scenario,
        preferred_addressee="patient",
    )
    assert result is not None
    _, entry = result

    assert "birthday" not in entry.get("answer", "").lower()
    assert "Patient Date of Birth" not in json.dumps(entry)
    assert "Patient Name" in json.dumps(entry)


def test_name_only_demographic_questions_do_not_disclose_dob_in_any_scenario():
    checked = []
    for path in Path("app/scenarios").rglob("*.json"):
        with open(path, encoding="utf-8") as fh:
            scenario = json.load(fh)
        if not isinstance(scenario.get("history_response_map"), dict):
            continue
        result = _resolve_history_response_entry("patient name", scenario)
        if not result:
            continue
        checked.append(path.name)
        _, entry = result

        serialized = json.dumps(entry)
        assert "birthday" not in entry.get("answer", "").lower(), path
        assert "date of birth" not in entry.get("answer", "").lower(), path
        assert "Patient Date of Birth" not in serialized, path

    assert checked


def test_explicit_patient_name_still_routes_to_responsive_pediatric_patient():
    with open("app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    assert _infer_scene_addressee("Marcus, can you tell me what happened?", scenario) == "patient"
    assert _infer_scene_addressee("talking to Marcus: what's your name?", scenario) == "patient"
    assert _infer_scene_addressee("Hi, can you tell me where it hurts?", scenario) == "patient"


def test_third_person_and_witness_questions_route_away_from_responsive_patient():
    with open("app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    assert _infer_scene_addressee("where does he hurt?", scenario) == "family"
    assert _infer_scene_addressee("did you see it happen?", scenario) == "family"


def test_nonverbal_patient_second_person_history_routes_to_caregiver():
    with open("app/scenarios/pediatric/medical/peds_croup_01.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    assert _infer_scene_addressee("where does it hurt?", scenario) == "family"
    assert _infer_scene_addressee("do you have any pain?", scenario) == "family"


def test_second_person_caregiver_knowledge_question_does_not_force_patient():
    with open("app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    assert _infer_scene_addressee("do you know what medications he takes?", scenario) == "family"


def test_adult_family_presence_does_not_override_responsive_patient_openers():
    with open("app/scenarios/adult/medical/adult_acs_01_stemi.json", encoding="utf-8") as fh:
        scenario = json.load(fh)

    assert _infer_scene_addressee("hi im jon, what's going on tonight?", scenario) == "patient"
    assert _infer_scene_addressee("when did it start?", scenario) == "patient"
    assert _infer_scene_addressee("ever happen before?", scenario) == "patient"
    assert _infer_scene_addressee("where does it hurt?", scenario) == "patient"


def test_adult_family_primary_historian_routes_openers_to_family_when_authored():
    with open("app/scenarios/adult/medical/adult_acs_01_stemi.json", encoding="utf-8") as fh:
        scenario = json.load(fh)
    scenario["initial_complaint"] = {
        "speaker": "Carol Lawson",
        "lay_summary": "I found him on the floor and he is not acting right.",
        "allowed_in_opener": True,
    }

    assert _infer_scene_addressee("hi im jon, what's going on tonight?", scenario) == "family"
    assert _infer_scene_addressee("what happened?", scenario) == "family"
    assert _infer_scene_addressee("where does it hurt?", scenario) == "patient"


def test_all_scenarios_declare_initial_complaint_guardrail():
    for path in sorted(Path("app/scenarios").glob("**/*.json")):
        with path.open(encoding="utf-8") as fh:
            scenario = json.load(fh)
        initial = scenario.get("initial_complaint")

        assert isinstance(initial, dict), f"{path} missing initial_complaint"
        assert initial.get("allowed_in_opener") is True, f"{path} must explicitly allow the opener"
        assert initial.get("speaker"), f"{path} missing initial_complaint.speaker"
        assert initial.get("lay_summary"), f"{path} missing initial_complaint.lay_summary"
        do_not_include = initial.get("do_not_include") or []
        assert "full OPQRST/SAMPLE" in do_not_include, f"{path} must block broad-opener history dumps"
        assert "treatment suggestions" in do_not_include or scenario.get("is_orientation"), (
            f"{path} must block treatment suggestions in broad openers"
        )


# ---------------------------------------------------------------------------
# Engine-side history response resolver
# ---------------------------------------------------------------------------

_DIABETIC_SCENARIO = None


def _load_diabetic_scenario():
    global _DIABETIC_SCENARIO
    if _DIABETIC_SCENARIO is None:
        with open("app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json", encoding="utf-8") as fh:
            _DIABETIC_SCENARIO = json.load(fh)
    return _DIABETIC_SCENARIO


def test_resolver_picks_sample_full_for_explicit_sample_request():
    scenario = _load_diabetic_scenario()
    result = _resolve_history_response_entry("can I get his SAMPLE?", scenario)
    assert result is not None
    key, entry = result
    assert key == "sample_full"


def test_resolver_picks_sample_full_for_full_sample_phrasing():
    scenario = _load_diabetic_scenario()
    result = _resolve_history_response_entry("give me a full sample please", scenario)
    assert result is not None
    key, _ = result
    assert key == "sample_full"


def test_resolver_picks_sample_full_for_compound_sample_without_exact_trigger():
    scenario = load_scenario("peds_croup_01")
    result = _resolve_history_response_entry(
        "signs and symptoms allergies medications past medical history events",
        scenario,
    )
    assert result is not None
    key, entry = result
    assert key == "sample_full"
    tags = entry["tags"]
    assert any(tag.startswith("[[HISTORY: Medications=") for tag in tags)
    assert any(tag.startswith("[[HISTORY: PMH=") for tag in tags)
    assert any(tag.startswith("[[HISTORY: Last Oral Intake=") for tag in tags)
    assert any(tag.startswith("[[HISTORY: Events=") for tag in tags)


def test_resolver_picks_diabetes_history_for_pmh_only_question():
    scenario = _load_diabetic_scenario()
    result = _resolve_history_response_entry("what's his PMH?", scenario)
    assert result is not None
    key, _ = result
    assert key == "diabetes_history"


def test_resolver_picks_diabetes_history_for_diabetic_question():
    scenario = _load_diabetic_scenario()
    result = _resolve_history_response_entry("is he diabetic?", scenario)
    assert result is not None
    key, _ = result
    assert key == "diabetes_history"


def test_resolver_picks_patient_identity_for_name_question():
    scenario = _load_diabetic_scenario()
    result = _resolve_history_response_entry("what's his name?", scenario)
    assert result is not None
    key, _ = result
    assert key == "patient_identity"


def test_resolver_returns_none_for_unrecognized_message():
    scenario = _load_diabetic_scenario()
    # Message with no trigger overlap against any entry
    result = _resolve_history_response_entry("let me assess his breath sounds", scenario)
    assert result is None


def test_resolver_returns_none_for_empty_map():
    result = _resolve_history_response_entry("what's his name?", {})
    assert result is None


def test_resolver_returns_none_for_missing_map():
    result = _resolve_history_response_entry("what's his name?", {"history_response_map": None})
    assert result is None


def test_resolver_sample_full_beats_diabetes_history_on_combined_question():
    scenario = _load_diabetic_scenario()
    # Student asks for SAMPLE — "sample" trigger in sample_full should win over
    # any diabetes_history trigger regardless of priority bonus.
    result = _resolve_history_response_entry("can you get me his sample history?", scenario)
    assert result is not None
    key, _ = result
    assert key == "sample_full"


def test_resolver_directive_includes_answer_and_tags():
    scenario = _load_diabetic_scenario()
    result = _resolve_history_response_entry("can I get his SAMPLE?", scenario)
    assert result is not None
    key, entry = result
    directive = _build_resolved_history_directive(key, entry)
    assert "ENGINE DIRECTIVE" in directive
    assert "sample_full" in directive or entry.get("label", "") in directive
    assert "[[HISTORY:" in directive
    assert "Omnipod" in directive or "insulin" in directive
    assert "natural lay speech" in directive


def test_resolver_directive_uses_initial_complaint_speaker_when_entry_has_no_speaker():
    scenario = load_scenario("peds_croup_01")
    result = _resolve_history_response_entry("when did it start", scenario)
    assert result is not None
    key, entry = result
    directive = _build_resolved_history_directive(key, entry, scenario)

    assert "Reply as Sarah" in directive
    assert "do not speak OPQRST/SAMPLE field labels" in directive


def test_resolver_priority_entry_beats_equal_length_nonpriority():
    scenario = {
        "history_response_map": {
            "narrow": {
                "triggers": ["sample"],
                "answer": "narrow answer",
                "tags": [],
                "notes": None,
                "priority": False,
            },
            "priority_entry": {
                "triggers": ["sample"],
                "answer": "priority answer",
                "tags": ["[[HISTORY: Test=value]]"],
                "notes": "Priority entry — use this when multiple components are requested.",
                "priority": True,
            },
        }
    }
    result = _resolve_history_response_entry("can I get a sample?", scenario)
    assert result is not None
    key, _ = result
    assert key == "priority_entry"


def test_resolver_nonpriority_wins_when_priority_entry_has_no_trigger_match():
    scenario = {
        "history_response_map": {
            "pmh_entry": {
                "triggers": ["pmh", "past medical history", "medical history"],
                "answer": "Type 1 diabetes",
                "tags": [],
                "notes": None,
                "priority": False,
            },
            "priority_entry": {
                "triggers": ["sample", "full sample"],
                "answer": "full SAMPLE answer",
                "tags": ["[[HISTORY: Signs and Symptoms=...]]"],
                "notes": "Priority entry — use for full SAMPLE",
                "priority": True,
            },
        }
    }
    # PMH question — priority_entry has no trigger match, so pmh_entry should win
    result = _resolve_history_response_entry("what's his PMH?", scenario)
    assert result is not None
    key, _ = result
    assert key == "pmh_entry"
