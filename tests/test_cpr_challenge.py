import pytest
from datetime import datetime
from pathlib import Path

from app.cpr_challenge import CPRChallengeError, CPRScoreContext, score_cpr_challenge
from app.scenario_engine import get_public_scenario_data, load_scenario
from app.vitals_engine import calculate_vitals


def _config(**criteria_overrides):
    criteria = {
        "eligible_after_cycles": 3,
        "max_cycles_before_rosc": 3,
        "hard_stop_cycle": 3,
        "min_ccf": 0.80,
        "min_ccf_window": "consecutive_eligible_cycles",
        "aha_compliance_gates": [
            "ccf",
            "rhythm_decisions",
            "post_decision_resume",
            "ventilation_ratio",
            "no_critical_failure",
        ],
    }
    criteria.update(criteria_overrides)
    return {
        "enabled": True,
        "challenge_id": "peds_arrest_01_cpr",
        "arrest_type": "pediatric",
        "algorithm": "pediatric_bls",
        "team_model": "ems_team",
        "initial_rhythm": "pulseless_vt",
        "rhythm_sequence": ["pulseless_vt", "vf", "pea"],
        "cycle_seconds": 120,
        "rosc_criteria": criteria,
        "allow_aed": True,
        "allow_manual_defib": False,
        "allow_precharge": False,
        "allow_medications": False,
        "rubric_integration": {
            "dimension": "clinical_performance",
            "item_id": "cpr_challenge_management",
            "weight_points": 20,
        },
    }


def _successful_timeline():
    return [
        {"t_ms": 0, "type": "challenge_started"},
        {"t_ms": 0, "type": "aed_applied"},
        {"t_ms": 4000, "type": "cpr_started", "data": {"mode": "15:2"}},
        {"t_ms": 124000, "type": "compressions_paused", "reason": "rhythm_check"},
        {"t_ms": 124000, "type": "rhythm_check_started"},
        {"t_ms": 127000, "type": "rhythm_identified", "rhythm": "pulseless_vt"},
        {"t_ms": 128000, "type": "shock_delivered"},
        {"t_ms": 131000, "type": "compressions_resumed", "reason": "post_shock"},
        {"t_ms": 251000, "type": "compressions_paused", "reason": "rhythm_check"},
        {"t_ms": 251000, "type": "rhythm_check_started"},
        {"t_ms": 254000, "type": "rhythm_identified", "rhythm": "vf"},
        {"t_ms": 255000, "type": "shock_delivered"},
        {"t_ms": 258000, "type": "compressions_resumed", "reason": "post_shock"},
        {"t_ms": 378000, "type": "compressions_paused", "reason": "rhythm_check"},
        {"t_ms": 378000, "type": "rhythm_check_started"},
        {"t_ms": 381000, "type": "rhythm_identified", "rhythm": "pea"},
        {"t_ms": 382000, "type": "no_shock_selected"},
        {"t_ms": 385000, "type": "compressions_resumed", "reason": "post_no_shock"},
        {"t_ms": 385000, "type": "challenge_ended", "outcome": "rosc"},
    ]


def _successful_timeline_with_valid_pulse_checks():
    return [
        {"t_ms": 0, "type": "challenge_started"},
        {"t_ms": 0, "type": "aed_applied"},
        {"t_ms": 4000, "type": "cpr_started", "data": {"mode": "15:2"}},
        {"t_ms": 124000, "type": "compressions_paused", "reason": "rhythm_check"},
        {"t_ms": 124000, "type": "rhythm_check_started"},
        {"t_ms": 124500, "type": "pulse_check_started", "data": {"cycle": 1, "phase": "rhythm_check"}},
        {
            "t_ms": 130500,
            "type": "pulse_check_completed",
            "data": {"cycle": 1, "phase": "rhythm_check", "duration_ms": 6000, "result": "no_pulse", "status": "valid", "valid": True},
        },
        {"t_ms": 131000, "type": "rhythm_identified", "rhythm": "pulseless_vt"},
        {"t_ms": 132000, "type": "shock_delivered"},
        {"t_ms": 135000, "type": "compressions_resumed", "reason": "post_shock"},
        {"t_ms": 255000, "type": "compressions_paused", "reason": "rhythm_check"},
        {"t_ms": 255000, "type": "rhythm_check_started"},
        {"t_ms": 255500, "type": "pulse_check_started", "data": {"cycle": 2, "phase": "rhythm_check"}},
        {
            "t_ms": 261500,
            "type": "pulse_check_completed",
            "data": {"cycle": 2, "phase": "rhythm_check", "duration_ms": 6000, "result": "no_pulse", "status": "valid", "valid": True},
        },
        {"t_ms": 262000, "type": "rhythm_identified", "rhythm": "vf"},
        {"t_ms": 263000, "type": "shock_delivered"},
        {"t_ms": 266000, "type": "compressions_resumed", "reason": "post_shock"},
        {"t_ms": 386000, "type": "compressions_paused", "reason": "rhythm_check"},
        {"t_ms": 386000, "type": "rhythm_check_started"},
        {"t_ms": 386500, "type": "pulse_check_started", "data": {"cycle": 3, "phase": "rhythm_check"}},
        {
            "t_ms": 392500,
            "type": "pulse_check_completed",
            "data": {"cycle": 3, "phase": "rhythm_check", "duration_ms": 6000, "result": "pulse_present", "status": "valid", "valid": True},
        },
        {"t_ms": 393000, "type": "rhythm_identified", "rhythm": "pea"},
        {"t_ms": 394000, "type": "no_shock_selected"},
        {"t_ms": 395000, "type": "rosc", "data": {"cycle": 3, "source": "pulse_check"}},
        {"t_ms": 396000, "type": "challenge_ended", "outcome": "rosc"},
    ]


def _terminated_timeline_without_rosc():
    timeline = [
        dict(ev, data=dict(ev["data"]) if isinstance(ev.get("data"), dict) else ev.get("data"))
        for ev in _successful_timeline_with_valid_pulse_checks()
        if ev["type"] != "rosc"
    ]
    # Make the first shockable decision incorrect so performance-gated ROSC is
    # not achieved; the terminal outcome then depends on termination validity.
    for ev in timeline:
        if ev["type"] == "shock_delivered":
            ev["type"] = "no_shock_selected"
            break
    for ev in timeline:
        if ev["type"] == "compressions_resumed" and ev.get("reason") == "post_shock":
            ev["reason"] = "post_no_shock"
            break
    for ev in timeline:
        if ev["type"] == "pulse_check_completed" and ev.get("data", {}).get("cycle") == 3:
            ev["data"]["result"] = "no_pulse"
    timeline[-1] = {"t_ms": 396000, "type": "challenge_ended", "outcome": "terminated"}
    timeline.insert(-1, {"t_ms": 395000, "type": "termination_of_resuscitation"})
    return timeline


def _refractory_vf_timeline():
    timeline = _successful_timeline()
    timeline[15] = {"t_ms": 381000, "type": "rhythm_identified", "rhythm": "vf"}
    timeline[16] = {"t_ms": 382000, "type": "shock_delivered"}
    timeline[17] = {"t_ms": 385000, "type": "compressions_resumed", "reason": "post_shock"}
    return timeline


def test_successful_bls_aed_timeline_achieves_rosc_after_three_cycles():
    result = score_cpr_challenge(_config(), _successful_timeline())

    assert result["outcome"] == "rosc"
    assert result["score"] >= 90
    assert result["rosc"]["triggered_after_cycle"] == 3
    assert result["rosc"]["triggered_at_boundary"] == 4
    assert result["gate_results"]["ccf"]["passed"] is True
    assert result["gate_results"]["ventilation_ratio"]["passed"] is True
    assert result["score_buckets"]["ventilation_ratio"]["earned"] == 5
    assert result["metrics"]["ventilation_modes"][0]["selected"] == "15:2"
    assert len(result["metrics"]["ccf_by_cycle"]) == 3
    assert len(result["metrics"]["rhythm_decisions"]) == 3
    assert len(result["metrics"]["cycle_discipline"]) == 3
    analytics = result["metrics"]["analytics"]
    assert analytics["ccf_trend"]["direction"] == "flat"
    assert len(analytics["cycle_review"]) == 3
    assert analytics["cycle_review"][0]["rhythm_decision"]["rhythm"] == "pulseless_vt"
    assert analytics["error_tags"] == []
    assert analytics["remediation_targets"] == []


def test_ventilation_mode_events_do_not_add_points_when_bucket_not_applicable():
    config = _config(aha_compliance_gates=["ccf", "rhythm_decisions", "post_decision_resume", "no_critical_failure"])
    config["score_ventilation_ratio"] = False
    timeline = _successful_timeline()
    timeline.insert(3, {"t_ms": 5000, "type": "ventilation_mode_changed", "data": {"mode": "15:2"}})

    result = score_cpr_challenge(config, timeline)

    assert result["score"] <= 100
    assert result["score_buckets"]["ventilation_ratio"] == {
        "earned": None,
        "possible": 0,
        "not_applicable": True,
    }


def test_bls_stray_medication_event_does_not_add_medication_points():
    timeline = _successful_timeline()
    timeline.insert(12, {"t_ms": 256000, "type": "medication_given", "medication_id": "epinephrine_cardiac"})

    result = score_cpr_challenge(_config(), timeline)

    assert result["score"] <= 100
    assert result["score_buckets"]["medication_timing"] == {
        "earned": None,
        "possible": 0,
        "not_applicable": True,
    }
    assert result["metrics"]["medication_timing"]["events"][0]["medication_id"] == "epinephrine_cardiac"


def test_bls_stray_precharge_event_is_visible_but_not_applicable():
    timeline = sorted(
        _successful_timeline() + [{"t_ms": 123000, "type": "precharge_started", "device": "manual_defib"}],
        key=lambda ev: ev["t_ms"],
    )

    result = score_cpr_challenge(_config(), timeline)
    defib = result["metrics"]["defib_management"]

    assert result["score"] <= 100
    assert defib["applicable"] is False
    assert defib["status"] == "not_applicable"
    assert defib["precharge_events"][0]["event_type"] == "precharge_started"
    assert defib["precharge_expectations"] == []


def test_als_epinephrine_after_second_shock_gets_medication_timing_credit():
    config = _config(aha_compliance_gates=["ccf", "rhythm_decisions", "post_decision_resume", "no_critical_failure"])
    config["allow_medications"] = True
    config["score_medication_timing"] = True
    timeline = _successful_timeline()
    timeline.insert(12, {"t_ms": 256000, "type": "medication_given", "medication_id": "epinephrine_cardiac"})

    result = score_cpr_challenge(config, timeline)
    medication = result["metrics"]["medication_timing"]

    assert result["score_buckets"]["medication_timing"] == {
        "earned": 5,
        "possible": 5,
        "not_applicable": False,
    }
    assert medication["expectations"][0]["id"] == "epinephrine_after_second_shock"
    assert medication["expectations"][0]["status"] == "on_time"
    assert medication["expectations"][0]["weight"] == 1.0


def test_als_missing_epinephrine_scores_zero_when_medication_timing_enabled():
    config = _config(aha_compliance_gates=["ccf", "rhythm_decisions", "post_decision_resume", "no_critical_failure"])
    config["allow_medications"] = True
    config["score_medication_timing"] = True

    result = score_cpr_challenge(config, _successful_timeline())

    assert result["score_buckets"]["medication_timing"] == {
        "earned": 0,
        "possible": 5,
        "not_applicable": False,
    }
    assert result["metrics"]["medication_timing"]["expectations"][0]["status"] == "missing"


def test_als_antiarrhythmic_after_third_shock_gets_medication_timing_credit():
    config = _config(
        aha_compliance_gates=["ccf", "rhythm_decisions", "post_decision_resume", "no_critical_failure"]
    )
    config["rhythm_sequence"] = ["vf", "vf", "vf"]
    config["allow_medications"] = True
    config["score_medication_timing"] = True
    config["score_epinephrine_timing"] = False
    config["score_antiarrhythmic_timing"] = True
    timeline = sorted(
        _refractory_vf_timeline()
        + [{"t_ms": 383000, "type": "medication_given", "medication_id": "amiodarone"}],
        key=lambda ev: ev["t_ms"],
    )

    result = score_cpr_challenge(config, timeline)
    medication = result["metrics"]["medication_timing"]

    assert result["score_buckets"]["medication_timing"] == {
        "earned": 5,
        "possible": 5,
        "not_applicable": False,
    }
    assert medication["expectations"][0]["id"] == "antiarrhythmic_after_third_shock"
    assert medication["expectations"][0]["status"] == "on_time"
    assert medication["expectations"][0]["weight"] == 1.0


def test_missing_antiarrhythmic_scores_zero_when_enabled():
    config = _config(
        aha_compliance_gates=["ccf", "rhythm_decisions", "post_decision_resume", "no_critical_failure"]
    )
    config["rhythm_sequence"] = ["vf", "vf", "vf"]
    config["allow_medications"] = True
    config["score_medication_timing"] = True
    config["score_epinephrine_timing"] = False
    config["score_antiarrhythmic_timing"] = True

    result = score_cpr_challenge(config, _refractory_vf_timeline())
    medication = result["metrics"]["medication_timing"]

    assert result["score_buckets"]["medication_timing"] == {
        "earned": 0,
        "possible": 5,
        "not_applicable": False,
    }
    assert medication["expectations"][0]["id"] == "antiarrhythmic_after_third_shock"
    assert medication["expectations"][0]["status"] == "missing"


def test_wrong_shock_for_pea_does_not_create_antiarrhythmic_expectation():
    config = _config(
        aha_compliance_gates=["ccf", "post_decision_resume", "no_critical_failure"]
    )
    config["allow_medications"] = True
    config["score_medication_timing"] = True
    config["score_epinephrine_timing"] = False
    config["score_antiarrhythmic_timing"] = True
    timeline = _successful_timeline()
    timeline[16] = {"t_ms": 382000, "type": "shock_delivered"}
    timeline[17] = {"t_ms": 385000, "type": "compressions_resumed", "reason": "post_shock"}

    result = score_cpr_challenge(config, timeline)

    assert result["metrics"]["rhythm_decisions"][2]["rhythm"] == "pea"
    assert result["metrics"]["rhythm_decisions"][2]["decision"] == "shock"
    assert result["metrics"]["medication_timing"]["expectations"] == []


def test_phase4_analytics_tags_common_cpr_errors_and_remediation_targets():
    timeline = _successful_timeline()
    timeline[6] = {"t_ms": 170000, "type": "shock_delivered"}
    timeline[7] = {"t_ms": 190000, "type": "compressions_resumed", "reason": "post_shock"}
    timeline[12] = {"t_ms": 330000, "type": "compressions_resumed", "reason": "post_shock"}
    timeline[16] = {"t_ms": 382000, "type": "shock_delivered"}
    timeline[17] = {"t_ms": 385000, "type": "compressions_resumed", "reason": "post_shock"}

    result = score_cpr_challenge(_config(), timeline)
    analytics = result["metrics"]["analytics"]

    assert analytics["pause_graph"][0]["severity"] == "severe"
    assert "ccf_below_target" in analytics["error_tags"]
    assert "severe_pause" in analytics["error_tags"]
    assert "delayed_resume" in analytics["error_tags"]
    assert "inappropriate_shock_pea" in analytics["error_tags"]
    assert "pause_minimization" in analytics["remediation_targets"]
    assert "nonshockable_rhythm_management" in analytics["remediation_targets"]


def test_manual_defib_precharge_metrics_track_on_time_precharge_when_enabled():
    config = _config()
    config["allow_aed"] = False
    config["allow_manual_defib"] = True
    config["allow_precharge"] = True
    config["score_precharge"] = True
    timeline = sorted(
        _successful_timeline()
        + [
            {"t_ms": 123000, "type": "precharge_started", "device": "manual_defib"},
            {"t_ms": 250000, "type": "precharge_started", "device": "manual_defib"},
        ],
        key=lambda ev: ev["t_ms"],
    )

    result = score_cpr_challenge(config, timeline)
    defib = result["metrics"]["defib_management"]

    assert defib["applicable"] is True
    assert defib["manual_defib_applicable"] is True
    assert defib["precharge_applicable"] is True
    assert [row["status"] for row in defib["precharge_expectations"]] == ["on_time", "on_time"]
    assert all(row["weight"] == 1.0 for row in defib["precharge_expectations"])


def test_missing_precharge_is_debrief_metric_without_score_bucket_side_effect():
    config = _config()
    config["allow_aed"] = False
    config["allow_manual_defib"] = True
    config["allow_precharge"] = True
    config["score_precharge"] = True

    result = score_cpr_challenge(config, _successful_timeline())
    defib = result["metrics"]["defib_management"]

    assert result["outcome"] == "rosc"
    assert "precharge" not in result["score_buckets"]
    assert [row["status"] for row in defib["precharge_expectations"]] == ["missing", "missing"]
    assert all(row["weight"] == 0.0 for row in defib["precharge_expectations"])


def test_advanced_airway_changes_expected_ventilation_mode_to_continuous_when_enabled():
    config = _config()
    config["allow_advanced_airway"] = True
    config["score_advanced_airway_mode"] = True
    timeline = _successful_timeline()
    timeline.insert(8, {"t_ms": 140000, "type": "advanced_airway_placed", "action_id": "supraglottic_airway_insert"})
    timeline.insert(9, {"t_ms": 141000, "type": "ventilation_mode_changed", "data": {"mode": "Continuous"}})

    result = score_cpr_challenge(config, timeline)
    ventilation = result["metrics"]["ventilation_modes"]

    assert result["outcome"] == "rosc"
    assert ventilation[0]["expected"] == "15:2"
    assert ventilation[1]["expected"] == "Continuous"
    assert ventilation[1]["airway_state"] == "advanced_airway"
    assert result["score_buckets"]["ventilation_ratio"]["earned"] == 5


def test_advanced_airway_without_continuous_mode_change_fails_ventilation_bucket_when_enabled():
    config = _config()
    config["allow_advanced_airway"] = True
    config["score_advanced_airway_mode"] = True
    timeline = _successful_timeline()
    timeline.insert(8, {"t_ms": 140000, "type": "advanced_airway_placed", "action_id": "supraglottic_airway_insert"})

    result = score_cpr_challenge(config, timeline)
    ventilation = result["metrics"]["ventilation_modes"]

    assert result["outcome"] == "criteria_not_met"
    assert ventilation[-1]["event_type"] == "missing_ventilation_mode_change"
    assert ventilation[-1]["expected"] == "Continuous"
    assert ventilation[-1]["weight"] == 0.0
    assert result["score_buckets"]["ventilation_ratio"]["earned"] < 5


def test_bls_supraglottic_menu_action_does_not_change_expected_mode_without_advanced_airway_scoring():
    timeline = _successful_timeline()
    timeline.insert(
        8,
        {
            "t_ms": 140000,
            "type": "additional_action_selected",
            "data": {
                "section_id": "actions",
                "menu_action_id": "place_supraglottic_airway",
                "action_id": "supraglottic_airway_insert",
                "label": "Place Supraglottic Airway",
            },
        },
    )

    result = score_cpr_challenge(_config(), timeline)

    assert result["outcome"] == "rosc"
    assert result["metrics"]["ventilation_modes"][0]["expected"] == "15:2"
    assert result["score_buckets"]["ventilation_ratio"]["earned"] == 5


def test_successful_terminal_no_shock_can_end_with_pulse_check_rosc_without_restarting_cpr():
    timeline = [
        ev for ev in _successful_timeline()
        if not (ev["type"] == "compressions_resumed" and ev.get("reason") == "post_no_shock")
    ]
    timeline[-1:] = [
        {"t_ms": 383000, "type": "pulse_check_started", "data": {"cycle": 3, "phase": "rhythm_check"}},
        {
            "t_ms": 389000,
            "type": "pulse_check_completed",
            "data": {
                "cycle": 3,
                "phase": "rhythm_check",
                "duration_ms": 6000,
                "result": "pulse_present",
                "status": "valid",
                "valid": True,
            },
        },
        {"t_ms": 389500, "type": "rosc", "data": {"cycle": 3, "source": "pulse_check"}},
        {"t_ms": 390000, "type": "challenge_ended", "outcome": "rosc"},
    ]

    result = score_cpr_challenge(_config(), timeline)

    assert result["outcome"] == "rosc"
    assert result["rosc"]["triggered_after_cycle"] == 3
    assert len(result["metrics"]["ccf_by_cycle"]) == 3
    assert result["metrics"]["pulse_checks"]["checks"][0]["result"] == "pulse_present"


def test_additional_action_events_are_preserved_for_debrief_timeline():
    timeline = _successful_timeline()
    timeline.insert(
        3,
        {
            "t_ms": 10000,
            "type": "additional_action_selected",
            "data": {
                "section_id": "actions",
                "menu_action_id": "check_bgl",
                "action_id": "blood_glucose_check",
                "label": "Check BGL",
                "finding": "Blood glucose is 118 mg/dL.",
                "phase": "during_arrest",
                "cycle": 1,
            },
        },
    )

    result = score_cpr_challenge(_config(), timeline)

    assert result["outcome"] == "rosc"
    assert any(
        ev["type"] == "additional_action_selected"
        and ev["data"]["action_id"] == "blood_glucose_check"
        for ev in result["timeline"]
    )
    additional = result["metrics"]["additional_actions"]
    assert additional["count"] == 1
    assert additional["by_section"] == {"actions": 1}
    assert additional["by_action_id"] == {"blood_glucose_check": 1}
    assert additional["events"][0]["label"] == "Check BGL"
    assert additional["events"][0]["finding"] == "Blood glucose is 118 mg/dL."


def test_additional_action_metrics_summarize_actions_and_meds_for_debrief():
    timeline = _successful_timeline()
    timeline[3:3] = [
        {
            "t_ms": 10000,
            "type": "additional_action_selected",
            "data": {
                "section_id": "actions",
                "section_label": "Actions",
                "section_kind": "action",
                "menu_action_id": "check_pupils",
                "action_id": "pupil_assessment",
                "label": "Check Pupils",
                "finding": "Pupils are mid-position and sluggish.",
                "phase": "during_arrest",
                "cycle": 1,
            },
        },
        {
            "t_ms": 11000,
            "type": "additional_action_selected",
            "data": {
                "section_id": "meds",
                "section_label": "Meds",
                "section_kind": "medication",
                "menu_action_id": "consider_naloxone_if_opioid_suspected",
                "action_id": "naloxone_consider",
                "label": "Consider Naloxone if Opioid Suspected",
                "finding": "No opioid toxidrome evidence is present.",
                "phase": "during_arrest",
                "cycle": 1,
            },
        },
    ]

    result = score_cpr_challenge(_config(), timeline)
    additional = result["metrics"]["additional_actions"]

    assert result["outcome"] == "rosc"
    assert additional["count"] == 2
    assert additional["by_section"] == {"actions": 1, "meds": 1}
    assert additional["by_action_id"] == {"pupil_assessment": 1, "naloxone_consider": 1}
    assert additional["events"][1]["section_kind"] == "medication"


def test_pulse_check_metrics_are_exposed_without_changing_score_denominator():
    timeline = _successful_timeline()
    timeline[5:5] = [
        {"t_ms": 124100, "type": "pulse_check_started", "data": {"cycle": 1, "phase": "rhythm_check"}},
        {
            "t_ms": 126100,
            "type": "pulse_check_completed",
            "data": {
                "cycle": 1,
                "phase": "rhythm_check",
                "duration_ms": 6000,
                "result": "no_pulse",
                "status": "valid",
                "valid": True,
            },
        },
    ]

    result = score_cpr_challenge(_config(), timeline)
    pulse_checks = result["metrics"]["pulse_checks"]

    assert result["outcome"] == "rosc"
    assert pulse_checks["valid_checks"] == 1
    assert pulse_checks["checks"][0]["duration_sec"] == 6.0
    assert pulse_checks["checks"][0]["result"] == "no_pulse"
    assert pulse_checks["rhythm_checks_without_pulse_check"][0]["cycle"] == 2


def test_pulse_check_metrics_flag_short_long_and_premature_restart_attempts():
    timeline = _successful_timeline()
    timeline[2:2] = [
        {"t_ms": 1000, "type": "pulse_check_started", "data": {"cycle": 0, "phase": "initial"}},
        {
            "t_ms": 2500,
            "type": "pulse_check_completed",
            "data": {
                "cycle": 0,
                "phase": "initial",
                "duration_ms": 11500,
                "result": "no_pulse",
                "status": "too_long",
                "valid": False,
            },
        },
    ]
    timeline[7:7] = [
        {"t_ms": 124500, "type": "pulse_check_started", "data": {"cycle": 1, "phase": "rhythm_check"}},
        {
            "t_ms": 126000,
            "type": "pulse_check_completed",
            "data": {
                "cycle": 1,
                "phase": "rhythm_check",
                "duration_ms": 3500,
                "result": "no_pulse",
                "status": "too_short",
                "valid": False,
            },
        },
        {
            "t_ms": 126500,
            "type": "premature_compressions_attempted",
            "data": {
                "cycle": 1,
                "reason": "aed_analysis_incomplete",
                "analysis_state": "analyzing",
                "attempted_mode": "15:2",
            },
        },
    ]

    result = score_cpr_challenge(_config(), timeline)
    pulse_checks = result["metrics"]["pulse_checks"]
    attempts = result["metrics"]["premature_compressions_attempts"]

    assert pulse_checks["too_short"][0]["cycle"] == 1
    assert pulse_checks["too_long"][0]["cycle"] == 0
    assert pulse_checks["rhythm_too_short"][0]["cycle"] == 1
    assert pulse_checks["rhythm_too_long"] == []
    assert attempts == [
        {
            "t_ms": 126500,
            "cycle": 1,
            "reason": "aed_analysis_incomplete",
            "analysis_state": "analyzing",
            "attempted_mode": "15:2",
        }
    ]


def test_initial_or_pre_challenge_pulse_check_does_not_penalize_rhythm_pulse_credit():
    from app.main import _cpr_training_rubric_detail

    timeline = _successful_timeline_with_valid_pulse_checks()
    timeline[2:2] = [
        {"t_ms": 0, "type": "pre_challenge_pulse_check_confirmed", "data": {"source": "scenario_documentation"}},
        {
            "t_ms": 500,
            "type": "additional_action_selected",
            "data": {
                "section_id": "actions",
                "menu_action_id": "blood_glucose_check",
                "action_id": "blood_glucose_check",
                "label": "Blood Glucose Check",
                "phase": "during_arrest",
                "cycle": 0,
            },
        },
        {"t_ms": 1000, "type": "pulse_check_started", "data": {"cycle": 0, "phase": "initial"}},
        {
            "t_ms": 3500,
            "type": "pulse_check_completed",
            "data": {
                "cycle": 0,
                "phase": "initial",
                "duration_ms": 11500,
                "result": "no_pulse",
                "status": "too_long",
                "valid": False,
            },
        },
    ]

    result = score_cpr_challenge(_config(), timeline)
    pulse_checks = result["metrics"]["pulse_checks"]
    detail = _cpr_training_rubric_detail(result)
    items = {item["id"]: item for item in detail[0]["items"]}

    assert result["outcome"] == "rosc"
    assert pulse_checks["pre_challenge_confirmed"] is True
    assert pulse_checks["initial_pulse_confirmed"] is True
    assert pulse_checks["too_long"][0]["cycle"] == 0
    assert pulse_checks["rhythm_too_long"] == []
    assert pulse_checks["valid_rhythm_checks"] == 3
    assert "pulse_check_timing_issue" not in result["metrics"]["analytics"]["error_tags"]
    assert items["cpr_training.pulse_checks"]["earned"] == 10
    assert items["cpr_training.pulse_checks"]["status"] == "applied"


def test_medical_control_auto_interval_is_score_neutral():
    baseline = score_cpr_challenge(_config(), _successful_timeline_with_valid_pulse_checks())
    timeline = _successful_timeline_with_valid_pulse_checks()
    timeline[-1:-1] = [
        {"t_ms": 395500, "type": "medical_control_auto_started", "data": {"mode": "15:2", "score_excluded": True}},
        {"t_ms": 515500, "type": "medical_control_auto_cycle", "data": {"displayed_cycle": 4, "shock_delivered": False, "score_excluded": True}},
        {"t_ms": 535500, "type": "medical_control_auto_ended", "data": {"cycle_count": 1, "score_excluded": True}},
    ]
    timeline[-1]["t_ms"] = 536000

    result = score_cpr_challenge(_config(), timeline)

    assert result["score"] == baseline["score"]
    assert result["outcome"] == baseline["outcome"]
    assert result["metrics"]["score_excluded_intervals"] == [
        {"start_ms": 395500, "end_ms": 535500, "duration_ms": 140000}
    ]


def test_termination_without_medical_control_or_dnr_is_critical_failure():
    result = score_cpr_challenge(_config(), _terminated_timeline_without_rosc())

    assert result["outcome"] == "criteria_not_met"
    assert result["metrics"]["termination"]["requested"] is True
    assert result["metrics"]["termination"]["valid"] is False
    assert result["metrics"]["termination"]["basis"] == "missing_medical_control_or_dnr"
    assert result["gate_results"]["no_critical_failure"]["passed"] is False
    assert "termination_without_medical_control_or_dnr" in result["metrics"]["critical_failures"]
    assert "terminated_without_achieving_rosc" in result["metrics"]["critical_failures"]
    assert len(result["metrics"]["critical_failures"]) == 2
    assert result["score_buckets"]["critical_failure"]["possible"] == 20
    assert result["score_buckets"]["critical_failure"]["earned"] == 0


def test_termination_after_medical_control_consultation_is_valid():
    timeline = _terminated_timeline_without_rosc()
    timeline.insert(-2, {"t_ms": 394500, "type": "medical_control_consulted", "data": {"score_excluded": True}})

    result = score_cpr_challenge(_config(), timeline)

    assert result["outcome"] == "terminated"
    assert result["metrics"]["termination"]["valid"] is True
    assert result["metrics"]["termination"]["basis"] == "medical_control_consulted_before_termination"
    # Consulting medical control clears the med-control failure but ROSC was achievable
    # and not achieved, so the scenario is still an auto-fail.
    assert result["metrics"]["critical_failures"] == ["terminated_without_achieving_rosc"]
    assert result["gate_results"]["no_critical_failure"]["passed"] is False
    assert result["score_buckets"]["critical_failure"]["earned"] == 0


def test_termination_with_dnr_context_is_valid_without_medical_control():
    timeline = _terminated_timeline_without_rosc()
    timeline.insert(-2, {
        "t_ms": 394500,
        "type": "additional_action_selected",
        "data": {
            "section_id": "orders",
            "menu_action_id": "dnr_present",
            "action_id": "dnr_confirmed",
            "label": "DNR present",
            "finding": "Valid DNR/withholding order confirmed",
        },
    })

    result = score_cpr_challenge(_config(), timeline)

    assert result["outcome"] == "terminated"
    assert result["metrics"]["termination"]["valid"] is True
    assert result["metrics"]["termination"]["basis"] == "dnr_or_withholding_context_documented"
    assert result["metrics"]["termination"]["dnr_or_withholding_context"] is True


def test_pediatric_two_rescuer_wrong_ratio_gets_partial_ratio_credit_and_blocks_gate():
    timeline = _successful_timeline()
    timeline[2] = {"t_ms": 4000, "type": "cpr_started", "data": {"mode": "30:2"}}

    result = score_cpr_challenge(_config(), timeline)

    assert result["outcome"] == "criteria_not_met"
    assert result["gate_results"]["ventilation_ratio"]["passed"] is False
    assert result["score_buckets"]["ventilation_ratio"]["earned"] == 2
    assert result["metrics"]["ventilation_modes"][0]["reason"] == "recognized_pediatric_bls_ratio_but_not_preferred_for_two_rescuer_ems"


def test_adult_bls_ratio_expects_thirty_to_two_when_enabled():
    config = _config(
        aha_compliance_gates=["ccf", "rhythm_decisions", "post_decision_resume", "ventilation_ratio", "no_critical_failure"]
    )
    config["arrest_type"] = "adult"
    config["algorithm"] = "adult_bls"
    config["score_ventilation_ratio"] = True
    timeline = _successful_timeline()
    timeline[2] = {"t_ms": 4000, "type": "cpr_started", "data": {"mode": "30:2"}}

    result = score_cpr_challenge(config, timeline)

    assert result["outcome"] == "rosc"
    assert result["metrics"]["ventilation_modes"][0]["expected"] == "30:2"
    assert result["score_buckets"]["ventilation_ratio"]["earned"] == 5


def test_failure_path_has_gate_results_and_no_rosc_when_ccf_window_fails():
    timeline = _successful_timeline()
    # Create a long compression pause in cycle 2 while keeping the sequence valid.
    timeline[8] = {"t_ms": 191000, "type": "compressions_paused", "reason": "rhythm_check"}

    result = score_cpr_challenge(_config(), timeline)

    assert result["outcome"] == "criteria_not_met"
    assert result["rosc"]["achieved"] is False
    assert result["gate_results"]["ccf"]["passed"] is False
    assert result["gate_results"]["ccf"]["basis"] == "cycles_2_3"
    assert len(result["metrics"]["ccf_by_cycle"]) == 3


def test_requires_backend_contract_fields_before_scoring():
    config = _config()
    del config["rubric_integration"]

    with pytest.raises(CPRChallengeError, match="rubric_integration"):
        score_cpr_challenge(config, _successful_timeline())


def test_timeline_requires_pause_and_resume_reasons():
    timeline = _successful_timeline()
    timeline[3] = {"t_ms": 124000, "type": "compressions_paused"}

    with pytest.raises(CPRChallengeError, match="compressions_paused requires reason"):
        score_cpr_challenge(_config(), timeline)


def test_repeated_missed_shocks_caps_rhythm_bucket():
    timeline = _successful_timeline()
    timeline[6] = {"t_ms": 128000, "type": "no_shock_selected"}
    timeline[11] = {"t_ms": 255000, "type": "no_shock_selected"}

    result = score_cpr_challenge(_config(), timeline)

    assert result["score_buckets"]["rhythm_decisions"]["earned"] == 5
    assert result["gate_results"]["rhythm_decisions"]["passed"] is False


def test_abandoned_attempt_is_terminal_completed_failed_attempt():
    result = score_cpr_challenge(
        _config(),
        [
            {"t_ms": 0, "type": "challenge_started"},
            {"t_ms": 1000, "type": "cpr_started"},
            {"t_ms": 5000, "type": "challenge_ended", "outcome": "abandoned"},
        ],
        context=CPRScoreContext(timestamp_integrity="abandoned"),
    )

    assert result["outcome"] == "abandoned"
    assert result["completed"] is True
    assert result["score"] == 0


def test_shocking_pea_is_major_error_and_caps_rhythm_bucket_at_ten():
    timeline = _successful_timeline()
    timeline[16] = {"t_ms": 382000, "type": "shock_delivered"}

    result = score_cpr_challenge(_config(), timeline)
    decision = result["metrics"]["rhythm_decisions"][2]

    assert decision["rhythm"] == "pea"
    assert decision["severity"] == "major"
    assert result["score_buckets"]["rhythm_decisions"]["earned"] == 10


def test_shocking_asystole_is_critical_error_and_caps_rhythm_bucket_at_five():
    config = _config()
    config["rhythm_sequence"] = ["pulseless_vt", "vf", "asystole"]
    timeline = _successful_timeline()
    timeline[15] = {"t_ms": 381000, "type": "rhythm_identified", "rhythm": "asystole"}
    timeline[16] = {"t_ms": 382000, "type": "shock_delivered"}

    result = score_cpr_challenge(config, timeline)
    decision = result["metrics"]["rhythm_decisions"][2]

    assert decision["rhythm"] == "asystole"
    assert decision["severity"] == "critical"
    assert result["score_buckets"]["rhythm_decisions"]["earned"] == 5


def test_cycle_discipline_scores_rhythm_check_start_not_resume_time():
    timeline = _successful_timeline()
    # Rhythm check starts perfectly at 120 sec after CPR start, but resume is
    # delayed. Cycle discipline should stay full; pause/resume buckets handle delay.
    timeline[6] = {"t_ms": 128000, "type": "shock_delivered"}
    timeline[7] = {"t_ms": 154000, "type": "compressions_resumed", "reason": "post_shock"}

    result = score_cpr_challenge(_config(), timeline)
    cycle_1 = result["metrics"]["cycle_discipline"][0]

    assert cycle_1["actual_sec"] == 120.0
    assert cycle_1["weight"] == 1.0


def test_missed_rhythm_check_cycles_are_debrief_flags_not_scored_cycles():
    timeline = [
        {"t_ms": 0, "type": "challenge_started"},
        {"t_ms": 0, "type": "cpr_started"},
        {"t_ms": 130000, "type": "compressions_resumed", "reason": "post_no_shock"},
        {"t_ms": 250000, "type": "compressions_paused", "reason": "rhythm_check"},
        {"t_ms": 250000, "type": "rhythm_check_started"},
        {"t_ms": 252000, "type": "rhythm_identified", "rhythm": "pea"},
        {"t_ms": 253000, "type": "no_shock_selected"},
        {"t_ms": 256000, "type": "compressions_resumed", "reason": "post_no_shock"},
        {"t_ms": 376000, "type": "compressions_paused", "reason": "rhythm_check"},
        {"t_ms": 376000, "type": "rhythm_check_started"},
        {"t_ms": 378000, "type": "rhythm_identified", "rhythm": "pea"},
        {"t_ms": 379000, "type": "no_shock_selected"},
        {"t_ms": 382000, "type": "compressions_resumed", "reason": "post_no_shock"},
        {"t_ms": 382000, "type": "challenge_ended", "outcome": "criteria_not_met"},
    ]

    result = score_cpr_challenge(
        _config(
            aha_compliance_gates=["ccf", "no_critical_failure"],
            min_ccf=0.1,
        ),
        timeline,
    )

    assert result["metrics"]["cycle_discipline"][0]["cycle"] == 2
    assert result["metrics"]["missed_rhythm_check_cycles"][0] == {
        "cycle": 1,
        "expected_by_ms": 120000,
        "cycle_start_ms": 0,
        "cycle_end_ms": 130000,
        "ended_by": "post_no_shock",
    }


def test_criteria_not_met_submission_must_reach_hard_stop_cycle():
    timeline = [
        {"t_ms": 0, "type": "challenge_started"},
        {"t_ms": 0, "type": "cpr_started"},
        {"t_ms": 1000, "type": "challenge_ended", "outcome": "criteria_not_met"},
    ]

    with pytest.raises(CPRChallengeError, match="hard_stop_cycle"):
        score_cpr_challenge(_config(), timeline)


def test_first_cpr_scenario_loads_and_exposes_public_challenge_config():
    scenario = load_scenario("adult_cardiac_arrest_01_bls")
    public = get_public_scenario_data(scenario)

    concepts = set(scenario["clinical_context"]["concepts"])
    assert scenario["cpr_challenge"]["enabled"] is True
    assert scenario["base_patient_care_rubric"] == "nremt_cardiac_arrest_aed_v1"
    assert public["cpr_challenge"]["challenge_id"] == "adult_cardiac_arrest_01_bls_cpr"
    assert "post_rosc_default" in scenario["vitals"]["post_rosc_profiles"]
    assert {"cpr", "high_performance_cpr", "rosc"}.issubset(concepts)


def test_cpr_hud_additional_actions_are_scenario_evidence_not_hud_only():
    scenario_ids = ["adult_cardiac_arrest_01_bls", "peds_cardiac_arrest_01_bls"]
    js = Path("static/js/app.js").read_text()

    assert "_recordCprAdditionalScenarioEvidence(action, section)" in js
    assert "flushVitalsBlock" in js
    assert "applyInterventionAndRecord(actionId" in js
    assert "/api/sessions/${state.sessionId}/events" in js

    for scenario_id in scenario_ids:
        scenario = load_scenario(scenario_id)
        interventions = scenario["vitals"]["interventions"]
        menu_actions = [
            action
            for section in scenario["cpr_challenge"]["additional_action_menu"]["sections"]
            for action in section["actions"]
        ]
        action_ids = {action["action_id"] for action in menu_actions}

        assert "blood_glucose_check" in action_ids
        assert "pupil_assessment" in action_ids
        assert "airway_suction" in action_ids
        assert "airway_bvm_reassess" in action_ids
        assert "blood_glucose_check" in interventions
        assert "airway_suction" in interventions
        assert "airway_bvm_reassess" in interventions
        assert "supraglottic_airway_insert" in interventions


def test_pediatric_cpr_scenario_loads_with_two_rescuer_ratio_scoring():
    scenario = load_scenario("peds_cardiac_arrest_01_bls")
    challenge = scenario["cpr_challenge"]
    concepts = set(scenario["clinical_context"]["concepts"])

    assert challenge["enabled"] is True
    assert scenario["base_patient_care_rubric"] == "nremt_cardiac_arrest_aed_v1"
    assert challenge["algorithm"] == "pediatric_bls"
    assert challenge["team_model"] == "ems_team"
    assert challenge["expected_ventilation_mode"] == "15:2"
    assert challenge["score_ventilation_ratio"] is True
    assert "ventilation_ratio" in challenge["rosc_criteria"]["aha_compliance_gates"]
    assert "post_rosc_default" in scenario["vitals"]["post_rosc_profiles"]
    assert {"cpr", "high_performance_cpr", "rosc"}.issubset(concepts)

    result = score_cpr_challenge(challenge, _successful_timeline())

    assert result["outcome"] == "rosc"
    assert result["metrics"]["ventilation_modes"][0]["selected"] == "15:2"
    assert result["score_buckets"]["ventilation_ratio"]["earned"] == 5


def test_post_rosc_vitals_profile_overrides_arrest_physiology_after_scored_cpr_rosc():
    scenario = load_scenario("adult_cardiac_arrest_01_bls")
    session = {
        "start_time": datetime.utcnow(),
        "interventions": [],
        "events": [
            {
                "event_type": "challenge_completed",
                "event_key": "cpr:adult_cardiac_arrest_01_bls_cpr",
                "source": "backend_auto",
                "occurred_at": datetime.utcnow(),
                "event_data": {
                    "challenge_type": "cpr",
                    "challenge_id": "adult_cardiac_arrest_01_bls_cpr",
                    "outcome": "rosc",
                    "score": 94,
                },
            }
        ],
    }

    vitals = calculate_vitals(session, scenario)

    assert vitals["hr"] == 96
    assert vitals["bp"] == "92/58"
    assert vitals["cpr_challenge_outcome"] == "rosc"
    assert "ROSC achieved" in vitals["patient_presentation"]


def test_pediatric_post_rosc_vitals_profile_overrides_arrest_physiology_after_scored_cpr_rosc():
    scenario = load_scenario("peds_cardiac_arrest_01_bls")
    session = {
        "start_time": datetime.utcnow(),
        "interventions": [],
        "events": [
            {
                "event_type": "challenge_completed",
                "event_key": "cpr:peds_cardiac_arrest_01_bls_cpr",
                "source": "backend_auto",
                "occurred_at": datetime.utcnow(),
                "event_data": {
                    "challenge_type": "cpr",
                    "challenge_id": "peds_cardiac_arrest_01_bls_cpr",
                    "outcome": "rosc",
                    "score": 94,
                },
            }
        ],
    }

    vitals = calculate_vitals(session, scenario)

    assert vitals["hr"] == 118
    assert vitals["bp"] == "86/50"
    assert vitals["cpr_challenge_outcome"] == "rosc"
    assert "ROSC achieved" in vitals["patient_presentation"]


def _neonatal_config():
    return {
        "enabled": True,
        "challenge_id": "newborn_resus_01_nrp",
        "arrest_type": "neonatal",
        "algorithm": "neonatal_nrp",
        "team_model": "ems_team",
        "neonatal_initial_status": {
            "gestational_age_weeks": 39,
            "tone": "poor",
            "breathing": "apneic",
            "initial_hr": 50,
        },
        "hr_reassessment_gates": [
            {"after": "initial_steps", "hr_at_gate": 70},
            {"after": "effective_ppv", "hr_at_gate": 55},
            {"after": "compressions", "hr_at_gate": 90},
        ],
        "ventilation_escalation_steps": [
            "warm_dry_stimulate_position",
            "ppv_start",
            "mr_sopa_corrective_steps",
            "compressions_3_to_1_when_hr_under_60",
        ],
        "required_equipment_ids": ["bvm_neonatal", "neonatal_mask", "stethoscope"],
        "required_medication_ids": [],
        "rubric_integration": {
            "dimension": "clinical_performance",
            "item_id": "neonatal_resuscitation_management",
            "weight_points": 20,
        },
    }


def _successful_neonatal_timeline():
    return [
        {"t_ms": 0, "type": "challenge_started"},
        {"t_ms": 12000, "type": "neonatal_action_performed", "action_id": "warm_dry_stimulate_position"},
        {"t_ms": 30000, "type": "hr_reassessed", "data": {"after": "initial_steps", "hr": 70}},
        {"t_ms": 42000, "type": "neonatal_action_performed", "action_id": "ppv_start"},
        {"t_ms": 65000, "type": "neonatal_action_performed", "action_id": "mr_sopa_corrective_steps"},
        {"t_ms": 72000, "type": "neonatal_action_performed", "action_id": "ppv_effective"},
        {"t_ms": 90000, "type": "hr_reassessed", "data": {"after": "effective_ppv", "hr": 55}},
        {"t_ms": 93000, "type": "ventilation_mode_set", "data": {"mode": "3:1"}},
        {"t_ms": 93000, "type": "neonatal_compressions_started", "data": {"mode": "3:1"}},
        {"t_ms": 125000, "type": "hr_reassessed", "data": {"after": "compressions", "hr": 90}},
        {"t_ms": 126000, "type": "challenge_ended", "outcome": "rosc"},
    ]


def test_neonatal_nrp_challenge_scores_without_rhythm_sequence_or_cpr_cycles():
    result = score_cpr_challenge(_neonatal_config(), _successful_neonatal_timeline())

    assert result["challenge_type"] == "neonatal_resuscitation"
    assert result["outcome"] == "rosc"
    assert result["score"] >= 90
    assert result["score_buckets"]["compressions_3_to_1"]["earned"] == 15
    neonatal = result["metrics"]["neonatal"]
    assert neonatal["ppv_start"]["status"] == "on_time"
    assert neonatal["effective_ppv"]["status"] == "on_time"
    assert neonatal["hr_reassessments"][1]["reported_hr"] == 55
    assert neonatal["compressions_3_to_1"]["status"] == "correct_3_to_1"
    assert result["metrics"]["analytics"]["error_tags"] == []


def test_neonatal_nrp_flags_missing_ppv_and_3_to_1_escalation():
    timeline = [
        {"t_ms": 0, "type": "challenge_started"},
        {"t_ms": 70000, "type": "neonatal_action_performed", "action_id": "warm_dry_stimulate_position"},
        {"t_ms": 90000, "type": "hr_reassessed", "data": {"after": "initial_steps", "hr": 70}},
        {"t_ms": 140000, "type": "hr_reassessed", "data": {"after": "effective_ppv", "hr": 55}},
        {"t_ms": 180000, "type": "hr_reassessed", "data": {"after": "compressions", "hr": 70}},
        {"t_ms": 181000, "type": "challenge_ended", "outcome": "criteria_not_met"},
    ]

    result = score_cpr_challenge(_neonatal_config(), timeline)

    assert result["outcome"] == "criteria_not_met"
    assert result["score"] < 70
    assert result["gate_results"]["ppv"]["passed"] is False
    assert result["gate_results"]["compressions_3_to_1"]["passed"] is False
    tags = result["metrics"]["analytics"]["error_tags"]
    assert "neonatal_ppv_gap" in tags
    assert "neonatal_3_to_1_gap" in tags


def test_neonatal_nrp_unnecessary_suction_creates_safety_gap():
    timeline = _successful_neonatal_timeline()
    timeline.insert(2, {"t_ms": 14000, "type": "neonatal_action_performed", "action_id": "suction_airway"})

    result = score_cpr_challenge(_neonatal_config(), timeline)

    assert result["score_buckets"]["safety"]["earned"] == 0
    assert result["metrics"]["neonatal"]["safety"]["flags"] == ["unnecessary_suction"]
    assert "neonatal_unnecessary_suction" in result["metrics"]["analytics"]["error_tags"]


def test_neonatal_pilot_scenario_loads_with_correct_cpr_config():
    scenario = load_scenario("newborn_resus_01_nrp")
    cpr = scenario["cpr_challenge"]

    # Challenge is active; NRP initial steps happen in-scenario (chat/actions).
    assert cpr["enabled"] is True
    # Uses regular CPR scoring engine (not neonatal) so rhythm/ROSC engine applies.
    assert cpr["arrest_type"] == "infant"
    assert "neonatal" not in cpr["algorithm"]
    # Non-shockable rhythms only — AED is used for rhythm monitoring, not defibrillation.
    assert all(r in {"asystole", "pea"} for r in cpr["rhythm_sequence"])
    assert cpr["allow_aed"] is True
    # Interim HR shown in HUD during pulse check when HR < 60.
    assert cpr["neonatal_interim_hr"] > 0
    assert cpr["neonatal_interim_hr"] < 60
    # Post-ROSC vitals have HR above 60.
    assert scenario["vitals"]["post_rosc_profiles"]["post_rosc_default"]["hr"] > 60


def test_cpr_browser_verification_nodes_are_station1_drills_not_peds_map0_nodes():
    js = Path("static/js/app.js").read_text()
    map0_start = js.index('id: "map_0"')
    pm1_start = js.index('id: "pm1"', map0_start)
    map0_block = js[map0_start:pm1_start]

    assert 'id: "peds_cardiac_arrest_01_bls"' not in map0_block
    assert 'id: "newborn_resus_01_nrp"' not in map0_block
    assert 'id: "adult_cardiac_arrest_01_bls"' not in map0_block
    assert "QA-only CPR browser verification nodes" not in map0_block
    assert 'const STATION1_CPR_SCENARIO_ID = "adult_cardiac_arrest_01_bls";' in js
    assert 'title="CPR Training Drill" aria-label="CPR Training Drill"' in js
    assert "startDrill: true" in js


def test_cpr_rosc_returns_to_normal_scenario_path_with_debrief_summary():
    adult = load_scenario("adult_cardiac_arrest_01_bls")
    peds = load_scenario("peds_cardiac_arrest_01_bls")
    js = Path("static/js/app.js").read_text()
    html = Path("static/index.html").read_text()

    assert adult["cpr_challenge"].get("training_auto_debrief_on_rosc") is False
    assert peds["cpr_challenge"].get("training_auto_debrief_on_rosc") is False
    assert adult["correct_treatment"]["recommended_actions"]
    assert peds["correct_treatment"]["recommended_actions"]
    assert "/cpr-training-debrief" not in js
    assert "Return to patient care for post-ROSC assessment, treatment, and handoff." in js
    assert 'id="debrief-cpr-section"' in html
    assert 'id="debrief-cpr-summary"' in html
    assert "cprChallengeSummary: data.cpr_challenge_summary || null" in js


def test_cpr_hud_lifecycle_applies_to_adult_pediatric_and_infant_newborn_paths():
    js = Path("static/js/app.js").read_text()
    newborn = load_scenario("newborn_resus_01_nrp")
    adult_start = js.index("async function _openCprChallengeHud")
    shared_modal_start = js.index("async function _openChallengeModal")
    adult_block = js[adult_start:shared_modal_start]

    assert newborn["cpr_challenge"]["enabled"] is True
    assert newborn["cpr_challenge"]["arrest_type"] == "infant"
    assert newborn["cpr_challenge"]["algorithm"] == "infant_bls"
    assert "/cpr-challenge/response" in adult_block
    assert 'hide("modal-challenge")' in adult_block
    assert "isPopupOpen = false" in adult_block
    assert "addPcrTreatment" in adult_block
    assert "code_log: codeLog" in adult_block
    assert "result?.completed !== false && scored" in adult_block
    assert "CPR Challenge completed" in adult_block
    assert "CPR challenge submitted but was not scored" in adult_block
    assert "_isUnscoredCprCompletedTreatmentLabel(label)" in js
    assert "_pcrTreatmentLabelsForSubmission()" in js
    assert "Return to patient care for post-ROSC assessment, treatment, and handoff." in adult_block
    assert "[data-cpr-log]" in adult_block
    assert "previousLogTop" in adult_block
    assert "Math.min(previousLogTop, logEl.scrollHeight)" in adult_block
    assert "scrollTop + logEl.clientHeight >= logEl.scrollHeight - 24" in adult_block
    assert "/cpr-training-debrief" not in js
    assert 'entry.source === "code_log"' in js
    assert "Code Log" in js
    assert 'mode === "Continuous" ? "CONT" : mode' in adult_block
    assert "pre_challenge_pulse_check_confirmed" in adult_block
    assert "_hasDocumentedPreChallengePulselessFinding()" in adult_block
    assert "terminalRoscPulseWindow()" in adult_block
    assert "let shocksDelivered = 0" in adult_block
    assert "shocksDelivered += 1" in adult_block
    assert "Cycle / Shock" in adult_block
    assert "${displayCycle}/${shocksDelivered}" in adult_block
    assert "neonatal_interim_hr" in adult_block
    assert "Medical Control" in adult_block
    assert "medical_control_auto_started" in adult_block
    assert "medical_control_auto_cycle" in adult_block
    assert "medical_control_auto_ended" in adult_block
    assert "medical-control-response-received" in adult_block
    assert "medicalControlConsulted" in adult_block
    assert "termination_of_resuscitation" in adult_block
    assert "score-neutral" in adult_block


def test_cpr_hud_does_not_hardcode_scenario_ids():
    js = Path("static/js/app.js").read_text()
    hud_block = js[js.index("async function _openCprChallengeHud"):js.index("async function _openChallengeModal")]

    assert "adult_cardiac_arrest_01_bls" not in hud_block
    assert "peds_cardiac_arrest_01_bls" not in hud_block
    assert "newborn_resus_01_nrp" not in hud_block
    assert "_openNeonatalResuscitationHud" not in hud_block


def test_cardiac_arrest_scenarios_defer_pcr_header_demographics_until_obtained():
    adult = load_scenario("adult_cardiac_arrest_01_bls")
    peds = load_scenario("peds_cardiac_arrest_01_bls")

    for scenario in (adult, peds):
        patient = scenario["patient"]
        response_map = scenario["history_response_map"]
        identity_tags = response_map["patient_identity"]["tags"]

        assert patient["pcr_demographics_deferred"] is True
        assert any(tag.startswith("[[HISTORY: Patient Name=") for tag in identity_tags)
        assert any(tag.startswith("[[HISTORY: Patient Age=") for tag in identity_tags)
        assert response_map["patient_weight"]["tag"].startswith("[[HISTORY: Patient Weight=")


def test_equipment_menu_exposes_o2_administration_modal_action():
    js = Path("static/js/app.js").read_text()
    equipment_start = js.index("const ACTION_EQUIPMENT")
    procedures_start = js.index("const ACTION_PROCEDURES", equipment_start)
    equipment_block = js[equipment_start:procedures_start]

    assert '{ label: "O₂ Administration",         action: "o2_modal"' in equipment_block


def test_cpr_training_rubric_gives_credit_for_recognition_and_valid_pulse_checks():
    from app.main import _cpr_training_rubric_detail

    result = score_cpr_challenge(_config(), _successful_timeline_with_valid_pulse_checks())
    detail = _cpr_training_rubric_detail(result)
    items = {item["id"]: item for item in detail[0]["items"]}

    assert result["metrics"]["pulse_checks"]["valid_checks"] == 3
    assert result["metrics"]["pulse_checks"]["rhythm_checks_without_pulse_check"] == []
    assert items["cpr_training.arrest_recognition"]["points"] == 5
    assert items["cpr_training.arrest_recognition"]["earned"] == 5
    assert items["cpr_training.pulse_checks"]["points"] == 10
    assert items["cpr_training.pulse_checks"]["earned"] == 10
    assert items["cpr_training.pulse_checks"]["status"] == "applied"


def test_neonatal_post_rosc_vitals_profile_overrides_after_successful_newborn_resus():
    scenario = load_scenario("newborn_resus_01_nrp")
    session = {
        "start_time": datetime.utcnow(),
        "interventions": [],
        "events": [
            {
                "event_type": "challenge_completed",
                "event_key": "cpr:newborn_resus_01_nrp_cpr",
                "source": "backend_auto",
                "occurred_at": datetime.utcnow(),
                "event_data": {
                    "challenge_type": "neonatal_resuscitation",
                    "challenge_id": "newborn_resus_01_nrp_cpr",
                    "outcome": "rosc",
                    "score": 92,
                },
            }
        ],
    }

    vitals = calculate_vitals(session, scenario)

    assert vitals["hr"] == 90
    assert vitals["rr"] == 24
    assert vitals["cpr_challenge_outcome"] == "rosc"
    assert "Newborn improving" in vitals["patient_presentation"]
