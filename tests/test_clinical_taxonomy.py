import json
from pathlib import Path

from app.protocol_engine import (
    _PROTOCOL_EXCERPT_GENERIC_CONCEPTS,
    build_protocol_excerpt_preview,
)
from app.scenarios.vocabulary import (
    CLINICAL_CONCEPTS,
    INTERVENTION_ACTIONS,
    INTERVENTIONS,
    canonical_intervention_id,
    clinical_concept_label,
    intervention_action_label,
    intervention_ids_for_action,
    is_known_clinical_concept,
    is_known_intervention_action,
)

SCENARIOS_DIR = Path(__file__).resolve().parents[1] / "app" / "scenarios"


def test_phase2_clinical_concepts_cover_current_scenario_families():
    required = {
        "pediatric_respiratory_distress",
        "anaphylaxis",
        "hypoglycemia",
        "febrile_seizure",
        "syncope",
        "chest_pain_acs",
        "stemi",
        "toxins_overdose",
        "soft_tissue_injury",
        "foreign_body_airway_obstruction",
        "extremity_injury",
        "burns",
        "multisystem_trauma",
        "abdominal_trauma",
        "obstetric_emergency",
        "imminent_delivery",
        "neonatal_resuscitation",
        "postpartum_hemorrhage",
        "preeclampsia_eclampsia",
        "behavioral_psychiatric_crisis",
        "severe_agitation",
        "chemical_restraint",
        "sepsis",
        "infectious_disease_precautions",
        "cardiac_arrest",
        "stroke",
        "pulmonary_edema",
        "croup",
        "bradycardia",
        "tachycardia",
        "tension_pneumothorax",
        "hypothermia",
        "heat_illness",
        "frostbite",
        "interfacility_transfer",
        "quality_improvement_review",
    }

    assert required.issubset(CLINICAL_CONCEPTS)


def test_phase2_intervention_actions_reference_registered_ui_interventions():
    for action_id, action in INTERVENTION_ACTIONS.items():
        assert action.get("label"), action_id
        assert action.get("category"), action_id
        for intervention_id in intervention_ids_for_action(action_id):
            assert intervention_id in INTERVENTIONS, f"{action_id} references {intervention_id}"


def test_phase2_intervention_actions_include_sme_required_als_families():
    required = {
        "supraglottic_airway_insertion",
        "endotracheal_intubation",
        "cricothyrotomy",
        "intravenous_access_establish",
        "intraosseous_access_establish",
        "defibrillation_aed",
        "defibrillation_manual",
        "synchronized_cardioversion",
        "transcutaneous_pacing",
        "narcotic_analgesia_administer",
        "benzodiazepine_administer",
        "antiarrhythmic_administer",
        "cpr_initiate",
        "pulse_check",
        "aed_apply_use",
        "tourniquet_apply",
        "wound_packing_hemostatic",
        "supraglottic_airway_insert",
        "opa_insert",
        "npa_insert",
        "chest_seal_apply",
        "traction_splint_apply",
        "pat_perform",
    }

    assert required.issubset(INTERVENTION_ACTIONS)


def test_legacy_high_flow_oxygen_keys_collapse_to_canonical_intervention():
    assert canonical_intervention_id("high_flow_o2") == "o2_nrb"
    assert canonical_intervention_id("o2_nrb") == "o2_nrb"


def test_phase2_taxonomy_helpers_return_labels_and_known_state():
    assert is_known_clinical_concept("anaphylaxis") is True
    assert clinical_concept_label("anaphylaxis") == "Anaphylaxis"
    assert is_known_clinical_concept("made_up_concept") is False
    assert clinical_concept_label("made_up_concept") is None

    assert is_known_intervention_action("epinephrine_im_administer") is True
    assert intervention_action_label("epinephrine_im_administer") == "Administer IM epinephrine"
    assert "epinephrine_im" in intervention_ids_for_action("epinephrine_im_administer")
    assert is_known_intervention_action("made_up_action") is False
    assert intervention_action_label("made_up_action") is None
    assert intervention_ids_for_action("made_up_action") == []


def test_protocol_excerpt_generic_concepts_are_registered_in_taxonomy():
    """Keep protocol excerpt generic filtering tied to the clinical taxonomy.

    The blocklist is intentionally engine-owned because it controls base
    protocol excerpt selection, but every entry still needs to be a valid
    clinical concept ID.
    """
    missing = sorted(_PROTOCOL_EXCERPT_GENERIC_CONCEPTS - set(CLINICAL_CONCEPTS))

    assert missing == []


def test_current_ems_scenarios_have_valid_phase2_clinical_context_tags():
    scenario_paths = sorted(SCENARIOS_DIR.rglob("*.json"))
    assert scenario_paths

    missing_context = []
    unknown_concepts = {}

    for path in scenario_paths:
        scenario = json.loads(path.read_text(encoding="utf-8"))
        scenario_id = scenario.get("id") or path.stem
        context = scenario.get("clinical_context")
        if not isinstance(context, dict):
            missing_context.append(scenario_id)
            continue
        concepts = context.get("concepts", [])
        focus = context.get("protocol_focus", [])
        if not isinstance(concepts, list) or not concepts:
            missing_context.append(scenario_id)
            continue
        unknown = {
            item
            for item in [*concepts, *(focus if isinstance(focus, list) else [])]
            if item not in CLINICAL_CONCEPTS
        }
        if unknown:
            unknown_concepts[scenario_id] = unknown

    assert missing_context == []
    assert unknown_concepts == {}


def test_current_ems_scenarios_preview_matches_at_least_one_protocol():
    scenario_paths = sorted(SCENARIOS_DIR.rglob("*.json"))
    assert scenario_paths

    missing_matches = {}

    for path in scenario_paths:
        scenario = json.loads(path.read_text(encoding="utf-8"))
        scenario_id = scenario.get("id") or path.stem
        context = scenario.get("clinical_context") if isinstance(scenario, dict) else {}
        jurisdiction = str((context or {}).get("jurisdiction") or scenario.get("jurisdiction") or "MI")
        base_protocol_set = "NASEMSO" if jurisdiction.lower() in {"national", "nasemso"} else "MI"
        preview = build_protocol_excerpt_preview(base_protocol_set, scenario)
        if preview["warnings"] or not preview["protocol_ids"]:
            missing_matches[scenario_id] = {
                "base_protocol_set": base_protocol_set,
                "warnings": preview["warnings"],
                "concepts": preview["concepts"],
            }

    assert missing_matches == {}
