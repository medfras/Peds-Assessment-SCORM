"""
Rubric item smoke tests — validates that every authored checklist item with a
Tier 1 match spec can actually be satisfied by synthetic evidence that matches
its configuration.

Catches before a scenario is ever run:
  - tier1_match with a pattern that never matches the expected key/value
  - require_source=True with no eligible_sources specified (can never satisfy)
  - tier1_alternatives silently dropped from "any" items with multiple specs
  - allowed_tiers=[1] with no tier1_match / tier1_matches (item can never score)
  - eligible_sources that don't resolve to a source the engine accepts

Items with only Tier 2 paths are not tested here -- those are covered by
test_tier2_matchers.py which validates positive/negative samples per item.

Source types covered:
  "finding"                -- synthetic SessionFinding
  "post_intervention_finding" -- synthetic finding + prior intervention
  "intervention"           -- synthetic Intervention record
  "absence_check"          -- empty intervention list (item satisfied by absence)
  "no_out_of_scope_actions" -- empty intervention list
  "session_event"          -- synthetic SessionEvent
  "scene_entry"            -- synthetic scene_entry dict

Not yet covered (structural -- adjudication logic is correct):
  Call-type rubric items (tested via test_rubric_loader.py and test_scoring_service.py)
"""
from __future__ import annotations

import json
import re
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# ── Import only what's needed to stay lightweight ────────────────────────────

from app.checklist import ChecklistItem, TierOneMatchSpec
from app.scoring_service import _try_tier1_spec

# ── Helpers ───────────────────────────────────────────────────────────────────

_SCENARIO_DIR = Path(__file__).parent.parent / "app" / "scenarios"
_T0 = datetime(2026, 1, 1, 12, 0, 0)


def _extract_literal(pattern: str) -> str:
    """
    Extract a string guaranteed to match the regex pattern by stripping
    metacharacters and trying each alternative (plus pairwise joins for
    optional-prefix patterns like '^(?:patient\s+|pt\s+)?name$').
    Returns empty string when no candidate matches — caller skips the test.
    """
    p = re.sub(r"\(\?[a-zA-Z]+\)", "", pattern)        # remove (?i), (?m) …
    p = p.replace("\\b", " ").replace("\\s", " ")
    p = p.replace("^", "").replace("$", "")
    p = re.sub(r"[().*+?\[\]\\:]", "", p)
    candidates = [a.strip() for a in re.split(r"\|", p) if a.strip()]
    # add pairwise joins to handle optional-prefix patterns
    for i in range(len(candidates)):
        for j in range(i + 1, min(i + 3, len(candidates) + 1)):
            candidates.append(" ".join(candidates[i:j]))
    for cand in candidates:
        cand = re.sub(r"\s+", " ", cand).strip()
        if cand and re.search(pattern, cand, re.IGNORECASE):
            return cand
    return ""


def _extract_event_key(pattern: str) -> str:
    """
    Extract an event_key string from an event_key_pattern.
    Colons are preserved (event keys like "cpr:scenario_id" use them as separators).
    For patterns ending with ':' (open prefix like '^impression:'), appends a suffix.
    """
    p = re.sub(r"\(\?[a-zA-Z]+\)", "", pattern)
    p = p.replace("^", "").replace("$", "").replace("\\b", "").replace("\\s", "")
    # Strip only true metacharacters, keeping colons and alphanumeric content
    p = re.sub(r"[().*+?\[\]\\]", "", p)
    cand = p.strip()
    # If the candidate ends with ':', it's an open prefix — append a stub suffix
    if cand.endswith(":"):
        cand = cand + "stub"
    if cand and re.search(pattern, cand, re.IGNORECASE):
        return cand
    # Fallback: try each alternative
    for alt in re.split(r"\|", cand):
        alt = alt.strip()
        if alt.endswith(":"):
            alt = alt + "stub"
        if alt and re.search(pattern, alt, re.IGNORECASE):
            return alt
    return ""


def _finding(finding_type: str, key: str, value: str, source: str | None, offset_s: int = 10):
    return types.SimpleNamespace(
        id=f"smoke_finding_{offset_s}",
        finding_type=finding_type,
        key=key,
        value=value,
        source=source,
        captured_at=_T0 + timedelta(seconds=offset_s),
    )


def _intervention(name: str, offset_s: int = 5):
    return types.SimpleNamespace(
        id=f"smoke_intv_{name}",
        name=name,
        applied_at=_T0 + timedelta(seconds=offset_s),
    )


def _event(event_type: str, event_key: str = "", event_data: dict | None = None):
    return types.SimpleNamespace(
        id="smoke_event",
        event_type=event_type,
        event_key=event_key,
        event_data=event_data or {},       # engine reads event_data, not data
        occurred_at=_T0 + timedelta(seconds=10),
    )


def _blank_scenario():
    return {
        "vitals": {"interventions": {}},
        "out_of_scope_actions": [],
    }


def _build_session_args(spec: TierOneMatchSpec, scenario: dict):
    """
    Build minimal (interventions, findings, events, scene_entry) that satisfy spec.
    Returns None for source types not yet supported by this harness.
    """
    src = spec.source
    eligible = spec.eligible_sources or []
    chosen_source = eligible[0] if eligible else None

    if src == "absence_check":
        # Satisfied by empty intervention list
        return [], [], [], None

    if src == "no_out_of_scope_actions":
        # Satisfied when scenario has no out_of_scope interventions attempted
        return [], [], [], None

    if src in ("finding", "post_intervention_finding"):
        ft = spec.finding_type or "vital"
        key_pat = spec.finding_key_pattern or ""
        val_pat = spec.finding_value_pattern or ""
        key = _extract_literal(key_pat) if key_pat else "test_key"
        val = _extract_literal(val_pat) if val_pat else "test_value"
        if not key:
            return None  # pattern too complex — skip
        f = _finding(ft, key, val, chosen_source, offset_s=20)
        if src == "post_intervention_finding":
            # The finding must be captured after at least one intervention
            dummy_intv = _intervention("dummy_o2", offset_s=5)
            return [dummy_intv], [f], [], None
        return [], [f], [], None

    if src == "intervention":
        key = spec.intervention_key
        if not key and spec.intervention_keys:
            key = spec.intervention_keys[0]
        if not key:
            return None
        return [_intervention(key)], [], [], None

    if src == "session_event":
        et = spec.event_type or "unknown_event"
        ek_pat = spec.event_key_pattern or ""
        if ek_pat:
            # Use a colon-preserving extraction for event keys (e.g. "cpr:...", "impression:")
            ek = _extract_event_key(ek_pat)
        else:
            ek = ""
        ev_data = {}
        if spec.event_data_result:
            ev_data["result"] = spec.event_data_result
        return [], [], [_event(et, ek, ev_data)], None

    if src == "scene_entry":
        path = spec.scene_entry_path or ""
        se: dict = {}
        # Build nested dict from dot-separated path with truthy leaf
        parts = path.split(".")
        node = se
        for part in parts[:-1]:
            node[part] = {}
            node = node[part]
        if parts:
            node[parts[-1]] = True
        return [], [], [], se

    return None  # unsupported source type


# ── Collect test cases from all scenario JSON files ──────────────────────────

def _iter_tier1_specs():
    """
    Yield (scenario_id, item_id, label, spec_dict) for every Tier 1 spec
    that is explicitly configured on a scenario-authored checklist item.
    Covers tier1_match, tier1_alternatives, and tier1_matches (all-logic).
    Shared base items (ems.medical.*, ems.trauma.*) are tested via their
    direct unit tests in test_scoring_service.py.
    """
    for path in sorted(_SCENARIO_DIR.rglob("*.json")):
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        scenario_id = data.get("id") or path.stem
        # Only scenario-authored items (not shared base items injected at runtime)
        for item in data.get("checklist", []):
            item_id = item.get("id", "")
            # skip shared base items — they're tested elsewhere
            if item_id.startswith("ems.medical.") or item_id.startswith("ems.trauma."):
                continue

            if item.get("tier1_match"):
                yield scenario_id, item_id, "tier1_match", item["tier1_match"]

            for i, spec in enumerate(item.get("tier1_alternatives", [])):
                yield scenario_id, item_id, f"tier1_alternatives[{i}]", spec

            for i, spec in enumerate(item.get("tier1_matches", [])):
                yield scenario_id, item_id, f"tier1_matches[{i}]", spec


_ALL_TIER1_SPECS = list(_iter_tier1_specs())


def _idfn(val):
    if isinstance(val, str):
        return val
    return ""


@pytest.mark.parametrize(
    "scenario_id,item_id,label,spec_dict",
    _ALL_TIER1_SPECS,
    ids=[f"{s}.{i}::{l}" for s, i, l, _ in _ALL_TIER1_SPECS],
)
def test_tier1_spec_satisfied_by_synthetic_evidence(scenario_id, item_id, label, spec_dict):
    """
    Each Tier 1 spec in each authored checklist item must be satisfiable
    by the minimal synthetic evidence implied by its own configuration.

    A failure here means the item is misconfigured and will NEVER score
    even when the student performs the expected action.
    """
    spec = TierOneMatchSpec(**spec_dict)
    scenario = _blank_scenario()

    args = _build_session_args(spec, scenario)
    if args is None:
        pytest.skip(f"{item_id} {label}: source type '{spec.source}' not yet covered by harness")

    interventions, findings, events, scene_entry = args

    result = _try_tier1_spec(
        spec,
        interventions=interventions,
        findings=findings,
        events=events,
        scene_entry=scene_entry,
        scenario=scenario,
        chat_messages=[],
        provider_level="EMT",
    )

    assert result is not None, (
        f"{scenario_id} / {item_id} / {label}: _try_tier1_spec returned None — "
        f"spec={spec_dict!r}. "
        f"The item is misconfigured: synthetic evidence built from the spec itself "
        f"did not satisfy the match. Check finding_key_pattern, finding_type, "
        f"eligible_sources, require_source, and intervention_key."
    )


# ── Configuration validation — items that can never score ────────────────────

def _iter_deadend_items():
    """
    Yield (scenario_id, item_id, reason) for items configured with
    allowed_tiers=[1] but no Tier 1 path — these can never score.
    """
    for path in sorted(_SCENARIO_DIR.rglob("*.json")):
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        scenario_id = data.get("id") or path.stem
        for item in data.get("checklist", []):
            item_id = item.get("id", "")
            if item_id.startswith("ems.medical.") or item_id.startswith("ems.trauma."):
                continue
            tiers = item.get("allowed_tiers", [1, 2])
            if tiers == [1]:
                has_t1 = bool(
                    item.get("tier1_match")
                    or item.get("tier1_matches")
                    or item.get("tier1_alternatives")
                )
                if not has_t1:
                    yield scenario_id, item_id, "allowed_tiers=[1] but no tier1_match/tier1_matches"


_DEAD_END_ITEMS = list(_iter_deadend_items())


@pytest.mark.parametrize(
    "scenario_id,item_id,reason",
    _DEAD_END_ITEMS,
    ids=[f"{s}.{i}" for s, i, _ in _DEAD_END_ITEMS],
)
def test_tier1_only_items_have_a_tier1_path(scenario_id, item_id, reason):
    """
    Items with allowed_tiers=[1] must have at least one Tier 1 spec.
    Without one, the item is unreachable and will always score as missed.
    """
    pytest.fail(
        f"{scenario_id} / {item_id}: {reason}. "
        f"Either add a tier1_match, or change allowed_tiers to include Tier 2."
    )
