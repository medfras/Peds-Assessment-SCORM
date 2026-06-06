"""Static protocol-to-clinical-concept index for Phase 2 pilot tree-shaking.

This is the deliberately boring bridge between untagged protocol JSON files and
the Phase 2 clinical concept taxonomy. It avoids mass-editing protocol files
before the tagging contract has been validated with real scenarios.
"""

from __future__ import annotations

from app.scenarios.vocabulary import CLINICAL_CONCEPTS


PROTOCOL_CONCEPT_INDEX: dict[str, frozenset[str]] = {
    # Michigan universal/procedure protocols
    "mi_base_scope_of_practice": frozenset({"medical_control"}),
    "mi_base_system_interfacility_patient_transfers": frozenset({
        "interfacility_transfer", "transport_decision", "medical_control",
        "documentation_handoff",
    }),
    "mi_base_system_enhanced_paramedic_critical_care_interfacility": frozenset({
        "interfacility_transfer", "medical_control", "documentation_handoff",
    }),
    "mi_base_system_quality_improvement_program": frozenset({
        "quality_improvement_review", "documentation_handoff", "medical_control",
    }),
    "mi_base_system_protocol_deviation": frozenset({
        "quality_improvement_review", "medical_control", "documentation_handoff",
    }),
    "mi_base_all_general_prehospital_care": frozenset({
        "scene_safety", "ppe_precautions", "primary_survey", "patient_assessment",
        "vital_signs", "transport_decision", "medical_control",
    }),
    "mi_base_procedure_patient_assessment": frozenset({
        "primary_survey", "patient_assessment", "vital_signs", "documentation_handoff",
    }),
    "mi_base_procedure_airway_management": frozenset({
        "airway_management", "ventilation_support", "oxygen_therapy",
    }),
    "mi_base_procedure_oxygen_administration": frozenset({"oxygen_therapy"}),
    "mi_base_procedure_cpap_administration": frozenset({
        "respiratory_distress", "pulmonary_edema", "ventilation_support", "oxygen_therapy",
    }),
    "mi_base_procedure_etco2_monitoring": frozenset({
        "airway_management", "ventilation_support", "cardiac_arrest",
    }),
    "mi_base_procedure_twelve_lead_ecg": frozenset({
        "chest_pain_acs", "stemi", "cardiac_monitoring", "syncope",
    }),
    "mi_base_procedure_blood_glucose_testing": frozenset({
        "blood_glucose", "hypoglycemia", "altered_mental_status",
    }),
    "mi_base_procedure_spinal_precautions": frozenset({
        "spinal_motion_restriction", "trauma", "pediatric_trauma",
    }),
    # Michigan medical/cardiac/pediatric protocols
    "mi_base_pediatric_respiratory_distress": frozenset({
        "pediatric_patient", "pediatric_respiratory_distress", "respiratory_distress",
        "bronchospasm", "croup", "upper_airway_obstruction", "oxygen_therapy",
        "airway_management", "ventilation_support",
    }),
    "mi_base_all_fbao": frozenset({
        "foreign_body_airway_obstruction", "airway_management",
        "upper_airway_obstruction",
    }),
    "mi_base_all_anaphylaxis": frozenset({
        "anaphylaxis", "allergic_reaction", "shock", "airway_management",
        "oxygen_therapy",
    }),
    "mi_base_all_syncope": frozenset({
        "syncope", "cardiac_monitoring", "blood_glucose", "transport_decision",
    }),
    "mi_base_pediatric_altered_mental_status": frozenset({
        "pediatric_patient", "altered_mental_status", "hypoglycemia",
        "blood_glucose", "toxins_overdose", "seizure",
    }),
    "mi_base_pediatric_fever": frozenset({
        "pediatric_patient", "febrile_seizure", "seizure",
    }),
    "mi_base_pediatric_seizures": frozenset({
        "pediatric_patient", "seizure", "febrile_seizure",
    }),
    "mi_base_all_opioid_overdose": frozenset({
        "opioid_overdose", "toxins_overdose", "altered_mental_status",
        "ventilation_support", "airway_management",
    }),
    "mi_base_all_poisoning_overdose": frozenset({
        "toxins_overdose", "opioid_overdose", "altered_mental_status",
    }),
    "mi_base_adult_chest_pain_acs": frozenset({
        "chest_pain_acs", "stemi", "cardiac_monitoring", "transport_decision", "medical_control",
    }),
    "mi_base_adult_respiratory_distress": frozenset({
        "respiratory_distress", "bronchospasm", "pulmonary_edema", "oxygen_therapy",
        "ventilation_support", "airway_management",
    }),
    "mi_base_adult_altered_mental_status": frozenset({
        "altered_mental_status", "hypoglycemia", "blood_glucose",
        "toxins_overdose", "seizure",
    }),
    "mi_base_adult_seizures": frozenset({"seizure", "altered_mental_status"}),
    "mi_base_all_shock": frozenset({"shock", "vital_signs", "transport_decision"}),
    # Michigan trauma/environmental protocols
    "mi_base_all_general_trauma": frozenset({
        "trauma", "pediatric_trauma", "multisystem_trauma", "transport_decision",
        "hypothermia_prevention", "hypothermia",
    }),
    "mi_base_all_trauma_triage": frozenset({
        "trauma", "multisystem_trauma", "transport_decision",
    }),
    "mi_base_all_bleeding_control": frozenset({
        "bleeding_control", "trauma", "shock",
    }),
    "mi_base_all_soft_tissue_orthopedic": frozenset({
        "soft_tissue_injury", "extremity_injury", "fracture_splinting",
        "bleeding_control", "trauma",
    }),
    "mi_base_all_burns": frozenset({
        "burns", "trauma", "airway_management", "hypothermia_prevention", "hypothermia", "heat_exposure",
    }),
    "mi_base_all_head_injury_tbi": frozenset({
        "head_injury", "trauma", "spinal_motion_restriction",
    }),
    "mi_base_all_spinal_injury": frozenset({
        "spinal_motion_restriction", "trauma", "pediatric_trauma",
    }),
    "mi_base_all_abdominal_pain": frozenset({
        "patient_assessment", "vital_signs", "transport_decision",
    }),
    "mi_base_all_heat_emergencies": frozenset({"heat_illness", "heat_exposure", "vital_signs"}),
    "mi_base_all_hypothermia_frostbite": frozenset({
        "hypothermia", "frostbite", "hypothermia_prevention", "vital_signs",
    }),
    # Michigan medication references commonly needed in excerpts
    "mi_base_medication_ref_albuterol": frozenset({"bronchospasm", "respiratory_distress"}),
    "mi_base_medication_ref_racepinephrine": frozenset({
        "croup", "upper_airway_obstruction", "pediatric_respiratory_distress",
    }),
    "mi_base_medication_ref_epinephrine": frozenset({
        "anaphylaxis", "allergic_reaction", "shock",
        "pediatric_respiratory_distress",
    }),
    "mi_base_medication_epinephrine_auto_injector_procedure": frozenset({
        "anaphylaxis", "allergic_reaction", "pediatric_respiratory_distress",
    }),
    "mi_base_medication_ref_naloxone": frozenset({"opioid_overdose", "toxins_overdose"}),
    "mi_base_medication_naloxone_leave_behind_kit": frozenset({
        "opioid_overdose", "toxins_overdose",
    }),
    "mi_base_medication_ref_oral_glucose": frozenset({"hypoglycemia", "blood_glucose"}),
    "mi_base_medication_ref_glucagon": frozenset({"hypoglycemia", "blood_glucose"}),
    "mi_base_medication_ref_dextrose": frozenset({"hypoglycemia", "blood_glucose"}),
    "mi_base_medication_ref_aspirin": frozenset({"chest_pain_acs", "stemi"}),
    "mi_base_medication_ref_nitroglycerin": frozenset({"chest_pain_acs", "stemi"}),
    "mi_base_medication_ref_ondansetron": frozenset({"documentation_handoff"}),
    "mi_base_medication_ref_fentanyl": frozenset({"fracture_splinting", "burns", "trauma"}),
    "mi_base_medication_ref_morphine": frozenset({"fracture_splinting", "burns", "trauma"}),
    # NASEMSO universal/procedure-like protocols
    "nasemso_base_scope_of_practice": frozenset({"medical_control"}),
    "nasemso_base_universal_care_universal_care_guideline": frozenset({
        "scene_safety", "ppe_precautions", "primary_survey", "patient_assessment",
        "vital_signs", "transport_decision", "medical_control",
    }),
    "nasemso_base_respiratory_airway_management": frozenset({
        "airway_management", "oxygen_therapy", "ventilation_support",
        "respiratory_distress", "foreign_body_airway_obstruction",
    }),
    "nasemso_base_respiratory_respiratory_distress_includes_bronchospasm_pulmona": frozenset({
        "respiratory_distress", "bronchospasm", "pulmonary_edema", "oxygen_therapy",
        "ventilation_support", "airway_management",
    }),
    "nasemso_base_pediatric_pediatric_respiratory_distress_bronchiolitis": frozenset({
        "pediatric_patient", "pediatric_respiratory_distress", "respiratory_distress",
        "bronchospasm", "oxygen_therapy",
    }),
    "nasemso_base_pediatric_pediatric_respiratory_distress_croup": frozenset({
        "pediatric_patient", "pediatric_respiratory_distress",
        "croup", "upper_airway_obstruction", "oxygen_therapy",
    }),
    "nasemso_base_general_medical_anaphylaxis_and_allergic_reaction": frozenset({
        "anaphylaxis", "allergic_reaction", "shock", "airway_management",
    }),
    "nasemso_base_general_medical_hypoglycemia": frozenset({
        "hypoglycemia", "blood_glucose", "altered_mental_status",
    }),
    "nasemso_base_general_medical_altered_mental_status": frozenset({
        "altered_mental_status", "hypoglycemia", "blood_glucose",
        "toxins_overdose", "seizure",
    }),
    "nasemso_base_general_medical_seizures": frozenset({"seizure", "altered_mental_status"}),
    "nasemso_base_cardiovascular_adult_and_pediatric_syncope_and_near_syncope": frozenset({
        "syncope", "cardiac_monitoring", "blood_glucose",
    }),
    "nasemso_base_cardiovascular_chest_pain_acute_coronary_syndrome_acs_st_segment_": frozenset({
        "chest_pain_acs", "stemi", "cardiac_monitoring",
    }),
    "nasemso_base_toxins_and_environmental_opioid_poisoning_overdose": frozenset({
        "opioid_overdose", "toxins_overdose", "altered_mental_status",
        "ventilation_support",
    }),
    "nasemso_base_toxins_and_environmental_poisoning_overdose_universal_care": frozenset({
        "toxins_overdose", "opioid_overdose", "altered_mental_status",
    }),
    "nasemso_base_trauma_general_trauma_management": frozenset({
        "trauma", "pediatric_trauma", "multisystem_trauma",
        "hypothermia_prevention", "hypothermia", "transport_decision",
    }),
    "nasemso_base_trauma_extremity_trauma_external_hemorrhage_management": frozenset({
        "extremity_injury", "fracture_splinting", "bleeding_control",
        "trauma", "shock",
    }),
    "nasemso_base_trauma_burns": frozenset({
        "burns", "trauma", "airway_management", "hypothermia_prevention", "hypothermia", "heat_exposure",
    }),
    "nasemso_base_trauma_head_injury": frozenset({
        "head_injury", "trauma", "spinal_motion_restriction",
    }),
    "nasemso_base_trauma_spinal_care": frozenset({
        "spinal_motion_restriction", "trauma", "pediatric_trauma",
    }),
}


def protocol_concepts(protocol_id: str) -> frozenset[str]:
    """Return clinical concept IDs mapped to a protocol ID."""
    return PROTOCOL_CONCEPT_INDEX.get(protocol_id, frozenset())


def protocol_ids_for_concepts(concepts: set[str] | frozenset[str] | list[str] | tuple[str, ...]) -> set[str]:
    """Return protocol IDs mapped to any of the supplied clinical concept IDs."""
    concept_set = {str(c) for c in concepts if str(c)}
    return {
        protocol_id
        for protocol_id, mapped_concepts in PROTOCOL_CONCEPT_INDEX.items()
        if mapped_concepts.intersection(concept_set)
    }


def unknown_index_concepts() -> dict[str, set[str]]:
    """Return any index entries referencing concepts not in CLINICAL_CONCEPTS."""
    known = set(CLINICAL_CONCEPTS)
    return {
        protocol_id: set(concepts) - known
        for protocol_id, concepts in PROTOCOL_CONCEPT_INDEX.items()
        if set(concepts) - known
    }
