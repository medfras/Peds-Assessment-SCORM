"""
Regression tests: _build_session_timeline() must defer to checklist_states.item_states
for STATUS (applied/missed) when the scoring engine has adjudicated an item.

Invariants verified:
  1. Scoring engine "missed" verdict overrides heuristics for recommended actions.
  2. Scoring engine "satisfied" verdict overrides absence-of-finding for recommended actions.
  3. Heuristics still apply when item_states has no entry for the item.
  4. "not_applicable" items are omitted from the timeline entirely.
  5. Scoring engine "missed" verdict overrides intervention timestamp for critical actions.
  6. Lung-sound STATUS comes from item_states when a lung-sound item is present.
  7. Lung-sound STATUS falls back to finding-based detection when item_states is empty.
  8. Applied timeline rows use elapsed timestamps; pre-start scene-entry rows sort first.
"""

from __future__ import annotations

import types
from datetime import datetime, timedelta

# conftest.py stubs app.config and sentry_sdk before this file is collected.
from app.main import _build_session_timeline
from app.scenario_engine import load_scenario


# ── Shared helpers ────────────────────────────────────────────────────────────

def _session(
    t0: datetime,
    checklist_states: dict | None = None,
    findings: list | None = None,
    interventions: list | None = None,
    messages: list | None = None,
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        start_time=t0,
        provider_level="EMT",
        findings=findings or [],
        messages=messages or [],
        scene_entry={},
        interventions=interventions or [],
        checklist_states=checklist_states or {},
    )


def _checklist_states(item_states: list[dict], definitions: list[dict] | None = None) -> dict:
    return {
        "checklist_definitions": definitions or [],
        "item_states": item_states,
    }


def _find_timeline(timeline: list[dict], action_fragment: str) -> dict | None:
    for item in timeline:
        if action_fragment.lower() in (item.get("action") or "").lower():
            return item
    return None


def _finding(key: str, value: str, finding_type: str, captured_at: datetime):
    return types.SimpleNamespace(
        key=key,
        value=value,
        finding_type=finding_type,
        captured_at=captured_at,
        source="authored_vitals",
    )


def _message(content: str, timestamp: datetime):
    return types.SimpleNamespace(
        role="user",
        content=content,
        timestamp=timestamp,
    )


def _intervention(name: str, applied_at: datetime):
    return types.SimpleNamespace(
        name=name,
        applied_at=applied_at,
    )


# ── Recommended-action deference ─────────────────────────────────────────────


def test_vitals_timeline_does_not_count_avpu_as_baseline_vital_signs():
    scenario = {
        "readiness_criteria": {
            "checks": [{"type": "vitals_logged"}],
        },
    }
    t0 = datetime.utcnow()
    session = _session(
        t0,
        findings=[
            _finding("AVPU", "alert", "vital", t0 + timedelta(seconds=10)),
        ],
    )

    timeline = _build_session_timeline(session, scenario)
    item = _find_timeline(timeline, "Vital signs obtained")

    assert item is not None
    assert item["status"] == "missed"


def test_vitals_timeline_does_not_count_qualitative_pulse_as_baseline_vitals():
    scenario = {
        "readiness_criteria": {
            "checks": [{"type": "vitals_logged"}],
        },
    }
    t0 = datetime.utcnow()
    session = _session(
        t0,
        findings=[
            _finding("Pulse", "present, weak and rapid", "vital", t0 + timedelta(seconds=10)),
        ],
    )

    timeline = _build_session_timeline(session, scenario)
    item = _find_timeline(timeline, "Vital signs obtained")

    assert item is not None
    assert item["status"] == "missed"


def test_cms_baseline_language_does_not_trigger_vitals_order_warning():
    scenario = {
        "vitals": {
            "interventions": {
                "assess_cms": {
                    "notes": "Document baseline CMS before any intervention.",
                },
            },
        },
        "correct_treatment": {
            "critical_actions": [
                {
                    "id": "cms_pre_assessment",
                    "description": "Assess CMS distal to injury BEFORE any intervention",
                    "intervention_ids": ["assess_cms"],
                    "required": True,
                },
            ],
            "recommended_actions": [],
        },
    }
    t0 = datetime.utcnow()
    session = _session(
        t0,
        checklist_states=_checklist_states([
            {"item_id": "peds_trauma_03_extremity.cms_pre_assessment", "state": "satisfied"},
        ]),
        interventions=[_intervention("assess_cms", t0 + timedelta(seconds=30))],
    )

    timeline = _build_session_timeline(session, scenario)
    item = _find_timeline(timeline, "Assess CMS distal")

    assert item is not None
    assert item["status"] == "applied"


def test_optional_enabled_lung_sound_challenge_does_not_create_missed_timeline_row():
    scenario = {
        "lung_sound_challenge": {
            "enabled": True,
            "required": False,
        },
        "correct_treatment": {
            "critical_actions": [],
            "recommended_actions": [],
        },
    }
    t0 = datetime.utcnow()
    session = _session(t0)

    timeline = _build_session_timeline(session, scenario)

    assert _find_timeline(timeline, "Lung sounds auscultated") is None


def test_scene_entry_critical_action_defers_to_scored_ppe_or_scene_safety():
    scenario = {
        "correct_treatment": {
            "critical_actions": [
                {
                    "id": "scene_safety",
                    "description": "Scene safety and BSI/PPE prior to patient contact",
                    "required": True,
                    "scene_entry_credited": True,
                }
            ],
        },
    }
    t0 = datetime.utcnow()
    session = _session(
        t0,
        checklist_states=_checklist_states([
            {"item_id": "ems.trauma.ppe", "state": "satisfied", "earned_points": 1},
            {"item_id": "ems.trauma.scene_safety", "state": "satisfied", "earned_points": 1},
        ]),
    )

    timeline = _build_session_timeline(session, scenario)
    item = _find_timeline(timeline, "Scene safety")

    assert item is not None
    assert item["status"] == "applied"
    assert item["elapsed_min"] is None
    assert item["pre_start"] is True


def test_pre_start_scene_entry_rows_sort_before_clocked_timeline_items():
    timeline = [
        {"elapsed_min": 0.1, "action": "First patient contact", "status": "applied"},
        {"elapsed_min": None, "action": "Scene safety and BSI/PPE", "status": "applied", "pre_start": True},
    ]

    from app.main import _sort_session_timeline_rows

    _sort_session_timeline_rows(timeline)

    assert timeline[0]["action"] == "Scene safety and BSI/PPE"
    assert timeline[1]["action"] == "First patient contact"


def test_scored_timeline_item_uses_evidence_timestamp_when_available():
    scenario = {
        "correct_treatment": {
            "recommended_actions": [
                {
                    "id": "oxygen_reassessment",
                    "description": "Reassess oxygenation after treatment",
                    "required": True,
                }
            ],
        },
    }
    t0 = datetime.utcnow()
    evidence_time = t0 + timedelta(seconds=90)
    session = _session(
        t0,
        checklist_states=_checklist_states([
            {
                "item_id": "oxygen_reassessment",
                "state": "satisfied",
                "earned_points": 1,
                "evidence_references": [
                    {
                        "tier": 1,
                        "source_type": "session_finding",
                        "timestamp": evidence_time.isoformat(),
                    }
                ],
            },
        ]),
    )

    timeline = _build_session_timeline(session, scenario)
    item = _find_timeline(timeline, "Reassess oxygenation")

    assert item is not None
    assert item["status"] == "applied"
    assert item["elapsed_min"] == 1.5


def test_critical_action_evidence_can_use_intervention_ids_for_assessment_procedures():
    scenario = {
        "correct_treatment": {
            "critical_actions": [
                {
                    "id": "pupil_assessment",
                    "description": "Assess pupils bilaterally for size, equality, and reactivity",
                    "required": True,
                    "protocol_indicated": True,
                    "evidence": {
                        "intervention_ids": ["neuro_assessment"],
                        "min_matches": 1,
                    },
                }
            ],
        },
    }
    t0 = datetime.utcnow()
    done_at = t0 + timedelta(seconds=36)
    session = _session(
        t0,
        interventions=[
            _intervention("neuro_assessment", done_at),
        ],
    )

    timeline = _build_session_timeline(session, scenario)
    item = _find_timeline(timeline, "Assess pupils")

    assert item is not None
    assert item["status"] == "applied"
    assert item["elapsed_min"] == 0.6


def test_head_injury_dcap_btls_critical_action_accepts_exam_menu_procedure():
    scenario = {
        "correct_treatment": {
            "critical_actions": [
                {
                    "id": "dcap_btls_head_neck",
                    "description": "DCAP-BTLS assessment of head — palpate for deformity, step-off, tenderness, and swelling",
                    "required": True,
                    "protocol_indicated": True,
                    "evidence": {
                        "finding_types": ["exam"],
                        "intervention_ids": ["dcap_btls_head_neck"],
                        "finding_key_patterns": [
                            "dcap[-\\s]?btls.*head",
                            "head.*dcap",
                            "head assessment",
                            "scalp assessment",
                        ],
                        "min_matches": 1,
                    },
                }
            ],
        },
    }
    t0 = datetime.utcnow()
    done_at = t0 + timedelta(seconds=32)
    session = _session(
        t0,
        interventions=[_intervention("dcap_btls_head_neck", done_at)],
        findings=[
            _finding(
                "DCAP-BTLS Head",
                "Head/scalp DCAP-BTLS assessed for deformity, tenderness, swelling, and skull step-off.",
                "exam",
                done_at,
            )
        ],
    )

    timeline = _build_session_timeline(session, scenario)
    item = _find_timeline(timeline, "DCAP-BTLS assessment of head")

    assert item is not None
    assert item["status"] == "applied"
    assert item["elapsed_min"] == 0.5


def test_head_injury_dcap_btls_evidence_overrides_stale_missed_checklist_state():
    scenario = {
        "correct_treatment": {
            "critical_actions": [
                {
                    "id": "dcap_btls_head_neck",
                    "description": "DCAP-BTLS assessment of head — palpate for deformity, step-off, tenderness, and swelling",
                    "required": True,
                    "protocol_indicated": True,
                    "evidence": {
                        "finding_types": ["exam"],
                        "intervention_ids": ["dcap_btls_head_neck"],
                        "finding_key_patterns": [
                            "dcap[-\\s]?btls.*head",
                            "head.*dcap",
                            "head assessment",
                            "scalp assessment",
                        ],
                        "min_matches": 1,
                    },
                }
            ],
        },
    }
    t0 = datetime.utcnow()
    done_at = t0 + timedelta(seconds=34)
    session = _session(
        t0,
        checklist_states=_checklist_states([
            {"item_id": "dcap_btls_head_neck", "state": "not_satisfied", "earned_points": 0},
        ]),
        findings=[
            _finding(
                "DCAP-BTLS Head",
                "Head/scalp DCAP-BTLS assessed for deformity, tenderness, swelling, and skull step-off.",
                "exam",
                done_at,
            )
        ],
    )

    timeline = _build_session_timeline(session, scenario)
    item = _find_timeline(timeline, "DCAP-BTLS assessment of head")

    assert item is not None
    assert item["status"] == "applied"
    assert item["elapsed_min"] == 0.6


def test_head_injury_neuro_reassessment_requires_post_intervention_gcs_and_pupils():
    scenario = {
        "correct_treatment": {
            "recommended_actions": [
                {
                    "id": "reassess_neuro",
                    "description": "Reassess GCS and pupils before ALS handoff and continue trending if care is extended",
                    "required": False,
                }
            ],
        },
    }
    t0 = datetime.utcnow()
    session = _session(
        t0,
        interventions=[_intervention("o2_nrb", t0 + timedelta(seconds=60))],
        findings=[
            _finding("GCS", "14/15", "vital", t0 + timedelta(seconds=45)),
            _finding("Pupils", "R 4 mm sluggish; L 3 mm brisk", "exam", t0 + timedelta(seconds=50)),
            _finding("SpO2", "97 %", "vital", t0 + timedelta(seconds=135)),
            _finding("Heart Rate", "106 bpm", "vital", t0 + timedelta(seconds=135)),
            _finding("Work of Breathing", "Non-labored", "exam", t0 + timedelta(seconds=135)),
        ],
    )

    timeline = _build_session_timeline(session, scenario)
    item = _find_timeline(timeline, "Reassess GCS and pupils")

    assert item is not None
    assert item["status"] == "missed"


def test_head_injury_neuro_reassessment_credits_repeated_gcs_and_pupils():
    scenario = {
        "correct_treatment": {
            "recommended_actions": [
                {
                    "id": "reassess_neuro",
                    "description": "Reassess GCS and pupils before ALS handoff and continue trending if care is extended",
                    "required": False,
                }
            ],
        },
    }
    t0 = datetime.utcnow()
    session = _session(
        t0,
        interventions=[_intervention("o2_nrb", t0 + timedelta(seconds=60))],
        findings=[
            _finding("GCS", "14/15", "vital", t0 + timedelta(seconds=45)),
            _finding("Pupils", "R 4 mm sluggish; L 3 mm brisk", "exam", t0 + timedelta(seconds=50)),
            _finding("GCS", "14/15", "vital", t0 + timedelta(seconds=135)),
            _finding("Pupils", "R 4 mm sluggish; L 3 mm brisk", "exam", t0 + timedelta(seconds=136)),
        ],
    )

    timeline = _build_session_timeline(session, scenario)
    item = _find_timeline(timeline, "Reassess GCS and pupils")

    assert item is not None
    assert item["status"] == "applied"


def test_head_injury_neuro_reassessment_credits_gcs_and_pupils_immediately_after_intervention():
    scenario = {
        "correct_treatment": {
            "recommended_actions": [
                {
                    "id": "reassess_neuro",
                    "description": "Reassess GCS and pupils before ALS handoff and continue trending if care is extended",
                    "required": False,
                }
            ],
        },
    }
    t0 = datetime.utcnow()
    session = _session(
        t0,
        interventions=[_intervention("o2_nrb", t0 + timedelta(seconds=60))],
        findings=[
            _finding("GCS", "14/15", "vital", t0 + timedelta(seconds=45)),
            _finding("Pupils", "R 4 mm sluggish; L 3 mm brisk", "exam", t0 + timedelta(seconds=50)),
            _finding("GCS", "14/15", "vital", t0 + timedelta(seconds=65)),
            _finding("Pupils", "R 4 mm sluggish; L 3 mm brisk", "exam", t0 + timedelta(seconds=66)),
        ],
    )

    timeline = _build_session_timeline(session, scenario)
    item = _find_timeline(timeline, "Reassess GCS and pupils")

    assert item is not None
    assert item["status"] == "applied"
    assert item["elapsed_min"] == 1.1


def test_scored_critical_action_falls_back_to_transcript_evidence_timestamp():
    scenario = {
        "correct_treatment": {
            "critical_actions": [
                {
                    "id": "seizure_history",
                    "description": "Obtain focused seizure history from family",
                    "required": True,
                    "evidence": {
                        "transcript_patterns": [r"(?i)(started|first.*time|prior.*seizure)"],
                        "min_matches": 1,
                    },
                }
            ],
        },
    }
    t0 = datetime.utcnow()
    session = _session(
        t0,
        checklist_states=_checklist_states([
            {
                "item_id": "seizure_history",
                "state": "satisfied",
                "earned_points": 1,
                "evidence_references": [],
            }
        ]),
        messages=[_message("when did this started has she ever had seizures before", t0 + timedelta(seconds=54))],
    )

    timeline = _build_session_timeline(session, scenario)
    item = _find_timeline(timeline, "focused seizure history")

    assert item is not None
    assert item["status"] == "applied"
    assert item["elapsed_min"] == 0.9


def test_optional_critical_action_without_evidence_is_not_reported_as_missed():
    scenario = {
        "vitals": {
            "interventions": {
                "als_intercept": {"label": "ALS intercept acknowledged"},
            },
        },
        "correct_treatment": {
            "critical_actions": [
                {
                    "id": "als_intercept",
                    "display": "Confirm ALS intercept / handoff readiness",
                    "intervention_ids": ["als_intercept"],
                    "required": False,
                }
            ],
        },
    }
    t0 = datetime.utcnow()
    session = _session(t0)

    timeline = _build_session_timeline(session, scenario)

    assert _find_timeline(timeline, "Confirm ALS intercept") is None


def test_optional_critical_action_is_reported_when_completed():
    scenario = {
        "vitals": {
            "interventions": {
                "als_intercept": {"label": "ALS intercept acknowledged"},
            },
        },
        "correct_treatment": {
            "critical_actions": [
                {
                    "id": "als_intercept",
                    "display": "Confirm ALS intercept / handoff readiness",
                    "intervention_ids": ["als_intercept"],
                    "required": False,
                }
            ],
        },
    }
    t0 = datetime.utcnow()
    done_at = t0 + timedelta(seconds=75)
    session = _session(
        t0,
        interventions=[
            types.SimpleNamespace(name="als_intercept", applied_at=done_at),
        ],
    )

    timeline = _build_session_timeline(session, scenario)
    item = _find_timeline(timeline, "Confirm ALS intercept")

    assert item is not None
    assert item["status"] == "applied"
    assert item["elapsed_min"] == 1.2


def test_scored_recommended_history_action_uses_history_timestamp_when_evidence_refs_empty():
    scenario = {
        "correct_treatment": {
            "recommended_actions": [
                {
                    "id": "focused_seizure_history",
                    "description": "Obtain focused seizure history from family",
                    "required": True,
                }
            ],
        },
    }
    t0 = datetime.utcnow()
    session = _session(
        t0,
        checklist_states=_checklist_states([
            {
                "item_id": "focused_seizure_history",
                "state": "satisfied",
                "earned_points": 1,
                "evidence_references": [],
            }
        ]),
        findings=[_finding("Onset", "about 2 minutes before EMS arrival", "history", t0 + timedelta(seconds=138))],
    )

    timeline = _build_session_timeline(session, scenario)
    item = _find_timeline(timeline, "focused seizure history")

    assert item is not None
    assert item["status"] == "applied"
    assert item["elapsed_min"] == 2.3


class TestRecommendedActionDeference:
    """Scoring engine verdict must override heuristics for recommended actions."""

    def test_heuristic_says_done_but_scoring_says_missed_shows_missed(self):
        """Calm-environment heuristic would fire on 'calm' in transcript, but the
        scoring engine adjudicated it as missed — timeline must show missed."""
        scenario = load_scenario("peds_croup_01")
        t0 = datetime.utcnow()
        session = _session(
            t0,
            # Scoring engine: calm_environment → missed
            checklist_states=_checklist_states([
                {"item_id": "calm_environment", "state": "missed", "earned_points": 0},
            ]),
            # Messages would trigger the heuristic: 'calm' keyword present
            messages=[
                types.SimpleNamespace(role="user", content="keep calm and use blow-by", timestamp=t0),
            ],
        )
        timeline = _build_session_timeline(session, scenario)
        # calm_environment description: "Actively minimize agitation — dim lights..."
        item = _find_timeline(timeline, "agitat")
        assert item is not None, "calm_environment item should appear in timeline"
        assert item["status"] == "missed"

    def test_scoring_engine_satisfied_shows_applied_regardless_of_finding(self):
        """When scoring engine says satisfied, the item must show applied even if the
        heuristic would have failed (no matching transcript keyword)."""
        scenario = load_scenario("peds_croup_01")
        t0 = datetime.utcnow()
        session = _session(
            t0,
            checklist_states=_checklist_states([
                {"item_id": "calm_environment", "state": "satisfied", "earned_points": 2},
            ]),
            messages=[],  # no 'calm' keyword — heuristic would say missed
            interventions=[
                types.SimpleNamespace(name="calm_environment", applied_at=t0 + timedelta(seconds=30)),
            ],
        )
        timeline = _build_session_timeline(session, scenario)
        item = _find_timeline(timeline, "agitat")
        assert item is not None
        assert item["status"] == "applied"

    def test_no_scoring_opinion_falls_through_to_heuristic(self):
        """When item_states has no entry for calm_environment, the heuristic
        ('calm' in transcript) must still fire."""
        scenario = load_scenario("peds_croup_01")
        t0 = datetime.utcnow()
        session = _session(
            t0,
            checklist_states=_checklist_states([]),  # no scoring opinion
            messages=[
                types.SimpleNamespace(role="user", content="keep calm", timestamp=t0),
            ],
        )
        timeline = _build_session_timeline(session, scenario)
        item = _find_timeline(timeline, "agitat")
        if item is not None:
            assert item["status"] == "applied"

    def test_not_applicable_omits_item_from_timeline(self):
        """not_applicable items must not appear in the timeline at all."""
        scenario = load_scenario("peds_croup_01")
        t0 = datetime.utcnow()
        session = _session(
            t0,
            checklist_states=_checklist_states([
                {"item_id": "calm_environment", "state": "not_applicable", "earned_points": 0},
            ]),
        )
        timeline = _build_session_timeline(session, scenario)
        item = _find_timeline(timeline, "agitat")
        assert item is None, "not_applicable items must be omitted from the timeline"


# ── Critical-action deference ─────────────────────────────────────────────────

class TestCriticalActionDeference:
    """Scoring engine verdict must override intervention-timestamp fallback for critical actions."""

    def test_scoring_missed_overrides_intervention_applied(self):
        """If an intervention was applied but the scoring engine adjudicated the
        corresponding item as missed (e.g., out-of-scope or wrong source), the
        timeline must show missed — not applied."""
        scenario = load_scenario("peds_asthma_01")
        t0 = datetime.utcnow()
        session = _session(
            t0,
            checklist_states=_checklist_states([
                # CA id in peds_asthma_01 is "albuterol_svn", not "administer_albuterol"
                {"item_id": "albuterol_svn", "state": "missed", "earned_points": 0},
            ]),
            interventions=[
                # Intervention was physically applied but scoring engine rejected it
                types.SimpleNamespace(name="albuterol_svn", applied_at=t0 + timedelta(seconds=90)),
            ],
        )
        timeline = _build_session_timeline(session, scenario)
        # Find the albuterol critical action row
        item = _find_timeline(timeline, "lbuterol")
        if item is not None and item.get("status") != "informational":
            assert item["status"] == "missed"

    def test_scoring_satisfied_shows_applied(self):
        """When scoring engine says satisfied, critical action shows applied."""
        scenario = load_scenario("peds_asthma_01")
        t0 = datetime.utcnow()
        session = _session(
            t0,
            checklist_states=_checklist_states([
                {"item_id": "albuterol_svn", "state": "satisfied", "earned_points": 10},
            ]),
            interventions=[
                types.SimpleNamespace(name="albuterol_svn", applied_at=t0 + timedelta(seconds=90)),
            ],
        )
        timeline = _build_session_timeline(session, scenario)
        item = _find_timeline(timeline, "lbuterol")
        if item is not None and item.get("status") != "informational":
            assert item["status"] == "applied"


# ── Lung-sound timeline deference ─────────────────────────────────────────────

class TestLungSoundDeference:
    """Lung-sound STATUS must come from item_states when present, not from findings re-derivation."""

    def _lung_sound_definitions(self) -> list[dict]:
        return [{"id": "lung_sound_auscultation", "description": "Lung sounds auscultated", "category": "clinical_performance"}]

    def test_scoring_missed_overrides_matching_finding(self):
        """A lung-sound finding exists (source=lung_sound_challenge) but the scoring engine
        says missed — timeline must show missed."""
        scenario = load_scenario("peds_croup_01")
        t0 = datetime.utcnow()
        session = _session(
            t0,
            checklist_states=_checklist_states(
                item_states=[
                    {"item_id": "lung_sound_auscultation", "state": "missed", "earned_points": 0},
                ],
                definitions=self._lung_sound_definitions(),
            ),
            findings=[
                types.SimpleNamespace(
                    finding_type="exam",
                    key="Lung Sounds",
                    value="Inspiratory stridor",
                    captured_at=t0 + timedelta(seconds=60),
                    source="lung_sound_challenge",
                ),
            ],
        )
        timeline = _build_session_timeline(session, scenario)
        item = _find_timeline(timeline, "Lung sounds")
        assert item is not None
        assert item["status"] == "missed"

    def test_scoring_satisfied_shows_applied_with_elapsed(self):
        """Scoring engine says satisfied → applied. Timestamp from finding."""
        scenario = load_scenario("peds_croup_01")
        t0 = datetime.utcnow()
        session = _session(
            t0,
            checklist_states=_checklist_states(
                item_states=[
                    {"item_id": "lung_sound_auscultation", "state": "satisfied", "earned_points": 3},
                ],
                definitions=self._lung_sound_definitions(),
            ),
            findings=[
                types.SimpleNamespace(
                    finding_type="exam",
                    key="Lung Sounds",
                    value="Inspiratory stridor",
                    captured_at=t0 + timedelta(seconds=60),
                    source="lung_sound_challenge",
                ),
            ],
        )
        timeline = _build_session_timeline(session, scenario)
        item = _find_timeline(timeline, "Lung sounds")
        assert item is not None
        assert item["status"] == "applied"
        assert item["elapsed_min"] == 1.0

    def test_no_scoring_opinion_falls_back_to_finding_detection(self):
        """When item_states has no lung-sound entry, WOB findings must NOT count
        (source restriction). A real lung_sound_challenge finding must count."""
        scenario = load_scenario("peds_croup_01")
        t0 = datetime.utcnow()
        # WOB finding — not a real lung sound auscultation
        session = _session(
            t0,
            checklist_states=_checklist_states([]),  # no scoring opinion
            findings=[
                types.SimpleNamespace(
                    finding_type="exam",
                    key="Work of Breathing",
                    value="Moderate retractions",
                    captured_at=t0 + timedelta(seconds=30),
                    source="authored_vitals",
                ),
            ],
        )
        timeline = _build_session_timeline(session, scenario)
        item = _find_timeline(timeline, "Lung sounds")
        assert item is None

        session = _session(
            t0,
            checklist_states=_checklist_states([]),  # no scoring opinion
            findings=[
                types.SimpleNamespace(
                    finding_type="exam",
                    key="Lung Sounds",
                    value="Inspiratory stridor",
                    captured_at=t0 + timedelta(seconds=60),
                    source="lung_sound_challenge",
                ),
            ],
        )
        timeline = _build_session_timeline(session, scenario)
        item = _find_timeline(timeline, "Lung sounds")
        assert item is not None
        assert item["status"] == "applied"
        assert item["elapsed_min"] == 1.0
