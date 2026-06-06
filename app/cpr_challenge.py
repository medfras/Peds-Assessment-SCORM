"""Deterministic CPR challenge validation and scoring.

This module keeps high-performance CPR scoring out of route handlers and out of
LLM prompts.  It evaluates a submitted HUD timeline against the authored
scenario contract and returns auditable facts for the evidence packet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class CPRChallengeError(ValueError):
    """Raised when a CPR challenge submission violates the deterministic contract."""


_SHOCKABLE_RHYTHMS = {"vf", "v_fib", "ventricular_fibrillation", "pulseless_vt", "pvt", "vt"}
_NON_SHOCKABLE_RHYTHMS = {"pea", "asystole"}
_RESUME_REASONS_SCORED = {"post_shock", "post_no_shock"}
_NEONATAL_INITIAL_STEP_ACTIONS = {
    "warm_dry_stimulate_position",
    "warm_dry_stimulate",
    "dry_stimulate",
    "airway_position_sniffing",
    "position_airway",
}
_NEONATAL_THERMOREGULATION_ACTIONS = {
    "warm_dry_stimulate_position",
    "warm_dry_stimulate",
    "thermoregulation",
    "warm_blankets",
    "hat_and_warm_blankets",
}
_NEONATAL_PPV_ACTIONS = {
    "ppv_start",
    "ppv_started",
    "neonatal_ppv_start",
    "bvm_ventilation_start",
}
_NEONATAL_EFFECTIVE_PPV_ACTIONS = {
    "ppv_effective",
    "effective_ppv",
    "chest_rise_confirmed",
    "mr_sopa_corrective_steps",
    "reposition_mask_and_airway",
}
_NEONATAL_MR_SOPA_ACTIONS = {
    "mr_sopa_corrective_steps",
    "mask_adjustment",
    "reposition_airway",
    "suction_airway_when_indicated",
    "open_mouth",
    "pressure_increase",
    "alternate_airway_when_indicated",
}
_NEONATAL_COMPRESSION_ACTIONS = {
    "compressions_3_to_1_when_hr_under_60",
    "neonatal_compressions_start",
}
_NEONATAL_SUCTION_ACTIONS = {"suction_airway", "airway_suction", "deep_suction"}


@dataclass(frozen=True)
class CPRScoreContext:
    assistive_interaction_mode: bool = False
    timestamp_integrity: str = "server_anchored"


def score_cpr_challenge(
    config: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    context: CPRScoreContext | None = None,
) -> dict[str, Any]:
    """Score a CPR challenge event timeline.

    The frontend supplies user actions and local timestamps; this function
    validates only deterministic sequence facts and computes score facts. Server
    anchoring/heartbeat validation belongs to the endpoint that calls this.
    """

    context = context or CPRScoreContext()
    cfg = _normalize_config(config)
    timeline = _normalize_events(events)

    if context.timestamp_integrity == "abandoned":
        return _abandoned_result(cfg, timeline)
    if context.timestamp_integrity == "rejected_invalid":
        return _rejected_result(cfg, timeline)
    if context.timestamp_integrity == "incomplete_unverified":
        return _incomplete_unverified_result(cfg, timeline)

    if _is_neonatal_config(cfg):
        return _score_neonatal_challenge(cfg, timeline, context)

    scoring_timeline, score_excluded_intervals = _timeline_without_score_excluded_intervals(timeline)

    cpr_started = _first_event(scoring_timeline, "cpr_started")
    if not cpr_started:
        raise CPRChallengeError("CPR challenge timeline must include cpr_started")

    cpr_started_ms = int(cpr_started["t_ms"])
    last_scored_ms = _last_scored_event_timestamp(scoring_timeline, cpr_started_ms)
    if last_scored_ms <= cpr_started_ms:
        raise CPRChallengeError("CPR challenge timeline has no scoreable time after cpr_started")

    rhythm_sequence = cfg["rhythm_sequence"]
    completed_cycles = _completed_cycles(scoring_timeline, cpr_started_ms, cfg["cycle_seconds"] * 1000)
    _validate_terminal_progress(cfg, scoring_timeline, completed_cycles)
    ccf_by_cycle = _ccf_by_cycle(scoring_timeline, completed_cycles)
    total_ccf = _total_ccf(scoring_timeline, cpr_started_ms, last_scored_ms)
    pause_metrics = _pause_metrics(scoring_timeline, cpr_started_ms)
    rhythm_decisions = _rhythm_decisions(scoring_timeline, rhythm_sequence)
    cycle_discipline = _cycle_discipline(scoring_timeline, completed_cycles, cfg["cycle_seconds"] * 1000)
    missed_rhythm_check_cycles = _missed_rhythm_check_cycles(
        scoring_timeline,
        _coaching_cycle_windows(scoring_timeline, cpr_started_ms, last_scored_ms),
        cfg["cycle_seconds"] * 1000,
    )
    resume_metrics = _resume_metrics(scoring_timeline, context.assistive_interaction_mode)
    ventilation_metrics = _ventilation_metrics(scoring_timeline, cfg, cpr_started_ms)
    medication_metrics = _medication_metrics(scoring_timeline, cfg, rhythm_decisions)
    defib_metrics = _defib_management_metrics(scoring_timeline, cfg, rhythm_decisions)
    pulse_check_metrics = _pulse_check_metrics(scoring_timeline)
    premature_attempts = _premature_compression_attempts(scoring_timeline)
    additional_action_metrics = _additional_action_metrics(timeline)
    termination_metrics = _termination_metrics(timeline)
    critical_failures: list[str] = []
    if termination_metrics["requested"] and not termination_metrics["valid"]:
        critical_failures.append("termination_without_medical_control_or_dnr")
    # Terminating without achieving ROSC is an auto-fail on ROSC-achievable scenarios,
    # unless a valid DNR/withholding order was documented (ROSC no longer the goal).
    if (
        termination_metrics["requested"]
        and cfg.get("rosc_criteria")
        and not termination_metrics.get("dnr_or_withholding_context")
    ):
        critical_failures.append("terminated_without_achieving_rosc")
    analytics_metrics = _analytics_metrics(
        total_ccf,
        ccf_by_cycle,
        pause_metrics,
        rhythm_decisions,
        cycle_discipline,
        missed_rhythm_check_cycles,
        resume_metrics,
        ventilation_metrics,
        medication_metrics,
        defib_metrics,
        pulse_check_metrics,
    )

    gate_results = _gate_results(
        cfg,
        ccf_by_cycle,
        rhythm_decisions,
        resume_metrics,
        ventilation_metrics,
        medication_metrics,
        critical_failures=critical_failures,
    )
    rosc = _rosc_result(cfg, gate_results, ccf_by_cycle)
    if rosc["achieved"]:
        outcome = "rosc"
    elif termination_metrics["requested"] and termination_metrics["valid"]:
        outcome = "terminated"
    else:
        outcome = "criteria_not_met"

    buckets = _score_buckets(
        total_ccf,
        pause_metrics,
        rhythm_decisions,
        cycle_discipline,
        resume_metrics,
        ventilation_metrics,
        medication_metrics,
        critical_failures=critical_failures,
    )

    return {
        "challenge_type": "cpr",
        "challenge_id": cfg["challenge_id"],
        "outcome": outcome,
        "timestamp_integrity": context.timestamp_integrity,
        "completed": True,
        "score": buckets["score"],
        "score_buckets": buckets["buckets"],
        "rosc": rosc,
        "gate_results": gate_results,
        "metrics": {
            "ccf": total_ccf,
            "ccf_by_cycle": ccf_by_cycle,
            "average_pause_sec": pause_metrics["average_pause_sec"],
            "longest_pause_sec": pause_metrics["longest_pause_sec"],
            "pause_events": pause_metrics["pause_events"],
            "rhythm_decisions": rhythm_decisions,
            "cycle_discipline": cycle_discipline,
            "missed_rhythm_check_cycles": missed_rhythm_check_cycles,
            "post_decision_resume": resume_metrics,
            "ventilation_modes": ventilation_metrics["events"],
            "medication_timing": medication_metrics,
            "defib_management": defib_metrics,
            "pulse_checks": pulse_check_metrics,
            "premature_compressions_attempts": premature_attempts,
            "additional_actions": additional_action_metrics,
            "termination": termination_metrics,
            "critical_failures": critical_failures,
            "score_excluded_intervals": score_excluded_intervals,
            "analytics": analytics_metrics,
        },
        "rubric_integration": cfg.get("rubric_integration"),
        "timeline": timeline,
    }


def _normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict) or not config.get("enabled", False):
        raise CPRChallengeError("CPR challenge is not enabled for this scenario")
    if _is_neonatal_config(config):
        required = [
            "challenge_id",
            "neonatal_initial_status",
            "hr_reassessment_gates",
            "ventilation_escalation_steps",
            "rubric_integration",
        ]
        missing = [key for key in required if key not in config]
        if missing:
            raise CPRChallengeError(f"Neonatal CPR challenge config missing required fields: {', '.join(missing)}")
        gates = config.get("hr_reassessment_gates") or []
        if not isinstance(gates, list) or not gates:
            raise CPRChallengeError("Neonatal CPR challenge requires at least one hr_reassessment_gates entry")
        return {
            **config,
            "arrest_type": "neonatal",
            "algorithm": config.get("algorithm") or "neonatal_nrp",
            "hr_reassessment_gates": [
                {
                    **gate,
                    "after": str(gate.get("after") or "").strip(),
                    "hr_at_gate": _safe_int(gate.get("hr_at_gate"), None),
                }
                for gate in gates
                if isinstance(gate, dict)
            ],
            "ventilation_escalation_steps": list(config.get("ventilation_escalation_steps") or []),
            "neonatal_scoring": {
                "initial_steps_full_by_ms": 30000,
                "initial_steps_partial_by_ms": 60000,
                "ppv_start_full_by_ms": 60000,
                "ppv_start_partial_by_ms": 90000,
                "effective_ppv_full_by_ms": 90000,
                "effective_ppv_partial_by_ms": 120000,
                **(config.get("neonatal_scoring") or {}),
            },
        }
    required = ["challenge_id", "cycle_seconds", "rhythm_sequence", "rosc_criteria", "rubric_integration"]
    missing = [key for key in required if key not in config]
    if missing:
        raise CPRChallengeError(f"CPR challenge config missing required fields: {', '.join(missing)}")
    criteria = config.get("rosc_criteria") or {}
    for key in ("eligible_after_cycles", "max_cycles_before_rosc", "hard_stop_cycle", "min_ccf"):
        if key not in criteria:
            raise CPRChallengeError(f"rosc_criteria missing required field: {key}")
    cycle_seconds = int(config["cycle_seconds"])
    if cycle_seconds < 60 or cycle_seconds > 300:
        raise CPRChallengeError("cycle_seconds must be between 60 and 300")
    return {
        **config,
        "cycle_seconds": cycle_seconds,
        "rhythm_sequence": [_norm_rhythm(r) for r in config.get("rhythm_sequence") or []],
        "rosc_criteria": {
            **criteria,
            "eligible_after_cycles": int(criteria["eligible_after_cycles"]),
            "max_cycles_before_rosc": int(criteria["max_cycles_before_rosc"]),
            "hard_stop_cycle": int(criteria["hard_stop_cycle"]),
            "min_ccf": float(criteria["min_ccf"]),
            "aha_compliance_gates": list(criteria.get("aha_compliance_gates") or ["ccf", "rhythm_decisions", "post_decision_resume", "no_critical_failure"]),
        },
    }


def _is_neonatal_config(config: dict[str, Any]) -> bool:
    algorithm = str((config or {}).get("algorithm") or "").lower()
    arrest_type = str((config or {}).get("arrest_type") or "").lower()
    return "neonatal" in algorithm or arrest_type == "neonatal"


def _normalize_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(events, list) or not events:
        raise CPRChallengeError("CPR challenge timeline must include at least one event")
    out: list[dict[str, Any]] = []
    last_ms = -1
    for raw in events:
        if not isinstance(raw, dict):
            raise CPRChallengeError("timeline events must be objects")
        try:
            t_ms = int(raw.get("t_ms"))
        except (TypeError, ValueError):
            raise CPRChallengeError("timeline event missing integer t_ms") from None
        if t_ms < last_ms:
            raise CPRChallengeError("timeline event timestamps must be monotonic")
        typ = str(raw.get("type") or "").strip()
        if not typ:
            raise CPRChallengeError("timeline event missing type")
        ev = {**raw, "t_ms": t_ms, "type": typ}
        if typ == "compressions_paused" and not ev.get("reason"):
            raise CPRChallengeError("compressions_paused requires reason")
        if typ == "compressions_resumed" and not ev.get("reason"):
            raise CPRChallengeError("compressions_resumed requires reason")
        out.append(ev)
        last_ms = t_ms
    return out


def _first_event(events: list[dict[str, Any]], typ: str) -> dict[str, Any] | None:
    return next((ev for ev in events if ev["type"] == typ), None)


def _events_of(events: list[dict[str, Any]], typ: str) -> list[dict[str, Any]]:
    return [ev for ev in events if ev["type"] == typ]


def _timeline_without_score_excluded_intervals(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    intervals: list[dict[str, int]] = []
    open_start: int | None = None
    for ev in events:
        if ev["type"] == "medical_control_auto_started":
            if open_start is None:
                open_start = int(ev["t_ms"])
        elif ev["type"] == "medical_control_auto_ended" and open_start is not None:
            end_ms = int(ev["t_ms"])
            if end_ms > open_start:
                intervals.append({"start_ms": open_start, "end_ms": end_ms, "duration_ms": end_ms - open_start})
            open_start = None
    if not intervals:
        return events, []

    excluded_types = {"medical_control_auto_started", "medical_control_auto_cycle", "medical_control_auto_ended"}

    def _shifted_ms(t_ms: int) -> int | None:
        shift = 0
        for interval in intervals:
            start = interval["start_ms"]
            end = interval["end_ms"]
            if t_ms > end:
                shift += interval["duration_ms"]
                continue
            if start <= t_ms <= end:
                return None
            break
        return t_ms - shift

    shifted: list[dict[str, Any]] = []
    for ev in events:
        if ev["type"] in excluded_types:
            continue
        t_ms = _shifted_ms(int(ev["t_ms"]))
        if t_ms is None:
            continue
        shifted.append({**ev, "t_ms": t_ms})
    return shifted, intervals


def _termination_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    termination = next(
        (
            ev for ev in reversed(events)
            if ev["type"] == "termination_of_resuscitation"
            or (ev["type"] == "challenge_ended" and str(ev.get("outcome") or "").strip().lower() == "terminated")
        ),
        None,
    )
    if not termination:
        return {
            "requested": False,
            "valid": None,
            "basis": None,
            "medical_control_consulted": False,
            "dnr_or_withholding_context": False,
        }

    termination_ms = int(termination["t_ms"])
    prior_events = [ev for ev in events if int(ev.get("t_ms") or 0) <= termination_ms]
    medical_control = any(ev["type"] in {"medical_control_consulted", "medical_control_contacted"} for ev in prior_events)
    dnr_context = any(_event_has_dnr_context(ev) for ev in prior_events)
    valid = medical_control or dnr_context
    if medical_control:
        basis = "medical_control_consulted_before_termination"
    elif dnr_context:
        basis = "dnr_or_withholding_context_documented"
    else:
        basis = "missing_medical_control_or_dnr"
    return {
        "requested": True,
        "valid": valid,
        "basis": basis,
        "t_ms": termination_ms,
        "medical_control_consulted": medical_control,
        "dnr_or_withholding_context": dnr_context,
    }


def _event_has_dnr_context(ev: dict[str, Any]) -> bool:
    data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
    if bool(data.get("dnr_or_withholding_context") or data.get("dnr_confirmed")):
        return True
    if ev["type"] in {"dnr_confirmed", "dnr_present", "withholding_order_confirmed"}:
        return True
    probe = " ".join(
        str(value or "")
        for value in (
            ev.get("type"),
            data.get("section_id"),
            data.get("section_label"),
            data.get("section_kind"),
            data.get("menu_action_id"),
            data.get("action_id"),
            data.get("label"),
            data.get("finding"),
        )
    )
    return bool(re.search(
        r"\b(dnr|do\s+not\s+resuscitate|post|polst|withhold(?:ing)?\s+cpr|withholding\s+order)\b",
        probe,
        re.IGNORECASE,
    ))


def _score_neonatal_challenge(
    cfg: dict[str, Any],
    timeline: list[dict[str, Any]],
    context: CPRScoreContext,
) -> dict[str, Any]:
    metrics = _neonatal_metrics(cfg, timeline)
    buckets = _neonatal_score_buckets(metrics)
    outcome = "rosc" if metrics["rosc"]["achieved"] else "criteria_not_met"
    return {
        "challenge_type": "neonatal_resuscitation",
        "challenge_id": cfg["challenge_id"],
        "outcome": outcome,
        "timestamp_integrity": context.timestamp_integrity,
        "completed": True,
        "score": buckets["score"],
        "score_buckets": buckets["buckets"],
        "rosc": metrics["rosc"],
        "gate_results": metrics["gate_results"],
        "metrics": {
            "neonatal": metrics,
            "additional_actions": _additional_action_metrics(timeline),
            "analytics": _neonatal_analytics(metrics),
        },
        "rubric_integration": cfg.get("rubric_integration"),
        "timeline": timeline,
    }


def _neonatal_metrics(cfg: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    scoring = cfg.get("neonatal_scoring") or {}
    gates = cfg.get("hr_reassessment_gates") or []
    initial_status = cfg.get("neonatal_initial_status") or {}
    action_rows = _neonatal_action_rows(events)

    initial_steps = _timed_neonatal_action(
        action_rows,
        _NEONATAL_INITIAL_STEP_ACTIONS,
        int(scoring.get("initial_steps_full_by_ms", 30000)),
        int(scoring.get("initial_steps_partial_by_ms", 60000)),
        "initial_steps",
    )
    thermoregulation = _presence_neonatal_action(
        action_rows,
        _NEONATAL_THERMOREGULATION_ACTIONS,
        "thermoregulation",
    )
    ppv_start = _timed_neonatal_action(
        action_rows,
        _NEONATAL_PPV_ACTIONS,
        int(scoring.get("ppv_start_full_by_ms", 60000)),
        int(scoring.get("ppv_start_partial_by_ms", 90000)),
        "ppv_start",
    )
    effective_ppv = _timed_neonatal_action(
        action_rows,
        _NEONATAL_EFFECTIVE_PPV_ACTIONS,
        int(scoring.get("effective_ppv_full_by_ms", 90000)),
        int(scoring.get("effective_ppv_partial_by_ms", 120000)),
        "effective_ppv",
    )
    mr_sopa = _presence_neonatal_action(action_rows, _NEONATAL_MR_SOPA_ACTIONS, "mr_sopa_corrective_steps")
    hr_reassessments = _neonatal_hr_reassessments(events, gates)
    compression_expected = any((gate.get("hr_at_gate") or 999) < 60 for gate in gates)
    compression_3_to_1 = _neonatal_compression_metrics(events, action_rows, compression_expected)
    safety = _neonatal_safety_metrics(cfg, action_rows, compression_expected)
    escalation = _neonatal_escalation_metrics(events, cfg, compression_expected)
    gate_results = {
        "initial_steps": {"passed": initial_steps["weight"] == 1.0, "basis": initial_steps["status"]},
        "ppv": {"passed": ppv_start["weight"] > 0 and effective_ppv["weight"] > 0, "basis": f"start={ppv_start['status']}; effective={effective_ppv['status']}"},
        "hr_reassessment": {"passed": all(row.get("weight") == 1.0 for row in hr_reassessments), "basis": f"{sum(1 for row in hr_reassessments if row.get('weight') == 1.0)}/{len(hr_reassessments)}"},
        "compressions_3_to_1": {
            "passed": (not compression_expected) or compression_3_to_1["weight"] == 1.0,
            "basis": compression_3_to_1["status"],
            "not_applicable": not compression_expected,
        },
        "safety": {"passed": safety["weight"] == 1.0, "basis": safety["status"]},
    }
    rosc_achieved = all(row.get("passed") for row in gate_results.values() if not row.get("not_applicable"))
    return {
        "initial_status": initial_status,
        "actions": action_rows,
        "initial_steps": initial_steps,
        "thermoregulation": thermoregulation,
        "ppv_start": ppv_start,
        "effective_ppv": effective_ppv,
        "mr_sopa": mr_sopa,
        "hr_reassessments": hr_reassessments,
        "compression_expected": compression_expected,
        "compressions_3_to_1": compression_3_to_1,
        "safety": safety,
        "escalation": escalation,
        "gate_results": gate_results,
        "rosc": {
            "achieved": rosc_achieved,
            "triggered_at_boundary": None,
            "triggered_after_cycle": None,
            "basis": "neonatal_nrp_hr_improvement" if rosc_achieved else "neonatal_criteria_not_met",
            "criteria": {
                "hr_reassessment_gates": gates,
                "ventilation_escalation_steps": cfg.get("ventilation_escalation_steps") or [],
            },
        },
    }


def _neonatal_action_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for ev in events:
        action_id = _event_action_id(ev)
        if not action_id:
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        rows.append({
            "t_ms": ev["t_ms"],
            "event_type": ev["type"],
            "action_id": action_id,
            "label": data.get("label") or ev.get("label") or action_id,
            "phase": data.get("phase") or ev.get("phase") or "neonatal_resuscitation",
        })
    return rows


def _event_action_id(ev: dict[str, Any]) -> str:
    data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
    raw = (
        ev.get("action_id")
        or ev.get("menu_action_id")
        or data.get("action_id")
        or data.get("menu_action_id")
        or data.get("id")
    )
    if not raw and ev.get("type") in {
        "initial_steps_completed",
        "ppv_started",
        "ppv_effective",
        "mr_sopa_completed",
        "neonatal_compressions_started",
    }:
        raw = {
            "initial_steps_completed": "warm_dry_stimulate_position",
            "ppv_started": "ppv_start",
            "ppv_effective": "ppv_effective",
            "mr_sopa_completed": "mr_sopa_corrective_steps",
            "neonatal_compressions_started": "compressions_3_to_1_when_hr_under_60",
        }[ev["type"]]
    return str(raw or "").strip().lower()


def _timed_neonatal_action(
    action_rows: list[dict[str, Any]],
    action_ids: set[str],
    full_by_ms: int,
    partial_by_ms: int,
    expectation_id: str,
) -> dict[str, Any]:
    selected = next((row for row in action_rows if row["action_id"] in action_ids), None)
    if not selected:
        return {"id": expectation_id, "status": "missing", "weight": 0.0, "t_ms": None}
    t_ms = int(selected["t_ms"])
    if t_ms <= full_by_ms:
        status, weight = "on_time", 1.0
    elif t_ms <= partial_by_ms:
        status, weight = "delayed_partial", 0.5
    else:
        status, weight = "late", 0.0
    return {
        "id": expectation_id,
        "status": status,
        "weight": weight,
        "t_ms": t_ms,
        "action_id": selected["action_id"],
    }


def _presence_neonatal_action(
    action_rows: list[dict[str, Any]],
    action_ids: set[str],
    expectation_id: str,
) -> dict[str, Any]:
    selected = next((row for row in action_rows if row["action_id"] in action_ids), None)
    return {
        "id": expectation_id,
        "status": "done" if selected else "missing",
        "weight": 1.0 if selected else 0.0,
        "t_ms": selected["t_ms"] if selected else None,
        "action_id": selected["action_id"] if selected else None,
    }


def _neonatal_hr_reassessments(events: list[dict[str, Any]], gates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    hr_events = [ev for ev in events if ev["type"] in {"hr_reassessed", "heart_rate_reassessed", "neonatal_hr_reassessed"}]
    for gate in gates:
        after = str(gate.get("after") or "").strip()
        expected_hr = gate.get("hr_at_gate")
        ev = next(
            (
                item for item in hr_events
                if str(((item.get("data") if isinstance(item.get("data"), dict) else {}).get("after") or item.get("after") or "")).strip() == after
            ),
            None,
        )
        if not ev:
            rows.append({
                "after": after,
                "expected_hr": expected_hr,
                "reported_hr": None,
                "t_ms": None,
                "status": "missing",
                "weight": 0.0,
            })
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        reported = _safe_int(ev.get("hr") or data.get("hr") or data.get("heart_rate"), None)
        accurate = reported is not None and expected_hr is not None and abs(reported - expected_hr) <= 5
        rows.append({
            "after": after,
            "expected_hr": expected_hr,
            "reported_hr": reported,
            "t_ms": ev["t_ms"],
            "status": "accurate" if accurate else "inaccurate",
            "weight": 1.0 if accurate else 0.0,
        })
    return rows


def _neonatal_compression_metrics(
    events: list[dict[str, Any]],
    action_rows: list[dict[str, Any]],
    compression_expected: bool,
) -> dict[str, Any]:
    mode_events = []
    for ev in events:
        if ev["type"] not in {"ventilation_mode_set", "ventilation_mode_changed", "cpr_started", "neonatal_compressions_started"}:
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        mode = ev.get("mode") or data.get("mode")
        if mode:
            mode_events.append({"t_ms": ev["t_ms"], "mode": _normalize_mode(mode), "event_type": ev["type"]})
    action = next((row for row in action_rows if row["action_id"] in _NEONATAL_COMPRESSION_ACTIONS), None)
    selected_3_to_1 = next((row for row in mode_events if row["mode"] == "3:1"), None)
    if not compression_expected:
        unnecessary = action or selected_3_to_1
        return {
            "applicable": False,
            "status": "unnecessary_started" if unnecessary else "not_indicated",
            "weight": 0.0 if unnecessary else 1.0,
            "mode_events": mode_events,
            "action": action,
        }
    if selected_3_to_1 or action:
        return {
            "applicable": True,
            "status": "correct_3_to_1",
            "weight": 1.0,
            "mode_events": mode_events,
            "action": action,
        }
    return {
        "applicable": True,
        "status": "missing_3_to_1",
        "weight": 0.0,
        "mode_events": mode_events,
        "action": None,
    }


def _neonatal_safety_metrics(cfg: dict[str, Any], action_rows: list[dict[str, Any]], compression_expected: bool) -> dict[str, Any]:
    suction_indicated = bool(cfg.get("suction_indicated") or (cfg.get("neonatal_initial_status") or {}).get("suction_indicated"))
    suction_events = [row for row in action_rows if row["action_id"] in _NEONATAL_SUCTION_ACTIONS]
    unnecessary_suction = bool(suction_events and not suction_indicated)
    unnecessary_compressions = not compression_expected and any(row["action_id"] in _NEONATAL_COMPRESSION_ACTIONS for row in action_rows)
    flags = []
    if unnecessary_suction:
        flags.append("unnecessary_suction")
    if unnecessary_compressions:
        flags.append("unnecessary_compressions")
    return {
        "status": "safe" if not flags else "safety_flags",
        "weight": 1.0 if not flags else 0.0,
        "flags": flags,
        "suction_events": suction_events,
        "suction_indicated": suction_indicated,
    }


def _neonatal_escalation_metrics(events: list[dict[str, Any]], cfg: dict[str, Any], compression_expected: bool) -> dict[str, Any]:
    medication_events = _medication_events(events)
    epi_events = [row for row in medication_events if _medication_matches_family(row.get("medication_id"), "epinephrine")]
    allow_medications = bool(cfg.get("allow_medications"))
    status = "not_applicable"
    weight = None
    if epi_events and not allow_medications:
        status = "out_of_scope_or_not_enabled"
        weight = 0.0
    elif epi_events and allow_medications and compression_expected:
        status = "escalation_documented"
        weight = 1.0
    elif allow_medications and compression_expected:
        status = "no_medication_escalation_documented"
        weight = None
    return {
        "applicable": allow_medications and compression_expected,
        "status": status,
        "weight": weight,
        "medication_events": medication_events,
    }


def _neonatal_score_buckets(metrics: dict[str, Any]) -> dict[str, Any]:
    hr_rows = metrics.get("hr_reassessments") or []
    compression_expected = bool(metrics.get("compression_expected"))
    buckets = {
        "initial_steps": {"earned": round(float(metrics["initial_steps"]["weight"]) * 20), "possible": 20},
        "ppv_effectiveness": {
            "earned": round(((float(metrics["ppv_start"]["weight"]) + float(metrics["effective_ppv"]["weight"])) / 2) * 25),
            "possible": 25,
        },
        "hr_reassessment": {"earned": _weighted_points(hr_rows, 20), "possible": 20 if hr_rows else 0},
        "compressions_3_to_1": {
            "earned": round(float(metrics["compressions_3_to_1"]["weight"]) * 15) if compression_expected else None,
            "possible": 15 if compression_expected else 0,
            "not_applicable": not compression_expected,
        },
        "thermoregulation": {"earned": round(float(metrics["thermoregulation"]["weight"]) * 10), "possible": 10},
        "safety": {"earned": round(float(metrics["safety"]["weight"]) * 10), "possible": 10},
    }
    possible = sum(row["possible"] for row in buckets.values())
    earned = sum(row["earned"] for row in buckets.values() if isinstance(row.get("earned"), (int, float)))
    score = round((earned / possible) * 100) if possible else None
    return {"score": score, "buckets": buckets}


def _neonatal_analytics(metrics: dict[str, Any]) -> dict[str, Any]:
    tags: set[str] = set()
    if metrics["initial_steps"]["weight"] < 1.0:
        tags.add("neonatal_initial_steps_delay")
    if metrics["ppv_start"]["weight"] < 1.0 or metrics["effective_ppv"]["weight"] < 1.0:
        tags.add("neonatal_ppv_gap")
    if any(row.get("weight") < 1.0 for row in metrics.get("hr_reassessments") or []):
        tags.add("neonatal_hr_reassessment_gap")
    if metrics.get("compression_expected") and metrics["compressions_3_to_1"]["weight"] < 1.0:
        tags.add("neonatal_3_to_1_gap")
    for flag in metrics["safety"].get("flags") or []:
        tags.add(f"neonatal_{flag}")
    mapping = {
        "neonatal_initial_steps_delay": "neonatal_initial_steps",
        "neonatal_ppv_gap": "neonatal_effective_ppv",
        "neonatal_hr_reassessment_gap": "neonatal_hr_reassessment",
        "neonatal_3_to_1_gap": "neonatal_3_to_1_compressions",
        "neonatal_unnecessary_suction": "neonatal_airway_decision_making",
        "neonatal_unnecessary_compressions": "neonatal_escalation_decision_making",
    }
    targets = []
    for tag in sorted(tags):
        target = mapping.get(tag)
        if target and target not in targets:
            targets.append(target)
    return {
        "error_tags": sorted(tags),
        "remediation_targets": targets,
    }


def _last_scored_event_timestamp(events: list[dict[str, Any]], cpr_started_ms: int) -> int:
    scored_types = {
        "challenge_ended",
        "rosc",
        "termination_of_resuscitation",
        "compressions_resumed",
        "shock_delivered",
        "no_shock_selected",
        "rhythm_identified",
    }
    candidates = [ev["t_ms"] for ev in events if ev["t_ms"] >= cpr_started_ms and ev["type"] in scored_types]
    return max(candidates or [events[-1]["t_ms"]])


def _completed_cycles(events: list[dict[str, Any]], cpr_started_ms: int, cycle_ms: int) -> list[dict[str, int]]:
    starts = [cpr_started_ms]
    for ev in events:
        if ev["type"] == "compressions_resumed" and ev.get("reason") in _RESUME_REASONS_SCORED:
            starts.append(ev["t_ms"])
    cycles = []
    for idx, start in enumerate(starts, start=1):
        end = starts[idx] if idx < len(starts) else None
        if end is None:
            end = _terminal_cycle_end_ms(events, start)
        if end is None:
            continue
        cycles.append({
            "cycle": idx,
            "start_ms": start,
            "end_ms": end,
            "target_end_ms": start + cycle_ms,
            "duration_ms": max(0, end - start),
        })
    return cycles


def _terminal_cycle_end_ms(events: list[dict[str, Any]], cycle_start_ms: int) -> int | None:
    """Allow ROSC/no-ROSC terminal cycles to end without forcing CPR restart.

    Clinically, a successful final cycle can end with "no shock advised" plus a
    pulse check showing ROSC. The learner should not have to restart CPR just to
    create a compressions_resumed event for the scorer.
    """

    terminal = next(
        (
            ev for ev in reversed(events)
            if ev["type"] in {"challenge_ended", "rosc", "termination_of_resuscitation"}
            and ev["t_ms"] >= cycle_start_ms
        ),
        None,
    )
    if not terminal:
        return None
    terminal_outcome = str(terminal.get("outcome") or terminal["type"]).strip().lower()
    if terminal_outcome not in {"rosc", "terminated", "termination_of_resuscitation", "criteria_not_met"}:
        return None
    decision = next(
        (
            ev for ev in reversed(events)
            if ev["t_ms"] >= cycle_start_ms
            and ev["t_ms"] <= terminal["t_ms"]
            and ev["type"] in {"shock_delivered", "no_shock_selected"}
        ),
        None,
    )
    if not decision:
        return None
    return terminal["t_ms"]


def _validate_terminal_progress(
    cfg: dict[str, Any],
    events: list[dict[str, Any]],
    completed_cycles: list[dict[str, int]],
) -> None:
    """Reject early terminal submissions that have not reached the authored hard stop.

    The endpoint performs server-window validation, but the scoring contract also
    needs to enforce the authored arrest lifecycle. Otherwise a forged client
    could end a criteria_not_met attempt before completing the required cycles
    and receive denominator-normalized credit.
    """

    terminal = next(
        (ev for ev in reversed(events) if ev["type"] in {"challenge_ended", "rosc", "termination_of_resuscitation"}),
        None,
    )
    if not terminal:
        return
    if terminal["type"] in {"rosc", "termination_of_resuscitation"}:
        return
    outcome = str(terminal.get("outcome") or "").strip().lower()
    if outcome in {"abandoned", "rosc", "terminated"}:
        return
    hard_stop = int((cfg.get("rosc_criteria") or {}).get("hard_stop_cycle") or 0)
    if hard_stop and len(completed_cycles) < hard_stop:
        raise CPRChallengeError(
            "CPR challenge criteria_not_met submissions must complete hard_stop_cycle before ending"
        )


def _coaching_cycle_windows(
    events: list[dict[str, Any]],
    cpr_started_ms: int,
    last_scored_ms: int,
) -> list[dict[str, int]]:
    starts = [cpr_started_ms]
    for ev in events:
        if ev["type"] == "compressions_resumed" and ev["t_ms"] > cpr_started_ms:
            starts.append(ev["t_ms"])
    windows = []
    for idx, start in enumerate(starts, start=1):
        end = starts[idx] if idx < len(starts) else last_scored_ms
        if end <= start:
            continue
        windows.append({
            "cycle": idx,
            "start_ms": start,
            "end_ms": end,
            "duration_ms": end - start,
        })
    return windows


def _ccf_by_cycle(events: list[dict[str, Any]], cycles: list[dict[str, int]]) -> list[dict[str, Any]]:
    rows = []
    for cycle in cycles:
        active_ms = _compression_active_ms(events, cycle["start_ms"], cycle["end_ms"])
        duration_ms = max(1, cycle["duration_ms"])
        rows.append({
            "cycle": cycle["cycle"],
            "ccf": round(active_ms / duration_ms, 3),
            "active_sec": round(active_ms / 1000, 1),
            "scored_sec": round(duration_ms / 1000, 1),
        })
    return rows


def _total_ccf(events: list[dict[str, Any]], start_ms: int, end_ms: int) -> float:
    return round(_compression_active_ms(events, start_ms, end_ms) / max(1, end_ms - start_ms), 3)


def _compression_active_ms(events: list[dict[str, Any]], start_ms: int, end_ms: int) -> int:
    active = True
    cursor = start_ms
    active_ms = 0
    for ev in events:
        t_ms = int(ev["t_ms"])
        if t_ms < start_ms:
            continue
        if t_ms > end_ms:
            break
        if active:
            active_ms += max(0, t_ms - cursor)
        cursor = t_ms
        if ev["type"] == "compressions_paused":
            active = False
        elif ev["type"] == "compressions_resumed":
            active = True
    if active:
        active_ms += max(0, end_ms - cursor)
    return max(0, active_ms)


def _pause_metrics(events: list[dict[str, Any]], cpr_started_ms: int) -> dict[str, Any]:
    pauses = []
    for idx, ev in enumerate(events):
        if ev["type"] != "compressions_paused" or ev["t_ms"] < cpr_started_ms:
            continue
        end_ms = _pause_end_ms(events, idx)
        if end_ms is None:
            continue
        sec = round(max(0, end_ms - ev["t_ms"]) / 1000, 2)
        pauses.append({"reason": ev.get("reason"), "start_ms": ev["t_ms"], "end_ms": end_ms, "pause_sec": sec})
    values = [p["pause_sec"] for p in pauses]
    return {
        "average_pause_sec": round(sum(values) / len(values), 2) if values else None,
        "longest_pause_sec": max(values) if values else None,
        "pause_events": pauses,
    }


def _pause_end_ms(events: list[dict[str, Any]], pause_index: int) -> int | None:
    pause = events[pause_index]
    reason = pause.get("reason")
    for ev in events[pause_index + 1:]:
        if reason == "rhythm_check" and ev["type"] in {"shock_delivered", "no_shock_selected", "compressions_resumed"}:
            return ev["t_ms"]
        if reason != "rhythm_check" and ev["type"] == "compressions_resumed":
            return ev["t_ms"]
    return None


def _rhythm_decisions(events: list[dict[str, Any]], rhythm_sequence: list[str]) -> list[dict[str, Any]]:
    decisions = []
    rhythm_idx = 0
    active_rhythm = None
    for ev in events:
        if ev["type"] == "rhythm_identified":
            authored = rhythm_sequence[min(rhythm_idx, max(0, len(rhythm_sequence) - 1))] if rhythm_sequence else _norm_rhythm(ev.get("rhythm"))
            active_rhythm = _norm_rhythm(ev.get("rhythm") or authored)
            rhythm_idx += 1
        elif ev["type"] in {"shock_delivered", "no_shock_selected"} and active_rhythm:
            should_shock = active_rhythm in _SHOCKABLE_RHYTHMS
            did_shock = ev["type"] == "shock_delivered"
            decisions.append({
                "cycle": len(decisions) + 1,
                "rhythm": active_rhythm,
                "decision": "shock" if did_shock else "no_shock",
                "correct": did_shock == should_shock,
                "severity": _decision_severity(active_rhythm, did_shock, should_shock),
                "t_ms": ev["t_ms"],
            })
            active_rhythm = None
    return decisions


def _decision_severity(rhythm: str, did_shock: bool, should_shock: bool) -> str | None:
    if did_shock == should_shock:
        return None
    if rhythm == "asystole" and did_shock:
        return "critical"
    if rhythm == "pea" and did_shock:
        return "major"
    if should_shock and not did_shock:
        return "major"
    return "moderate"


def _cycle_discipline(events: list[dict[str, Any]], cycles: list[dict[str, int]], cycle_ms: int) -> list[dict[str, Any]]:
    rows = []
    for cycle in cycles:
        pause_ms = _rhythm_check_pause_ms_for_cycle(events, cycle)
        if pause_ms is None:
            continue
        rhythm_check_ms = max(0, pause_ms - cycle["start_ms"])
        delta_sec = round((rhythm_check_ms - cycle_ms) / 1000, 1)
        abs_delta = abs(delta_sec)
        if abs_delta <= 15:
            weight = 1.0
        elif abs_delta <= 30:
            weight = 0.5
        else:
            weight = 0.0
        rows.append({
            "cycle": cycle["cycle"],
            "actual_sec": round(rhythm_check_ms / 1000, 1),
            "target_sec": round(cycle_ms / 1000, 1),
            "delta_sec": delta_sec,
            "weight": weight,
        })
    return rows


def _rhythm_check_pause_ms_for_cycle(events: list[dict[str, Any]], cycle: dict[str, int]) -> int | None:
    for ev in events:
        if ev["type"] != "compressions_paused" or ev.get("reason") != "rhythm_check":
            continue
        if cycle["start_ms"] <= ev["t_ms"] <= cycle["end_ms"]:
            return ev["t_ms"]
    return None


def _missed_rhythm_check_cycles(
    events: list[dict[str, Any]],
    cycles: list[dict[str, int]],
    cycle_ms: int,
) -> list[dict[str, Any]]:
    missed = []
    for cycle in cycles:
        if _rhythm_check_pause_ms_for_cycle(events, cycle) is not None:
            continue
        missed.append({
            "cycle": cycle["cycle"],
            "expected_by_ms": cycle["start_ms"] + cycle_ms,
            "cycle_start_ms": cycle["start_ms"],
            "cycle_end_ms": cycle["end_ms"],
            "ended_by": _cycle_end_reason(events, cycle["end_ms"]),
        })
    return missed


def _cycle_end_reason(events: list[dict[str, Any]], end_ms: int) -> str:
    matching = [ev for ev in events if ev["t_ms"] == end_ms]
    for ev in matching:
        if ev["type"] == "compressions_resumed":
            return ev.get("reason") or "compressions_resumed"
        if ev["type"] in {"challenge_ended", "rosc", "termination_of_resuscitation"}:
            return ev["type"]
    return "unknown"


def _resume_metrics(events: list[dict[str, Any]], assistive: bool) -> dict[str, Any]:
    rows = []
    last_decision_ms = None
    last_reason = None
    last_cycle = None
    decision_cycle = 0
    for ev in events:
        if ev["type"] == "shock_delivered":
            decision_cycle += 1
            last_decision_ms = ev["t_ms"]
            last_reason = "post_shock"
            last_cycle = decision_cycle
        elif ev["type"] == "no_shock_selected":
            decision_cycle += 1
            last_decision_ms = ev["t_ms"]
            last_reason = "post_no_shock"
            last_cycle = decision_cycle
        elif ev["type"] == "compressions_resumed" and ev.get("reason") in _RESUME_REASONS_SCORED and last_decision_ms is not None:
            sec = round((ev["t_ms"] - last_decision_ms) / 1000, 2)
            rows.append({
                "cycle": last_cycle,
                "reason": ev.get("reason") or last_reason,
                "resume_sec": sec,
                "weight": _resume_weight(sec, assistive),
            })
            last_decision_ms = None
            last_reason = None
            last_cycle = None
    return {
        "events": rows,
        "average_resume_sec": round(sum(r["resume_sec"] for r in rows) / len(rows), 2) if rows else None,
    }


def _resume_weight(sec: float, assistive: bool) -> float:
    full = 10 if assistive else 5
    partial = 15 if assistive else 10
    if sec <= full:
        return 1.0
    if sec <= partial:
        return 0.5
    return 0.0


def _pulse_check_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize pulse-check timing facts for debrief and future scoring hooks."""
    checks = []
    pre_challenge_confirmed = any(
        ev.get("type") == "pre_challenge_pulse_check_confirmed"
        for ev in events
    )
    for ev in events:
        if ev["type"] != "pulse_check_completed":
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        duration_ms = _safe_int(data.get("duration_ms"), 0)
        status = str(data.get("status") or _pulse_check_status(duration_ms))
        valid = bool(data.get("valid")) if "valid" in data else status == "valid"
        checks.append({
            "t_ms": ev["t_ms"],
            "cycle": _safe_int(data.get("cycle"), None),
            "phase": data.get("phase") or "unknown",
            "duration_sec": round(duration_ms / 1000, 2),
            "status": status,
            "valid": valid,
            "result": data.get("result") or "unknown",
        })

    initial_checks = [row for row in checks if row.get("phase") == "initial"]
    rhythm_checks = [row for row in checks if row.get("phase") == "rhythm_check"]
    rhythm_windows = _rhythm_check_windows(events)
    missing_cycles = []
    for window in rhythm_windows:
        if _pulse_check_for_window(checks, window):
            continue
        missing_cycles.append({
            "cycle": window["cycle"],
            "rhythm_check_started_ms": window["start_ms"],
            "decision_ms": window.get("decision_ms"),
        })

    return {
        "checks": checks,
        "valid_checks": sum(1 for row in checks if row.get("valid")),
        "initial_checks": initial_checks,
        "valid_initial_checks": sum(1 for row in initial_checks if row.get("valid")),
        "pre_challenge_confirmed": pre_challenge_confirmed,
        "initial_pulse_confirmed": pre_challenge_confirmed or any(row.get("valid") for row in initial_checks),
        "rhythm_check_checks": rhythm_checks,
        "valid_rhythm_checks": sum(1 for row in rhythm_checks if row.get("valid")),
        "rhythm_too_short": [row for row in rhythm_checks if row.get("status") == "too_short"],
        "rhythm_too_long": [row for row in rhythm_checks if row.get("status") == "too_long"],
        "too_short": [row for row in checks if row.get("status") == "too_short"],
        "too_long": [row for row in checks if row.get("status") == "too_long"],
        "rhythm_checks_without_pulse_check": missing_cycles,
    }


def _pulse_check_status(duration_ms: int) -> str:
    if duration_ms < 5000:
        return "too_short"
    if duration_ms > 10000:
        return "too_long"
    return "valid"


def _rhythm_check_windows(events: list[dict[str, Any]]) -> list[dict[str, int | None]]:
    windows = []
    cycle = 0
    for idx, ev in enumerate(events):
        if ev["type"] != "rhythm_check_started":
            continue
        cycle += 1
        decision_ms = None
        for later in events[idx + 1:]:
            if later["type"] in {"shock_delivered", "no_shock_selected", "compressions_resumed"}:
                decision_ms = later["t_ms"]
                break
        windows.append({
            "cycle": cycle,
            "start_ms": ev["t_ms"],
            "decision_ms": decision_ms,
        })
    return windows


def _pulse_check_for_window(checks: list[dict[str, Any]], window: dict[str, int | None]) -> dict[str, Any] | None:
    start_ms = int(window["start_ms"])
    end_ms = int(window["decision_ms"]) if window.get("decision_ms") is not None else None
    for row in checks:
        if row.get("phase") != "rhythm_check":
            continue
        if row.get("cycle") == window.get("cycle"):
            return row
        t_ms = int(row.get("t_ms") or 0)
        if end_ms is None and t_ms >= start_ms:
            return row
        if end_ms is not None and start_ms <= t_ms <= end_ms:
            return row
    return None


def _premature_compression_attempts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for ev in events:
        if ev["type"] != "premature_compressions_attempted":
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        rows.append({
            "t_ms": ev["t_ms"],
            "cycle": _safe_int(data.get("cycle"), None),
            "reason": data.get("reason") or "unknown",
            "analysis_state": data.get("analysis_state"),
            "attempted_mode": data.get("attempted_mode"),
        })
    return rows


def _additional_action_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize scenario-authored CPR Actions/Meds selections for debrief."""
    rows = []
    by_section: dict[str, int] = {}
    by_action_id: dict[str, int] = {}
    for ev in events:
        if ev["type"] != "additional_action_selected":
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        section_id = str(data.get("section_id") or "unknown")
        action_id = str(data.get("action_id") or data.get("menu_action_id") or "unknown")
        row = {
            "t_ms": ev["t_ms"],
            "cycle": _safe_int(data.get("cycle"), None),
            "section_id": section_id,
            "section_label": data.get("section_label") or section_id,
            "section_kind": data.get("section_kind") or data.get("kind") or section_id,
            "menu_action_id": data.get("menu_action_id"),
            "action_id": action_id,
            "label": data.get("label") or action_id,
            "finding": data.get("finding"),
            "phase": data.get("phase") or "unknown",
        }
        rows.append(row)
        by_section[section_id] = by_section.get(section_id, 0) + 1
        by_action_id[action_id] = by_action_id.get(action_id, 0) + 1
    return {
        "events": rows,
        "count": len(rows),
        "by_section": by_section,
        "by_action_id": by_action_id,
    }


def _safe_int(value: Any, default: int | None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ventilation_metrics(events: list[dict[str, Any]], cfg: dict[str, Any], cpr_started_ms: int) -> dict[str, Any]:
    applicable = bool(cfg.get("score_ventilation_ratio")) or "ventilation_ratio" in set(cfg["rosc_criteria"].get("aha_compliance_gates") or [])
    base_expected = _expected_ventilation_mode(cfg)
    advanced_airways = _advanced_airway_events(events)
    advanced_airway_ms = (
        advanced_airways[0]["t_ms"]
        if advanced_airways and (cfg.get("allow_advanced_airway") or cfg.get("score_advanced_airway_mode"))
        else None
    )
    rows = []
    for ev in events:
        if ev["type"] not in {"ventilation_mode_set", "ventilation_mode_changed", "cpr_started"}:
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        mode = ev.get("mode") or data.get("mode")
        if not mode:
            continue
        expected = _expected_ventilation_mode_at(base_expected, ev["t_ms"], advanced_airway_ms)
        selected = _normalize_mode(mode)
        weight, reason = _ventilation_weight(selected, expected, cfg)
        rows.append({
            "t_ms": ev["t_ms"],
            "event_type": ev["type"],
            "selected": selected,
            "expected": expected,
            "airway_state": "advanced_airway" if advanced_airway_ms is not None and ev["t_ms"] >= advanced_airway_ms else "basic_airway",
            "correct": weight == 1.0,
            "weight": weight,
            "reason": reason,
        })
    if applicable and advanced_airway_ms is not None and not any(row["t_ms"] >= advanced_airway_ms for row in rows):
        rows.append({
            "t_ms": advanced_airway_ms,
            "event_type": "missing_ventilation_mode_change",
            "selected": None,
            "expected": "Continuous",
            "airway_state": "advanced_airway",
            "correct": False,
            "weight": 0.0,
            "reason": "advanced_airway_requires_continuous_mode_change",
        })
    return {
        "applicable": applicable,
        "events": rows,
        "expected": base_expected,
        "advanced_airway_expected_mode": "Continuous" if advanced_airway_ms is not None else None,
        "advanced_airway_events": advanced_airways,
        "selected_initial": rows[0]["selected"] if rows else None,
    }


def _advanced_airway_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    airway_action_ids = {
        "advanced_airway_placed",
        "supraglottic_airway_insert",
        "supraglottic_airway_insertion",
        "endotracheal_intubation",
        "endotracheal_intubation_perform",
    }
    for ev in events:
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        action_id = str(data.get("action_id") or data.get("menu_action_id") or ev.get("action_id") or "").strip()
        if ev["type"] == "advanced_airway_placed" or action_id in airway_action_ids:
            rows.append({
                "t_ms": ev["t_ms"],
                "event_type": ev["type"],
                "action_id": action_id or "advanced_airway_placed",
                "label": data.get("label"),
            })
    return rows


def _expected_ventilation_mode_at(base_expected: str, t_ms: int, advanced_airway_ms: int | None) -> str:
    if advanced_airway_ms is not None and t_ms >= advanced_airway_ms:
        return "Continuous"
    return base_expected


def _expected_ventilation_mode(cfg: dict[str, Any]) -> str:
    if cfg.get("expected_ventilation_mode"):
        return _normalize_mode(cfg["expected_ventilation_mode"])
    algorithm = str(cfg.get("algorithm") or "").lower()
    arrest_type = str(cfg.get("arrest_type") or "").lower()
    team_model = str(cfg.get("team_model") or "ems_team").lower()
    if "neonatal" in algorithm or arrest_type == "neonatal":
        return "3:1"
    if "pediatric" in algorithm or "pals" in algorithm or arrest_type in {"pediatric", "infant"}:
        return "30:2" if team_model == "single_rescuer_exception" else "15:2"
    return "30:2"


def _normalize_mode(value: Any) -> str:
    mode = str(value or "").strip().lower().replace(" ", "")
    if mode in {"continuous", "async", "asynchronous"}:
        return "Continuous"
    return mode.replace(":1", ":1").replace(":2", ":2").upper().replace("CONTINUOUS", "Continuous")


def _ventilation_weight(selected: str, expected: str, cfg: dict[str, Any]) -> tuple[float, str]:
    if selected == expected:
        return 1.0, "correct_for_patient_team_and_airway_state"
    algorithm = str(cfg.get("algorithm") or "").lower()
    arrest_type = str(cfg.get("arrest_type") or "").lower()
    if expected == "15:2" and selected == "30:2" and ("pediatric" in algorithm or arrest_type in {"pediatric", "infant"}):
        return 0.5, "recognized_pediatric_bls_ratio_but_not_preferred_for_two_rescuer_ems"
    return 0.0, "incorrect_for_patient_team_or_airway_state"


def _medication_metrics(
    events: list[dict[str, Any]],
    cfg: dict[str, Any],
    rhythm_decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate first-pass ALS/PALS medication timing when explicitly enabled."""

    gates = set(cfg["rosc_criteria"].get("aha_compliance_gates") or [])
    applicable = bool(cfg.get("allow_medications")) and (
        bool(cfg.get("score_medication_timing")) or "medication_timing" in gates
    )
    medication_events = _medication_events(events)
    if not applicable:
        return {
            "applicable": False,
            "events": medication_events,
            "expectations": [],
            "status": "not_applicable",
        }

    expectations = _medication_expectations(cfg, rhythm_decisions)
    for expectation in expectations:
        _score_medication_expectation(expectation, medication_events)
    return {
        "applicable": True,
        "events": medication_events,
        "expectations": expectations,
        "status": "evaluated" if expectations else "no_authored_expectations",
    }


def _medication_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for ev in events:
        if ev["type"] != "medication_given":
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        raw_id = ev.get("medication_id") or data.get("medication_id") or data.get("id")
        med_id = _normalize_medication_id(raw_id)
        rows.append({
            "t_ms": ev["t_ms"],
            "medication_id": med_id,
            "raw_medication_id": raw_id,
            "dose": ev.get("dose") or data.get("dose"),
            "route": ev.get("route") or data.get("route"),
        })
    return rows


def _medication_expectations(cfg: dict[str, Any], rhythm_decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expectations: list[dict[str, Any]] = []
    if cfg.get("score_epinephrine_timing", True):
        nonshockable = next((d for d in rhythm_decisions if d.get("rhythm") in _NON_SHOCKABLE_RHYTHMS), None)
        shock_decisions = [
            d for d in rhythm_decisions
            if d.get("decision") == "shock" and d.get("rhythm") in _SHOCKABLE_RHYTHMS
        ]
        if rhythm_decisions and rhythm_decisions[0].get("rhythm") in _NON_SHOCKABLE_RHYTHMS:
            expectations.append({
                "id": "epinephrine_asap_nonshockable",
                "medication_family": "epinephrine",
                "due_after_ms": rhythm_decisions[0]["t_ms"],
                "full_by_ms": rhythm_decisions[0]["t_ms"] + 60000,
                "partial_by_ms": rhythm_decisions[0]["t_ms"] + 180000,
                "basis": f"nonshockable_cycle_{rhythm_decisions[0]['cycle']}",
            })
        elif len(shock_decisions) >= 2:
            second_shock = shock_decisions[1]
            expectations.append({
                "id": "epinephrine_after_second_shock",
                "medication_family": "epinephrine",
                "due_after_ms": second_shock["t_ms"],
                "full_by_ms": second_shock["t_ms"] + 60000,
                "partial_by_ms": second_shock["t_ms"] + 180000,
                "basis": f"second_shock_cycle_{second_shock['cycle']}",
            })
        elif nonshockable:
            expectations.append({
                "id": "epinephrine_after_nonshockable_conversion",
                "medication_family": "epinephrine",
                "due_after_ms": nonshockable["t_ms"],
                "full_by_ms": nonshockable["t_ms"] + 60000,
                "partial_by_ms": nonshockable["t_ms"] + 180000,
                "basis": f"nonshockable_cycle_{nonshockable['cycle']}",
            })

    if cfg.get("score_antiarrhythmic_timing"):
        shock_decisions = [
            d for d in rhythm_decisions
            if d.get("decision") == "shock" and d.get("rhythm") in _SHOCKABLE_RHYTHMS
        ]
        if len(shock_decisions) >= 3:
            third_shock = shock_decisions[2]
            expectations.append({
                "id": "antiarrhythmic_after_third_shock",
                "medication_family": "antiarrhythmic",
                "due_after_ms": third_shock["t_ms"],
                "full_by_ms": third_shock["t_ms"] + 60000,
                "partial_by_ms": third_shock["t_ms"] + 180000,
                "basis": f"third_shock_cycle_{third_shock['cycle']}",
            })
    return expectations


def _score_medication_expectation(expectation: dict[str, Any], medication_events: list[dict[str, Any]]) -> None:
    family = str(expectation.get("medication_family") or "")
    due_after_ms = int(expectation.get("due_after_ms") or 0)
    full_by_ms = int(expectation.get("full_by_ms") or due_after_ms)
    partial_by_ms = int(expectation.get("partial_by_ms") or full_by_ms)
    matches = [ev for ev in medication_events if _medication_matches_family(ev.get("medication_id"), family)]
    on_or_after = [ev for ev in matches if int(ev.get("t_ms") or 0) >= due_after_ms]
    early = [ev for ev in matches if int(ev.get("t_ms") or 0) < due_after_ms]
    selected = on_or_after[0] if on_or_after else (early[0] if early else None)
    if selected is None:
        expectation.update({"status": "missing", "weight": 0.0, "given_at_ms": None})
        return
    given_at_ms = int(selected.get("t_ms") or 0)
    if given_at_ms < due_after_ms:
        status = "early"
        weight = 0.5
    elif given_at_ms <= full_by_ms:
        status = "on_time"
        weight = 1.0
    elif given_at_ms <= partial_by_ms:
        status = "delayed_partial"
        weight = 0.5
    else:
        status = "late"
        weight = 0.0
    expectation.update({
        "status": status,
        "weight": weight,
        "given_at_ms": given_at_ms,
        "medication_id": selected.get("medication_id"),
    })


def _normalize_medication_id(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _medication_matches_family(medication_id: Any, family: str) -> bool:
    med_id = _normalize_medication_id(medication_id)
    if family == "epinephrine":
        return med_id in {"epinephrine", "epi", "epinephrine_cardiac", "epinephrine_1mg", "epinephrine_1_10000"}
    if family == "antiarrhythmic":
        return med_id in {"amiodarone", "amiodarone_300", "amiodarone_150", "lidocaine", "lidocaine_cardiac"}
    return False


def _defib_management_metrics(
    events: list[dict[str, Any]],
    cfg: dict[str, Any],
    rhythm_decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Collect Phase 3 manual-defib/precharge facts without changing BLS scoring."""

    manual_applicable = bool(cfg.get("allow_manual_defib") or cfg.get("score_manual_defib"))
    precharge_applicable = bool(cfg.get("allow_precharge") or cfg.get("score_precharge"))
    precharge_events = _precharge_events(events)
    shock_events = _shock_events(events)
    if not (manual_applicable or precharge_applicable):
        return {
            "applicable": False,
            "manual_defib_applicable": False,
            "precharge_applicable": False,
            "precharge_events": precharge_events,
            "shock_events": shock_events,
            "precharge_expectations": [],
            "status": "not_applicable",
        }

    expectations = []
    if precharge_applicable:
        expectations = _precharge_expectations(events, rhythm_decisions, precharge_events)
    return {
        "applicable": True,
        "manual_defib_applicable": manual_applicable,
        "precharge_applicable": precharge_applicable,
        "precharge_events": precharge_events,
        "shock_events": shock_events,
        "precharge_expectations": expectations,
        "status": "evaluated" if expectations else "no_authored_expectations",
    }


def _precharge_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for ev in events:
        if ev["type"] not in {"precharge_started", "precharge_completed"}:
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        rows.append({
            "t_ms": ev["t_ms"],
            "event_type": ev["type"],
            "device": ev.get("device") or data.get("device") or "manual_defib",
        })
    return rows


def _shock_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for ev in events:
        if ev["type"] != "shock_delivered":
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        rows.append({
            "t_ms": ev["t_ms"],
            "device": ev.get("device") or data.get("device") or "unknown",
            "dose_category": ev.get("dose_category") or data.get("dose_category"),
            "joules": ev.get("joules") or data.get("joules"),
            "precharged": bool(ev.get("precharged") or data.get("precharged")),
        })
    return rows


def _precharge_expectations(
    events: list[dict[str, Any]],
    rhythm_decisions: list[dict[str, Any]],
    precharge_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    expectations = []
    shockable_decisions = [
        row for row in rhythm_decisions
        if row.get("decision") == "shock" and row.get("rhythm") in _SHOCKABLE_RHYTHMS
    ]
    for index, decision in enumerate(shockable_decisions):
        previous_decision_ms = int(shockable_decisions[index - 1]["t_ms"]) if index else -1
        decision_ms = int(decision["t_ms"])
        rhythm_check_ms = _event_ms_for_cycle(events, "rhythm_check_started", int(decision["cycle"]))
        candidates = [
            row for row in precharge_events
            if row["event_type"] == "precharge_started"
            and previous_decision_ms < int(row["t_ms"]) <= decision_ms
        ]
        selected = candidates[-1] if candidates else None
        expectation = {
            "id": f"precharge_before_shock_cycle_{decision['cycle']}",
            "cycle": decision["cycle"],
            "rhythm": decision["rhythm"],
            "decision_t_ms": decision_ms,
            "rhythm_check_started_ms": rhythm_check_ms,
        }
        if selected is None:
            expectation.update({
                "status": "missing",
                "weight": 0.0,
                "precharge_started_ms": None,
                "basis": "no_precharge_before_shockable_decision",
            })
        elif rhythm_check_ms is not None and int(selected["t_ms"]) <= rhythm_check_ms:
            expectation.update({
                "status": "on_time",
                "weight": 1.0,
                "precharge_started_ms": int(selected["t_ms"]),
                "basis": "precharged_before_rhythm_check_pause",
            })
        else:
            expectation.update({
                "status": "late_partial",
                "weight": 0.5,
                "precharge_started_ms": int(selected["t_ms"]),
                "basis": "precharged_after_pause_before_shock",
            })
        expectations.append(expectation)
    return expectations


def _event_ms_for_cycle(events: list[dict[str, Any]], typ: str, cycle: int) -> int | None:
    count = 0
    for ev in events:
        if ev["type"] != typ:
            continue
        count += 1
        if count == cycle:
            return int(ev["t_ms"])
    return None


def _analytics_metrics(
    ccf: float,
    ccf_by_cycle: list[dict[str, Any]],
    pause_metrics: dict[str, Any],
    rhythm_decisions: list[dict[str, Any]],
    cycle_discipline: list[dict[str, Any]],
    missed_rhythm_check_cycles: list[dict[str, Any]],
    resume_metrics: dict[str, Any],
    ventilation_metrics: dict[str, Any],
    medication_metrics: dict[str, Any],
    defib_metrics: dict[str, Any],
    pulse_check_metrics: dict[str, Any],
) -> dict[str, Any]:
    """Build deterministic instructor-review facts from already-scored metrics."""

    pause_graph = [_pause_graph_row(row) for row in pause_metrics.get("pause_events") or []]
    cycle_review = _cycle_review(
        ccf_by_cycle,
        rhythm_decisions,
        cycle_discipline,
        resume_metrics.get("events") or [],
        missed_rhythm_check_cycles,
    )
    tags = _analytics_error_tags(
        ccf,
        pause_graph,
        rhythm_decisions,
        missed_rhythm_check_cycles,
        resume_metrics,
        ventilation_metrics,
        medication_metrics,
        defib_metrics,
        pulse_check_metrics,
    )
    return {
        "pause_graph": pause_graph,
        "cycle_review": cycle_review,
        "ccf_trend": _ccf_trend(ccf_by_cycle),
        "error_tags": tags,
        "remediation_targets": _remediation_targets(tags),
    }


def _pause_graph_row(row: dict[str, Any]) -> dict[str, Any]:
    pause_sec = float(row.get("pause_sec") or 0)
    if pause_sec > 20:
        severity = "severe"
    elif pause_sec > 10:
        severity = "prolonged"
    else:
        severity = "within_target"
    return {
        "reason": row.get("reason"),
        "start_ms": row.get("start_ms"),
        "end_ms": row.get("end_ms"),
        "pause_sec": pause_sec,
        "severity": severity,
    }


def _cycle_review(
    ccf_by_cycle: list[dict[str, Any]],
    rhythm_decisions: list[dict[str, Any]],
    cycle_discipline: list[dict[str, Any]],
    resume_rows: list[dict[str, Any]],
    missed_rhythm_check_cycles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    decisions_by_cycle = {row.get("cycle"): row for row in rhythm_decisions}
    discipline_by_cycle = {row.get("cycle"): row for row in cycle_discipline}
    resume_by_cycle = {row.get("cycle"): row for row in resume_rows}
    missed_by_cycle = {row.get("cycle"): row for row in missed_rhythm_check_cycles}
    cycle_ids = sorted({
        *(row.get("cycle") for row in ccf_by_cycle),
        *(row.get("cycle") for row in rhythm_decisions),
        *(row.get("cycle") for row in cycle_discipline),
        *(row.get("cycle") for row in resume_rows),
        *(row.get("cycle") for row in missed_rhythm_check_cycles),
    })
    rows = []
    for cycle in cycle_ids:
        if cycle is None:
            continue
        ccf_row = next((row for row in ccf_by_cycle if row.get("cycle") == cycle), None)
        rows.append({
            "cycle": cycle,
            "ccf": ccf_row.get("ccf") if ccf_row else None,
            "rhythm_decision": decisions_by_cycle.get(cycle),
            "cycle_discipline": discipline_by_cycle.get(cycle),
            "post_decision_resume": resume_by_cycle.get(cycle),
            "missed_rhythm_check": missed_by_cycle.get(cycle),
        })
    return rows


def _ccf_trend(ccf_by_cycle: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row.get("ccf") or 0) for row in ccf_by_cycle]
    if not values:
        return {"direction": "not_available", "values": []}
    if len(values) == 1:
        direction = "single_cycle"
    elif values[-1] > values[0]:
        direction = "improving"
    elif values[-1] < values[0]:
        direction = "declining"
    else:
        direction = "flat"
    return {
        "direction": direction,
        "values": values,
        "first": values[0],
        "last": values[-1],
        "delta": round(values[-1] - values[0], 3),
    }


def _analytics_error_tags(
    ccf: float,
    pause_graph: list[dict[str, Any]],
    rhythm_decisions: list[dict[str, Any]],
    missed_rhythm_check_cycles: list[dict[str, Any]],
    resume_metrics: dict[str, Any],
    ventilation_metrics: dict[str, Any],
    medication_metrics: dict[str, Any],
    defib_metrics: dict[str, Any],
    pulse_check_metrics: dict[str, Any],
) -> list[str]:
    tags: set[str] = set()
    if ccf < 0.80:
        tags.add("ccf_below_target")
    if ccf <= 0.60:
        tags.add("ccf_critical")
    prolonged = [row for row in pause_graph if row.get("severity") in {"prolonged", "severe"}]
    severe = [row for row in pause_graph if row.get("severity") == "severe"]
    if prolonged:
        tags.add("prolonged_pause")
    if len(prolonged) >= 2:
        tags.add("repeated_prolonged_pauses")
    if severe:
        tags.add("severe_pause")
    if missed_rhythm_check_cycles:
        tags.add("missed_rhythm_check")
    for row in rhythm_decisions:
        if row.get("correct"):
            continue
        tags.add("rhythm_decision_error")
        if row.get("rhythm") in _SHOCKABLE_RHYTHMS and row.get("decision") == "no_shock":
            tags.add("missed_shock")
        if row.get("rhythm") == "pea" and row.get("decision") == "shock":
            tags.add("inappropriate_shock_pea")
        if row.get("rhythm") == "asystole" and row.get("decision") == "shock":
            tags.add("inappropriate_shock_asystole")
    if any(row.get("weight", 1) < 1.0 for row in resume_metrics.get("events") or []):
        tags.add("delayed_resume")
    if ventilation_metrics.get("applicable") and any(row.get("weight", 1) < 1.0 for row in ventilation_metrics.get("events") or []):
        tags.add("ventilation_ratio_error")
    if medication_metrics.get("applicable") and any(row.get("weight", 1) < 1.0 for row in medication_metrics.get("expectations") or []):
        tags.add("medication_timing_gap")
    if defib_metrics.get("precharge_applicable") and any(row.get("weight", 1) < 1.0 for row in defib_metrics.get("precharge_expectations") or []):
        tags.add("precharge_timing_gap")
    if pulse_check_metrics.get("rhythm_too_short") or pulse_check_metrics.get("rhythm_too_long"):
        tags.add("pulse_check_timing_issue")
    return sorted(tags)


def _remediation_targets(tags: list[str]) -> list[str]:
    mapping = {
        "ccf_below_target": "high_performance_cpr_ccf",
        "ccf_critical": "high_performance_cpr_ccf",
        "prolonged_pause": "pause_minimization",
        "repeated_prolonged_pauses": "pause_minimization",
        "severe_pause": "pause_minimization",
        "missed_rhythm_check": "two_minute_cycle_discipline",
        "rhythm_decision_error": "aed_rhythm_decision",
        "missed_shock": "shockable_rhythm_recognition",
        "inappropriate_shock_pea": "nonshockable_rhythm_management",
        "inappropriate_shock_asystole": "nonshockable_rhythm_management",
        "delayed_resume": "post_shock_cpr_resume",
        "ventilation_ratio_error": "cpr_ventilation_ratio",
        "medication_timing_gap": "acls_pals_medication_timing",
        "precharge_timing_gap": "manual_defib_precharge_choreography",
        "pulse_check_timing_issue": "pulse_check_discipline",
    }
    targets = []
    for tag in tags:
        target = mapping.get(tag)
        if target and target not in targets:
            targets.append(target)
    return targets


def _gate_results(
    cfg: dict[str, Any],
    ccf_by_cycle: list[dict[str, Any]],
    rhythm_decisions: list[dict[str, Any]],
    resume_metrics: dict[str, Any],
    ventilation_metrics: dict[str, Any],
    medication_metrics: dict[str, Any],
    critical_failures: list[str],
) -> dict[str, Any]:
    criteria = cfg["rosc_criteria"]
    gates = set(criteria.get("aha_compliance_gates") or [])
    max_cycle = int(criteria["max_cycles_before_rosc"])
    min_ccf = float(criteria["min_ccf"])
    ccf_window = ccf_by_cycle[-2:] if len(ccf_by_cycle) >= 2 else ccf_by_cycle

    results: dict[str, Any] = {}
    if "ccf" in gates:
        results["ccf"] = {
            "passed": bool(ccf_window) and len(ccf_window) >= 2 and all(row["ccf"] >= min_ccf for row in ccf_window),
            "basis": f"cycles_{ccf_window[0]['cycle']}_{ccf_window[-1]['cycle']}" if ccf_window else None,
            "min_required": min_ccf,
        }
    if "rhythm_decisions" in gates:
        relevant = [d for d in rhythm_decisions if d["cycle"] <= max_cycle]
        results["rhythm_decisions"] = {
            "passed": bool(relevant) and all(d.get("correct") for d in relevant),
            "basis": f"{sum(1 for d in relevant if d.get('correct'))}/{len(relevant)}",
        }
    if "post_decision_resume" in gates:
        resume_rows = resume_metrics.get("events") or []
        results["post_decision_resume"] = {
            "passed": bool(resume_rows) and all(r.get("weight", 0) >= 0.5 for r in resume_rows),
            "basis": f"{sum(1 for r in resume_rows if r.get('weight', 0) >= 0.5)}/{len(resume_rows)}",
        }
    if "ventilation_ratio" in gates:
        if not ventilation_metrics.get("applicable"):
            results["ventilation_ratio"] = {
                "passed": True,
                "basis": "not_applicable_bucket_removed",
                "not_applicable": True,
            }
        else:
            rows = ventilation_metrics.get("events") or []
            results["ventilation_ratio"] = {
                "passed": bool(rows) and all(row.get("weight") == 1.0 for row in rows),
                "basis": f"{sum(1 for row in rows if row.get('weight') == 1.0)}/{len(rows)} expected={ventilation_metrics.get('expected')}",
            }
    if "medication_timing" in gates:
        if not medication_metrics.get("applicable"):
            results["medication_timing"] = {
                "passed": True,
                "basis": "not_applicable_bucket_removed",
                "not_applicable": True,
            }
        else:
            expectations = medication_metrics.get("expectations") or []
            results["medication_timing"] = {
                "passed": bool(expectations) and all(row.get("weight") == 1.0 for row in expectations),
                "basis": f"{sum(1 for row in expectations if row.get('weight') == 1.0)}/{len(expectations)}",
            }
    if "no_critical_failure" in gates:
        results["no_critical_failure"] = {
            "passed": not critical_failures,
            "basis": critical_failures,
        }
    return results


def _rosc_result(cfg: dict[str, Any], gate_results: dict[str, Any], ccf_by_cycle: list[dict[str, Any]]) -> dict[str, Any]:
    criteria = cfg["rosc_criteria"]
    eligible_after = int(criteria["eligible_after_cycles"])
    max_cycles = int(criteria["max_cycles_before_rosc"])
    completed = len(ccf_by_cycle)
    gates_passed = all(row.get("passed") for row in gate_results.values() if not row.get("not_applicable"))
    achieved = completed >= eligible_after and completed <= max_cycles and gates_passed
    if achieved:
        after_cycle = completed
        boundary = completed + 1
        basis = "performance_gated_aha_compliance"
    else:
        after_cycle = None
        boundary = None
        basis = "criteria_not_met"
    return {
        "achieved": achieved,
        "triggered_at_boundary": boundary,
        "triggered_after_cycle": after_cycle,
        "basis": basis,
        "criteria": criteria,
    }


def _score_buckets(
    ccf: float,
    pause_metrics: dict[str, Any],
    rhythm_decisions: list[dict[str, Any]],
    cycle_discipline: list[dict[str, Any]],
    resume_metrics: dict[str, Any],
    ventilation_metrics: dict[str, Any],
    medication_metrics: dict[str, Any],
    *,
    critical_failures: list[str] | None = None,
) -> dict[str, Any]:
    ventilation_rows = ventilation_metrics.get("events") or []
    ventilation_applicable = bool(ventilation_metrics.get("applicable"))
    ventilation_possible = 5 if ventilation_applicable else 0
    if ventilation_applicable:
        ventilation_earned = _weighted_points(ventilation_rows, 5) if ventilation_rows else 0
    else:
        ventilation_earned = None
    medication_expectations = medication_metrics.get("expectations") or []
    medication_applicable = bool(medication_metrics.get("applicable"))
    medication_possible = 5 if medication_applicable else 0
    if medication_applicable:
        medication_earned = _weighted_points(medication_expectations, 5) if medication_expectations else 0
    else:
        medication_earned = None
    buckets = {
        "ccf": {"earned": _ccf_points(ccf), "possible": 30},
        "pause_discipline": {"earned": _pause_points(pause_metrics), "possible": 20},
        "rhythm_decisions": {"earned": _rhythm_points(rhythm_decisions), "possible": 20 if rhythm_decisions else 0},
        "cycle_discipline": {"earned": _weighted_points(cycle_discipline, 10), "possible": 10 if cycle_discipline else 0},
        "post_decision_resume": {"earned": _weighted_points(resume_metrics.get("events") or [], 10), "possible": 10 if (resume_metrics.get("events") or []) else 0},
        "ventilation_ratio": {"earned": ventilation_earned, "possible": ventilation_possible, "not_applicable": not ventilation_applicable},
        "medication_timing": {"earned": medication_earned, "possible": medication_possible, "not_applicable": not medication_applicable},
    }
    if critical_failures:
        buckets["critical_failure"] = {
            "earned": 0,
            "possible": 20,
            "failures": critical_failures,
        }
    possible = sum(row["possible"] for row in buckets.values())
    earned = sum(row["earned"] for row in buckets.values() if isinstance(row.get("earned"), (int, float)))
    score = round((earned / possible) * 100) if possible else None
    return {"score": score, "buckets": buckets}


def _ccf_points(ccf: float) -> int:
    if ccf >= 0.80:
        return 30
    if ccf > 0.60:
        return round(((ccf - 0.60) / 0.20) * 30)
    return 0


def _pause_points(pause_metrics: dict[str, Any]) -> int:
    points = 20
    for pause in pause_metrics.get("pause_events") or []:
        sec = float(pause["pause_sec"])
        if sec <= 10:
            continue
        if sec <= 15:
            points -= 2
        elif sec <= 20:
            points -= 5
        else:
            points -= 8
    return max(0, points)


def _rhythm_points(decisions: list[dict[str, Any]]) -> int | None:
    if not decisions:
        return None
    correct = sum(1 for d in decisions if d.get("correct"))
    points = round((correct / len(decisions)) * 20)
    missed_shocks = sum(1 for d in decisions if d.get("severity") == "major")
    critical = any(d.get("severity") == "critical" for d in decisions)
    if critical:
        points = min(points, 5)
    if missed_shocks >= 2:
        points = min(points, 5)
    elif missed_shocks == 1:
        points = min(points, 10)
    return points


def _weighted_points(rows: list[dict[str, Any]], possible: int) -> int | None:
    if not rows:
        return None
    return round((sum(float(row.get("weight", 0)) for row in rows) / len(rows)) * possible)


def _abandoned_result(cfg: dict[str, Any], timeline: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "challenge_type": "cpr",
        "challenge_id": cfg.get("challenge_id"),
        "outcome": "abandoned",
        "timestamp_integrity": "abandoned",
        "completed": True,
        "score": 0,
        "score_buckets": {},
        "rosc": {"achieved": False, "triggered_at_boundary": None, "triggered_after_cycle": None, "basis": "abandoned"},
        "gate_results": {},
        "metrics": {},
        "timeline": timeline,
        "rubric_integration": cfg.get("rubric_integration"),
    }


def _rejected_result(cfg: dict[str, Any], timeline: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "challenge_type": "cpr",
        "challenge_id": cfg.get("challenge_id"),
        "outcome": "rejected_invalid",
        "timestamp_integrity": "rejected_invalid",
        "completed": False,
        "score": None,
        "score_buckets": {},
        "rosc": {"achieved": False, "triggered_at_boundary": None, "triggered_after_cycle": None, "basis": "rejected_invalid"},
        "gate_results": {},
        "metrics": {},
        "timeline": [],
        "rubric_integration": cfg.get("rubric_integration"),
    }


def _incomplete_unverified_result(cfg: dict[str, Any], timeline: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "challenge_type": "cpr",
        "challenge_id": cfg.get("challenge_id"),
        "outcome": "incomplete_unverified",
        "timestamp_integrity": "incomplete_unverified",
        "completed": False,
        "score": None,
        "score_buckets": {},
        "rosc": {"achieved": False, "triggered_at_boundary": None, "triggered_after_cycle": None, "basis": "incomplete_unverified"},
        "gate_results": {},
        "metrics": {},
        "timeline": timeline,
        "rubric_integration": cfg.get("rubric_integration"),
    }


def _norm_rhythm(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
