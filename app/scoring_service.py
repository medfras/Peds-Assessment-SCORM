"""
Scoring engine — Phase 4–6 adjudication and score arithmetic.

Architecture: §4, §5, §7, §10, §11, §12, §18 of SCORING_ENGINE_ARCHITECTURE.md.

Adjudication and score computation run here, before any AI prompt is constructed.
ai_client.py consumes the persisted output — it never originates it.

Phase 6 separated extraction calls (_run_documentation_extraction,
_run_professionalism_review) live in ai_client.py and override the legacy_ai
placeholder scores post-call. This module provides the Tier 3 infrastructure
stub (verify_tier3_model_capability, _try_tier3) and routes tier3_permitted
items to "ambiguous" when the model is unverified. Full async Tier 3 is Phase 7+.

Non-goals for this module:
  - No direct AI calls (verify_tier3_model_capability tests capability only)
  - No prompt construction
  - No HTTP layer
  - No business logic outside adjudication and score computation
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models import AdjudicationRevision
from app.checklist import (
    CategoryScore,
    ChecklistItem,
    ChecklistItemState,
    EffectiveContext,
    EvidenceReference,
    get_base_rubric_version,
    load_checklist,
)
from app.scenarios.vocabulary import OUT_OF_SCOPE
from app.rubric_loader import (
    load_call_type_rubric,
    log_shadow_rubric,
    compose_shadow_checklist,
    compose_active_checklist,
    load_scenario_overlay,
)

log = logging.getLogger(__name__)

PACKET_SCHEMA_VERSION = "1.1"

# Default legacy-AI category set used when a scenario does not declare
# legacy_ai_categories.  Matches historical EMS scoring behaviour.
_DEFAULT_LEGACY_AI_CATEGORIES: frozenset[str] = frozenset({"documentation", "professionalism"})

_SCOPE_ACTION_VERBS = (
    r"administer",
    r"give",
    r"start",
    r"establish",
    r"place",
    r"insert",
    r"perform",
    r"attempt",
    r"prepare",
    r"draw\s*up",
    r"push",
    r"inject",
    r"hang",
    r"suspend",
    r"program",
    r"adjust",
    r"turn\s*off",
    r"remove",
)

_INAPPROPRIATE_ATTEMPT_EVENT_KEY = "inappropriate_intervention_attempted"
_INAPPROPRIATE_ATTEMPT_CATEGORIES = {
    "clinical_performance",
    "protocols_treatment",
    "scope_adherence",
    "professionalism",
}

_OUT_OF_SCOPE_ALIASES: dict[str, list[str]] = {
    "iv_io_access": [r"iv", r"i\.v\.", r"io", r"i\.o\.", r"intravenous", r"intraosseous", r"iv\s+access", r"io\s+access", r"line"],
    "iv_io_access_als_only": [r"iv", r"i\.v\.", r"io", r"i\.o\.", r"intravenous", r"intraosseous", r"iv\s+access", r"io\s+access", r"line"],
    "dextrose_iv_io": [r"dextrose", r"d10", r"d50", r"iv\s+sugar", r"glucose\s+iv"],
    "glucagon_im_in": [r"glucagon", r"glucagen", r"gluca\s*gen"],
    "insulin_pump": [r"insulin\s+pump", r"omnipod", r"pump"],
    "racepinephrine_als": [r"racepinephrine", r"racemic\s+epi", r"racemic\s+epinephrine"],
    "epinephrine_nebulized_als": [r"nebulized\s+epi", r"nebulized\s+epinephrine", r"epi\s+neb"],
    "advanced_airway_als": [r"advanced\s+airway", r"ett", r"lma", r"intubat"],
    "advanced_airway_als_only": [r"advanced\s+airway", r"ett", r"lma", r"intubat"],
    "endotracheal_intubation": [r"intubat", r"ett", r"endotracheal"],
    "direct_laryngoscopy": [r"laryngoscopy", r"magill"],
    "chest_decompression": [r"needle\s+decompression", r"chest\s+decompression"],
}


def _get_legacy_ai_categories(scenario: dict) -> frozenset[str]:
    """
    Return the set of categories that remain method='legacy_ai' for this scenario.

    Reads scenario["legacy_ai_categories"] when present.  Falls back to the
    historical EMS default so existing scenarios without the field continue to
    work unmodified.

    New-domain scenarios that want all categories deterministic from day one
    should set legacy_ai_categories: [] in their JSON.
    """
    declared = scenario.get("legacy_ai_categories")
    if declared is None:
        return _DEFAULT_LEGACY_AI_CATEGORIES
    return frozenset(declared)


# ── Tier 3 infrastructure ─────────────────────────────────────────────────────
# Full Tier 3 (logprob-based AI adjudication) requires adjudicate() to be async.
# This stub provides the gate flag and the hook that adjudicate() calls.
# When tier3_permitted=True and the model is unverified, items route to "ambiguous"
# (not-credited, no deduction) rather than not_satisfied.

_tier3_model_verified: bool = False


async def verify_tier3_model_capability() -> bool:
    """Test logprob availability on the configured Tier 3 model at startup.

    Sets the module-level _tier3_model_verified flag.  Items with
    tier3_permitted=True default to 'ambiguous' until this passes.
    """
    global _tier3_model_verified
    try:
        from app.ai_client import client as _ai_client  # noqa: PLC0415
        from app.config import settings as _settings    # noqa: PLC0415
        result = await _ai_client.chat.completions.create(
            model=_settings.groq_tier3_model,
            messages=[{"role": "user", "content": "test"}],
            max_tokens=1,
            logprobs=True,
            top_logprobs=1,
        )
        choice = result.choices[0]
        has_logprobs = (
            hasattr(choice, "logprobs")
            and choice.logprobs is not None
            and getattr(choice.logprobs, "content", None) is not None
        )
        _tier3_model_verified = has_logprobs
    except Exception as exc:
        log.warning(
            "Tier 3 model capability check failed (%s: %s) — Tier 3 adjudication disabled",
            type(exc).__name__, exc,
        )
        _tier3_model_verified = False
    return _tier3_model_verified


def _try_tier3(item: "ChecklistItem", transcript: str) -> "EvidenceReference | None":
    """Tier 3 AI adjudication stub — §12.

    Returns None until verify_tier3_model_capability() confirms logprob support.
    Full async implementation is Phase 7+; requires adjudicate() to become async.
    When verified, still returns None (triggers ambiguous) until the call is wired.
    """
    if not _tier3_model_verified:
        return None
    # Full implementation deferred: sync adjudicate() cannot make async logprob calls.
    return None


# ── Adjudicated packet ────────────────────────────────────────────────────────


@dataclass
class AdjudicatedPacket:
    """
    Immutable output of one adjudication run.

    AdjudicationSnapshot (item_states + evidence) is always the source of truth.
    score_snapshot is derived from it by compute_scores() and is never authored
    independently.
    """

    item_states: list[ChecklistItemState]
    score_snapshot: dict[str, CategoryScore]
    effective_context: EffectiveContext
    effective_checklist: list[ChecklistItem]
    adjudication_input_hash: str
    adjudicated_at: str                          # ISO-8601
    critical_failure: dict[str, Any] | None = None
    packet_schema_version: str = PACKET_SCHEMA_VERSION

    def to_score_snapshot_jsonb(self) -> dict:
        """Serializable dict for session.score_snapshot column."""
        return {
            "packet_schema_version": self.packet_schema_version,
            "adjudicated_at": self.adjudicated_at,
            "adjudication_input_hash": self.adjudication_input_hash,
            "critical_failure": self.critical_failure,
            "categories": {
                cat: score.model_dump()
                for cat, score in self.score_snapshot.items()
            },
        }

    def to_checklist_states_jsonb(self) -> dict:
        """Serializable dict for session.checklist_states column."""
        return {
            "packet_schema_version": self.packet_schema_version,
            "adjudicated_at": self.adjudicated_at,
            "checklist_definitions": [i.model_dump() for i in self.effective_checklist],
            "item_states": [s.model_dump() for s in self.item_states],
        }

    def to_evidence_references_jsonb(self) -> dict:
        """Serializable dict for session.evidence_references column."""
        refs: dict[str, list[dict]] = {}
        for state in self.item_states:
            if state.evidence_references:
                refs[state.item_id] = [r.model_dump() for r in state.evidence_references]
        return {
            "packet_schema_version": self.packet_schema_version,
            "adjudicated_at": self.adjudicated_at,
            "references": refs,
        }


# ── Context resolution ────────────────────────────────────────────────────────


def resolve_context(session, scenario: dict) -> EffectiveContext:
    """Resolve session context — §5."""
    return EffectiveContext(
        session_id=session.id,
        provider_level=session.provider_level or "EMT",
        agency_id=session.agency_id,
        mca=session.mca or "mi_base",
        resolved_at=datetime.now(timezone.utc).isoformat(),
        base_patient_care_rubric=scenario.get("base_patient_care_rubric"),
        base_patient_care_rubric_version=get_base_rubric_version(scenario),
    )


# ── Scope guardrails ──────────────────────────────────────────────────────────

def _intervention_in_scope(idata: dict, level: str) -> bool:
    """Return whether a scenario intervention is authorized at provider level."""
    lvl = (level or "EMT").upper()
    if lvl in ("PARAMEDIC", "ALS"):
        return True
    if lvl == "AEMT":
        return idata.get("within_aemt_scope", idata.get("within_bls_scope", True))
    if lvl in ("EMT", "EMT-B", "BLS"):
        return idata.get("within_bls_scope", True)
    if lvl in ("MFR", "EMR"):
        return idata.get("within_mfr_scope", idata.get("within_bls_scope", True))
    return True


def _out_of_scope_entries_for_level(scenario: dict, level: str) -> list[str]:
    correct = scenario.get("correct_treatment") or {}
    lvl = (level or "EMT").upper()
    if lvl in ("PARAMEDIC", "ALS"):
        entries = list(correct.get("out_of_scope_paramedic") or [])
    elif lvl == "AEMT":
        entries = list(correct.get("out_of_scope_aemt") or correct.get("out_of_scope_bls") or [])
    else:
        entries = list(correct.get("out_of_scope_bls") or [])

    interventions_data = (scenario.get("vitals") or {}).get("interventions") or {}
    for intervention_id, idata in interventions_data.items():
        if not _intervention_in_scope(idata, level):
            entries.append(intervention_id)
    return entries


def _scope_entry_aliases(entry: str, scenario: dict) -> list[str]:
    text = str(entry or "").strip()
    aliases = list(_OUT_OF_SCOPE_ALIASES.get(text, []))
    interventions_data = (scenario.get("vitals") or {}).get("interventions") or {}
    if text in interventions_data:
        aliases.append(re.escape(text.replace("_", " ")))
        label = str((interventions_data.get(text) or {}).get("label") or "")
        if label:
            aliases.append(re.escape(label))
    label = OUT_OF_SCOPE.get(text)
    if label:
        aliases.append(re.escape(label))
    if text and not aliases:
        aliases.append(re.escape(text.replace("_", " ")))
    return aliases


def _student_attempted_scope_entry(message: str, aliases: list[str]) -> bool:
    if not message or not aliases:
        return False
    verbs = "|".join(_SCOPE_ACTION_VERBS)
    alias_group = "|".join(f"(?:{alias})" for alias in aliases if alias)
    if not alias_group:
        return False
    before = rf"\b(?:{verbs})\b[\w\s'/-]{{0,60}}\b(?:{alias_group})\b"
    after = rf"\b(?:{alias_group})\b[\w\s'/-]{{0,60}}\b(?:{verbs})\b"
    return bool(re.search(before, message, re.IGNORECASE) or re.search(after, message, re.IGNORECASE))


def _has_out_of_scope_action_attempt(
    interventions: list,
    chat_messages: list,
    scenario: dict,
    provider_level: str,
) -> bool:
    interventions_data = (scenario.get("vitals") or {}).get("interventions") or {}
    for intervention in interventions:
        intervention_id = getattr(intervention, "name", "")
        idata = interventions_data.get(intervention_id) or {}
        if idata and not _intervention_in_scope(idata, provider_level):
            return True

    entries = _out_of_scope_entries_for_level(scenario, provider_level)
    aliases_by_entry = [_scope_entry_aliases(entry, scenario) for entry in entries]
    for msg in chat_messages:
        if getattr(msg, "role", None) != "user":
            continue
        content = getattr(msg, "content", "") or ""
        if any(_student_attempted_scope_entry(content, aliases) for aliases in aliases_by_entry):
            return True
    return False


def _slug_for_synthetic_item(value: str, fallback: str = "attempt") -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return (slug or fallback)[:80]


def _synthetic_inappropriate_attempt_penalties(events: list) -> tuple[list[ChecklistItem], list[ChecklistItemState]]:
    """Create deterministic negative-only checklist rows for FTO-blocked attempts.

    These events are emitted by the runtime when a learner attempts an unsafe,
    out-of-scope, contraindicated, or clinically inappropriate action. They are
    not scenario-authored checklist items because the rule is universal: if the
    FTO has to block an attempted intervention for safety/scope/protocol reasons,
    the debrief should show it and deduct in the most relevant scoring bucket.
    """
    items: list[ChecklistItem] = []
    states: list[ChecklistItemState] = []
    seen: set[tuple[str, str, str]] = set()

    for event in events:
        if getattr(event, "event_type", None) != "clinical_decision":
            continue
        if getattr(event, "event_key", None) != _INAPPROPRIATE_ATTEMPT_EVENT_KEY:
            continue
        data = getattr(event, "event_data", None) or {}
        if not isinstance(data, dict):
            data = {}

        category = str(data.get("category") or "clinical_performance")
        if category not in _INAPPROPRIATE_ATTEMPT_CATEGORIES:
            category = "clinical_performance"
        attempt_type = str(data.get("attempt_type") or "inappropriate_intervention")
        label = str(data.get("label") or "Inappropriate intervention attempted").strip()
        reason = str(data.get("reason") or "The action was blocked by FTO guidance as inappropriate for this patient.").strip()
        try:
            points = int(data.get("penalty_points") or 3)
        except (TypeError, ValueError):
            points = 3
        points = max(1, min(points, 6))

        dedupe_key = (category, attempt_type, label.lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        item_id = (
            "runtime.inappropriate_attempt."
            f"{_slug_for_synthetic_item(category)}."
            f"{_slug_for_synthetic_item(attempt_type)}."
            f"{_slug_for_synthetic_item(label)}"
        )
        description = f"Unsafe/inappropriate action attempted — {label}"
        items.append(ChecklistItem(
            id=item_id,
            description=description,
            subtype="intervention",
            category=category,
            provenance="universal_base",
            point_value=points,
            required="required",
            allowed_tiers=[1],
            preferred_tier=1,
            missed_feedback=f"{description}.",
            clinical_rationale=reason,
            common_error="Attempting an intervention that is not indicated for the current patient state.",
        ))
        occurred_at = getattr(event, "occurred_at", None)
        states.append(ChecklistItemState(
            item_id=item_id,
            state="contradicted",
            earned_points=0,
            evidence_references=[EvidenceReference(
                tier=1,
                source_type="session_event",
                source_id=getattr(event, "id", None),
                timestamp=occurred_at.isoformat() if occurred_at else None,
            )],
            critical_failure_triggered=False,
            notes=reason,
        ))

    return items, states


_INDICATION_GATE_STATUSES_SCORING = frozenset({"not_indicated_now", "contraindicated"})


def _indication_gate_violation_penalties(
    events: list,
) -> tuple[list["ChecklistItem"], list["ChecklistItemState"]]:
    """Synthesize deduction rows for interventions applied against their indication_gate.

    Fires when a student applies an intervention whose indication_gate was stored at
    application time (via build_intervention_clinical_snapshot) AND:
      - the gate status is not_indicated_now or contraindicated, AND
      - no allowed_when conditions were met (conditions_met is empty), AND
      - all unevaluatable conditions are also empty (conservative: don't penalize
        if we couldn't evaluate whether the condition was present).

    This is distinct from FTO-blocked attempts (_synthetic_inappropriate_attempt_penalties)
    which fire from clinical_decision events when the FTO card hard-blocks. This function
    handles cases where the student saw the FTO card but applied the intervention anyway.
    """
    items: list[ChecklistItem] = []
    states: list[ChecklistItemState] = []
    seen: set[str] = set()

    for event in events:
        if getattr(event, "event_type", None) != "intervention_applied":
            continue
        data = getattr(event, "event_data", None)
        if not isinstance(data, dict):
            continue
        gate = data.get("indication_gate")
        if not isinstance(gate, dict):
            continue
        if gate.get("status") not in _INDICATION_GATE_STATUSES_SCORING:
            continue

        conditions_met = data.get("conditions_met") or []
        conditions_unevaluatable = data.get("conditions_unevaluatable") or []
        allowed_when = gate.get("allowed_when") or []

        # Only penalize when we can definitively say no condition was met.
        # If there are unevaluatable conditions, we can't confirm the intervention was wrong.
        if conditions_met:
            continue
        if conditions_unevaluatable:
            continue

        intervention_key = str(getattr(event, "event_key", "") or "")
        if intervention_key in seen:
            continue
        seen.add(intervention_key)

        status = gate["status"]
        reason = str(gate.get("reason") or "This intervention was applied when it was not indicated for the patient's current state.")
        label = intervention_key.replace("_", " ").title()
        item_id = f"runtime.indication_gate_violation.{_slug_for_synthetic_item(intervention_key)}"
        description = (
            f"Contraindicated intervention applied — {label}"
            if status == "contraindicated"
            else f"Intervention applied before indicated — {label}"
        )
        points = 4 if status == "contraindicated" else 3

        items.append(ChecklistItem(
            id=item_id,
            description=description,
            subtype="intervention",
            category="clinical_performance",
            provenance="universal_base",
            point_value=points,
            required="required",
            allowed_tiers=[1],
            preferred_tier=1,
            missed_feedback=f"{description}.",
            clinical_rationale=reason,
            common_error=(
                "Applying a contraindicated intervention despite protocol guidance."
                if status == "contraindicated"
                else "Applying an intervention before the clinical conditions warranted it."
            ),
        ))
        occurred_at = getattr(event, "occurred_at", None)
        states.append(ChecklistItemState(
            item_id=item_id,
            state="contradicted",
            earned_points=0,
            evidence_references=[EvidenceReference(
                tier=1,
                source_type="session_event",
                source_id=getattr(event, "id", None),
                timestamp=occurred_at.isoformat() if occurred_at else None,
            )],
            critical_failure_triggered=False,
            notes=reason,
        ))

    return items, states


# ── Tier 1 satisfaction ───────────────────────────────────────────────────────


_PD_REQUIRED_SCENE_RE = re.compile(
    r"\b(police|law enforcement|pd|violence|weapon|shooting|stabbing|assault|domestic|hostile)\b",
    re.IGNORECASE,
)


def _scene_wait_for_pd_needed(scenario: dict) -> bool:
    """Return whether the authored scene requires staging for PD/law enforcement."""
    scene_safety_cfg = ((scenario.get("scene_entry_scoring") or {}).get("scene_safety") or {})
    if bool(scene_safety_cfg.get("wait_for_pd_required")):
        return True
    hazards = scene_safety_cfg.get("hazards")
    if hazards is None:
        hazards = (scenario.get("scene") or {}).get("hazards") or []
    hazard_text = " ".join(str(h) for h in (hazards or []))
    response_text = str(scene_safety_cfg.get("correct_response") or "")
    return bool(_PD_REQUIRED_SCENE_RE.search(f"{hazard_text} {response_text}"))


def _scene_approach_is_correct(scene_entry: dict, scenario: dict) -> bool:
    """Validate the student's scene approach against authored scene hazards."""
    approach = str(scene_entry.get("scene_approach") or "")
    pd_needed = _scene_wait_for_pd_needed(scenario)
    if approach == "waited_for_pd":
        return pd_needed
    if approach == "direct_contact":
        return not pd_needed
    return False


def _try_tier1(
    item: ChecklistItem,
    interventions: list,
    findings: list,
    events: list,
    scene_entry: dict | None,
    scenario: dict,
    chat_messages: list | None = None,
    provider_level: str = "EMT",
) -> EvidenceReference | None:
    """
    Attempt Tier 1 satisfaction from structured backend records — §10 Tier 1.

    Returns an EvidenceReference on success, None if no Tier 1 evidence found.
    """
    m = item.tier1_match
    if not m:
        return None

    if m.source == "intervention":
        wanted_keys = set(m.intervention_keys or [])
        if m.intervention_key:
            wanted_keys.add(m.intervention_key)
        if not wanted_keys:
            for intv in interventions:
                return EvidenceReference(
                    tier=1,
                    source_type="intervention_record",
                    source_id=intv.id,
                    timestamp=intv.applied_at.isoformat() if intv.applied_at else None,
                )
            return None
        for intv in interventions:
            if intv.name in wanted_keys:
                return EvidenceReference(
                    tier=1,
                    source_type="intervention_record",
                    source_id=intv.id,
                    timestamp=intv.applied_at.isoformat() if intv.applied_at else None,
                )
        return None

    if m.source == "finding":
        for finding in findings:
            if m.finding_type and finding.finding_type != m.finding_type:
                continue
            if m.finding_key_pattern:
                if not re.search(m.finding_key_pattern, finding.key, re.IGNORECASE):
                    continue
            if m.finding_value_pattern:
                if not re.search(m.finding_value_pattern, str(getattr(finding, "value", "") or ""), re.IGNORECASE):
                    continue
            # Source eligibility filter — NULL-source findings pass for backward compatibility
            finding_source = getattr(finding, "source", None)
            if m.eligible_sources and m.require_source and finding_source is None:
                continue
            if m.eligible_sources and finding_source is not None and finding_source not in m.eligible_sources:
                continue
            return EvidenceReference(
                tier=1,
                source_type="session_finding",
                source_id=finding.id,
                timestamp=finding.captured_at.isoformat() if finding.captured_at else None,
            )
        return None

    if m.source == "post_intervention_finding":
        first_intervention_at = min(
            (getattr(intv, "applied_at", None) for intv in interventions if getattr(intv, "applied_at", None)),
            default=None,
        )
        if first_intervention_at is None:
            return None
        for finding in findings:
            captured_at = getattr(finding, "captured_at", None)
            if captured_at is None or captured_at <= first_intervention_at:
                continue
            if m.finding_type and finding.finding_type != m.finding_type:
                continue
            if m.finding_key_pattern:
                if not re.search(m.finding_key_pattern, finding.key, re.IGNORECASE):
                    continue
            if m.finding_value_pattern:
                if not re.search(m.finding_value_pattern, str(getattr(finding, "value", "") or ""), re.IGNORECASE):
                    continue
            finding_source = getattr(finding, "source", None)
            if m.eligible_sources and m.require_source and finding_source is None:
                continue
            if m.eligible_sources and finding_source is not None and finding_source not in m.eligible_sources:
                continue
            return EvidenceReference(
                tier=1,
                source_type="post_intervention_finding",
                source_id=finding.id,
                timestamp=captured_at.isoformat(),
            )
        return None

    if m.source == "session_event":
        if not m.event_type:
            return None
        for event in events:
            if getattr(event, "event_type", None) != m.event_type:
                continue
            event_key = str(getattr(event, "event_key", "") or "")
            if m.event_key_pattern and not re.search(m.event_key_pattern, event_key, re.IGNORECASE):
                continue
            if m.event_data_result is not None:
                event_data = getattr(event, "event_data", None) or {}
                if not isinstance(event_data, dict):
                    return None
                result = str(event_data.get("result", "") or "")
                if result.lower() != str(m.event_data_result).lower():
                    continue
            occurred_at = getattr(event, "occurred_at", None)
            return EvidenceReference(
                tier=1,
                source_type="session_event",
                source_id=getattr(event, "id", None),
                timestamp=occurred_at.isoformat() if occurred_at else None,
            )
        return None

    if m.source == "scene_entry":
        se = scene_entry or {}
        if not se:
            return None

        if m.scene_entry_path == "ppe":
            # PPE check: every required item must appear in the donned list.
            ppe_donned: list[str] = se.get("ppe_donned", []) or []
            ppe_cfg = (scenario.get("scene_entry_scoring") or {}).get("ppe") or {}
            required_ids: list[str] = list(ppe_cfg.get("required") or ["gloves"])
            donned_normalized = {p.lower().replace(" ", "_") for p in ppe_donned}
            if all(r in donned_normalized for r in required_ids):
                return EvidenceReference(
                    tier=1,
                    source_type="scene_entry",
                    source_id=None,
                    timestamp=None,
                )
            return None

        if m.scene_entry_path == "scene_approach":
            if not se.get("scene_approach"):
                # Older scene-entry payloads did not always include the explicit
                # approach field. A persisted scene-entry record still represents
                # the doorway safety/PPE gate being completed before patient contact.
                if (se.get("ppe_donned") or se.get("pat_assessment")):
                    return EvidenceReference(
                        tier=1,
                        source_type="scene_entry",
                        source_id=None,
                        timestamp=None,
                    )
                return None
            if _scene_approach_is_correct(se, scenario):
                return EvidenceReference(
                    tier=1,
                    source_type="scene_entry",
                    source_id=None,
                    timestamp=None,
                )
            return None

        # Generic dot-path: navigate the scene_entry JSONB to a truthy leaf.
        if m.scene_entry_path:
            node: Any = se
            for part in m.scene_entry_path.split("."):
                if not isinstance(node, dict):
                    return None
                node = node.get(part)
            if node:
                return EvidenceReference(
                    tier=1,
                    source_type="scene_entry",
                    source_id=None,
                    timestamp=None,
                )

        return None

    if m.source == "absence_check":
        if not m.absence_intervention_key:
            return None
        applied_keys = {intv.name for intv in interventions}
        if m.absence_intervention_key not in applied_keys:
            return EvidenceReference(
                tier=1,
                source_type="absence_check",
                source_id=None,
                timestamp=None,
            )
        return None

    if m.source == "no_out_of_scope_actions":
        if not _has_out_of_scope_action_attempt(
            interventions,
            chat_messages or [],
            scenario,
            provider_level,
        ):
            return EvidenceReference(
                tier=1,
                source_type="scope_guardrail",
                source_id=None,
                timestamp=None,
            )
        return None

    return None


def _try_tier1_spec(
    m: "TierOneMatchSpec",
    interventions: list,
    findings: list,
    events: list,
    scene_entry: dict | None,
    scenario: dict,
    chat_messages: list | None,
    provider_level: str,
) -> "EvidenceReference | None":
    """
    Run _try_tier1 logic against a single TierOneMatchSpec without requiring a
    full ChecklistItem. Used by _try_tier1_all to evaluate each sub-requirement.
    """
    from app.checklist import ChecklistItem as _CI, TierOneMatchSpec as _TMS

    sentinel = _CI(
        id="_sentinel",
        description="",
        category="clinical_performance",
        subtype="assessment",
        point_value=0,
        tier1_match=m,
        allowed_tiers=[1],
    )
    return _try_tier1(sentinel, interventions, findings, events, scene_entry,
                      scenario, chat_messages, provider_level)


def _try_tier1_all(
    item: ChecklistItem,
    interventions: list,
    findings: list,
    events: list,
    scene_entry: dict | None,
    scenario: dict,
    chat_messages: list | None = None,
    provider_level: str = "EMT",
) -> list[EvidenceReference] | None:
    """
    Attempt Tier 1 satisfaction for requirement_logic='all' items — §10 Tier 1 AND semantics.

    Every spec in item.tier1_matches must be independently satisfied.
    Returns a list of EvidenceReferences (one per sub-requirement) on full satisfaction,
    None if any sub-requirement is unsatisfied.
    Each EvidenceReference carries the sub-requirement index in its notes field
    for QA/QI evidence-chain rendering.
    """
    if not item.tier1_matches:
        return None
    refs: list[EvidenceReference] = []
    for i, spec in enumerate(item.tier1_matches):
        ref = _try_tier1_spec(
            spec, interventions, findings, events, scene_entry,
            scenario, chat_messages, provider_level,
        )
        if ref is None:
            return None  # any unsatisfied sub-requirement → "all" fails
        # Tag with sub-requirement index for evidence-chain rendering
        refs.append(EvidenceReference(
            tier=ref.tier,
            source_type=ref.source_type,
            source_id=ref.source_id,
            timestamp=ref.timestamp,
            matched_text=ref.matched_text,
            confidence=ref.confidence,
            document_type=ref.document_type,
        ))
    return refs


# ── Tier 2 satisfaction ───────────────────────────────────────────────────────

# Source eligibility by subtype — §10 Tier 2.
_FINDING_TEXT_SUBTYPES: frozenset[str] = frozenset(
    {"assessment", "reassessment", "screen"}
)
_DOCUMENT_TEXT_SUBTYPES: frozenset[str] = frozenset(
    {"documentation_handoff", "documentation_narrative"}
)


def _build_student_transcript(chat_messages: list) -> str:
    """
    Concatenate student (user-role) messages for Tier 2 pattern matching.

    Model messages are excluded — partner confirmation text is not student
    evidence and must not satisfy Tier 2 items.
    """
    return " ".join(
        msg.content
        for msg in chat_messages
        if msg.role == "user"
    )


def _try_tier2(
    item: ChecklistItem,
    transcript: str,
    session_findings: list | None = None,
    submitted_dmist: str | None = None,
    submitted_narrative: str | None = None,
) -> EvidenceReference | None:
    """
    Attempt Tier 2 satisfaction — §10 Tier 2.

    Search order (stops at first match):
      1. student_transcript — all subtypes
      2. session_finding_text — assessment, reassessment
      3. submitted_document_text — documentation_handoff, documentation_narrative
    """
    if not item.tier2_patterns:
        return None

    def _first_match(text: str) -> str | None:
        for pattern in item.tier2_patterns:
            try:
                m = re.search(pattern, text)
            except re.error:
                log.warning("Invalid tier2 pattern for item %s: %r", item.id, pattern)
                continue
            if m:
                # Zero-length matches occur with pure lookahead patterns; they
                # are valid matches — the lookahead confirmed the terms are present.
                return m.group(0)[:200] or "[lookahead match]"
        return None

    # 1. Student transcript — all subtypes
    if transcript:
        span = _first_match(transcript)
        if span:
            return EvidenceReference(
                tier=2,
                source_type="transcript_match",
                source_id=None,
                timestamp=None,
                matched_text=span,
            )

    # 2. Session finding text — assessment, reassessment
    if item.subtype in _FINDING_TEXT_SUBTYPES and session_findings:
        for finding in session_findings:
            if item.id.startswith("ems.medical.opqrst_") or item.id.startswith("ems.medical.sample_") or item.id == "ems.medical.associated_symptoms":
                # History checklist items may use persisted history answers, but
                # generated exam/vital findings must not back-credit questions the
                # student never asked.
                if getattr(finding, "finding_type", None) != "history":
                    continue
            finding_text = f"{finding.key or ''} {finding.value or ''}".strip()
            if not finding_text:
                continue
            span = _first_match(finding_text)
            if span:
                ts = None
                if getattr(finding, "captured_at", None):
                    ts = finding.captured_at.isoformat()
                return EvidenceReference(
                    tier=2,
                    source_type="session_finding_text",
                    source_id=finding.id,
                    timestamp=ts,
                    matched_text=span,
                )

    # 3. Submitted document text — documentation_handoff, documentation_narrative
    if item.subtype in _DOCUMENT_TEXT_SUBTYPES:
        if submitted_dmist:
            span = _first_match(submitted_dmist)
            if span:
                return EvidenceReference(
                    tier=2,
                    source_type="submitted_document_text",
                    source_id=None,
                    timestamp=None,
                    matched_text=span,
                    document_type="dmist",
                )
        if submitted_narrative:
            span = _first_match(submitted_narrative)
            if span:
                return EvidenceReference(
                    tier=2,
                    source_type="submitted_document_text",
                    source_id=None,
                    timestamp=None,
                    matched_text=span,
                    document_type="narrative",
                )

    return None


def _parse_evidence_timestamp(state: ChecklistItemState) -> datetime | None:
    """Return the first parseable evidence timestamp for an adjudicated item."""
    for ref in state.evidence_references or []:
        if not ref.timestamp:
            continue
        raw = ref.timestamp
        try:
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            return datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            continue
    return None


def _partial_points_for_timing_violation(item: ChecklistItem) -> int:
    """Conservative partial score for timing violations when a rule permits partial."""
    rule = item.partial_credit_rule
    if rule and rule.model == "fixed_partial" and rule.partial_score is not None:
        return max(0, min(item.point_value, int(rule.partial_score)))
    return max(0, item.point_value // 2)


def _scaled_challenge_points(
    item: ChecklistItem,
    evidence: EvidenceReference,
    session_events: list,
    scenario: dict,
) -> int | None:
    """Map authoritative CPR/NRP challenge score into its parent checklist item."""
    if evidence.source_type != "session_event":
        return None
    integration = (scenario.get("cpr_challenge") or {}).get("rubric_integration") or {}
    if str(integration.get("item_id") or "") != item.id:
        return None
    event = next((ev for ev in session_events if getattr(ev, "id", None) == evidence.source_id), None)
    event_data = getattr(event, "event_data", None) if event is not None else None
    if not isinstance(event_data, dict):
        return None
    raw_score = event_data.get("score")
    if not isinstance(raw_score, (int, float)):
        return None
    normalized = max(0.0, min(100.0, float(raw_score)))
    return max(0, min(item.point_value, round((normalized / 100.0) * item.point_value)))


def _apply_timing_constraints(
    item_states: list[ChecklistItemState],
    effective_checklist: list[ChecklistItem],
) -> list[ChecklistItemState]:
    """Apply deterministic ordering constraints using Tier 1/2 evidence timestamps.

    This post-pass only evaluates ordering constraints when both sides are
    satisfied and both have parseable timestamps. Missing timestamps leave the
    content score untouched and add a diagnostic rather than guessing order.
    """
    states_by_id = {state.item_id: state for state in item_states}
    items_by_id = {item.id: item for item in effective_checklist}
    updated: list[ChecklistItemState] = []

    for state in item_states:
        item = items_by_id.get(state.item_id)
        constraint = item.timing_constraint if item else None
        if not item or not constraint or state.state != "satisfied":
            updated.append(state)
            continue

        violation = False
        diagnostic: str | None = None
        own_ts = _parse_evidence_timestamp(state)

        if constraint.type in ("before_item", "after_item"):
            ref_state = states_by_id.get(constraint.reference_item_id or "")
            ref_satisfied = ref_state is not None and ref_state.state == "satisfied"
            ref_ts = _parse_evidence_timestamp(ref_state) if ref_satisfied else None
            if constraint.type == "after_item" and not ref_satisfied:
                violation = True
                diagnostic = "timing prerequisite was not satisfied"
            elif own_ts is None or ref_ts is None:
                diagnostic = "timing constraint could not be evaluated because one side lacked timestamped evidence"
            elif constraint.type == "before_item":
                violation = own_ts >= ref_ts
            else:
                violation = own_ts <= ref_ts

        elif constraint.type == "ordered_set":
            sequence_states = [states_by_id.get(item_id) for item_id in (constraint.items or [])]
            timestamps = [
                _parse_evidence_timestamp(sequence_state)
                for sequence_state in sequence_states
                if sequence_state is not None
            ]
            if len(timestamps) != len(constraint.items or []) or any(ts is None for ts in timestamps):
                diagnostic = "ordered_set timing constraint could not be evaluated because at least one item lacked timestamped evidence"
            else:
                violation = any(timestamps[i] >= timestamps[i + 1] for i in range(len(timestamps) - 1))

        elif constraint.type == "within_minutes":
            diagnostic = "within_minutes timing constraints require scene-contact elapsed-time normalization and are not evaluated in this pass"

        if not violation:
            if diagnostic:
                updated.append(state.model_copy(update={"notes": diagnostic}))
            else:
                updated.append(state)
            continue

        consequence = constraint.violation_consequence
        if consequence == "informational":
            updated.append(state.model_copy(update={"timing_violation": True}))
        elif consequence == "partial":
            updated.append(state.model_copy(update={
                "state": "partial",
                "earned_points": _partial_points_for_timing_violation(item),
                "timing_violation": True,
            }))
        else:
            updated.append(state.model_copy(update={
                "state": "not_satisfied",
                "earned_points": 0,
                "timing_violation": True,
                "notes": "timing violation triggered deduction_override",
            }))

    return updated


# ── Item adjudication ─────────────────────────────────────────────────────────


def adjudicate(
    effective_checklist: list[ChecklistItem],
    interventions: list,
    session_findings: list,
    session_events: list,
    chat_messages: list,
    scene_entry: dict | None,
    submitted_dmist: str | None,
    submitted_narrative: str | None,
    scenario: dict,
    legacy_ai_categories: frozenset[str] | None = None,
    provider_level: str = "EMT",
) -> list[ChecklistItemState]:
    """
    Run the satisfaction cascade for each item — §10.

    Items in legacy_ai_categories are returned as not_applicable here;
    they are handled by the ai_client legacy path until Phase 6.

    Returns one ChecklistItemState per item in effective_checklist.
    """
    if legacy_ai_categories is None:
        legacy_ai_categories = _get_legacy_ai_categories(scenario)

    transcript = _build_student_transcript(chat_messages)
    states: list[ChecklistItemState] = []

    for item in effective_checklist:
        # Documentation and professionalism items are not adjudicated in Phase 4.
        # They are excluded from the deterministic pass and scored via legacy AI.
        if item.category in legacy_ai_categories:
            states.append(ChecklistItemState(
                item_id=item.id,
                state="not_applicable",
                earned_points=0,
                notes="deferred to Phase 6 deterministic scoring",
            ))
            continue

        evidence: EvidenceReference | None = None
        all_evidences: list[EvidenceReference] | None = None

        # Tier 1 attempt
        if 1 in item.allowed_tiers:
            if item.requirement_logic == "all" and item.tier1_matches:
                # AND semantics: all sub-requirements must be independently satisfied.
                # _try_tier1_all returns a list of EvidenceReferences or None.
                all_evidences = _try_tier1_all(
                    item, interventions, session_findings, session_events,
                    scene_entry, scenario,
                    chat_messages=chat_messages,
                    provider_level=provider_level,
                )
                if all_evidences:
                    evidence = all_evidences[0]  # primary ref for state logic; full list stored below
            else:
                evidence = _try_tier1(
                    item, interventions, session_findings, session_events,
                    scene_entry, scenario,
                    chat_messages=chat_messages,
                    provider_level=provider_level,
                )

        # Tier 1 alternatives — "any" items with multiple evidence_requirements try
        # each alternative spec before falling to Tier 2. A match on any alternative
        # satisfies the item at Tier 1.
        if evidence is None and 1 in item.allowed_tiers and getattr(item, "tier1_alternatives", None):
            for alt_spec in item.tier1_alternatives:
                alt_ev = _try_tier1_spec(
                    alt_spec, interventions, session_findings, session_events,
                    scene_entry, scenario,
                    chat_messages=chat_messages,
                    provider_level=provider_level,
                )
                if alt_ev is not None:
                    evidence = alt_ev
                    break

        # Tier 2 attempt (only if Tier 1 did not satisfy)
        # Guard: "all" logic items with tier1_matches never fall to flat Tier 2.
        # A broad transcript regex cannot substitute for independent structured
        # evidence per sub-requirement. The converter sets allowed_tiers=[1] for
        # these items; this check is defense-in-depth for hand-authored items.
        _is_all_logic = item.requirement_logic == "all" and bool(item.tier1_matches)
        if evidence is None and 2 in item.allowed_tiers and not _is_all_logic:
            evidence = _try_tier2(
                item, transcript,
                session_findings=session_findings,
                submitted_dmist=submitted_dmist,
                submitted_narrative=submitted_narrative,
            )

        # Tier 3 attempt (only if Tier 2 did not satisfy and item opts in)
        if evidence is None and item.tier3_permitted and 3 in item.allowed_tiers:
            evidence = _try_tier3(item, transcript)
            if evidence is None:
                # Tier 3 attempted but returned no evidence — ambiguous, not not_satisfied.
                # §7.2: ambiguous items earn 0 pts and take 0 deduction; require review.
                states.append(ChecklistItemState(
                    item_id=item.id,
                    state="ambiguous",
                    earned_points=0,
                    critical_failure_triggered=False,
                    notes="tier3_permitted: pending async implementation or model verification",
                ))
                continue

        if evidence is not None:
            # "all" logic: store all sub-requirement refs so QA/QI can trace each component.
            evidence_refs = all_evidences if all_evidences else [evidence]
            scaled_points = _scaled_challenge_points(item, evidence, session_events, scenario)
            earned_points = item.point_value if scaled_points is None else scaled_points
            state = "satisfied" if earned_points >= item.point_value else "partial"
            states.append(ChecklistItemState(
                item_id=item.id,
                state=state,
                earned_points=earned_points,
                evidence_references=evidence_refs,
                critical_failure_triggered=False,
                notes="challenge score mapped into parent checklist item" if scaled_points is not None else None,
            ))
        else:
            noncritical_scene_delay = (
                item.tier1_match
                and item.tier1_match.source == "scene_entry"
                and item.tier1_match.scene_entry_path == "scene_approach"
                and (scene_entry or {}).get("scene_approach") == "waited_for_pd"
                and not _scene_wait_for_pd_needed(scenario)
            )
            states.append(ChecklistItemState(
                item_id=item.id,
                state="not_satisfied",
                earned_points=0,
                critical_failure_triggered=item.critical_failure and not noncritical_scene_delay,
                notes="unnecessary_pd_wait_delayed_patient_contact" if noncritical_scene_delay else None,
            ))

    return _apply_timing_constraints(states, effective_checklist)


# ── Score computation ─────────────────────────────────────────────────────────


def compute_scores(
    item_states: list[ChecklistItemState],
    effective_checklist: list[ChecklistItem],
    legacy_ai_categories: frozenset[str] | None = None,
    scenario: dict | None = None,
) -> dict[str, CategoryScore]:
    """
    Derive category scores from adjudicated item states — §11.

    Arithmetic model (additive from zero):
      - satisfied items contribute point_value to earned
      - partial items contribute earned_points to earned
      - not_satisfied required items contribute point_value to deducted
        for diagnostics only; they already earn zero and are not subtracted again
      - contradicted / unsupported_by_run contribute point_value to deducted
        and are subtracted because they represent an active negative finding
      - ambiguous, not_applicable: zero contribution to earned or deducted
      - optional not_satisfied: zero deduction
      - bonus items: add to earned, not counted toward category_max

    total = max(0, min(category_max, earned - integrity_deductions))

    Categories with no checklist items → legacy_ai placeholder.
    """
    if legacy_ai_categories is None:
        legacy_ai_categories = _get_legacy_ai_categories(scenario or {})

    items_by_id: dict[str, ChecklistItem] = {i.id: i for i in effective_checklist}
    states_by_id: dict[str, ChecklistItemState] = {s.item_id: s for s in item_states}

    categories_present: set[str] = {i.category for i in effective_checklist}
    scores: dict[str, CategoryScore] = {}

    for category in categories_present:
        # Legacy AI categories carry a placeholder — not scored here.
        if category in legacy_ai_categories:
            scores[category] = CategoryScore(
                total=None,
                max=0,
                method="legacy_ai",
                pending=True,
            )
            continue

        cat_items = [i for i in effective_checklist if i.category == category]

        # category_max = sum of required + optional point_values; bonus excluded
        category_max = sum(
            i.point_value for i in cat_items if i.required != "bonus"
        )

        earned = 0
        deducted = 0
        integrity_deductions = 0

        for item in cat_items:
            state = states_by_id.get(item.id)
            if state is None:
                continue

            if state.state == "satisfied":
                earned += item.point_value

            elif state.state == "partial":
                earned += state.earned_points

            elif state.state == "not_satisfied":
                if item.required == "required":
                    deducted += item.point_value
                # optional and bonus not_satisfied → no deduction

            elif state.state in ("contradicted", "unsupported_by_run"):
                # Documentation integrity deductions — will be more granular in Phase 6
                deducted += item.point_value
                integrity_deductions += item.point_value

            # ambiguous → not credited, no deduction (§7.2)
            # not_applicable → excluded from arithmetic

        total = max(0, min(category_max, earned - integrity_deductions))

        scores[category] = CategoryScore(
            earned=earned,
            deducted=deducted,
            total=total,
            max=category_max,
            method="deterministic",
        )

    # Ensure every category present in the checklist appears in the snapshot.
    # Legacy-AI categories that had no items still need a placeholder so consumers
    # don't silently skip the category.
    for cat in categories_present:
        if cat not in scores:
            scores[cat] = CategoryScore(
                total=None,
                max=0,
                method="legacy_ai",
                pending=True,
            )

    return scores


# ── Idempotency hash ──────────────────────────────────────────────────────────


def _compute_input_hash(
    effective_checklist_hash: str,
    interventions: list,
    session_findings: list,
    session_events: list,
    chat_messages: list,
    scene_entry: dict | None,
    submitted_dmist: str | None,
    submitted_narrative: str | None,
) -> str:
    """
    Deterministic hash over all adjudication inputs — §18 idempotency policy.

    Content-based (not count/timestamp-based) so a change in any finding value,
    intervention, or message content triggers a re-adjudication.
    """
    payload = {
        "checklist_hash": effective_checklist_hash,
        "interventions": sorted(
            [{"id": i.id, "name": i.name, "applied_at": str(i.applied_at)} for i in interventions],
            key=lambda x: x["id"],
        ),
        "findings": sorted(
            [{"id": f.id, "type": f.finding_type, "key": f.key, "value": f.value} for f in session_findings],
            key=lambda x: x["id"],
        ),
        "events": sorted(
            [
                {
                    "event_type": getattr(e, "event_type", None),
                    "event_key": getattr(e, "event_key", None),
                    "event_data": getattr(e, "event_data", None),
                    "source": getattr(e, "source", None),
                    "occurred_at": str(getattr(e, "occurred_at", None)),
                }
                for e in session_events
            ],
            key=lambda x: json.dumps(x, sort_keys=True, default=str),
        ),
        # Content-hashed in message order — Tier 2 matching depends on message text,
        # not row IDs, so an ID-only hash would miss message body changes.
        "chat_message_shas": [
            hashlib.sha256((m.content or "").encode()).hexdigest()
            for m in chat_messages
        ],
        "scene_entry": scene_entry,
        "dmist_sha": hashlib.sha256((submitted_dmist or "").encode()).hexdigest(),
        "narrative_sha": hashlib.sha256((submitted_narrative or "").encode()).hexdigest(),
    }
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def _compute_checklist_hash(checklist: list[ChecklistItem]) -> str:
    """
    Composite fingerprint of all effective checklist items — §6.4.

    Identifies the exact rule bundle this session was adjudicated against.
    """
    canonical_items = [
        json.dumps(item.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        for item in sorted(checklist, key=lambda x: x.id)
    ]
    return "sha256:" + hashlib.sha256("|".join(canonical_items).encode()).hexdigest()


def _shadow_compose_call_type_rubric(
    scenario: dict,
    ctx: EffectiveContext,
    effective_checklist: list[ChecklistItem],
    composed_at: str,
) -> dict | None:
    """
    F2a shadow phase: load, role-resolve, compose, and trace the NASEMSO call-type rubric.

    Produces a ShadowCompositionReport serialised as a dict for persistence in
    checklist_states['shadow_composition']. Scoring is not affected.

    Replace this with active composition in F2b after F3 overlay schema is defined.
    """
    call_type = scenario.get("call_type")
    if not call_type:
        log.debug("_shadow_compose_call_type_rubric: scenario has no call_type, skipping")
        return None
    rubric = load_call_type_rubric(call_type, deployment_context=ctx.deployment_context)
    if rubric is None:
        return None
    log_shadow_rubric(rubric)
    report = compose_shadow_checklist(
        base_items=effective_checklist,
        rubric=rubric,
        provider_level=ctx.provider_level,
        composed_at=composed_at,
    )
    return report.to_dict()


def _load_effective_checklist_for_session(
    session,
    scenario: dict,
    ctx: EffectiveContext,
) -> list[ChecklistItem]:
    """
    Resolve the effective checklist for this session.

    Historical sessions prefer the persisted checklist definition snapshot so
    later rubric changes do not retroactively re-grade old runs.
    """
    states_blob = session.checklist_states or {}
    stored_defs = states_blob.get("checklist_definitions") if isinstance(states_blob, dict) else None
    if stored_defs:
        try:
            return [ChecklistItem.model_validate(item) for item in stored_defs]
        except Exception as exc:
            log.warning(
                "Session %s has unreadable persisted checklist snapshot; rebuilding from current scenario (%s)",
                session.id, exc,
            )
    return load_checklist(
        scenario,
        level=ctx.provider_level,
        mca=ctx.mca,
        agency_id=ctx.agency_id,
    )


def _compute_critical_failure_status(
    item_states: list[ChecklistItemState],
    effective_checklist: list[ChecklistItem],
) -> dict[str, Any] | None:
    """
    Return a structured critical-failure status when any configured hard-fail
    item is missed or contradicted.
    """
    items_by_id: dict[str, ChecklistItem] = {i.id: i for i in effective_checklist}
    triggered: list[dict[str, Any]] = []
    for state in item_states:
        item = items_by_id.get(state.item_id)
        if not item or not item.critical_failure:
            continue
        if state.state in {"not_satisfied", "contradicted", "unsupported_by_run"} and getattr(
            state,
            "critical_failure_triggered",
            item.critical_failure,
        ):
            triggered.append({
                "item_id": item.id,
                "label": item.critical_failure_label or item.description,
                "state": state.state,
                "category": item.category,
            })
    if not triggered:
        return None
    return {
        "triggered": True,
        "display_label": "Critical Misses",
        "items": triggered,
    }


# ── Persist ───────────────────────────────────────────────────────────────────


async def adjudicate_and_persist(
    session,
    scenario: dict,
    db: AsyncSession,
) -> AdjudicatedPacket | None:
    """
    Run adjudication and write results to the five Phase 1 columns — §18 Phase 4.

    Idempotency:
      - Same inputs → no-op (hash match detected)
      - Changed inputs → replace all five columns atomically
      - Returns the packet (from DB or freshly computed)
      - Returns None when the scenario has no checklist or inherited base rubric
        (legacy-only session)

    Call this BEFORE evaluate_and_generate_debrief().  The AI call receives
    locked facts; it does not originate them.
    """
    if not scenario.get("checklist") and not scenario.get("base_patient_care_rubric"):
        return None

    ctx = resolve_context(session, scenario)

    from app.config import settings as _cfg
    base_checklist = _load_effective_checklist_for_session(session, scenario, ctx)
    if not base_checklist:
        return None

    # ── F2b: Active call-type rubric composition (behind feature flag) ────────
    overlay_audit_for_persist: list[dict] | None = None
    if _cfg.use_call_type_rubric:
        call_type = scenario.get("call_type")
        if call_type:
            rubric = load_call_type_rubric(call_type, deployment_context=ctx.deployment_context)
            if rubric is not None:
                scenario_id = scenario.get("id", "")
                overlay_ops = load_scenario_overlay(scenario_id, call_type)
                composed = compose_active_checklist(
                    base_items=base_checklist,
                    rubric=rubric,
                    provider_level=ctx.provider_level,
                    overlay_ops=overlay_ops,
                    overlay_id=f"{scenario_id}_overlay" if overlay_ops else "",
                    scenario=scenario,
                )
                effective_checklist = composed.items
                overlay_audit_for_persist = composed.overlay_audit
                log.info(
                    "adjudicate_and_persist: F2b active — session %s call_type=%s "
                    "base=%d call_type_items=%d composed=%d overlay_ops=%d suppressed=%d",
                    session.id, call_type,
                    len(base_checklist), len(rubric.items),
                    len(effective_checklist),
                    len(overlay_ops) if overlay_ops else 0,
                    sum(1 for op in (overlay_ops or []) if op.get("op") == "suppress_item"),
                )
            else:
                effective_checklist = base_checklist
        else:
            effective_checklist = base_checklist
    else:
        effective_checklist = base_checklist

    interventions = list(session.interventions or [])
    findings = list(session.findings or [])
    events = list(session.events or [])
    messages = list(session.messages or [])
    scene_entry: dict | None = session.scene_entry if isinstance(session.scene_entry, dict) else None
    submitted_dmist: str | None = session.dmist_report
    submitted_narrative: str | None = (session.narrative_data or {}).get("narrative")

    adjudication_checklist = effective_checklist
    synthetic_penalty_items, synthetic_penalty_states = _synthetic_inappropriate_attempt_penalties(events)
    gate_penalty_items, gate_penalty_states = _indication_gate_violation_penalties(events)
    all_synthetic_items = [*synthetic_penalty_items, *gate_penalty_items]
    all_synthetic_states = [*synthetic_penalty_states, *gate_penalty_states]
    if all_synthetic_items:
        effective_checklist = [*effective_checklist, *all_synthetic_items]

    ctx.checklist_item_count = len(effective_checklist)
    checklist_hash = _compute_checklist_hash(effective_checklist)

    input_hash = _compute_input_hash(
        checklist_hash, interventions, findings, events, messages,
        scene_entry, submitted_dmist, submitted_narrative,
    )

    # ── Idempotency check ─────────────────────────────────────────────────────
    existing_snapshot = session.score_snapshot
    if isinstance(existing_snapshot, dict):
        if existing_snapshot.get("adjudication_input_hash") == input_hash:
            # Inputs unchanged — reconstruct packet from persisted data and return
            log.debug("adjudicate_and_persist: no-op, inputs unchanged for session %s", session.id)
            return _reconstruct_packet_from_session(session, ctx)

    # ── Archive superseded packet before overwriting ──────────────────────────
    # If a previous adjudication exists, archive it before the live columns are
    # replaced.  This preserves the full audit history when inputs change (e.g.
    # a new message is sent, a re-debrief is triggered after an instructor override).
    # First-run sessions (no existing snapshot) skip archiving.
    if isinstance(existing_snapshot, dict) and existing_snapshot.get("adjudication_input_hash"):
        db.add(AdjudicationRevision(
            session_id=session.id,
            superseded_at=datetime.now(timezone.utc),
            input_hash=existing_snapshot["adjudication_input_hash"],
            checklist_states=session.checklist_states,
            score_snapshot=existing_snapshot,
            evidence_references=session.evidence_references,
        ))

    # ── Adjudicate ────────────────────────────────────────────────────────────
    legacy_cats = _get_legacy_ai_categories(scenario)

    item_states = adjudicate(
        adjudication_checklist,
        interventions, findings, events, messages,
        scene_entry, submitted_dmist, submitted_narrative,
        scenario,
        legacy_ai_categories=legacy_cats,
        provider_level=ctx.provider_level,
    )
    if all_synthetic_states:
        item_states.extend(all_synthetic_states)

    score_snapshot = compute_scores(
        item_states, effective_checklist,
        legacy_ai_categories=legacy_cats,
        scenario=scenario,
    )
    critical_failure = _compute_critical_failure_status(item_states, effective_checklist)

    now_iso = datetime.now(timezone.utc).isoformat()

    packet = AdjudicatedPacket(
        item_states=item_states,
        score_snapshot=score_snapshot,
        effective_context=ctx,
        effective_checklist=effective_checklist,
        adjudication_input_hash=input_hash,
        adjudicated_at=now_iso,
        critical_failure=critical_failure,
    )

    # ── Persist atomically ────────────────────────────────────────────────────
    score_snap_jsonb = packet.to_score_snapshot_jsonb()
    # Embed input hash at top level so idempotency check is a single dict read
    score_snap_jsonb["adjudication_input_hash"] = input_hash

    # ── F2a Shadow: compose call-type rubric against current checklist ────────
    shadow_report = _shadow_compose_call_type_rubric(
        scenario, ctx, effective_checklist, now_iso,
    )

    checklist_states_jsonb = packet.to_checklist_states_jsonb()

    # Overlay audit — scored composition (F2b). Clearly labelled for QA/QI.
    if overlay_audit_for_persist is not None:
        checklist_states_jsonb["overlay_audit"] = overlay_audit_for_persist

    # Shadow composition report — observe-only (F2a). Suppressed when F2b is active
    # to avoid confusion between diagnostic shadow output and live overlay audit.
    if shadow_report is not None and not _cfg.use_call_type_rubric:
        # _diagnostic_only: true marks this block as non-scored debug output.
        # QA/QI reviewers must not treat shadow_composition as adjudicated findings.
        shadow_report["_diagnostic_only"] = True
        checklist_states_jsonb["shadow_composition"] = shadow_report

    session.effective_context = ctx.model_dump()
    session.effective_checklist_hash = checklist_hash
    session.checklist_states = checklist_states_jsonb
    session.evidence_references = packet.to_evidence_references_jsonb()
    session.score_snapshot = score_snap_jsonb

    for attr in (
        "effective_context", "effective_checklist_hash",
        "checklist_states", "evidence_references", "score_snapshot",
    ):
        flag_modified(session, attr)

    await db.commit()
    await db.refresh(session)

    log.info(
        "adjudicate_and_persist: session %s adjudicated %d items hash=%s",
        session.id, len(item_states), input_hash[:16],
    )

    # Phase 7 observability: emit per-item tier resolution metrics for calibration monitoring.
    # JSON-formatted so production log aggregators can parse and aggregate.
    _tier_counts: dict[str, int] = {
        "tier1": 0, "tier2": 0, "tier3": 0,
        "ambiguous": 0, "not_satisfied": 0, "legacy_ai": 0,
    }
    _ambiguous_ids: list[str] = []
    for _st in item_states:
        if _st.state == "not_applicable":
            _tier_counts["legacy_ai"] += 1
        elif _st.state == "satisfied":
            _ev = _st.evidence_references[0] if _st.evidence_references else None
            _tier_key = f"tier{_ev.tier}" if _ev and _ev.tier in (1, 2, 3) else "tier1"
            _tier_counts[_tier_key] = _tier_counts.get(_tier_key, 0) + 1
        elif _st.state == "ambiguous":
            _tier_counts["ambiguous"] += 1
            _ambiguous_ids.append(_st.item_id)
        else:
            _tier_counts["not_satisfied"] += 1
    log.info(
        "adjudication_metrics %s",
        json.dumps({
            "session_id": session.id,
            "scenario_id": scenario.get("id", ""),
            "level": ctx.provider_level,
            "total_items": len(item_states),
            **_tier_counts,
            "ambiguous_ids": _ambiguous_ids,
            "critical_failure": bool(critical_failure),
        }),
    )

    return packet


def _reconstruct_packet_from_session(session, ctx: EffectiveContext) -> AdjudicatedPacket | None:
    """Rebuild AdjudicatedPacket from already-persisted session columns."""
    try:
        snap = session.score_snapshot or {}
        stored_version = snap.get("packet_schema_version")
        if stored_version and stored_version != PACKET_SCHEMA_VERSION:
            log.warning(
                "Session %s stored packet_schema_version=%r; current is %r — "
                "deserializing anyway but schema drift may cause silent field loss",
                session.id, stored_version, PACKET_SCHEMA_VERSION,
            )
        states_blob = session.checklist_states or {}

        item_states = [
            ChecklistItemState.model_validate(s)
            for s in states_blob.get("item_states", [])
        ]
        score_snapshot = {
            cat: CategoryScore.model_validate(v)
            for cat, v in snap.get("categories", {}).items()
        }
        return AdjudicatedPacket(
            item_states=item_states,
            score_snapshot=score_snapshot,
            effective_context=ctx,
            effective_checklist=[
                ChecklistItem.model_validate(item)
                for item in (states_blob.get("checklist_definitions", []) if isinstance(states_blob, dict) else [])
            ],
            adjudication_input_hash=snap.get("adjudication_input_hash", ""),
            adjudicated_at=snap.get("adjudicated_at", ""),
            critical_failure=snap.get("critical_failure"),
        )
    except Exception as exc:
        log.warning("Failed to reconstruct packet from session %s: %s", session.id, exc)
        return None


# ── Public helper: extract legacy-compatible subscores ────────────────────────


def extract_deterministic_subscores(packet: AdjudicatedPacket) -> dict[str, int | None]:
    """
    Convert a Phase 4 packet into the subscore dict format that main.py uses.

    legacy_ai categories return None so callers know to read from AI output.
    Only deterministic categories return an integer.
    """
    result: dict[str, int | None] = {}
    for cat, score in packet.score_snapshot.items():
        result[cat] = score.total  # null for legacy_ai, int for deterministic
    return result
