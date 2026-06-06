"""
tests/test_scenario_contracts.py

Production gate: structural contracts for every scenario JSON file and
call-type rubric file.  Run as part of CI — violations fail fast before
manual testing catches them.

If a test here fails after adding a new scenario or rubric, fix the authored
content; do not skip or relax the contract without a documented reason.
"""

from pathlib import Path
import json
import re

import pytest


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SCENARIOS_DIR = Path(__file__).parent.parent / "app" / "scenarios"
_RUBRICS_DIR = Path(__file__).parent.parent / "app" / "rubrics" / "nasemso"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_TURNOVER_TARGETS = frozenset({"hospital", "als", "none"})

_VALID_INDICATION_GATE_STATUSES = frozenset({"not_indicated_now", "contraindicated"})

# Regex matching notes text that signals FTO-blocked / not-indicated interventions.
# When found, a structured indication_gate dict is required so the engine can
# source FTO guidance from authoritative data rather than fragile regex.
_FTO_TRIGGER_RE = re.compile(
    r"\b(?:not\s+(?:yet\s+)?indicated|contraindicated|not\s+recommended)\b",
    re.IGNORECASE,
)

# SAMPLE component keys that a history_response_map entry covers individually.
# A rich HRM (>= _HRM_RICH_THRESHOLD entries, >= _HRM_SAMPLE_THRESHOLD matching)
# must also have a compound priority entry so "full SAMPLE" questions get one answer.
_SAMPLE_COMPONENT_KEYS = frozenset({
    "signs_symptoms",
    "allergies",
    "medications",
    "pmh",
    "last_oral_intake",
    "events",
    "pertinent_history",
})
_HRM_RICH_THRESHOLD = 8
_HRM_SAMPLE_THRESHOLD = 3

# Broad support concepts are useful in clinical_context.concepts for SOP overlays,
# but they are intentionally ignored for base protocol excerpt selection when
# protocol_focus contains more specific tags.
_PROTOCOL_FOCUS_GENERIC_CONCEPTS = frozenset({
    "airway_management",
    "documentation_handoff",
    "medical_control",
    "oxygen_therapy",
    "patient_assessment",
    "pediatric_patient",
    "primary_survey",
    "respiratory_distress",
    "scene_safety",
    "transport_decision",
    "ventilation_support",
    "vital_signs",
})

# Required top-level fields for every scenario.
_SCENARIO_REQUIRED_FIELDS = (
    "id",
    "title",
    "category",
    "turnover_target",
    "vitals",
    "checklist",
    "exemplar_narrative",
)

# Required per-item fields in a call-type rubric's checklist_items list.
_RUBRIC_ITEM_REQUIRED_FIELDS = (
    "id",
    "description",
    "category",
    "subtype",
    "point_value",
    "required",
    "tier2_patterns",
    "done_feedback",
    "missed_feedback",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def _all_scenario_paths():
    return sorted(_SCENARIOS_DIR.glob("**/*.json"))


def _all_rubric_paths():
    return [p for p in sorted(_RUBRICS_DIR.glob("*.json"))
            if not p.name.endswith("schema.json")]


# ---------------------------------------------------------------------------
# Parametrize
# ---------------------------------------------------------------------------

def pytest_generate_tests(metafunc):
    if "scenario_path" in metafunc.fixturenames:
        metafunc.parametrize(
            "scenario_path", _all_scenario_paths(), ids=lambda p: p.name
        )
    if "rubric_path" in metafunc.fixturenames:
        metafunc.parametrize(
            "rubric_path", _all_rubric_paths(), ids=lambda p: p.name
        )


# ---------------------------------------------------------------------------
# Scenario: required top-level fields
# ---------------------------------------------------------------------------

class TestScenarioRequiredFields:

    def test_required_top_level_fields_present(self, scenario_path):
        s = _load(scenario_path)
        missing = [f for f in _SCENARIO_REQUIRED_FIELDS if f not in s]
        assert not missing, (
            f"{scenario_path.name}: missing required top-level fields: {missing}"
        )

    def test_id_matches_filename_stem(self, scenario_path):
        s = _load(scenario_path)
        assert s.get("id") == scenario_path.stem, (
            f"{scenario_path.name}: scenario.id={s.get('id')!r} does not match "
            f"filename stem {scenario_path.stem!r}"
        )

    def test_turnover_target_is_valid(self, scenario_path):
        s = _load(scenario_path)
        tt = s.get("turnover_target")
        assert tt in _VALID_TURNOVER_TARGETS, (
            f"{scenario_path.name}: turnover_target={tt!r} must be one of "
            f"{sorted(_VALID_TURNOVER_TARGETS)}"
        )

    def test_exemplar_dmist_non_empty_when_present(self, scenario_path):
        s = _load(scenario_path)
        if "exemplar_dmist" not in s:
            return
        dmist = s["exemplar_dmist"]
        assert isinstance(dmist, str) and dmist.strip(), (
            f"{scenario_path.name}: exemplar_dmist is present but empty or non-string"
        )

    def test_debrief_present_unless_exempt(self, scenario_path):
        s = _load(scenario_path)
        if s.get("is_orientation") or s.get("debrief_exempt"):
            return
        assert s.get("debrief"), (
            f"{scenario_path.name}: 'debrief' is missing and scenario is not marked "
            f"is_orientation or debrief_exempt"
        )


class TestScenarioCallTypeSelection:

    def test_specific_head_injury_presentations_use_head_injury_call_type(self, scenario_path):
        s = _load(scenario_path)
        concepts = set(s.get("clinical_context", {}).get("concepts", []))
        protocol_focus = set(s.get("clinical_context", {}).get("protocol_focus", []))
        requires_head_injury_rubric = bool(
            {"traumatic_brain_injury", "neurological_assessment", "gcs_assessment"} & concepts
            or {"neurological_assessment", "gcs"} & protocol_focus
        )
        if not requires_head_injury_rubric:
            return
        assert s.get("call_type") == "head_injury", (
            f"{scenario_path.name}: TBI/neuro head-injury presentations must use "
            "call_type='head_injury' so reusable focused exam scoring stays in the "
            "call-type rubric instead of scenario JSON"
        )

    def test_head_injury_scenario_does_not_reauthor_reusable_focused_exam_items(self, scenario_path):
        s = _load(scenario_path)
        if s.get("call_type") != "head_injury":
            return
        reusable_suffixes = {
            "neuro_assessment",
            "pupil_assessment",
            "dcap_btls",
            "smr",
            "transport_decision",
            "scope_no_als_only_interventions",
            "protocols_smr",
            "protocols_high_flow_o2",
        }
        duplicated = [
            item.get("id")
            for item in s.get("checklist", [])
            if str(item.get("id", "")).split(".")[-1] in reusable_suffixes
        ]
        assert not duplicated, (
            f"{scenario_path.name}: reusable head-injury focused exam/protocol items "
            f"belong in head_injury_v1.json, not scenario checklist: {duplicated}"
        )


# ---------------------------------------------------------------------------
# Scenario: clinical context integrity
# ---------------------------------------------------------------------------

class TestClinicalContext:

    def test_protocol_focus_present_and_non_empty(self, scenario_path):
        """Every scenario must explicitly author protocol_focus.

        Without protocol_focus, protocol excerpt matching falls back to the full
        clinical_context.concepts list, which includes broad support tags and can
        pull unrelated base protocols into the scenario excerpt.
        """
        s = _load(scenario_path)
        context = s.get("clinical_context")
        assert isinstance(context, dict), (
            f"{scenario_path.name}: clinical_context is missing or not an object"
        )
        focus = context.get("protocol_focus")
        assert isinstance(focus, list) and any(str(item).strip() for item in focus), (
            f"{scenario_path.name}: clinical_context.protocol_focus must be a non-empty "
            f"list of condition/protocol-specific concepts"
        )

    def test_protocol_focus_contains_specific_selection_concept(self, scenario_path):
        """protocol_focus must not consist only of generic support concepts."""
        s = _load(scenario_path)
        if s.get("is_orientation") or s.get("debrief_exempt"):
            return
        context = s.get("clinical_context")
        if not isinstance(context, dict):
            return
        focus = context.get("protocol_focus")
        if not isinstance(focus, list) or not focus:
            return
        focus_values = {str(item).strip() for item in focus if str(item).strip()}
        specific = sorted(focus_values - _PROTOCOL_FOCUS_GENERIC_CONCEPTS)
        assert specific, (
            f"{scenario_path.name}: protocol_focus only contains generic support "
            f"concepts {sorted(focus_values)}. Add at least one condition/protocol-specific "
            f"concept so base protocol excerpt matching does not fall back to broad tags."
        )


# ---------------------------------------------------------------------------
# Scenario: deprecated field guardrails
# ---------------------------------------------------------------------------

class TestDeprecatedScenarioFields:

    def test_deprecated_top_level_runtime_fields_absent(self, scenario_path):
        """Scenario JSON must not author runtime-derived or legacy alias fields."""
        s = _load(scenario_path)
        deprecated = {
            "als_codispatched": (
                "agency-derived at adaptation time; do not bake one agency dispatch "
                "policy into scenario content"
            ),
            "lexi_hints": (
                "legacy alias; use debrief_lexi_hints so live Lexi remains universal"
            ),
        }
        violations = [
            f"{field}: {reason}"
            for field, reason in deprecated.items()
            if field in s
        ]
        assert not violations, (
            f"{scenario_path.name}: deprecated top-level scenario fields present:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Scenario: checklist integrity
# ---------------------------------------------------------------------------

class TestChecklistIntegrity:

    def test_no_duplicate_checklist_ids(self, scenario_path):
        s = _load(scenario_path)
        cl = s.get("checklist", [])
        if not isinstance(cl, list):
            return
        ids = [item.get("id") for item in cl if isinstance(item, dict)]
        dupes = sorted({id_ for id_ in ids if ids.count(id_) > 1})
        assert not dupes, (
            f"{scenario_path.name}: duplicate checklist item IDs: {dupes}"
        )

    def test_authored_feedback_strings_non_empty(self, scenario_path):
        """Items that declare done_feedback or missed_feedback must have non-empty
        string values.  Items that omit those keys entirely are OK — they rely on
        call-type rubric resolution at runtime."""
        s = _load(scenario_path)
        cl = s.get("checklist", [])
        if not isinstance(cl, list):
            return
        violations = []
        for item in cl:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id", "<no-id>")
            for field in ("done_feedback", "missed_feedback"):
                if field in item:
                    val = item[field]
                    if not isinstance(val, str) or not val.strip():
                        violations.append(f"{item_id}.{field}")
        assert not violations, (
            f"{scenario_path.name}: checklist items have empty feedback strings: "
            + ", ".join(violations)
        )


# ---------------------------------------------------------------------------
# Scenario: lung sound challenge
# ---------------------------------------------------------------------------

class TestLungSoundChallenge:

    def test_enabled_main_challenge_has_correct_choice_id(self, scenario_path):
        s = _load(scenario_path)
        lsc = s.get("lung_sound_challenge")
        if not isinstance(lsc, dict) or not lsc.get("enabled"):
            return
        assert lsc.get("correct_choice_id"), (
            f"{scenario_path.name}: lung_sound_challenge.enabled=true but "
            f"correct_choice_id is missing or empty — UI choice validation is non-deterministic"
        )

    def test_enabled_post_treatment_challenge_has_correct_choice_id(self, scenario_path):
        s = _load(scenario_path)
        lsc = s.get("lung_sound_challenge")
        if not isinstance(lsc, dict):
            return
        pt = lsc.get("post_treatment")
        if not isinstance(pt, dict) or not pt.get("enabled"):
            return
        assert pt.get("correct_choice_id"), (
            f"{scenario_path.name}: lung_sound_challenge.post_treatment.enabled=true but "
            f"correct_choice_id is missing or empty"
        )


# ---------------------------------------------------------------------------
# Scenario: indication_gate contracts
# ---------------------------------------------------------------------------

class TestIndicationGate:

    def test_fto_trigger_notes_require_indication_gate(self, scenario_path):
        """Any intervention whose notes contain 'not indicated', 'contraindicated',
        or 'not recommended' must carry a structured indication_gate dict.  Notes
        regex is brittle; indication_gate is the authoritative source for FTO
        guidance and engine-side penalty scoring."""
        s = _load(scenario_path)
        vitals = s.get("vitals", {})
        interventions = (vitals.get("interventions", {})
                         if isinstance(vitals, dict) else {})
        violations = []
        for ikey, idata in interventions.items():
            if not isinstance(idata, dict):
                continue
            notes = str(idata.get("notes", "") or "")
            if _FTO_TRIGGER_RE.search(notes) and not isinstance(
                idata.get("indication_gate"), dict
            ):
                violations.append(f"[{ikey}] notes={notes[:80]!r}")
        assert not violations, (
            f"{scenario_path.name}: interventions with FTO-trigger notes but no "
            f"indication_gate:\n" + "\n".join(violations)
        )

    def test_indication_gate_schema_valid(self, scenario_path):
        """indication_gate when present must have status, reason, allowed_when,
        and a known status value."""
        s = _load(scenario_path)
        vitals = s.get("vitals", {})
        interventions = (vitals.get("interventions", {})
                         if isinstance(vitals, dict) else {})
        violations = []
        for ikey, idata in interventions.items():
            if not isinstance(idata, dict):
                continue
            gate = idata.get("indication_gate")
            if gate is None:
                continue
            if not isinstance(gate, dict):
                violations.append(f"[{ikey}].indication_gate: not a dict ({type(gate).__name__})")
                continue
            for req in ("status", "reason", "allowed_when"):
                if req not in gate:
                    violations.append(f"[{ikey}].indication_gate: missing required field '{req}'")
            status = gate.get("status", "")
            if status not in _VALID_INDICATION_GATE_STATUSES:
                violations.append(
                    f"[{ikey}].indication_gate.status={status!r}: must be one of "
                    f"{sorted(_VALID_INDICATION_GATE_STATUSES)}"
                )
            if "allowed_when" in gate and not isinstance(gate["allowed_when"], list):
                violations.append(f"[{ikey}].indication_gate.allowed_when: must be a list")
        assert not violations, (
            f"{scenario_path.name}: indication_gate schema violations:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Scenario: intervention scope authoring
# ---------------------------------------------------------------------------

class TestInterventionScope:

    def test_required_expansion_items_have_within_bls_scope_true(self, scenario_path):
        """Interventions with required_expansion must be authored with within_bls_scope: true.

        The MCA adaptation engine (adapt_scenario_to_context) flips within_bls_scope to
        False at runtime when the expansion is not active.  If an expansion item is
        authored with within_bls_scope: false, it is never available even when the
        expansion is selected — the engine has no mechanism to flip it back to True."""
        s = _load(scenario_path)
        vitals = s.get("vitals", {})
        interventions = (vitals.get("interventions", {})
                         if isinstance(vitals, dict) else {})
        violations = []
        for ikey, idata in interventions.items():
            if not isinstance(idata, dict):
                continue
            if not idata.get("required_expansion"):
                continue
            if idata.get("within_bls_scope") is not True:
                violations.append(
                    f"[{ikey}]: required_expansion={idata['required_expansion']!r} "
                    f"but within_bls_scope={idata.get('within_bls_scope')!r} "
                    f"(must be true so the engine can gate it correctly)"
                )
        assert not violations, (
            f"{scenario_path.name}: expansion-gated interventions authored with wrong scope:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Scenario: history response map
# ---------------------------------------------------------------------------

class TestHistoryResponseMap:

    def test_hrm_entries_have_answer_and_triggers(self, scenario_path):
        """Each active HRM entry must have a non-empty answer and at least one trigger
        so the engine resolver and AI directive builder have valid data to work with."""
        s = _load(scenario_path)
        hrm = s.get("history_response_map") or {}
        if not isinstance(hrm, dict):
            return
        violations = []
        for key, entry in hrm.items():
            if not isinstance(entry, dict):
                violations.append(f"[{key}]: entry is not a dict")
                continue
            if entry.get("do_not_include"):
                continue
            answer = str(entry.get("answer", "") or "").strip()
            if not answer:
                violations.append(f"[{key}]: missing or empty 'answer'")
            if not entry.get("triggers"):
                violations.append(f"[{key}]: missing or empty 'triggers' list")
        assert not violations, (
            f"{scenario_path.name}: HRM entry schema violations:\n"
            + "\n".join(violations)
        )

    def test_rich_hrm_has_compound_sample_priority_entry(self, scenario_path):
        """A rich HRM (>= {_HRM_RICH_THRESHOLD} entries with >= {_HRM_SAMPLE_THRESHOLD}
        individual SAMPLE-component keys) must include a priority entry covering compound
        SAMPLE questions.  Without it, students who ask 'give me the full SAMPLE' get an
        incomplete answer assembled from the first matching entry rather than the full
        authored composite."""
        s = _load(scenario_path)
        hrm = s.get("history_response_map") or {}
        if not isinstance(hrm, dict) or len(hrm) < _HRM_RICH_THRESHOLD:
            return
        hrm_keys_lower = {k.lower() for k in hrm}
        sample_component_count = len(_SAMPLE_COMPONENT_KEYS & hrm_keys_lower)
        if sample_component_count < _HRM_SAMPLE_THRESHOLD:
            return
        has_priority = any(
            isinstance(v, dict) and (
                v.get("priority") or
                (v.get("notes") and str(v["notes"]).lower().startswith("priority"))
            )
            for v in hrm.values()
        )
        assert has_priority, (
            f"{scenario_path.name}: HRM has {len(hrm)} entries and "
            f"{sample_component_count} SAMPLE-component keys but no compound priority "
            f"entry.  Add a priority entry with triggers covering compound SAMPLE "
            f"questions ('sample', 'full sample', 'complete assessment', etc.) so "
            f"broad student questions get one complete authored answer."
        )

    def test_chief_concern_speaker_matches_initial_complaint(self, scenario_path):
        """The broad-opener HRM entry should preserve the authored caller/caregiver voice.

        Without an explicit speaker, the roleplay layer may display a generic "Bystander"
        label even when the scenario has an authoritative initial_complaint.speaker.
        """
        s = _load(scenario_path)
        initial_speaker = ((s.get("initial_complaint") or {}).get("speaker") or "").strip()
        hrm = s.get("history_response_map") or {}
        chief = hrm.get("chief_concern") if isinstance(hrm, dict) else None
        if not initial_speaker or not isinstance(chief, dict):
            return

        chief_speaker = str(chief.get("speaker") or "").strip()
        assert chief_speaker == initial_speaker, (
            f"{scenario_path.name}: history_response_map.chief_concern.speaker must "
            f"match initial_complaint.speaker ({initial_speaker!r}) so broad opener "
            "responses do not fall back to a generic speaker label."
        )


# ---------------------------------------------------------------------------
# Call-type rubric contracts
# ---------------------------------------------------------------------------

class TestCallTypeRubricIntegrity:

    def test_no_duplicate_checklist_item_ids(self, rubric_path):
        r = _load(rubric_path)
        items = r.get("checklist_items", [])
        ids = [item.get("id") for item in items if isinstance(item, dict)]
        dupes = sorted({id_ for id_ in ids if ids.count(id_) > 1})
        assert not dupes, (
            f"{rubric_path.name}: duplicate checklist_items IDs: {dupes}"
        )

    def test_all_items_have_required_schema_fields(self, rubric_path):
        r = _load(rubric_path)
        items = r.get("checklist_items", [])
        violations = []
        for item in items:
            if not isinstance(item, dict):
                violations.append("<non-dict item>")
                continue
            item_id = item.get("id", "<no-id>")
            for req in _RUBRIC_ITEM_REQUIRED_FIELDS:
                if req not in item:
                    violations.append(f"{item_id}: missing '{req}'")
        assert not violations, (
            f"{rubric_path.name}: checklist_items missing required fields:\n"
            + "\n".join(violations)
        )

    def test_all_item_feedback_strings_non_empty(self, rubric_path):
        r = _load(rubric_path)
        items = r.get("checklist_items", [])
        violations = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id", "<no-id>")
            for field in ("done_feedback", "missed_feedback"):
                val = item.get(field)
                if val is not None and (not isinstance(val, str) or not val.strip()):
                    violations.append(f"{item_id}.{field}")
        assert not violations, (
            f"{rubric_path.name}: checklist_items have empty feedback strings: "
            + ", ".join(violations)
        )


# ---------------------------------------------------------------------------
# DMIST component contracts
# ---------------------------------------------------------------------------

# corroboration_source values that indicate I is pointing at intervention data,
# not injury/illness data. These are not valid for the I component.
_DMIST_I_INVALID_CORROBORATION_SOURCES = frozenset({
    "intervention_timeline",
    "intervention_record",
})

_GLOBAL_SCORING_POLICY_PATTERNS = (
    (
        "ALS request scoring follows the active agency configuration",
        "ALS request/co-dispatch scoring is engine-owned and must not be "
        "re-documented in scenario scoring text.",
    ),
    (
        "Do NOT penalize for not naming 'PAT'",
        "PAT acronym credit is base-rubric/engine policy, not scenario policy.",
    ),
    (
        "Do NOT penalize for not naming PAT",
        "PAT acronym credit is base-rubric/engine policy, not scenario policy.",
    ),
    (
        "Credit any vitals verbally requested",
        "Student-assessed vitals credit is evidence-engine policy, not scenario policy.",
    ),
    (
        "CHART format only:",
        "CHART format is universal narrative policy, not scenario-specific guidance.",
    ),
    (
        "Narrative follows CHART format:",
        "CHART format is universal narrative policy, not scenario-specific guidance.",
    ),
)

# Grading formulas that belong in the DMIST scoring engine (ai_client.py), not in
# scenario dmist_components.*.scoring_note. scoring_note must contain clinical context
# (which signs are primary for this call type) — not "Award X/Y if" grading rules.
_DMIST_SCORING_NOTE_BANNED_PATTERNS = (
    (
        "Award 2/2 if",
        "Grading formulas belong in the DMIST scoring engine (ai_client.py). "
        "scoring_note must describe clinical context, not reauthor the grading model.",
    ),
    (
        "Award 1/2 if",
        "Grading formulas belong in the DMIST scoring engine (ai_client.py). "
        "scoring_note must describe clinical context, not reauthor the grading model.",
    ),
    (
        "Award 0/2 if",
        "Grading formulas belong in the DMIST scoring engine (ai_client.py). "
        "scoring_note must describe clinical context, not reauthor the grading model.",
    ),
    (
        "Award 0/2 only if",
        "Fabrication-penalty rules are universal engine policy (ai_client.py L4456). "
        "Do not repeat them in scenario scoring_note.",
    ),
    (
        "fabricates",
        "The fabrication penalty is universal engine policy (ai_client.py L4456). "
        "Do not repeat it in scenario scoring_note.",
    ),
)


class TestDmistComponentContracts:
    """Gate: DMIST I must represent injuries/illness, not interventions performed.

    The canonical DMIST model:
      D = Demographics (name, age, sex, weight)
      M = Mechanism or chief complaint
      I = Injuries or illness details (NOT treatments performed)
      S = Signs and symptoms
      T = Treatments, response, and transport

    Violations fail CI. Fix the authored scenario — do not skip or relax
    the contract. See docs/SCENARIO_DESIGN_EMS.md for the full model.
    """

    def test_i_component_is_injuries_not_interventions(self, scenario_path):
        """Fail if I component text describes interventions rather than injuries/illness."""
        from app.dmist_scoring import _is_legacy_intervention_i_config

        data = _load(scenario_path)
        dc = data.get("dmist_components", {})
        if "I" not in dc:
            return
        i_cfg = dc["I"]
        assert not _is_legacy_intervention_i_config(i_cfg), (
            f"{scenario_path.name}: dmist_components.I is authored as interventions "
            f"(description={i_cfg.get('description')!r}, "
            f"required_elements={i_cfg.get('required_elements', [])!r}). "
            "DMIST I = injuries or illness details. Treatments belong under T. "
            "See docs/SCENARIO_DESIGN_EMS.md."
        )

    def test_i_component_corroboration_source_valid(self, scenario_path):
        """Fail if I uses a corroboration_source that points at intervention data."""
        data = _load(scenario_path)
        dc = data.get("dmist_components", {})
        if "I" not in dc:
            return
        i_cfg = dc["I"]
        src = i_cfg.get("corroboration_source", "")
        assert src not in _DMIST_I_INVALID_CORROBORATION_SOURCES, (
            f"{scenario_path.name}: dmist_components.I.corroboration_source={src!r} "
            "targets intervention data. DMIST I = injuries/illness — use "
            "'history_and_findings' or 'scenario_vitals_and_exam'. "
            "See docs/SCENARIO_DESIGN_EMS.md."
        )

    def test_scenario_scoring_does_not_reauthor_global_policy(self, scenario_path):
        """Fail if scenario prose re-documents engine/base-rubric scoring policy."""
        data = _load(scenario_path)
        scoring = data.get("scoring", {})
        if not isinstance(scoring, dict):
            return
        violations = []
        for section in ("overall_considerations", "narrative_considerations"):
            values = scoring.get(section, [])
            if not isinstance(values, list):
                continue
            for idx, value in enumerate(values):
                if not isinstance(value, str):
                    continue
                for needle, reason in _GLOBAL_SCORING_POLICY_PATTERNS:
                    if needle in value:
                        violations.append(f"{section}[{idx}]: {reason}")
        assert not violations, (
            f"{scenario_path.name}: scenario scoring text must contain only "
            "scenario-specific clinical guidance. Global scoring policy belongs "
            "in the engine/base rubrics/docs:\n- " + "\n- ".join(violations)
        )

    def test_dmist_scoring_note_contains_no_grading_formulas(self, scenario_path):
        """Fail if dmist_components.*.scoring_note contains 'Award X/Y' grading formulas.

        scoring_note is AI guidance that identifies which clinical signs are primary
        for a specific call type. It must NOT reauthor the 2/1/0 grading model or
        repeat the fabrication-penalty rule — both live in ai_client.py and apply
        universally. Scenario-specific grading formulas override the engine and
        create per-scenario policy drift.
        """
        data = _load(scenario_path)
        dc = data.get("scoring", {}).get("dmist_components", {})
        if not dc:
            return
        violations = []
        for comp, spec in dc.items():
            if not isinstance(spec, dict):
                continue
            note = spec.get("scoring_note", "")
            if not note:
                continue
            for needle, reason in _DMIST_SCORING_NOTE_BANNED_PATTERNS:
                if needle in note:
                    violations.append(
                        f"dmist_components.{comp}.scoring_note contains {needle!r}: {reason}"
                    )
                    break  # one violation per component is enough
        assert not violations, (
            f"{scenario_path.name}: dmist_components scoring_notes must provide "
            "clinical context (which signs are primary) — not grading formulas. "
            "Fix: remove 'Award X/Y if' and fabrication-penalty language; "
            "keep only the list of primary clinical signs for this call type.\n- "
            + "\n- ".join(violations)
        )

    def test_t_component_does_not_repeat_als_readiness_boilerplate(self, scenario_path):
        """Fail if dmist_components.T.required_elements contains bare 'ALS readiness'.

        When turnover_target == 'als', the engine's universal T rule already requires
        ALS handoff readiness. Listing 'ALS readiness' as a required_element duplicates
        global policy and can cause the AI grader to treat it as a uniquely required
        scenario element rather than a universal expectation.

        Scenario-specific T elements are fine — 'ALS intercept decision', 'rapid
        transport decision', 'mandatory report', etc. The bare string 'ALS readiness'
        is the only disallowed pattern.
        """
        data = _load(scenario_path)
        tt = data.get("turnover_target", "none")
        if tt != "als":
            return
        t_spec = data.get("scoring", {}).get("dmist_components", {}).get("T", {})
        if not isinstance(t_spec, dict):
            return
        elems = t_spec.get("required_elements", [])
        banned = [e for e in elems if e.strip().lower() == "als readiness"]
        assert not banned, (
            f"{scenario_path.name}: dmist_components.T.required_elements contains "
            "'ALS readiness' — this is universal engine policy (turnover_target=als) "
            "and must not be repeated in scenario JSON. Remove it and keep only "
            "scenario-specific T elements (e.g. 'mandatory report', 'rapid transport decision')."
        )
