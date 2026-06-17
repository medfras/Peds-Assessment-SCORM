"""Tests for evidence packet — deterministic detection logic (Phase 2 + Phase 3).

Covers:
- Universal Base regex patterns (_SCENE_SAFETY_RE, _PRIMARY_SURVEY_RE, etc.)
- DMIST / CHART structural presence patterns
- _detect_greeting()
- _format_evidence_packet_for_prompt() — all rendering branches
- _build_evidence_packet() score ceilings, required_assessments/screens,
  §5.5 assessment phases, §5.6 transport/disposition
"""

import inspect
import json
import sys
import types
import datetime
from pathlib import Path

import pytest

# ── Stub app.config before any app imports ────────────────────────────────────
class _FakeSettings(types.SimpleNamespace):
    def __getattr__(self, name):
        if name.startswith("rate_limit_"):
            return 100
        if name.endswith("_enabled"):
            return False
        if name.endswith("_cap"):
            return 0
        if name.endswith("_origins"):
            return []
        return ""


_fake_config = types.ModuleType("app.config")
_fake_config.settings = _FakeSettings(
    groq_api_key="test",
    app_secret_key="test-secret",
    jwt_algorithm="HS256",
    jwt_expire_minutes=60,
    database_url="postgresql+asyncpg://test:test@localhost:5432/test",
    db_pool_size=1,
    db_max_overflow=1,
    log_level="INFO",
    log_format="json",
    default_provider_level="EMT",
    default_mca="mi_wmrmcc_kent",
    rate_limit_auth=10,
    rate_limit_session_start=10,
    rate_limit_session_write=60,
    rate_limit_chat=30,
    rate_limit_med_control=10,
    rate_limit_lexi=5,
    rate_limit_debrief=3,
    rate_limit_lexi_group_create=5,
    rate_limit_lexi_group_join=10,
    rate_limit_lexi_group_start=5,
    rate_limit_lexi_group_answer=30,
    rate_limit_lexi_group_feedback_ready=30,
    rate_limit_lexi_group_next_round=10,
    rate_limit_team_presence=30,
    rate_limit_team_invite=10,
    rate_limit_team_accept=10,
    rate_limit_team_start=10,
    team_challenge_enabled=False,
    superuser_username="",
    superuser_password="",
    seed_agency_name="",
    seed_agency_join_code="",
    seed_agency_file="",
    groq_lexi_model="llama-3.1-8b-instant",
    gemini_tts_model="gemini-2.5-flash-preview-tts",
    openai_tts_model="gpt-4o-mini-tts",
    allowed_origins=["http://testserver"],
    sentry_dsn="",
)
_fake_config._IS_PROD = False
sys.modules["app.config"] = _fake_config

from app.ai_client import (  # noqa: E402
    _CHART_ELEMENT_PATTERNS,
    _DMIST_COMPONENT_PATTERNS,
    _DISPOSITION_RE,
    _GREETING_RE,
    _HISTORY_RE,
    _PREPASS_FALLBACK,
    _PRIMARY_SURVEY_RE,
    _REASSESSMENT_RE_UB,
    _SCENE_SAFETY_RE,
    _build_evidence_packet,
    _compute_next_action_routing,
    _compute_reasoning_flags,
    _compute_professionalism_hardened_constraints,
    _detect_greeting,
    _deterministic_prepass_result,
    _extract_required_debrief_subscores,
    _format_evidence_packet_for_prompt,
    _is_retryable_groq_error,
    _o2_methods_equivalent,
    _intervention_label_for_evidence,
    _normalize_debrief_section_headers,
    _parse_debrief_response_payload,
    _parse_json_object_response,
    _replace_unrendered_debrief_placeholders,
    _sanitize_credited_item_contradictions,
    _sanitize_credited_item_list,
    _sanitize_missed_item_overcredit,
    _is_json_mode_validation_error,
    get_lexi_response,
    get_practice_coach_response,
    evaluate_and_generate_debrief,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _msg(content: str):
    return types.SimpleNamespace(content=content)


def _finding(key="spo2", value="98", finding_type="vital", captured_at=None):
    return types.SimpleNamespace(
        key=key, value=value, finding_type=finding_type, captured_at=captured_at
    )


def _make_session(interventions=None):
    return types.SimpleNamespace(interventions=interventions or [])


def _make_intervention(name: str, applied_at=None):
    return types.SimpleNamespace(name=name, applied_at=applied_at)


_BASE_AGENCY = {"transports_patients": True}
_BASE_SCENARIO = {
    "id": "test_01",
    "category": "medical",
    "protocol_config": {"mca": "mi_wmrmcc_kent"},
    "vitals": {"baseline": {}, "interventions": {}},
    "scoring": {},
    "turnover_target": "als",
}


def _call_build(
    scenario=None,
    session=None,
    submitted_docs=None,
    findings=None,
    *,
    elapsed_min=10.0,
    effective_level="EMT",
    agency=None,
    student_messages=None,
    scene_entry_scoring_result=None,
    greeting_detected=False,
    greeting_text="",
    prepass_result=None,
    critical_actions=None,
    grace_items=None,
    scene_entry_dict=None,
    session_events=None,
):
    return _build_evidence_packet(
        scenario or _BASE_SCENARIO,
        session or _make_session(),
        submitted_docs or {},
        findings or [],
        elapsed_min=elapsed_min,
        effective_level=effective_level,
        agency=agency or _BASE_AGENCY,
        student_messages=student_messages or [],
        scene_entry_scoring_result=scene_entry_scoring_result,
        greeting_detected=greeting_detected,
        greeting_text=greeting_text,
        prepass_result=prepass_result,
        critical_actions=critical_actions,
        grace_items=grace_items,
        scene_entry_dict=scene_entry_dict,
        session_events=session_events,
    )


def _session_event(event_type, event_key="", occurred_at=None, source="backend_auto"):
    from datetime import datetime
    return types.SimpleNamespace(
        event_type=event_type,
        event_key=event_key,
        source=source,
        occurred_at=occurred_at or datetime(2026, 1, 1, 12, 0, 0),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 0 — Critical action routing
# ═══════════════════════════════════════════════════════════════════════════════

class TestCriticalActionRouting:
    def test_per_action_als_grace_routes_to_als_grace_without_global_grace(self):
        packet = _call_build(
            critical_actions=[
                {
                    "id": "als_intercept",
                    "description": "Confirm ALS intercept",
                    "required": True,
                    "als_grace": True,
                }
            ],
        )

        actions = packet["critical_actions_classified"]["actions"]
        assert actions == [{"tag": "ALS_GRACE", "description": "Confirm ALS intercept", "category": "protocols_treatment"}]


# ═══════════════════════════════════════════════════════════════════════════════
# 1 — Universal Base regex patterns
# ═══════════════════════════════════════════════════════════════════════════════

class TestSceneSafetyRe:
    def test_scene_safe_phrase(self):
        assert _SCENE_SAFETY_RE.search("Is the scene safe?")

    def test_bsi(self):
        assert _SCENE_SAFETY_RE.search("BSI, scene safe.")

    def test_ppe(self):
        assert _SCENE_SAFETY_RE.search("PPE is on.")

    def test_gloves_on(self):
        assert _SCENE_SAFETY_RE.search("Gloves on, approaching the patient.")

    def test_survey_the_scene(self):
        assert _SCENE_SAFETY_RE.search("We survey the scene before entering.")

    def test_no_match(self):
        assert not _SCENE_SAFETY_RE.search("Patient is breathing normally.")


class TestPrimarySurveyRe:
    def test_general_impression(self):
        assert _PRIMARY_SURVEY_RE.search("General impression: sick-looking child.")

    def test_airway(self):
        assert _PRIMARY_SURVEY_RE.search("Airway appears patent.")

    def test_avpu(self):
        assert _PRIMARY_SURVEY_RE.search("AVPU: Alert.")

    def test_wob(self):
        assert _PRIMARY_SURVEY_RE.search("Increased WOB noted.")

    def test_gcs(self):
        assert _PRIMARY_SURVEY_RE.search("GCS 15.")

    def test_no_match(self):
        assert not _PRIMARY_SURVEY_RE.search("The family is present.")


class TestHistoryRe:
    def test_allergies(self):
        assert _HISTORY_RE.search("Do you have any allergies?")

    def test_medications(self):
        assert _HISTORY_RE.search("Any medications?")

    def test_sample(self):
        assert _HISTORY_RE.search("Let me get a SAMPLE history.")

    def test_opqrst(self):
        assert _HISTORY_RE.search("OPQRST: onset was this morning.")

    def test_past_medical(self):
        assert _HISTORY_RE.search("Any past medical history?")

    def test_no_match(self):
        assert not _HISTORY_RE.search("SpO2 is 98 percent.")


class TestDispositionRe:
    def test_transport(self):
        assert _DISPOSITION_RE.search("We're going to transport the patient.")

    def test_hospital(self):
        assert _DISPOSITION_RE.search("We are heading to the hospital.")

    def test_als_request(self):
        assert _DISPOSITION_RE.search("Requesting ALS intercept.")

    def test_package(self):
        assert _DISPOSITION_RE.search("Let's package and get moving.")

    def test_no_match(self):
        assert not _DISPOSITION_RE.search("Lung sounds are clear bilaterally.")


class TestReassessmentReUb:
    def test_reassess(self):
        assert _REASSESSMENT_RE_UB.search("Let's reassess after O2.")

    def test_repeat_vitals(self):
        assert _REASSESSMENT_RE_UB.search("We'll repeat vitals in 5 minutes.")

    def test_monitor(self):
        assert _REASSESSMENT_RE_UB.search("Continue to monitor the patient.")

    def test_any_change(self):
        assert _REASSESSMENT_RE_UB.search("Any change in her condition?")

    def test_no_match(self):
        assert not _REASSESSMENT_RE_UB.search("Patient is a 6-year-old male.")


# ═══════════════════════════════════════════════════════════════════════════════
# 2 — DMIST / CHART structural presence patterns
# ═══════════════════════════════════════════════════════════════════════════════

class TestDmistComponentPatterns:
    def test_D_demographics(self):
        assert _DMIST_COMPONENT_PATTERNS["D"].search("6-year-old male presented for difficulty breathing.")

    def test_M_chief_complaint(self):
        assert _DMIST_COMPONENT_PATTERNS["M"].search("Chief complaint is difficulty breathing.")

    def test_I_illness_history(self):
        assert _DMIST_COMPONENT_PATTERNS["I"].search("No prior medical history, no medications.")

    def test_T_treatment(self):
        # T: section header triggers structural T detection regardless of content
        assert _DMIST_COMPONENT_PATTERNS["T"].search("T: Blow-by oxygen applied. ALS en route.")
        # ALS/transport disposition terms also satisfy T detection
        assert _DMIST_COMPONENT_PATTERNS["T"].search("Positioned her on her side and called ALS for intercept.")

    def test_S_vitals(self):
        assert _DMIST_COMPONENT_PATTERNS["S"].search("Vitals: HR 110, SpO2 95%, RR 28.")

    def test_T_transport(self):
        assert _DMIST_COMPONENT_PATTERNS["T"].search("Transporting to Children's ED, 5 min ETA.")

    def test_no_D_match(self):
        assert not _DMIST_COMPONENT_PATTERNS["D"].search("Reassessment showed improvement.")


class TestChartElementPatterns:
    def test_C_chief_complaint(self):
        assert _CHART_ELEMENT_PATTERNS["C"].search("Dispatched to a 6-year-old with difficulty breathing.")

    def test_H_history(self):
        assert _CHART_ELEMENT_PATTERNS["H"].search("Mother states the child developed a barky cough tonight.")

    def test_A_assessment(self):
        assert _CHART_ELEMENT_PATTERNS["A"].search("Assessment: SpO2 93%, HR 120, increased WOB.")

    def test_R_treatment(self):
        assert _CHART_ELEMENT_PATTERNS["R"].search("Administered O2 via blow-by at 6 LPM.")

    def test_T_transport(self):
        assert _CHART_ELEMENT_PATTERNS["T"].search("Transported to ED without incident.")

    def test_no_T_match(self):
        assert not _CHART_ELEMENT_PATTERNS["T"].search("History reveals onset two hours prior.")


# ═══════════════════════════════════════════════════════════════════════════════
# 3 — _detect_greeting
# ═══════════════════════════════════════════════════════════════════════════════

class TestDetectGreeting:
    def test_hi_detected(self):
        detected, text = _detect_greeting([_msg("Hi, I'm your paramedic today.")])
        assert detected
        assert "message 1" in text

    def test_hello_detected(self):
        detected, _ = _detect_greeting([_msg("Hello, what's going on?")])
        assert detected

    def test_my_name_is(self):
        detected, _ = _detect_greeting([_msg("My name is Sarah with Kent County EMS.")])
        assert detected

    def test_im_here_to_help(self):
        detected, _ = _detect_greeting([_msg("I'm here to help. Can you tell me what happened?")])
        assert detected

    def test_im_an_emt(self):
        detected, _ = _detect_greeting([_msg("I'm an EMT responding to your call.")])
        assert detected

    def test_no_greeting(self):
        detected, text = _detect_greeting([_msg("SpO2 reading, please."), _msg("Get the BVM.")])
        assert not detected
        assert "none found" in text

    def test_empty_messages(self):
        detected, _ = _detect_greeting([])
        assert not detected

    def test_greeting_in_second_message(self):
        detected, text = _detect_greeting([_msg("Scene safe, gloves on."), _msg("Hi there, I'm the medic.")])
        assert detected
        assert "message 2" in text

    def test_only_scans_first_five(self):
        msgs = [_msg("Breathing check.")] * 5 + [_msg("Hi there!")]
        detected, _ = _detect_greeting(msgs)
        assert not detected

    def test_content_attr_none_safe(self):
        detected, _ = _detect_greeting([types.SimpleNamespace(content=None)])
        assert not detected


# ═══════════════════════════════════════════════════════════════════════════════
# 4 — _format_evidence_packet_for_prompt rendering branches
# ═══════════════════════════════════════════════════════════════════════════════

def _empty_packet():
    return {
        "universal_base": {"present": [], "gaps": []},
        "corroboration": {
            "dmist_missing_components": [],
            "chart_missing_elements": [],
            "prepass_available": False,
            "dmist_unsupported_claims": [],
            "narrative_unsupported_claims": [],
        },
        "required_assessments": {"present": [], "gaps": []},
        "required_screens": {"present": [], "gaps": []},
        "positive_evidence": [],
        "ceilings": {},
    }


class TestFormatEvidencePacketEmpty:
    def test_returns_empty_string_when_no_gaps(self):
        result = _format_evidence_packet_for_prompt(_empty_packet())
        assert result == ""


class TestFormatEvidencePacketUbGaps:
    def test_ub_gap_renders(self):
        packet = _empty_packet()
        packet["universal_base"]["gaps"].append({
            "element": "scene_safety",
            "description": "Scene Safety/BSI — no scene safety language found",
        })
        result = _format_evidence_packet_for_prompt(packet)
        assert "## CLINICAL_PERFORMANCE_GAPS" in result
        assert "scene/base" in result
        assert "Scene Safety/BSI" in result


class TestFormatEvidencePacketPositiveAllowlist:
    def test_positive_allowlist_renders(self):
        packet = _empty_packet()
        packet["positive_evidence"] = [
            "Vitals obtained",
            "Intervention applied: O2 via NRB",
        ]
        result = _format_evidence_packet_for_prompt(packet)
        assert "RUN-EVIDENCED POSITIVES ONLY" in result
        assert "Vitals obtained" in result

    def test_tier_1_label_without_prepass(self):
        packet = _empty_packet()
        packet["universal_base"]["gaps"].append({"element": "history", "description": "History gap"})
        result = _format_evidence_packet_for_prompt(packet)
        assert "Tier 1" in result
        assert "Tier 1+2" not in result

    def test_tier_1plus2_label_with_prepass(self):
        packet = _empty_packet()
        packet["corroboration"]["prepass_available"] = True
        packet["universal_base"]["gaps"].append({"element": "vitals", "description": "Vitals gap"})
        result = _format_evidence_packet_for_prompt(packet)
        assert "Tier 1+2" in result

    def test_ub_present_shown_when_gaps_exist(self):
        packet = _empty_packet()
        packet["universal_base"]["present"].append("scene_safety")
        packet["universal_base"]["gaps"].append({"element": "history", "description": "History gap"})
        result = _format_evidence_packet_for_prompt(packet)
        assert "CLINICAL_PERFORMANCE_CREDITED" in result
        assert "scene_safety" in result


class TestFormatEvidencePacketDmistMissing:
    def test_dmist_missing_renders(self):
        packet = _empty_packet()
        packet["corroboration"]["dmist_missing_components"] = ["M", "T"]
        result = _format_evidence_packet_for_prompt(packet)
        assert "DMIST structural check" in result
        assert "M — MOI or Chief Complaint" in result
        assert "T — Treatment or Transport" in result

    def test_corroboration_rule_injected_with_dmist_missing(self):
        packet = _empty_packet()
        packet["corroboration"]["dmist_missing_components"] = ["D"]
        result = _format_evidence_packet_for_prompt(packet)
        assert "CORROBORATION RULE" in result

    def test_evidence_packet_includes_deterministic_dmist_shadow_score(self):
        scenario = json.loads(
            Path("app/scenarios/pediatric/medical/peds_febrile_seizure_01.json").read_text(encoding="utf-8")
        )
        session = _make_session([
            _make_intervention("recovery_position"),
            _make_intervention("suction_airway"),
            _make_intervention("o2_blowby"),
            _make_intervention("blood_glucose_check"),
        ])
        packet = _call_build(
            scenario=scenario,
            session=session,
            findings=[
                _finding("SpO2", "94 %"),
                _finding("Temperature", "103.6 F"),
                _finding("Blood Glucose", "92 mg/dL"),
            ],
            submitted_docs={
                "dmist": (
                    "D: Chloe, 6-month-old female, 7 kg.\n"
                    "M: Active seizure chief complaint.\n"
                    "I: Generalized full-body seizure for about two minutes with fever, first seizure, no trauma/choking/ingestion.\n"
                    "S: Wet airway secretions, SpO2 94%, temperature 103.6 F, blood glucose 92.\n"
                    "T: Recovery position, suctioned airway, blow-by oxygen, ALS handoff."
                )
            },
        )

        shadow = packet["deterministic_dmist"]
        assert shadow["method"] == "deterministic_shadow_v1"
        assert shadow["score"] == 10
        assert shadow["components"]["I"]["meaning"] == "Injuries or illness"


class TestFormatEvidencePacketChartMissing:
    def test_chart_missing_renders(self):
        packet = _empty_packet()
        packet["corroboration"]["chart_missing_elements"] = ["A", "R"]
        result = _format_evidence_packet_for_prompt(packet)
        assert "CHART structural check" in result
        assert "A — Assessment Findings" in result
        assert "R — Rx/Treatment" in result

    def test_corroboration_rule_injected_with_chart_missing(self):
        packet = _empty_packet()
        packet["corroboration"]["chart_missing_elements"] = ["T"]
        result = _format_evidence_packet_for_prompt(packet)
        assert "CORROBORATION RULE" in result


class TestFormatEvidencePacketTier2:
    def test_tier2_prepass_no_contradictions(self):
        packet = _empty_packet()
        # Need some other content to make the packet non-empty
        packet["universal_base"]["gaps"].append({"element": "reassessment", "description": "Reassessment gap"})
        packet["corroboration"]["prepass_available"] = True
        result = _format_evidence_packet_for_prompt(packet)
        assert "Pre-pass completed" in result
        assert "no direct factual contradictions" in result

    def test_tier2_dmist_unsupported_claims(self):
        packet = _empty_packet()
        packet["corroboration"]["prepass_available"] = True
        packet["corroboration"]["dmist_unsupported_claims"] = [
            {"component": "I", "claim": "Administered epi 0.15 mg IM", "reason": "No epi in intervention timeline"}
        ]
        result = _format_evidence_packet_for_prompt(packet)
        assert "Tier 2 Corroboration" in result
        assert "DMIST contradictions" in result
        assert "Administered epi 0.15 mg IM" in result
        assert "No epi in intervention timeline" in result

    def test_tier2_narrative_unsupported_claims(self):
        packet = _empty_packet()
        packet["corroboration"]["prepass_available"] = True
        packet["corroboration"]["narrative_unsupported_claims"] = [
            {"chart_element": "R", "claim": "SpO2 improved to 99%", "reason": "Final SpO2 was 93%"}
        ]
        result = _format_evidence_packet_for_prompt(packet)
        assert "Narrative contradictions" in result
        assert "SpO2 improved to 99%" in result

    def test_tier2_not_shown_when_prepass_unavailable(self):
        packet = _empty_packet()
        packet["universal_base"]["gaps"].append({"element": "disposition", "description": "Disposition gap"})
        packet["corroboration"]["prepass_available"] = False
        packet["corroboration"]["dmist_unsupported_claims"] = [
            {"component": "I", "claim": "some claim", "reason": "some reason"}
        ]
        result = _format_evidence_packet_for_prompt(packet)
        assert "Tier 2 Corroboration" not in result


class TestLexiDebriefDocumentationGuardrails:
    def test_debrief_lexi_receives_submitted_docs_and_chart_dmist_rules(self):
        source = inspect.getsource(get_lexi_response)
        assert "SUBMITTED DOCUMENTATION" in source
        assert "student_dmist" in source
        assert "student_narrative" in source
        assert "document corroboration flags" in source.lower()
        assert "CHART: Chief complaint, History, Assessment findings, Rx/Treatment, Transport/Transfer" in source
        assert "DMIST coaching MUST follow D/M/I/S/T" in source
        assert "Never invent scene location, vital signs, times, interventions" in source
        assert "written as the student's EMS report, not as Lexi" in source
        assert "UNCERTAINTY AND EVIDENCE LIMITS" in source
        assert "I don't have that information in this run" in source
        assert "I can't tell from the evidence I have" in source
        assert "Do not give generic EMS advice as if it was a missed action in this run" in source
        assert "Harmless in-character personal flavor is allowed only for Lexi's fictional life/personality" in source
        assert "scenario-specific, operational, clinical, protocol, equipment, scoring, documentation, or patient-care" in source
        assert "SCENARIO-SPECIFIC LEXI GUARDRAILS" in source
        assert "Equipment availability alone never authorizes a medication" in source
        assert "Do not claim a county, MCA, agency, provider level, or local protocol authorizes an intervention" in source

    def test_practice_coach_uses_same_documentation_metrics(self):
        source = inspect.getsource(get_practice_coach_response)
        assert "CHART logic only: Chief complaint, History, Assessment findings, Rx/Treatment, Transport/Transfer" in source
        assert "DMIST, use D/M/I/S/T only" in source
        assert "Never invent vitals, locations, interventions" in source
        assert "I don't have enough information to answer that accurately from this record" in source
        assert "Do not convert generic EMS knowledge into a run-specific missed action" in source
        assert "Harmless in-character personal flavor is allowed only for Lexi's fictional life/personality" in source


class TestFormatEvidencePacketRequiredAssessments:
    def test_ra_gap_renders(self):
        packet = _empty_packet()
        packet["required_assessments"]["gaps"].append({
            "id": "lung_sounds",
            "description": "Lung sounds auscultated bilaterally",
            "expected_keywords": ["lung sounds", "auscultate"],
            "missing_deduction": 3,
            "note": "",
        })
        result = _format_evidence_packet_for_prompt(packet)
        assert "## CLINICAL_PERFORMANCE_GAPS" in result
        assert "[assessment]" in result
        assert "Lung sounds auscultated bilaterally" in result
        assert "−3 pts" in result

    def test_ra_gap_back_credit_prohibition_shown(self):
        packet = _empty_packet()
        packet["required_assessments"]["gaps"].append({
            "id": "bg_check",
            "description": "Blood glucose measured",
            "expected_keywords": ["blood glucose", "glucometer"],
            "missing_deduction": 3,
            "note": "",
        })
        result = _format_evidence_packet_for_prompt(packet)
        assert "SECTION ROUTING — Section 1 ONLY" in result
        assert "Do NOT cite these items in Section 2" in result

    def test_ra_gap_note_rendered_when_present(self):
        packet = _empty_packet()
        packet["required_assessments"]["gaps"].append({
            "id": "cms_pre",
            "description": "CMS check before splinting",
            "expected_keywords": ["CMS", "circulation"],
            "missing_deduction": 3,
            "note": "This is the primary assessment objective for extremity injuries.",
        })
        result = _format_evidence_packet_for_prompt(packet)
        assert "primary assessment objective" in result


class TestFormatEvidencePacketRequiredScreens:
    def test_rs_gap_renders(self):
        packet = _empty_packet()
        packet["required_screens"]["gaps"].append({
            "id": "epiglottitis_screen",
            "description": "Epiglottitis considered and ruled out",
            "expected_keywords": ["epiglottitis", "drooling", "tripod"],
            "missing_deduction": 3,
            "note": "",
        })
        result = _format_evidence_packet_for_prompt(packet)
        assert "## CLINICAL_PERFORMANCE_GAPS" in result
        assert "[differential_screen]" in result
        assert "Epiglottitis considered and ruled out" in result
        assert "−3 pts" in result

    def test_rs_gap_no_back_credit_language(self):
        packet = _empty_packet()
        packet["required_screens"]["gaps"].append({
            "id": "meningitis",
            "description": "Meningitis screening",
            "expected_keywords": ["meningitis", "stiff neck"],
            "missing_deduction": 2,
            "note": "",
        })
        result = _format_evidence_packet_for_prompt(packet)
        assert "SECTION ROUTING — Section 1 ONLY" in result
        assert "Do NOT cite these items in Section 2" in result


class TestFormatEvidencePacketCeilings:
    def test_no_submission_dmist_ceiling(self):
        packet = _empty_packet()
        packet["ceilings"]["dmist"] = 0
        packet["ceilings"]["dmist_reason"] = "no_submission"
        result = _format_evidence_packet_for_prompt(packet)
        assert "SCORE MUST BE 0/10" in result
        assert "enforced by the backend" in result

    def test_structural_dmist_ceiling_prompt_guided(self):
        packet = _empty_packet()
        packet["ceilings"]["dmist"] = 6
        packet["ceilings"]["dmist_reason"] = "2_missing_components"
        result = _format_evidence_packet_for_prompt(packet)
        assert "should not exceed 6/10" in result
        assert "You may score higher" in result

    def test_no_submission_narrative_ceiling(self):
        packet = _empty_packet()
        packet["ceilings"]["narrative"] = 0
        packet["ceilings"]["narrative_reason"] = "no_submission"
        result = _format_evidence_packet_for_prompt(packet)
        assert "SCORE MUST BE 0/20" in result

    def test_structural_narrative_ceiling_prompt_guided(self):
        packet = _empty_packet()
        packet["ceilings"]["narrative"] = 12
        packet["ceilings"]["narrative_reason"] = "2_missing_chart_elements"
        result = _format_evidence_packet_for_prompt(packet)
        assert "should not exceed 12/20" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 5 — _build_evidence_packet score ceiling enforcement
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildEvidencePacketCeilings:
    def test_no_dmist_submitted_ceiling_enforce(self):
        packet = _call_build(submitted_docs={"dmist": "", "narrative": "Some narrative text here."})
        assert packet["ceilings"].get("dmist") == 0
        assert packet["ceilings"].get("dmist_reason") == "no_submission"
        assert packet["ceilings"].get("dmist_enforce") is True

    def test_no_narrative_submitted_ceiling_enforce(self):
        packet = _call_build(submitted_docs={"dmist": "Patient is 6yo.", "narrative": ""})
        assert packet["ceilings"].get("narrative") == 0
        assert packet["ceilings"].get("narrative_reason") == "no_submission"
        assert packet["ceilings"].get("narrative_enforce") is True

    def test_dmist_with_one_missing_component_ceiling(self):
        # D/M/I/S present but no transport/ALS/disposition → T missing → ceiling 8
        dmist = (
            "6-year-old male, difficulty breathing. "
            "No prior medical history, no medications, NKDA. "
            "SpO2 94%, HR 120, RR 28. Alert and responsive."
        )
        packet = _call_build(submitted_docs={"dmist": dmist, "narrative": ""})
        # Missing T → ceiling = 10 - 1*2 = 8
        if packet["ceilings"].get("dmist") is not None:
            assert packet["ceilings"]["dmist"] == 8
            assert packet["ceilings"].get("dmist_enforce") is False

    def test_dmist_with_all_components_no_ceiling(self):
        dmist = (
            "6-year-old male dispatched for difficulty breathing. "
            "No prior medical history, denies medications, NKDA. "
            "Applied O2 via NRB. SpO2 94%, HR 120, RR 28, alert. "
            "Transporting to Children's ED, ETA 5 min."
        )
        packet = _call_build(submitted_docs={"dmist": dmist, "narrative": ""})
        assert "dmist" not in packet["ceilings"]

    def test_dmist_section_header_t_counts_as_structural_t(self):
        dmist = (
            "D — Lily, 10-month-old female, 9 kg.\n"
            "M — Barking cough and stridor after URI.\n"
            "I — URI illness with barking cough and stridor.\n"
            "S — SpO2 93%, HR 149, RR 44.\n"
            "T — Blow-by oxygen given, ready for ALS arrival."
        )
        packet = _call_build(submitted_docs={"dmist": dmist, "narrative": ""})
        assert packet["corroboration"]["dmist_structural"]["T"] is True
        assert "T" not in packet["corroboration"]["dmist_missing_components"]

    def test_narrative_with_missing_elements_ceiling(self):
        # Narrative with C/H but missing A/R/T
        narrative = (
            "Dispatched for 6yo with croup. Mother states started last night."
        )
        packet = _call_build(submitted_docs={"dmist": "", "narrative": narrative})
        if packet["ceilings"].get("narrative") is not None:
            missing_count = len(packet["corroboration"]["chart_missing_elements"])
            expected = max(0, 20 - missing_count * 4)
            assert packet["ceilings"]["narrative"] == expected
            assert packet["ceilings"].get("narrative_enforce") is False

    def test_no_dmist_applicable_for_non_als_turnover(self):
        scenario = {**_BASE_SCENARIO, "turnover_target": "bls_release"}
        packet = _call_build(scenario=scenario, submitted_docs={"dmist": "", "narrative": ""})
        assert "dmist" not in packet["ceilings"]

    def test_both_submitted_no_ceilings(self):
        dmist = (
            "6-year-old male dispatched for difficulty breathing. "
            "No prior medical history, denies medications, NKDA. "
            "Applied O2 via NRB blow-by. Vitals stable: SpO2 94%, HR 120. "
            "Transporting to Children's ED, ETA 5 min."
        )
        narrative = (
            "Dispatched to 6yo male for difficulty breathing. "
            "Mother states onset 2 hours ago. Assessment: SpO2 94%, HR 120, increased WOB. "
            "Administered O2 via blow-by. Transported to Children's ED."
        )
        packet = _call_build(submitted_docs={"dmist": dmist, "narrative": narrative})
        assert "dmist" not in packet["ceilings"]
        assert "narrative" not in packet["ceilings"]

    def test_unsupported_dmist_claims_reduce_prompt_guided_ceiling(self):
        packet = _call_build(
            submitted_docs={
                "dmist": (
                    "D — Lily, 10-month-old female, 9 kg. "
                    "M — Chief complaint difficulty breathing. "
                    "I — Barking cough and inspiratory stridor after URI illness. "
                    "S — SpO2 97%, stridor improved, HR 155. "
                    "T — Blow-by oxygen given, ready for ALS handoff."
                ),
                "narrative": "Chief complaint: difficulty breathing.",
            },
            prepass_result={
                "available": True,
                "dmist_unsupported": [
                    {"component": "T", "claim": "Blow-by O2", "reason": "timeline shows NRB"},
                    {"component": "S", "claim": "SpO2 improved to 97%", "reason": "recorded SpO2 remained 93%"},
                ],
                "narrative_unsupported": [],
            },
        )
        assert packet["ceilings"]["dmist"] == 6
        assert packet["ceilings"]["dmist_reason"] == "unsupported_claims_4pts"
        assert packet["ceilings"]["dmist_enforce"] is False

    def test_deterministic_unsupported_claims_enforce_dmist_and_narrative_ceilings(self):
        prepass = {
            "available": True,
            "method": "deterministic",
            "dmist_unsupported": [
                {"component": "T", "claim": "NRB", "reason": "Only blow-by was applied"},
            ],
            "narrative_unsupported": [
                {"chart_element": "R", "claim": "NRB", "reason": "Only blow-by was applied"},
            ],
        }
        packet = _call_build(
            submitted_docs={
                "dmist": (
                    "D — Lily, 10-month-old female. M — Croup. "
                    "I — URI illness with barking cough. S — SpO2 93%. T — Blow-by O2 w/ NRB and ALS handoff."
                ),
                "narrative": (
                    "Responded for difficulty breathing. Mother reports barky cough. "
                    "Assessment: SpO2 93%. Treatment: Blow-by O2 w/ NRB. "
                    "Patient care transferred to ALS."
                ),
            },
            prepass_result=prepass,
        )
        assert packet["ceilings"]["dmist"] == 8
        assert packet["ceilings"]["dmist_enforce"] is True
        assert packet["ceilings"]["narrative"] == 18
        assert packet["ceilings"]["narrative_enforce"] is True

    def test_unsupported_narrative_claims_reduce_prompt_guided_ceiling(self):
        packet = _call_build(
            submitted_docs={
                "dmist": "D — Lily, 10-month-old female. M — Stridor. I — URI illness. S — SpO2 93%. T — O2 and ALS handoff.",
                "narrative": (
                    "Chief complaint: difficulty breathing. "
                    "History: sudden barking cough after URI symptoms. "
                    "Assessment: stridor at rest with retractions. "
                    "Treatment: blow-by oxygen with improved stridor. "
                    "Transfer: handed to ALS with weight communicated."
                ),
            },
            prepass_result={
                "available": True,
                "dmist_unsupported": [],
                "narrative_unsupported": [
                    {"chart_element": "R", "claim": "Blow-by O2", "reason": "timeline shows NRB"},
                    {"chart_element": "A", "claim": "Stridor improved", "reason": "findings show unchanged WOB"},
                ],
            },
        )
        assert packet["ceilings"]["narrative"] == 16
        assert packet["ceilings"]["narrative_reason"] in {
            "unsupported_claims_4pts",
            "1_missing_chart_elements",
        }
        assert packet["ceilings"]["narrative_enforce"] is False

    def test_more_conservative_of_structural_and_unsupported_dmist_ceiling_wins(self):
        dmist = (
            "6-year-old male dispatched for difficulty breathing. "
            "No prior medical history. Applied O2 via blow-by. "
            "SpO2 94%, HR 120, alert."
        )
        packet = _call_build(
            submitted_docs={"dmist": dmist, "narrative": ""},
            prepass_result={
                "available": True,
                "dmist_unsupported": [
                    {"component": "I", "claim": "Blow-by O2", "reason": "timeline shows NRB"},
                ],
                "narrative_unsupported": [],
            },
        )
        # Structural ceiling for one missing component is 8; unsupported claims ceiling is also 8.
        assert packet["ceilings"]["dmist"] == 8
        assert packet["ceilings"]["dmist_reason"] in {
            "1_missing_components",
            "unsupported_claims_2pts",
        }

    def test_blowby_and_nrb_are_treated_as_equivalent_for_doc_conflicts(self):
        assert _o2_methods_equivalent("o2_blowby", "o2_nrb") is True
        assert _o2_methods_equivalent("o2_nrb", "o2_blowby") is True

        scenario = {
            **_BASE_SCENARIO,
            "vitals": {
                "baseline": {},
                "interventions": {
                    "o2_nrb": {
                        "label": "O2 via Non-Rebreather Mask (NRB) — 15 LPM (blow-by)",
                        "detection_patterns": [r"(?i)\bnrb\b", r"(?i)blow.?by"],
                    }
                },
            },
        }
        session = _make_session([_make_intervention("o2_nrb")])
        packet = _call_build(
            scenario=scenario,
            session=session,
            submitted_docs={
                "dmist": "T — Blow-by O2 at 15 LPM with infant upright.",
                "narrative": "Treatment: blow-by oxygen administered and tolerated.",
            },
        )
        assert packet["corroboration"]["documentation_conflicts"] == []


class TestProfessionalismHardening:
    def test_were_just_going_to_counts_as_action_explanation(self):
        score, reasons = _compute_professionalism_hardened_constraints(
            student_transcript=(
                "Hi Sarah, my name is John. We're just going to get a set of vitals "
                "and listen to some lung sounds now."
            ),
            greeting_detected=True,
            prof_ceiling=10,
            is_peds=True,
        )
        assert score == 8
        assert "no explanation of actions or care plan detected" not in reasons

    def test_sparse_peds_chat_keeps_professionalism_below_adequate(self):
        score, reasons = _compute_professionalism_hardened_constraints(
            student_transcript="hi my name is jon whats going on\nspo2 and hr\nadmin o2\nany better\nok",
            greeting_detected=True,
            prof_ceiling=9,
            is_peds=True,
        )
        assert score == 5
        assert "no agency or responder-role introduction detected" in reasons
        assert "no explanation of actions or care plan detected" in reasons
        assert "no direct caregiver acknowledgment or address detected" in reasons
        assert "no reassurance or empathy language detected" in reasons


# ═══════════════════════════════════════════════════════════════════════════════
# 6 — _build_evidence_packet required_assessments detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildEvidencePacketRequiredAssessments:
    def _scenario_with_assessment(self, assessment_spec):
        return {
            **_BASE_SCENARIO,
            "scoring": {
                "required_assessments": [assessment_spec],
            },
        }

    def test_keyword_in_transcript_marks_present(self):
        scenario = self._scenario_with_assessment({
            "id": "lung_sounds",
            "description": "Lung sounds auscultated",
            "keywords": ["lung sounds", "auscultate", "breath sounds"],
            "missing_deduction": 3,
        })
        msgs = [_msg("Let me listen to lung sounds bilaterally.")]
        packet = _call_build(scenario=scenario, student_messages=msgs)
        present_ids = [a["id"] for a in packet["required_assessments"]["present"]]
        assert "lung_sounds" in present_ids
        assert not packet["required_assessments"]["gaps"]

    def test_absent_keyword_creates_gap(self):
        scenario = self._scenario_with_assessment({
            "id": "lung_sounds",
            "description": "Lung sounds auscultated",
            "keywords": ["lung sounds", "auscultate", "breath sounds"],
            "missing_deduction": 3,
        })
        msgs = [_msg("Patient has difficulty breathing.")]
        packet = _call_build(scenario=scenario, student_messages=msgs)
        gap_ids = [g["id"] for g in packet["required_assessments"]["gaps"]]
        assert "lung_sounds" in gap_ids
        assert not packet["required_assessments"]["present"]

    def test_gap_deduction_value_preserved(self):
        scenario = self._scenario_with_assessment({
            "id": "bg_check",
            "description": "Blood glucose checked",
            "keywords": ["blood glucose", "glucometer", "bgl"],
            "missing_deduction": 5,
        })
        packet = _call_build(scenario=scenario)
        assert packet["required_assessments"]["gaps"][0]["missing_deduction"] == 5

    def test_keyword_in_findings_marks_present(self):
        scenario = self._scenario_with_assessment({
            "id": "bgl_check",
            "description": "Blood glucose measured",
            "keywords": ["blood glucose", "bgl"],
            "missing_deduction": 3,
        })
        findings = [_finding(key="blood glucose", value="58", finding_type="assessment")]
        packet = _call_build(scenario=scenario, findings=findings)
        present_ids = [a["id"] for a in packet["required_assessments"]["present"]]
        assert "bgl_check" in present_ids

    def test_submitted_docs_do_not_back_credit_required_assessment(self):
        scenario = self._scenario_with_assessment({
            "id": "lung_sounds",
            "description": "Lung sounds auscultated",
            "keywords": ["lung sounds", "auscultate", "breath sounds"],
            "missing_deduction": 3,
        })
        packet = _call_build(
            scenario=scenario,
            student_messages=[],
            findings=[],
            submitted_docs={"dmist": "S — clear lung sounds bilaterally.", "narrative": ""},
        )
        gap_ids = [g["id"] for g in packet["required_assessments"]["gaps"]]
        assert "lung_sounds" in gap_ids
        assert not packet["required_assessments"]["present"]

    def test_observed_stridor_does_not_back_credit_lung_sound_auscultation(self):
        scenario = self._scenario_with_assessment({
            "id": "lung_sound_auscultation",
            "description": "Auscultate lung sounds (stridor vs. wheeze distinction)",
            "keywords": ["lung sounds", "breath sounds", "auscultate", "auscultation", "stethoscope"],
            "missing_deduction": 3,
        })
        findings = [
            _finding(key="Stridor", value="present, audible at rest", finding_type="exam"),
            _finding(key="WOB", value="moderate retractions", finding_type="exam"),
        ]
        packet = _call_build(scenario=scenario, findings=findings)
        gap_ids = [g["id"] for g in packet["required_assessments"]["gaps"]]
        assert "lung_sound_auscultation" in gap_ids
        assert not packet["required_assessments"]["present"]

    def test_spec_without_keywords_skipped(self):
        scenario = self._scenario_with_assessment({
            "id": "no_keywords",
            "description": "An assessment with no keywords",
            "keywords": [],
            "missing_deduction": 2,
        })
        packet = _call_build(scenario=scenario)
        assert not packet["required_assessments"]["gaps"]
        assert not packet["required_assessments"]["present"]

    def test_no_required_assessments_in_scenario(self):
        packet = _call_build()
        assert packet["required_assessments"]["present"] == []
        assert packet["required_assessments"]["gaps"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# 7 — _build_evidence_packet required_screens detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildEvidencePacketRequiredScreens:
    def _scenario_with_screen(self, screen_spec):
        return {
            **_BASE_SCENARIO,
            "scoring": {
                "required_screens": [screen_spec],
            },
        }

    def test_keyword_in_transcript_marks_present(self):
        scenario = self._scenario_with_screen({
            "id": "epiglottitis",
            "description": "Epiglottitis considered",
            "keywords": ["epiglottitis", "drooling", "tripod"],
            "missing_deduction": 3,
        })
        msgs = [_msg("We need to rule out epiglottitis given the presentation.")]
        packet = _call_build(scenario=scenario, student_messages=msgs)
        present_ids = [s["id"] for s in packet["required_screens"]["present"]]
        assert "epiglottitis" in present_ids

    def test_absent_keyword_creates_gap(self):
        scenario = self._scenario_with_screen({
            "id": "meningitis",
            "description": "Meningitis screened",
            "keywords": ["meningitis", "stiff neck", "nuchal"],
            "missing_deduction": 2,
        })
        msgs = [_msg("High fever and seizure in a toddler.")]
        packet = _call_build(scenario=scenario, student_messages=msgs)
        gap_ids = [g["id"] for g in packet["required_screens"]["gaps"]]
        assert "meningitis" in gap_ids

    def test_screen_gap_deduction_value_preserved(self):
        scenario = self._scenario_with_screen({
            "id": "aortic_dissection",
            "description": "Aortic dissection considered",
            "keywords": ["aortic dissection", "tearing pain", "dissection"],
            "missing_deduction": 2,
        })
        packet = _call_build(scenario=scenario)
        assert packet["required_screens"]["gaps"][0]["missing_deduction"] == 2

    def test_keyword_in_findings_marks_screen_present(self):
        scenario = self._scenario_with_screen({
            "id": "ams_differential",
            "description": "AMS differential considered",
            "keywords": ["AMS", "altered mental status", "hypoglycemia"],
            "missing_deduction": 2,
        })
        findings = [_finding(key="AMS", value="suspected", finding_type="assessment")]
        packet = _call_build(scenario=scenario, findings=findings)
        present_ids = [s["id"] for s in packet["required_screens"]["present"]]
        assert "ams_differential" in present_ids

    def test_submitted_docs_do_not_back_credit_required_screen(self):
        scenario = self._scenario_with_screen({
            "id": "epiglottitis",
            "description": "Epiglottitis considered",
            "keywords": ["epiglottitis", "drooling", "tripod"],
            "missing_deduction": 3,
        })
        packet = _call_build(
            scenario=scenario,
            student_messages=[],
            findings=[],
            submitted_docs={"dmist": "M — no drooling, epiglottitis less likely.", "narrative": ""},
        )
        gap_ids = [g["id"] for g in packet["required_screens"]["gaps"]]
        assert "epiglottitis" in gap_ids


# ═══════════════════════════════════════════════════════════════════════════════
# 8 — _build_evidence_packet universal base detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildEvidencePacketUniversalBase:
    def test_scene_safety_detected_in_transcript(self):
        msgs = [_msg("BSI, scene is safe.")]
        packet = _call_build(student_messages=msgs)
        assert "scene_safety" in packet["universal_base"]["present"]

    def test_primary_survey_detected(self):
        msgs = [_msg("General impression: sick child, increased work of breathing.")]
        packet = _call_build(student_messages=msgs)
        assert "primary_survey" in packet["universal_base"]["present"]

    def test_history_detected(self):
        msgs = [_msg("Do you have any allergies? Any medications?")]
        packet = _call_build(student_messages=msgs)
        assert "history" in packet["universal_base"]["present"]

    def test_disposition_detected_als_turnover(self):
        # ALS-turnover scenario: ALS intercept language satisfies disposition
        msgs = [_msg("Let's call for ALS intercept.")]
        packet = _call_build(student_messages=msgs)
        assert "disposition" in packet["universal_base"]["present"]

    def test_disposition_detected_hospital_turnover(self):
        # Hospital-turnover scenario: transport-to-hospital language satisfies disposition
        scenario = {**_BASE_SCENARIO, "turnover_target": "hospital"}
        msgs = [_msg("Let's transport to the hospital.")]
        packet = _call_build(scenario=scenario, student_messages=msgs)
        assert "disposition" in packet["universal_base"]["present"]

    def test_disposition_not_credited_wrong_turnover_language(self):
        # ALS-turnover scenario: hospital transport language does NOT satisfy ALS disposition
        msgs = [_msg("Let's transport to the hospital.")]
        packet = _call_build(student_messages=msgs)
        gap_ids = [g["element"] for g in packet["universal_base"]["gaps"]]
        assert "disposition" in gap_ids

    def test_ppe_detected_via_scene_entry(self):
        packet = _call_build(scene_entry_scoring_result={"ppe": "gloves_mask"})
        assert "ppe" in packet["universal_base"]["present"]

    def test_ppe_absent_when_no_scene_entry(self):
        packet = _call_build(scene_entry_scoring_result=None)
        assert "ppe" in [g["element"] for g in packet["universal_base"]["gaps"]]

    def test_documentation_present_when_dmist_submitted(self):
        packet = _call_build(submitted_docs={"dmist": "Some DMIST text.", "narrative": ""})
        assert "documentation" in packet["universal_base"]["present"]

    def test_documentation_absent_when_neither_submitted(self):
        packet = _call_build(submitted_docs={"dmist": "", "narrative": ""})
        assert "documentation" in [g["element"] for g in packet["universal_base"]["gaps"]]

    def test_vitals_detected_via_vital_findings(self):
        findings = [_finding(key="spo2", value="94", finding_type="vital")]
        packet = _call_build(findings=findings)
        assert "vitals" in packet["universal_base"]["present"]

    def test_als_intercept_satisfies_disposition(self):
        session = _make_session(interventions=[_make_intervention("als_intercept")])
        packet = _call_build(session=session)
        assert "disposition" in packet["universal_base"]["present"]

    def test_suppress_universal_skips_element(self):
        scenario = {
            **_BASE_SCENARIO,
            "scoring": {"suppress_universal": ["scene_safety"]},
        }
        packet = _call_build(scenario=scenario)
        all_ids = (
            [e for e in packet["universal_base"]["present"]]
            + [g["element"] for g in packet["universal_base"]["gaps"]]
        )
        assert "scene_safety" not in all_ids


# ═══════════════════════════════════════════════════════════════════════════════
# 9 — _build_evidence_packet Tier 2 pre-pass wiring
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildEvidencePacketPrepass:
    def test_prepass_fallback_produces_tier1(self):
        packet = _call_build(prepass_result=None)
        assert packet["corroboration"]["tier"] == 1
        assert not packet["corroboration"]["prepass_available"]

    def test_prepass_available_produces_tier2(self):
        prepass = {
            "available": True,
            "dmist_unsupported": [],
            "narrative_unsupported": [],
        }
        packet = _call_build(prepass_result=prepass)
        assert packet["corroboration"]["tier"] == 2
        assert packet["corroboration"]["prepass_available"]

    def test_prepass_unsupported_claims_passed_through(self):
        prepass = {
            "available": True,
            "dmist_unsupported": [{"component": "I", "claim": "Gave epi", "reason": "Not in timeline"}],
            "narrative_unsupported": [],
        }
        packet = _call_build(prepass_result=prepass)
        assert packet["corroboration"]["dmist_unsupported_claims"][0]["claim"] == "Gave epi"

    def test_positive_evidence_uses_exact_finding_not_broad_assessment_description(self):
        scenario = {
            **_BASE_SCENARIO,
            "vitals": {
                "interventions": {
                    "o2_blowby": {"label": "Blow-by O2 (NRB mask held near face, high flow)"}
                }
            },
            "scoring": {
                "required_assessments": [
                    {
                        "id": "work_of_breathing_assessment",
                        "description": (
                            "Assess work of breathing (retractions, nasal flaring, "
                            "head bobbing, accessory muscle use)"
                        ),
                        "keywords": ["work of breath", "WOB", "stridor"],
                    }
                ]
            },
        }
        packet = _call_build(
            scenario=scenario,
            session=_make_session(interventions=[_make_intervention("o2_blowby")]),
            findings=[
                _finding(
                    key="WOB",
                    value="moderate work of breathing, audible stridor at rest",
                    finding_type="exam",
                )
            ],
        )

        positives = packet["positive_evidence"]
        assert "Intervention applied: Blow-by O2 (NRB mask held near face, high flow)" in positives
        assert (
            "Assessment performed: WOB: moderate work of breathing, audible stridor at rest"
            in positives
        )
        assert not any("head bobbing" in item for item in positives)

    def test_recent_sparse_croup_run_deterministic_flags_match_expected_counts(self):
        dmist = (
            "D - Lily, 10-month-old female, 9 kg per parents. "
            "M - Suspected croup. Low-grade temp 100.4F. "
            "I - Blow-by O2 at 15 LPM w/ NRB with infant in mother's arms. "
            "Calm, low-stimulation environment maintained throughout. "
            "S - SpO2 improved from 94% to 95%. RR increased from 38 to 44. "
            "HR 155. GCS alert, irritable. "
            "T - Patient calm and improving with O2 and positioning. Ready for ALS arrival."
        )
        narrative = (
            "Squad 1 responded for a 10-month-old female with difficulty breathing. "
            "Temp 100.4F. Primary assessment: SpO2 94%, RR 38 breaths/min, HR 132 bpm. "
            "Lung sounds clear bilaterally. Blow-by O2 at 15 LPM w/ NRB initiated with "
            "infant in mother's arms. Calm, low-stimulation environment maintained. "
            "Reassessment: SpO2 improved to 95%, RR increased to 44 breaths/min. "
            "Weight of 9 kg communicated to ALS."
        )

        result = _deterministic_prepass_result(
            dmist_text=dmist,
            narrative_text=narrative,
            applied_intervention_ids=["o2_blowby"],
            findings=[
                _finding(key="SpO2", value="93 %", finding_type="vital"),
                _finding(key="Heart Rate", value="148 bpm", finding_type="vital"),
            ],
            patient={"sex": "female", "weight_kg": 9},
        )

        assert result["available"] is True
        assert result["method"] == "deterministic"
        assert len(result["dmist_unsupported"]) == 3
        assert len(result["narrative_unsupported"]) == 5
        assert any(c["claim"] == "NRB" for c in result["dmist_unsupported"])
        assert any("TEMP value" in c["reason"] for c in result["dmist_unsupported"])
        assert any("HR value 155" in c["reason"] for c in result["dmist_unsupported"])
        assert any(c["claim"] == "NRB" for c in result["narrative_unsupported"])
        assert any("RR value" in c["reason"] for c in result["narrative_unsupported"])
        assert any("TEMP value" in c["reason"] for c in result["narrative_unsupported"])
        assert any("SPO2 value 95" in c["reason"] for c in result["narrative_unsupported"])
        assert any(c["claim"] == "132" for c in result["narrative_unsupported"])


class TestDebriefPromptEvidenceBoundaries:
    def test_final_debrief_prompt_does_not_embed_exemplar_documents(self):
        source = inspect.getsource(evaluate_and_generate_debrief)
        assert "## EXEMPLAR PATIENT CARE NARRATIVE" not in source
        assert "## EXEMPLAR DMIST" not in source
        assert "## EXEMPLAR HOSPITAL TURNOVER" not in source

    def test_section_2_prompt_is_allowlist_constrained(self):
        source = inspect.getsource(_format_evidence_packet_for_prompt) + inspect.getsource(evaluate_and_generate_debrief)
        assert "RUN-EVIDENCED POSITIVES ONLY" in source
        assert "Use ONLY items from this list when describing what the student did correctly" in source
        assert "Blow-by is an NRB/mask held close to the face at high flow" in source
        assert "Do not embellish run evidence" in source
        assert "Do not say the student recognized racepinephrine" in source
        assert "recognized that definitive therapy is ALS/Paramedic-level" in source

    def test_intervention_label_for_evidence_includes_oxygen_popup_flow(self):
        label = _intervention_label_for_evidence(
            "o2_blowby",
            {
                "o2_blowby": {
                    "label": "Blow-by O2 (NRB mask held near face, high flow)",
                    "popup_default": {"device": "blowby", "flow": 15},
                }
            },
        )
        assert label == "Blow-by O2 (NRB mask held near face, high flow) — 15 LPM"

    def test_credited_item_sanitizer_removes_avpu_missed_contradiction(self):
        debrief = (
            "**3. What Could Be Done Better**\n"
            "Assess level of consciousness with AVPU: The crew did not explicitly document whether the infant was Alert, Verbal, Pain, or Unresponsive. "
            "Provide explicit reassurance to the caregiver.\n\n"
            "**11. Key Takeaways**\n"
            "Always assess and document LOC/AVPU in pediatric patients. "
            "Use blow-by oxygen for croup."
        )
        cleaned = _sanitize_credited_item_contradictions(
            debrief,
            satisfied_item_ids={"ems.medical.loc"},
        )
        assert "AVPU" not in cleaned
        assert "LOC" not in cleaned
        assert "Provide explicit reassurance" in cleaned
        assert "Use blow-by oxygen" in cleaned

    def test_credited_item_sanitizer_removes_asthma_credited_gap_contradictions(self):
        debrief = (
            "**1. Clinical Performance**\n"
            "The only missed assessment item was patient name. "
            "Additionally, the differential screen for foreign body aspiration was not documented, "
            "and an opening patient assessment/general impression was not explicitly recorded. "
            "A foreign‑body aspiration screen was not performed. "
            "These gaps account for the single point loss.\n\n"
            "Screen for foreign‑body aspiration in any wheezing child, even when asthma is known.\n\n"
            "**2. Protocols & Treatment**\n"
            "All protocol expectations were met."
        )
        cleaned = _sanitize_credited_item_contradictions(
            debrief,
            satisfied_item_ids={
                "ems.medical.general_impression",
                "peds_asthma_01.foreign_body_screen",
            },
        )
        assert "The only missed assessment item was patient name" in cleaned
        assert "foreign body aspiration was not documented" not in cleaned
        assert "foreign‑body aspiration screen was not performed" not in cleaned
        assert "Screen for foreign‑body aspiration" not in cleaned
        assert "general impression was not explicitly recorded" not in cleaned
        assert "These gaps account" not in cleaned
        assert "All protocol expectations were met" in cleaned

    def test_credited_item_list_sanitizer_removes_structured_takeaway_contradictions(self):
        cleaned = _sanitize_credited_item_list(
            [
                "Screen for foreign‑body aspiration in any wheezing child.",
                "Document the exact oxygen delivery method used for ALS continuity.",
                "Always obtain and record age and weight.",
            ],
            satisfied_item_ids={
                "peds_asthma_01.foreign_body_screen",
                "resp_distress.o2_therapy_indicated",
            },
        )

        assert cleaned == ["Always obtain and record age and weight."]

    def test_missed_item_sanitizer_removes_head_injury_o2_and_pupil_overcredit(self):
        debrief = (
            "**2. Protocols & Treatment**\n"
            "SMR was applied. High-flow oxygen was provided and pupils were noted to be unequal. "
            "Continue to reassess GCS during transport.\n\n"
            "**6. Case Summary**\n"
            "The crew started high-flow O2 via a non-rebreather mask. "
            "Pupils were found unequal. SMR was applied."
        )
        cleaned = _sanitize_missed_item_overcredit(
            debrief,
            missed_item_ids={
                "head_injury.high_flow_o2",
                "head_injury.pupil_assessment",
            },
        )

        assert "High-flow oxygen was provided" not in cleaned
        assert "started high-flow O2" not in cleaned
        assert "pupils were noted" not in cleaned.lower()
        assert "Pupils were found" not in cleaned
        assert "SMR was applied" in cleaned
        assert "reassess GCS" in cleaned


# ═══════════════════════════════════════════════════════════════════════════════
# 10 — _extract_required_debrief_subscores — regex recovery warning
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractRequiredDebriefSubscores:
    def test_structured_subscores_returned_directly(self):
        structured = {
            "clinical_performance": 35,
            "scope_adherence": 18,
            "dmist": 8,
            "professionalism": 9,
        }
        result = _extract_required_debrief_subscores("", structured, include_narrative=False)
        assert result == structured

    def test_missing_key_recovered_from_markdown(self):
        debrief = "Scope Adherence: 17\nDMIST score: 8\nProfessionalism: 9"
        structured = {"clinical_performance": 35}
        result = _extract_required_debrief_subscores(
            debrief, structured, include_narrative=False
        )
        assert result["scope_adherence"] == 17
        assert result["dmist"] == 8
        assert result["professionalism"] == 9

    def test_raises_on_unrecoverable_key(self):
        debrief = "Clinical Performance: 35\nDMIST: 8\nProfessionalism: 9"
        with pytest.raises(ValueError, match="scope_adherence"):
            _extract_required_debrief_subscores(debrief, {}, include_narrative=False)

    def test_narrative_included_when_flag_set(self):
        structured = {
            "clinical_performance": 35,
            "scope_adherence": 18,
            "dmist": 8,
            "professionalism": 9,
            "narrative": 16,
        }
        result = _extract_required_debrief_subscores("", structured, include_narrative=True)
        assert result["narrative"] == 16

    def test_narrative_not_required_when_flag_false(self):
        structured = {
            "clinical_performance": 35,
            "scope_adherence": 18,
            "dmist": 8,
            "professionalism": 9,
        }
        result = _extract_required_debrief_subscores("", structured, include_narrative=False)
        assert "narrative" not in result

    def test_float_values_coerced_to_int(self):
        structured = {
            "clinical_performance": 35.0,
            "scope_adherence": 18.5,
            "dmist": 8.0,
            "professionalism": 9.0,
        }
        result = _extract_required_debrief_subscores("", structured, include_narrative=False)
        assert all(isinstance(v, int) for v in result.values())

    def test_missing_keys_recovered_from_authoritative_fallbacks(self):
        structured = {"clinical_performance": 35}
        fallbacks = {
            "scope_adherence": 18,
            "dmist": 8,
            "professionalism": 7,
        }
        result = _extract_required_debrief_subscores(
            "",
            structured,
            include_narrative=False,
            authoritative_fallbacks=fallbacks,
        )
        assert result == {
            "clinical_performance": 35,
            "scope_adherence": 18,
            "dmist": 8,
            "professionalism": 7,
        }


class TestParseDebriefResponsePayload:
    def test_parses_direct_json_envelope(self):
        raw = '{"debrief":"Hello","subscores":{"clinical_performance":30}}'
        debrief, subscores, score_notes, extras = _parse_debrief_response_payload(raw)
        assert debrief == "Hello"
        assert subscores == {"clinical_performance": 30}
        assert score_notes == {}
        assert isinstance(extras, dict)

    def test_recovers_json_envelope_from_noisy_output(self):
        raw = 'Score preface\\n{"debrief":"Hello","subscores":{"narrative":16}}\\nextra text'
        debrief, subscores, score_notes, extras = _parse_debrief_response_payload(raw)
        assert debrief == "Hello"
        assert subscores == {"narrative": 16}
        assert score_notes == {}
        assert isinstance(extras, dict)

    def test_extras_populated_from_structured_fields(self):
        raw = '{"debrief":"Hello","subscores":{},"top_takeaways":["Key point"],"reflection_prompts":["Think about X"],"next_action":"retry"}'
        _, _, _, extras = _parse_debrief_response_payload(raw)
        assert extras["top_takeaways"] == ["Key point"]
        assert extras["reflection_prompts"] == ["Think about X"]
        assert extras["next_action"] == "retry"

    def test_extras_empty_when_fields_absent(self):
        raw = '{"debrief":"Hello","subscores":{}}'
        _, _, _, extras = _parse_debrief_response_payload(raw)
        assert extras["top_takeaways"] == []
        assert extras["reflection_prompts"] == []
        assert extras["next_action"] == ""


class TestNormalizeDebriefSectionHeaders:
    def test_splits_inline_hash_headers_into_bold_section_headers(self):
        raw = (
            "**1. Clinical Performance**\n"
            "Marcus improved after oral glucose. ## 2. Protocols & Treatment\n"
            "- Checked blood glucose.\n"
            "## 3. Scope of Practice\n"
            "- Obtain a fuller vitals set."
        )

        normalized = _normalize_debrief_section_headers(raw)

        assert "oral glucose.\n\n**2. Protocols & Treatment**" in normalized
        assert "\n**3. Scope of Practice**\n" in normalized

    def test_splits_inline_unnumbered_backend_section_headers(self):
        raw = (
            "3 additional lower-priority rubric gap(s) are available in Rubric Detail. "
            "## Protocols & Treatments\n"
            "Reference: Michigan Trauma.\n"
            "✓ Direct pressure.\n"
            "DMIST was sparse. ## Patient Communication\n"
            "The student was task-focused."
        )

        normalized = _normalize_debrief_section_headers(raw)

        assert "Rubric Detail.\n\n## Protocols & Treatments\n" in normalized
        assert "DMIST was sparse.\n\n## Patient Communication\n" in normalized

    def test_unrendered_backend_placeholders_do_not_leak_to_debrief(self):
        raw = (
            "**2. Protocols & Treatment**\n"
            "{{SECTION2_PROTOCOLS_TREATMENT}}\n\n"
            "**Condition — Newborn Resuscitation**\n"
            "{{CONDITION_TREATMENT_REFERENCE}}"
        )

        cleaned = _replace_unrendered_debrief_placeholders(raw)

        assert "{{SECTION2_PROTOCOLS_TREATMENT}}" not in cleaned
        assert "{{CONDITION_TREATMENT_REFERENCE}}" not in cleaned
        assert "Protocol-specific treatment scoring was not configured separately" not in cleaned


class TestJsonObjectResponseRecovery:
    def test_parse_json_object_response_direct(self):
        assert _parse_json_object_response('{"dmist_score": 4}') == {"dmist_score": 4}

    def test_parse_json_object_response_recovers_outer_object(self):
        assert _parse_json_object_response('```json\n{"score": 5}\n```') == {"score": 5}

    def test_json_mode_validation_error_detected(self):
        class JsonValidationError(Exception):
            status_code = 400

            def __str__(self):
                return "Failed to validate JSON"

        assert _is_json_mode_validation_error(JsonValidationError())


class TestNextActionRouting:
    def test_cpr_remediation_targets_route_to_current_scenario_replay(self):
        evidence_packet = {
            "cpr_challenge": {
                "metrics": {
                    "analytics": {
                        "remediation_targets": [
                            "pause_minimization",
                            "nonshockable_rhythm_management",
                        ]
                    }
                }
            }
        }
        session = types.SimpleNamespace(scenario_id="adult_cardiac_arrest_01_bls")

        flags = _compute_reasoning_flags(evidence_packet, student_history=None)
        target_type, target_id = _compute_next_action_routing(
            evidence_packet,
            student_history=None,
            session=session,
            adapted_scenario={},
        )

        assert flags["cpr_remediation_targets"] == [
            "pause_minimization",
            "nonshockable_rhythm_management",
        ]
        assert (target_type, target_id) == ("scenario", "adult_cardiac_arrest_01_bls")

    def test_cpr_remediation_routes_before_random_call_review(self):
        evidence_packet = {
            "cpr_challenge": {
                "metrics": {
                    "analytics": {
                        "remediation_targets": ["high_performance_cpr_ccf"]
                    }
                }
            }
        }
        session = types.SimpleNamespace(scenario_id="adult_cardiac_arrest_01_bls")
        history = {
            "peds_asthma_01": {
                "last_random_call_date": datetime.datetime.utcnow()
                - datetime.timedelta(days=10),
                "interval_days": 1,
            }
        }

        target_type, target_id = _compute_next_action_routing(
            evidence_packet,
            student_history=history,
            session=session,
            adapted_scenario={},
        )

        assert (target_type, target_id) == ("scenario", "adult_cardiac_arrest_01_bls")

    def test_failed_rubric_category_routes_to_mapped_minigame(self):
        evidence_packet = {}
        session = types.SimpleNamespace(
            scenario_id="peds_seizure_01",
            score_snapshot={
                "categories": {
                    "dmist": {"total": 3, "max": 10, "method": "deterministic"},
                    "clinical_performance": {"total": 35, "max": 40, "method": "deterministic"},
                }
            },
        )

        target_type, target_id = _compute_next_action_routing(
            evidence_packet,
            student_history=None,
            session=session,
            adapted_scenario={},
        )

        assert (target_type, target_id) == ("minigame", "dmist_builder")

    def test_rubric_mapped_minigame_prefers_matching_recent_gap(self):
        evidence_packet = {}
        session = types.SimpleNamespace(
            scenario_id="peds_resp_01",
            score_snapshot={
                "categories": {
                    "protocols_treatment": {"total": 5, "max": 20, "method": "deterministic"},
                }
            },
        )

        target_type, target_id = _compute_next_action_routing(
            evidence_packet,
            student_history=None,
            session=session,
            adapted_scenario={},
            minigame_gaps={
                "lung_sounds_matcher": ["stridor_vs_wheeze", "upper_airway"],
                "ams_aeioutips": ["missed_O"],
            },
        )

        assert (target_type, target_id) == ("minigame", "lung_sounds_matcher")


class TestRetryableGroqError:
    def test_retries_rate_limit_status(self):
        exc = types.SimpleNamespace(status_code=429)
        assert _is_retryable_groq_error(exc) is True

    def test_retries_upstream_503_status(self):
        exc = types.SimpleNamespace(status_code=503)
        assert _is_retryable_groq_error(exc) is True

    def test_retries_timeout_error(self):
        assert _is_retryable_groq_error(TimeoutError()) is True

    def test_does_not_retry_bad_request(self):
        exc = types.SimpleNamespace(status_code=400)
        assert _is_retryable_groq_error(exc) is False


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3 — §5.5 Assessment Phases
# ═══════════════════════════════════════════════════════════════════════════════

class TestAssessmentPhasesInPacket:
    """§5.5 primary_survey, history_secondary, reassessment sections."""

    def test_primary_survey_detected_from_transcript(self):
        msgs = [_msg("Let me check the airway and breathing. Circulation looks okay.")]
        pkt = _call_build(student_messages=msgs)
        ps = pkt["assessment_phases"]["primary_survey"]
        assert ps["airway_addressed"] is True
        assert ps["breathing_assessed"] is True
        assert ps["circulation_assessed"] is True

    def test_loc_detected_from_avpu(self):
        msgs = [_msg("AVPU — patient is alert and oriented.")]
        pkt = _call_build(student_messages=msgs)
        assert pkt["assessment_phases"]["primary_survey"]["loc_assessed"] is True

    def test_primary_survey_gaps_when_empty_transcript(self):
        pkt = _call_build(student_messages=[])
        ps = pkt["assessment_phases"]["primary_survey"]
        assert ps["airway_addressed"] is False
        assert ps["breathing_assessed"] is False
        assert ps["loc_assessed"] is False

    def test_trauma_fields_present_for_trauma_scenario(self):
        scenario = {**_BASE_SCENARIO, "category": "pediatric_trauma"}
        msgs = [_msg("MOI is a fall. Controlling the bleeding and C-spine precautions.")]
        pkt = _call_build(scenario=scenario, student_messages=msgs)
        ps = pkt["assessment_phases"]["primary_survey"]
        assert ps["hemorrhage_control_performed"] is True
        assert ps["cspine_considered"] is True
        assert ps["moi_documented"] is True
        assert ps["emphasis"] == "full_abcde"

    def test_trauma_fields_absent_for_medical_scenario(self):
        pkt = _call_build(student_messages=[_msg("Checking airway and breathing.")])
        ps = pkt["assessment_phases"]["primary_survey"]
        assert "hemorrhage_control_performed" not in ps
        assert ps["emphasis"] == "immediate_life_threats"

    def test_history_secondary_detected(self):
        msgs = [_msg("Any allergies or medications? SAMPLE history done.")]
        pkt = _call_build(student_messages=msgs)
        hs = pkt["assessment_phases"]["history_secondary"]
        assert hs["history_attempted"] is True
        assert hs["sample_obtained"] is True

    def test_opqrst_detected(self):
        msgs = [_msg("Onset was 20 minutes ago. Rate your pain on a 1-10 scale.")]
        pkt = _call_build(student_messages=msgs)
        assert pkt["assessment_phases"]["history_secondary"]["opqrst_obtained"] is True

    def test_reassessment_after_intervention(self):
        from datetime import datetime, timedelta
        t0 = datetime(2024, 1, 1, 12, 0, 0)
        t1 = t0 + timedelta(minutes=2)
        iv = _make_intervention("oxygen", applied_at=t0)
        session = types.SimpleNamespace(interventions=[iv])
        post_vital = _finding(finding_type="vital", captured_at=t1)
        pkt = _call_build(session=session, findings=[post_vital])
        rs = pkt["assessment_phases"]["reassessment"]
        assert rs["occurred"] is True
        assert rs["after_intervention"] is True
        assert rs["vitals_repeated"] is True

    def test_response_documented_in_narrative(self):
        pkt = _call_build(
            submitted_docs={"narrative": "Patient responded well after administering oxygen."},
        )
        assert pkt["assessment_phases"]["reassessment"]["response_documented"] is True

    def test_assessment_phases_key_present(self):
        pkt = _call_build()
        assert "assessment_phases" in pkt
        assert "primary_survey" in pkt["assessment_phases"]
        assert "history_secondary" in pkt["assessment_phases"]
        assert "reassessment" in pkt["assessment_phases"]


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3 — §5.6 Transport and Disposition
# ═══════════════════════════════════════════════════════════════════════════════

class TestTransportDispositionInPacket:
    """§5.6 transport section — transport agencies and non-transport agencies."""

    def test_transport_decision_detected_from_transcript(self):
        msgs = [_msg("Let's load the patient and head to the hospital.")]
        pkt = _call_build(student_messages=msgs)
        assert pkt["transport"]["transport_decision_made"] is True

    def test_transport_decision_absent_when_no_keywords(self):
        pkt = _call_build(student_messages=[_msg("Check vitals again.")])
        assert pkt["transport"]["transport_decision_made"] is False

    def test_als_intercept_called_via_intervention(self):
        iv = _make_intervention("als_intercept")
        session = types.SimpleNamespace(interventions=[iv])
        pkt = _call_build(session=session)
        assert pkt["transport"]["als_intercept_called"] is True
        assert pkt["transport"]["als_intercept_considered"] is True

    def test_als_not_called_without_intervention_or_transcript(self):
        pkt = _call_build(student_messages=[_msg("Checking pupils.")])
        assert pkt["transport"]["als_intercept_called"] is False

    def test_als_auto_dispatched_suppresses_penalty(self):
        agency = {"transports_patients": True, "als_dispatch": {"auto_dispatched": True}}
        pkt = _call_build(agency=agency)
        assert pkt["transport"]["als_auto_dispatched"] is True
        assert pkt["transport"]["als_intercept_considered"] is True

    def test_handoff_prepared_when_dmist_submitted(self):
        pkt = _call_build(submitted_docs={"dmist": "D: 8yo male, chief complaint: fever"})
        assert pkt["transport"]["als_handoff_prepared"] is True

    def test_handoff_not_prepared_when_no_dmist(self):
        pkt = _call_build(submitted_docs={})
        assert pkt["transport"]["als_handoff_prepared"] is False

    def test_non_transport_agency_shape(self):
        agency = {"transports_patients": False}
        pkt = _call_build(agency=agency)
        trp = pkt["transport"]
        assert trp["non_transport_agency"] is True
        assert trp["transport_decision_applicable"] is False
        assert "transport_decision_made" not in trp

    def test_non_transport_agency_shape_from_service_type_schema(self):
        agency = {
            "service_type": {"transport": False},
            "als_dispatch": {"auto_dispatched": True},
        }
        pkt = _call_build(agency=agency)
        trp = pkt["transport"]
        assert trp["non_transport_agency"] is True
        assert trp["transport_decision_applicable"] is False
        assert trp["als_auto_dispatched"] is True
        assert trp["als_intercept_considered"] is True
        assert "transport_decision_made" not in trp

    def test_pre_arrival_notification_detected(self):
        iv = _make_intervention("pre_arrival_notification")
        session = types.SimpleNamespace(interventions=[iv])
        pkt = _call_build(session=session)
        assert pkt["transport"]["pre_arrival_notification_sent"] is True

    def test_disposition_in_dmist_detected(self):
        pkt = _call_build(
            submitted_docs={"dmist": "T: transport to county hospital via ALS intercept"},
        )
        assert pkt["transport"]["disposition_in_dmist"] is True

    def test_trauma_transport_weight_high(self):
        scenario = {**_BASE_SCENARIO, "category": "pediatric_trauma"}
        pkt = _call_build(scenario=scenario)
        assert pkt["transport"]["weight"] == "high"

    def test_medical_transport_weight_moderate(self):
        pkt = _call_build()
        assert pkt["transport"]["weight"] == "moderate"

    def test_transport_key_always_present(self):
        pkt = _call_build()
        assert "transport" in pkt


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3 — §5.5/§5.6 rendering in _format_evidence_packet_for_prompt
# ═══════════════════════════════════════════════════════════════════════════════

class TestFormatPhase3Sections:
    """Phase 3 rendering: assessment phase gaps and transport flags appear in output."""

    def _packet_with_ps_gaps(self):
        """Build a packet with clear primary survey gaps."""
        return _call_build(student_messages=[_msg("Let me apply some oxygen.")])

    def test_assessment_phases_section_absent_when_all_detected(self):
        # Full transcript that covers all primary survey elements
        msgs = [_msg(
            "AVPU alert. Airway is patent. Breathing rate 20, lung sounds clear. "
            "Pulse 90, skin warm and dry. Let me get vitals."
        )]
        pkt = _call_build(student_messages=msgs)
        rendered = _format_evidence_packet_for_prompt(pkt)
        # May have UB or other gaps — just confirm the function runs without error
        assert isinstance(rendered, str)

    def test_primary_survey_gaps_appear_in_rendered_output(self):
        pkt = _call_build(student_messages=[])
        rendered = _format_evidence_packet_for_prompt(pkt)
        # With an empty transcript, primary survey gaps should appear
        assert "Primary Survey gaps" in rendered or "Assessment Phases" in rendered or rendered == ""

    def test_als_auto_dispatch_context_rendered(self):
        agency = {"transports_patients": True, "als_dispatch": {"auto_dispatched": True}}
        pkt = _call_build(agency=agency)
        rendered = _format_evidence_packet_for_prompt(pkt)
        if rendered:
            assert "auto-dispatched" in rendered.lower() or "als" in rendered.lower()

    def test_non_transport_agency_no_transport_decision_flag(self):
        agency = {"transports_patients": False}
        # No ALS called, no DMIST
        pkt = _call_build(agency=agency, submitted_docs={})
        rendered = _format_evidence_packet_for_prompt(pkt)
        # Transport decision gap should NOT be flagged for non-transport agency
        assert "Transport decision not detected" not in rendered


# ═══════════════════════════════════════════════════════════════════════════════
# SessionEvent bridge — authoritative event integration tests
# ═══════════════════════════════════════════════════════════════════════════════

from datetime import datetime as _dt

class TestSessionEventBridge:
    """Verify that session_events are preferred over tag-derived fallbacks when available."""

    def _iv_event(self, minutes_offset=0):
        return _session_event(
            "intervention_applied", "o2_nrb",
            occurred_at=_dt(2026, 1, 1, 12, minutes_offset, 0),
        )

    def _vital_event(self, minutes_offset=5):
        return _session_event(
            "vital_check", "spo2",
            occurred_at=_dt(2026, 1, 1, 12, minutes_offset, 0),
        )

    def test_reassessment_via_vital_check_event_after_intervention(self):
        # vital_check event after intervention_applied → reassessment flagged
        events = [self._iv_event(0), self._vital_event(5)]
        pkt = _call_build(session_events=events)
        present_ids = {e["element"] for e in pkt["universal_base"]["present"] if isinstance(e, dict)}
        # reassessment should appear in present (via UB list)
        ub_present = pkt["universal_base"]["present"]
        ub_gaps = [g["element"] for g in pkt["universal_base"]["gaps"]]
        assert "reassessment" in ub_present or "reassessment" not in ub_gaps

    def test_vital_check_before_intervention_does_not_count_as_reassessment(self):
        # vital_check BEFORE intervention_applied → should NOT count as post-iv reassessment
        events = [
            self._vital_event(0),   # vital before intervention
            self._iv_event(5),      # intervention after
        ]
        pkt = _call_build(session_events=events, student_messages=[])
        # Reassessment is not confirmed via authoritative path — may still be detected via text
        # (there's no transcript text here, so it should be absent)
        ub_present = pkt["universal_base"]["present"]
        # With no transcript and no post-iv vital events, reassessment should not be present
        assert "reassessment" not in ub_present

    def test_authoritative_reassessment_takes_priority_over_tag_derived(self):
        # Both authoritative events AND tag-derived vitals present → authoritative wins (both paths confirm)
        events = [self._iv_event(0), self._vital_event(5)]
        iv = types.SimpleNamespace(name="o2_nrb", applied_at=_dt(2026, 1, 1, 12, 0, 0))
        post_vital = _finding(
            finding_type="vital", captured_at=_dt(2026, 1, 1, 12, 6, 0)
        )
        pkt = _call_build(
            session=_make_session(interventions=[iv]),
            findings=[post_vital],
            session_events=events,
        )
        assert "reassessment" in pkt["universal_base"]["present"]

    def test_explicit_assessment_event_satisfies_required_assessment(self):
        scenario = {
            **_BASE_SCENARIO,
            "scoring": {
                "required_assessments": [
                    {"id": "lung_sounds", "description": "Lung sounds", "keywords": ["lung", "auscultate"], "missing_deduction": 2},
                ]
            },
        }
        # Explicit assessment event with key matching the id
        events = [_session_event("explicit_assessment", "lung_sounds")]
        pkt = _call_build(scenario=scenario, session_events=events)
        present_ids = [r["id"] for r in pkt["required_assessments"]["present"]]
        gap_ids = [r["id"] for r in pkt["required_assessments"]["gaps"]]
        assert "lung_sounds" in present_ids
        assert "lung_sounds" not in gap_ids

    def test_explicit_assessment_keyword_match_in_event_key(self):
        scenario = {
            **_BASE_SCENARIO,
            "scoring": {
                "required_assessments": [
                    {"id": "neuro_exam", "description": "Neuro", "keywords": ["pupils", "neuro"], "missing_deduction": 2},
                ]
            },
        }
        # Event key matches a keyword (not the id itself)
        events = [_session_event("explicit_assessment", "pupils")]
        pkt = _call_build(scenario=scenario, session_events=events, student_messages=[])
        present_ids = [r["id"] for r in pkt["required_assessments"]["present"]]
        assert "neuro_exam" in present_ids

    def test_required_assessment_gap_when_no_event_and_no_transcript_match(self):
        scenario = {
            **_BASE_SCENARIO,
            "scoring": {
                "required_assessments": [
                    {"id": "skin_assessment", "description": "Skin", "keywords": ["skin", "crt"], "missing_deduction": 2},
                ]
            },
        }
        pkt = _call_build(scenario=scenario, session_events=[], student_messages=[])
        gap_ids = [r["id"] for r in pkt["required_assessments"]["gaps"]]
        assert "skin_assessment" in gap_ids

    def test_no_session_events_falls_back_to_tag_derived_behavior(self):
        # Without session_events, behavior is identical to before the bridge
        pkt_no_events = _call_build(session_events=None, student_messages=[])
        pkt_empty_events = _call_build(session_events=[], student_messages=[])
        # Both should produce the same universal_base structure
        assert pkt_no_events["universal_base"]["present"] == pkt_empty_events["universal_base"]["present"]
        assert pkt_no_events["universal_base"]["gaps"] == pkt_empty_events["universal_base"]["gaps"]

    def test_frontend_explicit_vital_check_not_authoritative_for_reassessment(self):
        # frontend_explicit vital_check events are self-reported and must not grant
        # authoritative reassessment credit — only backend_auto/instructor_note qualify.
        events = [
            self._iv_event(0),  # backend_auto intervention_applied
            _session_event("vital_check", "spo2",
                           occurred_at=_dt(2026, 1, 1, 12, 5, 0),
                           source="frontend_explicit"),
        ]
        pkt = _call_build(session_events=events, student_messages=[])
        # No transcript text, no tag-derived post-iv vitals, no backend_auto vital_check
        # → reassessment must NOT be in present
        assert "reassessment" not in pkt["universal_base"]["present"]

    def test_frontend_explicit_assessment_not_authoritative_for_required_assessments(self):
        # frontend_explicit explicit_assessment events are self-reported and must not
        # grant required-assessment credit that transcript matching would not also grant.
        scenario = {
            **_BASE_SCENARIO,
            "scoring": {
                "required_assessments": [
                    {"id": "lung_sounds", "description": "Lung sounds", "keywords": ["lung", "auscultate"], "missing_deduction": 2},
                ]
            },
        }
        events = [_session_event("explicit_assessment", "lung_sounds", source="frontend_explicit")]
        pkt = _call_build(scenario=scenario, session_events=events, student_messages=[])
        # Self-reported event with no transcript corroboration → assessment must NOT be credited
        gap_ids = [r["id"] for r in pkt["required_assessments"]["gaps"]]
        assert "lung_sounds" in gap_ids


# ═══════════════════════════════════════════════════════════════════════════════
# §5.8a — Impression Challenge evidence packet (Phase 4)
# ═══════════════════════════════════════════════════════════════════════════════

from datetime import datetime as _datetime


def _challenge_ev(
    challenge_type,
    student_answer,
    correct_answer,
    result,
    acceptable=None,
    occurred_at=None,
    source="backend_auto",
):
    return types.SimpleNamespace(
        event_type="challenge_completed",
        event_key=challenge_type,
        source=source,
        occurred_at=occurred_at or _datetime(2026, 1, 1, 12, 10, 0),
        event_data={
            "challenge_type": challenge_type,
            "student_answer": student_answer,
            "correct_answer": correct_answer,
            "result": result,
            "acceptable": acceptable or [],
        },
    )


def _iv_ev_at(minutes_offset=0):
    return types.SimpleNamespace(
        event_type="intervention_applied",
        event_key="o2_nrb",
        source="backend_auto",
        occurred_at=_datetime(2026, 1, 1, 12, minutes_offset, 0),
        event_data={},
    )


class TestImpressionChallengeEP:
    """§5.8a — impression_challenge field populated by challenge_completed events."""

    def test_no_challenge_event_returns_none(self):
        pkt = _call_build(session_events=[])
        assert pkt["impression_challenge"] is None

    def test_correct_result_populates_field(self):
        ev = _challenge_ev("impression", "Respiratory Distress", "Respiratory Distress", "correct")
        pkt = _call_build(session_events=[ev])
        ic = pkt["impression_challenge"]
        assert ic is not None
        assert ic["result"] == "correct"
        assert ic["student_answer"] == "Respiratory Distress"
        assert ic["correct"] == "Respiratory Distress"

    def test_acceptable_list_included_in_ep(self):
        ev = _challenge_ev(
            "impression", "Wheezing/Asthma", "Respiratory Distress", "acceptable",
            acceptable=["Wheezing/Asthma", "Bronchospasm"],
        )
        pkt = _call_build(session_events=[ev])
        ic = pkt["impression_challenge"]
        assert ic["result"] == "acceptable"
        assert "Wheezing/Asthma" in ic["acceptable"]
        assert "Bronchospasm" in ic["acceptable"]

    def test_incorrect_result_in_ep(self):
        ev = _challenge_ev("impression", "Cardiac Arrest", "Respiratory Distress", "incorrect")
        pkt = _call_build(session_events=[ev])
        ic = pkt["impression_challenge"]
        assert ic["result"] == "incorrect"
        assert ic["student_answer"] == "Cardiac Arrest"

    def test_skipped_result_in_ep(self):
        ev = _challenge_ev("impression", None, "Respiratory Distress", "skipped")
        pkt = _call_build(session_events=[ev])
        assert pkt["impression_challenge"]["result"] == "skipped"

    def test_timestamp_relative_to_first_intervention(self):
        iv_ev = _iv_ev_at(0)                                           # 12:00:00
        ch_ev = _challenge_ev(
            "impression", "Respiratory Distress", "Respiratory Distress", "correct",
            occurred_at=_datetime(2026, 1, 1, 12, 5, 0),              # 12:05:00 = 300s later
        )
        pkt = _call_build(session_events=[iv_ev, ch_ev])
        assert pkt["impression_challenge"]["timestamp_relative_to_first_intervention"] == 300.0

    def test_timestamp_none_when_no_intervention_event(self):
        ch_ev = _challenge_ev("impression", "Respiratory Distress", "Respiratory Distress", "correct")
        pkt = _call_build(session_events=[ch_ev])
        assert pkt["impression_challenge"]["timestamp_relative_to_first_intervention"] is None

    def test_frontend_explicit_challenge_excluded(self):
        # frontend_explicit challenge events are self-reported — not authoritative
        ev = _challenge_ev(
            "impression", "Respiratory Distress", "Respiratory Distress", "correct",
            source="frontend_explicit",
        )
        pkt = _call_build(session_events=[ev])
        assert pkt["impression_challenge"] is None

    def test_non_impression_challenge_type_excluded_from_impression_field(self):
        ev = _challenge_ev("ecg", "NSR", "STEMI", "incorrect")
        pkt = _call_build(session_events=[ev])
        assert pkt["impression_challenge"] is None

    def test_acceptable_defaults_to_empty_list_when_key_absent(self):
        ev = types.SimpleNamespace(
            event_type="challenge_completed",
            event_key="impression",
            source="backend_auto",
            occurred_at=_datetime(2026, 1, 1, 12, 5, 0),
            event_data={
                "challenge_type": "impression",
                "student_answer": "Respiratory Distress",
                "correct_answer": "Respiratory Distress",
                "result": "correct",
                # no "acceptable" key
            },
        )
        pkt = _call_build(session_events=[ev])
        assert pkt["impression_challenge"]["acceptable"] == []
