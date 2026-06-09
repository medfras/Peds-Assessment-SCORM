from types import SimpleNamespace

from app.main import (
    PASSING_SCORE,
    _challenge_requirement_progress,
    _check_requirement_met,
    _empty_challenge_progress,
)


def test_specific_requirement_can_be_satisfied_by_passing_drills():
    req = {"type": "specific", "drill_ids": ["lung_sounds_matcher", "peds_gcs_calculator"]}

    assert _check_requirement_met(
        req,
        {},
        best_drill_scores={"lung_sounds_matcher": 80, "peds_gcs_calculator": 85},
    )
    assert not _check_requirement_met(
        req,
        {},
        best_drill_scores={"lung_sounds_matcher": 69, "peds_gcs_calculator": 85},
    )


def test_any_n_requirement_counts_scenarios_and_drills_together():
    req = {
        "type": "any_n",
        "count": 2,
        "scenario_ids": ["peds_diabetic_emergency_01"],
        "drill_ids": ["pat_dash", "dev_sort"],
    }

    assert _check_requirement_met(
        req,
        {"peds_diabetic_emergency_01": PASSING_SCORE},
        best_drill_scores={"pat": 70, "dev_sort": 0},
    )
    assert not _check_requirement_met(
        req,
        {"peds_diabetic_emergency_01": PASSING_SCORE - 1},
        best_drill_scores={"pat": 70, "dev_sort": 0},
    )


def test_repeatable_challenge_without_attempt_exposes_drill_requirements():
    challenge = SimpleNamespace(
        requirements=[
            {
                "type": "specific",
                "label": "Complete the CPR drills",
                "drill_ids": ["cpr_bls_concepts", "cpr_bls_sequence"],
            }
        ],
        scenario_ids=[],
        time_goal_minutes=60,
    )

    progress = _empty_challenge_progress(challenge)

    assert progress["scenarios_completed"] == 0
    assert progress["scenarios_total"] == 2
    assert progress["time_goal_met"] is False
    assert progress["requirements_progress"] == [
        {
            "type": "specific",
            "label": "Complete the CPR drills",
            "scenario_ids": [],
            "scenario_titles": {},
            "drill_ids": ["cpr_bls_concepts", "cpr_bls_sequence"],
            "completed_ids": [],
            "completed_drill_ids": [],
            "completed": 0,
            "needed": 2,
        }
    ]


def test_repeatable_challenge_without_attempt_counts_orientation_as_one_requirement():
    challenge = SimpleNamespace(
        requirements=[
            {"type": "orientation_complete", "label": "Complete Station 1 orientation"},
            {"type": "any_n", "count": 4, "drill_ids": ["pat_dash", "dev_sort"], "scenario_ids": []},
        ],
        scenario_ids=[],
        time_goal_minutes=None,
    )

    progress = _empty_challenge_progress(challenge)

    assert progress["scenarios_total"] == 5
    assert progress["requirements_progress"][0]["needed"] == 1
    assert progress["requirements_progress"][1]["needed"] == 4


def test_min_xp_requirement_uses_user_total_xp_and_reports_single_requirement():
    req = {"type": "min_xp", "min_xp": 1200, "label": "Earn at least 1200 XP"}
    user = SimpleNamespace(xp=1030)

    assert not _check_requirement_met(req, {}, user=user)
    progress = _challenge_requirement_progress(req, best_scores={}, user=user)
    assert progress["completed"] == 0
    assert progress["needed"] == 1
    assert progress["progress_text"] == "1,030 of 1,200 XP"
    assert progress["custom_items"][0] == {
        "label": "XP",
        "status": "1,030 of 1,200 XP earned",
        "complete": False,
    }

    user.xp = 1200
    assert _check_requirement_met(req, {}, user=user)
    progress = _challenge_requirement_progress(req, best_scores={}, user=user)
    assert progress["completed"] == 1
    assert progress["needed"] == 1
    assert progress["custom_items"][0]["complete"] is True


def test_empty_challenge_progress_exposes_min_xp_requirement_as_one_requirement():
    challenge = SimpleNamespace(
        requirements=[{"type": "min_xp", "min_xp": 1200, "label": "Earn at least 1200 XP"}],
        scenario_ids=[],
        time_goal_minutes=None,
    )

    progress = _empty_challenge_progress(challenge)

    assert progress["scenarios_total"] == 1
    assert progress["requirements_progress"][0]["needed"] == 1
    assert progress["requirements_progress"][0]["progress_text"] == "0 of 1,200 XP"
