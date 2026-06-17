"""
Unit tests for the E3 deterministic debrief renderer functions:
  _compose_scored_section()  — per-item feedback block from adjudicated states
  _compose_reference_section() — authored condition/treatment reference block

No database or LLM dependencies required.
"""

from __future__ import annotations

import types

import pytest

from app.ai_client import (
    _assemble_fixed_debrief,
    _compose_case_study_guardrails,
    _compose_scored_section,
    _compose_reference_section,
    _conservative_dmist_floor,
    _ensure_narrative_feedback_section,
    _estimate_dmist_component_presence,
    _render_dmist_component_summary,
    _replace_protocols_section_with_rendered_block,
    _reorder_debrief_main_sections,
    _sanitize_credited_item_contradictions,
    _sanitize_missed_item_overcredit,
    _strip_orphan_improvement_headings,
    _strip_redundant_clinical_wrapper,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_session(
    definitions: list[dict],
    item_states: list[dict],
    score_snapshot: dict | None = None,
) -> types.SimpleNamespace:
    """Build a minimal session-like object for renderer tests."""
    return types.SimpleNamespace(
        checklist_states={
            "checklist_definitions": definitions,
            "item_states": item_states,
        },
        score_snapshot=score_snapshot or {
            "categories": {
                "clinical_performance": {"total": 8, "max": 10},
                "protocols_treatment": {"total": 6, "max": 10},
            }
        },
    )


def _def(
    item_id: str,
    description: str = "Did the thing",
    category: str = "clinical_performance",
    point_value: int = 2,
    done_feedback: str | None = None,
    missed_feedback: str | None = None,
    clinical_rationale: str | None = None,
    common_error: str | None = None,
    required: str = "required",
) -> dict:
    return {
        "id": item_id,
        "description": description,
        "category": category,
        "point_value": point_value,
        "required": required,
        "done_feedback": done_feedback,
        "missed_feedback": missed_feedback,
        "clinical_rationale": clinical_rationale,
        "common_error": common_error,
    }


def _state(item_id: str, status: str, earned: int = 0, notes: str | None = None) -> dict:
    state = {"item_id": item_id, "state": status, "earned_points": earned}
    if notes:
        state["notes"] = notes
    return state


# ── _compose_scored_section ───────────────────────────────────────────────────

class TestComposeScoredSection:
    def test_all_credited(self):
        defs = [
            _def("cp.ppe", "PPE", done_feedback="Gloves and eye protection donned."),
            _def("cp.primary_survey", "Primary survey", done_feedback="Survey completed."),
        ]
        states = [
            _state("cp.ppe", "satisfied", earned=2),
            _state("cp.primary_survey", "satisfied", earned=2),
        ]
        session = _make_session(defs, states)
        result = _compose_scored_section(session, "clinical_performance")

        assert "## What Went Well" in result
        assert "Gloves and eye protection donned." not in result
        assert "Survey completed." in result
        assert "## What Could Be Better" in result
        assert "No major clinical gaps" in result
        assert "Score:" not in result

    def test_all_missed(self):
        defs = [
            _def(
                "cp.o2",
                "Oxygen administration",
                missed_feedback="Oxygen was not initiated.",
                clinical_rationale="Corrects hypoxemia by increasing FiO2.",
                common_error="Students delay O2 because the patient is speaking.",
            ),
            _def("cp.pat", "PAT", missed_feedback="PAT not recorded."),
        ]
        states = [
            _state("cp.o2", "missed", earned=0),
            _state("cp.pat", "missed", earned=0),
        ]
        session = _make_session(defs, states)
        result = _compose_scored_section(session, "clinical_performance")

        assert "## What Could Be Better" in result
        assert "Oxygen was not initiated." in result
        assert "Corrects hypoxemia" in result
        assert "Students delay O2" not in result
        assert "PAT not recorded." in result
        assert "## What Went Well" in result

    def test_mixed(self):
        defs = [
            _def("cp.ppe", "PPE", done_feedback="PPE donned.", point_value=2),
            _def("cp.o2", "Oxygen", missed_feedback="O2 not given.", point_value=4),
            _def("cp.history", "History", missed_feedback="Incomplete history.", point_value=2),
        ]
        states = [
            _state("cp.ppe", "satisfied", earned=2),
            _state("cp.o2", "missed", earned=0),
            _state("cp.history", "partial", earned=1),
        ]
        session = _make_session(defs, states)
        result = _compose_scored_section(session, "clinical_performance")

        assert "## What Went Well" in result
        assert "PPE donned." not in result
        assert "Partially completed" not in result
        assert "Incomplete history." in result
        assert "## What Could Be Better" in result
        assert "O2 not given." in result

    def test_missed_items_stay_under_what_could_be_better(self):
        defs = [
            _def("cp.direct_pressure", "Direct pressure", done_feedback="Direct pressure applied.", point_value=10),
            _def("cp.pat", "PAT", done_feedback="PAT completed.", point_value=5),
            _def("cp.neuro", "Neuro", missed_feedback="Neuro assessment missing.", point_value=7),
            _def("cp.mechanism", "Mechanism", missed_feedback="Mechanism not assessed.", point_value=5),
            _def("cp.vitals", "Vitals", missed_feedback="Vitals missing.", point_value=4),
            _def("cp.sample", "SAMPLE", missed_feedback="SAMPLE history missing.", point_value=3),
            _def("cp.head", "Head exam", missed_feedback="Head exam missing.", point_value=2),
            _def("cp.reassess", "Reassessment", missed_feedback="Reassessment missing.", point_value=1),
        ]
        states = [
            _state("cp.direct_pressure", "satisfied", earned=10),
            _state("cp.pat", "satisfied", earned=5),
            _state("cp.neuro", "missed", earned=0),
            _state("cp.mechanism", "missed", earned=0),
            _state("cp.vitals", "missed", earned=0),
            _state("cp.sample", "missed", earned=0),
            _state("cp.head", "missed", earned=0),
            _state("cp.reassess", "missed", earned=0),
        ]
        session = _make_session(defs, states)

        result = _compose_scored_section(session, "clinical_performance")

        went_well = result.split("## What Could Be Better", 1)[0]
        could_better = result.split("## What Could Be Better", 1)[1]
        assert "Direct pressure applied." in went_well
        assert "PAT completed." in went_well
        assert "Neuro assessment missing." not in went_well
        assert "Mechanism not assessed." not in went_well
        assert "Neuro assessment missing." in could_better
        assert "additional lower-priority rubric gap" in could_better

    def test_generic_base_items_are_not_used_as_strength_filler(self):
        defs = [
            _def(
                "ems.trauma.airway",
                "Airway opened/assessed and adjunct inserted as indicated",
                done_feedback="Airway opened/assessed and adjunct inserted as indicated — completed.",
                point_value=2,
            ),
            _def(
                "ems.trauma.breathing",
                "Breathing assessed, ventilation assured, and oxygen managed when indicated",
                done_feedback="Breathing assessed, ventilation assured, and oxygen managed when indicated — completed.",
                point_value=4,
            ),
            _def(
                "head_injury.smr",
                "Spinal motion restriction applied",
                done_feedback="Spinal motion restriction applied — correct prioritization given mechanism and confusion.",
                point_value=12,
            ),
        ]
        states = [
            _state("ems.trauma.airway", "satisfied", earned=2),
            _state("ems.trauma.breathing", "satisfied", earned=4),
            _state("head_injury.smr", "satisfied", earned=12),
        ]
        session = _make_session(defs, states)
        result = _compose_scored_section(session, "clinical_performance")

        assert "Spinal motion restriction applied" in result
        assert "Airway opened/assessed" not in result
        assert "Breathing assessed" not in result

    def test_generic_medical_assessment_items_are_not_strength_filler(self):
        defs = [
            _def(
                "ems.medical.focused_secondary",
                "Performs focused secondary assessment of affected body system or rapid assessment if indicated",
                done_feedback="Performs focused secondary assessment of affected body system or rapid assessment if indicated",
                point_value=5,
            ),
            _def(
                "ems.medical.baseline_vitals",
                "Obtains and records vital signs relevant to the patient presentation",
                done_feedback="Obtains and records vital signs relevant to the patient presentation",
                point_value=5,
            ),
            _def(
                "peds_asthma_01.albuterol_svn",
                "Albuterol 2.5 mg via SVN administered",
                done_feedback="Albuterol 2.5 mg via SVN administered — correct first-line bronchodilator.",
                point_value=10,
            ),
        ]
        states = [
            _state("ems.medical.focused_secondary", "satisfied", earned=5),
            _state("ems.medical.baseline_vitals", "satisfied", earned=5),
            _state("peds_asthma_01.albuterol_svn", "satisfied", earned=10),
        ]
        session = _make_session(defs, states)
        result = _compose_scored_section(session, "clinical_performance")

        assert "Albuterol 2.5 mg via SVN administered" in result
        assert "Performs focused secondary" not in result
        assert "Obtains and records vital signs" not in result

    def test_generic_reassessment_strength_suppressed_when_specific_reassessment_missed(self):
        defs = [
            _def(
                "ems.trauma.reassessment",
                "Demonstrates how and when to reassess the patient",
                done_feedback="Demonstrates how and when to reassess the patient",
                point_value=1,
            ),
            _def(
                "peds_trauma_01_soft_tissue.reassess_vitals",
                "Reassess vitals and neuro status after bleeding controlled",
                missed_feedback="Reassess vitals and neuro status after bleeding controlled — not completed.",
                point_value=4,
            ),
        ]
        states = [
            _state("ems.trauma.reassessment", "satisfied", earned=1),
            _state("peds_trauma_01_soft_tissue.reassess_vitals", "not_satisfied", earned=0),
        ]
        session = _make_session(defs, states)

        result = _compose_scored_section(session, "clinical_performance")

        assert "Demonstrates how and when to reassess" not in result
        assert "Reassess vitals and neuro status after bleeding controlled" in result

    def test_generic_medical_airway_and_circulation_are_not_strength_filler(self):
        defs = [
            _def(
                "ems.medical.airway_breathing_o2",
                "Assesses airway and breathing, assures adequate ventilation, and initiates appropriate oxygen therapy",
                done_feedback="Assesses airway and breathing, assures adequate ventilation, and initiates appropriate oxygen therapy",
                point_value=3,
            ),
            _def(
                "ems.medical.circulation",
                "Assesses circulation: major bleeding, skin, and pulse",
                done_feedback="Assesses circulation: major bleeding, skin, and pulse",
                point_value=3,
            ),
            _def(
                "peds_croup_01.recognize_croup",
                "Croup recognized",
                done_feedback="Croup correctly recognized — treatment plan reflected upper airway obstruction management.",
                point_value=10,
            ),
        ]
        states = [
            _state("ems.medical.airway_breathing_o2", "satisfied", earned=3),
            _state("ems.medical.circulation", "satisfied", earned=3),
            _state("peds_croup_01.recognize_croup", "satisfied", earned=10),
        ]
        session = _make_session(defs, states)
        result = _compose_scored_section(session, "clinical_performance")

        assert "Croup correctly recognized" in result
        assert "Assesses airway and breathing" not in result
        assert "Assesses circulation" not in result

    def test_first_sentence_does_not_cut_off_vs_abbreviation(self):
        defs = [
            _def(
                "pediatric_croup.stridor_characterized",
                "Characterizes stridor",
                done_feedback="Stridor characterized — phase (inspiratory only vs. biphasic) correlates directly with obstruction severity.",
                point_value=3,
            ),
        ]
        states = [_state("pediatric_croup.stridor_characterized", "satisfied", earned=3)]
        session = _make_session(defs, states)

        result = _compose_scored_section(session, "clinical_performance")

        assert "Stridor characterized — phase (inspiratory only vs. biphasic) correlates directly with obstruction severity." in result
        assert "Stridor characterized — phase (inspiratory only vs.\n" not in result

    def test_low_signal_missed_items_are_not_top_five_gaps(self):
        defs = [
            _def("ems.medical.patient_name", "Obtains or verifies patient name", missed_feedback="Patient name not obtained.", point_value=1),
            _def("ems.medical.additional_help", "Requests additional help if necessary", missed_feedback="Additional help not requested.", point_value=1),
            _def("croup.hpi_onset_duration", "Obtains history of present illness: onset, duration, and progression", missed_feedback="Onset and progression were not obtained.", point_value=1),
        ]
        states = [
            _state("ems.medical.patient_name", "missed", earned=0),
            _state("ems.medical.additional_help", "missed", earned=0),
            _state("croup.hpi_onset_duration", "missed", earned=0),
        ]
        session = _make_session(defs, states)
        result = _compose_scored_section(session, "clinical_performance")

        assert "Onset and progression were not obtained." in result
        assert "Patient name not obtained." not in result
        assert "Additional help not requested." not in result

    def test_score_mapped_challenge_partial_uses_done_feedback_not_missed_feedback(self):
        defs = [
            _def(
                "cp.nrp",
                "Newborn resuscitation challenge submitted and backend-scored",
                point_value=20,
                done_feedback="Neonatal resuscitation challenge submitted — NRP workflow quality was scored from backend structured data.",
                missed_feedback="Neonatal resuscitation challenge not completed — completion is required.",
            )
        ]
        states = [
            _state(
                "cp.nrp",
                "partial",
                earned=19,
                notes="challenge score mapped into parent checklist item",
            )
        ]
        session = _make_session(defs, states)

        result = _compose_scored_section(session, "clinical_performance")

        assert "What Could Be Better" in result
        assert "NRP workflow quality was scored from backend structured data" in result
        assert "19/20" not in result
        assert "not completed" not in result

    def test_not_applicable_items_excluded(self):
        defs = [
            _def("cp.ppe", "PPE", done_feedback="PPE donned."),
            _def("cp.als", "ALS request", done_feedback="ALS called."),
        ]
        states = [
            _state("cp.ppe", "satisfied", earned=2),
            _state("cp.als", "not_applicable", earned=0),
        ]
        session = _make_session(defs, states)
        result = _compose_scored_section(session, "clinical_performance")

        assert "ALS request" not in result
        assert "PPE donned." not in result
        assert "No major clinical strengths" in result

    def test_missing_metadata_falls_back_to_description(self):
        defs = [
            _def("cp.ppe", "PPE — scene entry"),
            _def("cp.primary_survey", "Primary survey"),
        ]
        states = [
            _state("cp.ppe", "satisfied", earned=2),
            _state("cp.primary_survey", "missed", earned=0),
        ]
        session = _make_session(defs, states)
        result = _compose_scored_section(session, "clinical_performance")

        # Falls back to f"{description} — completed." / "— not completed."
        assert "PPE — scene entry" not in result
        assert "Primary survey — not completed." in result
        assert result  # non-empty

    def test_wrong_category_excluded(self):
        defs = [
            _def("cp.ppe", "PPE", category="clinical_performance", done_feedback="Done."),
            _def("pt.o2", "Oxygen", category="protocols_treatment", missed_feedback="Missed."),
        ]
        states = [
            _state("cp.ppe", "satisfied", earned=2),
            _state("pt.o2", "missed", earned=0),
        ]
        session = _make_session(defs, states)
        result = _compose_scored_section(session, "clinical_performance")

        assert "Oxygen" not in result
        assert "PPE" not in result
        assert "No major clinical gaps" in result

    def test_empty_when_no_matching_items(self):
        defs = [_def("pt.o2", "Oxygen", category="protocols_treatment")]
        states = [_state("pt.o2", "satisfied", earned=4)]
        session = _make_session(defs, states)
        result = _compose_scored_section(session, "clinical_performance")
        assert result == ""

    def test_empty_when_no_states(self):
        session = _make_session([], [])
        assert _compose_scored_section(session, "clinical_performance") == ""

    def test_empty_when_checklist_states_missing(self):
        session = types.SimpleNamespace(checklist_states=None, score_snapshot={})
        assert _compose_scored_section(session, "clinical_performance") == ""

    def test_protocols_treatment_category(self):
        defs = [
            _def(
                "pt.o2",
                "Oxygen administration",
                category="protocols_treatment",
                done_feedback="O2 appropriately applied.",
                point_value=4,
            )
        ]
        states = [_state("pt.o2", "satisfied", earned=4)]
        session = _make_session(
            defs,
            states,
            score_snapshot={"categories": {"protocols_treatment": {"total": 4, "max": 10}}},
        )
        result = _compose_scored_section(session, "protocols_treatment")
        assert "O2 appropriately applied." not in result
        assert "✓ Oxygen administration" in result
        assert "Score:" not in result
        assert "## Protocols & Treatments" in result

    def test_protocols_treatment_category_includes_protocol_reference(self):
        defs = [
            _def(
                "pt.o2",
                "Oxygen administration",
                category="protocols_treatment",
                done_feedback="O2 appropriately applied.",
                point_value=4,
            )
        ]
        states = [_state("pt.o2", "satisfied", earned=4)]
        session = _make_session(defs, states)
        scenario = {
            "protocol_config": {
                "protocol_reference": "Michigan Protocol Section 4-7: Pediatric Seizures"
            }
        }

        result = _compose_scored_section(session, "protocols_treatment", scenario=scenario)

        assert "Reference: Michigan Protocol Section 4-7: Pediatric Seizures" in result
        assert result.index("Reference:") < result.index("✓ Oxygen administration")

    def test_missed_bonus_protocol_items_are_not_listed_as_required_misses(self):
        defs = [
            _def(
                "peds_croup_01.als_intercept",
                "ALS handoff readiness confirmed",
                category="protocols_treatment",
                point_value=6,
                required="bonus",
            ),
            _def(
                "croup.o2",
                "Supplemental oxygen delivered",
                category="protocols_treatment",
                point_value=2,
                done_feedback="Oxygen delivered.",
            ),
        ]
        states = [
            _state("peds_croup_01.als_intercept", "missed", earned=0),
            _state("croup.o2", "satisfied", earned=2),
        ]
        session = _make_session(
            defs,
            states,
            score_snapshot={"categories": {"protocols_treatment": {"total": 2, "max": 2}}},
        )
        result = _compose_scored_section(session, "protocols_treatment")

        assert "✓ Supplemental oxygen delivered" in result
        assert "ALS handoff readiness" not in result

    def test_protocols_section_replacement_removes_llm_addendum(self):
        debrief = (
            "**1. Clinical Performance**\n"
            "Clinical text.\n\n"
            "**2. Protocols & Treatment**\n"
            "{{SECTION2_PROTOCOLS_TREATMENT}}\n\n"
            "COACHING NOTE: high-flow oxygen was provided.\n\n"
            "**3. Scope of Practice**\n"
            "Scope text."
        )

        result = _replace_protocols_section_with_rendered_block(
            debrief,
            "BACKEND PROTOCOL BLOCK",
        )

        assert "BACKEND PROTOCOL BLOCK" in result
        assert "high-flow oxygen was provided" not in result
        assert "{{SECTION2_PROTOCOLS_TREATMENT}}" not in result
        assert "**1. Clinical Performance**" in result
        assert "**3. Scope of Practice**" in result

    def test_score_line_ends_output(self):
        defs = [_def("cp.ppe", "PPE", done_feedback="Done.")]
        states = [_state("cp.ppe", "satisfied", earned=2)]
        session = _make_session(defs, states)
        result = _compose_scored_section(session, "clinical_performance")
        assert result.endswith("- No major clinical gaps were identified in the scored checklist.")

    def test_strip_redundant_clinical_performance_wrapper_before_rendered_block(self):
        result = _strip_redundant_clinical_wrapper(
            "Clinical Performance\n\n## What Went Well\n- SMR applied.\n\n## What Could Be Better\n- O2 missed."
        )

        assert "Clinical Performance" not in result
        assert result.startswith("## What Went Well")

    def test_strip_orphan_areas_for_improvement_heading(self):
        result = _strip_orphan_improvement_headings(
            "## What Could Be Better\n"
            "- Gap.\n\n"
            "Areas for Improvement\n"
            "## Protocols & Treatments\n"
            "✗ O2."
        )

        assert "Areas for Improvement" not in result
        assert "## Protocols & Treatments" in result

    def test_fixed_debrief_assembler_owns_heading_order_and_inserts_blocks(self):
        llm_text = (
            "## What Went Well\n\n"
            "## What Could Be Better\n"
            "- Model gap that should be replaced.\n\n"
            "Areas for Improvement\n\n"
            "**Patient Communication:**\n"
            "The student was task-focused. *Professionalism score: 4/10*\n\n"
            "## Handoff & Communication\n"
            "DMIST was sparse. DMIST score: 2/10\n\n"
            "## Narrative\n"
            "Narrative was brief. Narrative score: 4/20\n\n"
            "## Case Study\n"
            "What happened: Case body.\n\n"
            "## What Went Well\n"
            "- Duplicate model strength."
        )

        result = _assemble_fixed_debrief(
            llm_text,
            rendered_clinical="## What Went Well\n- Backend strength.\n\n## What Could Be Better\n- Backend gap.",
            rendered_protocols="## Protocols & Treatments\nReference: Protocol 4-7\n✗ O2.",
            include_narrative=True,
            include_protocols=True,
        )

        assert "Areas for Improvement" not in result
        assert "Duplicate model strength" not in result
        assert "Model gap that should be replaced" not in result
        assert result.count("## What Went Well") == 1
        assert result.index("## What Went Well") < result.index("## What Could Be Better")
        assert result.index("## What Could Be Better") < result.index("## Protocols & Treatments")
        assert result.index("## Protocols & Treatments") < result.index("## Handoff & Communication")
        assert result.index("## Handoff & Communication") < result.index("## Patient Communication")
        assert result.index("## Patient Communication") < result.index("## Narrative")
        assert result.index("## Narrative") < result.index("## Case Study")
        assert "Reference: Protocol 4-7" in result

    def test_fixed_debrief_uses_deterministic_handoff_block(self):
        result = _assemble_fixed_debrief(
            "## Handoff & Communication\nThe model says T missed ALS disposition.\n\n## Case Study\nCase body.",
            rendered_handoff="DMIST score: 7/10\nT - Treatment/Transport: full credit; treatment response.",
        )

        assert "The model says T missed ALS disposition" not in result
        assert "T - Treatment/Transport: full credit" in result

    def test_dmist_summary_does_not_report_t_missing_disposition_when_t_full_credit(self):
        summary = _render_dmist_component_summary({
            "score": 7,
            "max_score": 10,
            "applicable": True,
            "components": {
                "D": {"score": 1, "matched": ["name"], "missing": ["pediatric weight"]},
                "M": {"score": 1, "matched": ["difficulty breathing"], "missing": ["wheezing"]},
                "I": {"score": 1, "matched": ["known asthma history"], "missing": ["rescue inhaler unavailable"]},
                "S": {"score": 2, "matched": ["SpO2", "respiratory rate"], "missing": []},
                "T": {"score": 2, "matched": ["albuterol administered", "treatment response"], "missing": ["ALS readiness"]},
            },
        })

        assert "T - Treatment/Transport: full credit" in summary
        assert "ALS readiness" not in summary

    def test_narrative_feedback_section_is_filled_when_model_omits_it(self):
        result = _ensure_narrative_feedback_section(
            "## Handoff & Communication\nDMIST score: 8/10\n\n## Case Study\nCase body.",
            include_narrative=True,
            narrative_score=12,
            narrative_max=20,
            score_note="Narrative omitted transfer/disposition.",
        )

        assert "## Narrative" in result
        assert "Narrative score: 12/20" in result
        assert "Narrative omitted transfer/disposition." in result

    def test_unnecessary_pd_wait_is_inserted_into_improvement_section(self):
        session = _make_session(
            definitions=[
                _def(
                    "cp.airway",
                    "Airway assessed",
                    done_feedback="Airway was assessed.",
                    point_value=2,
                )
            ],
            item_states=[_state("cp.airway", "satisfied", earned=2)],
        )
        session.scene_entry = {
            "ppe_donned": ["Gloves"],
            "scene_approach": "waited_for_pd",
            "pat_assessment": "sick",
        }
        scenario = {"scene": {"hazards": []}}

        result = _compose_scored_section(session, "clinical_performance", scenario=scenario)

        assert "Waiting for PD delayed patient contact" in result
        assert result.index("## What Could Be Better") < result.index("Waiting for PD")

    def test_main_sections_are_reordered_after_rendered_block_injection(self):
        result = _reorder_debrief_main_sections(
            "FTO Summary\nKeep this.\n\n"
            "Handoff & Communication\nDMIST text.\n\n"
            "Case Study\nCase text.\n\n"
            "Narrative\nNarrative text.\n\n"
            "## What Went Well\n- Strength.\n\n"
            "## What Could Be Better\n- Gap.\n\n"
            "## Protocols & Treatments\n✓ O2."
        )

        assert result.index("## What Went Well") < result.index("## What Could Be Better")
        assert result.index("## What Could Be Better") < result.index("## Protocols & Treatments")
        assert result.index("## Protocols & Treatments") < result.index("Handoff & Communication")
        assert result.index("Handoff & Communication") < result.index("Narrative")
        assert result.index("Narrative") < result.index("Case Study")

    def test_reorder_prefers_non_empty_duplicate_clinical_sections(self):
        result = _reorder_debrief_main_sections(
            "FTO Summary\nKeep this.\n\n"
            "## What Went Well\n\n"
            "## What Could Be Better\n"
            "- Gap.\n\n"
            "Handoff & Communication\nDMIST text.\n\n"
            "Case Study\nCase text.\n\n"
            "## What Went Well\n"
            "- Strength."
        )

        assert result.count("What Went Well") == 1
        assert "- Strength." in result
        assert result.index("## What Went Well") < result.index("## What Could Be Better")


class TestDmistComponentFloor:
    def test_informal_pediatric_handoff_gets_component_floor(self):
        text = (
            "this is marcus, 8 yom fell off monkey bars and hit his head "
            "now his head hurts and hes confused happened 20 minutes ago "
            "we're holding cspine"
        )

        presence = _estimate_dmist_component_presence(text)

        assert presence["D"] is True
        assert presence["M"] is True
        assert presence["I"] is True
        assert presence["S"] is True
        assert presence["T"] is False
        assert _conservative_dmist_floor(text) == 5


class TestDebriefSanitizers:
    def test_credited_sanitizer_preserves_markdown_when_no_removal(self):
        markdown = "## What Went Well\n- First item.\n- Second item.\n\n## What Could Be Better\n- Gap."

        result = _sanitize_credited_item_contradictions(
            markdown,
            satisfied_item_ids={"peds_asthma_01.foreign_body_screen"},
        )

        assert result == markdown

    def test_missed_overcredit_sanitizer_preserves_markdown_when_no_removal(self):
        markdown = "## What Went Well\n- First item.\n- Second item.\n\n## What Could Be Better\n- Gap."

        result = _sanitize_missed_item_overcredit(
            markdown,
            missed_item_ids={"head_injury.pupil_assessment"},
        )

        assert result == markdown

    def test_missed_febrile_seizure_suction_removed_from_case_study(self):
        markdown = (
            "## Case Study\n"
            "What happened: Chloe was found actively seizing with pooled oral secretions. "
            "Interventions performed were placement in the recovery position, gentle oral suction, "
            "and delivery of high-flow blow-by oxygen.\n\n"
            "What it means clinically: Visible secretions require suction."
        )

        result = _sanitize_missed_item_overcredit(
            markdown,
            missed_item_ids={"peds_febrile_seizure_01.suction_airway"},
        )

        assert "Interventions performed were" not in result
        assert "gentle oral suction" not in result
        assert "Visible secretions require suction" in result

    def test_missed_soft_tissue_neuro_package_removes_pupil_overcredit(self):
        markdown = (
            "## Case Study\n"
            "The crew performed a focused neuro exam. "
            "Neurologic assessment revealed a GCS of 15, pupils equal and reactive, "
            "and no loss of consciousness. Continue monitoring for vomiting."
        )

        result = _sanitize_missed_item_overcredit(
            markdown,
            missed_item_ids={"peds_trauma_01_soft_tissue.neuro_assessment"},
        )

        assert "performed a focused neuro exam" not in result
        assert "pupils equal and reactive" not in result
        assert "no loss of consciousness" not in result
        assert "Continue monitoring for vomiting" in result

    def test_case_study_guardrails_flag_missed_neuro_package(self):
        defs = [
            _def(
                "peds_trauma_01_soft_tissue.neuro_assessment",
                "Neurological assessment performed — GCS/AVPU, pupils, and questions about LOC at time of injury and vomiting asked",
                missed_feedback="Complete neurological assessment not documented.",
                point_value=7,
            ),
            _def(
                "peds_trauma_01_soft_tissue.reassess_vitals",
                "Reassess vitals and neuro status after bleeding controlled",
                missed_feedback="Reassessment not documented.",
                point_value=4,
            ),
        ]
        states = [
            _state("peds_trauma_01_soft_tissue.neuro_assessment", "not_satisfied", earned=0),
            _state("peds_trauma_01_soft_tissue.reassess_vitals", "not_satisfied", earned=0),
        ]
        session = _make_session(defs, states)

        result = _compose_case_study_guardrails(session)

        assert "Do NOT write that a focused, complete, or full neurological assessment" in result
        assert "scenario-specific reassessment item was missed" in result


# ── _compose_reference_section ────────────────────────────────────────────────

class TestComposeReferenceSection:
    def _scenario(
        self,
        condition_background: str = "",
        key_teaching_points: list[str] | None = None,
        common_mistakes: list[str] | None = None,
    ) -> dict:
        return {
            "debrief": {
                "condition_background": condition_background,
                "key_teaching_points": key_teaching_points or [],
                "common_mistakes": common_mistakes or [],
            }
        }

    def test_full_authored_content(self):
        scenario = self._scenario(
            condition_background="Croup is viral subglottic edema.",
            key_teaching_points=["Stridor is upper airway.", "Calm first."],
            common_mistakes=["Reaching for albuterol.", "Forcing NRB on infant."],
        )
        result = _compose_reference_section(scenario)

        assert "Croup is viral subglottic edema." in result
        assert "Stridor is upper airway." in result
        assert "Calm first." in result
        assert "Reaching for albuterol." in result
        assert "Forcing NRB on infant." in result
        assert "Condition Background" in result
        assert "Key Teaching Points" in result
        assert "Common Errors" in result

    def test_empty_when_no_authored_content(self):
        result = _compose_reference_section({"debrief": {}})
        assert result == ""

    def test_empty_when_no_debrief_key(self):
        result = _compose_reference_section({})
        assert result == ""

    def test_empty_when_debrief_none(self):
        result = _compose_reference_section({"debrief": None})
        assert result == ""

    def test_partial_content_condition_only(self):
        scenario = self._scenario(condition_background="Asthma is lower airway bronchospasm.")
        result = _compose_reference_section(scenario)
        assert "Condition Background" in result
        assert "Asthma is lower airway bronchospasm." in result
        assert "Key Teaching Points" not in result

    def test_structured_condition_background_renders_clean_sections(self):
        scenario = self._scenario(
            condition_background={
                "pathophysiology": "Inferior STEMI reduces RCA territory perfusion.",
                "assessment_pearls": "Look for reciprocal changes and bradycardia.",
                "treatment_rationale": "Aspirin and cardiac alert reduce time to cath lab.",
            }
        )
        result = _compose_reference_section(scenario)

        assert "Pathophysiology" in result
        assert "Assessment Pearls" in result
        assert "Treatment Rationale" in result
        assert "Inferior STEMI" in result
        assert "{'pathophysiology'" not in result

    def test_partial_content_teaching_points_only(self):
        scenario = self._scenario(key_teaching_points=["Wheeze is expiratory."])
        result = _compose_reference_section(scenario)
        assert "Key Teaching Points" in result
        assert "Wheeze is expiratory." in result
        assert "Condition Background" not in result

    def test_common_mistakes_label(self):
        scenario = self._scenario(common_mistakes=["Students skip lung sounds."])
        result = _compose_reference_section(scenario)
        assert "Common Errors" in result
        assert "Students skip lung sounds." in result

    def test_output_ends_with_authored_content(self):
        scenario = self._scenario(condition_background="Something.")
        result = _compose_reference_section(scenario)
        assert result.endswith("Something.")

    def test_output_ends_with_last_common_mistake(self):
        scenario = self._scenario(
            condition_background="Background.",
            common_mistakes=["Error A.", "Error B."],
        )
        result = _compose_reference_section(scenario)
        assert result.endswith("- Error B.")
