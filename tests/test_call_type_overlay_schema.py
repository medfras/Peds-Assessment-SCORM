"""
Validator for EMS call-type overlay files against the overlay schema.

Validates structural correctness, governance field presence, operation-specific
constraints, and cross-file consistency where the base rubric is available.

Add new overlay files to OVERLAY_FILES to include them in CI.
"""

import json
import pathlib
import re
import pytest

RUBRIC_DIR = pathlib.Path(__file__).parent.parent / "app" / "rubrics" / "nasemso"
OVERLAY_SCHEMA_FILE = RUBRIC_DIR / "ems_call_type_overlay.schema.json"
EXAMPLES_DIR = RUBRIC_DIR / "examples"
OVERLAYS_DIR = RUBRIC_DIR / "overlays"

OVERLAY_FILES = [
    EXAMPLES_DIR / "mi_hypoglycemia_state_overlay.json",
] + sorted(OVERLAYS_DIR.glob("*.json"))

# ── Constants ─────────────────────────────────────────────────────────────────

VALID_OVERLAY_TYPES = {"state", "agency", "scenario"}
VALID_OPS = {"suppress_item", "modify_item", "add_to_item", "add_item"}
VALID_CATEGORIES = {"clinical_performance", "protocols_treatment", "scope_adherence", "documentation", "professionalism"}
VALID_SUBTYPES = {"scene_entry", "assessment", "screen", "intervention", "reassessment", "transport",
                  "documentation_handoff", "documentation_narrative", "professionalism"}
VALID_LEVELS = {"EMR", "EMT", "AEMT", "Paramedic"}
VALID_REQUIRED = {"required", "optional", "bonus"}
VALID_EVIDENCE_TYPES = {"finding", "post_intervention_finding", "intervention", "session_event",
                        "scene_entry", "absence_check"}

MODIFY_ALLOWED_FIELDS = {"point_value", "required", "applicable_levels"}
MODIFY_FORBIDDEN_FIELDS = {"id", "description", "category", "subtype", "evidence_requirements",
                           "done_feedback", "missed_feedback", "unsafe_if_missed"}

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.]*$")
TOP_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path: pathlib.Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_base_rubric(call_type: str) -> dict | None:
    """Load base rubric for cross-reference validation. Returns None if not found."""
    candidates = sorted(RUBRIC_DIR.glob(f"{call_type}_v*.json"))
    if not candidates:
        return None
    with open(candidates[-1], encoding="utf-8") as f:
        return json.load(f)


def _validate_added_item(item: dict, op_idx: int, overlay_id: str, base_item_ids: set[str]) -> list[str]:
    errors = []
    ctx = f"overlay '{overlay_id}' operations[{op_idx}].item"

    required_fields = ["id", "description", "category", "subtype", "point_value",
                       "required", "applicable_levels", "evidence_requirements",
                       "done_feedback", "missed_feedback"]
    for field in required_fields:
        if field not in item:
            errors.append(f"{ctx}: missing required field '{field}'")

    iid = item.get("id", "<missing>")
    if "id" in item and not ID_PATTERN.match(iid):
        errors.append(f"{ctx}: id '{iid}' does not match pattern [a-z][a-z0-9_.]*")

    if "id" in item and iid in base_item_ids:
        errors.append(f"{ctx}: id '{iid}' collides with a NASEMSO base rubric item — use a jurisdiction-namespaced ID")

    if "category" in item and item["category"] not in VALID_CATEGORIES:
        errors.append(f"{ctx}: category '{item['category']}' not in {VALID_CATEGORIES}")

    if "subtype" in item and item["subtype"] not in VALID_SUBTYPES:
        errors.append(f"{ctx}: subtype '{item['subtype']}' not in {VALID_SUBTYPES}")

    if "required" in item and item["required"] not in VALID_REQUIRED:
        errors.append(f"{ctx}: required '{item['required']}' not in {VALID_REQUIRED}")

    if "applicable_levels" in item:
        if not item["applicable_levels"]:
            errors.append(f"{ctx}: applicable_levels must not be empty")
        for lv in item["applicable_levels"]:
            if lv not in VALID_LEVELS:
                errors.append(f"{ctx}: applicable_level '{lv}' not in {VALID_LEVELS}")

    if "point_value" in item and (not isinstance(item["point_value"], int) or item["point_value"] < 0):
        errors.append(f"{ctx}: point_value must be a non-negative integer")

    for req in item.get("evidence_requirements", []):
        if "type" not in req:
            errors.append(f"{ctx}: evidence_requirement missing 'type'")
        elif req["type"] not in VALID_EVIDENCE_TYPES:
            errors.append(f"{ctx}: evidence_requirement type '{req['type']}' not in {VALID_EVIDENCE_TYPES}")

    if not item.get("done_feedback", "").strip():
        errors.append(f"{ctx}: done_feedback is empty")
    if not item.get("missed_feedback", "").strip():
        errors.append(f"{ctx}: missed_feedback is empty")

    return errors


def _validate_operation(op: dict, op_idx: int, overlay_id: str, base_item_ids: set[str],
                         has_approved_by: bool) -> list[str]:
    errors = []
    ctx = f"overlay '{overlay_id}' operations[{op_idx}]"

    if "op" not in op:
        errors.append(f"{ctx}: missing required field 'op'")
        return errors

    op_type = op["op"]
    if op_type not in VALID_OPS:
        errors.append(f"{ctx}: op '{op_type}' not in {VALID_OPS}")
        return errors

    # Governance fields required on every operation
    if not op.get("reason", "").strip():
        errors.append(f"{ctx}: missing required field 'reason' (governance lock)")
    if not op.get("protocol_ref", "").strip():
        errors.append(f"{ctx}: missing required field 'protocol_ref' (governance lock)")

    if op_type == "suppress_item":
        if "item_id" not in op:
            errors.append(f"{ctx}: suppress_item requires 'item_id'")
        elif base_item_ids and op["item_id"] not in base_item_ids:
            errors.append(
                f"{ctx}: suppress_item item_id '{op['item_id']}' not found in base rubric — "
                f"cannot suppress an item that does not exist"
            )
        if not has_approved_by:
            errors.append(
                f"{ctx}: suppress_item requires 'approved_by' at the overlay file level "
                f"(suppress can remove safety checks — explicit approval is mandatory)"
            )

    elif op_type == "modify_item":
        if "item_id" not in op:
            errors.append(f"{ctx}: modify_item requires 'item_id'")
        elif base_item_ids and op["item_id"] not in base_item_ids:
            errors.append(f"{ctx}: modify_item item_id '{op['item_id']}' not found in base rubric")

        changes = op.get("changes")
        if not changes:
            errors.append(f"{ctx}: modify_item requires a non-empty 'changes' object")
        else:
            forbidden = set(changes.keys()) & MODIFY_FORBIDDEN_FIELDS
            if forbidden:
                errors.append(
                    f"{ctx}: modify_item.changes contains forbidden fields {sorted(forbidden)} — "
                    f"structural changes belong in the base rubric, not overlays"
                )
            unknown = set(changes.keys()) - MODIFY_ALLOWED_FIELDS - MODIFY_FORBIDDEN_FIELDS
            if unknown:
                errors.append(f"{ctx}: modify_item.changes contains unknown fields {sorted(unknown)}")

            if "point_value" in changes and (
                not isinstance(changes["point_value"], int) or changes["point_value"] < 0
            ):
                errors.append(f"{ctx}: modify_item.changes.point_value must be a non-negative integer")

            if "required" in changes and changes["required"] not in VALID_REQUIRED:
                errors.append(f"{ctx}: modify_item.changes.required '{changes['required']}' not in {VALID_REQUIRED}")

            if "applicable_levels" in changes:
                lvls = changes["applicable_levels"]
                if not lvls:
                    errors.append(f"{ctx}: modify_item.changes.applicable_levels must not be empty")
                for lv in lvls:
                    if lv not in VALID_LEVELS:
                        errors.append(f"{ctx}: modify_item.changes.applicable_level '{lv}' not in {VALID_LEVELS}")

    elif op_type == "add_to_item":
        if "item_id" not in op:
            errors.append(f"{ctx}: add_to_item requires 'item_id'")
        elif base_item_ids and op["item_id"] not in base_item_ids:
            errors.append(f"{ctx}: add_to_item item_id '{op['item_id']}' not found in base rubric")

        has_patterns = bool(op.get("append_tier2_patterns"))
        has_reqs = bool(op.get("append_evidence_requirements"))
        if not has_patterns and not has_reqs:
            errors.append(
                f"{ctx}: add_to_item requires at least one of "
                f"'append_tier2_patterns' or 'append_evidence_requirements' to be non-empty"
            )
        for req in op.get("append_evidence_requirements", []):
            if "type" not in req:
                errors.append(f"{ctx}: append_evidence_requirements entry missing 'type'")
            elif req["type"] not in VALID_EVIDENCE_TYPES:
                errors.append(f"{ctx}: append_evidence_requirements type '{req['type']}' not in {VALID_EVIDENCE_TYPES}")

    elif op_type == "add_item":
        item = op.get("item")
        if not item:
            errors.append(f"{ctx}: add_item requires an 'item' object")
        else:
            errors.extend(_validate_added_item(item, op_idx, overlay_id, base_item_ids))

    return errors


def validate_overlay(data: dict, base_rubric: dict | None = None) -> list[str]:
    """Full structural validation of an overlay dict. Returns list of error strings."""
    errors = []

    required_top = ["_schema", "id", "version", "call_type", "overlay_type", "jurisdiction",
                    "effective_date", "operations"]
    for field in required_top:
        if field not in data:
            errors.append(f"top-level: missing required field '{field}'")

    if data.get("_schema") != "ems_call_type_overlay_v1":
        errors.append(f"top-level: _schema must be 'ems_call_type_overlay_v1', got '{data.get('_schema')}'")

    if "id" in data and not TOP_ID_PATTERN.match(data["id"]):
        errors.append(f"top-level: id '{data['id']}' does not match pattern [a-z][a-z0-9_]*")

    if "overlay_type" in data and data["overlay_type"] not in VALID_OVERLAY_TYPES:
        errors.append(f"top-level: overlay_type '{data['overlay_type']}' not in {VALID_OVERLAY_TYPES}")

    if "effective_date" in data and not DATE_PATTERN.match(data.get("effective_date", "")):
        errors.append(f"top-level: effective_date must be YYYY-MM-DD, got '{data.get('effective_date')}'")

    operations = data.get("operations", [])
    if not operations:
        errors.append("top-level: operations must contain at least one item")

    # Collect base rubric item IDs for cross-reference checks
    base_item_ids: set[str] = set()
    if base_rubric:
        base_item_ids = {item["id"] for item in base_rubric.get("checklist_items", []) if "id" in item}

    has_approved_by = bool(data.get("approved_by", "").strip() if isinstance(data.get("approved_by"), str) else data.get("approved_by"))
    has_suppress = any(op.get("op") == "suppress_item" for op in operations if isinstance(op, dict))

    if has_suppress and not has_approved_by:
        errors.append(
            "top-level: 'approved_by' is required when any operation is suppress_item — "
            "suppress can remove safety checks and requires explicit approval"
        )

    # Track added item IDs to catch intra-overlay duplicates
    added_ids: set[str] = set()
    for i, op in enumerate(operations):
        if not isinstance(op, dict):
            errors.append(f"operations[{i}]: must be an object")
            continue
        errors.extend(_validate_operation(op, i, data.get("id", "?"), base_item_ids, has_approved_by))
        if op.get("op") == "add_item" and isinstance(op.get("item"), dict):
            added_id = op["item"].get("id", "")
            if added_id in added_ids:
                errors.append(f"operations[{i}]: add_item id '{added_id}' is duplicated within this overlay")
            added_ids.add(added_id)

    return errors


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_overlay_schema_file_is_valid_json():
    """Overlay schema file must parse as valid JSON."""
    data = load_json(OVERLAY_SCHEMA_FILE)
    assert isinstance(data, dict)
    assert "_schema_version" in data
    assert data["_schema_version"] == "1.0"


@pytest.mark.parametrize("overlay_path", OVERLAY_FILES, ids=lambda p: p.stem)
def test_overlay_validates_against_schema(overlay_path: pathlib.Path):
    """Each overlay file must pass structural validation."""
    data = load_json(overlay_path)
    call_type = data.get("call_type", "")
    base_rubric = _load_base_rubric(call_type)
    errors = validate_overlay(data, base_rubric)
    assert not errors, "Overlay validation errors:\n" + "\n".join(f"  - {e}" for e in errors)


@pytest.mark.parametrize("overlay_path", OVERLAY_FILES, ids=lambda p: p.stem)
def test_overlay_all_ops_have_governance_fields(overlay_path: pathlib.Path):
    """Every operation must have non-empty reason and protocol_ref."""
    data = load_json(overlay_path)
    for i, op in enumerate(data.get("operations", [])):
        assert op.get("reason", "").strip(), f"operations[{i}]: reason is empty"
        assert op.get("protocol_ref", "").strip(), f"operations[{i}]: protocol_ref is empty"


@pytest.mark.parametrize("overlay_path", OVERLAY_FILES, ids=lambda p: p.stem)
def test_overlay_suppress_requires_approved_by(overlay_path: pathlib.Path):
    """Any overlay with suppress_item must have approved_by at the file level."""
    data = load_json(overlay_path)
    has_suppress = any(op.get("op") == "suppress_item" for op in data.get("operations", []))
    if has_suppress:
        assert data.get("approved_by", "").strip(), (
            "Overlay has suppress_item but 'approved_by' is missing or empty at the file level"
        )


@pytest.mark.parametrize("overlay_path", OVERLAY_FILES, ids=lambda p: p.stem)
def test_overlay_add_item_ids_do_not_collide_with_base(overlay_path: pathlib.Path):
    """add_item IDs must not collide with NASEMSO base rubric item IDs."""
    data = load_json(overlay_path)
    base_rubric = _load_base_rubric(data.get("call_type", ""))
    if not base_rubric:
        pytest.skip(f"No base rubric found for call_type '{data.get('call_type')}'")
    base_ids = {item["id"] for item in base_rubric.get("checklist_items", []) if "id" in item}
    for i, op in enumerate(data.get("operations", [])):
        if op.get("op") == "add_item":
            added_id = op.get("item", {}).get("id", "")
            assert added_id not in base_ids, (
                f"operations[{i}].item.id '{added_id}' collides with a NASEMSO base rubric item"
            )


@pytest.mark.parametrize("overlay_path", OVERLAY_FILES, ids=lambda p: p.stem)
def test_overlay_modify_item_uses_only_allowed_fields(overlay_path: pathlib.Path):
    """modify_item.changes must not contain forbidden structural fields."""
    data = load_json(overlay_path)
    for i, op in enumerate(data.get("operations", [])):
        if op.get("op") != "modify_item":
            continue
        changes = op.get("changes", {})
        forbidden = set(changes.keys()) & MODIFY_FORBIDDEN_FIELDS
        assert not forbidden, (
            f"operations[{i}].changes contains forbidden fields {sorted(forbidden)}"
        )


@pytest.mark.parametrize("overlay_path", OVERLAY_FILES, ids=lambda p: p.stem)
def test_overlay_add_to_item_has_nonempty_additions(overlay_path: pathlib.Path):
    """add_to_item must provide at least one non-empty append list."""
    data = load_json(overlay_path)
    for i, op in enumerate(data.get("operations", [])):
        if op.get("op") != "add_to_item":
            continue
        has_patterns = bool(op.get("append_tier2_patterns"))
        has_reqs = bool(op.get("append_evidence_requirements"))
        assert has_patterns or has_reqs, (
            f"operations[{i}] (add_to_item): both append_tier2_patterns and "
            f"append_evidence_requirements are empty or missing"
        )


@pytest.mark.parametrize("overlay_path", OVERLAY_FILES, ids=lambda p: p.stem)
def test_overlay_added_items_have_nonempty_feedback(overlay_path: pathlib.Path):
    """add_item items must have non-empty done_feedback and missed_feedback."""
    data = load_json(overlay_path)
    for i, op in enumerate(data.get("operations", [])):
        if op.get("op") != "add_item":
            continue
        item = op.get("item", {})
        iid = item.get("id", f"operations[{i}].item")
        assert item.get("done_feedback", "").strip(), f"add_item '{iid}': done_feedback is empty"
        assert item.get("missed_feedback", "").strip(), f"add_item '{iid}': missed_feedback is empty"


# ── Negative validator tests ──────────────────────────────────────────────────

def _minimal_valid_overlay() -> dict:
    """Returns the smallest overlay dict that passes validate_overlay()."""
    return {
        "_schema": "ems_call_type_overlay_v1",
        "id": "test_overlay",
        "version": "2026-01-01",
        "call_type": "test_call",
        "overlay_type": "state",
        "jurisdiction": "Test State",
        "effective_date": "2026-06-01",
        "approved_by": "Test Authority",
        "operations": [
            {
                "op": "modify_item",
                "item_id": "test.item_a",
                "reason": "Test reason.",
                "protocol_ref": "Test Protocol 1.2.3",
                "changes": {"point_value": 3},
            }
        ],
    }


def test_validate_overlay_accepts_minimal_valid():
    errors = validate_overlay(_minimal_valid_overlay())
    assert not errors, f"Baseline overlay unexpectedly invalid: {errors}"


def test_missing_schema_field_fails():
    overlay = _minimal_valid_overlay()
    del overlay["_schema"]
    errors = validate_overlay(overlay)
    assert any("_schema" in e for e in errors)


def test_wrong_schema_value_fails():
    overlay = _minimal_valid_overlay()
    overlay["_schema"] = "ems_call_type_rubric_v1"
    errors = validate_overlay(overlay)
    assert any("ems_call_type_overlay_v1" in e for e in errors)


def test_suppress_without_approved_by_fails():
    overlay = _minimal_valid_overlay()
    del overlay["approved_by"]
    overlay["operations"] = [{
        "op": "suppress_item",
        "item_id": "test.item_a",
        "reason": "Not needed here.",
        "protocol_ref": "Protocol 1.2",
    }]
    errors = validate_overlay(overlay)
    assert any("approved_by" in e and "suppress" in e.lower() for e in errors), (
        f"Expected suppress_item without approved_by to fail, got: {errors}"
    )


def test_modify_forbidden_field_fails():
    overlay = _minimal_valid_overlay()
    overlay["operations"][0]["changes"] = {"description": "New description"}
    errors = validate_overlay(overlay)
    assert any("forbidden" in e for e in errors)


def test_add_to_item_empty_additions_fails():
    overlay = _minimal_valid_overlay()
    overlay["operations"] = [{
        "op": "add_to_item",
        "item_id": "test.item_a",
        "reason": "Test.",
        "protocol_ref": "Protocol 1.2",
        "append_tier2_patterns": [],
        "append_evidence_requirements": [],
    }]
    errors = validate_overlay(overlay)
    assert any("append" in e and "empty" in e for e in errors)


def test_missing_reason_fails():
    overlay = _minimal_valid_overlay()
    del overlay["operations"][0]["reason"]
    errors = validate_overlay(overlay)
    assert any("reason" in e for e in errors)


def test_missing_protocol_ref_fails():
    overlay = _minimal_valid_overlay()
    del overlay["operations"][0]["protocol_ref"]
    errors = validate_overlay(overlay)
    assert any("protocol_ref" in e for e in errors)


def test_add_item_colliding_with_base_fails():
    overlay = _minimal_valid_overlay()
    overlay["operations"] = [{
        "op": "add_item",
        "reason": "Test.",
        "protocol_ref": "Protocol 1.2",
        "item": {
            "id": "base_item_id",
            "description": "Colliding item",
            "category": "clinical_performance",
            "subtype": "assessment",
            "point_value": 2,
            "required": "required",
            "applicable_levels": ["EMT"],
            "evidence_requirements": [{"type": "intervention", "intervention_key": "o2"}],
            "done_feedback": "Done.",
            "missed_feedback": "Missed.",
        }
    }]
    base_rubric = {
        "checklist_items": [{"id": "base_item_id", "description": "Base item"}]
    }
    errors = validate_overlay(overlay, base_rubric)
    assert any("collides" in e for e in errors)


def test_suppress_of_nonexistent_base_item_fails():
    overlay = _minimal_valid_overlay()
    overlay["operations"] = [{
        "op": "suppress_item",
        "item_id": "nonexistent.item",
        "reason": "Does not exist.",
        "protocol_ref": "Protocol 1.2",
    }]
    base_rubric = {"checklist_items": [{"id": "real_item"}]}
    errors = validate_overlay(overlay, base_rubric)
    assert any("not found in base rubric" in e for e in errors)


def test_invalid_overlay_type_fails():
    overlay = _minimal_valid_overlay()
    overlay["overlay_type"] = "district"
    errors = validate_overlay(overlay)
    assert any("overlay_type" in e for e in errors)
