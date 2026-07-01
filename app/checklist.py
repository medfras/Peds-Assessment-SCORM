"""
Unified checklist schema — §6 of SCORING_ENGINE_ARCHITECTURE.md.

This module defines the authoritative data contracts for the scoring engine.
No scoring logic lives here; this is the type layer only.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator


CURRENT_SCHEMA_VERSION = "1.0"

_BASE_RUBRIC_VERSIONS: dict[str, str] = {
    "nremt_e202_medical_v1": "2026.05",
    "nremt_trauma_v1": "2026.05",
    "nremt_cardiac_arrest_aed_v1": "2026.05",
    "nrp_newborn_v1": "2026.05",
}

# ── Tier 1 match specification ────────────────────────────────────────────────


class TierOneMatchSpec(BaseModel):
    """
    Tells the adjudicator how to satisfy this item from structured backend records.

    source taxonomy:
      intervention   — Intervention.name == intervention_key
      finding        — SessionFinding with matching finding_type and key_pattern
      session_event  — SessionEvent with matching event_type and optional key pattern
      post_intervention_finding — SessionFinding captured after the first intervention
      scene_entry    — value present at scene_entry_path (dot-separated) in scene_entry JSONB
      absence_check  — satisfied when absence_intervention_key is NOT in the intervention table
                       (used for scope-violation items like 'no IV/IO attempted')
      no_out_of_scope_actions
                    — satisfied when no out-of-scope medication/procedure was applied
                       or commanded by the student
    """

    source: Literal[
        "intervention",
        "finding",
        "post_intervention_finding",
        "session_event",
        "scene_entry",
        "absence_check",
        "no_out_of_scope_actions",
    ]
    # intervention
    intervention_key: Optional[str] = None
    intervention_keys: Optional[list[str]] = None
    # finding
    finding_type: Optional[str] = None        # "vital" | "exam" | "history"
    finding_key_pattern: Optional[str] = None # regex matched against SessionFinding.key
    finding_value_pattern: Optional[str] = None # optional regex matched against SessionFinding.value
    eligible_sources: Optional[list[str]] = None  # if set, only findings with matching source qualify;
                                                   # NULL-source findings pass unless require_source=True
    require_source: bool = False                  # challenge-gated items require a concrete source match
    # traceability
    protocol_refs: Optional[list[str]] = None  # IDs of protocol_refs entries that mandate this match
    # session_event
    event_type: Optional[str] = None
    event_key_pattern: Optional[str] = None
    event_data_result: Optional[str] = None
    # scene_entry
    scene_entry_path: Optional[str] = None    # e.g. "ppe.required_complete"
    # absence_check
    absence_intervention_key: Optional[str] = None

ItemSubtype = Literal[
    "scene_entry",
    "assessment",
    "screen",
    "intervention",
    "reassessment",
    "transport",
    "documentation_handoff",
    "documentation_narrative",
    "professionalism",
]

ItemCategory = Literal[
    "clinical_performance",
    "protocols_treatment",
    "scope_adherence",
    "documentation",
    "professionalism",
]

ItemProvenance = Literal[
    "universal_base",
    "base_patient_care_rubric",
    "call_type_rubric",
    "overlay",
    "scenario_overlay",
    "protocol_scope",
]

ItemRequired = Literal["required", "optional", "bonus"]

ItemState = Literal[
    "satisfied",
    "partial",
    "not_satisfied",
    "contradicted",
    "unsupported_by_run",
    "not_applicable",
    "ambiguous",
]

ScoreMethod = Literal["deterministic", "legacy_ai"]


# ── Supporting types ──────────────────────────────────────────────────────────


class PartialCreditRule(BaseModel):
    """One of three bounded partial-credit models — §8."""

    model: Literal["subcriteria", "fixed_partial", "percentage_bands"]
    # subcriteria: named sub-elements each worth a fraction of point_value
    subcriteria: Optional[list[dict[str, Any]]] = None
    # fixed_partial: single score applied whenever item is partially met
    partial_score: Optional[int] = None
    # percentage_bands: thresholds map to defined scores
    bands: Optional[list[dict[str, Any]]] = None

    @model_validator(mode="after")
    def _validate_model_data(self) -> "PartialCreditRule":
        if self.model == "subcriteria" and not self.subcriteria:
            raise ValueError("subcriteria model requires subcriteria list")
        if self.model == "fixed_partial" and self.partial_score is None:
            raise ValueError("fixed_partial model requires partial_score")
        if self.model == "percentage_bands" and not self.bands:
            raise ValueError("percentage_bands model requires bands list")
        return self


class TimingConstraint(BaseModel):
    """Sequence-aware constraint — §9."""

    type: Literal["within_minutes", "before_item", "after_item", "ordered_set"]
    value: Optional[int] = None                # minutes; used by within_minutes
    reference_item_id: Optional[str] = None    # used by before_item / after_item
    items: Optional[list[str]] = None          # used by ordered_set
    violation_consequence: Literal["partial", "deduction_override", "informational"] = "informational"

    @model_validator(mode="after")
    def _validate_constraint_data(self) -> "TimingConstraint":
        if self.type == "within_minutes" and self.value is None:
            raise ValueError("within_minutes requires value (minutes)")
        if self.type in ("before_item", "after_item") and not self.reference_item_id:
            raise ValueError(f"{self.type} requires reference_item_id")
        if self.type == "ordered_set" and not self.items:
            raise ValueError("ordered_set requires items list")
        return self


class ApplicabilityFilter(BaseModel):
    """Optional structured applicability filter — §5.3 / §6.2."""

    scenario_category_in: Optional[list[str]] = None
    turnover_target_in: Optional[list[str]] = None
    scenario_id_in: Optional[list[str]] = None
    non_transport_agency: Optional[bool] = None
    als_codispatched: Optional[bool] = None
    spinal_injury_possible: Optional[bool] = None
    multiple_patients_possible: Optional[bool] = None
    additional_help_needed: Optional[bool] = None
    opqrst_radiation_relevant: Optional[bool] = None
    diagnostics_indicated: Optional[bool] = None


# ── Core schema ───────────────────────────────────────────────────────────────


class ChecklistItem(BaseModel):
    """
    Universal scored item — §6.2.

    Every scored element of a scenario is an instance of this model.
    Subtype preserves semantic structure; category determines which score
    bucket receives points.

    Once an id is in production use it is permanent — items are deprecated,
    never deleted (§6.4).
    """

    id: str
    description: str
    subtype: ItemSubtype
    category: ItemCategory
    provenance: ItemProvenance = "scenario_overlay"
    point_value: int
    partial_credit_rule: Optional[PartialCreditRule] = None
    required: ItemRequired = "required"
    # Empty list = all levels eligible.
    applicable_levels: list[str] = []
    # MCA expansion ID required for this item to apply.
    requires_mca_expansion: Optional[str] = None
    # true = all agencies; false = no agencies; list = specific agency IDs.
    agency_applicable: Union[bool, list[str]] = True
    # Optional structured filter used by inherited rubric items.
    applicable_if: Optional[ApplicabilityFilter] = None
    timing_constraint: Optional[TimingConstraint] = None
    # Explicit tier list — [1], [1,2], or [1,2,3].
    allowed_tiers: list[int] = [1, 2]
    # Which tier should resolve this item in the normal case.
    preferred_tier: int = 1
    # Tier 3 must be explicitly opted in per item.
    tier3_permitted: bool = False
    tier3_confidence_threshold: Optional[float] = None
    critical_failure: bool = False
    critical_failure_label: Optional[str] = None
    schema_version: str = CURRENT_SCHEMA_VERSION
    deprecated: bool = False
    # ── Match specs (Phase 4 / Phase 5) ───────────────────────────────────────
    # tier1_match: how to satisfy this item from structured Tier 1 records.
    # Required for items with preferred_tier=1. Populated per-item in scenario JSON.
    tier1_match: Optional[TierOneMatchSpec] = None
    # tier1_matches: multiple match specs for requirement_logic="all" items.
    # Each spec must be independently satisfied. Ignored when requirement_logic="any".
    tier1_matches: list[TierOneMatchSpec] = Field(default_factory=list)
    # tier1_alternatives: additional Tier 1 specs tried in order for "any" items with
    # multiple evidence_requirements. Any one match satisfies the item. Populated by
    # rubric_loader for call-type rubric items; not used by hand-authored checklist items.
    tier1_alternatives: list[TierOneMatchSpec] = Field(default_factory=list)
    # requirement_logic: "any" (default, OR) — first satisfied tier1_match wins.
    # "all" (AND) — every spec in tier1_matches must be independently satisfied.
    # Existing items without tier1_matches are unaffected (default "any").
    requirement_logic: Literal["any", "all"] = "any"
    # tier2_patterns: regex list for transcript matching. Any match = satisfied.
    # Phase 3 will add positive/negative samples for CI validation.
    tier2_patterns: list[str] = []
    # Protocol citations that mandate this item — traceable to source authority.
    protocol_refs: Optional[list[str]] = None
    # ── Debrief display metadata (Phase 3 / Group E) ───────────────────────────
    # Authored per-item text for the deterministic debrief renderer.
    # When present, the renderer uses these instead of asking the LLM to generate
    # per-item explanations. Required on all scenario-authored required items before
    # the deterministic debrief renderer is activated (Phase 3 E3).
    done_feedback: Optional[str] = None      # shown when item is credited
    missed_feedback: Optional[str] = None    # shown when item is missed
    clinical_rationale: Optional[str] = None # the clinical why behind this item
    common_error: Optional[str] = None       # what students typically get wrong

    @field_validator("point_value")
    @classmethod
    def _point_value_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("point_value must be >= 0")
        return v

    @field_validator("allowed_tiers")
    @classmethod
    def _allowed_tiers_valid(cls, v: list[int]) -> list[int]:
        for t in v:
            if t not in (1, 2, 3):
                raise ValueError(f"tier {t} is not valid; allowed_tiers must be a subset of [1, 2, 3]")
        return v

    @field_validator("preferred_tier")
    @classmethod
    def _preferred_tier_valid(cls, v: int) -> int:
        if v not in (1, 2, 3):
            raise ValueError("preferred_tier must be 1, 2, or 3")
        return v

    @model_validator(mode="after")
    def _tier3_consistency(self) -> "ChecklistItem":
        if self.tier3_permitted and 3 not in self.allowed_tiers:
            raise ValueError("tier3_permitted=True requires 3 in allowed_tiers")
        if not self.tier3_permitted and 3 in self.allowed_tiers:
            raise ValueError("tier3_permitted must be True when 3 is in allowed_tiers")
        if self.tier3_permitted and self.tier3_confidence_threshold is None:
            raise ValueError("tier3_permitted=True requires tier3_confidence_threshold")
        return self

    @model_validator(mode="after")
    def _preferred_tier_in_allowed(self) -> "ChecklistItem":
        if self.allowed_tiers and self.preferred_tier not in self.allowed_tiers:
            raise ValueError(
                f"preferred_tier {self.preferred_tier} not in allowed_tiers {self.allowed_tiers}"
            )
        return self


# ── Adjudication output types ─────────────────────────────────────────────────


class EvidenceReference(BaseModel):
    """Single piece of evidence supporting an item state — §10."""

    tier: int
    source_type: Literal[
        "intervention_record",
        "session_finding",
        "post_intervention_finding",
        "session_finding_text",
        "scene_entry",
        "session_event",
        "transcript_match",
        "submitted_document_text",
        "absence_check",
        "scope_guardrail",
    ]
    source_id: Optional[Union[str, int]] = None
    timestamp: Optional[str] = None          # ISO-8601
    matched_text: Optional[str] = None       # Tier 2 / Tier 3 matched span
    confidence: Optional[float] = None       # Tier 3 logprob-derived confidence
    document_type: Optional[str] = None      # "dmist" | "narrative" for submitted_document_text


class ChecklistItemState(BaseModel):
    """
    Runtime state of a single checklist item after the satisfaction cascade — §7.

    This is the engine's factual output (part of AdjudicationSnapshot).
    It is never authored directly — always produced by scoring_service.adjudicate().
    """

    item_id: str
    state: ItemState
    earned_points: int = 0
    evidence_references: list[EvidenceReference] = []
    timing_violation: Optional[bool] = None
    critical_failure_triggered: bool = False
    notes: Optional[str] = None # diagnostics for ambiguous / special states


class CategoryScore(BaseModel):
    """
    Per-category bounded score totals (ScoreSnapshot) — §11, §18 Phase 4.

    `total` is null for legacy_ai categories — consumers MUST check `method`
    before using `total`. Skipping the check and treating null as zero is a bug.
    """

    earned: Optional[int] = None
    deducted: Optional[int] = None
    total: Optional[int] = None    # null until deterministic scoring for this category
    max: int
    method: ScoreMethod
    pending: bool = False         # True = excluded from totals, thresholds, rewards

    @model_validator(mode="after")
    def _legacy_ai_must_be_null(self) -> "CategoryScore":
        if self.method == "legacy_ai" and self.total is not None:
            raise ValueError("legacy_ai categories must have total=null; check method before use")
        return self


class EffectiveContext(BaseModel):
    """
    Resolved session context — §5.

    Computed once at session start and persisted so all scoring phases
    operate against the same resolved parameters.
    """

    session_id: str
    provider_level: str
    agency_id: Optional[str] = None
    mca: str
    resolved_at: str               # ISO-8601 timestamp
    checklist_item_count: int = 0  # number of items in the effective checklist
    base_patient_care_rubric: Optional[str] = None
    base_patient_care_rubric_version: Optional[str] = None
    # "training" (simulator) or "qaqi" (real-call QA/QI) — drives source role resolution.
    deployment_context: str = "training"


# ── Context resolution ────────────────────────────────────────────────────────


def _base_item(
    item_id: str,
    description: str,
    point_value: int,
    scenario_categories: list[str],
    *,
    subtype: str = "assessment",
    allowed_tiers: Optional[list[int]] = None,
    preferred_tier: int = 2,
    tier1_match: Optional[dict[str, Any]] = None,
    tier1_matches: Optional[list[dict[str, Any]]] = None,
    requirement_logic: str = "any",
    tier2_patterns: Optional[list[str]] = None,
    critical_failure: bool = False,
    critical_failure_label: Optional[str] = None,
    applicable_if: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Create an inherited NREMT-style base patient-care checklist item."""
    if allowed_tiers is None:
        allowed_tiers = [1, 2] if (tier1_match or tier1_matches) else [2]
    applicability = {"scenario_category_in": scenario_categories}
    if applicable_if:
        applicability.update(applicable_if)
    return {
        "id": item_id,
        "description": description,
        "subtype": subtype,
        "category": "clinical_performance",
        "provenance": "base_patient_care_rubric",
        "point_value": point_value,
        "allowed_tiers": allowed_tiers,
        "preferred_tier": preferred_tier,
        "tier3_permitted": False,
        "tier1_match": tier1_match,
        "tier1_matches": tier1_matches or [],
        "requirement_logic": requirement_logic,
        "tier2_patterns": tier2_patterns or [],
        "critical_failure": critical_failure,
        "critical_failure_label": critical_failure_label,
        "applicable_if": applicability,
    }


_MEDICAL_CATS = ["adult_medical", "pediatric_medical"]
_TRAUMA_CATS = ["adult_trauma", "pediatric_trauma"]
_CARDIAC_ARREST_CATS = ["adult_medical", "pediatric_medical", "adult_trauma", "pediatric_trauma"]
_CARDIAC_ARREST_CHALLENGE_MATCH = {
    "source": "session_event",
    "event_type": "challenge_completed",
    "event_key_pattern": r"(?i)^cpr:",
}

_BASE_RUBRIC_REGISTRY: dict[str, list[dict[str, Any]]] = {
    "nremt_cardiac_arrest_aed_v1": [
        _base_item("ems.cardiac_arrest.ppe", "Takes or verbalizes appropriate PPE precautions", 1, _CARDIAC_ARREST_CATS, subtype="scene_entry", allowed_tiers=[1], preferred_tier=1, tier1_match={"source": "scene_entry", "scene_entry_path": "ppe"}, critical_failure=True, critical_failure_label="Failure to take or verbalize appropriate PPE precautions"),
        _base_item("ems.cardiac_arrest.scene_safety", "Determines the scene/situation is safe", 1, _CARDIAC_ARREST_CATS, subtype="scene_entry", allowed_tiers=[1], preferred_tier=1, tier1_match={"source": "scene_entry", "scene_entry_path": "scene_approach"}, critical_failure=True, critical_failure_label="Failure to determine scene safety"),
        _base_item("ems.cardiac_arrest.responsiveness", "Checks patient responsiveness", 1, _CARDIAC_ARREST_CATS, allowed_tiers=[1, 2], preferred_tier=1, tier1_match={"source": "finding", "finding_type": "vital", "finding_key_pattern": r"(?i)(gcs|avpu|loc|mental)"}, tier2_patterns=[r"(?i)(responsive|responsiveness|unresponsive|AVPU|GCS|level of consciousness|LOC)"], critical_failure=True, critical_failure_label="Failure to check responsiveness"),
        _base_item("ems.cardiac_arrest.additional_ems", "Requests additional EMS assistance", 1, _CARDIAC_ARREST_CATS, subtype="transport", tier2_patterns=[r"(?i)(additional EMS|additional help|ALS|\bmedic\b|\bparamedic\b|backup|intercept|more units|request.*help)"], applicable_if={"als_codispatched": False, "additional_help_needed": True}),
        _base_item("ems.cardiac_arrest.breathing_pulse", "Checks breathing and pulse simultaneously for no more than 10 seconds", 1, _CARDIAC_ARREST_CATS, allowed_tiers=[1, 2], preferred_tier=1, tier1_match=_CARDIAC_ARREST_CHALLENGE_MATCH, tier2_patterns=[r"(?i)(breathing.*pulse|pulse.*breathing|check.*pulse|no pulse|pulseless|apneic|not breathing|agonal)"], critical_failure=True, critical_failure_label="Failure to check responsiveness, then check breathing and pulse simultaneously for no more than 10 seconds"),
        _base_item("ems.cardiac_arrest.begin_compressions", "Immediately begins chest compressions once pulselessness is confirmed", 1, _CARDIAC_ARREST_CATS, subtype="intervention", allowed_tiers=[1, 2], preferred_tier=1, tier1_match=_CARDIAC_ARREST_CHALLENGE_MATCH, tier2_patterns=[r"(?i)(start|begin|initiat).*compressions|start CPR|begin CPR|chest compressions"], critical_failure=True, critical_failure_label="Failure to immediately begin chest compressions as soon as pulselessness is confirmed"),
        _base_item("ems.cardiac_arrest.high_quality_cpr", "Performs two minutes of high-quality CPR with adequate depth/rate, correct ratio, recoil, adequate breaths, and minimal interruptions", 5, _CARDIAC_ARREST_CATS, subtype="intervention", allowed_tiers=[1], preferred_tier=1, tier1_match=_CARDIAC_ARREST_CHALLENGE_MATCH, critical_failure=True, critical_failure_label="Failure to demonstrate acceptable high-quality CPR or interrupts CPR for more than 10 seconds"),
        _base_item("ems.cardiac_arrest.two_minute_reassessment", "After two minutes of CPR, reassesses patient and transitions second rescuer to compressions while operating AED", 1, _CARDIAC_ARREST_CATS, subtype="reassessment", allowed_tiers=[1], preferred_tier=1, tier1_match=_CARDIAC_ARREST_CHALLENGE_MATCH),
        _base_item("ems.cardiac_arrest.aed_power", "Turns on power to AED", 1, _CARDIAC_ARREST_CATS, subtype="intervention", allowed_tiers=[1], preferred_tier=1, tier1_match=_CARDIAC_ARREST_CHALLENGE_MATCH, critical_failure=True, critical_failure_label="Failure to operate the AED properly"),
        _base_item("ems.cardiac_arrest.aed_attach", "Follows prompts and correctly attaches AED to patient", 1, _CARDIAC_ARREST_CATS, subtype="intervention", allowed_tiers=[1], preferred_tier=1, tier1_match=_CARDIAC_ARREST_CHALLENGE_MATCH, critical_failure=True, critical_failure_label="Failure to correctly attach the AED to the patient"),
        _base_item("ems.cardiac_arrest.clear_analysis", "Stops CPR and ensures all individuals are clear during rhythm analysis", 1, _CARDIAC_ARREST_CATS, subtype="intervention", allowed_tiers=[1], preferred_tier=1, tier1_match=_CARDIAC_ARREST_CHALLENGE_MATCH, critical_failure=True, critical_failure_label="Failure to ensure that all individuals are clear of patient during rhythm analysis"),
        _base_item("ems.cardiac_arrest.deliver_shock", "Ensures all individuals are clear and delivers shock from AED when indicated", 1, _CARDIAC_ARREST_CATS, subtype="intervention", allowed_tiers=[1], preferred_tier=1, tier1_match=_CARDIAC_ARREST_CHALLENGE_MATCH, critical_failure=True, critical_failure_label="Failure to deliver shock in a timely manner or failure to ensure all individuals are clear before shock"),
        _base_item("ems.cardiac_arrest.resume_compressions", "Immediately directs rescuer to resume chest compressions after shock or no-shock decision", 1, _CARDIAC_ARREST_CATS, subtype="intervention", allowed_tiers=[1], preferred_tier=1, tier1_match=_CARDIAC_ARREST_CHALLENGE_MATCH, critical_failure=True, critical_failure_label="Failure to immediately resume compressions after shock delivered"),
    ],
    "nrp_newborn_v1": [
        _base_item("ems.nrp.ppe", "Takes or verbalizes appropriate PPE precautions", 1, _CARDIAC_ARREST_CATS, subtype="scene_entry", allowed_tiers=[1], preferred_tier=1, tier1_match={"source": "scene_entry", "scene_entry_path": "ppe"}, critical_failure=True, critical_failure_label="Failure to take or verbalize appropriate PPE precautions"),
        _base_item("ems.nrp.scene_safety", "Determines the scene/situation is safe", 1, _CARDIAC_ARREST_CATS, subtype="scene_entry", allowed_tiers=[1], preferred_tier=1, tier1_match={"source": "scene_entry", "scene_entry_path": "scene_approach"}, critical_failure=True, critical_failure_label="Failure to determine scene safety"),
        _base_item("ems.nrp.responsiveness", "Checks newborn tone, cry, and breathing effort", 1, _CARDIAC_ARREST_CATS, allowed_tiers=[1, 2], preferred_tier=1, tier1_match={"source": "finding", "finding_type": "vital", "finding_key_pattern": r"(?i)(gcs|avpu|loc|mental|tone|cry|respiratory|effort)"}, tier2_patterns=[r"(?i)(responsive|unresponsive|tone|cry|respiratory effort|no cry|limp|AVPU|GCS|level of consciousness)"], critical_failure=True, critical_failure_label="Failure to assess newborn tone, cry, and breathing effort"),
        _base_item("ems.nrp.additional_ems", "Requests additional EMS assistance", 1, _CARDIAC_ARREST_CATS, subtype="transport", tier2_patterns=[r"(?i)(additional EMS|additional help|ALS|\bmedic\b|\bparamedic\b|backup|intercept|more units|request.*help)"], applicable_if={"als_codispatched": False, "additional_help_needed": True}),
        _base_item("ems.nrp.breathing_hr", "Assesses breathing and heart rate within 10 seconds of identifying non-vigorous newborn", 1, _CARDIAC_ARREST_CATS, allowed_tiers=[1, 2], preferred_tier=1, tier1_match=_CARDIAC_ARREST_CHALLENGE_MATCH, tier2_patterns=[r"(?i)(breathing.*heart rate|heart rate.*breathing|HR|auscult|no breathing|apneic|not breathing|bradycard|below 60)"], critical_failure=True, critical_failure_label="Failure to assess breathing and heart rate within 10 seconds"),
        _base_item("ems.nrp.begin_compressions", "Begins 3:1 coordinated compressions once HR confirmed below 60 bpm despite effective PPV", 1, _CARDIAC_ARREST_CATS, subtype="intervention", allowed_tiers=[1, 2], preferred_tier=1, tier1_match=_CARDIAC_ARREST_CHALLENGE_MATCH, tier2_patterns=[r"(?i)(3:1|compress|start CPR|begin CPR|chest compressions|below 60)"], critical_failure=True, critical_failure_label="Failure to immediately begin 3:1 compressions when HR is below 60 bpm despite effective PPV"),
        _base_item("ems.nrp.high_quality_nrp", "Performs two minutes of high-quality NRP: 3:1 ratio, coordinated ventilations, adequate rate, and minimal interruptions", 5, _CARDIAC_ARREST_CATS, subtype="intervention", allowed_tiers=[1], preferred_tier=1, tier1_match=_CARDIAC_ARREST_CHALLENGE_MATCH, critical_failure=True, critical_failure_label="Failure to perform acceptable high-quality NRP or interrupts compressions for more than 10 seconds"),
        _base_item("ems.nrp.rhythm_reassessment", "After two minutes of NRP, pauses for heart rate reassessment and rhythm check", 1, _CARDIAC_ARREST_CATS, subtype="reassessment", allowed_tiers=[1], preferred_tier=1, tier1_match=_CARDIAC_ARREST_CHALLENGE_MATCH),
        _base_item("ems.nrp.monitor_attach", "Attaches cardiac monitor leads for rhythm assessment", 1, _CARDIAC_ARREST_CATS, subtype="intervention", allowed_tiers=[1], preferred_tier=1, tier1_match=_CARDIAC_ARREST_CHALLENGE_MATCH, critical_failure=True, critical_failure_label="Failure to attach cardiac monitor for rhythm assessment"),
        _base_item("ems.nrp.clear_during_analysis", "Minimizes motion and clears field during rhythm analysis", 1, _CARDIAC_ARREST_CATS, subtype="intervention", allowed_tiers=[1], preferred_tier=1, tier1_match=_CARDIAC_ARREST_CHALLENGE_MATCH, critical_failure=True, critical_failure_label="Failure to minimize motion or clear field during rhythm analysis"),
        _base_item("ems.nrp.rhythm_treatment", "Correctly responds to rhythm — delivers indicated treatment or confirms non-shockable and proceeds", 1, _CARDIAC_ARREST_CATS, subtype="intervention", allowed_tiers=[1], preferred_tier=1, tier1_match=_CARDIAC_ARREST_CHALLENGE_MATCH),
        _base_item("ems.nrp.resume_after_rhythm", "Immediately resumes coordinated 3:1 compressions and ventilations after rhythm decision", 1, _CARDIAC_ARREST_CATS, subtype="intervention", allowed_tiers=[1], preferred_tier=1, tier1_match=_CARDIAC_ARREST_CHALLENGE_MATCH, critical_failure=True, critical_failure_label="Failure to immediately resume compressions and ventilations after rhythm decision"),
    ],
    "nremt_e202_medical_v1": [
        _base_item("ems.medical.ppe", "Takes or verbalizes appropriate PPE precautions", 1, _MEDICAL_CATS, subtype="scene_entry", allowed_tiers=[1], preferred_tier=1, tier1_match={"source": "scene_entry", "scene_entry_path": "ppe"}, critical_failure=True, critical_failure_label="Failure to take or verbalize appropriate PPE precautions"),
        _base_item("ems.medical.scene_safety", "Determines the scene/situation is safe before patient contact", 1, _MEDICAL_CATS, subtype="scene_entry", allowed_tiers=[1], preferred_tier=1, tier1_match={"source": "scene_entry", "scene_entry_path": "scene_approach"}, critical_failure=True, critical_failure_label="Failure to determine scene safety before approaching patient"),
        _base_item("ems.medical.noi_moi", "Determines mechanism of injury or nature of illness", 1, _MEDICAL_CATS, allowed_tiers=[1, 2], preferred_tier=1, tier1_match={"source": "session_event", "event_type": "challenge_completed", "event_key_pattern": r"(?i)^impression:"}, tier2_patterns=[r"(?i)(nature of illness|NOI|mechanism|MOI|what happened|what'?s going on|what is going on|why.*called|dispatch|complaint|primary problem|medical problem|diabetic|hypoglyc|low blood sugar|altered|not acting right)"]),
        _base_item("ems.medical.patient_count", "Determines number of patients", 1, _MEDICAL_CATS, tier2_patterns=[r"(?i)(number of patients|how many patients|anyone else|only patient|one patient|single patient)"], applicable_if={"multiple_patients_possible": True}),
        _base_item("ems.medical.patient_name", "Obtains or verifies patient name", 1, _MEDICAL_CATS, tier1_match={"source": "finding", "finding_type": "history", "finding_key_pattern": r"(?i)^(?:patient\s+|pt\s+)?name$"}, tier2_patterns=[r"(?i)(?:patient'?s?\s+name|what'?s\s+(?:your|his|her|their)\s+name|what\s+is\s+(?:your|his|her|their)\s+name|who\s+is\s+(?:he|she|the patient)|name\s+and\s+(?:date of birth|dob|age))"]),
        _base_item("ems.medical.patient_age_dob", "Obtains or verifies patient age or date of birth", 1, _MEDICAL_CATS, tier1_match={"source": "finding", "finding_type": "history", "finding_key_pattern": r"(?i)^(?:patient\s+|pt\s+)?(?:age|date\s+of\s+birth|dob|birth\s*date)$"}, tier2_patterns=[r"(?i)(?:date\s+of\s+birth|DOB|birth\s*date|birthday|how\s+old|age|when\s+was\s+(?:he|she|the patient)\s+born|name\s+and\s+(?:date of birth|dob|age))"]),
        _base_item("ems.medical.additional_help", "Requests additional help if necessary", 1, _MEDICAL_CATS, subtype="transport", tier2_patterns=[r"(?i)(additional help|additional resources|ALS|\bmedic\b|backup|intercept|fire|police|PD|more units)"], applicable_if={"als_codispatched": False, "additional_help_needed": True}),
        _base_item("ems.medical.spine_considered", "Considers stabilization of the spine", 1, _MEDICAL_CATS, tier1_match={"source": "intervention", "intervention_key": "smr"}, tier2_patterns=[r"(?i)(c.?spine|spinal|spine|neck stabilization|manual stabilization|trauma|fall|mechanism)"], applicable_if={"spinal_injury_possible": True}),
        _base_item("ems.medical.general_impression", "Forms or states general impression of the patient", 1, _MEDICAL_CATS, allowed_tiers=[1, 2], preferred_tier=1, tier1_match={"source": "scene_entry", "scene_entry_path": "pat_assessment"}, tier2_patterns=[r"(?i)(general impression|sick|not sick|ill appearing|toxic|stable|unstable|critical|distress)"]),
        _base_item("ems.medical.loc", "Determines responsiveness or level of consciousness", 1, _MEDICAL_CATS, tier1_match={"source": "finding", "finding_type": "vital", "finding_key_pattern": r"(?i)(gcs|avpu|loc|mental)", "eligible_sources": ["avpu_quick_action"], "require_source": True}, tier2_patterns=[r"(?i)(responsive|responsiveness|LOC|level of consciousness|AVPU|GCS|alert|oriented|orientation|where (?:are|is) (?:you|he|she)|what day|what year|who (?:is|are)|do you know (?:where|what|who))"]),
        _base_item("ems.medical.chief_life_threats", "Determines chief complaint and apparent life threats", 1, _MEDICAL_CATS, allowed_tiers=[1, 2], preferred_tier=1, tier1_match={"source": "session_event", "event_type": "challenge_completed", "event_key_pattern": r"(?i)^impression:"}, tier2_patterns=[r"(?i)(chief complaint|life threat|primary problem|what.*complaint|trouble breathing|pain|seizure|allergic|diabetic|syncope|altered)"]),
        _base_item("ems.medical.airway_breathing_o2", "Assesses airway and breathing, assures adequate ventilation, and initiates appropriate oxygen therapy", 3, _MEDICAL_CATS, tier1_match={"source": "finding", "finding_type": "vital", "finding_key_pattern": r"(?i)(spo2|rr|resp|breath|airway|wob|work of breathing|respiratory effort)"}, tier2_patterns=[r"(?i)(airway|breathing|ventilat|respirations|lung sounds|breath sounds|oxygen|O2|BVM|SpO2)"]),
        _base_item("ems.medical.circulation", "Assesses circulation: major bleeding, skin, and pulse", 3, _MEDICAL_CATS, tier1_match={"source": "finding", "finding_type": "vital", "finding_key_pattern": r"(?i)(pulse|hr|heart|skin|cap|bp)"}, tier2_patterns=[r"(?i)(pulse|circulation|bleeding|skin|color|temperature|condition|cap refill|blood pressure|BP)"]),
        _base_item("ems.medical.priority_transport", "Identifies priority patient and makes transport decision", 1, _MEDICAL_CATS, subtype="transport", tier2_patterns=[r"(?i)(priority|transport|load(?:\\s+and\\s+go)?|load\\s+and\\s+go|hospital|ALS|intercept|critical|unstable)"], applicable_if={"non_transport_agency": False}),
        _base_item("ems.medical.opqrst_onset", "History of present illness: onset obtained", 1, _MEDICAL_CATS, tier1_match={"source": "finding", "finding_type": "exam", "finding_key_pattern": r"(?i)^onset$"}, tier2_patterns=[r"(?i)(onset|when did|when.*start|started|begin|how long)"]),
        _base_item("ems.medical.opqrst_severity", "History of present illness: severity obtained", 1, _MEDICAL_CATS, tier1_match={"source": "finding", "finding_type": "exam", "finding_key_pattern": r"(?i)^severity$"}, tier2_patterns=[r"(?i)(severity|how severe|scale|0.?10|one to ten|how bad|pain score)"]),
        _base_item("ems.medical.opqrst_provocation", "History of present illness: provocation/palliation obtained", 1, _MEDICAL_CATS, tier1_match={"source": "finding", "finding_type": "exam", "finding_key_pattern": r"(?i)^provocation(?:\s*/\s*palliation)?$"}, tier2_patterns=[r"(?i)(provok|provoc|palliat|better|worse|makes.*better|makes.*worse|trigger)"]),
        _base_item("ems.medical.opqrst_time", "History of present illness: time/course obtained", 1, _MEDICAL_CATS, tier1_match={"source": "finding", "finding_type": "exam", "finding_key_pattern": r"(?i)^(?:time|time\s*/\s*course|course)$"}, tier2_patterns=[r"(?i)(time|duration|constant|comes and goes|intermittent|progress|getting worse)"]),
        _base_item("ems.medical.opqrst_quality", "History of present illness: quality obtained", 1, _MEDICAL_CATS, tier1_match={"source": "finding", "finding_type": "exam", "finding_key_pattern": r"(?i)^quality$"}, tier2_patterns=[r"(?i)(quality|describe|sharp|dull|pressure|tight|burning|bark|wheeze|stridor)"]),
        _base_item("ems.medical.associated_symptoms", "Clarifies associated signs and symptoms related to OPQRST", 2, _MEDICAL_CATS, tier2_patterns=[r"(?i)(associated|other\s+(?:signs?(?:\s+(?:or|and)\s+symptoms?)?|symptoms?)|signs?\s+(?:or|and)\s+symptoms?|anything else|nausea|vomit|dizzy|fever|rash|shortness|chest pain|drool|cough)"]),
        _base_item("ems.medical.opqrst_radiation", "History of present illness: radiation obtained when relevant", 1, _MEDICAL_CATS, tier1_match={"source": "finding", "finding_type": "exam", "finding_key_pattern": r"(?i)^(?:radiation|region\s*/\s*radiation)$"}, tier2_patterns=[r"(?i)(radiat|travel|spread|move anywhere|go anywhere)"], applicable_if={"opqrst_radiation_relevant": True}),
        _base_item("ems.medical.sample_allergies", "Past history: allergies obtained", 1, _MEDICAL_CATS, tier1_match={"source": "finding", "finding_type": "history", "finding_key_pattern": r"(?i)^allergies?$"}, tier2_patterns=[r"(?i)(allerg|NKDA|no known drug allergies)"]),
        _base_item("ems.medical.sample_history", "Past pertinent medical history obtained", 1, _MEDICAL_CATS, tier1_match={"source": "finding", "finding_type": "history", "finding_key_pattern": r"(?i)^pmh$"}, tier2_patterns=[r"(?i)(medical history|past history|PMH|diagnosed|asthma|diabetes|seizure|cardiac|allergy history)"]),
        _base_item("ems.medical.sample_events", "Events leading to present illness obtained", 1, _MEDICAL_CATS, tier1_match={"source": "finding", "finding_type": "history", "finding_key_pattern": r"(?i)^events?$"}, tier2_patterns=[r"(?i)(events|leading up|before this|what happened|what.*(?:doing|happening).*when|when.*what.*(?:doing|happening)|walk me through|timeline)"]),
        _base_item("ems.medical.sample_meds", "Medications obtained", 1, _MEDICAL_CATS, tier1_match={"source": "finding", "finding_type": "history", "finding_key_pattern": r"(?i)^medications?$"}, tier2_patterns=[r"(?i)(meds|medications|prescriptions|takes anything|inhaler|insulin|epi.?pen)"]),
        _base_item("ems.medical.sample_last_oral", "Last oral intake obtained", 1, _MEDICAL_CATS, tier1_match={"source": "finding", "finding_type": "history", "finding_key_pattern": r"(?i)^last\s+oral"}, tier2_patterns=[r"(?i)(last oral|last ate|last drink|eat or drink|NPO|last meal|last food|oral intake|when.*(?:last\s+)?(?:ate?|eat|eaten)|breakfast|lunch|dinner|fasted|fasting)"]),
        _base_item("ems.medical.secondary_assessment", "Performs focused secondary assessment of affected body system or rapid assessment if indicated", 5, _MEDICAL_CATS, allowed_tiers=[1], preferred_tier=1, tier1_match={"source": "finding", "finding_type": "exam", "finding_key_pattern": r"(?i)(lung|breath sounds|chest|neuro|pupils|mental|level of consciousness|\bLOC\b|\bAVPU\b|\bGCS\b|abdomen|skin|musculoskeletal|extremit)"}, tier2_patterns=[r"(?i)(lung sounds|breath sounds|auscultat|neuro|pupils|mental status|level of consciousness|\bLOC\b|\bAVPU\b|\bGCS\b|abdomen|skin|musculoskeletal|GI|GU|psych)"]),
        _base_item("ems.medical.vital_signs", "Obtains and records vital signs relevant to the patient presentation", 5, _MEDICAL_CATS, allowed_tiers=[1], preferred_tier=1, tier1_match={"source": "finding", "finding_type": "vital", "finding_key_pattern": r"(?i)(spo2|sp\s*o2|oxygen\s*saturation|heart\s*rate|\bhr\b|resp(?:iratory)?\s*rate|respirations?|\brr\b|blood\s*pressure|\bbp\b|temperature|temp|blood\s*glucose|glucose|\bbgl\b)", "finding_value_pattern": r"^\d", "eligible_sources": ["authored_vitals", "glucometer_check"], "require_source": True}, tier2_patterns=[r"(?i)(vitals|vital signs|heart rate|HR|respiratory rate|RR|blood pressure|BP|SpO2|temperature|temp|blood glucose|BGL)"]),
        _base_item("ems.medical.diagnostics", "Obtains indicated diagnostics such as blood glucose, ECG/monitoring, or capnography when available and indicated", 2, _MEDICAL_CATS, tier2_patterns=[r"(?i)(diagnostic|ECG|EKG|12.?lead|monitor|blood glucose|BGL|glucometer|capnography|EtCO2)"], applicable_if={"diagnostics_indicated": True}),
        _base_item("ems.medical.field_impression", "Forms field impression of patient", 1, _MEDICAL_CATS, allowed_tiers=[1, 2], preferred_tier=1, tier1_match={"source": "session_event", "event_type": "challenge_completed", "event_key_pattern": r"(?i)^impression:"}, tier2_patterns=[r"(?i)(impression|field impression|I think|appears to be|working diagnosis|anaphylaxis|asthma|croup|seizure|diabetic|syncope|STEMI|overdose)"]),
        _base_item("ems.medical.treatment_plan", "Verbalizes treatment plan and calls for appropriate interventions", 1, _MEDICAL_CATS, subtype="intervention", allowed_tiers=[1, 2], preferred_tier=1, tier1_match={"source": "intervention"}, tier2_patterns=[r"(?i)(plan|treatment|we need|let's|administer|give|apply|start|call|intervention)"]),
        _base_item("ems.medical.transport_reevaluated", "Transport decision re-evaluated", 1, _MEDICAL_CATS, subtype="transport", tier2_patterns=[r"(?i)(transport|still going|re.?evaluate.*transport|priority remains|load|hospital)"], applicable_if={"non_transport_agency": False}),
        _base_item("ems.medical.repeat_vitals", "Repeats vital signs during reassessment", 1, _MEDICAL_CATS, subtype="reassessment", tier1_match={"source": "post_intervention_finding", "finding_type": "vital", "finding_key_pattern": r"(?i)(spo2|rr|resp|pulse|hr|heart|bp|blood pressure|vital)"}, tier2_patterns=[r"(?i)(repeat vitals|recheck vitals|repeat BP|repeat pulse|repeat respiratory|another set of vitals)"]),
        _base_item("ems.medical.treatment_response", "Evaluates response to treatments", 1, _MEDICAL_CATS, subtype="reassessment", tier1_match={"source": "post_intervention_finding", "finding_key_pattern": r"(?i)(spo2|sp\s*o2|oxygen.saturation|respiratory.rate|\brr\b|work.of.breathing|wob|lung.sounds?|breath.sounds?|wheez|gcs|avpu|loc|mental|blood.glucose|bgl|glucose)"}, tier2_patterns=[r"(?i)(response to treatment|any better|improved|worse|reassess.*after|after.*treatment|working)"]),
    ],
    "nremt_trauma_v1": [
        _base_item("ems.trauma.ppe", "Takes or verbalizes appropriate PPE precautions", 1, _TRAUMA_CATS, subtype="scene_entry", allowed_tiers=[1], preferred_tier=1, tier1_match={"source": "scene_entry", "scene_entry_path": "ppe"}, critical_failure=True, critical_failure_label="Failure to take or verbalize appropriate PPE precautions"),
        _base_item("ems.trauma.scene_safety", "Determines the scene/situation is safe", 1, _TRAUMA_CATS, subtype="scene_entry", allowed_tiers=[1], preferred_tier=1, tier1_match={"source": "scene_entry", "scene_entry_path": "scene_approach"}, critical_failure=True, critical_failure_label="Failure to determine scene safety"),
        _base_item("ems.trauma.moi_noi", "Determines mechanism of injury or nature of illness", 1, _TRAUMA_CATS, tier2_patterns=[r"(?i)(mechanism|MOI|NOI|what happened|fall|struck|hit|burn|choking|crash|MVC|auto|handlebar)"]),
        _base_item("ems.trauma.patient_count", "Determines number of patients", 1, _TRAUMA_CATS, tier2_patterns=[r"(?i)(number of patients|how many patients|anyone else|only patient|one patient|single patient)"], applicable_if={"multiple_patients_possible": True}),
        _base_item("ems.trauma.patient_name", "Obtains or verifies patient name", 1, _TRAUMA_CATS, tier1_match={"source": "finding", "finding_type": "history", "finding_key_pattern": r"(?i)^(?:patient\s+|pt\s+)?name$"}, tier2_patterns=[r"(?i)(?:patient'?s?\s+name|what'?s\s+(?:his|her|their)\s+name|what\s+is\s+(?:his|her|their)\s+name|who\s+is\s+(?:he|she|the patient)|name\s+and\s+(?:date of birth|dob|age))"]),
        _base_item("ems.trauma.patient_age_dob", "Obtains or verifies patient age or date of birth", 1, _TRAUMA_CATS, tier1_match={"source": "finding", "finding_type": "history", "finding_key_pattern": r"(?i)^(?:patient\s+|pt\s+)?(?:age|date\s+of\s+birth|dob|birth\s*date)$"}, tier2_patterns=[r"(?i)(?:date\s+of\s+birth|DOB|birth\s*date|birthday|how\s+old|age|when\s+was\s+(?:he|she|the patient)\s+born|name\s+and\s+(?:date of birth|dob|age))"]),
        _base_item("ems.trauma.additional_ems", "Requests additional EMS assistance if necessary", 1, _TRAUMA_CATS, subtype="transport", tier2_patterns=[r"(?i)(additional EMS|additional help|resources|ALS|\bmedic\b|backup|intercept|more units)"], applicable_if={"als_codispatched": False, "additional_help_needed": True}),
        _base_item("ems.trauma.spine_protection", "Considers stabilization of the spine", 1, _TRAUMA_CATS, tier1_match={"source": "intervention", "intervention_key": "smr"}, tier2_patterns=[r"(?i)(c.?spine|spinal|spine|manual stabilization|collar|SMR|immobiliz|neck)",], applicable_if={"spinal_injury_possible": True}),
        _base_item("ems.trauma.general_impression", "Forms or states general impression of the patient", 1, _TRAUMA_CATS, allowed_tiers=[1, 2], preferred_tier=1, tier1_match={"source": "scene_entry", "scene_entry_path": "pat_assessment"}, tier2_patterns=[r"(?i)(general impression|sick|not sick|ill appearing|toxic|stable|unstable|critical|distress)"]),
        _base_item("ems.trauma.loc", "Determines responsiveness or level of consciousness", 1, _TRAUMA_CATS, tier1_match={"source": "finding", "finding_type": "vital", "finding_key_pattern": r"(?i)(gcs|avpu|loc|mental)"}, tier2_patterns=[r"(?i)(responsive|responsiveness|LOC|level of consciousness|AVPU|GCS|alert|oriented|unresponsive)"]),
        _base_item("ems.trauma.chief_life_threats", "Determines chief complaint and apparent life threats", 1, _TRAUMA_CATS, tier2_patterns=[r"(?i)(chief complaint|life threat|primary problem|bleeding|airway|breathing|shock|pain|injury)"]),
        _base_item("ems.trauma.airway", "Airway opened/assessed and adjunct inserted as indicated", 2, _TRAUMA_CATS, tier2_patterns=[r"(?i)(airway|jaw thrust|open.*airway|OPA|NPA|adjunct|suction)"]),
        _base_item("ems.trauma.breathing", "Breathing assessed, ventilation assured, and oxygen or breathing-compromising injuries managed when indicated", 4, _TRAUMA_CATS, tier1_match={"source": "finding", "finding_key_pattern": r"(?i)(spo2|rr|resp|breath|airway|wob|work of breathing|respiratory effort)"}, tier2_patterns=[r"(?i)(breathing|ventilat|respirations|lung sounds|breath sounds|oxygen|O2|BVM|SpO2|chest seal|decompress)"]),
        _base_item("ems.trauma.circulation", "Circulation assessed: pulse, skin, major bleeding control, and shock management", 4, _TRAUMA_CATS, tier1_match={"source": "finding", "finding_key_pattern": r"(?i)(pulse|hr|heart|skin|cap|bp|circulation)"}, tier2_patterns=[r"(?i)(pulse|circulation|bleeding|hemorrhage|skin|cap refill|shock|pressure|tourniquet|keep warm|position)"]),
        _base_item("ems.trauma.priority_transport", "Identifies patient priority and makes treatment/transport decision based on GCS", 1, _TRAUMA_CATS, subtype="transport", tier2_patterns=[r"(?i)(priority|transport|rapid transport|load and go|GCS|trauma center|ALS|hospital|unstable)"], applicable_if={"non_transport_agency": False}),
        _base_item("ems.trauma.baseline_vitals", "Obtains baseline vital signs including blood pressure, pulse, and respirations", 1, _TRAUMA_CATS, allowed_tiers=[1], preferred_tier=1, requirement_logic="all", tier1_matches=[
            {"source": "finding", "finding_type": "vital", "finding_key_pattern": r"(?i)^(?:blood\s*pressure|bp)$"},
            {"source": "finding", "finding_type": "vital", "finding_key_pattern": r"(?i)^(?:heart\s*rate|hr|pulse)$"},
            {"source": "finding", "finding_type": "vital", "finding_key_pattern": r"(?i)^(?:resp(?:iratory)?\s*rate|respirations?|rr)$"},
        ], tier2_patterns=[r"(?i)(vitals|vital signs|BP|blood pressure|pulse|heart rate|respiratory rate|RR)"]),
        _base_item("ems.trauma.sample_history", "Attempts to obtain SAMPLE history", 1, _TRAUMA_CATS, tier2_patterns=[r"(?i)(SAMPLE|allerg|medications|medical history|last oral|events|what happened)"]),
        _base_item("ems.trauma.head_scalp_ears", "Head assessment: inspects and palpates scalp and ears", 1, _TRAUMA_CATS, tier1_match={"source": "finding", "finding_type": "exam", "finding_key_pattern": r"(?i)(dcap[-\s]?btls.*head|head.*dcap|head assessment|scalp assessment)"}, tier2_patterns=[r"(?i)(assess|inspect|palpat|check|examin|look at|evaluate).{0,40}(head|scalp|ears?)|(head|scalp|ears?).{0,40}(assessment|exam|inspection|palpation|checked|clear|normal|abnormal|DCAP)|dcap[-\s]?btls.{0,60}(head|scalp|ears?)|(head|scalp|ears?).{0,60}dcap[-\s]?btls"]),
        _base_item("ems.trauma.head_eyes", "Head assessment: assesses eyes", 1, _TRAUMA_CATS, tier1_match={"source": "finding", "finding_type": "exam", "finding_key_pattern": r"(?i)(pupils?|eyes?)"}, tier2_patterns=[r"(?i)(assess|inspect|check|examin|look at|evaluate).{0,40}(eyes?|pupils?)|(eyes?|pupils?).{0,40}(assessment|exam|checked|PERRL|equal|reactive)"]),
        _base_item("ems.trauma.head_mouth_nose_face", "Head assessment: inspects mouth, nose, and facial area", 1, _TRAUMA_CATS, tier1_match={"source": "finding", "finding_type": "exam", "finding_key_pattern": r"(?i)(facial|face|mouth|nose)"}, tier2_patterns=[r"(?i)(assess|inspect|check|examin|look at|evaluate).{0,40}(mouth|nose|face|facial)|(mouth|nose|face|facial).{0,40}(assessment|exam|inspection|checked|clear|normal|abnormal)"]),
        _base_item("ems.trauma.neck_trachea", "Neck assessment: checks position of trachea", 1, _TRAUMA_CATS, tier1_match={"source": "finding", "finding_type": "exam", "finding_key_pattern": r"(?i)(trachea|tracheal)"}, tier2_patterns=[r"(?i)(trachea|tracheal)"]),
        _base_item("ems.trauma.neck_jugular_veins", "Neck assessment: checks jugular veins", 1, _TRAUMA_CATS, tier1_match={"source": "finding", "finding_type": "exam", "finding_key_pattern": r"(?i)(JVD|jugular|neck veins?)"}, tier2_patterns=[r"(?i)(JVD|jugular|neck veins?)"]),
        _base_item("ems.trauma.neck_c_spine", "Neck assessment: palpates cervical spine", 1, _TRAUMA_CATS, tier1_match={"source": "finding", "finding_type": "exam", "finding_key_pattern": r"(?i)(cervical|c.?spine|neck)"}, tier2_patterns=[r"(?i)(cervical|c.?spine|neck).{0,40}(palpat|tender|pain|step.?off|DCAP)|(palpat|assess|check|examin).{0,40}(cervical|c.?spine|neck)"]),
        _base_item("ems.trauma.chest_inspect", "Chest assessment: inspects chest", 1, _TRAUMA_CATS, tier1_match={"source": "finding", "finding_type": "exam", "finding_key_pattern": r"(?i)(chest|thorax)"}, tier2_patterns=[r"(?i)(inspect|look at|assess|examin|check).{0,40}(chest|thorax)|(chest|thorax).{0,40}(inspection|inspected|looked|clear|normal|abnormal|DCAP)"]),
        _base_item("ems.trauma.chest_palpate", "Chest assessment: palpates chest", 1, _TRAUMA_CATS, tier1_match={"source": "finding", "finding_type": "exam", "finding_key_pattern": r"(?i)(chest|thorax)"}, tier2_patterns=[r"(?i)(palpat|feel).{0,40}(chest|thorax)|(chest|thorax).{0,40}(palpat|tender|crepitus|instability|DCAP)"]),
        _base_item("ems.trauma.chest_auscultate", "Chest assessment: auscultates chest", 1, _TRAUMA_CATS, tier1_match={"source": "finding", "finding_key_pattern": r"(?i)(lung sounds|breath sounds)"}, tier2_patterns=[r"(?i)(auscultat|listen).{0,40}(chest|lung|breath)|(lung sounds|breath sounds)"]),
        _base_item("ems.trauma.abdomen_inspect_palpate", "Abdomen/pelvis assessment: inspects and palpates abdomen", 1, _TRAUMA_CATS, tier1_match={"source": "finding", "finding_type": "exam", "finding_key_pattern": r"(?i)(abdomen|belly)"}, tier2_patterns=[r"(?i)(inspect|palpat|assess|check|examin).{0,40}(abdomen|belly)|(abdomen|belly).{0,40}(inspect|palpat|tender|rigid|soft|DCAP)"]),
        _base_item("ems.trauma.pelvis_assess", "Abdomen/pelvis assessment: assesses pelvis", 1, _TRAUMA_CATS, tier1_match={"source": "finding", "finding_type": "exam", "finding_key_pattern": r"(?i)(pelvis|pelvic)"}, tier2_patterns=[r"(?i)(pelvis|pelvic)"]),
        _base_item("ems.trauma.genitalia_perineum_as_needed", "Abdomen/pelvis assessment: verbalizes assessment of genitalia/perineum as needed", 1, _TRAUMA_CATS, tier2_patterns=[r"(?i)(genital|perineum|groin)"]),
        _base_item("ems.trauma.lower_left_pmsc", "Lower extremities: left leg inspected/palpated with motor, sensory, and distal circulation assessed", 1, _TRAUMA_CATS, tier2_patterns=[r"(?i)(all extremit|moves all four|four extremit|bilateral lower|both legs|left.{0,30}(lower extremit|leg|foot)|(?:lower extremit|leg|foot).{0,30}left).{0,60}(pms|cms|pulse.motor.sens|motor|sensory|distal circulation|distal pulse|pedal pulse|movement|sensation)"]),
        _base_item("ems.trauma.lower_right_pmsc", "Lower extremities: right leg inspected/palpated with motor, sensory, and distal circulation assessed", 1, _TRAUMA_CATS, tier2_patterns=[r"(?i)(all extremit|moves all four|four extremit|bilateral lower|both legs|right.{0,30}(lower extremit|leg|foot)|(?:lower extremit|leg|foot).{0,30}right).{0,60}(pms|cms|pulse.motor.sens|motor|sensory|distal circulation|distal pulse|pedal pulse|movement|sensation)"]),
        _base_item("ems.trauma.upper_left_pmsc", "Upper extremities: left arm inspected/palpated with motor, sensory, and distal circulation assessed", 1, _TRAUMA_CATS, tier2_patterns=[r"(?i)(all extremit|moves all four|four extremit|bilateral upper|both arms|left.{0,30}(upper extremit|arm|hand)|(?:upper extremit|arm|hand).{0,30}left).{0,60}(pms|cms|pulse.motor.sens|motor|sensory|distal circulation|distal pulse|radial pulse|movement|sensation)"]),
        _base_item("ems.trauma.upper_right_pmsc", "Upper extremities: right arm inspected/palpated with motor, sensory, and distal circulation assessed", 1, _TRAUMA_CATS, tier2_patterns=[r"(?i)(all extremit|moves all four|four extremit|bilateral upper|both arms|right.{0,30}(upper extremit|arm|hand)|(?:upper extremit|arm|hand).{0,30}right).{0,60}(pms|cms|pulse.motor.sens|motor|sensory|distal circulation|distal pulse|radial pulse|movement|sensation)"]),
        _base_item("ems.trauma.posterior_thorax", "Posterior thorax, lumbar, and buttocks: inspects and palpates posterior thorax", 1, _TRAUMA_CATS, tier2_patterns=[r"(?i)(posterior thorax|thoracic spine|upper back|log roll).{0,60}(inspect|palpat|assess|check|examin|DCAP|tender)|(inspect|palpat|assess|check|examin).{0,40}(posterior thorax|thoracic spine|upper back)"]),
        _base_item("ems.trauma.lumbar_buttocks", "Posterior thorax, lumbar, and buttocks: inspects and palpates lumbar and buttocks areas", 1, _TRAUMA_CATS, tier2_patterns=[r"(?i)(lumbar|low back|lower back|buttocks|buttock).{0,60}(inspect|palpat|assess|check|examin|DCAP|tender)|(inspect|palpat|assess|check|examin).{0,40}(lumbar|low back|lower back|buttocks|buttock)"]),
        _base_item("ems.trauma.secondary_wounds", "Secondary injuries and wounds managed appropriately", 1, _TRAUMA_CATS, subtype="intervention", tier2_patterns=[r"(?i)(wound|dress|bandage|splint|burn sheet|cover|pressure|irrigate|manage.*injur)"]),
        _base_item("ems.trauma.reassessment", "Demonstrates how and when to reassess the patient", 1, _TRAUMA_CATS, subtype="reassessment", tier1_match={"source": "post_intervention_finding", "finding_key_pattern": r"(?i)(spo2|sp\s*o2|oxygen.saturation|respiratory.rate|\brr\b|pulse|hr|heart|bp|blood.pressure|work.of.breathing|wob|gcs|avpu|loc|mental|pupils?|skin|cap|pain|bleeding|wound)"}, tier2_patterns=[r"(?i)(reassess|repeat vitals|recheck|monitor en route|every.*minutes|after.*treatment)"]),
    ],
}

_SECONDARY_RUBRIC_SUPPRESSED_IDS: dict[str, set[str]] = {
    "nremt_e202_medical_v1": {
        "ems.medical.ppe",
        "ems.medical.scene_safety",
        "ems.medical.patient_count",
        "ems.medical.patient_name",
        "ems.medical.patient_age_dob",
        "ems.medical.additional_help",
        "ems.medical.general_impression",
        "ems.medical.loc",
        "ems.medical.chief_life_threats",
        "ems.medical.airway_breathing_o2",
        "ems.medical.circulation",
        "ems.medical.priority_transport",
        "ems.medical.vital_signs",
        "ems.medical.field_impression",
        "ems.medical.treatment_plan",
        "ems.medical.transport_reevaluated",
        "ems.medical.repeat_vitals",
        "ems.medical.treatment_response",
    },
    "nremt_trauma_v1": {
        "ems.trauma.ppe",
        "ems.trauma.scene_safety",
        "ems.trauma.patient_count",
        "ems.trauma.patient_name",
        "ems.trauma.patient_age_dob",
        "ems.trauma.additional_ems",
        "ems.trauma.general_impression",
        "ems.trauma.loc",
        "ems.trauma.chief_life_threats",
        "ems.trauma.airway",
        "ems.trauma.breathing",
        "ems.trauma.circulation",
        "ems.trauma.priority_transport",
        "ems.trauma.baseline_vitals",
        "ems.trauma.sample_history",
        "ems.trauma.reassessment",
    },
    # Deterioration-to-arrest scenarios already score initial scene entry through
    # their primary medical/trauma base. The secondary arrest rubric should score
    # arrest recognition and CPR/AED management, not duplicate arrival PPE/safety.
    "nremt_cardiac_arrest_aed_v1": {
        "ems.cardiac_arrest.ppe",
        "ems.cardiac_arrest.scene_safety",
    },
    "nrp_newborn_v1": {
        "ems.nrp.ppe",
        "ems.nrp.scene_safety",
    },
}


def _declared_base_rubric_families(scenario: dict) -> list[tuple[str, bool]]:
    """Return declared base rubrics as (family, is_secondary) pairs."""
    families: list[tuple[str, bool]] = []
    primary = scenario.get("base_patient_care_rubric")
    if primary:
        families.append((primary, False))

    additional = scenario.get("additional_patient_care_rubrics") or []
    if additional and not primary:
        raise ValueError("additional_patient_care_rubrics requires base_patient_care_rubric")
    if not isinstance(additional, list):
        raise ValueError("additional_patient_care_rubrics must be a list when provided")

    seen = {primary} if primary else set()
    for family in additional:
        if family in seen:
            continue
        families.append((family, True))
        seen.add(family)
    return families


def _resolve_base_rubric_items(scenario: dict) -> list[dict[str, Any]]:
    """Return raw inherited rubric items for scenarios that opt in."""
    items: list[dict[str, Any]] = []
    for family, is_secondary in _declared_base_rubric_families(scenario):
        if family not in _BASE_RUBRIC_REGISTRY:
            field = "additional_patient_care_rubrics" if is_secondary else "base_patient_care_rubric"
            raise ValueError(f"Unknown {field} value {family!r}")
        suppressed = _SECONDARY_RUBRIC_SUPPRESSED_IDS.get(family, set()) if is_secondary else set()
        for item in _BASE_RUBRIC_REGISTRY[family]:
            if item["id"] in suppressed:
                continue
            copied = dict(item)
            if is_secondary and isinstance(copied.get("applicable_if"), dict):
                applicable_if = dict(copied["applicable_if"])
                applicable_if.pop("scenario_category_in", None)
                copied["applicable_if"] = applicable_if
            items.append(copied)
    return items


def get_base_rubric_version(scenario: dict) -> Optional[str]:
    """Return the declared version string for the scenario's inherited base rubric."""
    family = scenario.get("base_patient_care_rubric")
    if not family:
        return None
    return _BASE_RUBRIC_VERSIONS.get(family)


def _scenario_applicability_flag(scenario: dict, key: str) -> bool:
    """Resolve authored scenario applicability with stable concept fallbacks."""
    if key in scenario:
        return bool(scenario.get(key))
    if key == "als_codispatched":
        dispatch = scenario.get("dispatch") or {}
        if not isinstance(dispatch, dict):
            dispatch = {"text": dispatch}
        dispatch_text = " ".join(
            str(dispatch.get(field) or "") for field in ("text", "notes", "priority")
        )
        return bool(
            re.search(
                r"(?i)\b(?:als|medic|paramedic)\b.{0,40}\b(?:en route|co-?dispatch(?:ed)?|dispatch(?:ed)?|respond(?:ing)?|intercept)\b"
                r"|\b(?:en route|co-?dispatch(?:ed)?|dispatch(?:ed)?|respond(?:ing)?|intercept)\b.{0,40}\b(?:als|medic|paramedic)\b",
                dispatch_text,
            )
        )
    concepts = set((scenario.get("clinical_context") or {}).get("concepts") or [])
    if key == "spinal_injury_possible":
        return "spinal_motion_restriction" in concepts
    if key == "opqrst_radiation_relevant":
        return bool(concepts & {"chest_pain_acs", "chest_pain", "pain"})
    if key == "diagnostics_indicated":
        return bool(concepts & {"blood_glucose", "cardiac_monitoring", "stemi", "chest_pain_acs", "capnography"})
    if key == "additional_help_needed":
        high_acuity_concepts = {
            "airway_obstruction",
            "apnea",
            "cardiac_arrest",
            "decompensated_shock",
            "extrication",
            "hazmat",
            "mass_casualty",
            "mci",
            "multiple_patients",
            "refractory",
            "rescue",
            "respiratory_failure",
            "severe_hypoxia",
            "shock",
            "status_epilepticus",
            "unstable",
            "unresponsive",
        }
        return bool(
            scenario.get("additional_help_needed")
            or scenario.get("multiple_patients_possible")
            or concepts & high_acuity_concepts
        )
    return False


def _item_matches_applicability(item: ChecklistItem, scenario: dict) -> bool:
    """Check scenario-level applicability for inherited/base items."""
    filt = item.applicable_if
    if not filt:
        return True
    if filt.scenario_category_in and scenario.get("category") not in filt.scenario_category_in:
        return False
    if filt.turnover_target_in and scenario.get("turnover_target") not in filt.turnover_target_in:
        return False
    if filt.scenario_id_in and scenario.get("id") not in filt.scenario_id_in:
        return False
    if filt.non_transport_agency is not None:
        if _scenario_applicability_flag(scenario, "non_transport_agency") != filt.non_transport_agency:
            return False
    if filt.als_codispatched is not None:
        if _scenario_applicability_flag(scenario, "als_codispatched") != filt.als_codispatched:
            return False
    if filt.spinal_injury_possible is not None:
        if _scenario_applicability_flag(scenario, "spinal_injury_possible") != filt.spinal_injury_possible:
            return False
    if filt.multiple_patients_possible is not None:
        if _scenario_applicability_flag(scenario, "multiple_patients_possible") != filt.multiple_patients_possible:
            return False
    if filt.additional_help_needed is not None:
        if _scenario_applicability_flag(scenario, "additional_help_needed") != filt.additional_help_needed:
            return False
    if filt.opqrst_radiation_relevant is not None:
        if _scenario_applicability_flag(scenario, "opqrst_radiation_relevant") != filt.opqrst_radiation_relevant:
            return False
    if filt.diagnostics_indicated is not None:
        if _scenario_applicability_flag(scenario, "diagnostics_indicated") != filt.diagnostics_indicated:
            return False
    return True


def load_checklist(
    scenario: dict,
    level: str,
    mca: str,
    agency_id: Optional[str],
) -> list[ChecklistItem]:
    """
    Return the effective checklist for this session context — §5.

    Resolution order:
    1. Resolve inherited primary rubric items from scenario["base_patient_care_rubric"] (if present)
    2. Resolve inherited secondary rubric items from scenario["additional_patient_care_rubrics"] (if present)
    3. Load scenario["checklist"] overlay items (if present)
    4. Scenario overlay items override inherited items when IDs collide
    5. Skip deprecated items
    6. Filter by applicable_levels (empty = all levels eligible)
    7. Filter by requires_mca_expansion (None = always applicable)
    8. Filter by agency_applicable (True = all, False = none, list = specific IDs)
    9. Filter by applicable_if against scenario metadata

    Returns an empty list when the scenario has neither an inherited rubric nor
    a "checklist" key — callers must handle this case and fall back to legacy scoring.
    """
    raw_items: list[dict] = []
    raw_items.extend(_resolve_base_rubric_items(scenario))
    raw_items.extend(scenario.get("checklist", []))
    if not raw_items:
        return []

    items_by_id: dict[str, ChecklistItem] = {}
    for raw in raw_items:
        item = ChecklistItem.model_validate(raw)
        items_by_id[item.id] = item

    # Resolved expansion keys from the adapted scenario (set by adapt_scenario_to_context).
    # These are expansion identifiers like "narcan_expansion", not MCA strings like "mi_base".
    mca_expansions: set[str] = set(scenario.get("mca_expansions") or [])

    result: list[ChecklistItem] = []
    for item in items_by_id.values():
        if item.deprecated:
            continue

        # Level filter — empty = all levels
        if item.applicable_levels and level not in item.applicable_levels:
            continue

        # MCA expansion filter — item is only applicable when the specific BLS expansion
        # has been selected by the MCA.  Compare against the resolved expansion key set,
        # not the MCA string (e.g. "mi_base" ≠ "narcan_expansion").
        if item.requires_mca_expansion and item.requires_mca_expansion not in mca_expansions:
            continue

        # Agency filter
        agency_ok = item.agency_applicable
        if isinstance(agency_ok, bool):
            if not agency_ok:
                continue
        elif isinstance(agency_ok, list):
            if agency_id not in agency_ok:
                continue

        if not _item_matches_applicability(item, scenario):
            continue

        result.append(item)

    return result
