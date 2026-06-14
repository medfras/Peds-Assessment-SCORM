"""
Loads scenario JSON files from disk and provides helpers for displaying scenario data.

Protocol resolution:
  Scenarios may reference an external protocol file via the "protocol" key instead of
  embedding a full "protocol_config" block inline. Both forms are supported.

  Simple reference (recommended):
      "protocol": "MI/04_OB_Pediatrics/04-5_respiratory_distress"

  Reference with scenario-specific overrides:
      "protocol": {
          "ref": "MI/04_OB_Pediatrics/04-5_respiratory_distress",
          "overrides": { "scope_notes": ["CPAP unavailable — not on this unit"] }
      }

  Inline (legacy / backward-compatible):
      "protocol_config": { ... }

  Resolution order: external file → deep-merged with overrides → stored as protocol_config.
  If both "protocol" and "protocol_config" are present, "protocol" wins.

Context adaptation:
  Scenarios are authored generically using placeholders and omitting agency-specific
  fields. Call adapt_scenario_to_context() after load_scenario() to fill in values
  from the active session's agency config and MCA. The lru_cache stores only the
  generic base; adaptation is applied per-request and never cached.

  Placeholders resolved at adaptation time:
    {unit}   → agency.unit_designator  (used in dispatch.unit and dispatch.text)

  Agency-sourced fields (override scenario defaults when agency config is present):
    non_transport_agency  ← not agency.service_type.transport
    als_arrival_minutes   ← agency.als_dispatch.arrival_minutes
    als_unit_name         ← agency.als_dispatch.unit_name

  Protocol MCA substitution:
    When the session MCA differs from the scenario's default protocol MCA, the engine
    attempts to find a matching protocol under the session MCA path and re-resolves.
    Falls back to the scenario default if no matching file exists.

MCA expansion scope adaptation:
  Michigan base protocols define optional BLS expansions — procedures or medications
  that are NOT in default EMT scope but can be authorized via MCA board selection.
  Examples: epinephrine draw-up IM for BLS, CPAP for BLS, I-Gel for BLS.

  Scenario interventions that require an expansion carry a "required_expansion" key.
  At adaptation time, adapt_scenario_to_context() checks mca_config.json for the
  session MCA's "bls_expansions" list:
    - If the expansion IS selected → intervention stays within_bls_scope: true
    - If the expansion is NOT selected → within_bls_scope flipped to false;
      "expansion_not_selected": true added; out_of_scope_bls updated in protocol_config

  The resolved expansion set is written to adapted["mca_expansions"] for use by
  the AI client when building clinical context.
"""
from __future__ import annotations

import calendar
import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.logging_config import get_logger
from app.pediatric_length_based_tape import patient_tape_reference, tape_reference_sentence
from app.protocol_engine import action_ids_for_intervention, get_resolved_protocol
from app.scenarios.vocabulary import validate_scenario, ScenarioVocabularyError

logger = get_logger()

SCENARIOS_DIR  = Path(__file__).parent / "scenarios"
AGENCIES_DIR   = Path(__file__).parent / "agencies"
MCA_CONFIG_PATH = Path(__file__).parent / "mca_config.json"

IN_SCENARIO_LEXI_HINTS = [
    {"label": "What can you do?", "msg": "What can you do?"},
    {"label": "Next Step?", "msg": "What should I do next?"},
    {"label": "Missing Info?", "msg": "What information am I missing?"},
    {"label": "BLS Scope?", "msg": "What is within my BLS scope in this scenario?"},
]

_FTO_GUIDANCE_NOTE_RE = re.compile(
    r"(^|\.\s+)[^.]{0,120}\b(?:not indicated|not yet indicated|contraindicated|not recommended|premature)\b"
    r"|\bindicated for [^.;]+,\s*not\b",
    re.IGNORECASE,
)


_INDICATION_GATE_STATUSES = frozenset({"not_indicated_now", "contraindicated"})

# Vitals-evaluatable allowed_when conditions.
# Maps condition key → lambda(vitals_dict) → bool.
# Conditions not in this map require clinical assessment data not available from
# vitals alone; they are treated as "unevaluatable" (not assumed false).
_VITALS_CONDITION_EVALUATORS: dict[str, object] = {
    "apnea":                  lambda v: v.get("rr", 99) == 0,
    "spo2_below_88":          lambda v: (v.get("spo2") or 100) < 88,
    "severe_hypoxia":         lambda v: (v.get("spo2") or 100) < 88,
    "spo2_below_94":          lambda v: (v.get("spo2") or 100) < 94,
    "hypoxia":                lambda v: (v.get("spo2") or 100) < 94,
    "decreased_loc":          lambda v: (v.get("gcs") or 15) < 13,
    "obtunded":               lambda v: (v.get("gcs") or 15) < 10,
    "unresponsive":           lambda v: (v.get("gcs") or 15) <= 8,
}


def evaluate_indication_gate_conditions(
    allowed_when: list[str],
    vitals: dict,
) -> dict[str, bool | None]:
    """Evaluate each allowed_when condition against current vitals.

    Returns a dict mapping condition → True/False/None.
    None means the condition cannot be determined from vitals alone (not assumed False).
    Only False entries mean the condition is definitively not met.
    """
    result: dict[str, bool | None] = {}
    for condition in allowed_when:
        evaluator = _VITALS_CONDITION_EVALUATORS.get(condition)
        if evaluator is not None:
            try:
                result[condition] = bool(evaluator(vitals))
            except Exception:
                result[condition] = None
        else:
            result[condition] = None  # unevaluatable from vitals
    return result


def build_intervention_clinical_snapshot(
    intervention_name: str,
    scenario: dict,
    vitals: dict,
) -> dict:
    """Build an event_data payload for an intervention_applied SessionEvent.

    Captures the vitals state and indication_gate at the moment of application.
    This snapshot is consumed by the scoring service to detect premature interventions.
    """
    idata = scenario.get("vitals", {}).get("interventions", {}).get(intervention_name, {})
    gate = idata.get("indication_gate") if isinstance(idata, dict) else None

    snapshot: dict = {
        "vitals_snapshot": {
            k: vitals.get(k)
            for k in ("hr", "rr", "spo2", "bp", "gcs", "blood_glucose")
            if vitals.get(k) is not None
        },
    }

    if isinstance(gate, dict) and gate.get("status") in _INDICATION_GATE_STATUSES:
        allowed_when = gate.get("allowed_when") or []
        conditions = evaluate_indication_gate_conditions(allowed_when, vitals)
        snapshot["indication_gate"] = {
            "status": gate["status"],
            "reason": gate.get("reason", ""),
            "allowed_when": allowed_when,
        }
        snapshot["conditions_met"] = [k for k, v in conditions.items() if v is True]
        snapshot["conditions_unevaluatable"] = [k for k, v in conditions.items() if v is None]

    return snapshot


def _public_intervention_fto_guidance(idata: dict) -> str:
    """Return learner-safe FTO guidance only for blocked/inappropriate actions.

    Priority order:
    1. unavailable_reason (scenario marks intervention unavailable)
    2. expansion_not_selected (agency expansion not active)
    3. within_bls_scope == False (out of provider scope)
    4. indication_gate.reason (structured "not indicated now" / contraindicated)
    5. notes regex fallback (legacy — for entries not yet migrated to indication_gate)
    """
    unavailable_reason = str(idata.get("unavailable_reason") or "").strip()
    if unavailable_reason:
        return unavailable_reason
    if idata.get("expansion_not_selected"):
        return "This treatment requires an agency-specific protocol expansion that is not active for this session."
    if idata.get("within_bls_scope") is False:
        notes = str(idata.get("notes") or "").strip()
        return notes or "This intervention is outside the current BLS/EMT scope for this session."

    # Structured indication gate — preferred over regex-parsed notes
    gate = idata.get("indication_gate")
    if isinstance(gate, dict) and gate.get("status") in _INDICATION_GATE_STATUSES:
        reason = str(gate.get("reason") or "").strip()
        if reason:
            return reason

    # Legacy fallback: detect FTO-relevant language in free-text notes
    notes = str(idata.get("notes") or "").strip()
    if notes and _FTO_GUIDANCE_NOTE_RE.search(notes):
        return notes
    return ""


@lru_cache(maxsize=1)
def _load_mca_config() -> dict:
    """Load mca_config.json once and cache. Returns the full config dict."""
    if not MCA_CONFIG_PATH.exists():
        return {"mcas": []}
    with open(MCA_CONFIG_PATH, "r") as f:
        return json.load(f)


def get_mca_config(mca_id: str) -> dict:
    """Return the config dict for a single MCA, or {} if not found."""
    config = _load_mca_config()
    for mca in config.get("mcas", []):
        if mca.get("id") == mca_id:
            return mca
    return {}


def mca_has_expansion(mca_id: str, expansion: str) -> bool:
    """Return True if the given MCA has selected the specified BLS expansion."""
    return expansion in get_mca_config(mca_id).get("bls_expansions", [])


def _format_patient_dob(dob: date) -> str:
    """Return a compact DOB string matching the PCR header style."""
    return f"{dob.strftime('%b')} {dob.day}, {dob.year}"


def _subtract_months(today: date, months: int) -> date:
    """Subtract calendar months while clamping to the target month's final day."""
    month_index = today.month - 1 - months
    year = today.year + month_index // 12
    month = month_index % 12 + 1
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = (next_month - date.resolution).day
    return date(year, month, min(today.day, last_day))


def _patient_dob_from_relative(text: str, today: date | None = None) -> date | None:
    """Resolve authored relative DOB phrases such as '10 months before today's date'."""
    today = today or date.today()
    value = str(text or "").strip().lower()
    if not value:
        return None
    if value in {"today", "born today"}:
        return today
    month_match = re.search(r"\b(?:about\s+|approximately\s+|approx\.?\s*)?(\d+)\s*months?\b", value)
    if month_match:
        return _subtract_months(today, int(month_match.group(1)))
    day_match = re.search(r"\b(?:about\s+|approximately\s+|approx\.?\s*)?(\d+)\s*days?\b", value)
    if day_match:
        return today - date.resolution * int(day_match.group(1))
    return None


def _patient_dob_from_month_day(patient: dict, today: date | None = None) -> date | None:
    """Resolve authored month/day birthdays using the patient's displayed age."""
    today = today or date.today()
    value = str(patient.get("dob_month_day") or "").strip()
    if not value:
        return None
    match = re.match(r"^([A-Za-z]+\.?)\s+(\d{1,2})$", value)
    if not match:
        return None
    try:
        age = int(patient.get("age"))
        day = int(match.group(2))
    except (TypeError, ValueError):
        return None
    month_name = match.group(1).rstrip(".").lower()
    full_names = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
    abbr_names = {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}
    month = full_names.get(month_name) or abbr_names.get(month_name)
    if not month:
        return None
    birthday_this_year = date(today.year, month, day)
    birth_year = today.year - age - (1 if birthday_this_year > today else 0)
    try:
        return date(birth_year, month, day)
    except ValueError:
        return None


def _patient_dob_from_age(patient: dict, today: date | None = None) -> date | None:
    """Derive a concrete DOB from relative pediatric age fields when available."""
    today = today or date.today()
    try:
        days = patient.get("age_days")
        if days is not None:
            return today - date.resolution * int(days)
    except (TypeError, ValueError):
        pass
    try:
        months = patient.get("age_months")
        if months is not None:
            return _subtract_months(today, int(months))
    except (TypeError, ValueError):
        pass
    return None


def _replace_patient_dob_tags_with_concrete_date(scenario: dict, dob_text: str) -> None:
    """Rewrite public history tags so the client receives a concrete patient DOB."""
    response_map = scenario.get("history_response_map")
    if not isinstance(response_map, dict) or not dob_text:
        return

    dob_tag_re = re.compile(r"\[\[\s*HISTORY:\s*Patient\s+Date\s+of\s+Birth\s*=\s*[^\]]+\]\]", re.I)

    def rewrite(tag: str) -> str:
        return dob_tag_re.sub(f"[[HISTORY: Patient Date of Birth={dob_text}]]", str(tag))

    for entry in response_map.values():
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get("tag"), str):
            entry["tag"] = rewrite(entry["tag"])
        if isinstance(entry.get("tags"), list):
            entry["tags"] = [rewrite(tag) if isinstance(tag, str) else tag for tag in entry["tags"]]


def _insert_concrete_patient_dob(scenario: dict) -> dict:
    """Add runtime DOB fields derived from authored relative DOB metadata."""
    patient = dict(scenario.get("patient") or {})
    dob = _patient_dob_from_relative(patient.get("dob_relative", ""))
    if dob is None:
        dob = _patient_dob_from_month_day(patient)
    if dob is None:
        dob = _patient_dob_from_age(patient)
    if dob is None:
        return scenario

    dob_text = _format_patient_dob(dob)
    patient["dob"] = dob_text
    patient["dob_display"] = dob_text
    scenario["patient"] = patient
    _replace_patient_dob_tags_with_concrete_date(scenario, dob_text)
    return scenario


def list_mcas() -> list[dict]:
    """Return summary list of all configured MCAs for UI selectors."""
    config = _load_mca_config()
    return [
        {
            "id": m["id"],
            "display": m["display"],
            "display_short": m.get("display_short", m["id"]),
            "state": m.get("state", ""),
        }
        for m in config.get("mcas", [])
    ]


def _resolve_protocol(scenario: dict) -> dict:
    """
    Resolve the 'protocol' reference key into a 'protocol_config' dict.
    Mutates and returns the scenario dict.
    Backward-compatible: if only 'protocol_config' is present, leaves it untouched.
    """
    proto_ref = scenario.get("protocol")
    if not proto_ref:
        return scenario  # inline protocol_config or none — nothing to do

    if isinstance(proto_ref, str):
        protocol = dict(get_resolved_protocol(None, proto_ref))
        overrides = {}
    elif isinstance(proto_ref, dict):
        protocol = dict(get_resolved_protocol(None, proto_ref["ref"]))
        overrides = proto_ref.get("overrides", {})
    else:
        return scenario  # unrecognised format — leave as-is

    # Apply scenario-level overrides (shallow merge per top-level key)
    protocol.update(overrides)

    # Promote to protocol_config for all downstream consumers
    scenario["protocol_config"] = protocol
    return scenario


def _find_scenario_path(scenario_id: str) -> Path:
    """Search the scenarios tree recursively for <scenario_id>.json."""
    matches = list(SCENARIOS_DIR.rglob(f"{scenario_id}.json"))
    if not matches:
        raise FileNotFoundError(f"Scenario not found: {scenario_id}")
    return matches[0]


@lru_cache(maxsize=64)
def _load_scenario_cached(scenario_id: str, path_str: str, mtime_ns: int) -> dict:
    path = Path(path_str)
    with open(path, "r") as f:
        scenario = json.load(f)
    scenario = _resolve_protocol(scenario)
    try:
        warnings = validate_scenario(scenario)
    except ScenarioVocabularyError as exc:
        logger.error("scenario.vocabulary_validation_failed", scenario_id=scenario_id, error=str(exc))
        raise
    for w in warnings:
        logger.warning("scenario.vocabulary_label_drift", scenario_id=scenario_id, detail=w)
    return scenario


def load_scenario(scenario_id: str) -> dict:
    path = _find_scenario_path(scenario_id)
    return _load_scenario_cached(scenario_id, str(path), path.stat().st_mtime_ns)


load_scenario.cache_clear = _load_scenario_cached.cache_clear  # type: ignore[attr-defined]


def adapt_scenario_to_context(
    scenario: dict,
    agency: dict,
    mca: str | None = None,
    effective_protocol_excerpt: dict | None = None,
) -> dict:
    """
    Return a shallow-copied scenario with agency/session-specific fields applied.
    The base scenario returned by load_scenario() (lru_cache) is never mutated.

    Parameters
    ----------
    scenario : dict
        Raw scenario from load_scenario().
    agency : dict
        Agency clinical config from load_agency() — may be {} if unconfigured.
    mca : str | None
        Session MCA (e.g. "mi_base"). Used for protocol re-resolution when
        the session MCA differs from the scenario's default.
    """
    adapted = dict(scenario)

    # ── ALS / transport fields from agency config ─────────────────────────────
    if agency:
        service = agency.get("service_type", {})
        als_cfg = agency.get("als_dispatch", {})

        # non_transport_agency: derived from whether the agency transports patients
        adapted["non_transport_agency"] = not service.get("transport", True)

        # ALS co-dispatch is an agency operational policy, not scenario content.
        # The adapted scenario carries it so checklist applicability can suppress
        # "request additional help/ALS" items when ALS was already sent.
        adapted["als_codispatched"] = bool(
            als_cfg.get("auto_dispatched", als_cfg.get("co_dispatched", False))
        )

        # ALS arrival time — agency config wins; fall back to scenario default or 12 min
        if "arrival_minutes" in als_cfg:
            adapted["als_arrival_minutes"] = als_cfg["arrival_minutes"]
        elif "als_arrival_minutes" not in adapted:
            adapted["als_arrival_minutes"] = 12

        # ALS unit name — agency config wins; fall back to scenario default or "ALS"
        if "unit_name" in als_cfg:
            adapted["als_unit_name"] = als_cfg["unit_name"]
        elif "als_unit_name" not in adapted:
            adapted["als_unit_name"] = "ALS"

    # ── Dispatch unit / text placeholder substitution ─────────────────────────
    unit = agency.get("unit_designator", "") if agency else ""
    if unit and "dispatch" in adapted:
        dispatch = dict(adapted["dispatch"])
        if "{unit}" in dispatch.get("unit", ""):
            dispatch["unit"] = unit
        if "{unit}" in dispatch.get("text", ""):
            dispatch["text"] = dispatch["text"].replace("{unit}", unit)
        adapted["dispatch"] = dispatch

    # ── Protocol MCA substitution ─────────────────────────────────────────────
    effective_mca = mca or (agency.get("mca") if agency else None)
    proto_ref = scenario.get("protocol")
    if effective_mca and isinstance(proto_ref, str):
        # Extract the existing MCA segment (first path component)
        parts = proto_ref.split("/", 1)
        if len(parts) == 2 and parts[0] != effective_mca:
            candidate_ref = f"{effective_mca}/{parts[1]}"
            try:
                get_resolved_protocol(None, candidate_ref)
                # File exists — re-resolve with the session MCA protocol
                adapted = dict(adapted)
                adapted["protocol"] = candidate_ref
                adapted.pop("protocol_config", None)
                adapted = _resolve_protocol(adapted)
            except FileNotFoundError:
                pass  # no protocol for this MCA — keep scenario default
    elif isinstance(proto_ref, dict) and effective_mca:
        ref = proto_ref.get("ref", "")
        parts = ref.split("/", 1)
        if len(parts) == 2 and parts[0] != effective_mca:
            candidate_ref = f"{effective_mca}/{parts[1]}"
            try:
                get_resolved_protocol(None, candidate_ref)
                adapted = dict(adapted)
                adapted["protocol"] = {"ref": candidate_ref, "overrides": proto_ref.get("overrides", {})}
                adapted.pop("protocol_config", None)
                adapted = _resolve_protocol(adapted)
            except FileNotFoundError:
                pass

    # ── Pediatric length-based tape reference ────────────────────────────────
    # Patient weight in scenario JSON is authoritative. Compute tape color and
    # measurement data deterministically, with optional state/agency overrides,
    # before the adapted scenario reaches AI prompts or the frontend.
    patient = adapted.get("patient")
    if isinstance(patient, dict):
        tape_ref = patient_tape_reference(patient, agency)
        if tape_ref:
            patient = dict(patient)
            patient["length_based_tape"] = tape_ref
            adapted["patient"] = patient

            response_map = adapted.get("history_response_map")
            tape_sentence = tape_reference_sentence(patient, agency)
            if isinstance(response_map, dict) and tape_sentence:
                updated_map = {}
                for key, entry in response_map.items():
                    if not isinstance(entry, dict):
                        updated_map[key] = entry
                        continue
                    triggers = " ".join(str(t) for t in entry.get("triggers") or []).lower()
                    raw_tags = entry.get("tags") or ([entry["tag"]] if entry.get("tag") else [])
                    tag_text = " ".join(str(t) for t in raw_tags).lower()
                    tape_related = (
                        key == "patient_weight"
                        or "broselow" in triggers
                        or "broslow" in triggers
                        or "patient weight" in tag_text
                    )
                    if tape_related:
                        entry = dict(entry)
                        answer = str(entry.get("answer") or "").strip()
                        if "broselow" not in answer.lower() and "length-based" not in answer.lower():
                            entry["answer"] = f"{answer} {tape_sentence}".strip()
                        tape_tag = f"[[HISTORY: Length-Based Tape = {tape_ref['color']} zone]]"
                        if entry.get("tag"):
                            tags = [entry["tag"]]
                            entry.pop("tag", None)
                            entry["tags"] = tags
                        tags = [
                            str(tag)
                            for tag in entry.get("tags") or []
                            if str(tag).strip()
                        ]
                        if not any("length-based tape" in tag.lower() for tag in tags):
                            tags.append(tape_tag)
                            entry["tags"] = tags
                    updated_map[key] = entry
                adapted["history_response_map"] = updated_map

    # ── MCA expansion scope adaptation ───────────────────────────────────────
    # Interventions tagged with "required_expansion" are only within BLS scope
    # if the session MCA has selected that expansion. If not, flip within_bls_scope
    # to False and add an entry to out_of_scope_bls in protocol_config.
    mca_id = effective_mca or "mi_base"
    mca_cfg = get_mca_config(mca_id)
    expansions = set(mca_cfg.get("bls_expansions", []))
    specialist_expansions = set(mca_cfg.get("specialist_expansions", []))
    adapted["mca_expansions"] = sorted(expansions)
    adapted["mca_specialist_expansions"] = sorted(specialist_expansions)

    interventions = adapted.get("vitals", {}).get("interventions", {})
    if interventions:
        updated_interventions = {}
        out_of_scope_additions = []
        for iid, idata in interventions.items():
            req_exp = idata.get("required_expansion")
            if req_exp and req_exp not in expansions:
                idata = dict(idata)
                idata["within_bls_scope"] = False
                idata["expansion_not_selected"] = True
                idata["expansion_key"] = req_exp
                out_of_scope_additions.append(
                    f"{idata['label']} — not a BLS expansion at this MCA ({mca_id})"
                )
            updated_interventions[iid] = idata

        vitals = dict(adapted.get("vitals", {}))
        vitals["interventions"] = updated_interventions
        adapted["vitals"] = vitals

        if out_of_scope_additions:
            proto_cfg = dict(adapted.get("protocol_config", {}))
            out_of_scope = list(proto_cfg.get("out_of_scope_bls", []))
            existing_labels = {e.split(" —")[0] for e in out_of_scope}
            for entry in out_of_scope_additions:
                label = entry.split(" —")[0]
                if label not in existing_labels:
                    out_of_scope.append(entry)
            proto_cfg["out_of_scope_bls"] = out_of_scope
            adapted["protocol_config"] = proto_cfg

    adapted = _apply_protocol_scope_checklist_overlay(adapted, effective_protocol_excerpt)

    return adapted


def _stable_overlay_slug(value: str) -> str:
    """Return a checklist-safe slug segment for generated protocol-scope item IDs."""
    clean = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or ""))
    clean = "_".join(part for part in clean.split("_") if part)
    return clean[:80] or "rule"


def _protocol_scope_checklist_point_value(sop: dict) -> int:
    """Bound optional SOP scoring weight metadata to a conservative default."""
    meta = sop.get("metadata_json") if isinstance(sop.get("metadata_json"), dict) else {}
    raw = meta.get("scope_point_value", meta.get("point_value", 5))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 5
    return max(1, min(value, 10))


def _protocol_scope_applicable_levels(sop: dict) -> list[str]:
    meta = sop.get("metadata_json") if isinstance(sop.get("metadata_json"), dict) else {}
    raw = meta.get("applicable_levels") or meta.get("restricted_provider_levels") or []
    if not isinstance(raw, list):
        return []
    allowed = {"MFR", "EMR", "EMT", "EMT-B", "BLS", "AEMT", "PARAMEDIC", "ALS"}
    return [str(level) for level in raw if str(level).upper() in allowed]


def _apply_protocol_scope_checklist_overlay(
    adapted: dict,
    effective_protocol_excerpt: dict | None,
) -> dict:
    """Add deterministic checklist items for active SOP scoring rules.

    Phase 2B scoring authority uses the normal checklist path. Generated
    absence-check items are satisfied when the restricted/contraindicated/
    unavailable intervention is not performed and are missed when it appears
    in the intervention table.
    """
    if not isinstance(effective_protocol_excerpt, dict) or not effective_protocol_excerpt.get("authoritative"):
        return adapted

    sops = effective_protocol_excerpt.get("sops") or []
    if not isinstance(sops, list) or not sops:
        return adapted

    interventions = (adapted.get("vitals") or {}).get("interventions") or {}
    if not isinstance(interventions, dict) or not interventions:
        return adapted

    overlay_items: list[dict] = []
    existing_ids = {str(item.get("id")) for item in adapted.get("checklist", []) if isinstance(item, dict)}

    for sop in sops:
        if not isinstance(sop, dict):
            continue
        rule_type = sop.get("rule_type")
        if rule_type not in {"scope_restriction", "contraindication", "not_carried"}:
            continue
        sop_action_ids = {str(action_id) for action_id in (sop.get("intervention_action_ids") or [])}
        if not sop_action_ids:
            continue
        sop_slug = _stable_overlay_slug(sop.get("id") or sop.get("title") or "sop")
        point_value = _protocol_scope_checklist_point_value(sop)
        applicable_levels = _protocol_scope_applicable_levels(sop)
        is_contraindication = rule_type == "contraindication"
        is_not_carried = rule_type == "not_carried"
        if is_contraindication:
            default_rule_text = "Active agency SOP marks this intervention contraindicated."
        elif is_not_carried:
            default_rule_text = "Active agency SOP marks this intervention unavailable or not carried."
        else:
            default_rule_text = "Active agency SOP restricts this intervention."
        rule_text = sop.get("rule_text") or default_rule_text
        for intervention_id, idata in interventions.items():
            action_ids = set(action_ids_for_intervention(intervention_id))
            if not action_ids.intersection(sop_action_ids):
                continue
            item_id = f"protocol_scope.{sop_slug}.{_stable_overlay_slug(intervention_id)}"
            if item_id in existing_ids:
                continue
            label = idata.get("label") if isinstance(idata, dict) else None
            label = label or intervention_id
            category = "protocols_treatment" if (is_contraindication or is_not_carried) else "scope_adherence"
            if is_contraindication:
                item_prefix = "Avoid contraindicated intervention"
            elif is_not_carried:
                item_prefix = "Avoid unavailable/not-carried intervention"
            else:
                item_prefix = "Avoid restricted intervention"
            overlay_items.append({
                "id": item_id,
                "description": f"{item_prefix}: {label} — {rule_text}",
                "subtype": "intervention",
                "category": category,
                "provenance": "protocol_scope",
                "point_value": point_value,
                "required": "required",
                "applicable_levels": applicable_levels,
                "allowed_tiers": [1],
                "preferred_tier": 1,
                "tier3_permitted": False,
                "tier1_match": {
                    "source": "absence_check",
                    "absence_intervention_key": intervention_id,
                },
                "tier2_patterns": [],
            })
            existing_ids.add(item_id)

    if not overlay_items:
        return adapted

    adapted = dict(adapted)
    adapted["checklist"] = list(adapted.get("checklist") or []) + overlay_items
    adapted["protocol_scope_checklist_overlay"] = {
        "source": "effective_protocol_excerpt_v1",
        "item_count": len(overlay_items),
        "active_sop_ids": effective_protocol_excerpt.get("sop_ids") or [],
    }
    return adapted



_scenario_list_cache: list[dict] | None = None


def list_scenarios() -> list[dict]:
    global _scenario_list_cache
    if _scenario_list_cache is not None:
        return _scenario_list_cache
    scenarios = []
    for path in sorted(SCENARIOS_DIR.rglob("*.json")):
        with open(path, "r") as f:
            data = json.load(f)
        scenarios.append({
            "id": data["id"],
            "title": data["title"],
            "display_title": data.get("display_title", data["title"]),
            "subtitle": data.get("subtitle", ""),
            "difficulty": data.get("difficulty", ""),
            "version": data.get("version", "1.0"),
            "category": data.get("category", "general"),
            "category_display": data.get("category_display", "General"),
            "scenario_number": data.get("scenario_number", 999),
            "prerequisites": data.get("prerequisites", []),
        })
    scenarios.sort(key=lambda s: s["scenario_number"])
    _scenario_list_cache = scenarios
    return _scenario_list_cache


def _public_history_response_map(scenario: dict) -> dict:
    """Return client-safe response-map triggers/tags used for deterministic PCR capture."""
    response_map = scenario.get("history_response_map")
    if not isinstance(response_map, dict):
        return {}

    public_map = {}
    for key, entry in response_map.items():
        if not isinstance(entry, dict):
            continue
        tags = entry.get("tags") or ([entry["tag"]] if entry.get("tag") else [])
        tags = [
            tag for tag in tags
            if isinstance(tag, str) and tag.strip().upper().startswith(("[[HISTORY:", "[[EXAM:"))
        ]
        if not tags:
            continue
        public_map[key] = {
            "label": entry.get("label") or key,
            "triggers": entry.get("triggers", []),
            "speaker": entry.get("speaker"),
            "answer": entry.get("answer"),
            "tags": tags,
        }
    return public_map


def _public_personas(scenario: dict) -> dict:
    """Return client-safe speaker metadata without hidden roleplay instructions."""
    personas = scenario.get("personas")
    if not isinstance(personas, dict):
        return {}
    public: dict[str, dict] = {}
    allowed = {"name", "role", "relation", "sex", "gender", "age", "aliases", "tts"}
    for key, persona in personas.items():
        if not isinstance(persona, dict):
            continue
        safe = {field: persona[field] for field in allowed if field in persona}
        if safe.get("tts") and isinstance(safe["tts"], dict):
            tts_allowed = {
                "enabled",
                "voice_role",
                "gender",
                "age_band",
                "provider_voice",
                "demeanor",
                "delivery",
                "avoid",
                "speed",
            }
            safe["tts"] = {field: safe["tts"][field] for field in tts_allowed if field in safe["tts"]}
        public[key] = safe
    return public


def get_public_scenario_data(scenario: dict) -> dict:
    """Returns only the data the frontend should display (no answers/debrief)."""
    scenario = _insert_concrete_patient_dob(dict(scenario))
    demographics_deferred = scenario["patient"].get("pcr_demographics_deferred", False)
    chat_address_hint = scenario.get("chat_address_hint", "")
    if demographics_deferred:
        chat_address_hint = "Address by role: patient · caregiver/parent · Alex (partner/vitals)"
    return {
        "id": scenario["id"],
        "title": scenario["title"],
        "display_title": scenario.get("display_title", scenario["title"]),
        "subtitle": scenario.get("subtitle", ""),
        "category": scenario.get("category", ""),
        "category_display": scenario.get("category_display", ""),
        "objectives": scenario.get("objectives", []),
        "dispatch": scenario["dispatch"],
        "scene": {
            "description": scenario["scene"]["description"],
            "image": scenario["scene"].get("image"),
            "video": scenario["scene"].get("video"),
            "hazards": scenario["scene"].get("hazards", []),
            "bystanders": scenario["scene"].get("bystanders", []),
        },
        "patient": {
            "name": scenario["patient"]["name"],
            "age": scenario["patient"]["age"],
            "age_days": scenario["patient"].get("age_days"),
            "age_months": scenario["patient"].get("age_months"),
            "dob": scenario["patient"].get("dob"),
            "dob_display": scenario["patient"].get("dob_display"),
            "dob_relative": scenario["patient"].get("dob_relative"),
            "sex": scenario["patient"].get("sex", ""),
            "age_display": scenario["patient"].get(
                "age_display",
                f"{scenario['patient']['age']}-year-old {scenario['patient']['sex']}",
            ),
            "weight_display": scenario["patient"]["weight_display"],
            "length_based_tape": scenario["patient"].get("length_based_tape"),
            "pcr_demographics_deferred": scenario["patient"].get("pcr_demographics_deferred", False),
            "chief_complaint": scenario["patient"]["chief_complaint"],
            "general_impression": scenario["patient"]["general_impression"],
            "image": scenario["patient"].get("image"),
            "video": scenario["patient"].get("video"),
            "pat": scenario["patient"].get("pat"),
            "gcs_assessment": scenario["patient"].get("gcs_assessment"),
            "avpu_assessment": scenario["patient"].get("avpu_assessment"),
            "airway_assessment": scenario["patient"].get("airway_assessment"),
        },
        "history": scenario["history"],
        "vitals": {
            "baseline": scenario["vitals"]["baseline"],
        },
        "vitals_baseline_labels": {
            k: {"label": v["label"], "unit": v.get("unit", "")}
            for k, v in scenario["vitals"]["baseline"].items()
        },
        "available_interventions": [
            {
                "id": iid,
                "label": idata["label"],
                "within_bls_scope": idata.get("within_bls_scope", True),
                "unavailable": idata.get("unavailable_in_scenario", False),
                "unavailable_reason": idata.get("unavailable_reason", ""),
                "requires_popup": idata.get("requires_popup", False),
                "popup_type": idata.get("popup_type"),
                "popup_default": idata.get("popup_default", {}),
                "popup_config": idata.get("popup_config", {}),
                "detection_patterns": idata.get("detection_patterns", []),
                "required_expansion": idata.get("required_expansion"),
                "expansion_not_selected": idata.get("expansion_not_selected", False),
                "fto_guidance": _public_intervention_fto_guidance(idata),
                # indication_gate is passed through so the frontend and future engine
                # logic can inspect allowed_when conditions without another API change.
                # scoring deduction and auto-blocking are deferred pending clinical state tracking.
                "indication_gate": idata.get("indication_gate") or None,
            }
            for iid, idata in scenario["vitals"]["interventions"].items()
        ],
        "als_arrival_minutes": scenario.get("als_arrival_minutes", 12),
        "als_unit_name": scenario.get("als_unit_name", "ALS"),
        "non_transport_agency": scenario.get("non_transport_agency", False),
        "readiness_criteria": scenario.get("readiness_criteria", {}),
        "history_response_map": _public_history_response_map(scenario),
        "personas": _public_personas(scenario),
        "chat_placeholder": scenario.get("chat_placeholder", ""),
        "chat_address_hint": chat_address_hint,
        "lexi_hints": [dict(hint) for hint in IN_SCENARIO_LEXI_HINTS],
        "protocol_config": scenario.get("protocol_config", {}),
        "cpr_challenge": scenario.get("cpr_challenge", {}),
        "lung_sound_challenge": scenario.get("lung_sound_challenge", {}),
        "mca_expansions": scenario.get("mca_expansions", []),
        "mca_specialist_expansions": scenario.get("mca_specialist_expansions", []),
        "is_orientation": scenario.get("is_orientation", False),
        "orientation_guidance": scenario.get("orientation_guidance", []),
        "impression_challenge": scenario.get("impression_challenge", {}),
    }
