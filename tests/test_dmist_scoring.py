from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.dmist_scoring import DMIST_COMPONENT_MEANINGS, score_dmist, segment_dmist


def _finding(key: str, value: str, finding_type: str = "vital"):
    return SimpleNamespace(key=key, value=value, finding_type=finding_type)


def _febrile_scenario() -> dict:
    return json.loads(
        Path("app/scenarios/pediatric/medical/peds_febrile_seizure_01.json").read_text(encoding="utf-8")
    )


def _asthma_scenario() -> dict:
    return json.loads(
        Path("app/scenarios/pediatric/medical/peds_asthma_01.json").read_text(encoding="utf-8")
    )


def _croup_scenario() -> dict:
    return json.loads(
        Path("app/scenarios/pediatric/medical/peds_croup_01.json").read_text(encoding="utf-8")
    )


def _soft_tissue_scenario() -> dict:
    return json.loads(
        Path("app/scenarios/pediatric/trauma/peds_trauma_01_soft_tissue.json").read_text(encoding="utf-8")
    )


def _diabetic_scenario() -> dict:
    return json.loads(
        Path("app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json").read_text(encoding="utf-8")
    )


def _head_injury_scenario() -> dict:
    return json.loads(
        Path("app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json").read_text(encoding="utf-8")
    )


def test_dmist_component_meanings_follow_corrected_model():
    assert DMIST_COMPONENT_MEANINGS == {
        "D": "Demographics",
        "M": "MOI or chief complaint",
        "I": "Injuries or illness",
        "S": "Signs and symptoms",
        "T": "Treatment or transport",
    }


def test_segment_dmist_accepts_labeled_sections():
    sections = segment_dmist(
        "D: Chloe, 6-month-old female, 7 kg\n"
        "M: Active seizure\n"
        "I: Fever and first seizure\n"
        "S: Gurgling airway, temp 103.6\n"
        "T: Suction and ALS handoff"
    )

    assert sections["D"].startswith("Chloe")
    assert sections["M"] == "Active seizure"
    assert "first seizure" in sections["I"]
    assert "Gurgling" in sections["S"]
    assert "ALS handoff" in sections["T"]


def test_febrile_seizure_dmist_scores_full_credit_with_corrected_meanings():
    result = score_dmist(
        "D: Chloe, 6-month-old female, 7 kg.\n"
        "M: Active seizure chief complaint.\n"
        "I: Generalized full-body seizure, ongoing about 2 minutes, fever and congestion, first seizure, no trauma, choking, or ingestion.\n"
        "S: Still seizing, airway secretions and wet gurgling, SpO2 94%, temperature 103.6 F, blood glucose 92.\n"
        "T: Recovery position, suctioned oral secretions, oxygen by blow-by NRB, SpO2 improved, ALS handoff/transport.",
        scenario=_febrile_scenario(),
        applied_intervention_ids={"recovery_position", "suction_airway", "o2_blowby", "blood_glucose_check"},
        findings=[
            _finding("SpO2", "94 %"),
            _finding("Temperature", "103.6 F"),
            _finding("Blood Glucose", "92 mg/dL"),
        ],
        turnover_target="als",
    )

    assert result.score == 10
    assert result.components["D"].score == 2
    assert result.components["M"].score == 2
    assert result.components["I"].score == 2
    assert result.components["S"].score == 2
    assert result.components["T"].score == 2


def test_febrile_seizure_dmist_treatment_transport_gap_reduces_t_component_only():
    result = score_dmist(
        "D: Chloe, 6-month-old female, 7 kg.\n"
        "M: Active seizure chief complaint.\n"
        "I: Generalized full-body seizure, ongoing about 2 minutes, fever and congestion, first seizure.\n"
        "S: Still seizing, airway secretions and wet gurgling, SpO2 94%, temperature 103.6 F.\n",
        scenario=_febrile_scenario(),
        applied_intervention_ids={"recovery_position", "suction_airway", "o2_blowby"},
        findings=[_finding("SpO2", "94 %"), _finding("Temperature", "103.6 F")],
        turnover_target="als",
    )

    assert result.components["T"].score == 0
    assert result.score == 8


def test_febrile_seizure_dmist_t_full_credit_for_treatments_and_response_without_handoff_plan():
    result = score_dmist(
        "this is Chloe six month old female with an active seizure upon arrival with secretions in the mouth "
        "this is her first seizure put her into recovery position suctioned Airway administered Blow by oxygen "
        "initial spo2 of 94 blood glucose 92 temperature 103 after oxygen admin spo2 came up to 97",
        scenario=_febrile_scenario(),
        applied_intervention_ids={"recovery_position", "suction_airway", "o2_blowby", "blood_glucose_check"},
        findings=[
            _finding("SpO2", "94 %"),
            _finding("SpO2", "97 %"),
            _finding("Temperature", "103.6 F"),
            _finding("Blood Glucose", "92 mg/dL"),
        ],
        turnover_target="als",
    )

    assert result.components["D"].score == 1
    assert "pediatric weight" in result.components["D"].missing
    assert result.components["T"].score == 2
    assert "treatment response" in result.components["T"].matched
    assert result.score >= 8


def test_febrile_seizure_dmist_secretions_do_not_credit_suction_when_not_applied():
    result = score_dmist(
        "this is Chloe 6 month old female presented an active seizure lasting for 2 minutes "
        "initially found secretions of the mouth put her in the recovery position "
        "administered blow by oxygen initial blood glucose 92 temperature 103",
        scenario=_febrile_scenario(),
        applied_intervention_ids={"recovery_position", "o2_blowby", "blood_glucose_check"},
        findings=[
            _finding("Blood Glucose", "92 mg/dL"),
            _finding("Temperature", "103.6 F"),
        ],
        turnover_target="als",
    )

    assert "suctioned oral secretions" not in result.components["T"].matched
    assert "suctioned oral secretions" in result.components["T"].missing
    assert result.components["T"].score < 2


def test_dmist_demographics_accepts_spoken_word_month_age():
    result = score_dmist(
        "this is Chloe six month old female in active seizure",
        scenario=_febrile_scenario(),
        applied_intervention_ids=set(),
        findings=[],
        turnover_target="als",
    )

    assert "age" in result.components["D"].matched
    assert "pediatric weight" in result.components["D"].missing
    assert result.components["D"].score == 1


def test_febrile_seizure_dmist_claimed_suction_without_timeline_is_flagged():
    result = score_dmist(
        "Chloe 6 month old female active seizure. I suctioned oral secretions, "
        "placed her in recovery position, and gave blow by oxygen.",
        scenario=_febrile_scenario(),
        applied_intervention_ids={"recovery_position", "o2_blowby"},
        findings=[],
        turnover_target="als",
    )

    assert "suctioned oral secretions" in result.components["T"].missing
    assert "unsupported_intervention_claim:suction_airway" in result.components["T"].flags
    assert result.components["T"].score < 2


def test_asthma_dmist_t_full_credit_for_albuterol_and_response_without_als_plan():
    result = score_dmist(
        "Liam 4 year old male history of asthma difficulty breathing started 30 minutes prior "
        "to playing outside does not have his inhaler auscultated expiratory wheeze initial "
        "SpO2 93% and 33 breaths per minute administered albuterol SpO2 came up to 98% "
        "respirations down to 26 and lung sounds clear",
        scenario=_asthma_scenario(),
        applied_intervention_ids={"albuterol_svn"},
        findings=[
            _finding("SpO2", "93 %"),
            _finding("Resp Rate", "33 breaths/min"),
            _finding("SpO2", "98 %"),
            _finding("Resp Rate", "26 breaths/min"),
        ],
        turnover_target="als",
    )

    assert result.components["T"].score == 2
    assert "ALS readiness" not in result.components["T"].missing
    assert "treatment response" in result.components["T"].matched


def test_diabetic_dmist_accepts_concise_ems_shorthand_and_glucose_response():
    result = score_dmist(
        "this is an 8 YOM, AMS, 60# PMHx DM1\n\n"
        "we got BGL 38, admin 15g oral glucose and improved to 64, no allergies, dexcom is acting up",
        scenario=_diabetic_scenario(),
        applied_intervention_ids={"blood_glucose_check", "oral_glucose"},
        findings=[
            _finding("Blood Glucose", "38 mg/dL"),
            _finding("Blood Glucose", "64.8 mg/dL"),
            _finding("SpO2", "99 %"),
            _finding("Heart Rate", "112 bpm"),
        ],
        turnover_target="als",
    )

    assert result.components["D"].matched == ["age", "sex", "pediatric weight"]
    assert result.components["D"].missing == ["name"]
    assert result.components["M"].score >= 1
    assert "Type 1 DM / known diabetic" in result.components["M"].matched
    assert "CGM alarm or BG reading (~38 mg/dL)" in result.components["M"].matched
    assert result.components["I"].score >= 1
    assert result.components["T"].score == 2
    assert "oral glucose administered" in result.components["T"].matched
    assert "BGL post-treatment value or trend (primary)" in result.components["T"].matched
    assert result.score >= 6


def test_legacy_intervention_i_config_is_ignored_for_corrected_illness_scoring():
    scenario = {
        "turnover_target": "als",
        "patient": {"name": "Ari", "age": 10, "sex": "female"},
        "scoring": {
            "dmist_components": {
                "I": {
                    "description": "Interventions performed",
                    "required_elements": ["oxygen administered", "albuterol administered"],
                }
            }
        },
    }

    result = score_dmist(
        "D: Ari, 10-year-old female.\n"
        "M: difficulty breathing.\n"
        "I: illness history includes cough and wheezing that started after outdoor activity; no injury.\n"
        "S: SpO2 93%, wheezing, increased work of breathing.\n"
        "T: albuterol given and breathing improved.",
        scenario=scenario,
        applied_intervention_ids={"albuterol_svn"},
        findings=[_finding("SpO2", "93 %")],
        turnover_target="als",
    )

    assert result.components["I"].score == 2
    assert result.components["I"].missing == []
    assert "legacy_intervention_i_config_ignored" in result.components["I"].flags


def test_croup_dmist_does_not_require_saying_croup_or_als_handoff_phrase():
    result = score_dmist(
        "this is Lily 10 month old female with difficulty breathing and a barking like cough "
        "started about 20 minutes ago had a fever last night auscultated inspiratory strider "
        "initial spo2 of 92 respirations 45 temperature 100 positioned upright kept calm "
        "and administered blow by oxygen 15 L per minute spo2 came up to 96%",
        scenario=_croup_scenario(),
        applied_intervention_ids={"position_of_comfort", "minimize_stimulation", "o2_blowby"},
        findings=[
            _finding("SpO2", "92 %"),
            _finding("Resp Rate", "45 /min"),
            _finding("Temperature", "100.4 F"),
            _finding("SpO2", "96 %"),
        ],
        turnover_target="als",
    )

    assert result.components["M"].score == 2
    assert "croup" not in result.components["M"].missing
    assert result.components["I"].score >= 1
    assert all("\\" not in item for item in result.components["I"].matched)
    assert result.components["T"].score == 2
    assert "ALS readiness" not in result.components["T"].missing


def test_soft_tissue_dmist_credits_mechanism_neuro_signs_and_treatment_response():
    result = score_dmist(
        "this is Leo 4-year-old male he was running and tripped and fell hit his head "
        "on the edge of the table lacerating his scalp initial GCS of 15 normal vitals "
        "pupils equal and reactive no loss of consciousness direct pressure and dry "
        "sterile dressing he's A and O times 4",
        scenario=_soft_tissue_scenario(),
        applied_intervention_ids={"direct_pressure"},
        findings=[
            _finding("Blood Pressure", "100/65 mmHg"),
            _finding("SpO2", "99%"),
            _finding("Heart Rate", "130 bpm"),
            _finding("Resp Rate", "24/min"),
            _finding("GCS", "15/15"),
            _finding("Pupils", "PERRL", finding_type="exam"),
        ],
        turnover_target="als",
    )

    assert result.components["D"].score == 1
    assert "pediatric weight" in result.components["D"].missing
    assert result.components["M"].score == 2
    assert result.components["S"].score >= 1
    assert result.components["T"].score == 2
    assert result.score >= 8


def test_soft_tissue_dmist_accepts_name_age_and_broselow_size_shorthand():
    result = score_dmist(
        "leo is 4, bumped his head, no pain, controlled bleeding, green on broslow, "
        "no history, normal appearing",
        scenario=_soft_tissue_scenario(),
        applied_intervention_ids={"direct_pressure"},
        findings=[
            _finding("SpO2", "99 %"),
            _finding("GCS", "15/15"),
            _finding("Pupils", "PERRL", finding_type="exam"),
            _finding("Pain", "8/10 sharp head pain", finding_type="exam"),
        ],
        turnover_target="als",
    )

    assert result.components["D"].matched == ["name", "age", "pediatric weight"]
    assert result.components["D"].missing == ["sex"]
    assert "fall mechanism" in result.components["M"].missing
    assert "neuro status" in result.components["T"].missing
    assert result.score >= 5


def test_head_injury_dmist_does_not_credit_smr_without_applied_intervention():
    result = score_dmist(
        "this is Marcus 8-year-old male fell from the monkey bars about 5 ft hit his head on the ground "
        "no report of loss of consciousness currently GCS of 14 and confused administering 15 L per minute "
        "oxygen high flow non-rebreather",
        scenario=_head_injury_scenario(),
        applied_intervention_ids={"o2_nrb"},
        findings=[
            _finding("SpO2", "97%"),
            _finding("Heart Rate", "107 bpm"),
            _finding("Blood Pressure", "106/70"),
            _finding("GCS", "14/15"),
        ],
        turnover_target="als",
    )

    assert result.components["T"].score == 1
    assert "SMR reported in handoff" in result.components["T"].missing
    assert "O2 reported in handoff" in result.components["T"].matched
    assert "unsupported_intervention_claim:smr" not in result.components["T"].flags


def test_head_injury_dmist_credits_confusion_and_pupil_speech_to_text_variants():
    result = score_dmist(
        "this is Marcus 8-year-old male fell from the monkey bars about eight feet up hit his head "
        "on the ground no loss of consciousness reported but vomiting after impact currently GCS of 14 "
        "due to confusion posterior tenderness on scalp sluggishness and eyes pupils on equal vitals "
        "normal administered 15 L per minute oxygen via non rebreather",
        scenario=_head_injury_scenario(),
        applied_intervention_ids={"smr", "o2_nrb"},
        findings=[
            _finding("SpO2", "97%"),
            _finding("Heart Rate", "106 bpm"),
            _finding("Blood Pressure", "106/70"),
            _finding("GCS", "14/15"),
            _finding("Pupils", "R 4 mm sluggish; L 3 mm brisk", finding_type="exam"),
        ],
        turnover_target="als",
    )

    assert "confused/disoriented" in result.components["I"].matched
    assert "unequal pupils" in result.components["I"].matched
    assert "pupil exam finding (primary)" in result.components["S"].matched
    assert "SMR reported in handoff" in result.components["T"].missing
    assert "O2 reported in handoff" in result.components["T"].matched
    assert result.components["T"].score == 1


def test_head_injury_dmist_credits_latest_run_speech_to_text_variants():
    result = score_dmist(
        "is Marcus 8 years old male fell from the monkey bars about 8 ft hit his head on the ground "
        "initially vomited no loss of consciousness reported GCS of 14 due to confusion pupils slow to "
        "react on equal I measured 15 L per minute oxygen and healthy spine",
        scenario=_head_injury_scenario(),
        applied_intervention_ids={"smr", "o2_nrb"},
        findings=[
            _finding("SpO2", "97%"),
            _finding("Heart Rate", "107 bpm"),
            _finding("Blood Pressure", "106/70"),
            _finding("GCS", "14/15"),
            _finding("Pupils", "R 4 mm sluggish; L 3 mm brisk", finding_type="exam"),
        ],
        turnover_target="als",
    )

    assert "fall height approximately 8 feet" in result.components["M"].matched
    assert "single vomiting episode" in result.components["M"].matched
    assert "unequal pupils" in result.components["I"].matched
    assert "pupil exam finding (primary)" in result.components["S"].matched
    assert "SMR reported in handoff" in result.components["T"].matched
    assert "O2 reported in handoff" in result.components["T"].matched


def test_pediatric_weight_required_but_adult_weight_not_required():
    pediatric = _febrile_scenario()
    pediatric_result = score_dmist(
        "D: Chloe, 6-month-old female.\nM: Active seizure.\nI: Fever and seizure.\nS: Febrile.\nT: ALS handoff.",
        scenario=pediatric,
        applied_intervention_ids=set(),
        findings=[],
        turnover_target="als",
    )
    assert "pediatric weight" in pediatric_result.components["D"].missing
    assert pediatric_result.components["D"].score == 1

    adult = {
        "turnover_target": "als",
        "patient": {"name": "Robert", "age": 54, "sex": "male"},
        "scoring": {"dmist_components": {"M": {"required_elements": ["chest pain chief complaint"]}}},
    }
    adult_result = score_dmist(
        "D: Robert, 54-year-old male.\nM: chest pain.\nI: illness.\nS: signs.\nT: transport.",
        scenario=adult,
        applied_intervention_ids=set(),
        findings=[],
        turnover_target="als",
    )
    assert "pediatric weight" not in adult_result.components["D"].missing
    assert adult_result.components["D"].score == 2


def test_demographics_accepts_pediatric_yom_shorthand():
    result = score_dmist(
        "D: Leo, 4 yom.\nM: fall.\nI: scalp cut.\nS: GCS 15.\nT: dressing applied.",
        scenario=_soft_tissue_scenario(),
        applied_intervention_ids={"pressure_dressing"},
        findings=[_finding("GCS", "15/15")],
        turnover_target="als",
    )

    assert "age" in result.components["D"].matched
    assert "sex" in result.components["D"].matched
    assert "age" not in result.components["D"].missing
    assert "sex" not in result.components["D"].missing
    assert result.components["D"].missing == ["pediatric weight"]


def test_generic_shadow_scoring_handles_scenarios_without_dmist_components():
    adult = {
        "turnover_target": "hospital",
        "patient": {"name": "Robert", "age": 54, "sex": "male"},
        "scoring": {},
    }
    result = score_dmist(
        "D: Robert, 54-year-old male.\n"
        "M: Chief complaint chest pain.\n"
        "I: Illness history includes substernal pain that started 20 minutes ago, no allergies.\n"
        "S: BP 148/92, HR 96, SpO2 98%, skin pale.\n"
        "T: Aspirin given and transporting to the ED.",
        scenario=adult,
        applied_intervention_ids=set(),
        findings=[
            _finding("Blood Pressure", "148/92"),
            _finding("Heart Rate", "96"),
            _finding("SpO2", "98%"),
        ],
        turnover_target="hospital",
    )

    assert result.score == 10
    assert result.components["M"].score == 2
    assert result.components["I"].score == 2
    assert result.components["T"].score == 2


def test_signs_component_flags_unassessed_vital_claims():
    result = score_dmist(
        "D: Chloe, 6-month-old female, 7 kg.\n"
        "M: Active seizure.\n"
        "I: Fever and seizure.\n"
        "S: HR 173, BP 82/48, temp 103.6 F.\n"
        "T: ALS handoff.",
        scenario=_febrile_scenario(),
        applied_intervention_ids=set(),
        findings=[_finding("Temperature", "103.6 F")],
        turnover_target="als",
    )

    assert result.components["S"].score <= 1
    assert any(flag.startswith("unassessed_vital_claims") for flag in result.components["S"].flags)
