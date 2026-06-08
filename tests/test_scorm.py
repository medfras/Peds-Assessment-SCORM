"""
Tests for SCORM attempt summary logic and node registry.

Covers the pure _compute_attempt_summary() function and the constants used for
unlock, grade, and lesson_status computation. No DB or HTTP fixtures needed —
these are unit tests of the scoring contract defined in 02_MAP_TOPOLOGY.md.

4-map topology:
  Map 0 — drill_pat (gate), drill_dev (gate), drill_gcs (optional)
  PM1   — scen_croup, scen_asthma, scen_diabetes, scen_seizure   (any 2 of 4)
  PT1   — scen_laceration, scen_head, scen_bleeding, scen_airway, scen_anaph (any 2 of 5)
  Map 3 — scen_cpr (required)
  Games — game_vitals, game_lung_sounds, game_bls (any 2 of 3)
"""

from __future__ import annotations

import re
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.auth import _extract_token
from app.routers.scorm import (
    _ALL_NODES,
    _CPR_NODES,
    _DRILL_NODES,
    _OPTIONAL_GAME_NODES,
    _PEDS_CE_MIN_OPT_GAMES,
    _PEDS_CE_MIN_PM1,
    _PEDS_CE_MIN_PT1,
    _PEDS_CE_MIN_XP,
    _PEDS_CE_TARGET_SECONDS,
    _PM1_NODES,
    _PT1_NODES,
    _REQUIRED_DRILLS,
    _SCENARIO_NODES,
    _compute_attempt_summary,
    _duplicate_launch_warning,
    _node_result_counts_complete,
    _parse_lms_student_name,
    _scorm_launch_owner,
    _sanitize_launch_id,
    ScormNodeResultRequest,
)


# ── Minimal ScormAttempt stub ─────────────────────────────────────────────────

def _attempt(node_scores=None, node_completed=None) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        attempt_id="test-attempt-001",
        node_scores=node_scores or {},
        node_completed=node_completed or {},
        status="incomplete",
        active_launch_id=None,
        active_launch_owner=None,
        active_launch_seen_at=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def _full_ce_context() -> dict:
    """Keyword args that satisfy all CE context requirements."""
    return dict(
        ce_seconds=_PEDS_CE_TARGET_SECONDS,
        orientation_done=True,
        user_xp=_PEDS_CE_MIN_XP,
    )


def _passing_attempt():
    """All 16 nodes completed at passing scores."""
    return _attempt(
        node_scores={n: 80 for n in _ALL_NODES},
        node_completed={n: True for n in _ALL_NODES},
    )


def _min_passing_attempt():
    """Minimum required nodes for SCORM pass: 2 PM1 + 2 PT1."""
    pm1   = sorted(_PM1_NODES)[:_PEDS_CE_MIN_PM1]
    pt1   = sorted(_PT1_NODES)[:_PEDS_CE_MIN_PT1]
    nodes = pm1 + pt1
    return _attempt(
        node_scores={n: 80 for n in nodes},
        node_completed={n: True for n in nodes},
    )


@pytest.mark.asyncio
async def test_shared_auth_extractor_accepts_scorm_bearer_token():
    request = types.SimpleNamespace(cookies={}, headers={"Authorization": "Bearer scorm.jwt.token"})
    assert await _extract_token(request) == "scorm.jwt.token"


def test_lms_student_name_parser_handles_moodle_display_formats():
    assert _parse_lms_student_name("Frastaci, Jonathan") == ("Jonathan", "Frastaci")
    assert _parse_lms_student_name("(Jon),") == ("Jon", None)
    assert _parse_lms_student_name("Jane Student") == ("Jane", "Student")
    assert _parse_lms_student_name("") == ("Student", None)


def test_node_completion_requires_on_track_score():
    assert _node_result_counts_complete(
        ScormNodeResultRequest(activity_type="scenario", score=69, completed=True, passed=True),
        69,
    ) is False


def test_duplicate_scorm_launch_warning_is_recent_and_advisory():
    now = datetime.utcnow()
    attempt = _attempt()
    attempt.active_launch_id = "launch-old"
    attempt.active_launch_owner = "student-1"
    attempt.active_launch_seen_at = now - timedelta(seconds=30)

    warning = _duplicate_launch_warning(attempt, "launch-new", now, "student-1")

    assert warning["code"] == "duplicate_scorm_launch"
    assert "already be open" in warning["message"]
    assert _duplicate_launch_warning(attempt, "launch-old", now, "student-1") is None
    assert _duplicate_launch_warning(attempt, "launch-new", now, "student-2") is None

    attempt.active_launch_seen_at = now - timedelta(minutes=10)
    assert _duplicate_launch_warning(attempt, "launch-new", now, "student-1") is None


def test_scorm_launch_owner_includes_id_and_display_name():
    assert _scorm_launch_owner("42", "Frastaci, Jonathan") == "42|FrastaciJonathan"
    assert _scorm_launch_owner("", "Different User") == "DifferentUser"
    assert len(_scorm_launch_owner("x" * 100, "y" * 100)) == 128


def test_scorm_launch_id_is_bounded_and_sanitized():
    assert _sanitize_launch_id("abc-DEF_123!!") == "abc-DEF_123"
    assert len(_sanitize_launch_id("x" * 100)) == 64
    assert _sanitize_launch_id("!!!") is None


def test_scorm_router_exposes_launch_close_endpoint_for_window_unload():
    src = Path(__file__).parent.parent.joinpath("app", "routers", "scorm.py").read_text()

    assert '"/api/scorm/attempts/{attempt_id}/launch-close"' in src
    assert "async def scorm_launch_close" in src
    assert "attempt.active_launch_id = None" in src
    assert "_SCORM_DUPLICATE_LAUNCH_WINDOW_SECONDS = 90" in src


def test_node_result_completion_requires_completed_and_passing_score():
    assert _node_result_counts_complete(
        ScormNodeResultRequest(activity_type="scenario", score=70, completed=True, passed=True),
        70,
    ) is True
    assert _node_result_counts_complete(
        ScormNodeResultRequest(activity_type="scenario", score=80, completed=True, passed=False),
        80,
    ) is False


def test_summary_completion_counts_require_on_track_score():
    pm1 = sorted(_PM1_NODES)[:2]
    pt1 = sorted(_PT1_NODES)[:2]
    nodes = pm1 + pt1
    scores = {n: 80 for n in nodes}
    scores[pm1[0]] = 69
    s = _compute_attempt_summary(_attempt(
        node_scores=scores,
        node_completed={n: True for n in nodes},
    ), **_full_ce_context())
    assert s["peds_ce_challenge"]["pm1_completed"] == 1
    assert s["peds_ce_challenge"]["pm1_done"] is False
    assert s["peds_ce_challenge"]["complete"] is False


# ── Node registry ─────────────────────────────────────────────────────────────

def test_node_registry_completeness():
    assert _REQUIRED_DRILLS <= _DRILL_NODES <= _ALL_NODES
    assert _PM1_NODES <= _SCENARIO_NODES <= _ALL_NODES
    assert _PT1_NODES <= _SCENARIO_NODES <= _ALL_NODES
    assert _CPR_NODES <= _SCENARIO_NODES <= _ALL_NODES
    assert _OPTIONAL_GAME_NODES <= _ALL_NODES
    assert _DRILL_NODES.isdisjoint(_SCENARIO_NODES)
    assert _DRILL_NODES.isdisjoint(_OPTIONAL_GAME_NODES)
    assert _SCENARIO_NODES.isdisjoint(_OPTIONAL_GAME_NODES)
    assert _PM1_NODES.isdisjoint(_PT1_NODES)
    assert _PM1_NODES.isdisjoint(_CPR_NODES)
    assert _PT1_NODES.isdisjoint(_CPR_NODES)
    # 3 drills + 4 PM1 + 5 PT1 + 1 CPR + 3 optional games = 16
    assert len(_ALL_NODES) == 16
    assert len(_DRILL_NODES) == 3
    assert len(_PM1_NODES) == 4
    assert len(_PT1_NODES) == 5
    assert len(_CPR_NODES) == 1
    assert len(_OPTIONAL_GAME_NODES) == 3
    assert len(_SCENARIO_NODES) == 10


def test_required_drills():
    assert "drill_pat" in _REQUIRED_DRILLS
    assert "drill_dev" in _REQUIRED_DRILLS
    assert "drill_gcs" not in _REQUIRED_DRILLS


def test_pm1_nodes_contents():
    for node in ("scen_croup", "scen_asthma", "scen_diabetes", "scen_seizure"):
        assert node in _PM1_NODES


def test_pt1_nodes_contents():
    for node in ("scen_laceration", "scen_head", "scen_bleeding", "scen_airway", "scen_anaph"):
        assert node in _PT1_NODES


def test_cpr_node():
    assert "scen_cpr" in _CPR_NODES


def test_optional_game_nodes():
    assert "game_vitals"      in _OPTIONAL_GAME_NODES
    assert "game_lung_sounds" in _OPTIONAL_GAME_NODES
    assert "game_bls"         in _OPTIONAL_GAME_NODES


# ── Unlock logic ──────────────────────────────────────────────────────────────

def test_no_drills_done_scenarios_and_map3_locked():
    s = _compute_attempt_summary(_attempt())
    assert s["unlocks"]["scenarios"] is False
    assert s["unlocks"]["map3"] is False


def test_only_pat_done_scenarios_still_locked():
    s = _compute_attempt_summary(_attempt(
        node_scores={"drill_pat": 90},
        node_completed={"drill_pat": True},
    ))
    assert s["unlocks"]["scenarios"] is False


def test_both_required_drills_done_scenarios_unlocked():
    s = _compute_attempt_summary(_attempt(
        node_scores={"drill_pat": 80, "drill_dev": 75},
        node_completed={"drill_pat": True, "drill_dev": True},
    ))
    assert s["unlocks"]["scenarios"] is True


def test_optional_gcs_drill_alone_does_not_unlock_scenarios():
    s = _compute_attempt_summary(_attempt(
        node_scores={"drill_gcs": 95},
        node_completed={"drill_gcs": True},
    ))
    assert s["unlocks"]["scenarios"] is False


def test_map3_locked_until_pm1_and_pt1_minimums_met():
    # Only 1 PM1 and 2 PT1 done — map3 still locked
    pm1_one = sorted(_PM1_NODES)[:1]
    pt1_two = sorted(_PT1_NODES)[:2]
    nodes = list(_REQUIRED_DRILLS) + pm1_one + pt1_two
    s = _compute_attempt_summary(_attempt(
        node_scores={n: 80 for n in nodes},
        node_completed={n: True for n in nodes},
    ))
    assert s["unlocks"]["map3"] is False


def test_map3_locked_when_pm1_met_but_pt1_not():
    pm1_two = sorted(_PM1_NODES)[:2]
    pt1_one = sorted(_PT1_NODES)[:1]
    nodes = list(_REQUIRED_DRILLS) + pm1_two + pt1_one
    s = _compute_attempt_summary(_attempt(
        node_scores={n: 80 for n in nodes},
        node_completed={n: True for n in nodes},
    ))
    assert s["unlocks"]["map3"] is False


def test_map3_unlocked_when_both_pm1_and_pt1_minimums_met():
    pm1_two = sorted(_PM1_NODES)[:2]
    pt1_two = sorted(_PT1_NODES)[:2]
    nodes = list(_REQUIRED_DRILLS) + pm1_two + pt1_two
    s = _compute_attempt_summary(_attempt(
        node_scores={n: 80 for n in nodes},
        node_completed={n: True for n in nodes},
    ))
    assert s["unlocks"]["map3"] is True


# ── Summary shape ─────────────────────────────────────────────────────────────

def test_summary_includes_all_nodes():
    s = _compute_attempt_summary(_attempt())
    assert set(s["node_scores"].keys()) == _ALL_NODES
    assert set(s["node_completed"].keys()) == _ALL_NODES


def test_missing_nodes_default_to_zero():
    s = _compute_attempt_summary(_attempt(
        node_scores={"drill_pat": 87},
        node_completed={"drill_pat": True},
    ))
    for node in _ALL_NODES - {"drill_pat"}:
        assert s["node_scores"][node] == 0


def test_summary_includes_node_maps():
    s = _compute_attempt_summary(_attempt())
    assert "scenario_node_map" in s
    assert "game_node_map" in s
    assert s["scenario_node_map"]["scen_diabetes"] == "peds_diabetic_emergency_01"
    assert s["scenario_node_map"]["scen_bleeding"] == "peds_trauma_03_extremity"
    assert s["scenario_node_map"]["scen_airway"] == "peds_trauma_02_partial_choking"
    assert s["game_node_map"]["drill_pat"] == "pat"


# ── Drill grade formula ───────────────────────────────────────────────────────

def test_drill_grade_zero_when_no_drills_complete():
    s = _compute_attempt_summary(_attempt())
    assert s["drill_grade"] == 0.0


def test_drill_grade_one_drill_half_weight():
    s = _compute_attempt_summary(_attempt(
        node_scores={"drill_pat": 80},
        node_completed={"drill_pat": True},
    ))
    assert s["drill_grade"] == 40.0


def test_drill_grade_best_two_of_two():
    s = _compute_attempt_summary(_attempt(
        node_scores={"drill_pat": 80, "drill_dev": 70},
        node_completed={"drill_pat": True, "drill_dev": True},
    ))
    assert s["drill_grade"] == 75.0


def test_drill_grade_best_two_of_three_picks_highest():
    # drill_gcs=95 highest, drill_pat=80 second — drill_dev=60 excluded
    s = _compute_attempt_summary(_attempt(
        node_scores={"drill_pat": 80, "drill_dev": 60, "drill_gcs": 95},
        node_completed={"drill_pat": True, "drill_dev": True, "drill_gcs": True},
    ))
    assert s["drill_grade"] == pytest.approx((95 + 80) / 2)


def test_drill_grade_optional_games_not_included():
    s_drills_only = _compute_attempt_summary(_attempt(
        node_scores={"drill_pat": 80, "drill_dev": 70},
        node_completed={"drill_pat": True, "drill_dev": True},
    ))
    s_with_games = _compute_attempt_summary(_attempt(
        node_scores={"drill_pat": 80, "drill_dev": 70,
                     "game_vitals": 100, "game_bls": 100},
        node_completed={"drill_pat": True, "drill_dev": True,
                        "game_vitals": True, "game_bls": True},
    ))
    assert s_drills_only["drill_grade"] == s_with_games["drill_grade"]


# ── Scenario average and final score ──────────────────────────────────────────

def test_scenario_avg_populated_without_cpr_once_pm1_pt1_minimum_met():
    pm1 = sorted(_PM1_NODES)[:2]
    pt1 = sorted(_PT1_NODES)[:2]
    nodes = pm1 + pt1
    s = _compute_attempt_summary(_attempt(
        node_scores={n: 90 for n in nodes},
        node_completed={n: True for n in nodes},
    ))
    assert s["scenario_avg"] == pytest.approx(90.0)
    assert s["final_score"] == 90


def test_scenario_avg_null_with_cpr_but_insufficient_pm1():
    pt1 = sorted(_PT1_NODES)[:2]
    pm1_one = sorted(_PM1_NODES)[:1]
    nodes = pm1_one + pt1 + ["scen_cpr"]
    s = _compute_attempt_summary(_attempt(
        node_scores={n: 90 for n in nodes},
        node_completed={n: True for n in nodes},
    ))
    assert s["scenario_avg"] is None


def test_scenario_avg_null_with_cpr_but_insufficient_pt1():
    pm1 = sorted(_PM1_NODES)[:2]
    pt1_one = sorted(_PT1_NODES)[:1]
    nodes = pm1 + pt1_one + ["scen_cpr"]
    s = _compute_attempt_summary(_attempt(
        node_scores={n: 90 for n in nodes},
        node_completed={n: True for n in nodes},
    ))
    assert s["scenario_avg"] is None


def test_scenario_avg_populated_once_minimum_met():
    pm1 = sorted(_PM1_NODES)[:2]
    pt1 = sorted(_PT1_NODES)[:2]
    nodes = pm1 + pt1
    s = _compute_attempt_summary(_attempt(
        node_scores={n: 80 for n in nodes},
        node_completed={n: True for n in nodes},
    ))
    assert s["scenario_avg"] == pytest.approx(80.0)
    assert s["final_score"] is not None


def test_final_score_uses_all_completed_scenarios():
    # All PM1 + all PT1: avg uses all 9, not just minimum 4. CPR is telemetry.
    nodes = list(_PM1_NODES) + list(_PT1_NODES)
    scenario_scores = {n: (90 if i < 5 else 70) for i, n in enumerate(nodes)}
    s = _compute_attempt_summary(_attempt(
        node_scores=scenario_scores,
        node_completed={n: True for n in nodes},
    ))
    expected_avg = (90 * 5 + 70 * 4) / 9
    assert s["scenario_avg"] == pytest.approx(expected_avg, abs=0.2)


def test_final_score_formula():
    drills = {"drill_pat": 80, "drill_dev": 70}
    pm1 = {n: 75 for n in sorted(_PM1_NODES)[:2]}
    pt1 = {n: 75 for n in sorted(_PT1_NODES)[:2]}
    s = _compute_attempt_summary(_attempt(
        node_scores={**drills, **pm1, **pt1},
        node_completed={**{k: True for k in drills}, **{k: True for k in pm1},
                        **{k: True for k in pt1}},
    ))
    scenario_avg = 75.0
    assert s["final_score"] == round(scenario_avg)


# ── lesson_status is tied to CE challenge ─────────────────────────────────────

def test_lesson_status_incomplete_by_default():
    s = _compute_attempt_summary(_attempt())
    assert s["lesson_status"] == "incomplete"


def test_lesson_status_passed_only_when_challenge_complete():
    s = _compute_attempt_summary(
        _min_passing_attempt(),
        **_full_ce_context(),
    )
    assert s["peds_ce_challenge"]["complete"] is True
    assert s["lesson_status"] == "passed"


def test_lesson_status_still_incomplete_when_challenge_not_met():
    s = _compute_attempt_summary(
        _passing_attempt(),
        ce_seconds=0,
        orientation_done=True,
        user_xp=0,
    )
    assert s["lesson_status"] == "incomplete"


# ── Peds CE challenge ─────────────────────────────────────────────────────────

def test_peds_ce_challenge_not_complete_by_default():
    s = _compute_attempt_summary(_attempt())
    assert s["peds_ce_challenge"]["complete"] is False


def test_peds_ce_challenge_exposes_orientation_without_requiring_it():
    s = _compute_attempt_summary(
        _min_passing_attempt(),
        ce_seconds=_PEDS_CE_TARGET_SECONDS,
        orientation_done=False,
        user_xp=_PEDS_CE_MIN_XP,
    )
    assert s["peds_ce_challenge"]["complete"] is True
    assert s["peds_ce_challenge"]["orientation_done"] is False


def test_peds_ce_challenge_exposes_required_drills_without_requiring_them():
    # GCS only — no PAT/DEV
    no_req_drills = _attempt(
        node_scores={**{n: 80 for n in _PM1_NODES},
                     **{n: 80 for n in _PT1_NODES},
                     **{n: 80 for n in _CPR_NODES},
                     **{n: 80 for n in _OPTIONAL_GAME_NODES},
                     "drill_gcs": 90},
        node_completed={**{n: True for n in _PM1_NODES},
                        **{n: True for n in _PT1_NODES},
                        **{n: True for n in _CPR_NODES},
                        **{n: True for n in _OPTIONAL_GAME_NODES},
                        "drill_gcs": True},
    )
    s = _compute_attempt_summary(no_req_drills, **_full_ce_context())
    assert s["peds_ce_challenge"]["drills_done"] is False
    assert s["peds_ce_challenge"]["complete"] is True


def test_peds_ce_challenge_requires_min_pm1():
    pm1_one = sorted(_PM1_NODES)[:1]
    pt1_two = sorted(_PT1_NODES)[:2]
    nodes = list(_REQUIRED_DRILLS) + pm1_one + pt1_two + list(_CPR_NODES) + list(_OPTIONAL_GAME_NODES)
    a = _attempt(
        node_scores={n: 80 for n in nodes},
        node_completed={n: True for n in nodes},
    )
    s = _compute_attempt_summary(a, **_full_ce_context())
    assert s["peds_ce_challenge"]["pm1_completed"] == 1
    assert s["peds_ce_challenge"]["pm1_done"] is False
    assert s["peds_ce_challenge"]["complete"] is False


def test_peds_ce_challenge_requires_min_pt1():
    pm1_two = sorted(_PM1_NODES)[:2]
    pt1_one = sorted(_PT1_NODES)[:1]
    nodes = list(_REQUIRED_DRILLS) + pm1_two + pt1_one + list(_CPR_NODES) + list(_OPTIONAL_GAME_NODES)
    a = _attempt(
        node_scores={n: 80 for n in nodes},
        node_completed={n: True for n in nodes},
    )
    s = _compute_attempt_summary(a, **_full_ce_context())
    assert s["peds_ce_challenge"]["pt1_completed"] == 1
    assert s["peds_ce_challenge"]["pt1_done"] is False
    assert s["peds_ce_challenge"]["complete"] is False


def test_peds_ce_challenge_exposes_cpr_without_requiring_it():
    pm1_two = sorted(_PM1_NODES)[:2]
    pt1_two = sorted(_PT1_NODES)[:2]
    nodes = pm1_two + pt1_two
    a = _attempt(
        node_scores={n: 80 for n in nodes},
        node_completed={n: True for n in nodes},
    )
    s = _compute_attempt_summary(a, **_full_ce_context())
    assert s["peds_ce_challenge"]["cpr_done"] is False
    assert s["peds_ce_challenge"]["cpr_required"] is False
    assert s["peds_ce_challenge"]["complete"] is True


def test_peds_ce_challenge_any_two_pm1_qualify():
    # Use the last 2 PM1 scenarios — not the first 2
    pm1_last = sorted(_PM1_NODES)[-2:]
    pt1_two  = sorted(_PT1_NODES)[:2]
    nodes = list(_REQUIRED_DRILLS) + pm1_last + pt1_two + list(_CPR_NODES) + list(_OPTIONAL_GAME_NODES)
    a = _attempt(
        node_scores={n: 80 for n in nodes},
        node_completed={n: True for n in nodes},
    )
    s = _compute_attempt_summary(a, **_full_ce_context())
    assert s["peds_ce_challenge"]["pm1_done"] is True


def test_peds_ce_challenge_any_two_pt1_qualify():
    pm1_two  = sorted(_PM1_NODES)[:2]
    pt1_last = sorted(_PT1_NODES)[-2:]
    nodes = list(_REQUIRED_DRILLS) + pm1_two + pt1_last + list(_CPR_NODES) + list(_OPTIONAL_GAME_NODES)
    a = _attempt(
        node_scores={n: 80 for n in nodes},
        node_completed={n: True for n in nodes},
    )
    s = _compute_attempt_summary(a, **_full_ce_context())
    assert s["peds_ce_challenge"]["pt1_done"] is True


def test_peds_ce_challenge_exposes_optional_games_without_requiring_them():
    pm1_two = sorted(_PM1_NODES)[:2]
    pt1_two = sorted(_PT1_NODES)[:2]
    one_game = sorted(_OPTIONAL_GAME_NODES)[:1]
    nodes = pm1_two + pt1_two + one_game
    a = _attempt(
        node_scores={n: 80 for n in nodes},
        node_completed={n: True for n in nodes},
    )
    s = _compute_attempt_summary(a, **_full_ce_context())
    assert s["peds_ce_challenge"]["optional_games_completed"] == 1
    assert s["peds_ce_challenge"]["optional_games_done"] is False
    assert s["peds_ce_challenge"]["optional_games_required_for_pass"] is False
    assert s["peds_ce_challenge"]["complete"] is True


def test_peds_ce_challenge_requires_ce_time():
    s = _compute_attempt_summary(
        _min_passing_attempt(),
        ce_seconds=_PEDS_CE_TARGET_SECONDS - 1,
        orientation_done=True,
        user_xp=0,
    )
    assert s["peds_ce_challenge"]["complete"] is False


def test_peds_ce_challenge_requires_min_xp():
    s = _compute_attempt_summary(
        _min_passing_attempt(),
        ce_seconds=_PEDS_CE_TARGET_SECONDS,
        orientation_done=True,
        user_xp=_PEDS_CE_MIN_XP - 1,
    )
    assert s["peds_ce_challenge"]["xp_required"] == _PEDS_CE_MIN_XP
    assert s["peds_ce_challenge"]["xp_ok"] is False
    assert s["peds_ce_challenge"]["complete"] is False


def test_peds_ce_challenge_xp_comes_from_user_xp_total():
    source = Path("app/routers/scorm.py").read_text()

    assert "user_xp = int((user.xp or 0)) if user else 0" in source
    assert "peds_ce_challenge" in source
    assert '"xp":                         user_xp' in source


def test_peds_ce_challenge_complete_when_all_criteria_met():
    s = _compute_attempt_summary(
        _min_passing_attempt(),
        **_full_ce_context(),
    )
    c = s["peds_ce_challenge"]
    assert c["id"] == "pfd_station1_scorm_pass"
    assert c["title"] == "Pediatric Patient Assessment"
    assert c["complete"] is True
    assert c["pm1_done"] is True
    assert c["pt1_done"] is True
    assert c["ce_target_minutes"] == 60.0
    assert c["training_time_done"] is True
    assert c["xp_ok"] is True


def test_peds_ce_challenge_extra_nodes_still_complete():
    # All 16 nodes completed — still passes
    s = _compute_attempt_summary(
        _passing_attempt(),
        **_full_ce_context(),
    )
    assert s["peds_ce_challenge"]["complete"] is True


def test_peds_ce_challenge_counts_exposed():
    pm1_two = sorted(_PM1_NODES)[:2]
    pt1_three = sorted(_PT1_NODES)[:3]
    nodes = pm1_two + pt1_three + ["scen_cpr"]
    a = _attempt(
        node_scores={n: 80 for n in nodes},
        node_completed={n: True for n in nodes},
    )
    s = _compute_attempt_summary(a)
    c = s["peds_ce_challenge"]
    assert c["pm1_completed"] == 2
    assert c["pm1_required"] == _PEDS_CE_MIN_PM1
    assert c["pt1_completed"] == 3
    assert c["pt1_required"] == _PEDS_CE_MIN_PT1
    assert c["optional_games_required"] == _PEDS_CE_MIN_OPT_GAMES


# ── scorm.js finish() contract ────────────────────────────────────────────────
# Static assertions against the JS source. These prevent the finish() function
# from drifting back to writing "failed" for in-progress learners — a bug that
# looks fine locally but gets reported to the LMS grade book as a hard failure.
#
# Contract (fixed 2026-05-17, documented in docs/CE_CERTIFICATION_DESIGN.md §6):
#   1. Pass condition gates on peds_ce_challenge.complete, not final_score.
#   2. Fallback lesson_status is "incomplete", never "failed".

_SCORM_JS = Path(__file__).parent.parent / "static" / "js" / "scorm.js"


def _finish_body() -> str:
    src = _SCORM_JS.read_text()
    idx = src.find("function finish(")
    assert idx != -1, "finish() function not found in scorm.js"
    # LMSFinish is always the last call in finish() — slice up to and including it
    end = src.find("LMSFinish", idx)
    assert end != -1, "LMSFinish call not found after finish() definition"
    return src[idx:end + len("LMSFinish")]


def test_scorm_js_finish_gates_on_ce_challenge():
    assert "peds_ce_challenge" in _finish_body(), (
        "finish() must gate on peds_ce_challenge.complete, not final_score"
    )


def test_scorm_js_finish_writes_incomplete_not_failed():
    body = _finish_body()
    assert '"incomplete"' in body, (
        'finish() must write "incomplete" for in-progress learners'
    )
    assert '"failed"' not in body, (
        'finish() must not write "failed" — use "incomplete" for in-progress learners'
    )


def test_scorm_js_writes_lesson_status_when_summary_is_persisted():
    src = _SCORM_JS.read_text()
    start = src.index("function _writeSuspendData(summary)")
    end = src.index("function _writeUiState", start)
    body = src[start:end]

    assert "peds_ce_challenge" in body
    assert 'LMSSetValue("cmi.core.lesson_status", ceComplete ? "passed" : "incomplete")' in body
    assert 'LMSSetValue("cmi.core.score.raw", String(summary.final_score))' in body
    assert 'LMSSetValue("cmi.core.score.min", "0")' in body
    assert 'LMSSetValue("cmi.core.score.max", "100")' in body
    assert "LMSCommit" in body


# ── app.js completion event contract ─────────────────────────────────────────
# Static assertions against app.js. The SCORM adapter (scorm_adapter.js, built
# in the SCORM branch) listens for these events. If the event name or shape
# changes here, the adapter silently stops working — these tests catch that.
#
# Contract:
#   rt:scenarioComplete — fired in processDebrief() after score is set.
#     detail: { scenarioId, sessionId, score, passed, isDrill }
#   rt:drillComplete — fired in _mgSubmitResult() on successful server submit.
#     detail: { gameId, score, passed, mistakeTags }
#
# app.js must not reference RescueTrails.scorm directly (no SCORM coupling).

_APP_JS = Path(__file__).parent.parent / "static" / "js" / "app.js"
_INDEX_HTML = Path(__file__).parent.parent / "static" / "index.html"


def test_app_js_dispatches_scenario_complete_event():
    src = _APP_JS.read_text()
    assert '"rt:scenarioComplete"' in src, (
        "app.js must dispatch rt:scenarioComplete in processDebrief()"
    )


def test_app_js_dispatches_drill_complete_event():
    src = _APP_JS.read_text()
    assert '"rt:drillComplete"' in src, (
        "app.js must dispatch rt:drillComplete in _mgSubmitResult()"
    )


def test_app_js_scenario_event_has_required_fields():
    src = _APP_JS.read_text()
    idx = src.find('"rt:scenarioComplete"')
    assert idx != -1
    block = src[idx:idx + 300]
    for field in ("scenarioId", "sessionId", "score", "passed", "isDrill"):
        assert field in block, f"rt:scenarioComplete detail missing field: {field}"


def test_app_js_drill_event_has_required_fields():
    src = _APP_JS.read_text()
    idx = src.find('"rt:drillComplete"')
    assert idx != -1
    block = src[idx:idx + 300]
    for field in ("gameId", "score", "passed", "mistakeTags"):
        assert field in block, f"rt:drillComplete detail missing field: {field}"


def test_app_js_refreshes_challenge_display_after_scorm_node_submit():
    src = _APP_JS.read_text()
    idx = src.find("async function _onScormNodeComplete")
    assert idx != -1
    block = src[idx:idx + 900]

    assert "_applyScormResumeState(summary);" in block
    assert "_refreshScormChallengeDisplays();" in block
    assert block.index("_applyScormResumeState(summary);") < block.index("_refreshScormChallengeDisplays();")


def test_app_js_refreshes_scorm_summary_after_lexi_xp_award():
    src = _APP_JS.read_text()
    idx = src.find("async function _lexiShowOutro")
    assert idx != -1
    block = src[idx:idx + 5200]

    assert "await _loadProgressFromServer().catch(() => {});" in block
    assert "await _refreshScormSummary().catch(() => {});" in block
    assert block.index("await _loadProgressFromServer().catch(() => {});") < block.index("await _refreshScormSummary().catch(() => {});")


def test_app_js_refreshes_xp_chrome_after_drill_xp_awards():
    src = _APP_JS.read_text()
    idx = src.find("async function _mgSubmitResult")
    assert idx != -1
    block = src[idx:idx + 2600]

    assert "await _loadProgressFromServer().catch(() => {});" in block
    assert "_refreshGamificationChrome();" in block
    assert "await _refreshScormSummary().catch(() => {});" in block
    assert block.index("await _loadProgressFromServer().catch(() => {});") < block.index("_refreshGamificationChrome();")
    assert block.index("_refreshGamificationChrome();") < block.index("await _refreshScormSummary().catch(() => {});")


def test_drill_results_do_not_include_scenario_offramps():
    html = _INDEX_HTML.read_text()
    src = _APP_JS.read_text()

    assert "Try a Scenario" not in html
    assert "try-scenario" not in html
    assert "try-scenario" not in src
    assert "function _syncMgScenarioBridgeAvailability" not in src
    assert "_currentPedsMapHasPlayableScenario" not in src


def test_app_js_does_not_reference_scorm_directly():
    src = _APP_JS.read_text()
    assert "RescueTrails.scorm" not in src, (
        "app.js must not reference RescueTrails.scorm — SCORM coupling belongs in scorm_adapter.js"
    )
