import json
import types
from pathlib import Path

from app.checklist import load_checklist
from app.protocol_engine import (
    _compiled_context_for_profile,
    action_ids_for_intervention,
    available_base_protocol_sets,
    build_protocol_excerpt_locked,
    build_protocol_excerpt_preview,
    get_all_protocols_for_base_set,
    get_all_protocols_for_mca,
    get_protocol_concepts,
    get_protocols_for_concepts,
    get_resolved_protocol,
    protocol_content_hash,
)
from app.scenario_engine import adapt_scenario_to_context, load_scenario
from app.scoring_service import adjudicate
from app.protocol_concept_index import PROTOCOL_CONCEPT_INDEX, unknown_index_concepts
from app.models import AgencyProtocolProfile, AgencyProtocolSelection, AgencySOP, SimSession

SCENARIOS_DIR = Path(__file__).resolve().parents[1] / "app" / "scenarios"
PROTOCOLS_DIR = Path(__file__).resolve().parents[1] / "app" / "protocols"


def _protocol_files_by_id() -> dict[str, Path]:
    files = {}
    for path in PROTOCOLS_DIR.rglob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("id"):
            files[data["id"]] = path
    return files


def test_resolver_accepts_legacy_path_refs_and_canonical_ids():
    by_path = get_resolved_protocol(None, "MI/04_OB_Pediatrics/04-5_respiratory_distress")
    by_id = get_resolved_protocol(None, by_path["id"])

    assert by_path["id"] == "mi_base_pediatric_respiratory_distress"
    assert by_id["id"] == by_path["id"]
    assert by_id["protocol_reference"] == by_path["protocol_reference"]


def test_draft_pediatric_trauma_protocol_refs_resolve():
    head_spine = get_resolved_protocol(None, "MI/02_Trauma_Environmental/02-3_head_spine_trauma")
    mandatory_reporting = get_resolved_protocol(
        None,
        "MI/02_Trauma_Environmental/02-9_child_abuse_mandatory_reporting",
    )

    assert head_spine["id"] == "mi_base_all_head_spine_trauma"
    assert mandatory_reporting["id"] == "mi_base_all_child_abuse_mandatory_reporting"
    assert "Head Injury" in head_spine["condition"]
    assert "Mandatory Reporting" in mandatory_reporting["condition"]


def test_mca_protocol_list_falls_back_to_state_base():
    protocols = get_all_protocols_for_mca(None, "mi_wmrmcc_kent")
    ids = {p.get("id") for p in protocols}

    assert "mi_base_scope_of_practice" in ids
    assert "mi_base_pediatric_respiratory_distress" in ids


def test_protocol_content_hash_is_deterministic_for_key_order():
    assert protocol_content_hash({"b": 1, "a": 2}) == protocol_content_hash({"a": 2, "b": 1})


def test_base_protocol_sets_expose_profile_seed_options():
    base_sets = {p["id"] for p in available_base_protocol_sets()}

    assert "MI" in base_sets
    assert "NASEMSO" in base_sets


def test_base_protocol_set_loader_supports_profile_compilation():
    protocols = get_all_protocols_for_base_set("MI")
    ids = {p.get("id") for p in protocols}

    assert "mi_base_scope_of_practice" in ids
    assert "mi_base_pediatric_respiratory_distress" in ids


def test_profile_selections_only_overlay_matching_mca_options():
    profile = AgencyProtocolProfile(
        id="profile-test",
        agency_id="agency-test",
        display_name="Kent County",
        base_protocol_set="MI",
        official_mca_id="mi_wmrmcc_kent",
    )
    selection = AgencyProtocolSelection(
        protocol_profile_id=profile.id,
        agency_id=profile.agency_id,
        mca_id=profile.official_mca_id,
        protocol_id="mi_base_medication_epinephrine_auto_injector_procedure",
        selection_id="epinephrine_auto_injector_mfr_authorization",
        selected_value="Authorized — MFR may administer epinephrine auto-injector per protocol criteria",
    )

    compiled = _compiled_context_for_profile(
        profile.agency_id,
        profile.official_mca_id,
        profile,
        [selection],
    )

    epi_options = compiled["protocols"]["mi_base_medication_epinephrine_auto_injector_procedure"]["mca_selections_required"]
    naloxone_options = compiled["protocols"]["mi_base_medication_naloxone_leave_behind_kit"]["mca_selections_required"]
    selection_meta = compiled["selections"][f"{selection.protocol_id}:{selection.selection_id}"]

    assert epi_options[0]["selected"] == selection.selected_value
    assert selection_meta["selected_value"] == selection.selected_value
    assert naloxone_options[0]["selected"] is None


def test_profile_selection_changes_compiled_snapshot_hash():
    profile = AgencyProtocolProfile(
        id="profile-test",
        agency_id="agency-test",
        display_name="Kent County",
        base_protocol_set="MI",
        official_mca_id="mi_wmrmcc_kent",
    )
    baseline = _compiled_context_for_profile(
        profile.agency_id,
        profile.official_mca_id,
        profile,
        [],
    )
    selected = _compiled_context_for_profile(
        profile.agency_id,
        profile.official_mca_id,
        profile,
        [
            AgencyProtocolSelection(
                protocol_profile_id=profile.id,
                agency_id=profile.agency_id,
                mca_id=profile.official_mca_id,
                protocol_id="mi_base_medication_epinephrine_auto_injector_procedure",
                selection_id="epinephrine_auto_injector_mfr_authorization",
                selected_value="Authorized — MFR may administer epinephrine auto-injector per protocol criteria",
            )
        ],
    )

    assert protocol_content_hash(baseline) != protocol_content_hash(selected)


def test_phase2a_sop_scaffold_is_non_authoritative_storage_only():
    columns = AgencySOP.__table__.columns
    constraints = {constraint.name for constraint in AgencySOP.__table__.constraints}

    assert "clinical_concept_tags" in columns
    assert "intervention_action_ids" in columns
    assert "patch_operations" in columns
    assert "sme_review_status" in columns
    assert AgencySOP.__table__.columns["status"].default.arg == "draft"
    assert AgencySOP.__table__.columns["sme_review_status"].default.arg == "pending"
    assert "ck_agency_sops_no_self_approval" in constraints


def test_phase2a_session_audit_columns_exist_without_runtime_authority():
    columns = SimSession.__table__.columns

    assert "active_sop_ids" in columns
    assert "effective_protocol_excerpt" in columns
    assert "debrief_markdown" in columns


def test_static_protocol_concept_index_references_known_concepts():
    assert unknown_index_concepts() == {}


def test_static_protocol_concept_index_references_existing_protocols():
    known_ids = {p["id"] for p in get_all_protocols_for_base_set("MI")}
    known_ids.update(p["id"] for p in get_all_protocols_for_base_set("NASEMSO"))

    missing = set(PROTOCOL_CONCEPT_INDEX) - known_ids
    assert missing == set()


def test_indexed_protocol_files_carry_initial_pending_clinical_context_tags():
    files_by_id = _protocol_files_by_id()
    missing_or_drifted = {}

    for protocol_id, indexed_concepts in PROTOCOL_CONCEPT_INDEX.items():
        path = files_by_id.get(protocol_id)
        if not path:
            missing_or_drifted[protocol_id] = {"error": "missing protocol file"}
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        context = data.get("clinical_context")
        if not isinstance(context, dict):
            missing_or_drifted[protocol_id] = {"error": "missing clinical_context"}
            continue
        if context.get("concepts") != sorted(indexed_concepts):
            missing_or_drifted[protocol_id] = {
                "error": "concept drift",
                "expected": sorted(indexed_concepts),
                "actual": context.get("concepts"),
            }
            continue
        if context.get("tag_source") != "initial_static_mapping":
            missing_or_drifted[protocol_id] = {"error": "unexpected tag_source"}
            continue
        if context.get("sme_review_status") != "pending":
            missing_or_drifted[protocol_id] = {"error": "unexpected sme_review_status"}

    assert missing_or_drifted == {}


def test_protocol_concepts_expose_static_index_entries():
    concepts = get_protocol_concepts("mi_base_pediatric_respiratory_distress")

    assert "pediatric_respiratory_distress" in concepts
    assert "oxygen_therapy" in concepts


def test_get_protocols_for_concepts_filters_base_set():
    protocols = get_protocols_for_concepts(
        "MI",
        ["pediatric_respiratory_distress", "upper_airway_obstruction", "airway_management"],
    )
    ids = {p["id"] for p in protocols}

    assert "mi_base_pediatric_respiratory_distress" in ids
    assert "mi_base_procedure_airway_management" in ids
    assert "nasemso_base_pediatric_pediatric_respiratory_distress_croup" not in ids


def test_sme_required_protocol_mapping_corrections_are_preserved():
    abdominal = get_protocol_concepts("mi_base_all_abdominal_pain")
    fbao = get_protocol_concepts("mi_base_all_fbao")
    etco2 = get_protocol_concepts("mi_base_procedure_etco2_monitoring")

    assert abdominal == ["patient_assessment", "transport_decision", "vital_signs"]
    assert "abdominal_trauma" not in abdominal
    assert "pediatric_patient" not in fbao
    assert "cardiac_monitoring" not in etco2
    assert "cardiac_arrest" in etco2


def test_protocol_excerpt_preview_uses_scenario_clinical_context_without_authority():
    scenario = json.loads(
        (SCENARIOS_DIR / "pediatric" / "medical" / "peds_anaphylaxis_01.json").read_text(
            encoding="utf-8"
        )
    )

    excerpt = build_protocol_excerpt_preview("MI", scenario)

    assert excerpt["schema"] == "protocol_excerpt_preview_v1"
    assert excerpt["authoritative"] is False
    assert excerpt["scenario_id"] == "peds_anaphylaxis_01"
    assert "anaphylaxis" in excerpt["concepts"]
    assert "mi_base_all_anaphylaxis" in excerpt["protocol_ids"]
    assert "mi_base_medication_ref_epinephrine" in excerpt["protocol_ids"]
    assert "anaphylaxis" in excerpt["protocols"]["mi_base_all_anaphylaxis"]["matched_concepts"]
    assert "anaphylaxis" in excerpt["protocols"]["mi_base_all_anaphylaxis"]["static_index_concepts"]
    assert excerpt["warnings"] == []


def test_protocol_excerpt_preview_warns_without_clinical_context():
    excerpt = build_protocol_excerpt_preview("MI", {"id": "untagged"})

    assert excerpt["authoritative"] is False
    assert excerpt["protocol_ids"] == []
    assert excerpt["warnings"] == ["scenario clinical_context is missing"]


def test_phase2b_action_id_lookup_maps_ui_interventions_without_scope_authority():
    assert action_ids_for_intervention("epinephrine_im") == ["epinephrine_im_administer"]
    assert action_ids_for_intervention("epi_draw_up") == ["epinephrine_im_administer"]
    assert action_ids_for_intervention("high_flow_o2") == ["oxygen_high_flow_nrb"]
    assert action_ids_for_intervention("o2_nrb") == ["oxygen_high_flow_nrb"]
    assert action_ids_for_intervention("not_a_real_intervention") == []


def test_phase2b_locked_excerpt_filters_protocols_and_reviewed_sops_without_authority():
    scenario = json.loads(
        (SCENARIOS_DIR / "pediatric" / "medical" / "peds_anaphylaxis_01.json").read_text(
            encoding="utf-8"
        )
    )
    profile = AgencyProtocolProfile(
        id="profile-test",
        agency_id="agency-test",
        display_name="Kent County",
        base_protocol_set="MI",
        official_mca_id="mi_wmrmcc_kent",
    )
    compiled = _compiled_context_for_profile(
        profile.agency_id,
        profile.official_mca_id,
        profile,
        [],
    )
    matching_sop = AgencySOP(
        id="sop-matching",
        agency_id=profile.agency_id,
        protocol_profile_id=profile.id,
        version_id="sop-matching-v1",
        rule_type="clarification",
        extracted_rule="Use the local pediatric epinephrine dosing card.",
        status="reviewed_non_authoritative",
        sme_review_status="pending",
        clinical_concept_tags=["anaphylaxis", "pediatric_patient"],
        intervention_action_ids=["epinephrine_im_administer"],
    )
    draft_sop = AgencySOP(
        id="sop-draft",
        agency_id=profile.agency_id,
        protocol_profile_id=profile.id,
        version_id="sop-draft-v1",
        rule_type="clarification",
        extracted_rule="Draft only.",
        status="draft",
        sme_review_status="pending",
        clinical_concept_tags=["anaphylaxis"],
        intervention_action_ids=["epinephrine_im_administer"],
    )

    excerpt = build_protocol_excerpt_locked(compiled, scenario, sops=[matching_sop, draft_sop])

    assert excerpt["schema"] == "protocol_excerpt_locked_v1"
    assert excerpt["authoritative"] is False
    assert excerpt["authority_blocked"] is True
    assert "mi_base_all_anaphylaxis" in excerpt["protocol_ids"]
    assert excerpt["sop_ids"] == ["sop-matching"]
    assert excerpt["sops"][0]["matched_concepts"] == ["anaphylaxis", "pediatric_patient"]
    assert excerpt["warnings"] == []


def test_locked_excerpt_uses_protocol_focus_instead_of_generic_support_tags():
    scenario = json.loads(
        (SCENARIOS_DIR / "pediatric" / "medical" / "peds_croup_01.json").read_text(
            encoding="utf-8"
        )
    )
    profile = AgencyProtocolProfile(
        id="profile-test",
        agency_id="agency-test",
        display_name="Kent County",
        base_protocol_set="MI",
        official_mca_id="mi_wmrmcc_kent",
    )
    compiled = _compiled_context_for_profile(
        profile.agency_id,
        profile.official_mca_id,
        profile,
        [],
    )

    excerpt = build_protocol_excerpt_locked(compiled, scenario)

    assert excerpt["warnings"] == []
    assert excerpt["protocol_match_concepts"] == ["croup", "upper_airway_obstruction"]
    assert "mi_base_pediatric_respiratory_distress" in excerpt["protocol_ids"]
    assert "mi_base_medication_ref_racepinephrine" in excerpt["protocol_ids"]
    assert "mi_base_all_anaphylaxis" not in excerpt["protocol_ids"]
    assert "mi_base_all_burns" not in excerpt["protocol_ids"]
    assert "mi_base_all_opioid_overdose" not in excerpt["protocol_ids"]
    assert "mi_base_pediatric_seizures" not in excerpt["protocol_ids"]


def test_phase2b_locked_excerpt_refuses_authoritative_mode_without_runtime_gate():
    scenario = json.loads(
        (SCENARIOS_DIR / "pediatric" / "medical" / "peds_anaphylaxis_01.json").read_text(
            encoding="utf-8"
        )
    )
    compiled = _compiled_context_for_profile(
        "agency-test",
        "mi_wmrmcc_kent",
        AgencyProtocolProfile(
            id="profile-test",
            agency_id="agency-test",
            display_name="Kent County",
            base_protocol_set="MI",
            official_mca_id="mi_wmrmcc_kent",
        ),
        [],
    )

    try:
        build_protocol_excerpt_locked(compiled, scenario, authoritative=True)
    except ValueError as exc:
        assert "Phase 2B runtime use" in str(exc)
    else:
        raise AssertionError("authoritative protocol excerpts should remain locked")


def test_phase2b_authoritative_excerpt_includes_only_active_sops_when_enabled():
    scenario = json.loads(
        (SCENARIOS_DIR / "pediatric" / "medical" / "peds_anaphylaxis_01.json").read_text(
            encoding="utf-8"
        )
    )
    profile = AgencyProtocolProfile(
        id="profile-test",
        agency_id="agency-test",
        display_name="Kent County",
        base_protocol_set="MI",
        official_mca_id="mi_wmrmcc_kent",
    )
    compiled = _compiled_context_for_profile(
        profile.agency_id,
        profile.official_mca_id,
        profile,
        [],
    )
    active_sop = AgencySOP(
        id="sop-active",
        agency_id=profile.agency_id,
        protocol_profile_id=profile.id,
        version_id="sop-active-v1",
        rule_type="scope_restriction",
        extracted_rule="Local protocol requires medical control contact before IM epinephrine repeat dosing.",
        status="active",
        sme_review_status="approved",
        clinical_concept_tags=["anaphylaxis", "pediatric_patient"],
        intervention_action_ids=["epinephrine_im_administer"],
    )
    reviewed_sop = AgencySOP(
        id="sop-reviewed",
        agency_id=profile.agency_id,
        protocol_profile_id=profile.id,
        version_id="sop-reviewed-v1",
        rule_type="clarification",
        extracted_rule="Reviewed but not yet active.",
        status="reviewed_non_authoritative",
        sme_review_status="approved",
        clinical_concept_tags=["anaphylaxis"],
        intervention_action_ids=["epinephrine_im_administer"],
    )

    excerpt = build_protocol_excerpt_locked(
        compiled,
        scenario,
        sops=[active_sop, reviewed_sop],
        authoritative=True,
        allow_authoritative=True,
    )

    assert excerpt["authoritative"] is True
    assert excerpt["authority_blocked"] is False
    assert excerpt["sop_ids"] == ["sop-active"]
    assert excerpt["sops"][0]["rule_type"] == "scope_restriction"
    assert excerpt["sops"][0]["matched_concepts"] == ["anaphylaxis", "pediatric_patient"]


def test_phase2b_active_scope_sop_generates_deterministic_checklist_overlay():
    scenario = load_scenario("peds_anaphylaxis_01")
    excerpt = {
        "schema": "protocol_excerpt_locked_v1",
        "authoritative": True,
        "sop_ids": ["sop-epi-restrict"],
        "sops": [{
            "id": "sop-epi-restrict",
            "rule_type": "scope_restriction",
            "rule_text": "EMTs must not administer IM epinephrine without the local expansion.",
            "intervention_action_ids": ["epinephrine_im_administer"],
            "metadata_json": {"point_value": 6, "applicable_levels": ["EMT"]},
        }],
    }

    adapted = adapt_scenario_to_context(scenario, {}, "mi_wmrmcc_kent", excerpt)
    checklist = load_checklist(adapted, level="EMT", mca="mi_wmrmcc_kent", agency_id="agency-test")
    overlay_items = [item for item in checklist if item.provenance == "protocol_scope"]

    assert len(overlay_items) == 1
    overlay = overlay_items[0]
    assert overlay.category == "scope_adherence"
    assert overlay.point_value == 6
    assert overlay.tier1_match.absence_intervention_key == "epinephrine_im"

    clean_states = adjudicate(
        [overlay],
        interventions=[],
        session_findings=[],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=adapted,
        legacy_ai_categories=frozenset(),
    )
    violated_states = adjudicate(
        [overlay],
        interventions=[types.SimpleNamespace(id="iv-1", name="epinephrine_im", applied_at=None)],
        session_findings=[],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=adapted,
        legacy_ai_categories=frozenset(),
    )

    assert clean_states[0].state == "satisfied"
    assert clean_states[0].earned_points == 6
    assert violated_states[0].state == "not_satisfied"
    assert violated_states[0].earned_points == 0


def test_phase2b_active_contraindication_sop_scores_protocols_treatment_overlay():
    scenario = load_scenario("peds_anaphylaxis_01")
    excerpt = {
        "schema": "protocol_excerpt_locked_v1",
        "authoritative": True,
        "sop_ids": ["sop-albuterol-contra"],
        "sops": [{
            "id": "sop-albuterol-contra",
            "rule_type": "contraindication",
            "rule_text": "Albuterol is contraindicated for this local anaphylaxis pathway unless bronchospasm is present.",
            "intervention_action_ids": ["albuterol_administer"],
            "metadata_json": {"point_value": 4},
        }],
    }

    adapted = adapt_scenario_to_context(scenario, {}, "mi_wmrmcc_kent", excerpt)
    checklist = load_checklist(adapted, level="EMT", mca="mi_wmrmcc_kent", agency_id="agency-test")
    overlay_items = [item for item in checklist if item.provenance == "protocol_scope"]

    assert len(overlay_items) == 1
    overlay = overlay_items[0]
    assert overlay.category == "protocols_treatment"
    assert overlay.point_value == 4
    assert "contraindicated" in overlay.description.lower()
    assert overlay.tier1_match.absence_intervention_key == "albuterol_svn"

    violated_states = adjudicate(
        [overlay],
        interventions=[types.SimpleNamespace(id="iv-1", name="albuterol_svn", applied_at=None)],
        session_findings=[],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=adapted,
        legacy_ai_categories=frozenset(),
    )

    assert violated_states[0].state == "not_satisfied"
    assert violated_states[0].earned_points == 0


def test_phase2b_active_not_carried_sop_scores_protocols_treatment_overlay():
    scenario = load_scenario("peds_asthma_01")
    excerpt = {
        "schema": "protocol_excerpt_locked_v1",
        "authoritative": True,
        "sop_ids": ["sop-cpap-not-carried"],
        "sops": [{
            "id": "sop-cpap-not-carried",
            "rule_type": "not_carried",
            "rule_text": "This agency does not carry CPAP on BLS units.",
            "intervention_action_ids": ["cpap_apply"],
            "metadata_json": {"point_value": 3},
        }],
    }

    adapted = adapt_scenario_to_context(scenario, {}, "mi_wmrmcc_kent", excerpt)
    checklist = load_checklist(adapted, level="EMT", mca="mi_wmrmcc_kent", agency_id="agency-test")
    overlay_items = [item for item in checklist if item.provenance == "protocol_scope"]

    assert len(overlay_items) == 1
    overlay = overlay_items[0]
    assert overlay.category == "protocols_treatment"
    assert overlay.point_value == 3
    assert "unavailable/not-carried" in overlay.description
    assert overlay.tier1_match.absence_intervention_key == "cpap"

    clean_states = adjudicate(
        [overlay],
        interventions=[],
        session_findings=[],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=adapted,
        legacy_ai_categories=frozenset(),
    )
    violated_states = adjudicate(
        [overlay],
        interventions=[types.SimpleNamespace(id="iv-1", name="cpap", applied_at=None)],
        session_findings=[],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=adapted,
        legacy_ai_categories=frozenset(),
    )

    assert clean_states[0].state == "satisfied"
    assert clean_states[0].earned_points == 3
    assert violated_states[0].state == "not_satisfied"
    assert violated_states[0].earned_points == 0
