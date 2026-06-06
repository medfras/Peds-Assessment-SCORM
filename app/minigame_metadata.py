"""Authoritative static metadata for mini-game routing and unlock contracts.

Learner result rows are evidence of performance. They are not the source of
truth for what a game teaches, which rubric categories it remediates, or what
counts as passing for reference-card/mastery-flow purposes.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_PASS_THRESHOLD: dict[str, int] = {"score_gte": 80}

VALID_RUBRIC_CATEGORY_IDS: set[str] = {
    "clinical_performance",
    "protocols_treatment",
    "narrative",
    "dmist",
    "professionalism",
    "scope_adherence",
}


MINIGAME_METADATA: dict[str, dict[str, Any]] = {
    "pat": {
        "display_name": "PAT Doorway Dash",
        "skill_tags": ["pat_impression"],
        "rubric_category_mapping": ["clinical_performance"],
        "pass_threshold": {"score_gte": 70},
        "hint_policy": "Point to appearance, work of breathing, or circulation cue; do not say sick/not sick.",
        "reference_card": {
            "id": "ref_pat_doorway_impression",
            "unlock_condition": {"all_passed": ["pat"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, add highest-priority first-action implication prompts.",
    },
    "ten4_facesp": {
        "display_name": "TEN-4 FACESp",
        "skill_tags": ["non_accidental_trauma_screening"],
        "rubric_category_mapping": ["clinical_performance", "professionalism", "narrative"],
        "hint_policy": "Point to objective age, location, and pattern criteria; do not name the classification.",
        "reference_card": {
            "id": "ref_ten4_facesp",
            "unlock_condition": {"all_passed": ["ten4_facesp"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, add documentation-language follow-up prompts.",
    },
    "adult_child_ap_swipe": {
        "display_name": "Adult/Peds Assessment Priorities",
        "skill_tags": ["pediatric_anatomy"],
        "rubric_category_mapping": ["clinical_performance", "protocols_treatment"],
        "hint_policy": "Point to the physiologic or assessment consequence; do not name adult, child, or both.",
        "reference_card": {
            "id": "ref_adult_peds_assessment_differences",
            "unlock_condition": {"all_passed": ["adult_child_ap_swipe"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, use clinical-consequence questions instead of classification swipes.",
    },
    "lung_sounds_matcher": {
        "display_name": "Lung Sounds",
        "skill_tags": ["lung_sound_identification"],
        "rubric_category_mapping": ["clinical_performance", "protocols_treatment"],
        "hint_policy": "Point to sound quality, airway level, or treatment branch; do not name the sound or intervention.",
        "reference_card": {
            "id": "ref_breath_sounds_actions",
            "unlock_condition": {"all_passed": ["lung_sounds_matcher"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "Two-round flow is standard: identify sound, then choose the best in-scope intervention from a clinical presentation.",
    },
    "sound_check": {
        "display_name": "Sound Check",
        "skill_tags": ["lung_sound_identification", "respiratory_assessment"],
        "rubric_category_mapping": ["clinical_performance", "protocols_treatment"],
        "hint_policy": "Point to sound quality, airway level, or first respiratory action; do not name the sound.",
        "reference_card": {
            "id": "ref_breath_sounds_actions",
            "unlock_condition": {"all_passed": ["sound_check"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, lead with field-action implications before replaying the audio clip.",
    },
    "history_maker": {
        "display_name": "History Maker",
        "skill_tags": ["history_taking"],
        "rubric_category_mapping": ["clinical_performance", "narrative"],
        "hint_policy": "Point to the OPQRST/SAMPLE target and patient cue; do not reveal the chunk sequence.",
        "reference_card": {
            "id": "ref_opqrst_sample_peds",
            "unlock_condition": {"all_passed": ["history_maker:foundation", "history_maker:interview_builder"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": {
            "modes": ["foundation", "interview_builder"],
            "next": "reference_card/ref_opqrst_sample_peds",
        },
        "adaptive_next_step": "After proficiency, route to scenario practice or complex caregiver/source Interview Builder cases.",
    },
    "peds_gcs_calculator": {
        "display_name": "Pediatric GCS",
        "skill_tags": ["gcs_calculation"],
        "rubric_category_mapping": ["clinical_performance", "narrative"],
        "hint_policy": "Point to observed E/V/M behavior or scale cue; do not reveal the number.",
        "reference_card": {
            "id": "ref_peds_gcs",
            "unlock_condition": {"all_passed": ["peds_gcs_calculator"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, require scale inference from age/presentation without explicit prompting.",
    },
    "ams_aeioutips": {
        "display_name": "AMS: AEIOU-TIPS",
        "skill_tags": ["ams_differential", "aeioutips_recall"],
        "rubric_category_mapping": ["clinical_performance", "protocols_treatment"],
        "hint_policy": "Point to finding class or first safety check; do not name the category.",
        "reference_card": {
            "id": "ref_aeioutips_field_actions",
            "unlock_condition": {"all_passed": ["ams_aeioutips"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, ask first treatment or assessment priority from a finding/vignette.",
    },
    "dev_flags": {
        "display_name": "Developmental Red Flags",
        "skill_tags": ["developmental_red_flags"],
        "rubric_category_mapping": ["clinical_performance", "professionalism"],
        "hint_policy": "Point to expected vs regression vs further-assessment cue; do not name the classification.",
        "reference_card": {
            "id": "ref_developmental_stages_red_flags",
            "unlock_condition": {"all_passed": ["dev_sort", "dev_flags"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": {"previous": "dev_sort", "next": "dev_flags"},
        "adaptive_next_step": "CE learners should continue into developmental red-flag application rather than milestone bucket sorting.",
    },
    "dmist_builder": {
        "display_name": "DMIST Builder",
        "skill_tags": ["handoff_communication"],
        "rubric_category_mapping": ["dmist", "narrative"],
        "hint_policy": "Point to receiving-team need or DMIST section; do not identify include/skip.",
        "reference_card": {
            "id": "ref_dmist_handoff",
            "unlock_condition": {"all_passed": ["dmist_builder"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, add sequence scoring and soft time pressure.",
    },
    "protocol_pivot": {
        "display_name": "Protocol Pivot",
        "skill_tags": ["clinical_impression_update"],
        "rubric_category_mapping": ["clinical_performance", "protocols_treatment"],
        "hint_policy": "Point to the new finding type; do not reveal the updated impression.",
        "reference_card": {
            "id": "ref_protocol_pivot_anchoring",
            "unlock_condition": {"all_passed": ["protocol_pivot"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "Expand cases and preserve scoring for wrong-to-correct recovery.",
    },
    "vitals_trend_spotter": {
        "display_name": "Vitals Trend Spotter",
        "skill_tags": ["vitals_trend_reading"],
        "rubric_category_mapping": ["clinical_performance", "protocols_treatment"],
        "hint_policy": "Point to trend direction and earliest abnormality; do not identify the event time.",
        "reference_card": {
            "id": "ref_vitals_trend_interpretation",
            "unlock_condition": {"all_passed": ["vitals_trend_spotter"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, increase channel complexity and add delayed reveal/playback.",
    },
    "cpr_bls_sequence": {
        "display_name": "CPR Mastery: Round 2 — Chain of Survival",
        "skill_tags": ["cpr_sequence", "bls_competency"],
        "rubric_category_mapping": ["clinical_performance", "protocols_treatment"],
        "hint_policy": "Guide toward the next step in sequence without revealing the full order or the specific error.",
        "reference_card": {
            "id": "ref_aha_cpr_guide",
            "unlock_condition": {"all_passed": ["cpr_bls_sequence", "cpr_bls_concepts"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "pass_threshold": {"score_gte": 70},
        "mastery_flow": {"previous": "cpr_bls_concepts", "next": "adult_cardiac_arrest_01_bls"},
        "adaptive_next_step": "After proficiency, route to the integrated CPR training scenario/challenge.",
    },
    "cpr_bls_concepts": {
        "display_name": "CPR Mastery: Round 1 — Key Metrics",
        "skill_tags": ["cpr_metrics", "bls_competency"],
        "rubric_category_mapping": ["clinical_performance", "protocols_treatment"],
        "hint_policy": "Hint toward physiologic rationale (recoil, rate, depth) without giving the exact numeric value.",
        "reference_card": {
            "id": "ref_aha_cpr_guide",
            "unlock_condition": {"all_passed": ["cpr_bls_sequence", "cpr_bls_concepts"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "pass_threshold": {"score_gte": 70},
        "mastery_flow": {"next": "cpr_bls_sequence"},
        "adaptive_next_step": "After proficiency, route to cpr_bls_sequence for Chain of Survival ordering, then to the integrated CPR scenario.",
    },
    "shock_spotter_med": {
        "display_name": "Shock Spotter: Medical",
        "skill_tags": ["shock_recognition", "medical_assessment"],
        "rubric_category_mapping": ["clinical_performance", "protocols_treatment"],
        "hint_policy": "Point to perfusion, mentation, BP trend, or compensation cue; do not name the shock stage.",
        "reference_card": {
            "id": "ref_shock_spotter_medical",
            "unlock_condition": {"all_passed": ["shock_spotter_med"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, add first-action and transport-priority implication prompts.",
    },
    "diff_dash_ams": {
        "display_name": "Differential Dash: AMS",
        "skill_tags": ["ams_differential", "pattern_recognition"],
        "rubric_category_mapping": ["clinical_performance", "protocols_treatment"],
        "hint_policy": "Point to the reversible threat or finding class; do not name the etiology.",
        "reference_card": {
            "id": "ref_ams_differential_dash",
            "unlock_condition": {"all_passed": ["diff_dash_ams"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, use first-action priority cases instead of finding-to-etiology matching.",
    },
    "diff_dash_resp": {
        "display_name": "Differential Dash: Respiratory",
        "skill_tags": ["respiratory_differential", "respiratory_assessment"],
        "rubric_category_mapping": ["clinical_performance", "protocols_treatment"],
        "hint_policy": "Point to airway level, sound quality, work of breathing, or exposure cue; do not name the etiology.",
        "reference_card": {
            "id": "ref_respiratory_differential_dash",
            "unlock_condition": {"all_passed": ["diff_dash_resp"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, use first-action priority cases for respiratory distress presentations.",
    },
    "resp_dx_1q": {
        "display_name": "Differential Detective: Resp-Dx",
        "skill_tags": ["respiratory_differential", "respiratory_assessment", "clinical_impression_update"],
        "rubric_category_mapping": ["clinical_performance", "protocols_treatment"],
        "hint_policy": "Point to the clinical system category most likely to differentiate; do not name the finding or the diagnosis.",
        "reference_card": {
            "id": "ref_resp_dx_discriminators",
            "title": "Respiratory Differential Discriminators",
            "unlock_condition": {"all_passed": ["resp_dx_1q"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, introduce dual-pathology presentations where two differentials are simultaneously supported.",
    },
    "rule_of_nines": {
        "display_name": "Rule of Nines",
        "skill_tags": ["burn_assessment", "trauma_assessment"],
        "rubric_category_mapping": ["clinical_performance", "protocols_treatment"],
        "hint_policy": "Point to body region, special-area concern, or transport implication; do not reveal the percentage or follow-up answer.",
        "reference_card": {
            "id": "ref_rule_of_nines",
            "unlock_condition": {"all_passed": ["rule_of_nines"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, use pediatric-adjusted BSA and burn-center triage cases.",
    },
    "moi_mapper": {
        "display_name": "MOI Mapper",
        "skill_tags": ["moi_recognition", "trauma_assessment"],
        "rubric_category_mapping": ["clinical_performance", "protocols_treatment"],
        "hint_policy": "Point to energy transfer, body region, or hidden injury pattern; do not reveal the implication.",
        "reference_card": {
            "id": "ref_moi_mapper",
            "unlock_condition": {"all_passed": ["moi_mapper"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, add next-assessment priority prompts for high-risk mechanisms.",
    },
    "shock_spotter_trauma": {
        "display_name": "Shock Spotter: Trauma",
        "skill_tags": ["shock_recognition", "trauma_assessment"],
        "rubric_category_mapping": ["clinical_performance", "protocols_treatment"],
        "hint_policy": "Point to hemorrhage, perfusion, compensation, or mechanism cue; do not name the shock state.",
        "reference_card": {
            "id": "ref_shock_spotter_trauma",
            "unlock_condition": {"all_passed": ["shock_spotter_trauma"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, ask hemorrhage-control or transport-priority implications.",
    },
    "temp_check": {
        "display_name": "Temp Check",
        "skill_tags": ["temperature_emergency", "environmental_assessment"],
        "rubric_category_mapping": ["clinical_performance", "protocols_treatment"],
        "hint_policy": "Point to exposure, mental status, temperature trend, or sepsis risk; do not reveal the treatment priority.",
        "reference_card": {
            "id": "ref_temperature_emergency_care",
            "unlock_condition": {"all_passed": ["temp_check"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, use mixed environmental/sepsis cases with incomplete temperature data.",
    },
    "stop_the_bleed": {
        "display_name": "Stop the Bleed",
        "skill_tags": ["hemorrhage_control", "trauma_assessment"],
        "rubric_category_mapping": ["protocols_treatment", "clinical_performance"],
        "hint_policy": "Point to wound type/location and whether current control is failing; do not name the next step.",
        "reference_card": {
            "id": "ref_stop_the_bleed",
            "unlock_condition": {"all_passed": ["stop_the_bleed"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, use mixed hemorrhage cases with distractor procedures and shock trends.",
    },
    "bls_sequence": {
        "display_name": "BLS Sequence",
        "skill_tags": ["bls_sequence", "cardiac_arrest"],
        "rubric_category_mapping": ["protocols_treatment", "clinical_performance"],
        "hint_policy": "Point to the algorithm phase; do not reveal the order.",
        "reference_card": {
            "id": "ref_bls_sequence",
            "unlock_condition": {"all_passed": ["bls_sequence"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, use scenario-specific CPR/AED sequencing with rhythm and ratio changes.",
    },
    "priority_stack": {
        "display_name": "Priority Stack",
        "skill_tags": ["priority_synthesis", "high_acuity_assessment"],
        "rubric_category_mapping": ["clinical_performance", "protocols_treatment", "professionalism"],
        "hint_policy": "Point to competing priorities and immediate life threats; do not reveal the rank.",
        "reference_card": {
            "id": "ref_priority_stack",
            "unlock_condition": {"all_passed": ["priority_stack"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, add incomplete-data cases where learners must ask one clarifying question before ranking.",
    },
}


LEGACY_MINIGAME_METADATA: dict[str, dict[str, Any]] = {
    "pat": {
        "display_name": "PAT Doorway Dash",
        "skill_tags": ["pat_impression"],
        "rubric_category_mapping": ["clinical_performance"],
        "pass_threshold": {"score_gte": 70},
        "hint_policy": "Point to appearance, work of breathing, or circulation cue; do not say sick/not sick.",
        "reference_card": {
            "id": "ref_pat_doorway_impression",
            "unlock_condition": {"all_passed": ["pat"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": None,
        "adaptive_next_step": "After proficiency, add highest-priority first-action implication prompts.",
    },
    "dev_sort": {
        "display_name": "Pediatric Development Stages",
        "skill_tags": ["developmental_stage"],
        "rubric_category_mapping": ["clinical_performance", "professionalism"],
        "pass_threshold": {"score_gte": 70},
        "hint_policy": "Point to age range or developmental domain; do not name the bucket.",
        "reference_card": {
            "id": "ref_developmental_stages_red_flags",
            "unlock_condition": {"all_passed": ["dev_sort", "dev_flags"]},
            "content_schema": ["framework_summary", "common_traps", "field_examples", "review_status"],
        },
        "mastery_flow": {"next": "dev_flags"},
        "adaptive_next_step": "CE routing should prefer dev_flags unless milestone recall is the demonstrated gap.",
    },
}


REFERENCE_CARD_CONTENT: dict[str, dict[str, Any]] = {
    "ref_ten4_facesp": {
        "title": "TEN-4 FACESp Bruising Screen",
        "framework_summary": [
            "Use TEN-4 FACESp as an objective bruising screen, not as a diagnosis.",
            "Age, location, pattern, and explanation determine whether the finding requires escalation.",
        ],
        "common_traps": [
            "Calling concerning bruising accidental because the child is otherwise well appearing.",
            "Documenting suspected abuse as a conclusion instead of objective location/pattern findings.",
        ],
        "field_examples": [
            "Torso bruising in a non-mobile infant is concerning even with normal vital signs.",
            "A patterned ear bruise should be documented precisely and reported per policy.",
        ],
        "related_game_ids": ["ten4_facesp"],
        "review_status": "clinical_review_pending",
    },
    "ref_adult_peds_assessment_differences": {
        "title": "Adult vs Pediatric Assessment Differences",
        "framework_summary": [
            "Pediatric anatomy changes airway position, ventilation mechanics, dosing, and compensation patterns.",
            "Ask what the finding changes in field care, not just whether it is an adult or pediatric fact.",
        ],
        "common_traps": [
            "Treating normal pediatric blood pressure as reassurance during compensated shock.",
            "Forgetting that a large occiput can flex the airway during supine positioning.",
        ],
        "field_examples": [
            "A shoulder pad may improve neutral airway alignment in a toddler being ventilated.",
            "Pale skin, delayed cap refill, and tachycardia can indicate pediatric shock before hypotension.",
        ],
        "related_game_ids": ["adult_child_ap_swipe"],
        "review_status": "draft",
    },
    "ref_breath_sounds_actions": {
        "title": "Breath Sounds and Field Actions",
        "framework_summary": [
            "Identify sound quality, airway level, and clinical implication before choosing treatment.",
            "Audio recognition should lead to a field action: bronchodilator, suction, airway positioning, oxygenation, or transport priority.",
        ],
        "common_traps": [
            "Confusing upper-airway stridor with lower-airway wheeze.",
            "Treating clear lung sounds as proof that respiratory distress is benign.",
        ],
        "field_examples": [
            "Bilateral wheezes with distress point toward bronchodilator therapy and reassessment.",
            "Rhonchi that clear with cough suggest moveable secretions rather than fixed bronchospasm.",
        ],
        "related_game_ids": ["lung_sounds_matcher", "sound_check"],
        "review_status": "draft",
    },
    "ref_opqrst_sample_peds": {
        "title": "OPQRST and SAMPLE Pediatric History",
        "framework_summary": [
            "OPQRST clarifies the chief symptom; SAMPLE fills in context that changes risk and treatment.",
            "Good field questions are built from the patient presentation, caregiver source, and immediate differential.",
        ],
        "common_traps": [
            "Asking checklist questions in order while missing the one history item that changes care now.",
            "Letting caregiver narrative replace a specific onset, medication, allergy, or event question.",
        ],
        "field_examples": [
            "For croup-like distress, ask what worsens breathing or stridor.",
            "For anaphylaxis, ask immediately whether an epinephrine auto-injector is present and used.",
        ],
        "related_game_ids": ["history_maker"],
        "review_status": "draft",
    },
    "ref_peds_gcs": {
        "title": "Pediatric GCS",
        "framework_summary": [
            "Score eye, verbal, and motor components separately before adding the total.",
            "Use age-appropriate verbal and motor anchors for infants and children.",
        ],
        "common_traps": [
            "Scoring purposeful localization as simple withdrawal.",
            "Using the child verbal scale for an infant who cannot produce oriented speech.",
        ],
        "field_examples": [
            "Pushing your hand away from the painful stimulus is localization.",
            "Inconsolable persistent crying in an infant differs from crying only to pain.",
        ],
        "related_game_ids": ["peds_gcs_calculator"],
        "review_status": "draft",
    },
    "ref_aeioutips_field_actions": {
        "title": "AEIOU-TIPS Field Actions",
        "framework_summary": [
            "Use AEIOU-TIPS to keep AMS differentials broad while prioritizing reversible threats.",
            "Glucose, oxygenation/ventilation, perfusion, toxins, trauma, temperature, seizure, and stroke are field-action categories.",
        ],
        "common_traps": [
            "Anchoring on opioids from pinpoint pupils while missing organophosphate or other toxin patterns.",
            "Calling psychiatric AMS before checking glucose, oxygenation, trauma, and toxidromes.",
        ],
        "field_examples": [
            "RR 6 with miosis prioritizes airway support and naloxone.",
            "Sudden facial droop and arm drift requires last-known-well time and stroke-center routing.",
        ],
        "related_game_ids": ["ams_aeioutips"],
        "review_status": "draft",
    },
    "ref_developmental_stages_red_flags": {
        "title": "Developmental Stages and Red Flags",
        "framework_summary": [
            "Differentiate expected variation, further-assessment findings, and true red flags.",
            "Regression is concerning regardless of the exact age window.",
        ],
        "common_traps": [
            "Using a wait-and-see approach for loss of a previously acquired skill.",
            "Calling an early or advanced skill abnormal when it only needs documentation.",
        ],
        "field_examples": [
            "Loss of language after prior word use should trigger developmental concern.",
            "A 4-month-old not yet rolling may need follow-up, not emergency escalation by itself.",
        ],
        "related_game_ids": ["dev_sort", "dev_flags"],
        "review_status": "draft",
    },
    "ref_dmist_handoff": {
        "title": "DMIST Handoff",
        "framework_summary": [
            "DMIST prioritizes demographics, mechanism/medical complaint, injuries/illness, signs, and treatment/transport status.",
            "A good handoff tells the receiving team what to prepare for first.",
        ],
        "common_traps": [
            "Including social details that do not change receiving-team preparation.",
            "Omitting trend, intervention response, or ETA from a time-sensitive patient.",
        ],
        "field_examples": [
            "STEMI handoff should include ECG finding, onset timing, aspirin/nitro, vitals, and cath-lab request.",
            "Trauma handoff should include mechanism, unstable findings, interventions, trend, and ETA.",
        ],
        "related_game_ids": ["dmist_builder"],
        "review_status": "draft",
    },
    "ref_protocol_pivot_anchoring": {
        "title": "Protocol Pivot and Anchoring Bias",
        "framework_summary": [
            "Initial impressions should update when new findings change the highest-risk diagnosis.",
            "The pivot skill is recognizing when a new cue confirms, refutes, or reframes the working protocol.",
        ],
        "common_traps": [
            "Staying with the first protocol after a new high-risk finding appears.",
            "Treating a pivot as a failure instead of a normal part of reassessment.",
        ],
        "field_examples": [
            "COPD-like dyspnea plus sudden pulmonary edema signs should prompt CHF consideration.",
            "Chest pain with tearing back pain and pulse deficit should pivot away from simple ACS.",
        ],
        "related_game_ids": ["protocol_pivot"],
        "review_status": "draft",
    },
    "ref_vitals_trend_interpretation": {
        "title": "Vitals Trend Interpretation",
        "framework_summary": [
            "Trend interpretation is about the first meaningful change, not only the final abnormal value.",
            "Multiple channels moving in the wrong direction usually matter more than a single isolated number.",
        ],
        "common_traps": [
            "Calling a falling respiratory rate improvement when oxygenation is worsening.",
            "Waiting for hypotension before recognizing pediatric shock.",
        ],
        "field_examples": [
            "Rising HR and RR with falling SBP suggests compensation failing.",
            "Falling RR with falling SpO2 in asthma can mean fatigue and impending respiratory failure.",
        ],
        "related_game_ids": ["vitals_trend_spotter"],
        "review_status": "draft",
    },
    "ref_pat_doorway_impression": {
        "title": "PAT Doorway Impression",
        "framework_summary": [
            "PAT rapidly integrates appearance, work of breathing, and circulation to skin.",
            "The first look should determine urgency and immediate first actions.",
        ],
        "common_traps": [
            "Over-reassuring from normal color when appearance or work of breathing is abnormal.",
            "Ignoring quiet, limp, or non-interactive appearance because the child is not fighting care.",
        ],
        "field_examples": [
            "Inconsolable, non-interactive appearance is sick until proven otherwise.",
            "Retractions and nasal flaring should change respiratory priority before full vitals return.",
        ],
        "related_game_ids": ["pat"],
        "review_status": "draft",
    },
    "ref_shock_spotter_medical": {
        "title": "Medical Shock Recognition",
        "framework_summary": [
            "Recognize compensated shock from tachycardia, delayed perfusion, abnormal appearance, and narrowing pulse pressure before hypotension appears.",
            "Decompensated shock is suggested by hypotension, altered mentation, weak pulses, poor skin signs, or signs that compensation is failing.",
        ],
        "common_traps": [
            "Waiting for hypotension before treating pediatric shock as high risk.",
            "Calling a normal systolic blood pressure reassuring when perfusion and mental status are worsening.",
        ],
        "field_examples": [
            "Tachycardia, cool skin, delayed cap refill, and anxiety can be compensated shock in sepsis or dehydration.",
            "Lethargy with weak pulses and falling BP should trigger rapid transport, oxygenation/ventilation support, and protocol-directed fluid or ALS escalation.",
        ],
        "related_game_ids": ["shock_spotter_med"],
        "review_status": "draft",
    },
    "ref_ams_differential_dash": {
        "title": "AMS Differential Pattern Recognition",
        "framework_summary": [
            "Altered mental status is a finding, not a diagnosis; sort cues into reversible threats first.",
            "Prioritize glucose, oxygenation/ventilation, perfusion, toxins, trauma, infection, seizure, stroke, and temperature before calling AMS psychiatric.",
        ],
        "common_traps": [
            "Anchoring on opioids from miosis while missing hypoglycemia, organophosphates, or mixed ingestion.",
            "Skipping BGL, oxygenation, or trauma screening because the patient appears intoxicated or behavioral.",
        ],
        "field_examples": [
            "Diaphoresis, tremor, confusion, and insulin use should trigger an immediate glucose check.",
            "Fever, petechiae, photophobia, and neck stiffness should push infection/sepsis and rapid transport.",
        ],
        "related_game_ids": ["diff_dash_ams"],
        "review_status": "draft",
    },
    "ref_respiratory_differential_dash": {
        "title": "Respiratory Differential Pattern Recognition",
        "framework_summary": [
            "Respiratory distress differentials begin with airway level, work of breathing, lung sounds, oxygenation, exposure history, and fever/toxin clues.",
            "Match the finding pattern to the field action: bronchodilator, epinephrine, airway positioning, oxygenation/ventilation, suction, or rapid transport.",
        ],
        "common_traps": [
            "Calling every noisy respiratory sound wheezing and missing upper-airway obstruction.",
            "Treating clear lung sounds as reassurance when work of breathing or oxygenation is worsening.",
        ],
        "field_examples": [
            "Barking cough with inspiratory stridor points toward upper-airway croup physiology and avoiding agitation.",
            "Crackles with fever and focal findings should raise pneumonia/consolidation concerns, not simple bronchospasm.",
        ],
        "related_game_ids": ["diff_dash_resp"],
        "review_status": "draft",
    },
    "ref_moi_mapper": {
        "title": "Mechanism of Injury Mapping",
        "framework_summary": [
            "Mechanism of injury predicts hidden injury, assessment priority, spinal motion consideration, hemorrhage risk, and transport urgency.",
            "Use energy transfer, body region, age, restraint/protection, and symptom mismatch to decide what to look for next.",
        ],
        "common_traps": [
            "Calling a child stable because the first vitals are normal after a high-energy mechanism.",
            "Missing abdominal or thoracic injury after handlebar, lap-belt, or compression mechanisms.",
        ],
        "field_examples": [
            "Handlebar impact plus abdominal pain should raise suspicion for pancreatic or hollow-organ injury.",
            "Diving injury with neck pain should trigger spinal motion restriction and neurologic reassessment.",
        ],
        "related_game_ids": ["moi_mapper"],
        "review_status": "draft",
    },
    "ref_rule_of_nines": {
        "title": "Rule of Nines Burn Estimate",
        "framework_summary": [
            "Rule of Nines provides a rapid field estimate of burned body surface area: head/neck 9%, each arm 9%, anterior torso 18%, posterior torso 18%, each leg 18%, and perineum 1%.",
            "In children, body proportions differ; use this as an EMS estimate and refine with pediatric burn tools or burn-center consultation when available.",
        ],
        "common_traps": [
            "Treating percentage as the only transport driver and missing face, airway, hand, foot, genital, joint, or circumferential burns.",
            "Forgetting heat-loss prevention after the burning process has stopped.",
        ],
        "field_examples": [
            "Head/neck plus anterior torso equals 27%, but soot or facial burns should also trigger airway vigilance.",
            "Perineal burns may be only 1% TBSA but can require special-area escalation and careful mechanism documentation.",
        ],
        "related_game_ids": ["rule_of_nines"],
        "review_status": "draft",
    },
    "ref_shock_spotter_trauma": {
        "title": "Trauma Shock Recognition",
        "framework_summary": [
            "Trauma shock recognition combines mechanism, visible blood loss, skin signs, pulse quality, mentation, and blood pressure trend.",
            "Pediatric patients can compensate until sudden collapse; delayed cap refill and tachycardia matter before hypotension.",
        ],
        "common_traps": [
            "Waiting for hypotension before controlling hemorrhage or accelerating transport.",
            "Missing internal hemorrhage when external bleeding is minimal.",
        ],
        "field_examples": [
            "Femur deformity, tachycardia, pallor, and cool skin can represent significant blood loss even with preserved BP.",
            "Abdominal trauma with worsening lethargy and weak pulses should be treated as decompensated shock risk.",
        ],
        "related_game_ids": ["shock_spotter_trauma"],
        "review_status": "draft",
    },
    "ref_temperature_emergency_care": {
        "title": "Temperature Emergency Field Care",
        "framework_summary": [
            "Temperature emergencies require linking exposure, core temperature estimate, mental status, skin findings, and sepsis risk to the next priority.",
            "Treatment choices differ for mild hypothermia, severe hypothermia, heat exhaustion, heat stroke, fever/sepsis, and toxic exposure.",
        ],
        "common_traps": [
            "Actively cooling heat exhaustion like heat stroke without checking mental status and severity.",
            "Rough handling of severe hypothermia patients with dysrhythmia risk.",
        ],
        "field_examples": [
            "Confusion with hot skin after exertion points toward heat stroke and rapid cooling.",
            "Cold exposure with stopped shivering and bradycardia demands gentle handling, insulation, warming, and monitoring.",
        ],
        "related_game_ids": ["temp_check"],
        "review_status": "draft",
    },
    "ref_stop_the_bleed": {
        "title": "Hemorrhage-Control Escalation",
        "framework_summary": [
            "Hemorrhage control escalates from exposure/PPE and direct pressure to packing, pressure/hemostatic dressing, tourniquet when appropriate, reassessment, and rapid transport.",
            "Wound location determines the tool: extremity hemorrhage can receive a tourniquet; junctional wounds require packing and sustained pressure; torso wounds require wound-specific management and rapid transport.",
        ],
        "common_traps": [
            "Using a tourniquet for junctional or torso wounds where it cannot work.",
            "Failing to reassess bleeding, distal perfusion, and shock after the first intervention.",
        ],
        "field_examples": [
            "Groin hemorrhage should move from direct pressure to wound packing and sustained pressure.",
            "Traumatic partial amputation with pulsatile bleeding should trigger early tourniquet use and time documentation.",
        ],
        "related_game_ids": ["stop_the_bleed"],
        "review_status": "draft",
    },
    "ref_bls_sequence": {
        "title": "BLS Sequence",
        "framework_summary": [
            "BLS sequencing emphasizes rapid recognition, help/AED activation, high-quality CPR, brief rhythm-analysis pauses, shock when advised, and immediate CPR resumption.",
            "For pediatric two-rescuer CPR, 15:2 is expected until advanced-airway strategy changes the ventilation model.",
        ],
        "common_traps": [
            "Letting AED analysis or shock delivery create a prolonged pause.",
            "Using adult 30:2 logic for a two-rescuer pediatric arrest.",
        ],
        "field_examples": [
            "AED already present: pads and compressions can happen in parallel, but analysis requires stopping motion.",
            "No shock advised: resume CPR immediately and continue until the next AED analysis cycle.",
        ],
        "related_game_ids": ["bls_sequence"],
        "review_status": "draft",
    },
    "ref_priority_stack": {
        "title": "High-Acuity Priority Stack",
        "framework_summary": [
            "Rank priorities by immediate life threat: airway/ventilation failure, oxygenation, perfusion/shock, time-sensitive treatment, transport/ALS, then secondary assessment/history.",
            "A good priority stack changes as new findings arrive; it is not a static checklist.",
        ],
        "common_traps": [
            "Collecting detailed history while oxygenation, ventilation, or perfusion is failing.",
            "Treating secondary medications or comfort measures as first-line life-threat interventions.",
        ],
        "field_examples": [
            "Respiratory failure with bradycardia: ventilate first, then prepare for CPR if poor perfusion persists.",
            "Anaphylaxis with hypotension and wheeze: epinephrine is the first treatment priority, supported by airway and shock care.",
        ],
        "related_game_ids": ["priority_stack"],
        "review_status": "draft",
    },
    "ref_resp_dx_discriminators": {
        "title": "Respiratory Differential Discriminators",
        "framework_summary": [
            "Asthma, Croup, Epiglottitis, Anaphylaxis, and FBAO share overlapping sounds (wheeze, stridor) but separate on onset pattern, skin findings, and appearance.",
            "High-yield investigation: pick the one finding that eliminates the most alternatives — usually onset/mechanism, positioning, or skin findings.",
        ],
        "common_traps": [
            "Anchoring on bilateral wheeze as asthma when skin findings or allergen exposure point to anaphylaxis.",
            "Calling fever-plus-stridor epiglottitis when the child is crying and consolable — croup children are upset; epiglottitis children are toxic and still.",
            "Missing FBAO because gradual-onset findings emerge (unilateral wheeze, decreased air entry one side) when the choking episode was unwitnessed.",
        ],
        "field_examples": [
            "Tripod positioning, drooling, and muffled voice: do not examine the throat — transport immediately with airway backup.",
            "Bee sting plus throat tightness plus hypotension: epinephrine IM before albuterol, even if wheeze is the dominant sound.",
            "Sudden choking in a healthy child during eating: unilateral decreased air entry confirms aspiration into the right mainstem bronchus.",
        ],
        "related_game_ids": ["resp_dx_1q", "diff_dash_resp"],
        "review_status": "draft",
    },
    "ref_aha_cpr_guide": {
        "title": "AHA CPR & Resuscitation Guide",
        "framework_summary": [
            "High-quality CPR requires rate 100–120/min, depth ≥2 in (5 cm) for adults and at least 1/3 AP diameter for pediatrics, and full recoil between every compression.",
            "Compressions fraction (CCF) should exceed 80%: minimize all interruptions to < 10 seconds, including AED analysis pauses.",
            "C:V ratio is 30:2 for single rescuer at all ages and two-rescuer adult; switch to 15:2 for two-rescuer pediatric/infant. After advanced airway, deliver 1 breath every 6 seconds asynchronously.",
        ],
        "common_traps": [
            "Applying adult 30:2 ratio with a second rescuer in a pediatric arrest — it should be 15:2.",
            "Stopping compressions to apply AED pads; pads can be placed during ongoing CPR.",
            "Leaning on the chest during recoil — partial recoil reduces cardiac filling and coronary perfusion pressure.",
            "Long pre-shock and post-shock pauses — analysis and charge during CPR, deliver shock, resume immediately.",
        ],
        "field_examples": [
            "Infant cardiac arrest, two rescuers: two-thumb-encircling technique, 15:2, ≥1.5 in depth, brachial pulse check.",
            "EMS takes over from bystander CPR: assign roles before stopping — no full interruption to switch; accept ongoing compressions and integrate.",
            "Post-advanced-airway: provider delivers 1 breath every 6 sec while compressions continue uninterrupted.",
        ],
        "related_game_ids": ["cpr_bls_sequence", "cpr_bls_concepts"],
        "review_status": "draft",
    },
}


def _with_default_pass_threshold(metadata: dict[str, Any]) -> dict[str, Any]:
    item = deepcopy(metadata)
    item.setdefault("pass_threshold", deepcopy(DEFAULT_PASS_THRESHOLD))
    reference_card = item.get("reference_card")
    if isinstance(reference_card, dict):
        card_id = reference_card.get("id")
        if card_id in REFERENCE_CARD_CONTENT:
            reference_card.update(deepcopy(REFERENCE_CARD_CONTENT[card_id]))
    return item


def get_minigame_metadata(game_id: str) -> dict[str, Any] | None:
    item = MINIGAME_METADATA.get(game_id) or LEGACY_MINIGAME_METADATA.get(game_id)
    return _with_default_pass_threshold(item) if item else None


def get_allowed_minigame_ids() -> set[str]:
    """Generic result endpoint IDs backed by MinigameResult rows."""

    return set(MINIGAME_METADATA)


def get_minigame_display_name(game_id: str) -> str:
    metadata = get_minigame_metadata(game_id) or {}
    return str(metadata.get("display_name") or game_id)


def get_reference_card_catalog() -> dict[str, dict[str, Any]]:
    """Return unique reference-card definitions declared by game metadata."""

    catalog: dict[str, dict[str, Any]] = {}
    for game_id in sorted(set(MINIGAME_METADATA) | set(LEGACY_MINIGAME_METADATA)):
        metadata = get_minigame_metadata(game_id) or {}
        card = metadata.get("reference_card") or {}
        card_id = card.get("id")
        if card_id and card_id not in catalog:
            catalog[card_id] = deepcopy(card)
    return catalog


def get_reference_card_definition(card_id: str) -> dict[str, Any] | None:
    card = get_reference_card_catalog().get(card_id)
    return deepcopy(card) if card else None


def validate_minigame_metadata(
    allowed_game_ids: set[str] | None = None,
    registry: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Fail loudly when static game metadata is missing or malformed."""

    registry = registry if registry is not None else MINIGAME_METADATA
    allowed_game_ids = allowed_game_ids if allowed_game_ids is not None else set(registry)
    missing = sorted(set(allowed_game_ids) - set(registry))
    if missing:
        raise ValueError(f"Missing mini-game metadata for: {', '.join(missing)}")

    for game_id, raw_metadata in registry.items():
        metadata = _with_default_pass_threshold(raw_metadata)
        if not metadata.get("skill_tags"):
            raise ValueError(f"{game_id}: skill_tags is required")
        if not metadata.get("rubric_category_mapping"):
            raise ValueError(f"{game_id}: rubric_category_mapping is required")
        invalid_categories = sorted(set(metadata["rubric_category_mapping"]) - VALID_RUBRIC_CATEGORY_IDS)
        if invalid_categories:
            raise ValueError(
                f"{game_id}: invalid rubric_category_mapping values: {', '.join(invalid_categories)}"
            )
        threshold = metadata.get("pass_threshold") or {}
        score_gte = threshold.get("score_gte")
        if not isinstance(score_gte, int) or not 0 <= score_gte <= 100:
            raise ValueError(f"{game_id}: pass_threshold.score_gte must be an integer 0-100")
        if not metadata.get("hint_policy"):
            raise ValueError(f"{game_id}: hint_policy is required")
        reference_card = metadata.get("reference_card") or {}
        if not reference_card.get("id"):
            raise ValueError(f"{game_id}: reference_card.id is required")
        for field in ("title", "framework_summary", "common_traps", "field_examples", "related_game_ids", "review_status"):
            if not reference_card.get(field):
                raise ValueError(f"{game_id}: reference_card.{field} is required")
