"""
Unit tests for scoring_service — Phase 5 Tier 2 expansion and scene_entry generalization.

Tests _try_tier2 and _try_tier1 helper functions directly.
No database or app.config dependencies required.
"""

from __future__ import annotations

import json
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.checklist import ChecklistItem, TierOneMatchSpec, TimingConstraint, load_checklist
from app.scoring_service import adjudicate, compute_scores, _compute_critical_failure_status, _try_tier2, _try_tier1, _shadow_compose_call_type_rubric, _synthetic_inappropriate_attempt_penalties


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _item(
    item_id: str = "test_item",
    subtype: str = "assessment",
    patterns: list[str] | None = None,
    tier1_match: TierOneMatchSpec | None = None,
    point_value: int = 2,
) -> ChecklistItem:
    return ChecklistItem(
        id=item_id,
        description="Did the observable thing",
        subtype=subtype,
        category="clinical_performance",
        point_value=point_value,
        allowed_tiers=[1, 2] if tier1_match else [1, 2],
        preferred_tier=2 if not tier1_match else 1,
        tier2_patterns=patterns or [],
        tier1_match=tier1_match,
    )


def _finding(key: str, value: str, finding_type: str = "vital", fid: int = 1, source: str | None = None):
    return types.SimpleNamespace(
        id=fid,
        key=key,
        value=value,
        finding_type=finding_type,
        captured_at=None,
        source=source,
    )


def _finding_ts(key: str, value: str, fid: int = 1, minute: int = 0):
    ts = datetime(2025, 1, 1, 12, minute, 0, tzinfo=timezone.utc)
    return types.SimpleNamespace(
        id=fid,
        key=key,
        value=value,
        finding_type="vital",
        captured_at=ts,
    )


def _finding_ts_typed(key: str, value: str, finding_type: str, fid: int = 1, minute: int = 0, source: str | None = None):
    ts = datetime(2025, 1, 1, 12, minute, 0, tzinfo=timezone.utc)
    return types.SimpleNamespace(
        id=fid,
        key=key,
        value=value,
        finding_type=finding_type,
        captured_at=ts,
        source=source,
    )


def _event(event_type: str, event_key: str, eid: int = 1):
    ts = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    return types.SimpleNamespace(
        id=eid,
        event_type=event_type,
        event_key=event_key,
        event_data={},
        occurred_at=ts,
    )


def _event_with_data(event_type: str, event_key: str, event_data: dict, eid: int = 1):
    event = _event(event_type, event_key, eid=eid)
    event.event_data = event_data
    return event


def _intervention(name: str, iid: int = 1, minute: int = 5):
    return types.SimpleNamespace(
        id=iid,
        name=name,
        applied_at=datetime(2025, 1, 1, 12, minute, 0, tzinfo=timezone.utc),
    )


def _message(content: str, role: str = "user"):
    return types.SimpleNamespace(role=role, content=content)


def _try_adjudicate_for_tests(
    items: list[ChecklistItem],
    *,
    interventions: list | None = None,
    findings: list | None = None,
    events: list | None = None,
):
    return adjudicate(
        items,
        interventions=interventions or [],
        session_findings=findings or [],
        session_events=events or [],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario={"legacy_ai_categories": []},
        legacy_ai_categories=frozenset(),
    )


# ── _try_tier2: baseline (transcript) ─────────────────────────────────────────


def test_tier2_transcript_match():
    item = _item(patterns=[r"(?i)blood glucose"])
    result = _try_tier2(item, transcript="I checked blood glucose level")
    assert result is not None
    assert result.source_type == "transcript_match"
    assert result.tier == 2
    assert "blood glucose" in result.matched_text.lower()


def test_tier2_medical_severity_matches_natural_how_severe_phrase():
    item = _item(
        item_id="ems.medical.opqrst_severity",
        subtype="assessment",
        patterns=[r"(?i)(severity|how severe|scale|0.?10|one to ten|how bad|pain score)"],
    )
    result = _try_tier2(item, transcript="how severe is it and has it been constant?")
    assert result is not None
    assert result.source_type == "transcript_match"


def test_tier2_medical_events_matches_what_patient_was_doing_phrase():
    item = _item(
        item_id="ems.medical.sample_events",
        subtype="assessment",
        patterns=[r"(?i)(events|leading up|before this|what happened|what.*(?:doing|happening).*when|when.*what.*(?:doing|happening)|walk me through|timeline)"],
    )
    result = _try_tier2(item, transcript="when did it start and what was he doing")
    assert result is not None
    assert result.source_type == "transcript_match"


def test_tier2_medical_events_does_not_match_unrelated_vital_request():
    item = _item(
        item_id="ems.medical.sample_events",
        subtype="assessment",
        patterns=[r"(?i)(events|leading up|before this|what happened|what.*(?:doing|happening).*when|when.*what.*(?:doing|happening)|walk me through|timeline)"],
    )
    result = _try_tier2(item, transcript="what is her spo2 right now")
    assert result is None


def test_tier2_no_patterns_returns_none():
    item = _item(patterns=[])
    result = _try_tier2(item, transcript="anything here")
    assert result is None


def test_treatment_response_credits_post_intervention_respiratory_reassessment():
    item = _item(
        item_id="ems.medical.treatment_response",
        subtype="reassessment",
        tier1_match=TierOneMatchSpec(
            source="post_intervention_finding",
            finding_key_pattern=r"(?i)(spo2|sp\s*o2|oxygen.saturation|respiratory.rate|\brr\b|work.of.breathing|wob|lung.sounds?|breath.sounds?|wheez|gcs|avpu|loc|mental|blood.glucose|bgl|glucose)",
        ),
    )
    states = _try_adjudicate_for_tests(
        [item],
        interventions=[_intervention("albuterol_svn", minute=5)],
        findings=[
            _finding_ts_typed("SpO2", "94 %", "vital", fid=1, minute=3),
            _finding_ts_typed("SpO2", "98 %", "vital", fid=2, minute=7),
            _finding_ts_typed("Lung Sounds", "Clear bilaterally", "exam", fid=3, minute=8),
        ],
    )
    assert states[0].state == "satisfied"
    assert states[0].evidence_references[0].source_type == "post_intervention_finding"


def test_trauma_reassessment_credits_post_intervention_neuro_reassessment():
    item = _item(
        item_id="ems.trauma.reassessment",
        subtype="reassessment",
        tier1_match=TierOneMatchSpec(
            source="post_intervention_finding",
            finding_key_pattern=r"(?i)(spo2|sp\s*o2|oxygen.saturation|respiratory.rate|\brr\b|pulse|hr|heart|bp|blood.pressure|work.of.breathing|wob|gcs|avpu|loc|mental|pupils?|skin|cap|pain|bleeding|wound)",
        ),
    )
    states = _try_adjudicate_for_tests(
        [item],
        interventions=[_intervention("direct_pressure", minute=5)],
        findings=[
            _finding_ts_typed("Pupils", "PERRL", "exam", fid=1, minute=3),
            _finding_ts_typed("GCS", "15/15", "vital", fid=2, minute=7),
        ],
    )

    assert states[0].state == "satisfied"
    assert states[0].evidence_references[0].source_type == "post_intervention_finding"


def test_trauma_secondary_assessment_quick_action_satisfies_atomic_nremt_body_survey_items():
    scenario = {
        "id": "unit_test_trauma_secondary_quick_action",
        "category": "pediatric_trauma",
        "turnover_target": "als",
        "base_patient_care_rubric": "nremt_trauma_v1",
        "checklist": [],
    }
    items = load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
    secondary_ids = {
        "ems.trauma.head_scalp_ears",
        "ems.trauma.head_eyes",
        "ems.trauma.head_mouth_nose_face",
        "ems.trauma.neck_trachea",
        "ems.trauma.neck_jugular_veins",
        "ems.trauma.neck_c_spine",
        "ems.trauma.chest_inspect",
        "ems.trauma.chest_palpate",
        "ems.trauma.chest_auscultate",
        "ems.trauma.abdomen_inspect_palpate",
        "ems.trauma.pelvis_assess",
        "ems.trauma.genitalia_perineum_as_needed",
        "ems.trauma.lower_left_pmsc",
        "ems.trauma.lower_right_pmsc",
        "ems.trauma.upper_left_pmsc",
        "ems.trauma.upper_right_pmsc",
        "ems.trauma.posterior_thorax",
        "ems.trauma.lumbar_buttocks",
    }
    secondary_items = [item for item in items if item.id in secondary_ids]
    secondary_text = (
        "Inspects and palpates scalp and ears. "
        "Assesses eyes and pupils. "
        "Inspects mouth, nose, and facial area. "
        "Checks trachea position, jugular veins/JVD, and palpates cervical spine. "
        "Inspects chest, palpates chest, and auscultates chest/lung sounds. "
        "Inspects and palpates abdomen. "
        "Assesses pelvis. "
        "Verbalizes genitalia/perineum assessment as needed. "
        "Inspects and palpates both legs with PMS/CMS, motor, sensory, and distal circulation. "
        "Inspects and palpates both arms with PMS/CMS, motor, sensory, and distal circulation. "
        "Log roll to inspect and palpate posterior thorax. "
        "Inspects and palpates lumbar and buttocks areas. "
        "Identifies secondary injuries and wounds for appropriate management."
    )

    states = _try_adjudicate_for_tests(
        secondary_items,
        findings=[_finding("Secondary Assessment", secondary_text, finding_type="exam")],
    )

    assert {state.item_id for state in states if state.state == "satisfied"} == secondary_ids


def test_hypoglycemia_reassessment_credits_post_glucose_and_treatment_response():
    from app.rubric_loader import compose_active_checklist, load_call_type_rubric

    rubric = load_call_type_rubric("hypoglycemia", "training")
    composed = compose_active_checklist(base_items=[], rubric=rubric, provider_level="EMT")
    item = next(i for i in composed.items if i.id == "hypoglycemia.reassess_bgl_loc")

    states = _try_adjudicate_for_tests(
        [item],
        interventions=[_intervention("oral_glucose", minute=5)],
        findings=[
            _finding_ts_typed("Blood Glucose", "34 mg/dL", "vital", fid=1, minute=3),
            _finding_ts_typed("Blood Glucose", "67 mg/dL", "vital", fid=2, minute=7),
            _finding_ts_typed(
                "Treatment Response",
                "Patient feels better, is hungry, and answers appropriately",
                "exam",
                fid=3,
                minute=8,
            ),
        ],
    )

    assert states[0].state == "satisfied"
    assert [ref.source_type for ref in states[0].evidence_references] == [
        "post_intervention_finding",
        "post_intervention_finding",
    ]


@pytest.mark.parametrize(
    ("call_type", "item_id", "intervention_name", "response_value"),
    [
        (
            "pediatric_croup",
            "croup.reassess_post_treatment",
            "o2_blowby",
            "Child is calmer with less visible distress after positioning and oxygen",
        ),
        (
            "respiratory_distress",
            "resp_distress.reassess_post_treatment",
            "albuterol_svn",
            "Patient reports breathing is easier after treatment",
        ),
    ],
)
def test_post_intervention_status_response_satisfies_reassessment_exam_half(
    call_type,
    item_id,
    intervention_name,
    response_value,
):
    from app.rubric_loader import compose_active_checklist, load_call_type_rubric

    rubric = load_call_type_rubric(call_type, "training")
    composed = compose_active_checklist(base_items=[], rubric=rubric, provider_level="EMT")
    item = next(i for i in composed.items if i.id == item_id)

    states = _try_adjudicate_for_tests(
        [item],
        interventions=[_intervention(intervention_name, minute=5)],
        findings=[
            _finding_ts_typed(
                "Treatment Response",
                response_value,
                "exam",
                fid=2,
                minute=8,
                source="ai_roleplay_tag",
            ),
        ],
    )

    assert states[0].state == "satisfied"
    assert states[0].evidence_references[0].source_id == 2


def test_tier2_empty_transcript_no_fallback_for_intervention():
    """intervention subtype: no transcript match → None even if DMIST has the word."""
    item = _item(subtype="intervention", patterns=[r"(?i)epiglottitis"])
    result = _try_tier2(
        item,
        transcript="",
        submitted_dmist="Patient screened for epiglottitis",
    )
    assert result is None


def test_tier2_no_match_returns_none():
    item = _item(patterns=[r"(?i)oxygen"])
    result = _try_tier2(item, transcript="I checked blood pressure")
    assert result is None


# ── _try_tier2: session_finding_text ─────────────────────────────────────────


def test_tier2_assessment_satisfied_from_finding_text():
    """assessment subtype uses finding text when transcript has no match."""
    item = _item(subtype="assessment", patterns=[r"(?i)blood.glucose|cgm"])
    findings = [_finding("blood_glucose", "42 mg/dL")]
    result = _try_tier2(item, transcript="", session_findings=findings)
    assert result is not None
    assert result.source_type == "session_finding_text"
    assert result.source_id == 1
    assert result.tier == 2


def test_tier2_screen_uses_finding_text():
    """screen subtype uses session_finding_text — same as assessment.

    screen items (e.g., croup.hpi_fever) must credit structured vital findings
    (e.g., Temperature vital logged via action modal) even when the student's
    typed message is not in the backend transcript.
    """
    item = _item(subtype="screen", patterns=[r"(?i)temperature|epiglottitis"])
    findings = [_finding("Temperature", "100.4°F — low-grade fever")]
    result = _try_tier2(item, transcript="", session_findings=findings)
    assert result is not None
    assert result.source_type == "session_finding_text"


def test_tier2_finding_timestamp_preserved():
    item = _item(subtype="assessment", patterns=[r"(?i)blood.glucose"])
    findings = [_finding_ts("blood_glucose", "55 mg/dL")]
    result = _try_tier2(item, transcript="", session_findings=findings)
    assert result is not None
    assert result.timestamp == "2025-01-01T12:00:00+00:00"


def test_tier2_history_item_ignores_exam_finding_text():
    item = _item(
        item_id="ems.medical.associated_symptoms",
        subtype="assessment",
        patterns=[r"(?i)cough"],
    )
    result = _try_tier2(
        item,
        transcript="",
        session_findings=[_finding("WOB", "forceful coughing", finding_type="exam")],
    )
    assert result is None


def test_tier2_history_item_can_use_history_finding_text():
    item = _item(
        item_id="ems.medical.associated_symptoms",
        subtype="assessment",
        patterns=[r"(?i)cough"],
    )
    result = _try_tier2(
        item,
        transcript="",
        session_findings=[_finding("Associated Symptoms", "barking cough", finding_type="history")],
    )
    assert result is not None
    assert result.source_type == "session_finding_text"


def test_tier1_finding_value_pattern_matches_only_safe_loc_values():
    item = _item(
        item_id="hypoglycemia.swallow_assessment",
        subtype="screen",
        tier1_match=TierOneMatchSpec(
            source="finding",
            finding_type="vital",
            finding_key_pattern=r"(?i)(gcs|avpu|loc|mental)",
            finding_value_pattern=r"(?i)(alert|verbal|oriented|confused|slurred|responds?\s+to\s+voice)",
        ),
    )

    safe = _try_tier1(
        item,
        scenario={},
        scene_entry=None,
        findings=[_finding("LOC", "verbal, confused and slurred")],
        interventions=[],
        events=[],
    )
    unsafe = _try_tier1(
        item,
        scenario={},
        scene_entry=None,
        findings=[_finding("LOC", "unresponsive")],
        interventions=[],
        events=[],
    )

    assert safe is not None
    assert unsafe is None


def test_tier1_source_required_blocks_authored_vitals_avpu():
    item = _item(
        item_id="ems.medical.loc",
        tier1_match=TierOneMatchSpec(
            source="finding",
            finding_type="vital",
            finding_key_pattern=r"(?i)(gcs|avpu|loc|mental)",
            eligible_sources=["avpu_quick_action"],
            require_source=True,
        ),
    )

    authored_vitals = _try_tier1(
        item,
        scenario={},
        scene_entry=None,
        findings=[_finding("AVPU", "alert", source="authored_vitals")],
        interventions=[],
        events=[],
    )
    quick_action = _try_tier1(
        item,
        scenario={},
        scene_entry=None,
        findings=[_finding("AVPU", "alert", source="avpu_quick_action")],
        interventions=[],
        events=[],
    )

    assert authored_vitals is None
    assert quick_action is not None


def test_trauma_baseline_vitals_requires_bp_pulse_and_respirations_not_avpu_only():
    scenario = {
        "category": "pediatric_trauma",
        "base_patient_care_rubric": "nremt_trauma_v1",
    }
    item = next(
        item for item in load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
        if item.id == "ems.trauma.baseline_vitals"
    )

    avpu_only = adjudicate(
        [item],
        interventions=[],
        session_findings=[_finding("AVPU", "alert", source="avpu_quick_action")],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=scenario,
        legacy_ai_categories=frozenset(),
    )[0]
    complete_vitals = adjudicate(
        [item],
        interventions=[],
        session_findings=[
            _finding("Blood Pressure", "106/70", fid=1, source="authored_vitals"),
            _finding("Heart Rate", "108", fid=2, source="authored_vitals"),
            _finding("Respirations", "16", fid=3, source="authored_vitals"),
        ],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=scenario,
        legacy_ai_categories=frozenset(),
    )[0]

    assert avpu_only.state == "not_satisfied"
    assert complete_vitals.state == "satisfied"


def test_head_injury_neuro_package_requires_formal_gcs_and_loc_vomiting_history():
    from app.rubric_loader import compose_active_checklist, load_call_type_rubric

    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json"
    scenario = json.loads(scenario_path.read_text())
    rubric = load_call_type_rubric("head_injury", "training")
    composed = compose_active_checklist(
        base_items=load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None),
        rubric=rubric,
        provider_level="EMT",
        scenario=scenario,
    )
    item = next(
        item for item in composed.items
        if item.id == "head_injury.neuro_assessment"
    )

    loc_only = adjudicate(
        [item],
        interventions=[],
        session_findings=[
            _finding("AVPU", "alert", source="avpu_quick_action"),
            _finding("Events", "No loss of consciousness", finding_type="history", fid=2),
        ],
        session_events=[],
        chat_messages=[types.SimpleNamespace(role="user", content="did he lose consciousness? he seems confused")],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=scenario,
        legacy_ai_categories=frozenset(),
    )[0]
    complete = adjudicate(
        [item],
        interventions=[],
        session_findings=[
            _finding("GCS", "14/15", fid=1, source="gcs_modal"),
            _finding("Events", "No loss of consciousness; vomited once", finding_type="history", fid=2),
        ],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=scenario,
        legacy_ai_categories=frozenset(),
    )[0]
    complete_split_history = adjudicate(
        [item],
        interventions=[],
        session_findings=[
            _finding("GCS", "14/15", fid=1, source="gcs_modal"),
            _finding("LOC", "No loss of consciousness; cried immediately", finding_type="history", fid=2),
            _finding("Events", "Vomited once about 2 minutes after fall", finding_type="history", fid=3),
        ],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=scenario,
        legacy_ai_categories=frozenset(),
    )[0]
    complete_stable_history_keys = adjudicate(
        [item],
        interventions=[],
        session_findings=[
            _finding("GCS", "14/15", fid=1, source="gcs_modal"),
            _finding("LOC", "No loss of consciousness; cried immediately", finding_type="history", fid=2, source="ai_roleplay_tag"),
            _finding("Vomiting", "Vomited once about 2 minutes after fall", finding_type="history", fid=3, source="ai_roleplay_tag"),
        ],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=scenario,
        legacy_ai_categories=frozenset(),
    )[0]

    assert item.allowed_tiers == [1]
    assert item.requirement_logic == "all"
    assert loc_only.state == "not_satisfied"
    assert complete.state == "satisfied"
    assert complete_split_history.state == "satisfied"
    assert complete_stable_history_keys.state == "satisfied"


def test_head_injury_dcap_btls_head_accepts_structured_exam_finding():
    from app.rubric_loader import compose_active_checklist, load_call_type_rubric

    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json"
    scenario = json.loads(scenario_path.read_text())
    rubric = load_call_type_rubric("head_injury", "training")
    composed = compose_active_checklist(
        base_items=load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None),
        rubric=rubric,
        provider_level="EMT",
        scenario=scenario,
    )
    item = next(
        item for item in composed.items
        if item.id == "head_injury.dcap_btls_head"
    )

    structured_exam = adjudicate(
        [item],
        interventions=[],
        session_findings=[
            _finding("DCAP-BTLS Head", "No deformity or step-off noted", finding_type="exam", source="ems_performed_exam"),
        ],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=scenario,
        legacy_ai_categories=frozenset(),
    )[0]
    vague_head_pain = adjudicate(
        [item],
        interventions=[],
        session_findings=[
            _finding("Headache", "Reports head pain", finding_type="exam", source="ems_performed_exam"),
        ],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=scenario,
        legacy_ai_categories=frozenset(),
    )[0]

    assert structured_exam.state == "satisfied"
    assert vague_head_pain.state == "not_satisfied"


def test_head_injury_pupil_assessment_accepts_neuro_assessment_procedure():
    from app.rubric_loader import compose_active_checklist, load_call_type_rubric

    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json"
    scenario = json.loads(scenario_path.read_text())
    rubric = load_call_type_rubric("head_injury", "training")
    composed = compose_active_checklist(
        base_items=load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None),
        rubric=rubric,
        provider_level="EMT",
        scenario=scenario,
    )
    item = next(
        item for item in composed.items
        if item.id == "head_injury.pupil_assessment"
    )

    neuro_procedure = adjudicate(
        [item],
        interventions=[
            _intervention("neuro_assessment"),
        ],
        session_findings=[],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=scenario,
        legacy_ai_categories=frozenset(),
    )[0]
    pupil_exam = adjudicate(
        [item],
        interventions=[],
        session_findings=[
            _finding("Pupils", "R 4 mm sluggish; L 3 mm brisk", finding_type="exam", source="student_stated_exam"),
        ],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=scenario,
        legacy_ai_categories=frozenset(),
    )[0]
    partner_pupil_exam = adjudicate(
        [item],
        interventions=[],
        session_findings=[
            _finding("Pupils", "R 4 mm sluggish; L 3 mm brisk", finding_type="exam", source="partner_reported_exam"),
        ],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=scenario,
        legacy_ai_categories=frozenset(),
    )[0]
    gcs_only = adjudicate(
        [item],
        interventions=[],
        session_findings=[
            _finding("GCS", "14/15", finding_type="vital", source="gcs_modal"),
        ],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=scenario,
        legacy_ai_categories=frozenset(),
    )[0]

    assert neuro_procedure.state == "satisfied"
    assert pupil_exam.state == "satisfied"
    assert partner_pupil_exam.state == "satisfied"
    assert gcs_only.state == "not_satisfied"


def test_head_injury_dcap_btls_head_exam_satisfies_focused_head_item():
    from app.rubric_loader import compose_active_checklist, load_call_type_rubric

    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json"
    scenario = json.loads(scenario_path.read_text())
    rubric = load_call_type_rubric("head_injury", "training")
    composed = compose_active_checklist(
        base_items=load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None),
        rubric=rubric,
        provider_level="EMT",
        scenario=scenario,
    )
    item = next(
        item for item in composed.items
        if item.id == "head_injury.dcap_btls_head"
    )

    head_dcap = adjudicate(
        [item],
        interventions=[],
        session_findings=[
            _finding(
                "DCAP-BTLS Assessment — Head",
                "No deformity, contusions, abrasions, punctures, burns, tenderness, lacerations, or swelling noted.",
                finding_type="exam",
                source="student_stated_exam",
            ),
        ],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=scenario,
        legacy_ai_categories=frozenset(),
    )[0]
    partner_head_dcap = adjudicate(
        [item],
        interventions=[],
        session_findings=[
            _finding(
                "DCAP-BTLS Assessment — Head",
                "No deformity, contusions, abrasions, punctures, burns, tenderness, lacerations, or swelling noted.",
                finding_type="exam",
                source="partner_reported_exam",
            ),
        ],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=scenario,
        legacy_ai_categories=frozenset(),
    )[0]

    assert head_dcap.state == "satisfied"
    assert partner_head_dcap.state == "satisfied"


def test_head_injury_structured_exam_rows_credit_neuro_and_general_head_items():
    from app.rubric_loader import compose_active_checklist, load_call_type_rubric

    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/trauma/peds_trauma_07_head_injury.json"
    scenario = json.loads(scenario_path.read_text())
    rubric = load_call_type_rubric("head_injury", "training")
    composed = compose_active_checklist(
        base_items=load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None),
        rubric=rubric,
        provider_level="EMT",
        scenario=scenario,
    )
    by_id = {item.id: item for item in composed.items}
    findings = [
        _finding("GCS", "14 (E4 V4 M6)", finding_type="vital", fid=1, source="gcs_modal"),
        _finding(
            "Neurological Assessment",
            "GCS 14/15 (E4 V4 M6); Patient is alert but confused; Pupils: R 4 mm sluggish, L 3 mm brisk",
            finding_type="exam",
            fid=2,
            source="student_stated_exam",
        ),
        _finding("Pupils", "R 4 mm sluggish, L 3 mm brisk", finding_type="exam", fid=3, source="student_stated_exam"),
        _finding("LOC", "No loss of consciousness; cried right after; vomited once", finding_type="history", fid=4, source="ai_roleplay_tag"),
        _finding("Vomiting", "Vomited once about 2 minutes after fall", finding_type="history", fid=5, source="ai_roleplay_tag"),
        _finding(
            "DCAP-BTLS Head",
            "Head/scalp DCAP-BTLS assessed for deformity, contusions, abrasions, punctures, burns, tenderness, lacerations, swelling, and skull step-off; no visible scalp laceration or external hemorrhage noted.",
            finding_type="exam",
            fid=6,
            source="student_stated_exam",
        ),
        _finding(
            "Facial / Mouth / Nose Assessment",
            "Face, mouth, and nose assessed for DCAP-BTLS and visible injury.",
            finding_type="exam",
            fid=7,
            source="student_stated_exam",
        ),
        _finding(
            "Tracheal Position",
            "Trachea assessed and found midline without deviation.",
            finding_type="exam",
            fid=11,
            source="student_stated_exam",
        ),
        _finding(
            "Jugular Veins / JVD",
            "Jugular veins assessed: no jugular vein distension noted.",
            finding_type="exam",
            fid=12,
            source="student_stated_exam",
        ),
        _finding(
            "Neck / Cervical Spine Assessment",
            "Neck and cervical spine assessed for DCAP-BTLS, midline tenderness, deformity, and step-off.",
            finding_type="exam",
            fid=13,
            source="student_stated_exam",
        ),
        _finding(
            "Chest Assessment",
            "Chest inspected and palpated for DCAP-BTLS: no chest wall deformity, tenderness, crepitus, instability, or visible trauma noted.",
            finding_type="exam",
            fid=8,
            source="student_stated_exam",
        ),
        _finding(
            "Abdomen Assessment",
            "Abdomen inspected and palpated: soft, non-distended, and non-tender; no visible trauma noted.",
            finding_type="exam",
            fid=9,
            source="student_stated_exam",
        ),
        _finding(
            "Pelvis Assessment",
            "Pelvis assessed: stable without tenderness, deformity, or visible trauma.",
            finding_type="exam",
            fid=10,
            source="student_stated_exam",
        ),
    ]

    for item_id in [
        "head_injury.neuro_assessment",
        "head_injury.pupil_assessment",
        "head_injury.dcap_btls_head",
    ]:
        state = adjudicate(
            [by_id[item_id]],
            interventions=[],
            session_findings=findings,
            session_events=[],
            chat_messages=[],
            scene_entry=None,
            submitted_dmist=None,
            submitted_narrative=None,
            scenario=scenario,
            legacy_ai_categories=frozenset(),
        )[0]
        assert state.state == "satisfied", item_id


def test_soft_tissue_mechanism_screen_uses_structured_mechanism_and_loc_history():
    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/trauma/peds_trauma_01_soft_tissue.json"
    scenario = json.loads(scenario_path.read_text())
    item = next(
        item for item in load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
        if item.id == "peds_trauma_01_soft_tissue.mechanism_screen"
    )

    chief_only = adjudicate(
        [item],
        interventions=[],
        session_findings=[
            _finding("Patient Chief Complaint", "head cut after fall", finding_type="history", fid=1),
        ],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=scenario,
        legacy_ai_categories=frozenset(),
    )[0]
    complete = adjudicate(
        [item],
        interventions=[],
        session_findings=[
            _finding(
                "Events",
                "running in the living room, tripped on the rug, struck the corner of the coffee table",
                finding_type="history",
                fid=2,
            ),
            _finding(
                "LOC",
                "no loss of consciousness; cried immediately",
                finding_type="history",
                fid=3,
            ),
        ],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=scenario,
        legacy_ai_categories=frozenset(),
    )[0]

    assert item.allowed_tiers == [1]
    assert item.requirement_logic == "all"
    assert chief_only.state == "not_satisfied"
    assert complete.state == "satisfied"


def test_soft_tissue_neuro_assessment_credits_structured_gcs_and_loc_history():
    scenario_path = Path(__file__).resolve().parents[1] / "app/scenarios/pediatric/trauma/peds_trauma_01_soft_tissue.json"
    scenario = json.loads(scenario_path.read_text())
    item = next(
        item for item in load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
        if item.id == "peds_trauma_01_soft_tissue.neuro_assessment"
    )

    baseline_only = adjudicate(
        [item],
        interventions=[],
        session_findings=[
            _finding("GCS", "15 (E4 V5 M6)", finding_type="exam", fid=1),
        ],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=scenario,
        legacy_ai_categories=frozenset(),
    )[0]
    complete = adjudicate(
        [item],
        interventions=[],
        session_findings=[
            _finding("GCS", "15 (E4 V5 M6)", finding_type="exam", fid=1),
            _finding("LOC", "no loss of consciousness; cried immediately", finding_type="history", fid=2),
        ],
        session_events=[],
        chat_messages=[],
        scene_entry=None,
        submitted_dmist=None,
        submitted_narrative=None,
        scenario=scenario,
        legacy_ai_categories=frozenset(),
    )[0]

    assert item.allowed_tiers == [1]
    assert item.requirement_logic == "all"
    assert baseline_only.state == "not_satisfied"
    assert complete.state == "satisfied"


def test_tier1_history_finding_credits_sample_allergies():
    item = _item(
        item_id="ems.medical.sample_allergies",
        tier1_match=TierOneMatchSpec(
            source="finding",
            finding_type="history",
            finding_key_pattern=r"(?i)^allergies?$",
        ),
    )
    hit = _try_tier1(
        item, scenario={}, scene_entry=None,
        findings=[_finding("Allergies", "NKDA", finding_type="history", source="ai_roleplay_tag")],
        interventions=[], events=[],
    )
    miss = _try_tier1(
        item, scenario={}, scene_entry=None,
        findings=[_finding("Allergies", "NKDA", finding_type="exam", source="ai_roleplay_tag")],
        interventions=[], events=[],
    )
    assert hit is not None
    assert miss is None


def test_tier1_history_finding_credits_sample_meds():
    item = _item(
        item_id="ems.medical.sample_meds",
        tier1_match=TierOneMatchSpec(
            source="finding",
            finding_type="history",
            finding_key_pattern=r"(?i)^medications?$",
        ),
    )
    hit = _try_tier1(
        item, scenario={}, scene_entry=None,
        findings=[_finding("Medications", "Amoxicillin", finding_type="history", source="ai_roleplay_tag")],
        interventions=[], events=[],
    )
    assert hit is not None


def test_tier1_history_finding_credits_sample_pmh():
    item = _item(
        item_id="ems.medical.sample_history",
        tier1_match=TierOneMatchSpec(
            source="finding",
            finding_type="history",
            finding_key_pattern=r"(?i)^pmh$",
        ),
    )
    hit = _try_tier1(
        item, scenario={}, scene_entry=None,
        findings=[_finding("PMH", "asthma", finding_type="history", source="ai_roleplay_tag")],
        interventions=[], events=[],
    )
    miss = _try_tier1(
        item, scenario={}, scene_entry=None,
        findings=[_finding("Medications", "Amoxicillin", finding_type="history", source="ai_roleplay_tag")],
        interventions=[], events=[],
    )
    assert hit is not None
    assert miss is None


def test_tier1_history_finding_credits_last_oral():
    item = _item(
        item_id="ems.medical.sample_last_oral",
        tier1_match=TierOneMatchSpec(
            source="finding",
            finding_type="history",
            finding_key_pattern=r"(?i)^last\s+oral",
        ),
    )
    hit = _try_tier1(
        item, scenario={}, scene_entry=None,
        findings=[_finding("Last Oral Intake", "2 hours ago", finding_type="history", source="ai_roleplay_tag")],
        interventions=[], events=[],
    )
    assert hit is not None


def test_tier2_transcript_beats_finding_text():
    """Transcript match takes priority over finding text for all subtypes."""
    item = _item(subtype="assessment", patterns=[r"(?i)blood.glucose"])
    findings = [_finding("blood_glucose", "42 mg/dL")]
    result = _try_tier2(
        item,
        transcript="I measured blood glucose",
        session_findings=findings,
    )
    assert result is not None
    assert result.source_type == "transcript_match"


def test_tier2_intervention_subtype_ignores_finding_text():
    """intervention subtype is not eligible for session_finding_text."""
    item = _item(subtype="intervention", patterns=[r"(?i)epinephrine"])
    findings = [_finding("med_note", "epinephrine 0.15mg IM given")]
    result = _try_tier2(item, transcript="", session_findings=findings)
    assert result is None


# ── _try_tier2: submitted_document_text ──────────────────────────────────────


def test_tier2_screen_ignores_dmist():
    """Submitted documents cannot create clinical screen credit."""
    item = _item(subtype="screen", patterns=[r"(?i)epiglottitis"])
    result = _try_tier2(
        item,
        transcript="",
        submitted_dmist="Differential: croup vs epiglottitis — ruled out epiglottitis",
    )
    assert result is None


def test_tier2_screen_ignores_narrative():
    item = _item(subtype="screen", patterns=[r"(?i)epiglottitis"])
    result = _try_tier2(
        item,
        transcript="",
        submitted_dmist=None,
        submitted_narrative="Considered epiglottitis and ruled out based on clinical picture",
    )
    assert result is None


def test_tier2_documentation_handoff_dmist_beats_narrative():
    """DMIST is searched before narrative for documentation/handoff items."""
    item = _item(subtype="documentation_handoff", patterns=[r"(?i)epiglottitis"])
    result = _try_tier2(
        item,
        transcript="",
        submitted_dmist="screened for epiglottitis",
        submitted_narrative="also mentioned epiglottitis here",
    )
    assert result is not None
    assert result.document_type == "dmist"


def test_tier2_transcript_beats_dmist():
    """Transcript match wins over DMIST for screen items."""
    item = _item(subtype="screen", patterns=[r"(?i)epiglottitis"])
    result = _try_tier2(
        item,
        transcript="I am screening for epiglottitis",
        submitted_dmist="epiglottitis mentioned in DMIST",
    )
    assert result is not None
    assert result.source_type == "transcript_match"


def test_tier2_assessment_subtype_ignores_dmist():
    """assessment subtype is NOT eligible for submitted_document_text."""
    item = _item(subtype="assessment", patterns=[r"(?i)blood pressure"])
    result = _try_tier2(
        item,
        transcript="",
        submitted_dmist="Blood pressure was 120/80",
    )
    assert result is None


def test_tier2_intervention_subtype_ignores_dmist():
    """intervention subtype is NOT eligible for submitted_document_text."""
    item = _item(subtype="intervention", patterns=[r"(?i)aspirin"])
    result = _try_tier2(
        item,
        transcript="",
        submitted_dmist="Patient received aspirin 324mg",
    )
    assert result is None


# ── _try_tier2: source priority full cascade ──────────────────────────────────


def test_tier2_screen_transcript_beats_ignored_dmist_and_finding_text():
    """Clinical screen credit comes from the student's run transcript, not docs/findings."""
    item = _item(subtype="screen", patterns=[r"(?i)epiglottitis"])
    findings = [_finding("differential_note", "epiglottitis considered")]
    result = _try_tier2(
        item,
        transcript="I am screening for epiglottitis.",
        session_findings=findings,
        submitted_dmist="epiglottitis in DMIST",
    )
    assert result is not None
    assert result.source_type == "transcript_match"


# ── _try_tier1: scene_entry dot-path ─────────────────────────────────────────


def _scene_entry_item(path: str) -> ChecklistItem:
    return ChecklistItem(
        id="scene_safety",
        description="Completed scene safety check",
        subtype="scene_entry",
        category="clinical_performance",
        point_value=5,
        allowed_tiers=[1],
        preferred_tier=1,
        tier1_match=TierOneMatchSpec(source="scene_entry", scene_entry_path=path),
    )


def test_tier1_scene_entry_ppe_satisfied():
    item = _scene_entry_item("ppe")
    scenario = {"scene_entry_scoring": {"ppe": {"required": ["gloves"]}}}
    result = _try_tier1(
        item,
        interventions=[],
        findings=[],
        events=[],
        scene_entry={"ppe_donned": ["Gloves", "Eye Protection"]},
        scenario=scenario,
    )
    assert result is not None
    assert result.source_type == "scene_entry"
    assert result.tier == 1


def test_tier1_scene_entry_ppe_missing_item():
    item = _scene_entry_item("ppe")
    scenario = {"scene_entry_scoring": {"ppe": {"required": ["gloves", "mask"]}}}
    result = _try_tier1(
        item,
        interventions=[],
        findings=[],
        events=[],
        scene_entry={"ppe_donned": ["Gloves"]},
        scenario=scenario,
    )
    assert result is None


def test_tier1_scene_entry_scene_approach_requires_correct_pd_decision():
    item = _scene_entry_item("scene_approach")
    safe_scene = {"scene": {"hazards": []}}
    unsafe_scene = {
        "scene_entry_scoring": {
            "scene_safety": {
                "wait_for_pd_required": True,
            }
        }
    }

    direct_safe = _try_tier1(
        item,
        interventions=[],
        findings=[],
        events=[],
        scene_entry={"scene_approach": "direct_contact"},
        scenario=safe_scene,
    )
    wait_safe = _try_tier1(
        item,
        interventions=[],
        findings=[],
        events=[],
        scene_entry={"scene_approach": "waited_for_pd"},
        scenario=safe_scene,
    )
    wait_unsafe = _try_tier1(
        item,
        interventions=[],
        findings=[],
        events=[],
        scene_entry={"scene_approach": "waited_for_pd"},
        scenario=unsafe_scene,
    )
    direct_unsafe = _try_tier1(
        item,
        interventions=[],
        findings=[],
        events=[],
        scene_entry={"scene_approach": "direct_contact"},
        scenario=unsafe_scene,
    )

    assert direct_safe is not None
    assert wait_safe is None
    assert wait_unsafe is not None
    assert direct_unsafe is None


def test_unnecessary_pd_wait_misses_scene_safety_without_critical_failure():
    item = _scene_entry_item("scene_approach")
    item.critical_failure = True
    item.critical_failure_label = "Failure to determine scene safety"

    states = adjudicate(
        [item],
        interventions=[],
        session_findings=[],
        session_events=[],
        chat_messages=[],
        scene_entry={"scene_approach": "waited_for_pd", "ppe_donned": ["Gloves"]},
        submitted_dmist=None,
        submitted_narrative=None,
        scenario={"scene": {"hazards": []}},
    )

    state = states[0]
    assert state.state == "not_satisfied"
    assert state.earned_points == 0
    assert state.critical_failure_triggered is False
    assert state.notes == "unnecessary_pd_wait_delayed_patient_contact"
    assert _compute_critical_failure_status(states, [item]) is None


def test_tier1_scene_entry_generic_dot_path_truthy():
    """Generic dot-path returns evidence when leaf is truthy."""
    item = _scene_entry_item("safety.cleared")
    result = _try_tier1(
        item,
        interventions=[],
        findings=[],
        events=[],
        scene_entry={"safety": {"cleared": True}},
        scenario={},
    )
    assert result is not None
    assert result.source_type == "scene_entry"


def test_tier1_requires_concrete_source_for_challenge_gated_findings():
    item = _item(
        tier1_match=TierOneMatchSpec(
            source="finding",
            finding_type="exam",
            finding_key_pattern=r"(?i)lung.sounds?",
            eligible_sources=["lung_sound_challenge"],
            require_source=True,
        ),
        patterns=[r"(?i)lung sounds clear"],
    )

    legacy_null_source = _finding("Lung Sounds", "clear bilaterally", finding_type="exam", source=None)
    ai_source = _finding("Lung Sounds", "clear bilaterally", finding_type="exam", source="ai_roleplay_tag")
    challenge_source = _finding("Lung Sounds", "clear bilaterally", finding_type="exam", source="lung_sound_challenge")

    assert _try_tier1(item, interventions=[], findings=[legacy_null_source], events=[], scene_entry=None, scenario={}) is None
    assert _try_tier1(item, interventions=[], findings=[ai_source], events=[], scene_entry=None, scenario={}) is None
    assert _try_tier1(item, interventions=[], findings=[challenge_source], events=[], scene_entry=None, scenario={}) is not None


def test_tier1_scene_entry_generic_dot_path_falsy():
    """Generic dot-path returns None when leaf is falsy."""
    item = _scene_entry_item("safety.cleared")
    result = _try_tier1(
        item,
        interventions=[],
        findings=[],
        events=[],
        scene_entry={"safety": {"cleared": False}},
        scenario={},
    )
    assert result is None


def test_tier1_scene_entry_generic_dot_path_missing():
    """Generic dot-path returns None when path does not exist."""
    item = _scene_entry_item("hazmat.suit_donned")
    result = _try_tier1(
        item,
        interventions=[],
        findings=[],
        events=[],
        scene_entry={"safety": {"cleared": True}},
        scenario={},
    )
    assert result is None


def test_tier1_scene_entry_generic_dot_path_non_dict_node():
    """Returns None if an intermediate node is not a dict."""
    item = _scene_entry_item("safety.sub.field")
    result = _try_tier1(
        item,
        interventions=[],
        findings=[],
        events=[],
        scene_entry={"safety": "yes"},  # "safety" is a str, not dict
        scenario={},
    )
    assert result is None


def test_tier1_scene_entry_empty_scene_entry():
    item = _scene_entry_item("ppe")
    result = _try_tier1(
        item,
        interventions=[],
        findings=[],
        events=[],
        scene_entry=None,
        scenario={},
    )
    assert result is None


def test_general_impression_can_be_satisfied_by_pat_scene_entry():
    item = ChecklistItem(
        id="ems.medical.general_impression",
        description="Forms or states general impression",
        subtype="assessment",
        category="clinical_performance",
        point_value=1,
        tier1_match=TierOneMatchSpec(source="scene_entry", scene_entry_path="pat_assessment"),
    )
    result = _try_tier1(
        item,
        interventions=[],
        findings=[],
        events=[],
        scene_entry={"pat_assessment": "sick"},
        scenario={},
    )
    assert result is not None
    assert result.source_type == "scene_entry"


def test_tier1_session_event_satisfied_by_type_and_key_pattern():
    item = _item(
        subtype="transport",
        tier1_match=TierOneMatchSpec(
            source="session_event",
            event_type="medical_control_contact",
            event_key_pattern=r"contacted",
        ),
    )
    result = _try_tier1(
        item,
        interventions=[],
        findings=[],
        events=[_event("medical_control_contact", "medical_control_contacted")],
        scene_entry=None,
        scenario={},
    )

    assert result is not None
    assert result.source_type == "session_event"
    assert result.source_id == 1
    assert result.timestamp == "2025-01-01T12:05:00+00:00"


def test_impression_challenge_event_can_satisfy_impression_rubric_items():
    item = _item(
        item_id="ems.medical.chief_life_threats",
        subtype="assessment",
        tier1_match=TierOneMatchSpec(
            source="session_event",
            event_type="challenge_completed",
            event_key_pattern=r"(?i)^impression:",
        ),
    )
    result = _try_tier1(
        item,
        interventions=[],
        findings=[],
        events=[_event("challenge_completed", "impression:default")],
        scene_entry=None,
        scenario={},
    )

    assert result is not None
    assert result.source_type == "session_event"
    assert result.source_id == 1


def test_tier1_session_event_can_require_correct_result():
    item = _item(
        item_id="peds_croup_01.croup_recognition",
        subtype="screen",
        tier1_match=TierOneMatchSpec(
            source="session_event",
            event_type="challenge_completed",
            event_key_pattern=r"(?i)^impression:",
            event_data_result="correct",
        ),
    )

    result = _try_tier1(
        item,
        interventions=[],
        findings=[],
        events=[
            _event_with_data("challenge_completed", "impression:default", {"result": "incorrect"}),
            _event_with_data("challenge_completed", "impression:default", {"result": "correct"}, eid=2),
        ],
        scene_entry=None,
        scenario={},
    )

    assert result is not None
    assert result.source_type == "session_event"
    assert result.source_id == 2


def test_cpr_challenge_rubric_integration_maps_score_to_parent_item_points():
    item = _item(
        item_id="newborn_resus_01_nrp.neonatal_resuscitation_management",
        subtype="intervention",
        point_value=20,
        tier1_match=TierOneMatchSpec(
            source="session_event",
            event_type="challenge_completed",
            event_key_pattern=r"(?i)^cpr:newborn_resus_01_nrp_cpr$",
        ),
    )
    states = adjudicate(
        [item],
        interventions=[],
        session_findings=[],
        session_events=[
            _event_with_data(
                "challenge_completed",
                "cpr:newborn_resus_01_nrp_cpr",
                {"challenge_type": "neonatal_resuscitation", "score": 25},
            )
        ],
        chat_messages=[],
        scene_entry={},
        submitted_dmist=None,
        submitted_narrative=None,
        scenario={
            "cpr_challenge": {
                "rubric_integration": {
                    "item_id": "newborn_resus_01_nrp.neonatal_resuscitation_management",
                    "weight_points": 20,
                }
            }
        },
        legacy_ai_categories=frozenset(),
    )

    assert states[0].state == "partial"
    assert states[0].earned_points == 5
    assert states[0].notes == "challenge score mapped into parent checklist item"


def test_tier1_session_event_requires_matching_type():
    item = _item(
        subtype="transport",
        tier1_match=TierOneMatchSpec(
            source="session_event",
            event_type="medical_control_contact",
        ),
    )
    result = _try_tier1(
        item,
        interventions=[],
        findings=[],
        events=[_event("clinical_decision", "medical_control_contacted")],
        scene_entry=None,
        scenario={},
    )

    assert result is None


def _scope_guardrail_item() -> ChecklistItem:
    return ChecklistItem(
        id="scope.no_out_of_scope_actions",
        description="No out-of-scope medications or procedures attempted",
        subtype="intervention",
        category="scope_adherence",
        point_value=10,
        allowed_tiers=[1],
        preferred_tier=1,
        tier1_match=TierOneMatchSpec(source="no_out_of_scope_actions"),
    )


def test_no_out_of_scope_actions_allows_history_questions_about_oos_medication():
    item = _scope_guardrail_item()
    result = _try_tier1(
        item,
        interventions=[],
        findings=[],
        events=[],
        scene_entry=None,
        scenario={"correct_treatment": {"out_of_scope_bls": ["glucagon_im_in"]}},
        chat_messages=[_message("Does he have a glucagon kit at home?")],
        provider_level="EMT",
    )

    assert result is not None
    assert result.source_type == "scope_guardrail"


def test_no_out_of_scope_actions_rejects_command_to_give_oos_medication():
    item = _scope_guardrail_item()
    result = _try_tier1(
        item,
        interventions=[],
        findings=[],
        events=[],
        scene_entry=None,
        scenario={"correct_treatment": {"out_of_scope_bls": ["glucagon_im_in"]}},
        chat_messages=[_message("Give him glucagon now.")],
        provider_level="EMT",
    )

    assert result is None


def test_no_out_of_scope_actions_rejects_applied_intervention_above_level():
    item = _scope_guardrail_item()
    result = _try_tier1(
        item,
        interventions=[_intervention("iv_io_access")],
        findings=[],
        events=[],
        scene_entry=None,
        scenario={
            "vitals": {
                "interventions": {
                    "iv_io_access": {"label": "IV/IO access", "within_bls_scope": False}
                }
            }
        },
        chat_messages=[],
        provider_level="EMT",
    )

    assert result is None


def test_inappropriate_intervention_attempt_creates_category_penalty_item():
    event = _event_with_data(
        "clinical_decision",
        "inappropriate_intervention_attempted",
        {
            "category": "clinical_performance",
            "attempt_type": "cpr_not_indicated",
            "label": "CPR attempted when not indicated",
            "reason": "Patient is responsive, breathing, and has a pulse.",
            "penalty_points": 4,
        },
    )

    items, states = _synthetic_inappropriate_attempt_penalties([event])
    scores = compute_scores(states, items, legacy_ai_categories=frozenset(), scenario={})

    assert len(items) == 1
    assert items[0].category == "clinical_performance"
    assert items[0].point_value == 4
    assert states[0].state == "contradicted"
    assert "responsive" in (states[0].notes or "")
    assert scores["clinical_performance"].total == 0
    assert scores["clinical_performance"].deducted == 4
    assert scores["clinical_performance"].max == 4


def test_out_of_scope_fto_attempt_routes_to_scope_adherence():
    event = _event_with_data(
        "clinical_decision",
        "inappropriate_intervention_attempted",
        {
            "category": "scope_adherence",
            "attempt_type": "out_of_scope_intervention",
            "label": "Glucagon IM",
            "reason": "Outside BLS scope.",
            "penalty_points": 3,
        },
    )

    items, states = _synthetic_inappropriate_attempt_penalties([event])

    assert items[0].category == "scope_adherence"
    assert items[0].description == "Unsafe/inappropriate action attempted — Glucagon IM"
    assert states[0].state == "contradicted"


def test_tier1_post_intervention_finding_requires_finding_after_intervention():
    item = _item(
        subtype="reassessment",
        tier1_match=TierOneMatchSpec(
            source="post_intervention_finding",
            finding_type="vital",
            finding_key_pattern=r"(?i)(spo2|rr|resp)",
        ),
    )
    before = types.SimpleNamespace(
        id=1,
        key="SpO2",
        value="93 %",
        finding_type="vital",
        captured_at=datetime(2025, 1, 1, 12, 4, 0, tzinfo=timezone.utc),
    )
    after = types.SimpleNamespace(
        id=2,
        key="Resp Rate",
        value="44 breaths/min",
        finding_type="vital",
        captured_at=datetime(2025, 1, 1, 12, 7, 0, tzinfo=timezone.utc),
    )

    result = _try_tier1(
        item,
        interventions=[_intervention("o2_blowby", minute=5)],
        findings=[before, after],
        events=[],
        scene_entry=None,
        scenario={},
    )

    assert result is not None
    assert result.source_type == "post_intervention_finding"
    assert result.source_id == 2


def test_tier1_post_intervention_finding_rejects_baseline_only():
    item = _item(
        subtype="reassessment",
        tier1_match=TierOneMatchSpec(
            source="post_intervention_finding",
            finding_type="vital",
            finding_key_pattern=r"(?i)(spo2|rr|resp)",
        ),
    )
    result = _try_tier1(
        item,
        interventions=[_intervention("o2_blowby", minute=5)],
        findings=[_finding_ts("SpO2", "93 %")],
        events=[],
        scene_entry=None,
        scenario={},
    )

    assert result is None


def test_tier1_intervention_without_specific_key_accepts_any_applied_intervention():
    item = _item(
        item_id="ems.medical.treatment_plan",
        subtype="intervention",
        tier1_match=TierOneMatchSpec(source="intervention"),
    )

    result = _try_tier1(
        item,
        interventions=[_intervention("albuterol_svn", minute=5)],
        findings=[],
        events=[],
        scene_entry=None,
        scenario={},
    )

    assert result is not None
    assert result.source_type == "intervention_record"
    assert result.source_id == 1


def test_timing_constraint_before_item_preserves_score_when_order_is_correct():
    mc_item = _item(
        item_id="mc_before_ntg",
        subtype="transport",
        tier1_match=TierOneMatchSpec(
            source="session_event",
            event_type="medical_control_contact",
        ),
    ).model_copy(update={
        "timing_constraint": TimingConstraint(
            type="before_item",
            reference_item_id="ntg_given",
            violation_consequence="deduction_override",
        )
    })
    ntg_item = _item(
        item_id="ntg_given",
        subtype="intervention",
        tier1_match=TierOneMatchSpec(source="intervention", intervention_key="nitroglycerin"),
    )

    states = _try_adjudicate_for_tests(
        [mc_item, ntg_item],
        interventions=[_intervention("nitroglycerin", minute=10)],
        events=[_event("medical_control_contact", "medical_control_contacted")],
    )

    mc_state = next(state for state in states if state.item_id == "mc_before_ntg")
    assert mc_state.state == "satisfied"
    assert mc_state.timing_violation is None
    assert mc_state.earned_points == 2


def test_timing_constraint_before_item_deducts_when_order_is_wrong():
    mc_item = _item(
        item_id="mc_before_ntg",
        subtype="transport",
        tier1_match=TierOneMatchSpec(
            source="session_event",
            event_type="medical_control_contact",
        ),
    ).model_copy(update={
        "timing_constraint": TimingConstraint(
            type="before_item",
            reference_item_id="ntg_given",
            violation_consequence="deduction_override",
        )
    })
    ntg_item = _item(
        item_id="ntg_given",
        subtype="intervention",
        tier1_match=TierOneMatchSpec(source="intervention", intervention_key="nitroglycerin"),
    )

    states = _try_adjudicate_for_tests(
        [mc_item, ntg_item],
        interventions=[_intervention("nitroglycerin", minute=4)],
        events=[_event("medical_control_contact", "medical_control_contacted")],
    )

    mc_state = next(state for state in states if state.item_id == "mc_before_ntg")
    assert mc_state.state == "not_satisfied"
    assert mc_state.timing_violation is True
    assert mc_state.earned_points == 0


def test_timing_constraint_after_item_deducts_when_prerequisite_missing():
    oral_glucose = _item(
        item_id="oral_glucose",
        subtype="intervention",
        tier1_match=TierOneMatchSpec(source="intervention", intervention_key="oral_glucose"),
        point_value=8,
    ).model_copy(update={
        "timing_constraint": TimingConstraint(
            type="after_item",
            reference_item_id="swallow_screen",
            violation_consequence="deduction_override",
        )
    })
    swallow_screen = _item(
        item_id="swallow_screen",
        subtype="screen",
        patterns=[r"(?i)swallow"],
        point_value=4,
    )

    states = _try_adjudicate_for_tests(
        [swallow_screen, oral_glucose],
        interventions=[_intervention("oral_glucose", minute=4)],
    )

    oral_state = next(state for state in states if state.item_id == "oral_glucose")
    assert oral_state.state == "not_satisfied"
    assert oral_state.timing_violation is True
    assert oral_state.earned_points == 0


def test_diabetic_protocol_oral_glucose_deducts_when_given_before_swallow_screen():
    swallow_screen = _item(
        item_id="hypoglycemia.swallow_assessment",
        subtype="screen",
        patterns=[r"(?i)swallow|gag|seiz|vomit|protect.*airway"],
        point_value=4,
    )
    protocol_oral_glucose = _item(
        item_id="peds_diabetic_emergency_01.protocol_oral_glucose",
        subtype="intervention",
        tier1_match=TierOneMatchSpec(source="intervention", intervention_key="oral_glucose"),
        point_value=10,
    ).model_copy(update={
        "timing_constraint": TimingConstraint(
            type="after_item",
            reference_item_id="hypoglycemia.swallow_assessment",
            violation_consequence="deduction_override",
        )
    })

    states = _try_adjudicate_for_tests(
        [swallow_screen, protocol_oral_glucose],
        interventions=[_intervention("oral_glucose", minute=4)],
    )

    oral_state = next(state for state in states if state.item_id == "peds_diabetic_emergency_01.protocol_oral_glucose")
    assert oral_state.state == "not_satisfied"
    assert oral_state.timing_violation is True
    assert oral_state.earned_points == 0


def test_shared_hypoglycemia_oral_glucose_deducts_when_swallow_screen_after_med():
    swallow_screen = _item(
        item_id="hypoglycemia.swallow_assessment",
        subtype="screen",
        tier1_match=TierOneMatchSpec(
            source="finding",
            finding_key_pattern=r"(?i)(gcs|avpu|loc|mental)",
            finding_value_pattern=r"(?i)(alert|verbal|oriented|confused|slurred|responds?\s+to\s+voice)",
        ),
        point_value=3,
    ).model_copy(update={
        "timing_constraint": TimingConstraint(
            type="before_item",
            reference_item_id="hypoglycemia.oral_glucose_administered",
            violation_consequence="deduction_override",
        )
    })
    oral_glucose = _item(
        item_id="hypoglycemia.oral_glucose_administered",
        subtype="intervention",
        tier1_match=TierOneMatchSpec(source="intervention", intervention_key="oral_glucose"),
        point_value=3,
    ).model_copy(update={
        "timing_constraint": TimingConstraint(
            type="after_item",
            reference_item_id="hypoglycemia.swallow_assessment",
            violation_consequence="deduction_override",
        )
    })

    states = _try_adjudicate_for_tests(
        [swallow_screen, oral_glucose],
        findings=[_finding_ts_typed("GCS", "alert and oriented, 15 (E4 V5 M6)", "exam", minute=3)],
        interventions=[_intervention("oral_glucose", minute=2)],
    )

    swallow_state = next(state for state in states if state.item_id == "hypoglycemia.swallow_assessment")
    oral_state = next(state for state in states if state.item_id == "hypoglycemia.oral_glucose_administered")
    assert swallow_state.state == "not_satisfied"
    assert swallow_state.timing_violation is True
    assert swallow_state.earned_points == 0
    assert oral_state.state == "not_satisfied"
    assert oral_state.timing_violation is True
    assert oral_state.earned_points == 0


def test_shared_hypoglycemia_oral_glucose_credits_when_swallow_screen_before_med():
    swallow_screen = _item(
        item_id="hypoglycemia.swallow_assessment",
        subtype="screen",
        tier1_match=TierOneMatchSpec(
            source="finding",
            finding_key_pattern=r"(?i)(gcs|avpu|loc|mental)",
            finding_value_pattern=r"(?i)(alert|verbal|oriented|confused|slurred|responds?\s+to\s+voice)",
        ),
        point_value=3,
    ).model_copy(update={
        "timing_constraint": TimingConstraint(
            type="before_item",
            reference_item_id="hypoglycemia.oral_glucose_administered",
            violation_consequence="deduction_override",
        )
    })
    oral_glucose = _item(
        item_id="hypoglycemia.oral_glucose_administered",
        subtype="intervention",
        tier1_match=TierOneMatchSpec(source="intervention", intervention_key="oral_glucose"),
        point_value=3,
    ).model_copy(update={
        "timing_constraint": TimingConstraint(
            type="after_item",
            reference_item_id="hypoglycemia.swallow_assessment",
            violation_consequence="deduction_override",
        )
    })

    states = _try_adjudicate_for_tests(
        [swallow_screen, oral_glucose],
        findings=[_finding_ts_typed("AVPU", "responds to voice, confused and slurred", "exam", minute=1)],
        interventions=[_intervention("oral_glucose", minute=2)],
    )

    swallow_state = next(state for state in states if state.item_id == "hypoglycemia.swallow_assessment")
    oral_state = next(state for state in states if state.item_id == "hypoglycemia.oral_glucose_administered")
    assert swallow_state.state == "satisfied"
    assert swallow_state.timing_violation is not True
    assert oral_state.state == "satisfied"
    assert oral_state.timing_violation is not True


def test_diabetic_protocol_oral_glucose_credits_when_loc_screen_precedes_med():
    swallow_screen = _item(
        item_id="hypoglycemia.swallow_assessment",
        subtype="screen",
        tier1_match=TierOneMatchSpec(
            source="finding",
            finding_key_pattern=r"(?i)(gcs|avpu|loc|mental)",
            finding_value_pattern=r"(?i)(alert|verbal|oriented|confused|slurred|responds?\s+to\s+voice)",
        ),
        point_value=4,
    )
    protocol_oral_glucose = _item(
        item_id="peds_diabetic_emergency_01.protocol_oral_glucose",
        subtype="intervention",
        tier1_match=TierOneMatchSpec(source="intervention", intervention_key="oral_glucose"),
        point_value=10,
    ).model_copy(update={
        "timing_constraint": TimingConstraint(
            type="after_item",
            reference_item_id="hypoglycemia.swallow_assessment",
            violation_consequence="deduction_override",
        )
    })

    states = _try_adjudicate_for_tests(
        [swallow_screen, protocol_oral_glucose],
        findings=[_finding_ts_typed("LOC", "verbal, confused and slurred", "exam", minute=1)],
        interventions=[_intervention("oral_glucose", minute=4)],
    )

    swallow_state = next(state for state in states if state.item_id == "hypoglycemia.swallow_assessment")
    oral_state = next(state for state in states if state.item_id == "peds_diabetic_emergency_01.protocol_oral_glucose")
    assert swallow_state.state == "satisfied"
    assert oral_state.state == "satisfied"
    assert oral_state.timing_violation is not True
    assert oral_state.earned_points == 10


def test_medical_secondary_assessment_credits_ams_neuro_exam_finding():
    scenario = json.loads(Path("app/scenarios/pediatric/medical/peds_diabetic_emergency_01.json").read_text())
    secondary = next(
        item for item in load_checklist(scenario, level="EMT", mca="mi_base", agency_id=None)
        if item.id == "ems.medical.secondary_assessment"
    )

    states = _try_adjudicate_for_tests(
        [secondary],
        findings=[
            _finding_ts_typed(
                "Mental Status",
                "Patient is confused with slurred speech and cannot follow multiple questions.",
                "exam",
                minute=1,
            )
        ],
    )

    state = next(s for s in states if s.item_id == "ems.medical.secondary_assessment")
    assert state.state == "satisfied"
    assert state.earned_points == 5


def test_critical_failure_status_triggers_for_missed_critical_item():
    item = ChecklistItem(
        id="scene_safety",
        description="Scene safety completed",
        subtype="scene_entry",
        category="clinical_performance",
        point_value=4,
        allowed_tiers=[1],
        preferred_tier=1,
        critical_failure=True,
        critical_failure_label="Unsafe scene entry",
        tier1_match=TierOneMatchSpec(source="scene_entry", scene_entry_path="ppe"),
    )
    status = _compute_critical_failure_status(
        [
            types.SimpleNamespace(
                item_id="scene_safety",
                state="not_satisfied",
                earned_points=0,
                evidence_references=[],
            )
        ],
        [item],
    )
    assert status is not None
    assert status["triggered"] is True
    assert status["display_label"] == "Critical Misses"
    assert status["items"][0]["label"] == "Unsafe scene entry"


def test_critical_failure_status_ignores_satisfied_critical_item():
    item = ChecklistItem(
        id="scene_safety",
        description="Scene safety completed",
        subtype="scene_entry",
        category="clinical_performance",
        point_value=4,
        allowed_tiers=[1],
        preferred_tier=1,
        critical_failure=True,
        critical_failure_label="Unsafe scene entry",
        tier1_match=TierOneMatchSpec(source="scene_entry", scene_entry_path="ppe"),
    )
    status = _compute_critical_failure_status(
        [
            types.SimpleNamespace(
                item_id="scene_safety",
                state="satisfied",
                earned_points=4,
                evidence_references=[],
            )
        ],
        [item],
    )
    assert status is None


def test_compute_scores_does_not_double_subtract_required_misses():
    done = _item(item_id="done", point_value=5, patterns=[r"(?i)did the observable"])
    missed = _item(item_id="missed", point_value=3, patterns=[r"(?i)missing behavior"])
    states = _try_adjudicate_for_tests([done, missed], findings=[_finding("done", "Did the observable thing", finding_type="exam")])
    done_state = next(state for state in states if state.item_id == "done")
    missed_state = next(state for state in states if state.item_id == "missed")
    assert done_state.state == "satisfied"
    assert missed_state.state == "not_satisfied"

    scores = compute_scores(states, [done, missed], legacy_ai_categories=frozenset(), scenario={"legacy_ai_categories": []})
    score = scores["clinical_performance"]

    assert score.earned == 5
    assert score.deducted == 3
    assert score.total == 5


# ── "all" logic Tier 2 guard ──────────────────────────────────────────────────


def _all_logic_item(
    item_id: str = "all_item",
    spec_keys: list[str] | None = None,
    tier2_patterns: list[str] | None = None,
) -> ChecklistItem:
    """ChecklistItem with requirement_logic='all' and two Tier 1 match specs.

    Mirrors what _rubric_item_to_checklist_item() produces for 'all' items:
    source='finding', allowed_tiers=[1].
    """
    keys = spec_keys or ["glucose", "loc"]
    specs = [
        TierOneMatchSpec(source="finding", finding_key_pattern=k, finding_type="vital")
        for k in keys
    ]
    return ChecklistItem(
        id=item_id,
        description="Check BGL and assess LOC",
        subtype="assessment",
        category="clinical_performance",
        point_value=4,
        allowed_tiers=[1],          # converter sets this for "all" items
        preferred_tier=1,
        tier2_patterns=tier2_patterns or [r"(?i)glucose"],
        tier1_match=None,
        tier1_matches=specs,
        requirement_logic="all",
    )


def test_all_logic_item_not_credited_via_tier2_when_tier1_fails():
    """An 'all' item with no structured Tier 1 evidence must not get credited
    through a Tier 2 transcript match, even when the transcript matches."""
    item = _all_logic_item(tier2_patterns=[r"(?i)glucose|(?i)blood sugar"])
    # Provide only transcript evidence — no authored_vitals findings.
    states = _try_adjudicate_for_tests(
        [item],
        findings=[],  # no structured findings at all
    )
    assert len(states) == 1
    assert states[0].state == "not_satisfied", (
        "Item with requirement_logic='all' must not be credited by Tier 2 transcript match"
    )


def test_all_logic_item_not_credited_when_only_one_of_two_specs_satisfied():
    """An 'all' item requires every spec to be independently satisfied.
    Satisfying only one sub-requirement must not earn credit."""
    item = _all_logic_item(spec_keys=["glucose", "loc"])
    # Only the glucose finding present — loc missing.
    glucose_finding = _finding("glucose", "72", finding_type="vital")
    states = _try_adjudicate_for_tests([item], findings=[glucose_finding])
    assert states[0].state == "not_satisfied", (
        "'all' item must remain not_satisfied when only one sub-requirement has evidence"
    )


def test_all_logic_item_credited_when_all_specs_satisfied():
    """An 'all' item must be credited when every spec has structured evidence."""
    item = _all_logic_item(spec_keys=["glucose", "loc"])
    glucose_finding = _finding("glucose", "72", finding_type="vital", fid=1)
    loc_finding = _finding("loc", "alert", finding_type="vital", fid=2)
    states = _try_adjudicate_for_tests(
        [item], findings=[glucose_finding, loc_finding]
    )
    assert states[0].state == "satisfied", (
        "'all' item must be satisfied when every sub-requirement has independent structured evidence"
    )


def test_all_logic_item_tier2_not_attempted_when_tier1_fails():
    """Confirm the defense-in-depth guard: _try_tier2 is never reached for
    'all' items because allowed_tiers=[1] excludes Tier 2."""
    item = _all_logic_item(tier2_patterns=[r"(?i)glucose"])
    # allowed_tiers=[1] means 2 not in item.allowed_tiers, so Tier 2 is skipped
    # regardless of the _is_all_logic guard — both guards must hold.
    assert 2 not in item.allowed_tiers, (
        "Converter must set allowed_tiers=[1] for 'all' items to block Tier 2"
    )
    states = _try_adjudicate_for_tests([item], findings=[])
    assert states[0].state == "not_satisfied"


# ── F2b shadow-suppression and overlay-audit behavioral assertions ─────────────


from app.checklist import EffectiveContext


def _training_ctx(provider_level: str = "EMT") -> EffectiveContext:
    return EffectiveContext(
        session_id="test-session-0",
        provider_level=provider_level,
        mca="mi_base",
        resolved_at="2026-05-13T00:00:00+00:00",
        deployment_context="training",
    )


def test_shadow_compose_returns_report_for_authored_call_type():
    """_shadow_compose_call_type_rubric returns a dict when call_type resolves."""
    report = _shadow_compose_call_type_rubric(
        scenario={"call_type": "hypoglycemia"},
        ctx=_training_ctx(),
        effective_checklist=[],
        composed_at="2026-05-13T00:00:00+00:00",
    )
    assert report is not None
    assert report["call_type"] == "hypoglycemia"
    assert report["call_type_item_count"] > 0


def test_shadow_compose_skips_when_no_call_type():
    """_shadow_compose_call_type_rubric returns None for scenarios without call_type."""
    report = _shadow_compose_call_type_rubric(
        scenario={},
        ctx=_training_ctx(),
        effective_checklist=[],
        composed_at="2026-05-13T00:00:00+00:00",
    )
    assert report is None, "Scenario without call_type must not produce a shadow report"


def test_shadow_compose_skips_for_unknown_call_type():
    """_shadow_compose_call_type_rubric returns None when call_type has no rubric file."""
    report = _shadow_compose_call_type_rubric(
        scenario={"call_type": "no_such_call_type_xyz"},
        ctx=_training_ctx(),
        effective_checklist=[],
        composed_at="2026-05-13T00:00:00+00:00",
    )
    assert report is None


def test_shadow_report_does_not_set_diagnostic_only_flag():
    """_shadow_compose_call_type_rubric itself does not set _diagnostic_only.
    That flag is added by the caller (adjudicate_and_persist) so the contract
    is clear: the function returns raw data, the caller marks it diagnostic."""
    report = _shadow_compose_call_type_rubric(
        scenario={"call_type": "hypoglycemia"},
        ctx=_training_ctx(),
        effective_checklist=[],
        composed_at="2026-05-13T00:00:00+00:00",
    )
    assert report is not None
    assert "_diagnostic_only" not in report, (
        "_diagnostic_only must be set by adjudicate_and_persist, not by _shadow_compose_call_type_rubric"
    )


def test_active_checklist_items_have_call_type_rubric_provenance():
    """Items from compose_active_checklist carry provenance='call_type_rubric'.
    This is required for QA/QI source tracing and for the debrief renderer to
    distinguish call-type items from scenario-authored items."""
    from app.rubric_loader import load_call_type_rubric, compose_active_checklist

    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    composed = compose_active_checklist(base_items=[], rubric=rubric, provider_level="EMT")
    ct_items = [i for i in composed.items if getattr(i, "provenance", None) == "call_type_rubric"]
    assert len(ct_items) > 0, "Composed checklist must include items with provenance='call_type_rubric'"


def test_active_compose_overlay_audit_is_empty_without_overlay_ops():
    """overlay_audit is an empty list (not None) when no overlay ops are applied.
    An empty list in active mode correctly signals 'composition ran, no overlay mutations.'"""
    from app.rubric_loader import load_call_type_rubric, compose_active_checklist

    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    composed = compose_active_checklist(base_items=[], rubric=rubric, provider_level="EMT")
    assert composed.overlay_audit == [], (
        "overlay_audit must be an empty list when no overlay ops are applied, not None"
    )


def test_level_excluded_items_absent_from_active_composed_checklist():
    """Items whose applicable_levels exclude the provider level must not appear
    in the active composed checklist — they should not affect max score or denomination."""
    from app.rubric_loader import load_call_type_rubric, compose_active_checklist

    rubric = load_call_type_rubric("pediatric_croup", "training")
    assert rubric is not None
    # nebulized_epi_severe is Paramedic-only
    paramedic_only = [i for i in rubric.items if i.applicable_levels == ["Paramedic"]]
    assert len(paramedic_only) == 1, "Expected exactly one Paramedic-only item in croup rubric"
    excluded_id = paramedic_only[0].item_id

    composed = compose_active_checklist(base_items=[], rubric=rubric, provider_level="EMT")
    composed_ids = {getattr(i, "id", None) for i in composed.items}
    assert excluded_id not in composed_ids, (
        f"{excluded_id} is Paramedic-only and must not appear in EMT active composition"
    )
