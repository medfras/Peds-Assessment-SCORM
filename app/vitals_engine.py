"""
Calculates real-time vitals based on elapsed time and interventions applied.
Vitals deteriorate over time if untreated; interventions modify the trajectory.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def calculate_vitals(session, scenario: dict) -> dict:
    """
    Returns current vital signs as a dict.
    Numeric vitals deteriorate at per-minute rates from the scenario definition.
    Each applied intervention adds an immediate change and modifies the ongoing rate.
    """
    baseline = scenario["vitals"]["baseline"]
    deteri = scenario["vitals"]["deterioration"]
    base_rates = deteri.get("rates", {})
    caps = deteri.get("caps", {})
    interventions_data = scenario["vitals"].get("interventions", {})

    # Build working copies of numeric vitals and rate modifiers
    vitals: dict[str, float] = {}
    rate_mods: dict[str, float] = {}
    for key, spec in baseline.items():
        if spec.get("numeric", True) and isinstance(spec["value"], (int, float)):
            vitals[key] = float(spec["value"])
            rate_mods[key] = 1.0

    # Support both ORM objects and plain dicts (snapshot from chat endpoint)
    if isinstance(session, dict):
        raw_interventions = session["interventions"]
        start_time = session["start_time"]
        applied = sorted(raw_interventions, key=lambda i: i["applied_at"])
        get_name = lambda i: i["name"]
        get_dt   = lambda i: i["applied_at"]
    else:
        applied = sorted(session.interventions, key=lambda i: i.applied_at)
        start_time = session.start_time
        get_name = lambda i: i.name
        get_dt   = lambda i: i.applied_at

    prev_dt = start_time
    now = datetime.utcnow()

    segments  = [*(get_dt(i) for i in applied), now]
    int_names = [get_name(i) for i in applied] + [None]

    # Collects string vital overrides from interventions (e.g. cardiac_rhythm when
    # the monitor is placed). Applied to result after baseline copy so the last
    # intervention's override wins. string_thresholds can still override these.
    pending_string_overrides: dict[str, str] = {}

    for seg_end, int_name in zip(segments, int_names):
        # Elapsed minutes in this segment
        elapsed = max(0.0, (seg_end - prev_dt).total_seconds() / 60.0)

        # Apply deterioration for this segment
        for vital, base_rate in base_rates.items():
            if vital in vitals:
                vitals[vital] += base_rate * rate_mods.get(vital, 1.0) * elapsed

        # Apply intervention effects at end of this segment
        if int_name and int_name in interventions_data:
            effects = interventions_data[int_name].get("effects", {})
            for vital, fx in effects.items():
                if vital == "string_override" and isinstance(fx, dict):
                    pending_string_overrides.update(fx)
                elif vital in vitals and isinstance(fx, dict):
                    vitals[vital] += fx.get("immediate_change", 0)
                    if "rate_modifier" in fx:
                        rate_mods[vital] = rate_mods.get(vital, 1.0) * fx["rate_modifier"]

        prev_dt = seg_end

    # Enforce caps
    for vital, cap_spec in caps.items():
        if vital not in vitals:
            continue
        # GCS only drops once SpO2 threshold is crossed
        if vital == "gcs":
            spo2_trigger = cap_spec.get("trigger_spo2_below")
            if spo2_trigger and vitals.get("spo2", 100) >= spo2_trigger:
                continue  # GCS stays at baseline until SpO2 triggers it
        if "max" in cap_spec:
            vitals[vital] = min(vitals[vital], cap_spec["max"])
        if "min" in cap_spec:
            vitals[vital] = max(vitals[vital], cap_spec["min"])

    # Round for display
    result: dict[str, Any] = {}
    for vital, value in vitals.items():
        if vital in ("hr", "rr", "gcs"):
            result[vital] = int(round(value))
        elif vital == "spo2":
            # SpO2 is reported/documented as a whole number percentage in scene chat,
            # handoff, and narrative flows so clinically normal rounding (e.g. 92.2 -> 92%)
            # does not create artificial scoring mismatches.
            result[vital] = int(round(value))
        else:
            result[vital] = round(value, 1)

    # Copy non-numeric vitals from baseline, potentially overriding with thresholds
    for key, spec in baseline.items():
        if not (spec.get("numeric", True) and isinstance(spec["value"], (int, float))):
            result[key] = spec["value"]

    # Apply intervention string overrides (e.g. cardiac_rhythm set when monitor placed).
    # Runs after baseline copy so overrides win over baseline defaults.
    # string_thresholds below can still override these based on numeric conditions.
    result.update(pending_string_overrides)

    # Apply deterioration string thresholds based on current numeric vitals
    thresholds = deteri.get("string_thresholds", {})
    for vital_str, rules in thresholds.items():
        for rule in rules:
            trigger_key = next((k for k in rule if k.endswith("_below") or k.endswith("_above")), None)
            if not trigger_key:
                continue
            numeric_key = trigger_key.replace("_below", "").replace("_above", "")
            current_num = result.get(numeric_key)
            if current_num is None:
                continue
            if trigger_key.endswith("_below") and current_num < rule[trigger_key]:
                result[vital_str] = rule["value"]
            elif trigger_key.endswith("_above") and current_num > rule[trigger_key]:
                result[vital_str] = rule["value"]

    # Apply improvement thresholds — only if the required intervention was applied
    improvement = scenario["vitals"].get("improvement", {})
    required_intervention = improvement.get("requires_intervention")
    if required_intervention and required_intervention not in [get_name(i) for i in applied]:
        improvement = {}  # skip improvement — required treatment not given
    imp_thresholds = improvement.get("string_thresholds", {})
    for vital_str, rules in imp_thresholds.items():
        for rule in rules:
            conditions_met = True
            for key, threshold_val in rule.items():
                if key == "value":
                    continue
                numeric_key = key.replace("_above", "").replace("_below", "")
                current_num = result.get(numeric_key)
                if current_num is None:
                    conditions_met = False
                    break
                if key.endswith("_above") and current_num <= threshold_val:
                    conditions_met = False
                    break
                if key.endswith("_below") and current_num >= threshold_val:
                    conditions_met = False
                    break
            if conditions_met:
                result[vital_str] = rule["value"]
                break  # first matching rule wins

    # Determine patient presentation milestone (best matching)
    result["patient_presentation"] = None
    for milestone in improvement.get("presentation_milestones", []):
        conditions_met = True
        for key, threshold_val in milestone.items():
            if key == "text":
                continue
            numeric_key = key.replace("_above", "").replace("_below", "")
            current_num = result.get(numeric_key)
            if current_num is None:
                conditions_met = False
                break
            if key.endswith("_above") and current_num <= threshold_val:
                conditions_met = False
                break
            if key.endswith("_below") and current_num >= threshold_val:
                conditions_met = False
                break
        if conditions_met:
            result["patient_presentation"] = milestone["text"]
            break  # first (best) matching milestone wins

    return _apply_post_rosc_profile(result, session, scenario)


def format_vitals_for_prompt(vitals: dict, baseline: dict) -> str:
    """Returns a formatted string of vitals for inclusion in the AI system prompt."""
    lines = []
    # Priority order — any baseline key not listed here is appended at the end
    ordered_keys = ["hr", "rr", "spo2", "bp", "temp", "blood_glucose", "gcs",
                    "cardiac_rhythm", "etco2", "ecg_findings",
                    "skin_color", "cap_refill", "pupils", "lung_sounds", "work_of_breathing"]
    seen = set()
    for key in ordered_keys:
        spec = baseline.get(key)
        if spec is None:
            continue
        seen.add(key)
        label = spec.get("label", key)
        unit = spec.get("unit", "")
        val = vitals.get(key, spec["value"])
        detail = spec.get("detail", "")
        alt = spec.get("alt_display", "")
        display = f"{val}{unit}"
        if alt:
            display += f" ({alt})"
        if detail:
            display += f" ({detail})"
        lines.append(f"  {label}: {display}")

    # Catch-all: any baseline key the scenario defines that isn't in ordered_keys
    for key, spec in baseline.items():
        if key in seen:
            continue
        label = spec.get("label", key)
        unit = spec.get("unit", "")
        val = vitals.get(key, spec.get("value", ""))
        detail = spec.get("detail", "")
        alt = spec.get("alt_display", "")
        display = f"{val}{unit}"
        if alt:
            display += f" ({alt})"
        if detail:
            display += f" ({detail})"
        lines.append(f"  {label}: {display}")

    presentation = vitals.get("patient_presentation")
    if presentation:
        lines.append(f"\n  PATIENT APPEARANCE AFTER TREATMENT: {presentation}")

    return "\n".join(lines)


def _latest_cpr_challenge_result(session) -> dict | None:
    if isinstance(session, dict):
        events = session.get("events") or []
    else:
        events = list(getattr(session, "events", None) or [])
    cpr_events = []
    for ev in events:
        if isinstance(ev, dict):
            event_type = ev.get("event_type")
            source = ev.get("source")
            event_data = ev.get("event_data") or {}
            occurred_at = ev.get("occurred_at")
        else:
            event_type = getattr(ev, "event_type", None)
            source = getattr(ev, "source", None)
            event_data = getattr(ev, "event_data", None) or {}
            occurred_at = getattr(ev, "occurred_at", None)
        if (
            event_type == "challenge_completed"
            and source == "backend_auto"
            and event_data.get("challenge_type") in {"cpr", "neonatal_resuscitation"}
        ):
            cpr_events.append((occurred_at, event_data))
    if not cpr_events:
        return None
    cpr_events.sort(key=lambda row: row[0] or datetime.min, reverse=True)
    return cpr_events[0][1]


def _apply_post_rosc_profile(result: dict, session, scenario: dict) -> dict:
    cpr_result = _latest_cpr_challenge_result(session)
    if not cpr_result or cpr_result.get("outcome") != "rosc":
        return result
    cpr_config = scenario.get("cpr_challenge") or {}
    profile_id = cpr_config.get("post_rosc_vitals_profile_id") or "post_rosc_default"
    profiles = scenario.get("vitals", {}).get("post_rosc_profiles", {})
    profile = profiles.get(profile_id)
    if not isinstance(profile, dict):
        return result
    updated = dict(result)
    for key, value in profile.items():
        if isinstance(value, dict) and "value" in value:
            updated[key] = value["value"]
        else:
            updated[key] = value
    updated["cpr_challenge_outcome"] = "rosc"
    updated["cpr_challenge_score"] = cpr_result.get("score")
    return updated
