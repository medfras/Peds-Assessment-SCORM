"""
NASEMSO call-type rubric loader and source role resolver — Group F1.

Loads rubric files from app/rubrics/nasemso/ and resolves abstract source roles
to concrete source strings per deployment context ("training" or "qaqi").

Shadow mode: the loader produces a ResolvedRubric that is logged for diagnostic
purposes but does not yet feed into score computation. See SCORING_IMPROVEMENT_PLAN.md
Group F for the staged integration plan.

Architecture reference: SCORING_ENGINE_ARCHITECTURE.md §5.5, SCORING_IMPROVEMENT_PLAN.md Group F.
"""

from __future__ import annotations

import json
import logging
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

_RUBRIC_DIR = pathlib.Path(__file__).parent / "rubrics" / "nasemso"
_OVERLAY_DIR = _RUBRIC_DIR / "overlays"

# Glob pattern: <call_type>_v*.json (ignores the schema file)
_RUBRIC_GLOB = "*_v*.json"


def load_scenario_overlay(scenario_id: str, call_type: str) -> list[dict] | None:
    """
    Load a scenario-specific overlay file from app/rubrics/nasemso/overlays/.

    File convention: overlays/{scenario_id}.json
    Returns the operations list if the file exists and its call_type matches,
    otherwise None (no overlay — compose_active_checklist uses the base rubric as-is).
    """
    overlay_path = _OVERLAY_DIR / f"{scenario_id}.json"
    if not overlay_path.exists():
        log.debug("load_scenario_overlay: no overlay file for scenario=%s", scenario_id)
        return None
    try:
        with open(overlay_path) as f:
            data = json.load(f)
    except Exception as exc:
        log.warning("load_scenario_overlay: failed to parse %s: %s", overlay_path, exc)
        return None
    file_call_type = data.get("call_type")
    if file_call_type != call_type:
        log.warning(
            "load_scenario_overlay: overlay %s has call_type=%r, expected %r — skipping",
            overlay_path, file_call_type, call_type,
        )
        return None
    ops = data.get("operations", [])
    log.debug(
        "load_scenario_overlay: loaded scenario=%s call_type=%s ops=%d",
        scenario_id, call_type, len(ops),
    )
    return ops


def get_known_call_types() -> frozenset[str]:
    """
    Return the set of call type names that have at least one rubric file in _RUBRIC_DIR.

    Used by scenario validation to confirm call_type resolves before accepting it.
    Stem format is <call_type>_v<N>.json — this function strips the version suffix.
    """
    known: set[str] = set()
    for path in _RUBRIC_DIR.glob(_RUBRIC_GLOB):
        m = re.match(r"^(.+)_v\d+$", path.stem)
        if m:
            known.add(m.group(1))
    return frozenset(known)

DeploymentContext = str  # "training" | "qaqi"
_STRUCTURED_SOURCE_ONLY_ROLES = frozenset({
    "challenge_performed_exam",
    "challenge_calculated_gcs",
    "challenge_measured_bgl",
})


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class ResolvedEvidenceRequirement:
    """
    One evidence requirement with abstract source roles expanded to concrete
    source strings for the given deployment context.
    """
    type: str
    finding_type: str | None = None
    key_pattern: str | None = None
    value_pattern: str | None = None
    # Concrete sources resolved from eligible_source_roles + source_role_map.
    # Empty list means the role exists but has no concrete sources in this context
    # (legitimate interim state — falls to Tier 2 via tier2_patterns).
    resolved_sources: list[str] = field(default_factory=list)
    # Original abstract roles before resolution (for diagnostics).
    original_source_roles: list[str] = field(default_factory=list)
    # Which roles resolved to zero concrete sources (smoke detector for bad overlays).
    empty_roles: list[str] = field(default_factory=list)
    # Intervention fields
    intervention_key: str | None = None
    intervention_keys: list[str] | None = None
    # session_event fields
    event_type: str | None = None
    event_key_pattern: str | None = None
    # scene_entry fields
    scene_entry_path: str | None = None
    # absence_check fields
    absence_intervention_key: str | None = None


@dataclass
class ResolvedChecklistItem:
    """
    A call-type rubric checklist item with source roles resolved for the
    given deployment context. Carries full diagnostic metadata.
    """
    # Identification
    source_rubric: str           # Rubric file stem, e.g. "respiratory_distress_v1"
    item_id: str
    description: str
    # Scoring
    category: str
    subtype: str
    point_value: int
    required: str                # "required" | "optional" | "bonus"
    applicable_levels: list[str]
    applicable_if: dict[str, Any]
    requirement_logic: str       # "any" | "all"
    timing_constraints: list[dict[str, Any]]
    # Evidence
    evidence_requirements: list[ResolvedEvidenceRequirement]
    tier2_patterns: list[str]
    # Feedback
    done_feedback: str
    missed_feedback: str
    # Safety flags
    unsafe_if_missed: bool
    # Provenance
    provenance: str = "call_type_rubric"
    # Diagnostic summary (populated by resolver)
    has_empty_roles: bool = False


@dataclass
class ResolvedRubric:
    """
    Output of load_call_type_rubric() — a loaded and role-resolved rubric.
    """
    call_type: str
    source_file: str             # Absolute path as string
    rubric_id: str
    rubric_version: str
    deployment_context: DeploymentContext
    items: list[ResolvedChecklistItem] = field(default_factory=list)


# ── Source role resolver ──────────────────────────────────────────────────────


def _resolve_source_roles(
    source_role_map: dict[str, Any],
    roles: list[str],
    context: DeploymentContext,
) -> tuple[list[str], list[str]]:
    """
    Expand a list of abstract source roles to concrete source strings.

    Returns (resolved_sources, empty_roles) where empty_roles contains roles
    that are defined in source_role_map but have no concrete sources for context.
    An undefined role is treated as an empty role (not a hard error) so loading
    can continue in shadow mode — the validator catches undefined roles at CI time.
    """
    resolved: list[str] = []
    empty_roles: list[str] = []
    for role in roles:
        role_def = source_role_map.get(role)
        if role_def is None:
            log.warning("rubric_loader: abstract role '%s' not found in source_role_map", role)
            empty_roles.append(role)
            continue
        sources = role_def.get(context) or []
        if not sources:
            empty_roles.append(role)
        resolved.extend(sources)
    return resolved, empty_roles


def _resolve_evidence_requirement(
    req: dict[str, Any],
    source_role_map: dict[str, Any],
    context: DeploymentContext,
) -> ResolvedEvidenceRequirement:
    abstract_roles = req.get("eligible_source_roles", [])
    if abstract_roles:
        resolved_sources, empty_roles = _resolve_source_roles(source_role_map, abstract_roles, context)
    else:
        resolved_sources = []
        empty_roles = []

    return ResolvedEvidenceRequirement(
        type=req["type"],
        finding_type=req.get("finding_type"),
        key_pattern=req.get("key_pattern"),
        value_pattern=req.get("value_pattern"),
        resolved_sources=resolved_sources,
        original_source_roles=abstract_roles,
        empty_roles=empty_roles,
        intervention_key=req.get("intervention_key"),
        intervention_keys=req.get("intervention_keys"),
        event_type=req.get("event_type"),
        event_key_pattern=req.get("event_key_pattern"),
        scene_entry_path=req.get("scene_entry_path"),
        absence_intervention_key=req.get("absence_intervention_key"),
    )


def _resolve_item(
    raw_item: dict[str, Any],
    source_rubric: str,
    source_role_map: dict[str, Any],
    context: DeploymentContext,
) -> ResolvedChecklistItem:
    resolved_reqs = [
        _resolve_evidence_requirement(req, source_role_map, context)
        for req in raw_item.get("evidence_requirements", [])
    ]
    has_empty = any(bool(r.empty_roles) for r in resolved_reqs)

    return ResolvedChecklistItem(
        source_rubric=source_rubric,
        item_id=raw_item["id"],
        description=raw_item["description"],
        category=raw_item["category"],
        subtype=raw_item["subtype"],
        point_value=raw_item["point_value"],
        required=raw_item.get("required", "required"),
        applicable_levels=raw_item.get("applicable_levels", []),
        applicable_if=raw_item.get("applicable_if", {}),
        requirement_logic=raw_item.get("requirement_logic", "any"),
        timing_constraints=raw_item.get("timing_constraints", []) or [],
        evidence_requirements=resolved_reqs,
        tier2_patterns=raw_item.get("tier2_patterns", []),
        done_feedback=raw_item.get("done_feedback", ""),
        missed_feedback=raw_item.get("missed_feedback", ""),
        unsafe_if_missed=raw_item.get("unsafe_if_missed", False),
        has_empty_roles=has_empty,
    )


# ── Debug trace ───────────────────────────────────────────────────────────────


def _log_resolved_rubric(rubric: ResolvedRubric) -> None:
    """
    Emit a structured debug trace of the resolved rubric.

    Each item line includes: rubric source, item ID, requirement_logic,
    original source roles, resolved concrete sources, and any empty roles.
    This is the smoke detector for bad overlays.
    """
    log.debug(
        "rubric_loader [%s] loaded %d items from %s (context=%s)",
        rubric.call_type,
        len(rubric.items),
        rubric.source_file,
        rubric.deployment_context,
    )
    for item in rubric.items:
        for i, req in enumerate(item.evidence_requirements):
            role_summary = (
                ", ".join(
                    f"{role}→[{', '.join(req.resolved_sources)}]{'(EMPTY)' if role in req.empty_roles else ''}"
                    for role in req.original_source_roles
                )
                if req.original_source_roles
                else "(no role filter)"
            )
            log.debug(
                "  [%s] item=%s logic=%s req[%d] type=%s sources: %s",
                rubric.source_file.rsplit("/", 1)[-1],
                item.item_id,
                item.requirement_logic,
                i,
                req.type,
                role_summary,
            )
        if item.has_empty_roles:
            log.debug(
                "  [%s] item=%s has empty roles in context=%s — falls to Tier 2 via tier2_patterns",
                rubric.source_file.rsplit("/", 1)[-1],
                item.item_id,
                rubric.deployment_context,
            )


# ── File discovery ────────────────────────────────────────────────────────────


def _find_rubric_file(call_type: str) -> pathlib.Path | None:
    """
    Locate the latest versioned rubric file for a call_type slug.

    Matches files named <call_type>_v*.json. If multiple versions exist,
    picks the lexicographically last (v2 > v1), which covers the v1/v2 pattern.
    """
    candidates = sorted(_RUBRIC_DIR.glob(f"{call_type}_v*.json"))
    return candidates[-1] if candidates else None


# ── Public API ────────────────────────────────────────────────────────────────


def load_call_type_rubric(
    call_type: str,
    deployment_context: DeploymentContext = "training",
) -> ResolvedRubric | None:
    """
    Load and role-resolve the NASEMSO call-type rubric for call_type.

    Returns a ResolvedRubric if a rubric file exists, None if no rubric exists
    for this call type (log + skip, not a hard error).

    In shadow mode (Group F1), the result is logged but not incorporated into
    effective checklist scoring. Call log_shadow_rubric() after this.
    """
    path = _find_rubric_file(call_type)
    if path is None:
        log.debug("rubric_loader: no rubric found for call_type='%s' in %s", call_type, _RUBRIC_DIR)
        return None

    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as exc:
        log.error("rubric_loader: failed to load %s: %s", path, exc)
        return None

    source_role_map = raw.get("source_role_map", {})
    source_rubric = path.stem

    items = [
        _resolve_item(raw_item, source_rubric, source_role_map, deployment_context)
        for raw_item in raw.get("checklist_items", [])
    ]

    rubric = ResolvedRubric(
        call_type=raw.get("call_type", call_type),
        source_file=str(path),
        rubric_id=raw.get("id", ""),
        rubric_version=raw.get("version", ""),
        deployment_context=deployment_context,
        items=items,
    )
    return rubric


def log_shadow_rubric(rubric: ResolvedRubric) -> None:
    """
    Emit the full resolved-rubric debug trace (shadow mode).

    Call this immediately after load_call_type_rubric() during F1 shadow phase.
    Separated from load_call_type_rubric() so callers can suppress the trace
    in production once F2b is live and the rubric is actively scoring.
    """
    _log_resolved_rubric(rubric)


# ── F2a: Shadow composition ───────────────────────────────────────────────────


@dataclass
class CompositionConflict:
    """A problem detected during shadow composition that would prevent clean merge."""
    kind: str         # "duplicate_id" | "category_conflict" | "subtype_conflict"
    item_id: str
    base_provenance: str
    call_type_provenance: str
    detail: str


@dataclass
class ShadowCompositionReport:
    """
    Output of compose_shadow_checklist(). Persisted in checklist_states['shadow_composition'].

    Fields match the F2a trace spec from SCORING_IMPROVEMENT_PLAN.md Group F.
    """
    # Counts
    base_item_count: int
    call_type_item_count: int
    composed_item_count: int
    # Conflict detection (composition errors — would prevent clean merge)
    conflicts: list[dict]               # serialised CompositionConflict
    # Items that would be added by call_type_rubric layer (no ID conflict)
    added_items: list[dict]
    # Items with requirement_logic='all' in call-type rubric
    all_logic_items: list[str]          # item_ids
    # Items with at least one empty resolved source role
    empty_role_items: list[str]         # item_ids
    # Items whose applicable_levels exclude the current provider level
    level_excluded_items: list[str]     # item_ids
    # Call-type items that appear to duplicate a base/scenario item by description similarity
    suspected_duplicates: list[dict]    # [{call_type_id, similar_to_id, reason}]
    # Source rubric metadata
    call_type: str
    rubric_id: str
    rubric_version: str
    deployment_context: str
    composed_at: str                    # ISO-8601

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


# ── Description similarity heuristic ──────────────────────────────────────────

_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "to", "for", "in", "is", "are",
    "was", "be", "by", "with", "as", "at", "from", "on", "this", "that",
    "performed", "assessed", "obtained", "documented", "checks", "check",
    "using", "via", "whether", "patient", "student", "provider",
})


def _description_tokens(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return frozenset(w for w in words if w not in _STOP_WORDS and len(w) > 2)


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union)


_SIMILARITY_THRESHOLD = 0.55  # tuned for EMS clinical language


def _find_suspected_duplicates(
    call_type_items: list[ResolvedChecklistItem],
    base_ids: set[str],
    base_items_by_id: dict[str, Any],  # ChecklistItem from checklist.py — avoid import cycle
) -> list[dict]:
    results = []
    ct_tokens = {item.item_id: _description_tokens(item.description) for item in call_type_items}
    base_tokens = {
        iid: _description_tokens(base_items_by_id[iid].description)
        for iid in base_ids
        if hasattr(base_items_by_id[iid], "description")
    }
    for ct_item in call_type_items:
        ct_tok = ct_tokens[ct_item.item_id]
        for base_id, b_tok in base_tokens.items():
            score = _jaccard(ct_tok, b_tok)
            if score >= _SIMILARITY_THRESHOLD:
                results.append({
                    "call_type_id": ct_item.item_id,
                    "similar_to_id": base_id,
                    "jaccard_score": round(score, 3),
                    "reason": f"description token overlap {score:.0%}",
                })
    return results


def compose_shadow_checklist(
    base_items: list,           # list[ChecklistItem] from checklist.py
    rubric: ResolvedRubric,
    provider_level: str,
    composed_at: str,           # ISO-8601
) -> ShadowCompositionReport:
    """
    Build a shadow composition report: what the effective checklist would look like
    if call-type rubric items were merged with the base/scenario checklist.

    No scores are affected. The report exposes composition differences, conflicts,
    and filtering decisions for comparison against current scoring runs.

    Conflict semantics:
    - duplicate_id: call-type item ID already exists in base — hard composition error.
      Overlay ops (suppress/modify) are the correct resolution; raw merge must fail loud.
    - category_conflict / subtype_conflict: same ID, different metadata (defensive check).
    """
    from datetime import datetime, timezone

    base_ids: set[str] = {item.id for item in base_items}
    base_items_by_id = {item.id: item for item in base_items}

    conflicts: list[CompositionConflict] = []
    added_items: list[dict] = []
    all_logic_ids: list[str] = []
    empty_role_ids: list[str] = []
    level_excluded_ids: list[str] = []

    for ct_item in rubric.items:
        if ct_item.item_id in base_ids:
            base_item = base_items_by_id[ct_item.item_id]
            conflicts.append(CompositionConflict(
                kind="duplicate_id",
                item_id=ct_item.item_id,
                base_provenance=getattr(base_item, "provenance", "unknown"),
                call_type_provenance="call_type_rubric",
                detail=(
                    f"base: category={getattr(base_item, 'category', '?')} "
                    f"subtype={getattr(base_item, 'subtype', '?')} "
                    f"call_type: category={ct_item.category} subtype={ct_item.subtype}"
                ),
            ))
            continue

        # Level-excluded items are reported separately; they must not inflate added_items
        # or composed_item_count, which are used as the "what the active checklist would look like"
        # signal. Active composition already filters them — shadow must match.
        if ct_item.applicable_levels and provider_level not in ct_item.applicable_levels:
            level_excluded_ids.append(ct_item.item_id)
            continue

        # Item would be added — annotate with diagnostic flags
        item_dict: dict = {
            "item_id": ct_item.item_id,
            "description": ct_item.description,
            "category": ct_item.category,
            "subtype": ct_item.subtype,
            "point_value": ct_item.point_value,
            "required": ct_item.required,
            "requirement_logic": ct_item.requirement_logic,
            "applicable_levels": ct_item.applicable_levels,
            "provenance": ct_item.provenance,
            "has_empty_roles": ct_item.has_empty_roles,
            "unsafe_if_missed": ct_item.unsafe_if_missed,
        }
        added_items.append(item_dict)

        if ct_item.requirement_logic == "all":
            all_logic_ids.append(ct_item.item_id)

        if ct_item.has_empty_roles:
            empty_role_ids.append(ct_item.item_id)

    suspected = _find_suspected_duplicates(
        [i for i in rubric.items if i.item_id not in base_ids],
        base_ids,
        base_items_by_id,
    )

    composed_count = len(base_items) + len(added_items)

    report = ShadowCompositionReport(
        base_item_count=len(base_items),
        call_type_item_count=len(rubric.items),
        composed_item_count=composed_count,
        conflicts=[
            {
                "kind": c.kind,
                "item_id": c.item_id,
                "base_provenance": c.base_provenance,
                "call_type_provenance": c.call_type_provenance,
                "detail": c.detail,
            }
            for c in conflicts
        ],
        added_items=added_items,
        all_logic_items=all_logic_ids,
        empty_role_items=empty_role_ids,
        level_excluded_items=level_excluded_ids,
        suspected_duplicates=suspected,
        call_type=rubric.call_type,
        rubric_id=rubric.rubric_id,
        rubric_version=rubric.rubric_version,
        deployment_context=rubric.deployment_context,
        composed_at=composed_at,
    )

    _log_shadow_composition(report)
    return report


def _log_shadow_composition(report: ShadowCompositionReport) -> None:
    log.debug(
        "shadow_composition [%s] base=%d call_type=%d composed=%d conflicts=%d added=%d "
        "all_logic=%d empty_roles=%d level_excluded=%d suspected_dups=%d",
        report.call_type,
        report.base_item_count,
        report.call_type_item_count,
        report.composed_item_count,
        len(report.conflicts),
        len(report.added_items),
        len(report.all_logic_items),
        len(report.empty_role_items),
        len(report.level_excluded_items),
        len(report.suspected_duplicates),
    )
    for c in report.conflicts:
        log.warning(
            "shadow_composition [%s] CONFLICT kind=%s item=%s | %s",
            report.call_type, c["kind"], c["item_id"], c["detail"],
        )
    for dup in report.suspected_duplicates:
        log.debug(
            "shadow_composition [%s] suspected_duplicate call_type=%s similar_to=%s score=%.2f",
            report.call_type, dup["call_type_id"], dup["similar_to_id"], dup["jaccard_score"],
        )
    if report.level_excluded_items:
        log.debug(
            "shadow_composition [%s] level_excluded items (not applicable to provider level): %s",
            report.call_type, report.level_excluded_items,
        )


# ── F2b: Active composition ───────────────────────────────────────────────────


@dataclass
class ComposedChecklist:
    """
    Output of compose_active_checklist(). The merged checklist and its audit trail.

    items: merged list of ChecklistItems (base + call_type_rubric, after overlay ops).
    overlay_audit: one entry per overlay op applied, for 'why was this item not scored?' answers.
    """
    items: list  # list[ChecklistItem] — imported at call time to avoid circular import
    overlay_audit: list[dict]


def _resolved_req_to_tier1_spec(req: ResolvedEvidenceRequirement) -> Any:
    """Convert one ResolvedEvidenceRequirement to a TierOneMatchSpec."""
    from app.checklist import TierOneMatchSpec
    source_required = any(role in _STRUCTURED_SOURCE_ONLY_ROLES for role in req.original_source_roles)
    eligible_sources = req.resolved_sources if req.resolved_sources else (
        ["__unresolved_required_source__"] if source_required else None
    )
    return TierOneMatchSpec(
        source=req.type,
        finding_type=req.finding_type,
        finding_key_pattern=req.key_pattern,
        finding_value_pattern=req.value_pattern,
        eligible_sources=eligible_sources,
        require_source=source_required,
        intervention_key=req.intervention_key,
        intervention_keys=req.intervention_keys,
        event_type=req.event_type,
        event_key_pattern=req.event_key_pattern,
        scene_entry_path=req.scene_entry_path,
        absence_intervention_key=req.absence_intervention_key,
    )


def _rubric_item_to_checklist_item(ct_item: ResolvedChecklistItem) -> Any:
    """
    Convert a ResolvedChecklistItem to a ChecklistItem for the scoring engine.

    For requirement_logic='any': first non-finding-only requirement becomes tier1_match.
    For requirement_logic='all': all requirements become tier1_matches (AND semantics).
    Items with no evidence_requirements that resolve to a valid tier1 spec fall back
    to tier2_patterns only (allowed_tiers=[2]).
    """
    from app.checklist import ChecklistItem, TimingConstraint

    specs = [_resolved_req_to_tier1_spec(req) for req in ct_item.evidence_requirements]
    structured_source_only = any(
        role in _STRUCTURED_SOURCE_ONLY_ROLES
        for req in ct_item.evidence_requirements
        for role in req.original_source_roles
    )

    if ct_item.requirement_logic == "all" and len(specs) >= 2:
        tier1_match = None
        tier1_matches = specs
        tier1_alternatives = []
        # "all" items are Tier 1 structured evidence only. A flat transcript regex
        # (Tier 2) cannot substitute for independent structured evidence per
        # sub-requirement. tier2_patterns are preserved on the item for reference
        # and display but will not be used for scoring — see adjudicate() guard.
        allowed_tiers = [1]
        preferred_tier = 1
    elif structured_source_only and specs:
        tier1_match = specs[0]
        tier1_matches = []
        tier1_alternatives = []
        # Challenge-gated findings must come from structured evidence with an
        # approved source. Transcript fallback would let AI/free-text leaks
        # satisfy the item and defeat the challenge boundary.
        allowed_tiers = [1]
        preferred_tier = 1
    elif specs:
        tier1_match = specs[0]
        tier1_matches = []
        # For "any" items with multiple evidence requirements, store the remaining
        # specs as alternatives — tried in order before falling to Tier 2.
        tier1_alternatives = specs[1:] if len(specs) > 1 else []
        allowed_tiers = [1, 2]
        preferred_tier = 1
    else:
        tier1_match = None
        tier1_matches = []
        tier1_alternatives = []
        allowed_tiers = [2]
        preferred_tier = 2

    return ChecklistItem(
        id=ct_item.item_id,
        description=ct_item.description,
        category=ct_item.category,
        subtype=ct_item.subtype,
        point_value=ct_item.point_value,
        required=ct_item.required,
        applicable_levels=ct_item.applicable_levels,
        applicable_if=ct_item.applicable_if or None,
        provenance="call_type_rubric",
        tier1_match=tier1_match,
        tier1_matches=tier1_matches,
        tier1_alternatives=tier1_alternatives,
        requirement_logic=ct_item.requirement_logic,
        timing_constraint=(
            TimingConstraint(**ct_item.timing_constraints[0])
            if ct_item.timing_constraints
            else None
        ),
        tier2_patterns=ct_item.tier2_patterns,
        allowed_tiers=allowed_tiers,
        preferred_tier=preferred_tier,
        done_feedback=ct_item.done_feedback or None,
        missed_feedback=ct_item.missed_feedback or None,
    )


def compose_active_checklist(
    base_items: list,              # list[ChecklistItem]
    rubric: ResolvedRubric,
    provider_level: str,
    overlay_ops: list[dict] | None = None,  # serialised OverlayOperation dicts
    overlay_id: str = "",
    scenario: dict | None = None,
) -> ComposedChecklist:
    """
    Build the active composed checklist: base items + call-type rubric items,
    with overlay ops applied and an audit trail per affected item.

    Rules:
    - Items whose applicable_levels exclude provider_level are skipped (not scored).
    - Duplicate IDs (call-type item ID already in base) are skipped with a WARNING —
      they should be resolved via explicit overlay suppress/modify ops, not silent drop.
    - suppress_item removes a call-type item from the composed list and records an audit entry.
    - modify_item patches point_value/required/applicable_levels on the resolved item.
    - add_to_item appends tier2_patterns and/or evidence_requirements.
    - add_item introduces a new item with provenance='overlay'.

    overlay_ops and overlay_id are optional — when absent, base NASEMSO rubric is used as-is.
    """
    ops_by_item_id: dict[str, dict] = {}
    add_ops: list[dict] = []
    overlay_audit: list[dict] = []

    for op in (overlay_ops or []):
        op_type = op.get("op")
        if op_type in ("suppress_item", "modify_item", "add_to_item"):
            ops_by_item_id[op["item_id"]] = op
        elif op_type == "add_item":
            add_ops.append(op)

    base_ids: set[str] = {item.id for item in base_items}
    result_items: list = list(base_items)

    for ct_item in rubric.items:
        iid = ct_item.item_id
        op = ops_by_item_id.get(iid)

        if op and op["op"] == "suppress_item":
            overlay_audit.append({
                "item_id": iid,
                "operation": "suppress_item",
                "overlay_id": overlay_id,
                "reason": op.get("reason", ""),
                "protocol_ref": op.get("protocol_ref", ""),
                "approved_by": op.get("approved_by", ""),
            })
            log.debug("compose_active [%s] suppressed item=%s (overlay=%s)", rubric.call_type, iid, overlay_id)
            continue

        if iid in base_ids:
            log.warning(
                "compose_active [%s] SKIP item=%s — ID collision with base checklist. "
                "Use suppress/modify overlay ops to resolve intentionally.",
                rubric.call_type, iid,
            )
            continue

        if ct_item.applicable_levels and provider_level not in ct_item.applicable_levels:
            log.debug("compose_active [%s] level_excluded item=%s (level=%s)", rubric.call_type, iid, provider_level)
            continue

        # Apply modify_item patches before conversion
        if op and op["op"] == "modify_item":
            changes = op.get("changes", {})
            if "point_value" in changes:
                ct_item = _patch_ct_item(ct_item, point_value=changes["point_value"])
            if "required" in changes:
                ct_item = _patch_ct_item(ct_item, required=changes["required"])
            if "applicable_levels" in changes:
                ct_item = _patch_ct_item(ct_item, applicable_levels=changes["applicable_levels"])
            overlay_audit.append({
                "item_id": iid,
                "operation": "modify_item",
                "overlay_id": overlay_id,
                "reason": op.get("reason", ""),
                "protocol_ref": op.get("protocol_ref", ""),
                "changes": changes,
            })

        # Apply add_to_item patches
        if op and op["op"] == "add_to_item":
            extra_patterns = op.get("append_tier2_patterns", [])
            extra_reqs = op.get("append_evidence_requirements", [])
            if extra_patterns:
                ct_item = _patch_ct_item(ct_item, tier2_patterns=ct_item.tier2_patterns + extra_patterns)
            if extra_reqs:
                # Convert raw overlay req dicts to ResolvedEvidenceRequirement
                resolved_extra = [
                    _resolve_evidence_requirement(r, rubric.items[0].evidence_requirements[0].__class__.__module__
                                                  and {}, rubric.deployment_context)
                    if False else ResolvedEvidenceRequirement(
                        type=r.get("type", "finding"),
                        finding_type=r.get("finding_type"),
                        key_pattern=r.get("key_pattern"),
                        intervention_key=r.get("intervention_key"),
                        intervention_keys=r.get("intervention_keys"),
                        event_type=r.get("event_type"),
                        scene_entry_path=r.get("scene_entry_path"),
                        absence_intervention_key=r.get("absence_intervention_key"),
                    )
                    for r in extra_reqs
                ]
                ct_item = _patch_ct_item(ct_item, evidence_requirements=ct_item.evidence_requirements + resolved_extra)
            overlay_audit.append({
                "item_id": iid,
                "operation": "add_to_item",
                "overlay_id": overlay_id,
                "reason": op.get("reason", ""),
                "protocol_ref": op.get("protocol_ref", ""),
                "appended_patterns": len(extra_patterns),
                "appended_requirements": len(extra_reqs),
            })

        checklist_item = _rubric_item_to_checklist_item(ct_item)
        if scenario is not None:
            from app.checklist import _item_matches_applicability
            if not _item_matches_applicability(checklist_item, scenario):
                log.debug("compose_active [%s] applicability_excluded item=%s", rubric.call_type, iid)
                continue
        result_items.append(checklist_item)

    # Process add_item ops — new jurisdiction-specific items
    for op in add_ops:
        raw_item = op.get("item", {})
        iid = raw_item.get("id", "")
        if not iid or iid in base_ids or any(getattr(i, "id", None) == iid for i in result_items):
            log.warning("compose_active [%s] SKIP add_item id=%s — collision or missing id", rubric.call_type, iid)
            continue
        from app.checklist import ChecklistItem, TierOneMatchSpec
        reqs = raw_item.get("evidence_requirements", [])
        specs = []
        for r in reqs:
            try:
                specs.append(TierOneMatchSpec(
                    source=r["type"],
                    finding_type=r.get("finding_type"),
                    intervention_key=r.get("intervention_key"),
                    intervention_keys=r.get("intervention_keys"),
                    event_type=r.get("event_type"),
                    scene_entry_path=r.get("scene_entry_path"),
                    absence_intervention_key=r.get("absence_intervention_key"),
                ))
            except Exception as exc:
                log.warning("compose_active add_item %s: failed to convert req: %s", iid, exc)
        overlay_item = ChecklistItem(
            id=iid,
            description=raw_item.get("description", ""),
            category=raw_item.get("category", "clinical_performance"),
            subtype=raw_item.get("subtype", "assessment"),
            point_value=raw_item.get("point_value", 0),
            required=raw_item.get("required", "required"),
            applicable_levels=raw_item.get("applicable_levels", []),
            applicable_if=raw_item.get("applicable_if") or None,
            provenance="overlay",
            tier1_match=specs[0] if len(specs) == 1 else None,
            tier1_matches=specs if len(specs) > 1 else [],
            tier2_patterns=raw_item.get("tier2_patterns", []),
            allowed_tiers=[1, 2] if specs else [2],
            preferred_tier=1 if specs else 2,
            done_feedback=raw_item.get("done_feedback") or None,
            missed_feedback=raw_item.get("missed_feedback") or None,
        )
        if scenario is not None:
            from app.checklist import _item_matches_applicability
            if not _item_matches_applicability(overlay_item, scenario):
                log.debug("compose_active [%s] applicability_excluded add_item=%s", rubric.call_type, iid)
                continue
        result_items.append(overlay_item)
        overlay_audit.append({
            "item_id": iid,
            "operation": "add_item",
            "overlay_id": overlay_id,
            "reason": op.get("reason", ""),
            "protocol_ref": op.get("protocol_ref", ""),
        })

    return ComposedChecklist(items=result_items, overlay_audit=overlay_audit)


def _patch_ct_item(item: ResolvedChecklistItem, **kwargs) -> ResolvedChecklistItem:
    """Return a new ResolvedChecklistItem with the given fields replaced."""
    from dataclasses import replace
    return replace(item, **kwargs)
