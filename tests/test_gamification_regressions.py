import json
import inspect
import sys
import types
from datetime import datetime
from datetime import timedelta

import pytest

# conftest.py stubs app.config and sentry_sdk before this file is collected.
# No local override needed — _PermissiveSettings handles all settings with __getattr__.

from app.main import (  # noqa: E402
    ActiveContext,
    AdjudicationRequest,
    SessionProgressRequest,
    SpendTreatRequest,
    TreatRefundRequest,
    _build_session_timeline,
    _cpr_challenge_summary_from_evidence,
    _cpr_training_debrief_text,
    _cpr_training_timeline,
    _check_and_fire_primary_survey_milestone,
    _effective_score,
    _effective_subscores,
    _LEXI_RECENT_MISSED_KEYS,
    _build_group_public_state,
    _PILOT_PEDIATRIC_CHAMPION_SCENARIOS,
    _overlap_recent_missed_keys,
    _remember_missed_lexi_keys_for_user,
    _session_counts_as_passing_pilot_scenario,
    _validate_adjudication_request,
    post_session_progress,
    refund_treat,
    spend_treat,
)
from app.ai_client import (  # noqa: E402
    _assert_turnover_resolved,
    _build_evidence_packet,
    _compute_scene_entry_scoring,
    _extract_required_debrief_subscores,
    _format_evidence_packet_for_prompt,
    _infer_scene_addressee,
    evaluate_and_generate_debrief,
)
from app.scenario_engine import load_scenario  # noqa: E402
from app.scenarios.vocabulary import validate_scenario  # noqa: E402
from app.vitals_engine import calculate_vitals  # noqa: E402
from app.models import LexiGroupSession, SimSession, User  # noqa: E402


def test_cpr_challenge_summary_exposes_stable_challenge_level_reward_fields():
    evidence_packet = {
        "cpr_challenge": {
            "challenge_id": "adult_cardiac_arrest_01_bls_cpr",
            "challenge_attempt_id": "session-1:adult_cardiac_arrest_01_bls_cpr:abc123",
            "outcome": "criteria_not_met",
            "completed": True,
            "score": 74,
            "timestamp_integrity": "server_anchored",
            "timeline": [
                {"t_ms": 0, "type": "challenge_started"},
                {"t_ms": 128000, "type": "shock_delivered"},
                {"t_ms": 255000, "type": "challenge_ended"},
            ],
            "rosc": {
                "achieved": False,
                "triggered_after_cycle": None,
            },
            "metrics": {
                "ccf": 0.76,
                "ccf_by_cycle": [{"cycle": 1}, {"cycle": 2}],
                "average_pause_sec": 8.5,
                "longest_pause_sec": 12.0,
                "pause_events": [
                    {"pause_sec": 5.0},
                    {"pause_sec": 12.0},
                ],
                "post_decision_resume": {
                    "average_resume_sec": 6.0,
                    "events": [
                        {"resume_sec": 3.0, "weight": 1.0},
                        {"resume_sec": 9.0, "weight": 0.5},
                    ],
                },
                "pulse_checks": {
                    "valid_checks": 2,
                    "too_short": [{"duration_sec": 4.0}],
                    "too_long": [],
                    "rhythm_checks_without_pulse_check": [{"cycle": 3}],
                },
                "ventilation_modes": {
                    "applicable": True,
                    "selected_initial": "30:2",
                    "expected": "30:2",
                    "events": [
                        {"selected": "30:2", "expected": "30:2", "correct": True},
                    ],
                },
                "rhythm_decisions": [
                    {"decision": "shock", "correct": True},
                    {"decision": "no_shock", "correct": False, "severity": "major"},
                ],
                "analytics": {
                    "ccf_trend": {"direction": "declining", "values": [0.82, 0.77, 0.69]},
                    "error_tags": ["ccf_below_target", "delayed_resume"],
                    "remediation_targets": ["high_performance_cpr_ccf", "post_shock_cpr_resume"],
                },
            },
        }
    }

    summary = _cpr_challenge_summary_from_evidence(evidence_packet)

    assert summary == {
        "challenge_type": "cpr",
        "challenge_id": "adult_cardiac_arrest_01_bls_cpr",
        "challenge_attempt_id": "session-1:adult_cardiac_arrest_01_bls_cpr:abc123",
        "outcome": "criteria_not_met",
        "completed": True,
        "score": 74,
        "timestamp_integrity": "server_anchored",
        "rosc_achieved": False,
        "rosc_after_cycle": None,
        "cpr_time_sec": 255.0,
        "rounds_completed": 2,
        "shocks_delivered": 1,
        "ccf": 0.76,
        "ccf_trend": {"direction": "declining", "values": [0.82, 0.77, 0.69]},
        "average_pause_sec": 8.5,
        "longest_pause_sec": 12.0,
        "pauses_over_10_count": 1,
        "pulse_checks": {
            "valid_checks": 2,
            "too_short_count": 1,
            "too_long_count": 0,
            "rhythm_checks_without_pulse_check_count": 1,
        },
        "post_decision_resume": {
            "average_resume_sec": 6.0,
            "events_count": 2,
            "delayed_count": 1,
        },
        "ventilation_ratio": {
            "applicable": True,
            "selected_initial": "30:2",
            "expected": "30:2",
            "events_count": 1,
            "incorrect_count": 0,
        },
        "rhythm_decisions": {
            "decisions_count": 2,
            "incorrect_count": 1,
            "critical_count": 0,
        },
        "error_tags": ["ccf_below_target", "delayed_resume"],
        "remediation_targets": ["high_performance_cpr_ccf", "post_shock_cpr_resume"],
        "aggregation_rule": "latest_completed_attempt",
    }


def test_cpr_challenge_summary_absent_without_cpr_evidence():
    assert _cpr_challenge_summary_from_evidence({}) is None
    assert _cpr_challenge_summary_from_evidence(None) is None


def test_cpr_training_timeline_uses_cpr_evidence_not_generic_scenario_checklist():
    cpr_result = {
        "completed": True,
        "outcome": "rosc",
        "score": 94,
        "rosc": {"achieved": True},
        "score_buckets": {
            "ccf": {"earned": 30, "possible": 30},
            "pause_discipline": {"earned": 18, "possible": 20},
            "rhythm_decisions": {"earned": 20, "possible": 20},
            "cycle_discipline": {"earned": 10, "possible": 10},
            "post_decision_resume": {"earned": 10, "possible": 10},
            "ventilation_ratio": {"earned": 0, "possible": 5},
        },
        "metrics": {
            "ccf": 0.88,
            "average_pause_sec": 6.0,
            "longest_pause_sec": 11.0,
            "pause_events": [{"pause_sec": 11.0}],
            "pulse_checks": {
                "valid_checks": 2,
                "too_short": [],
                "too_long": [],
                "rhythm_checks_without_pulse_check": [],
            },
            "rhythm_decisions": [{"correct": True}],
            "post_decision_resume": {
                "average_resume_sec": 3.0,
                "events": [{"weight": 1.0}],
            },
            "ventilation_modes": [
                {"selected": "15:2", "expected": "30:2", "correct": False},
            ],
            "analytics": {},
        },
        "code_log": [
            {"t_ms": 0, "text": "CPR challenge started"},
            {"t_ms": 124000, "text": "AED: analyzing rhythm"},
        ],
    }

    timeline = _cpr_training_timeline(cpr_result)
    actions = [row["action"] for row in timeline]

    assert timeline[0]["status"] == "applied"
    assert "Cardiac arrest recognized" in actions[0]
    assert "backend-verified CPR evidence" in actions[1]
    assert any("Chest compression fraction 88%" in action for action in actions)
    assert any("longest pause 11.0 sec" in action for action in actions)
    assert any("valid 5-10 sec" in action for action in actions)
    assert any("selected 15:2; expected 30:2" in action for action in actions)
    assert any(row.get("source") == "code_log" and row["action"] == "AED: analyzing rhythm" for row in timeline)
    assert not any("CPR/AED challenge completed with high-performance CPR management" == action for action in actions)

    feedback = _cpr_training_debrief_text({"display_title": "Adult Arrest"}, cpr_result, None)
    assert "HIGH-PERFORMANCE CPR METRICS" in feedback
    assert "normal transcript checklist is not used" in feedback


class _FakeResult:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows

    def scalar_one_or_none(self):
        return self._row

    def all(self):
        return self._rows or []


class _FakeTreatsDB:
    """Fake DB for treat spend/refund tests.

    spend_treat makes two sequential queries: first for SimSession, then for User.
    Subsequent queries (refund_treat) return the User row.
    """
    def __init__(self, user: User, session: SimSession = None):
        self.user = user
        self.session = session
        self._query_count = 0
        self.execute_statements = []
        self.commit_calls = 0

    async def execute(self, statement):
        self.execute_statements.append(statement)
        self._query_count += 1
        # spend_treat: query 1 → session, query 2 → user; refund_treat → user
        if self._query_count == 1 and self.session is not None:
            return _FakeResult(self.session)
        return _FakeResult(self.user)

    async def commit(self):
        self.commit_calls += 1


class _FakeProgressDB:
    def __init__(self, session: SimSession):
        self.session = session
        self.execute_statements = []
        self.commit_calls = 0
        self.get_calls = 0

    async def execute(self, statement):
        self.execute_statements.append(statement)
        return _FakeResult(self.session)

    async def commit(self):
        self.commit_calls += 1

    async def get(self, *_args, **_kwargs):
        self.get_calls += 1
        return None


class _FakeProgressAwardDB:
    def __init__(self, session: SimSession, user: User, prior_rows=None):
        self._rows = [session, user]
        self._prior_rows = prior_rows or []
        self._prior_rows_returned = False
        self.execute_statements = []
        self.commit_calls = 0

    async def execute(self, statement):
        self.execute_statements.append(statement)
        if self._rows:
            row = self._rows.pop(0)
            return _FakeResult(row=row)
        if not self._prior_rows_returned:
            self._prior_rows_returned = True
            return _FakeResult(rows=self._prior_rows)
        return _FakeResult(rows=[])

    async def commit(self):
        self.commit_calls += 1

    async def flush(self):
        return None


def _ctx(user_id: str) -> ActiveContext:
    return ActiveContext(
        user_id=user_id,
        username="tester",
        first_name="Test",
        is_superuser=False,
        agency_id="agency-1",
        agency_name="Agency",
        agency_file="agency_file",
        provider_level="EMT",
        mca="mi_wmrmcc_kent",
        protocol_profile_id=None,
        role="student",
        membership_count=1,
    )


def test_croup_racepinephrine_contract_is_internally_consistent():
    scenario = load_scenario("peds_croup_01")
    racepi = scenario["vitals"]["interventions"]["racepinephrine_svn"]

    # Racepinephrine is not a BLS/EMT treatment in this croup scenario.
    assert racepi["within_bls_scope"] is False
    assert racepi.get("required_expansion") in (None, "")
    assert racepi["unavailable_in_scenario"] is True
    assert "ALS" in racepi["unavailable_reason"]
    assert "EMT scope" in racepi["notes"] or "BLS unit" in racepi["notes"]
    assert "racepinephrine_bls" not in json.dumps(scenario)

    scope_text = scenario["scoring_rubric"]["protocols_treatment"]["full_credit"]
    assert "ALS-only" in scope_text or "ALS" in scope_text
    lexi_guardrails = " ".join(scenario.get("lexi_guardrails") or [])
    assert "Equipment availability alone" in lexi_guardrails
    assert "Kent County" in lexi_guardrails
    assert "SVN/nebulizer kit" in lexi_guardrails
    assert "Paramedic/ALS nebulized agent" in lexi_guardrails
    assert "not a BLS/EMT scope expansion" in lexi_guardrails


def test_debrief_subscores_require_scope_and_narrative_for_full_run():
    debrief = """
Clinical Performance score: 33/40
DMIST score: 10/10
Professionalism score: 8/10
"""
    with pytest.raises(ValueError, match="scope_adherence, narrative|narrative, scope_adherence"):
        _extract_required_debrief_subscores(
            debrief,
            {},
            include_narrative=True,
        )


def test_debrief_subscores_recover_from_markdown_score_lines():
    debrief = """
Clinical Performance score: 33/40
DMIST score: 10/10
Professionalism score: 8/10
Scope score: 17/20
Narrative score: 15/20
"""
    subscores = _extract_required_debrief_subscores(
        debrief,
        {"clinical_performance": 33},
        include_narrative=True,
    )
    assert subscores == {
        "clinical_performance": 33,
        "scope_adherence": 17,
        "dmist": 10,
        "professionalism": 8,
        "narrative": 15,
    }


def test_debrief_subscores_recover_protocols_treatment_lines():
    debrief = """
Clinical Performance score: 31/40
Protocols/Treatment score: 16/20
DMIST score: 9/10
Professionalism score: 8/10
Narrative score: 14/20
"""
    subscores = _extract_required_debrief_subscores(
        debrief,
        {"clinical_performance": 31},
        include_narrative=True,
        required_non_narrative=("clinical_performance", "protocols_treatment", "dmist", "professionalism"),
    )
    assert subscores == {
        "clinical_performance": 31,
        "protocols_treatment": 16,
        "dmist": 9,
        "professionalism": 8,
        "narrative": 14,
    }


def test_scene_addressee_routes_general_openers_to_family_not_partner():
    # peds_croup_01 has family personas (Sarah/mom, Mike/dad) so openers route to "family"
    scenario = load_scenario("peds_croup_01")
    assert _infer_scene_addressee("hi my name is John with the fire department what's going on today", scenario) == "family"
    assert _infer_scene_addressee("how are you today", scenario) == "family"
    assert _infer_scene_addressee("what's going on", scenario) == "family"


def test_scene_addressee_keeps_partner_when_alex_is_named():
    scenario = load_scenario("peds_croup_01")
    assert _infer_scene_addressee("Alex, please report the SpO2", scenario) == "ems_partner"


def test_scene_addressee_routes_conversational_assessment_questions_away_from_partner():
    scenario = load_scenario("peds_croup_01")
    samples = [
        "how can we help?",
        "what's the problem?",
        "why did you call?",
        "are you ok?",
        "where does it hurt?",
        "what's her name?",
        "what do you need?",
        "is that better?",
        "how are you doing?",
        "is it ok if we examine her?",
        "we're here to help.",
        "what can we do for you?",
    ]
    for message in samples:
        assert _infer_scene_addressee(message, scenario) in {"bystander", "patient", "family", "patient_or_family"}


def test_scene_entry_scoring_uses_scenario_defined_ppe_rules():
    scenario = load_scenario("peds_trauma_01_soft_tissue")
    scoring = _compute_scene_entry_scoring(
        scenario,
        {"ppe_donned": ["Gloves"], "scene_approach": "direct_contact", "pat_assessment": "not_sick"},
    )
    assert scoring["prof_ceiling"] == 9
    assert "scenario-defined PPE criteria" in scoring["block"]
    assert "do not verbalize" not in scoring["block"].lower()
    assert "PAT NOTE:" in scoring["block"]
    assert "not verbalizing it in the handoff" in scoring["block"]


def _minimal_ep_session(interventions=None):
    return types.SimpleNamespace(
        interventions=interventions or [],
        start_time=None,
        messages=[],
        scene_entry={},
        findings=[],
    )


def _call_ep(scenario, findings=None, student_text="", submitted_docs=None, session=None):
    """Helper: call _build_evidence_packet with minimal args and return formatted block."""
    _session = session or _minimal_ep_session()
    _msgs = [types.SimpleNamespace(role="user", content=student_text, timestamp=None)] if student_text else []
    packet = _build_evidence_packet(
        adapted_scenario=scenario,
        session=_session,
        submitted_docs=submitted_docs or {"dmist": "", "narrative": ""},
        findings=findings or [],
        elapsed_min=10.0,
        effective_level="EMT",
        agency={},
        student_messages=_msgs,
        critical_actions=scenario["correct_treatment"].get("critical_actions", []),
    )
    return _format_evidence_packet_for_prompt(packet)


def test_protocol_indicated_assessment_block_marks_head_injury_neuro_check_missed_without_evidence():
    scenario = load_scenario("peds_trauma_01_soft_tissue")
    block = _call_ep(scenario, findings=[], student_text="we controlled the bleeding and talked to dad")
    assert "LIKELY MISSED" in block
    assert "neurological assessment" in block.lower()


def test_protocol_indicated_assessment_block_marks_head_injury_neuro_check_done_with_findings():
    scenario = load_scenario("peds_trauma_01_soft_tissue")
    findings = [
        types.SimpleNamespace(finding_type="exam", key="Pupils", value="4 mm, equal and reactive"),
        types.SimpleNamespace(finding_type="vital", key="GCS", value="15"),
    ]
    block = _call_ep(scenario, findings=findings, student_text="")
    # The neuro action (tagged DONE_EVIDENCED) should not have LIKELY MISSED on the preceding line
    lines = block.split("\n")
    for i, line in enumerate(lines):
        if "neurological assessment" in line.lower() and i > 0:
            assert "LIKELY MISSED" not in lines[i - 1], "neuro action should be DONE_EVIDENCED, not LIKELY_MISSED"
            break


def test_critical_actions_block_does_not_allow_dmist_or_narrative_back_credit():
    scenario = load_scenario("peds_croup_01")
    block = _call_ep(scenario, findings=[], student_text="")
    assert "Do NOT use DMIST/narrative to back-credit" in block
    assert "from transcript, DMIST, and narrative" not in block
    assert "unless DMIST/narrative clearly proves completion" not in block


def test_ai_client_scoring_rules_treat_actual_run_as_source_of_truth():
    import pathlib

    text = (pathlib.Path(__file__).parent.parent / "app/ai_client.py").read_text()
    assert "If the submitted DMIST / turnover report conflicts with the actual transcript, findings, interventions, or results, treat that as a factual inaccuracy and deduct from DMIST accordingly." in text
    assert "If the narrative conflicts with the actual transcript, findings, interventions, or results, treat that as a factual inaccuracy and deduct from Narrative accordingly." in text


def test_documentation_conflict_block_flags_wrong_oxygen_method():
    scenario = load_scenario("peds_croup_01")
    session = _minimal_ep_session(interventions=[
        types.SimpleNamespace(name="o2_nrb", applied_at=None),
    ])
    block = _call_ep(
        scenario,
        session=session,
        submitted_docs={
            "dmist": "I: Nasal cannula at 2 LPM with infant in mother's arms.",
            "narrative": "Rx/Treatment: Nasal cannula used and tolerated well.",
        },
    )
    assert "[CONFLICT] DMIST:" in block
    assert "[CONFLICT] Narrative:" in block


def test_documentation_conflict_block_allows_blowby_via_nrb():
    # peds_croup_01 uses NRB-held-near-face blow-by (MI protocol guidance).
    # Documenting NRB blow-by must not trigger a conflict.
    scenario = load_scenario("peds_croup_01")
    session = _minimal_ep_session(interventions=[
        types.SimpleNamespace(name="o2_blowby", applied_at=None),
    ])
    block = _call_ep(
        scenario,
        session=session,
        submitted_docs={
            "dmist": "I: Blow-by O2 at 15 LPM via NRB held near infant's face with parent assistance.",
            "narrative": "Rx/Treatment: Blow-by O2 via NRB mask held near face at 15 LPM was administered and tolerated well.",
        },
    )
    assert "[CONFLICT] DMIST:" not in block
    assert "[CONFLICT] Narrative:" not in block


def test_corroboration_rules_default_deduction_applied_when_no_scenario_rule():
    """Unsupported claims with no scenario corroboration_rules use the 2-pt default."""
    from app.ai_client import _build_evidence_packet, _format_evidence_packet_for_prompt

    scenario = {
        "turnover_target": "als",
        "scoring": {},  # no corroboration_rules
        "correct_treatment": {},
        "interventions": {},
        "dmist_components": {},
    }
    # Inject a fake prepass result with one unsupported DMIST claim
    packet = _build_evidence_packet(
        adapted_scenario=scenario,
        session=_minimal_ep_session(),
        submitted_docs={"dmist": "I: gave epi 0.3mg IM", "narrative": ""},
        findings=[],
        elapsed_min=10.0,
        effective_level="EMT",
        agency={},
        student_messages=[],
        prepass_result={
            "available": True,
            "dmist_unsupported": [{"component": "I", "claim": "epi 0.3mg IM", "reason": "dose not in timeline"}],
            "narrative_unsupported": [],
        },
    )
    claim = packet["corroboration"]["dmist_unsupported_claims"][0]
    assert claim["max_deduction"] == 2
    assert claim["rule_note"] == ""

    block = _format_evidence_packet_for_prompt(packet)
    assert "deduct up to 2 pts from DMIST" in block


def test_corroboration_rules_scenario_deduction_overrides_default():
    """Scenario-defined corroboration_rules annotate the claim with the specified max_deduction."""
    from app.ai_client import _build_evidence_packet, _format_evidence_packet_for_prompt

    scenario = {
        "turnover_target": "als",
        "scoring": {
            "corroboration_rules": {
                "dmist": {
                    "I": {"max_deduction_per_violation": 3, "note": "Epinephrine route is critical"}
                }
            }
        },
        "correct_treatment": {},
        "interventions": {},
        "dmist_components": {},
    }
    packet = _build_evidence_packet(
        adapted_scenario=scenario,
        session=_minimal_ep_session(),
        submitted_docs={"dmist": "I: auto-injector epi 0.15mg", "narrative": ""},
        findings=[],
        elapsed_min=10.0,
        effective_level="EMT",
        agency={},
        student_messages=[],
        prepass_result={
            "available": True,
            "dmist_unsupported": [{"component": "I", "claim": "auto-injector epi 0.15mg", "reason": "timeline shows IM draw-up"}],
            "narrative_unsupported": [],
        },
    )
    claim = packet["corroboration"]["dmist_unsupported_claims"][0]
    assert claim["max_deduction"] == 3
    assert claim["rule_note"] == "Epinephrine route is critical"

    block = _format_evidence_packet_for_prompt(packet)
    assert "deduct up to 3 pts from DMIST" in block


# ── Adjudication helpers ──────────────────────────────────────────────────────

def _fake_adjudication(corrected_score=None, corrected_subscores=None, created_at=None):
    return types.SimpleNamespace(
        id=1,
        reason_type="human_appeal",
        reason_notes="Test",
        adjudicated_by="user1",
        corrected_score=corrected_score,
        corrected_subscores=corrected_subscores,
        override_findings=None,
        created_at=created_at or datetime(2026, 1, 1),
    )


def _fake_session(score=75, narrative_subscores=None, adjudications=None):
    s = types.SimpleNamespace(
        score=score,
        narrative_data={"subscores": narrative_subscores} if narrative_subscores else {},
        adjudications=adjudications or [],
    )
    return s


def test_effective_score_returns_original_when_no_adjudication():
    s = _fake_session(score=72)
    assert _effective_score(s) == 72


def test_effective_score_returns_latest_corrected_score():
    from datetime import datetime
    adj1 = _fake_adjudication(corrected_score=80, created_at=datetime(2026, 1, 1))
    adj2 = _fake_adjudication(corrected_score=85, created_at=datetime(2026, 1, 2))
    s = _fake_session(score=72, adjudications=[adj1, adj2])
    assert _effective_score(s) == 85


def test_effective_score_derives_from_subscores_when_no_direct_score():
    # Subscore-only adjudication: effective total must equal the sum of effective subscores.
    # No original subscores in narrative_data → derived total = sum of correction only.
    adj = _fake_adjudication(corrected_score=None, corrected_subscores={"clinical_performance": 38})
    s = _fake_session(score=72, adjudications=[adj])
    assert _effective_score(s) == 38


def test_effective_score_derives_from_subscores_merged_with_original():
    # Subscore-only adjudication merged with original subscores.
    # Original: clinical_performance=35, narrative=15.
    # Correction: clinical_performance=30.
    # Narrative is bonus-only and must not affect the effective base score.
    adj = _fake_adjudication(corrected_score=None, corrected_subscores={"clinical_performance": 30})
    s = _fake_session(score=50, narrative_subscores={"clinical_performance": 35, "narrative": 15}, adjudications=[adj])
    assert _effective_score(s) == 30


def test_effective_subscores_returns_narrative_data_when_no_adjudication():
    subs = {"clinical_performance": 35, "narrative": 18}
    s = _fake_session(narrative_subscores=subs)
    assert _effective_subscores(s) == subs


def test_effective_subscores_merges_partial_correction_with_original():
    # Partial correction: only clinical_performance changed; narrative must come from original.
    orig = {"clinical_performance": 35, "narrative": 18}
    adj = _fake_adjudication(corrected_subscores={"clinical_performance": 30})
    s = _fake_session(narrative_subscores=orig, adjudications=[adj])
    merged = _effective_subscores(s)
    assert merged["clinical_performance"] == 30
    assert merged["narrative"] == 18


def test_effective_subscores_returns_corrected_subscores_from_latest_adjudication():
    from datetime import datetime
    adj1 = _fake_adjudication(corrected_subscores={"clinical_performance": 38}, created_at=datetime(2026, 1, 1))
    adj2 = _fake_adjudication(corrected_subscores={"clinical_performance": 40}, created_at=datetime(2026, 1, 2))
    s = _fake_session(adjudications=[adj1, adj2])
    assert _effective_subscores(s)["clinical_performance"] == 40


def test_validate_adjudication_request_rejects_unknown_reason_type():
    import pytest
    from fastapi import HTTPException
    req = AdjudicationRequest(reason_type="bad_type", corrected_score=80)
    with pytest.raises(HTTPException) as exc:
        _validate_adjudication_request(req)
    assert exc.value.status_code == 400
    assert "reason_type" in exc.value.detail


def test_validate_adjudication_request_requires_at_least_one_correction():
    import pytest
    from fastapi import HTTPException
    req = AdjudicationRequest(reason_type="human_appeal", reason_notes="Student verbalized correctly")
    with pytest.raises(HTTPException) as exc:
        _validate_adjudication_request(req)
    assert exc.value.status_code == 400
    assert "corrected_score" in exc.value.detail or "corrected_subscores" in exc.value.detail


def test_validate_adjudication_request_rejects_out_of_range_score():
    import pytest
    from fastapi import HTTPException
    req = AdjudicationRequest(reason_type="system_error", corrected_score=105)
    with pytest.raises(HTTPException) as exc:
        _validate_adjudication_request(req)
    assert exc.value.status_code == 400
    assert "0–100" in exc.value.detail


def test_validate_adjudication_request_rejects_bad_subscore_key():
    import pytest
    from fastapi import HTTPException
    req = AdjudicationRequest(reason_type="system_error", corrected_subscores={"bad_key": 10})
    with pytest.raises(HTTPException) as exc:
        _validate_adjudication_request(req)
    assert exc.value.status_code == 400
    assert "bad_key" in exc.value.detail


def test_validate_adjudication_request_requires_notes_for_appeal():
    import pytest
    from fastapi import HTTPException
    req = AdjudicationRequest(reason_type="human_appeal", corrected_score=80, reason_notes="")
    with pytest.raises(HTTPException) as exc:
        _validate_adjudication_request(req)
    assert exc.value.status_code == 400
    assert "reason_notes" in exc.value.detail


def test_validate_adjudication_request_accepts_valid_appeal():
    req = AdjudicationRequest(
        reason_type="human_appeal",
        reason_notes="Student auscultated but did not verbalize in chat",
        corrected_score=88,
    )
    _validate_adjudication_request(req)  # should not raise


def test_validate_adjudication_request_accepts_subscores_only():
    req = AdjudicationRequest(
        reason_type="system_error",
        corrected_subscores={"clinical_performance": 38, "narrative": 18},
    )
    _validate_adjudication_request(req)  # should not raise


def test_reassessment_timeline_requires_real_post_treatment_gap():
    scenario = load_scenario("peds_croup_01")
    t0 = datetime.utcnow()
    session = types.SimpleNamespace(
        start_time=t0,
        provider_level="EMT",
        findings=[
            types.SimpleNamespace(finding_type="vital", key="SpO2", value="93", captured_at=t0 + timedelta(seconds=50)),
            # This lands only 5 seconds after treatment and should NOT count as reassessment.
            types.SimpleNamespace(finding_type="vital", key="SpO2", value="93", captured_at=t0 + timedelta(seconds=65)),
        ],
        messages=[],
        scene_entry={},
        interventions=[
            types.SimpleNamespace(name="o2_nrb", applied_at=t0 + timedelta(seconds=60)),
        ],
    )
    timeline = _build_session_timeline(session, scenario)
    reassess = next(item for item in timeline if "Reassess stridor severity" in item["action"])
    assert reassess["status"] == "missed"


def test_croup_timeline_does_not_count_work_of_breathing_as_lung_sounds():
    scenario = load_scenario("peds_croup_01")
    t0 = datetime.utcnow()
    session = types.SimpleNamespace(
        start_time=t0,
        provider_level="EMT",
        findings=[
            types.SimpleNamespace(
                finding_type="exam",
                key="Work of Breathing",
                value="Moderate retractions with inspiratory stridor audible at rest",
                captured_at=t0 + timedelta(seconds=30),
                source="authored_vitals",
            ),
        ],
        messages=[],
        scene_entry={},
        interventions=[],
        checklist_states={},
    )

    timeline = _build_session_timeline(session, scenario)
    assert not any(item["action"] == "Lung sounds auscultated" for item in timeline)


def test_croup_timeline_counts_challenge_lung_sound_finding():
    scenario = load_scenario("peds_croup_01")
    t0 = datetime.utcnow()
    session = types.SimpleNamespace(
        start_time=t0,
        provider_level="EMT",
        findings=[
            types.SimpleNamespace(
                finding_type="exam",
                key="Lung Sounds @ 00:30",
                value="Inspiratory stridor with clear lower lung fields",
                captured_at=t0 + timedelta(seconds=30),
                source="lung_sound_challenge",
            ),
        ],
        messages=[],
        scene_entry={},
        interventions=[],
        checklist_states={},
    )

    timeline = _build_session_timeline(session, scenario)
    lung_sounds = next(item for item in timeline if item["action"] == "Lung sounds auscultated")
    assert lung_sounds["status"] == "applied"
    assert lung_sounds["elapsed_min"] == 0.5


def test_cpr_code_log_rows_can_be_loaded_from_explicit_session_events():
    scenario = load_scenario("adult_cardiac_arrest_01_bls")
    t0 = datetime.utcnow()
    session = types.SimpleNamespace(
        start_time=t0,
        provider_level="EMT",
        findings=[],
        messages=[],
        scene_entry={},
        interventions=[],
        checklist_states={},
    )
    session_events = [
        types.SimpleNamespace(
            id=10,
            event_type="challenge_started",
            event_key="cpr:adult_cardiac_arrest_01_bls_cpr",
            event_data={},
            occurred_at=t0 + timedelta(seconds=30),
        ),
        types.SimpleNamespace(
            id=11,
            event_type="challenge_completed",
            event_key="cpr:adult_cardiac_arrest_01_bls_cpr",
            event_data={
                "challenge_started_event_id": 10,
                "code_log": [
                    {"t_ms": 0, "text": "CPR challenge ready"},
                    {"t_ms": 124000, "text": "AED: analyzing rhythm"},
                ],
            },
            occurred_at=t0 + timedelta(minutes=5),
        ),
    ]

    timeline = _build_session_timeline(session, scenario, session_events=session_events)
    code_rows = [row for row in timeline if row.get("source") == "code_log"]

    assert [row["action"] for row in code_rows] == ["CPR challenge ready", "AED: analyzing rhythm"]
    assert code_rows[0]["elapsed_min"] == 0.5
    assert code_rows[1]["elapsed_min"] == 2.6


def test_cpr_timeline_events_become_code_log_rows_when_frontend_log_missing():
    scenario = load_scenario("peds_cardiac_arrest_01_bls")
    t0 = datetime.utcnow()
    session = types.SimpleNamespace(
        start_time=t0,
        provider_level="EMT",
        findings=[],
        messages=[],
        scene_entry={},
        interventions=[],
        checklist_states={},
    )
    session_events = [
        types.SimpleNamespace(
            id=20,
            event_type="challenge_started",
            event_key="cpr:peds_cardiac_arrest_01_bls_cpr",
            event_data={},
            occurred_at=t0 + timedelta(seconds=20),
        ),
        types.SimpleNamespace(
            id=21,
            event_type="challenge_completed",
            event_key="cpr:peds_cardiac_arrest_01_bls_cpr",
            event_data={
                "challenge_started_event_id": 20,
                "timeline": [
                    {"t_ms": 0, "type": "challenge_started"},
                    {"t_ms": 4000, "type": "cpr_started", "data": {"mode": "15:2"}},
                    {"t_ms": 124000, "type": "rhythm_check_started"},
                    {"t_ms": 131000, "type": "shock_delivered"},
                    {"t_ms": 385000, "type": "rosc"},
                    {"t_ms": 386000, "type": "challenge_ended", "outcome": "rosc"},
                ],
            },
            occurred_at=t0 + timedelta(minutes=6),
        ),
    ]

    timeline = _build_session_timeline(session, scenario, session_events=session_events)
    code_rows = [row for row in timeline if row.get("source") == "code_log"]

    assert [row["action"] for row in code_rows] == [
        "CPR challenge opened",
        "CPR initiated - 15:2",
        "AED analysis started",
        "Shock delivered",
        "ROSC confirmed",
        "CPR challenge ended - rosc",
    ]


def test_calculate_vitals_reports_spo2_as_whole_number():
    scenario = {
        "vitals": {
            "baseline": {
                "spo2": {"value": 92.2, "numeric": True, "label": "SpO2", "unit": "%"},
                "hr": {"value": 128, "numeric": True, "label": "HR", "unit": " bpm"},
            },
            "deterioration": {"rates": {}, "caps": {}},
            "interventions": {},
        }
    }
    session = {
        "start_time": datetime.utcnow() - timedelta(minutes=1),
        "interventions": [],
    }

    vitals = calculate_vitals(session, scenario)
    assert vitals["spo2"] == 92


@pytest.mark.asyncio
async def test_treat_refund_token_is_single_use_and_row_locked():
    user = User(
        id="user-1",
        username="tester",
        hashed_password="x",
        treats=2,
        treat_tokens=[],
    )
    session = SimSession(
        id="sess-1",
        user_id="user-1",
        scenario_id="scenario-1",
        treats_spent=0,
    )
    db = _FakeTreatsDB(user, session)
    ctx = _ctx(user.id)

    spend = await spend_treat(req=SpendTreatRequest(session_id="sess-1"), ctx=ctx, db=db)
    token = spend["token"]
    assert spend["treats"] == 1
    assert token in (user.treat_tokens or [])

    first_refund = await refund_treat(req=TreatRefundRequest(token=token), ctx=ctx, db=db)
    assert first_refund["treats"] == 2
    assert token not in (user.treat_tokens or [])

    second_refund = await refund_treat(req=TreatRefundRequest(token=token), ctx=ctx, db=db)
    assert second_refund["treats"] == 2  # no-op on reused/invalid token

    # Spend + first refund commit; second refund is a no-op and should not commit.
    assert db.commit_calls == 2

    # spend_treat now makes 2 queries (session lock + user lock); each refund makes 1.
    # Total: 2 (spend) + 1 (first refund) + 1 (second refund no-op) = 4.
    assert len(db.execute_statements) == 4
    assert all(getattr(stmt, "_for_update_arg", None) is not None for stmt in db.execute_statements)


# ── ALS / transport turnover target enforcement ──────────────────────────────

def test_dynamic_turnover_raises_at_debrief_entry():
    """_assert_turnover_resolved must raise for 'dynamic' — debrief must never proceed."""
    with pytest.raises(ValueError, match="'dynamic' was not resolved"):
        _assert_turnover_resolved({"id": "test_scenario", "turnover_target": "dynamic"})


def test_concrete_turnover_targets_do_not_raise():
    for tt in ("als", "hospital", "none"):
        _assert_turnover_resolved({"id": "test_scenario", "turnover_target": tt})
    # Missing field defaults safely — no raise.
    _assert_turnover_resolved({"id": "test_scenario"})


def test_debrief_documentation_extraction_uses_resolved_turnover_target():
    """Regression: debrief submit must not reference an undefined turnover_target local."""
    source = inspect.getsource(evaluate_and_generate_debrief)
    assert "turnover_target=turnover_target or" not in source
    assert "turnover_target=_debrief_turnover_target or" in source


# ── Pilot STEMI scenario structural contract ──────────────────────────────────

def test_stemi_pilot_passes_vocabulary_validation():
    import json, pathlib
    path = pathlib.Path(__file__).parent.parent / "app/scenarios/adult/medical/adult_acs_01_stemi.json"
    scenario = json.loads(path.read_text())
    all_warnings = validate_scenario(scenario)
    # call_type warning is expected — no ACS/STEMI NASEMSO rubric exists yet.
    non_call_type = [w for w in all_warnings if "call_type is not set" not in w]
    assert non_call_type == [], f"Unexpected validation warnings: {non_call_type}"


def test_stemi_pilot_has_required_transport_fields():
    import json, pathlib
    path = pathlib.Path(__file__).parent.parent / "app/scenarios/adult/medical/adult_acs_01_stemi.json"
    s = json.loads(path.read_text())

    assert s.get("turnover_target") == "hospital"

    tp = s.get("transport_phase", {})
    assert tp.get("applicable") is True
    assert tp.get("destination"), "transport_phase.destination must be set"
    assert tp.get("priority") in ("emergent", "non-emergent"), \
        f"transport_phase.priority must be 'emergent' or 'non-emergent', got {tp.get('priority')!r}"
    assert isinstance(tp.get("reassessment_expectations"), list) and tp["reassessment_expectations"], \
        "transport_phase.reassessment_expectations must be a non-empty list"

    pr = s.get("prearrival_report", {})
    assert pr.get("required") is True
    assert isinstance(pr.get("trigger_conditions"), list) and pr["trigger_conditions"], \
        "prearrival_report.trigger_conditions must be a non-empty list"
    assert isinstance(pr.get("required_elements"), list) and pr["required_elements"], \
        "prearrival_report.required_elements must be a non-empty list"

    adv = s.get("advanced_monitoring", {})
    assert adv.get("cardiac_monitor_4lead") is True
    assert adv.get("ecg_12lead") is True


def test_stemi_pilot_string_override_interventions():
    """ekg_monitoring and 12_lead_ecg must carry string_override effects."""
    import json, pathlib
    path = pathlib.Path(__file__).parent.parent / "app/scenarios/adult/medical/adult_acs_01_stemi.json"
    s = json.loads(path.read_text())
    intv = s["vitals"]["interventions"]

    ekg = intv["ekg_monitoring"]["effects"]
    assert "string_override" in ekg
    assert "cardiac_rhythm" in ekg["string_override"]

    lead12 = intv["12_lead_ecg"]["effects"]
    assert "string_override" in lead12
    assert "ecg_findings" in lead12["string_override"]


def test_legacy_scenarios_with_exemplar_dmist_explicitly_target_als_turnover():
    import json, pathlib

    scenario_paths = sorted((pathlib.Path(__file__).parent.parent / "app/scenarios").rglob("*.json"))
    checked = 0
    for path in scenario_paths:
        if path.name == "adult_acs_01_stemi.json":
            continue
        scenario = json.loads(path.read_text())
        if not scenario.get("exemplar_dmist"):
            continue
        checked += 1
        assert scenario.get("turnover_target") == "als", (
            f"{path.name} has exemplar_dmist but no explicit ALS turnover target"
        )
    assert checked > 0


@pytest.mark.asyncio
async def test_progress_idempotent_replay_returns_stored_values_and_uses_row_lock():
    session = SimSession(
        id="sess-1",
        user_id="user-1",
        agency_id="agency-1",
        scenario_id="peds_asthma_01",
        xp_gross=300,
        xp_earned=120,
        treats_earned=1,
        new_badges=["first_alarm"],
    )
    db = _FakeProgressDB(session)
    ctx = _ctx("user-1")
    req = SessionProgressRequest(session_id="sess-1", elapsed_min=7, is_drill=False)

    first = await post_session_progress(req=req, ctx=ctx, db=db)
    second = await post_session_progress(req=req, ctx=ctx, db=db)

    assert first == second
    assert first["xp_gross"] == 300
    assert first["xp_earned"] == 120
    assert first["treats_earned"] == 1
    assert first["new_badges"] == ["first_alarm"]
    assert first["challenge_badges"] == []

    # Idempotent replay path should not write or continue into award computation.
    assert db.commit_calls == 0
    assert db.get_calls == 0

    # First query of each call should lock the session row.
    assert len(db.execute_statements) == 2
    assert all(getattr(stmt, "_for_update_arg", None) is not None for stmt in db.execute_statements)


@pytest.mark.asyncio
async def test_drill_progress_caps_per_run_and_by_remaining_daily_xp():
    session = SimSession(
        id="sess-drill-1",
        user_id="user-1",
        agency_id="agency-1",
        scenario_id="peds_asthma_01",
        score=100,
        narrative_data={"drill": True},
    )
    user = User(
        id="user-1",
        username="tester",
        hashed_password="x",
        xp=1000,
        treats=7,
        drill_xp_day=datetime.utcnow().date(),
        drill_xp_today=120,
        drill_runs_today=2,
        drill_paid_ids=[],
    )
    db = _FakeProgressAwardDB(session, user, prior_rows=[])
    ctx = _ctx("user-1")
    req = SessionProgressRequest(session_id=session.id, elapsed_min=6, is_drill=False)

    out = await post_session_progress(req=req, ctx=ctx, db=db)

    # base drill XP at score 100 is 300, but per-run cap is 75 and remaining daily cap is 30.
    assert out["xp_gross"] == 75
    assert out["xp_earned"] == 30
    assert out["treats_earned"] == 1
    assert out["new_badges"] == []
    assert out["challenge_badges"] == []

    assert user.xp == 1030
    assert user.treats == 8
    assert user.drill_xp_today == 150
    assert user.drill_runs_today == 3
    assert user.drill_paid_ids == []
    assert db.commit_calls == 1


@pytest.mark.asyncio
async def test_drill_progress_uses_best_prior_drill_delta_for_same_scenario():
    session = SimSession(
        id="sess-drill-2",
        user_id="user-1",
        agency_id="agency-1",
        scenario_id="peds_asthma_01",
        score=65,
        narrative_data={"drill": True},
    )
    user = User(
        id="user-1",
        username="tester",
        hashed_password="x",
        xp=500,
        treats=3,
        drill_xp_day=datetime.utcnow().date(),
        drill_xp_today=10,
        drill_runs_today=1,
        drill_paid_ids=[],
    )
    # Prior drill at 60 points gross (score 65 => 120/2), so same-score repeat earns 0 delta.
    prior_rows = [(60, {"drill": True})]
    db = _FakeProgressAwardDB(session, user, prior_rows=prior_rows)
    ctx = _ctx("user-1")
    req = SessionProgressRequest(session_id=session.id, elapsed_min=8, is_drill=False)

    out = await post_session_progress(req=req, ctx=ctx, db=db)

    assert out["xp_gross"] == 60
    assert out["xp_earned"] == 0
    assert out["treats_earned"] == 0
    assert user.xp == 500
    assert user.treats == 3
    assert user.drill_xp_today == 10
    assert user.drill_runs_today == 2  # run is counted for practice volume
    assert user.drill_paid_ids == []
    assert db.commit_calls == 1


def test_scenario_treats_are_limited_to_perfect_scenarios():
    source = inspect.getsource(post_session_progress)

    assert "treats_earned = 1 if (score or 0) >= 100 and xp_earned > 0 else 0" in source
    assert "is_perfect_scenario = not critical_failure and (session.assessment_score or 0) >= _assessment_max" in source
    assert "treats_earned = 1 if is_perfect_scenario else 0" in source
    assert "treats_earned = (xp_gross // 1000) + len(new_badges) + levels_gained" not in source
    assert "award_duplicate_treats = is_perfect_scenario" in source


def test_pediatric_champion_uses_all_pilot_scenarios_not_legacy_counts():
    source = inspect.getsource(post_session_progress)

    assert "await _pilot_pediatric_champion_complete" in source
    assert 'maybe_badge(\n            "peds_champion"' in source
    assert '(user.peds_count or 0) >= 5 and (user.peds_trauma_count or 0) >= 5' not in source
    assert len(_PILOT_PEDIATRIC_CHAMPION_SCENARIOS) == 9
    assert "peds_cardiac_arrest_01_bls" not in _PILOT_PEDIATRIC_CHAMPION_SCENARIOS


def test_pilot_pediatric_champion_session_pass_filter_uses_passed_distinct_pilot_scenarios():
    passing = types.SimpleNamespace(
        scenario_id="peds_asthma_01",
        assessment_score=56,
        score=0,
        narrative_data={},
        score_snapshot={},
    )
    failing = types.SimpleNamespace(
        scenario_id="peds_asthma_01",
        assessment_score=55,
        score=0,
        narrative_data={},
        score_snapshot={},
    )
    critical_failure = types.SimpleNamespace(
        scenario_id="peds_asthma_01",
        assessment_score=80,
        score=100,
        narrative_data={},
        score_snapshot={"critical_failure": {"triggered": True}},
    )
    non_pilot = types.SimpleNamespace(
        scenario_id="peds_cardiac_arrest_01_bls",
        assessment_score=80,
        score=100,
        narrative_data={},
        score_snapshot={},
    )

    assert _session_counts_as_passing_pilot_scenario(passing)
    assert not _session_counts_as_passing_pilot_scenario(failing)
    assert not _session_counts_as_passing_pilot_scenario(critical_failure)
    assert not _session_counts_as_passing_pilot_scenario(non_pilot)


def _group_session(updated_at: datetime) -> LexiGroupSession:
    return LexiGroupSession(
        id="grp-1",
        agency_id="agency-1",
        host_user_id="user-1",
        room_code="ABC123",
        status="active",
        phase="question",
        round_index=1,
        max_rounds=3,
        current_question_index=0,
        participants=[
            {"user_id": "user-1", "display": "User One", "provider_level": "EMT"},
            {"user_id": "user-2", "display": "User Two", "provider_level": "EMT"},
        ],
        rounds=[
            {
                "questions": [
                    {
                        "question": "Test question?",
                        "options": ["A", "B", "C", "D"],
                        "correct": 1,
                        "explanation": "Because test.",
                    }
                ],
                "answers": {},
                "feedback_ready": {},
                "next_round_ready": {},
            }
        ],
        created_at=updated_at,
        updated_at=updated_at,
    )


def test_group_public_state_includes_state_version_ms():
    updated_at = datetime(2026, 4, 10, 12, 0, 0)
    session = _group_session(updated_at)

    state = _build_group_public_state(session, "user-1")

    assert "state_version_ms" in state
    assert isinstance(state["state_version_ms"], int)
    assert state["state_version_ms"] > 0


def test_group_public_state_state_version_ms_monotonic_with_updated_at():
    first = _group_session(datetime(2026, 4, 10, 12, 0, 0))
    second = _group_session(datetime(2026, 4, 10, 12, 0, 5))

    state_a = _build_group_public_state(first, "user-1")
    state_b = _build_group_public_state(second, "user-1")

    assert state_b["state_version_ms"] > state_a["state_version_ms"]


def test_recent_missed_keys_overlap_requires_minimum_participant_count():
    _LEXI_RECENT_MISSED_KEYS.clear()
    _remember_missed_lexi_keys_for_user("u1", ["q_a", "q_shared"])
    _remember_missed_lexi_keys_for_user("u2", ["q_b", "q_shared"])
    _remember_missed_lexi_keys_for_user("u3", ["q_c"])

    overlap2 = _overlap_recent_missed_keys(["u1", "u2", "u3"], min_count=2)
    overlap3 = _overlap_recent_missed_keys(["u1", "u2", "u3"], min_count=3)

    assert "q_shared" in overlap2
    assert "q_a" not in overlap2
    assert "q_b" not in overlap2
    assert overlap3 == set()


def test_missed_key_recording_can_be_filtered_to_reported_round_keys():
    _LEXI_RECENT_MISSED_KEYS.clear()
    user_id = "user-lexi-1"
    round_keys = ["q1", "q2", "q3", "q4", "q5"]
    reported_missed = ["q2", "q4", "q_not_in_round"]

    filtered = [k for k in reported_missed if k in set(round_keys)]
    _remember_missed_lexi_keys_for_user(user_id, filtered)

    missed = list(_LEXI_RECENT_MISSED_KEYS.get(user_id, []))
    assert "q2" in missed
    assert "q4" in missed
    assert "q_not_in_round" not in missed


# ── Primary survey milestone — Phase 4 ───────────────────────────────────────

class _FakeMilestoneDB:
    """Minimal fake async DB for milestone tests — only needs add() and commit()."""
    def __init__(self):
        self.added = []
        self.commit_calls = 0

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commit_calls += 1


def _ms_event(event_type, event_key="", source="backend_auto"):
    return types.SimpleNamespace(event_type=event_type, event_key=event_key, source=source)


def _ms_msg(role="user"):
    return types.SimpleNamespace(role=role, content="test message")


def _ms_session(events=None, messages=None):
    return types.SimpleNamespace(
        id="sess-milestone-1",
        events=events or [],
        messages=messages or [],
    )


_IC_SCENARIO = {
    "vitals": {
        "interventions": {
            "o2_nrb": {"popup_type": "oxygen"},
            "albuterol_svn": {"popup_type": "medication"},
        }
    },
    "impression_challenge": {
        "enabled": True,
        "prompt": "What is your primary clinical impression?",
        "options": [
            {"id": "a", "label": "Respiratory Distress"},
            {"id": "b", "label": "Cardiac Arrest"},
        ],
    }
}

_NO_IC_SCENARIO = {
    "vitals": {
        "interventions": {
            "albuterol_svn": {"popup_type": "medication"},
        }
    }
}


@pytest.mark.asyncio
async def test_milestone_fires_with_medication_and_three_messages():
    session = _ms_session(
        events=[_ms_event("intervention_applied", "albuterol_svn", source="backend_auto")],
        messages=[_ms_msg(), _ms_msg(), _ms_msg()],
    )
    db = _FakeMilestoneDB()
    result = await _check_and_fire_primary_survey_milestone(session, _IC_SCENARIO, db)

    assert result is not None
    assert result["type"] == "impression"
    assert len(db.added) == 1
    assert db.commit_calls == 1
    fired_ev = db.added[0]
    assert fired_ev.event_type == "milestone_fired"
    assert fired_ev.event_key == "primary_survey_complete"


@pytest.mark.asyncio
async def test_milestone_does_not_fire_with_oxygen_only():
    session = _ms_session(
        events=[_ms_event("intervention_applied", "o2_nrb", source="backend_auto")],
        messages=[_ms_msg(), _ms_msg(), _ms_msg()],
    )
    db = _FakeMilestoneDB()
    result = await _check_and_fire_primary_survey_milestone(session, _IC_SCENARIO, db)

    assert result is None
    assert db.commit_calls == 0


@pytest.mark.asyncio
async def test_milestone_idempotent_already_fired():
    # If milestone_fired event already exists, function returns None immediately.
    session = _ms_session(
        events=[
            _ms_event("intervention_applied", "o2_nrb", source="backend_auto"),
            _ms_event("milestone_fired", "primary_survey_complete", source="backend_auto"),
        ],
        messages=[_ms_msg(), _ms_msg(), _ms_msg()],
    )
    db = _FakeMilestoneDB()
    result = await _check_and_fire_primary_survey_milestone(session, _IC_SCENARIO, db)

    assert result is None
    assert len(db.added) == 0
    assert db.commit_calls == 0


@pytest.mark.asyncio
async def test_milestone_does_not_fire_without_backend_auto_intervention():
    # frontend_explicit intervention events are not authoritative — milestone must not fire.
    session = _ms_session(
        events=[_ms_event("intervention_applied", "albuterol_svn", source="frontend_explicit")],
        messages=[_ms_msg(), _ms_msg(), _ms_msg()],
    )
    db = _FakeMilestoneDB()
    result = await _check_and_fire_primary_survey_milestone(session, _IC_SCENARIO, db)

    assert result is None
    assert db.commit_calls == 0


@pytest.mark.asyncio
async def test_milestone_does_not_fire_with_fewer_than_three_messages():
    session = _ms_session(
        events=[_ms_event("intervention_applied", "albuterol_svn", source="backend_auto")],
        messages=[_ms_msg(), _ms_msg()],  # only 2
    )
    db = _FakeMilestoneDB()
    result = await _check_and_fire_primary_survey_milestone(session, _IC_SCENARIO, db)

    assert result is None
    assert db.commit_calls == 0


@pytest.mark.asyncio
async def test_milestone_fires_exactly_at_three_messages():
    session = _ms_session(
        events=[_ms_event("intervention_applied", "albuterol_svn", source="backend_auto")],
        messages=[_ms_msg(), _ms_msg(), _ms_msg()],  # exactly 3
    )
    db = _FakeMilestoneDB()
    result = await _check_and_fire_primary_survey_milestone(session, _IC_SCENARIO, db)

    assert result is not None
    assert db.commit_calls == 1


@pytest.mark.asyncio
async def test_milestone_returns_none_when_impression_challenge_disabled():
    scenario_disabled = {
        "vitals": {"interventions": {"albuterol_svn": {"popup_type": "medication"}}},
        "impression_challenge": {"enabled": False},
    }
    session = _ms_session(
        events=[_ms_event("intervention_applied", "albuterol_svn", source="backend_auto")],
        messages=[_ms_msg(), _ms_msg(), _ms_msg()],
    )
    db = _FakeMilestoneDB()
    result = await _check_and_fire_primary_survey_milestone(session, scenario_disabled, db)

    # Milestone still fires (event written), but no challenge returned
    assert result is None
    assert db.commit_calls == 1  # milestone event committed


@pytest.mark.asyncio
async def test_milestone_returns_none_when_no_impression_challenge_key():
    session = _ms_session(
        events=[_ms_event("intervention_applied", "albuterol_svn", source="backend_auto")],
        messages=[_ms_msg(), _ms_msg(), _ms_msg()],
    )
    db = _FakeMilestoneDB()
    result = await _check_and_fire_primary_survey_milestone(session, _NO_IC_SCENARIO, db)

    assert result is None
    assert db.commit_calls == 1  # milestone event still committed


@pytest.mark.asyncio
async def test_milestone_model_messages_filtered_to_user_role():
    # AI/model messages must not count toward the 3-message threshold.
    session = _ms_session(
        events=[_ms_event("intervention_applied", "albuterol_svn", source="backend_auto")],
        messages=[
            _ms_msg(role="model"),
            _ms_msg(role="model"),
            _ms_msg(role="user"),   # only 1 user message
            _ms_msg(role="model"),
        ],
    )
    db = _FakeMilestoneDB()
    result = await _check_and_fire_primary_survey_milestone(session, _IC_SCENARIO, db)

    assert result is None
    assert db.commit_calls == 0
