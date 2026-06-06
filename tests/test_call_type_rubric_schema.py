"""
Validator for EMS call-type rubric files against the canonical schema.

Dependency-free: uses only stdlib. Validates structural correctness,
ID uniqueness, cross-reference integrity, and source role consistency.
Add new rubric files to RUBRIC_FILES to include them in CI.
"""

import json
import pathlib
import re
import pytest

RUBRIC_DIR = pathlib.Path(__file__).parent.parent / "app" / "rubrics" / "nasemso"
SCHEMA_FILE = RUBRIC_DIR / "ems_call_type_rubric.schema.json"

RUBRIC_FILES = [
    RUBRIC_DIR / "respiratory_distress_v1.json",
    RUBRIC_DIR / "pediatric_croup_v1.json",
    RUBRIC_DIR / "hypoglycemia_v1.json",
    RUBRIC_DIR / "head_injury_v1.json",
    RUBRIC_DIR / "nremt_trauma_v1.json",
]

# ── Constants drawn from schema ───────────────────────────────────────────────

VALID_DOMAINS = {"medical", "trauma", "pediatric", "environmental", "obstetric", "cardiac_arrest"}
VALID_OVERLAYS = {"state", "agency", "scenario"}
VALID_CATEGORIES = {"clinical_performance", "protocols_treatment", "scope_adherence", "documentation", "professionalism"}
VALID_SUBTYPES = {"scene_entry", "assessment", "screen", "intervention", "reassessment", "transport",
                  "documentation_handoff", "documentation_narrative", "professionalism"}
VALID_LEVELS = {"EMR", "EMT", "AEMT", "Paramedic"}
VALID_REQUIRED = {"required", "optional", "bonus"}
VALID_REQUIREMENT_LOGIC = {"any", "all"}
VALID_EVIDENCE_TYPES = {"finding", "post_intervention_finding", "intervention", "session_event",
                        "scene_entry", "absence_check"}
VALID_FINDING_TYPES = {"vital", "exam", "history"}
VALID_TIMING_TYPES = {"within_minutes", "before_item", "after_item"}
VALID_TIMING_CONSEQUENCES = {"partial", "deduction_override", "informational"}

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.]*$")
TOP_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path: pathlib.Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _check_evidence_requirement(req: dict, item_id: str, idx: int, source_roles: set) -> list[str]:
    errors = []
    ctx = f"item '{item_id}' evidence_requirements[{idx}]"

    if "type" not in req:
        errors.append(f"{ctx}: missing required field 'type'")
        return errors

    t = req["type"]
    if t not in VALID_EVIDENCE_TYPES:
        errors.append(f"{ctx}: type '{t}' not in {VALID_EVIDENCE_TYPES}")

    if t in ("finding", "post_intervention_finding"):
        if "finding_type" in req and req["finding_type"] not in VALID_FINDING_TYPES:
            errors.append(f"{ctx}: finding_type '{req['finding_type']}' not in {VALID_FINDING_TYPES}")
        for role in req.get("eligible_source_roles", []):
            if role not in source_roles:
                errors.append(f"{ctx}: eligible_source_role '{role}' not defined in source_role_map")

    if t == "intervention":
        has_key = "intervention_key" in req or "intervention_keys" in req
        if not has_key:
            errors.append(f"{ctx}: intervention type requires 'intervention_key' or 'intervention_keys'")

    if t == "session_event" and "event_type" not in req:
        errors.append(f"{ctx}: session_event type requires 'event_type'")

    if t == "scene_entry" and "scene_entry_path" not in req:
        errors.append(f"{ctx}: scene_entry type requires 'scene_entry_path'")

    if t == "absence_check" and "absence_intervention_key" not in req:
        errors.append(f"{ctx}: absence_check type requires 'absence_intervention_key'")

    return errors


def _check_item(item: dict, protocol_ref_ids: set, source_roles: set) -> list[str]:
    errors = []
    item_id = item.get("id", "<missing>")

    required_fields = ["id", "description", "category", "subtype", "point_value",
                       "required", "applicable_levels", "evidence_requirements",
                       "done_feedback", "missed_feedback"]
    for field in required_fields:
        if field not in item:
            errors.append(f"item '{item_id}': missing required field '{field}'")

    if "id" in item and not ID_PATTERN.match(item["id"]):
        errors.append(f"item '{item_id}': id does not match pattern [a-z][a-z0-9_.]*")

    if "category" in item and item["category"] not in VALID_CATEGORIES:
        errors.append(f"item '{item_id}': category '{item['category']}' not in {VALID_CATEGORIES}")

    if "subtype" in item and item["subtype"] not in VALID_SUBTYPES:
        errors.append(f"item '{item_id}': subtype '{item['subtype']}' not in {VALID_SUBTYPES}")

    if "point_value" in item and (not isinstance(item["point_value"], int) or item["point_value"] < 0):
        errors.append(f"item '{item_id}': point_value must be a non-negative integer")

    if "required" in item and item["required"] not in VALID_REQUIRED:
        errors.append(f"item '{item_id}': required '{item['required']}' not in {VALID_REQUIRED}")

    req_logic = item.get("requirement_logic")
    if req_logic is not None and req_logic not in VALID_REQUIREMENT_LOGIC:
        errors.append(f"item '{item_id}': requirement_logic '{req_logic}' not in {VALID_REQUIREMENT_LOGIC}")

    if req_logic == "all" and len(item.get("evidence_requirements", [])) < 2:
        errors.append(f"item '{item_id}': requirement_logic 'all' requires at least 2 evidence_requirements")

    if "applicable_levels" in item:
        levels = item["applicable_levels"]
        if not levels:
            errors.append(f"item '{item_id}': applicable_levels must not be empty")
        for lv in levels:
            if lv not in VALID_LEVELS:
                errors.append(f"item '{item_id}': applicable_level '{lv}' not in {VALID_LEVELS}")

    for ref in item.get("protocol_refs", []):
        if ref not in protocol_ref_ids:
            errors.append(f"item '{item_id}': protocol_ref '{ref}' not defined in top-level protocol_refs")

    for i, req in enumerate(item.get("evidence_requirements", [])):
        errors.extend(_check_evidence_requirement(req, item_id, i, source_roles))

    for tc in item.get("timing_constraints") or []:
        if "type" not in tc:
            errors.append(f"item '{item_id}': timing_constraint missing 'type'")
        elif tc["type"] not in VALID_TIMING_TYPES:
            errors.append(f"item '{item_id}': timing_constraint type '{tc['type']}' invalid")
        if tc.get("type") == "within_minutes" and "value" not in tc:
            errors.append(f"item '{item_id}': within_minutes constraint requires 'value'")
        if tc.get("type") in ("before_item", "after_item") and "reference_item_id" not in tc:
            errors.append(f"item '{item_id}': {tc['type']} constraint requires 'reference_item_id'")
        vc = tc.get("violation_consequence")
        if vc is not None and vc not in VALID_TIMING_CONSEQUENCES:
            errors.append(f"item '{item_id}': violation_consequence '{vc}' invalid")

    return errors


def validate_rubric(data: dict) -> list[str]:
    """Full structural validation of a rubric dict. Returns list of error strings."""
    errors = []

    # Top-level required fields
    required_top = ["_schema", "id", "version", "call_type", "domain",
                    "protocol_refs", "source_role_map", "checklist_items"]
    for field in required_top:
        if field not in data:
            errors.append(f"top-level: missing required field '{field}'")

    if data.get("_schema") != "ems_call_type_rubric_v1":
        errors.append(f"top-level: _schema must be 'ems_call_type_rubric_v1', got '{data.get('_schema')}'")

    if "id" in data and not TOP_ID_PATTERN.match(data["id"]):
        errors.append(f"top-level: id '{data['id']}' does not match pattern [a-z][a-z0-9_]*")

    if "domain" in data and data["domain"] not in VALID_DOMAINS:
        errors.append(f"top-level: domain '{data['domain']}' not in {VALID_DOMAINS}")

    for overlay in data.get("overlays_supported", []):
        if overlay not in VALID_OVERLAYS:
            errors.append(f"top-level: overlays_supported contains invalid value '{overlay}'")

    # protocol_refs
    protocol_ref_ids: set[str] = set()
    for i, ref in enumerate(data.get("protocol_refs", [])):
        if "id" not in ref:
            errors.append(f"protocol_refs[{i}]: missing 'id'")
        else:
            if ref["id"] in protocol_ref_ids:
                errors.append(f"protocol_refs: duplicate id '{ref['id']}'")
            protocol_ref_ids.add(ref["id"])
        if "title" not in ref:
            errors.append(f"protocol_refs[{i}]: missing 'title'")

    # source_role_map
    source_roles: set[str] = set()
    for role, cfg in data.get("source_role_map", {}).items():
        source_roles.add(role)
        if "training" not in cfg:
            errors.append(f"source_role_map.{role}: missing required 'training' key")
        if not isinstance(cfg.get("training", []), list):
            errors.append(f"source_role_map.{role}: 'training' must be a list")

    # checklist_items — IDs must be unique
    items = data.get("checklist_items", [])
    if not items:
        errors.append("checklist_items: must contain at least one item")

    seen_ids: set[str] = set()
    for item in items:
        item_id = item.get("id", "")
        if item_id in seen_ids:
            errors.append(f"checklist_items: duplicate id '{item_id}'")
        seen_ids.add(item_id)
        errors.extend(_check_item(item, protocol_ref_ids, source_roles))

    return errors


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_schema_file_is_valid_json():
    """Schema file must parse as valid JSON."""
    data = load_json(SCHEMA_FILE)
    assert isinstance(data, dict), "Schema file must be a JSON object"
    assert "_schema_version" in data, "Schema file must contain _schema_version"


@pytest.mark.parametrize("rubric_path", RUBRIC_FILES, ids=lambda p: p.stem)
def test_rubric_validates_against_schema(rubric_path: pathlib.Path):
    """Each rubric file must pass structural validation."""
    data = load_json(rubric_path)
    errors = validate_rubric(data)
    assert not errors, "Rubric validation errors:\n" + "\n".join(f"  - {e}" for e in errors)


@pytest.mark.parametrize("rubric_path", RUBRIC_FILES, ids=lambda p: p.stem)
def test_rubric_item_ids_are_namespaced_consistently(rubric_path: pathlib.Path):
    """All item IDs must share the same top-level namespace (prefix before the first dot)."""
    data = load_json(rubric_path)
    items = data.get("checklist_items", [])
    if not items:
        return
    prefixes = set()
    for item in items:
        item_id = item.get("id", "")
        prefix = item_id.split(".")[0] if "." in item_id else item_id
        prefixes.add(prefix)
    assert len(prefixes) == 1, (
        f"All item IDs must share one namespace prefix, found multiple: {sorted(prefixes)}"
    )


@pytest.mark.parametrize("rubric_path", RUBRIC_FILES, ids=lambda p: p.stem)
def test_every_item_has_nonempty_feedback(rubric_path: pathlib.Path):
    """done_feedback and missed_feedback must not be empty strings."""
    data = load_json(rubric_path)
    for item in data.get("checklist_items", []):
        iid = item.get("id", "?")
        assert item.get("done_feedback", "").strip(), f"item '{iid}': done_feedback is empty"
        assert item.get("missed_feedback", "").strip(), f"item '{iid}': missed_feedback is empty"


@pytest.mark.parametrize("rubric_path", RUBRIC_FILES, ids=lambda p: p.stem)
def test_unsafe_items_have_tier2_fallback_or_scene_entry(rubric_path: pathlib.Path):
    """Items marked unsafe_if_missed must have tier2_patterns or a scene_entry evidence requirement."""
    data = load_json(rubric_path)
    for item in data.get("checklist_items", []):
        if not item.get("unsafe_if_missed"):
            continue
        iid = item.get("id", "?")
        has_tier2 = bool(item.get("tier2_patterns"))
        # absence_check items are inherently transcript-free — the absence IS the evidence
        has_deterministic_path = any(
            r.get("type") in ("scene_entry", "absence_check")
            for r in item.get("evidence_requirements", [])
        )
        assert has_tier2 or has_deterministic_path, (
            f"item '{iid}' is unsafe_if_missed but has no tier2_patterns, scene_entry, or absence_check evidence path"
        )


@pytest.mark.parametrize("rubric_path", RUBRIC_FILES, ids=lambda p: p.stem)
def test_source_roles_in_evidence_requirements_are_defined(rubric_path: pathlib.Path):
    """All eligible_source_roles referenced in evidence_requirements must be in source_role_map."""
    data = load_json(rubric_path)
    defined_roles = set(data.get("source_role_map", {}).keys())
    for item in data.get("checklist_items", []):
        for req in item.get("evidence_requirements", []):
            for role in req.get("eligible_source_roles", []):
                assert role in defined_roles, (
                    f"item '{item.get('id')}': eligible_source_role '{role}' not in source_role_map"
                )


# ── Negative validator tests ──────────────────────────────────────────────────

def _minimal_valid_rubric() -> dict:
    """Returns the smallest rubric dict that passes validate_rubric()."""
    return {
        "_schema": "ems_call_type_rubric_v1",
        "id": "test_rubric",
        "version": "2026-01-01",
        "call_type": "test_call",
        "domain": "medical",
        "protocol_refs": [{"id": "proto_a", "title": "Test Protocol A"}],
        "source_role_map": {
            "ems_measured_vital": {"training": ["authored_vitals"]}
        },
        "checklist_items": [
            {
                "id": "test.item_a",
                "description": "Test item",
                "category": "clinical_performance",
                "subtype": "assessment",
                "point_value": 3,
                "required": "required",
                "applicable_levels": ["EMT"],
                "evidence_requirements": [
                    {"type": "finding", "finding_type": "vital", "key_pattern": "glucose"}
                ],
                "done_feedback": "Good.",
                "missed_feedback": "Missed.",
            }
        ],
    }


def test_validate_rubric_accepts_minimal_valid():
    """Baseline: _minimal_valid_rubric() must produce zero errors."""
    errors = validate_rubric(_minimal_valid_rubric())
    assert not errors, f"Baseline rubric unexpectedly invalid: {errors}"


def test_requirement_logic_all_with_undefined_source_role_fails():
    """requirement_logic 'all' item referencing an undefined source role must produce a validation error."""
    rubric = _minimal_valid_rubric()
    rubric["checklist_items"] = [
        {
            "id": "test.compound_item",
            "description": "Requires two findings (AND logic) — one from an undefined role.",
            "category": "clinical_performance",
            "subtype": "assessment",
            "point_value": 5,
            "required": "required",
            "requirement_logic": "all",
            "applicable_levels": ["EMT"],
            "evidence_requirements": [
                {
                    "type": "finding",
                    "finding_type": "vital",
                    "key_pattern": "glucose",
                    "eligible_source_roles": ["ems_measured_vital"],
                },
                {
                    "type": "finding",
                    "finding_type": "exam",
                    "key_pattern": "loc",
                    # "undefined_role" is not in source_role_map — must fail validation
                    "eligible_source_roles": ["undefined_role"],
                },
            ],
            "done_feedback": "Both assessed.",
            "missed_feedback": "Missed one or both.",
        }
    ]
    errors = validate_rubric(rubric)
    assert any("undefined_role" in e for e in errors), (
        "Expected a validation error for undefined eligible_source_role 'undefined_role', "
        f"but errors were: {errors}"
    )


def test_requirement_logic_all_with_single_requirement_fails():
    """requirement_logic 'all' with only one evidence_requirement must produce a validation error."""
    rubric = _minimal_valid_rubric()
    rubric["checklist_items"][0]["requirement_logic"] = "all"
    # checklist_items[0] already has exactly one evidence_requirement — must fail
    errors = validate_rubric(rubric)
    assert any("requirement_logic 'all' requires at least 2" in e for e in errors), (
        f"Expected 'all' requires at least 2 error, got: {errors}"
    )


def test_requirement_logic_unknown_value_fails():
    """An unrecognized requirement_logic value must produce a validation error."""
    rubric = _minimal_valid_rubric()
    rubric["checklist_items"][0]["requirement_logic"] = "xor"
    errors = validate_rubric(rubric)
    assert any("requirement_logic" in e and "xor" in e for e in errors), (
        f"Expected requirement_logic 'xor' invalid error, got: {errors}"
    )


def test_missing_schema_field_fails():
    """Missing _schema must produce a validation error."""
    rubric = _minimal_valid_rubric()
    del rubric["_schema"]
    errors = validate_rubric(rubric)
    assert any("_schema" in e for e in errors), f"Expected _schema error, got: {errors}"


def test_duplicate_item_ids_fail():
    """Duplicate checklist item IDs must produce a validation error."""
    rubric = _minimal_valid_rubric()
    rubric["checklist_items"].append(dict(rubric["checklist_items"][0]))  # exact duplicate
    errors = validate_rubric(rubric)
    assert any("duplicate id" in e for e in errors), f"Expected duplicate id error, got: {errors}"
