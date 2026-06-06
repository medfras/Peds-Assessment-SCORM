"""
Unit tests for app/rubric_loader.py — Group F1 and F2a.

Covers: source role resolution, empty-role detection, file discovery,
missing-rubric handling, known rubric files, and shadow composition.
"""

import json
import pathlib
import pytest

from app.rubric_loader import (
    ResolvedRubric,
    ShadowCompositionReport,
    ComposedChecklist,
    load_call_type_rubric,
    log_shadow_rubric,
    compose_shadow_checklist,
    compose_active_checklist,
    _find_rubric_file,
    _resolve_source_roles,
    _resolve_evidence_requirement,
)

RUBRIC_DIR = pathlib.Path(__file__).parent.parent / "app" / "rubrics" / "nasemso"


# ── _resolve_source_roles ─────────────────────────────────────────────────────


def test_resolve_source_roles_training():
    source_role_map = {
        "ems_measured_vital": {"training": ["authored_vitals"], "qaqi": ["epcr_vital"]},
        "history_obtained": {"training": ["caregiver_reported_history", "patient_reported_history"]},
    }
    resolved, empty = _resolve_source_roles(source_role_map, ["ems_measured_vital"], "training")
    assert resolved == ["authored_vitals"]
    assert empty == []


def test_resolve_source_roles_qaqi():
    source_role_map = {
        "ems_measured_vital": {"training": ["authored_vitals"], "qaqi": ["epcr_vital", "monitor_import"]},
    }
    resolved, empty = _resolve_source_roles(source_role_map, ["ems_measured_vital"], "qaqi")
    assert resolved == ["epcr_vital", "monitor_import"]
    assert empty == []


def test_resolve_source_roles_multiple_roles_merged():
    source_role_map = {
        "caregiver_reported": {"training": ["caregiver_reported_history"]},
        "patient_reported": {"training": ["patient_reported_history"]},
    }
    resolved, empty = _resolve_source_roles(
        source_role_map, ["caregiver_reported", "patient_reported"], "training"
    )
    assert set(resolved) == {"caregiver_reported_history", "patient_reported_history"}
    assert empty == []


def test_resolve_source_roles_empty_role_in_context():
    """A role with an empty training list produces an empty_roles entry, not an error."""
    source_role_map = {
        "ems_performed_exam": {"training": [], "qaqi": ["epcr_exam"]},
    }
    resolved, empty = _resolve_source_roles(source_role_map, ["ems_performed_exam"], "training")
    assert resolved == []
    assert "ems_performed_exam" in empty


def test_resolve_source_roles_undefined_role_produces_empty_role():
    """An undefined abstract role is treated as empty (not a hard error)."""
    source_role_map = {}
    resolved, empty = _resolve_source_roles(source_role_map, ["undefined_role"], "training")
    assert resolved == []
    assert "undefined_role" in empty


def test_resolve_source_roles_no_roles_returns_empty():
    resolved, empty = _resolve_source_roles({}, [], "training")
    assert resolved == []
    assert empty == []


# ── _resolve_evidence_requirement ─────────────────────────────────────────────


def test_resolve_evidence_requirement_finding_with_roles():
    source_role_map = {
        "ems_measured_vital": {"training": ["authored_vitals"]},
    }
    req = {
        "type": "finding",
        "finding_type": "vital",
        "key_pattern": "glucose",
        "eligible_source_roles": ["ems_measured_vital"],
    }
    resolved = _resolve_evidence_requirement(req, source_role_map, "training")
    assert resolved.type == "finding"
    assert resolved.finding_type == "vital"
    assert resolved.key_pattern == "glucose"
    assert resolved.resolved_sources == ["authored_vitals"]
    assert resolved.original_source_roles == ["ems_measured_vital"]
    assert resolved.empty_roles == []
    assert not resolved.empty_roles


def test_resolve_evidence_requirement_no_role_filter():
    """No eligible_source_roles → all sources eligible (empty resolved_sources, not an error)."""
    req = {"type": "intervention", "intervention_key": "o2_nrb"}
    resolved = _resolve_evidence_requirement(req, {}, "training")
    assert resolved.type == "intervention"
    assert resolved.intervention_key == "o2_nrb"
    assert resolved.resolved_sources == []
    assert resolved.original_source_roles == []
    assert resolved.empty_roles == []


def test_resolve_evidence_requirement_empty_role_flagged():
    """A role with no training sources is flagged in empty_roles."""
    source_role_map = {"ems_performed_exam": {"training": []}}
    req = {
        "type": "finding",
        "finding_type": "exam",
        "key_pattern": "breath_sounds",
        "eligible_source_roles": ["ems_performed_exam"],
    }
    resolved = _resolve_evidence_requirement(req, source_role_map, "training")
    assert resolved.empty_roles == ["ems_performed_exam"]
    assert resolved.resolved_sources == []


# ── _find_rubric_file ─────────────────────────────────────────────────────────


def test_find_rubric_file_respiratory_distress():
    path = _find_rubric_file("respiratory_distress")
    assert path is not None
    assert path.exists()
    assert "respiratory_distress" in path.name


def test_find_rubric_file_missing_call_type():
    path = _find_rubric_file("nonexistent_call_type_xyzzy")
    assert path is None


# ── load_call_type_rubric ─────────────────────────────────────────────────────


@pytest.mark.parametrize("call_type,expected_items_min", [
    ("respiratory_distress", 5),
    ("pediatric_croup", 5),
    ("hypoglycemia", 10),
    ("head_injury", 8),
    ("nremt_trauma", 10),
])
def test_load_known_rubric(call_type, expected_items_min):
    rubric = load_call_type_rubric(call_type, "training")
    assert rubric is not None
    assert rubric.call_type == call_type
    assert len(rubric.items) >= expected_items_min
    assert rubric.deployment_context == "training"
    assert rubric.rubric_id
    assert rubric.rubric_version


def test_load_missing_rubric_returns_none():
    rubric = load_call_type_rubric("no_such_call_type_xyzzy", "training")
    assert rubric is None


def test_load_rubric_training_vs_qaqi_different_sources():
    """Training and qaqi contexts resolve to different concrete sources."""
    training = load_call_type_rubric("respiratory_distress", "training")
    qaqi = load_call_type_rubric("respiratory_distress", "qaqi")
    assert training is not None
    assert qaqi is not None

    # Collect all resolved sources across all requirements
    def all_sources(rubric: ResolvedRubric) -> set[str]:
        return {
            s
            for item in rubric.items
            for req in item.evidence_requirements
            for s in req.resolved_sources
        }

    training_sources = all_sources(training)
    qaqi_sources = all_sources(qaqi)
    # Training uses authored_vitals; qaqi uses epcr sources — they must not be identical
    assert training_sources != qaqi_sources, (
        "Training and qaqi contexts should resolve to different concrete sources"
    )


def test_load_rubric_items_have_required_fields():
    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    for item in rubric.items:
        assert item.item_id, f"item missing id"
        assert item.description, f"item '{item.item_id}' missing description"
        assert item.done_feedback, f"item '{item.item_id}' missing done_feedback"
        assert item.missed_feedback, f"item '{item.item_id}' missing missed_feedback"
        assert item.requirement_logic in ("any", "all"), (
            f"item '{item.item_id}' has invalid requirement_logic '{item.requirement_logic}'"
        )
        assert item.provenance == "call_type_rubric"


def test_load_rubric_exam_items_have_tier2_patterns():
    """
    Items with ems_performed_exam and finding_type='exam' will not produce Tier 1
    matches in training: authored_vitals findings carry finding_type='vital', not 'exam'.
    These items must have tier2_patterns as their effective fallback path.

    Note: the loader itself cannot detect this finding_type/source mismatch —
    that is a scoring engine concern. The loader correctly reports authored_vitals
    as a resolved source. The fallback requirement is validated here instead.
    """
    rubric = load_call_type_rubric("respiratory_distress", "training")
    assert rubric is not None
    exam_items = [
        item for item in rubric.items
        if any(
            req.finding_type == "exam" and "ems_performed_exam" in req.original_source_roles
            for req in item.evidence_requirements
        )
    ]
    assert exam_items, "Expected at least one exam item using ems_performed_exam in respiratory_distress rubric"
    for item in exam_items:
        assert item.tier2_patterns, (
            f"item '{item.item_id}' uses ems_performed_exam with finding_type=exam "
            f"(no effective Tier 1 training path) but has no tier2_patterns fallback"
        )


def test_lung_sounds_item_is_challenge_source_gated():
    """Lung sound challenge items must not fall back to transcript/AI prose."""
    rubric = load_call_type_rubric("respiratory_distress", "training")
    assert rubric is not None
    active = compose_active_checklist([], rubric, "EMT")
    item = next(i for i in active.items if i.id == "resp_distress.lung_sounds")

    assert item.allowed_tiers == [1]
    assert item.tier1_match is not None
    assert item.tier1_match.eligible_sources == ["lung_sound_challenge"]
    assert item.tier1_match.require_source is True


def test_hypoglycemia_gcs_item_is_modal_source_gated():
    """Formal GCS credit is separate from LOC/AVPU and requires the GCS modal."""
    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    active = compose_active_checklist([], rubric, "EMT")
    item = next(i for i in active.items if i.id == "hypoglycemia.gcs_calculated")

    assert item.allowed_tiers == [1]
    assert item.tier1_match is not None
    assert item.tier1_match.finding_type == "vital"
    assert item.tier1_match.eligible_sources == ["gcs_modal"]
    assert item.tier1_match.require_source is True


def test_hypoglycemia_bgl_item_is_glucometer_source_gated():
    """On-scene BGL credit requires the EMS glucometer/fingerstick source."""
    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    active = compose_active_checklist([], rubric, "EMT")
    item = next(i for i in active.items if i.id == "hypoglycemia.blood_glucose_check")

    assert item.allowed_tiers == [1]
    assert item.tier1_match is not None
    assert item.tier1_match.finding_type == "vital"
    assert item.tier1_match.eligible_sources == ["glucometer_check"]
    assert item.tier1_match.require_source is True


def test_load_rubric_unsafe_items_have_tier2_patterns_or_deterministic_path():
    """Mirrors the CI validator rule: unsafe items must have a fallback."""
    for call_type in ("respiratory_distress", "pediatric_croup", "hypoglycemia", "head_injury", "nremt_trauma"):
        rubric = load_call_type_rubric(call_type, "training")
        assert rubric is not None
        for item in rubric.items:
            if not item.unsafe_if_missed:
                continue
            has_tier2 = bool(item.tier2_patterns)
            has_deterministic = any(
                r.type in ("scene_entry", "absence_check")
                for r in item.evidence_requirements
            )
            assert has_tier2 or has_deterministic, (
                f"[{call_type}] item '{item.item_id}' is unsafe_if_missed but has no tier2 or deterministic path"
            )


def test_load_rubric_requirement_logic_all_items_have_multiple_requirements():
    """Items with requirement_logic='all' must have >=2 evidence_requirements."""
    for call_type in ("respiratory_distress", "pediatric_croup", "hypoglycemia", "head_injury", "nremt_trauma"):
        rubric = load_call_type_rubric(call_type, "training")
        assert rubric is not None
        for item in rubric.items:
            if item.requirement_logic == "all":
                assert len(item.evidence_requirements) >= 2, (
                    f"[{call_type}] item '{item.item_id}' has requirement_logic='all' "
                    f"but only {len(item.evidence_requirements)} evidence_requirement(s)"
                )


# ── log_shadow_rubric ─────────────────────────────────────────────────────────


def test_log_shadow_rubric_does_not_raise():
    """log_shadow_rubric must not raise even if some roles are empty."""
    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    log_shadow_rubric(rubric)  # must not raise


# ── compose_shadow_checklist (F2a) ────────────────────────────────────────────


def _make_mock_checklist_item(item_id: str, description: str = "Test item", category: str = "clinical_performance", provenance: str = "scenario_overlay"):
    """Minimal ChecklistItem-like object for composition tests."""
    from app.checklist import ChecklistItem
    return ChecklistItem(
        id=item_id,
        description=description,
        category=category,
        subtype="assessment",
        point_value=2,
        required="required",
        applicable_levels=["EMT"],
        provenance=provenance,
    )


NOW_ISO = "2026-05-13T00:00:00+00:00"


def test_compose_shadow_empty_base():
    """With an empty base checklist, all call-type items should appear in added_items."""
    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    report = compose_shadow_checklist(
        base_items=[],
        rubric=rubric,
        provider_level="EMT",
        composed_at=NOW_ISO,
    )
    assert isinstance(report, ShadowCompositionReport)
    assert report.base_item_count == 0
    assert report.call_type_item_count == len(rubric.items)
    assert report.composed_item_count == len(rubric.items)
    assert len(report.added_items) == len(rubric.items)
    assert report.conflicts == []


def test_compose_shadow_counts_are_consistent():
    """Composed count = base + added (conflicts are excluded from composition)."""
    rubric = load_call_type_rubric("respiratory_distress", "training")
    assert rubric is not None
    base = [_make_mock_checklist_item("scene.ppe_complete"), _make_mock_checklist_item("scene.intro")]
    report = compose_shadow_checklist(
        base_items=base,
        rubric=rubric,
        provider_level="EMT",
        composed_at=NOW_ISO,
    )
    assert report.base_item_count == 2
    assert report.call_type_item_count == len(rubric.items)
    assert report.composed_item_count == report.base_item_count + len(report.added_items)


def test_compose_shadow_detects_duplicate_id():
    """A call-type item ID already in base must produce a duplicate_id conflict."""
    rubric = load_call_type_rubric("respiratory_distress", "training")
    assert rubric is not None
    # Grab the first call-type item ID and put it in base
    first_ct_id = rubric.items[0].item_id
    base = [_make_mock_checklist_item(first_ct_id)]
    report = compose_shadow_checklist(
        base_items=base,
        rubric=rubric,
        provider_level="EMT",
        composed_at=NOW_ISO,
    )
    assert len(report.conflicts) >= 1
    conflict = next(c for c in report.conflicts if c["item_id"] == first_ct_id)
    assert conflict["kind"] == "duplicate_id"
    # Conflicting item must NOT appear in added_items
    assert not any(a["item_id"] == first_ct_id for a in report.added_items)


def test_compose_shadow_no_conflict_with_disjoint_base():
    """If base has no overlapping IDs, there should be no conflicts."""
    rubric = load_call_type_rubric("pediatric_croup", "training")
    assert rubric is not None
    base = [
        _make_mock_checklist_item("scene.ppe_complete"),
        _make_mock_checklist_item("scene.intro"),
    ]
    report = compose_shadow_checklist(
        base_items=base,
        rubric=rubric,
        provider_level="EMT",
        composed_at=NOW_ISO,
    )
    assert report.conflicts == []
    # Level-excluded items do NOT appear in added_items — they go in level_excluded_items instead.
    # added_items + level_excluded_items must equal the total call-type item count.
    assert len(report.added_items) + len(report.level_excluded_items) == len(rubric.items)


def test_compose_shadow_flags_all_logic_items():
    """Items with requirement_logic='all' are listed in all_logic_items."""
    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    all_logic_ct = [i.item_id for i in rubric.items if i.requirement_logic == "all"]
    report = compose_shadow_checklist([], rubric, "EMT", NOW_ISO)
    assert set(report.all_logic_items) == set(all_logic_ct), (
        f"Expected all_logic_items to match call-type items with logic='all'"
    )


def test_compose_shadow_flags_level_excluded_items():
    """Items whose applicable_levels exclude provider_level are flagged."""
    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    # Using "EMR" which has no ALS-only items in hypoglycemia rubric; but items
    # must apply to at least one level. Find items that don't include "EMR".
    excluded_expected = [
        i.item_id for i in rubric.items
        if i.applicable_levels and "EMR" not in i.applicable_levels
    ]
    report = compose_shadow_checklist([], rubric, "EMR", NOW_ISO)
    assert set(report.level_excluded_items) == set(excluded_expected)


def test_compose_shadow_empty_role_items_tracked():
    """Items with has_empty_roles are listed in empty_role_items."""
    rubric = load_call_type_rubric("respiratory_distress", "training")
    assert rubric is not None
    expected = [i.item_id for i in rubric.items if i.has_empty_roles]
    report = compose_shadow_checklist([], rubric, "EMT", NOW_ISO)
    assert set(report.empty_role_items) == set(expected)


def test_compose_shadow_serialises_to_dict():
    """to_dict() must produce a JSON-serialisable dict with all expected top-level keys."""
    import json as json_mod
    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    report = compose_shadow_checklist([], rubric, "Paramedic", NOW_ISO)
    d = report.to_dict()
    assert isinstance(d, dict)
    for key in (
        "base_item_count", "call_type_item_count", "composed_item_count",
        "conflicts", "added_items", "all_logic_items", "empty_role_items",
        "level_excluded_items", "suspected_duplicates",
        "call_type", "rubric_id", "rubric_version", "deployment_context", "composed_at",
    ):
        assert key in d, f"shadow report missing key '{key}'"
    json_mod.dumps(d)  # must not raise


def test_compose_shadow_does_not_raise_on_log():
    """compose_shadow_checklist must not raise on any known rubric."""
    for call_type in ("respiratory_distress", "pediatric_croup", "hypoglycemia", "head_injury", "nremt_trauma"):
        rubric = load_call_type_rubric(call_type, "training")
        assert rubric is not None
        compose_shadow_checklist([], rubric, "EMT", NOW_ISO)  # must not raise


# ── compose_active_checklist (F2b) ────────────────────────────────────────────


def test_compose_active_returns_composed_checklist():
    """compose_active_checklist returns a ComposedChecklist with items and overlay_audit."""
    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    result = compose_active_checklist([], rubric, "EMT")
    assert isinstance(result, ComposedChecklist)
    assert len(result.items) == len(rubric.items)
    assert isinstance(result.overlay_audit, list)


def test_compose_active_items_have_call_type_rubric_provenance():
    """All items added from call-type rubric carry provenance='call_type_rubric'."""
    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    result = compose_active_checklist([], rubric, "EMT")
    for item in result.items:
        assert item.provenance == "call_type_rubric", (
            f"item '{item.id}' has unexpected provenance '{item.provenance}'"
        )


def test_compose_active_base_items_preserved_first():
    """Base checklist items appear before call-type rubric items and keep their provenance."""
    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    base = [_make_mock_checklist_item("scene.ppe", provenance="universal_base")]
    result = compose_active_checklist(base, rubric, "EMT")
    assert result.items[0].id == "scene.ppe"
    assert result.items[0].provenance == "universal_base"
    assert len(result.items) == 1 + len(rubric.items)


def test_compose_active_duplicate_id_skipped():
    """A call-type item whose ID is already in base is skipped (logged as WARNING)."""
    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    first_ct_id = rubric.items[0].item_id
    base = [_make_mock_checklist_item(first_ct_id)]
    result = compose_active_checklist(base, rubric, "EMT")
    # Duplicate must not appear twice — base version is kept, call-type version skipped
    matching = [i for i in result.items if i.id == first_ct_id]
    assert len(matching) == 1
    assert matching[0].provenance != "call_type_rubric"


def test_compose_active_level_excluded_items_not_in_result():
    """Items whose applicable_levels exclude provider_level are not added."""
    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    result_emt = compose_active_checklist([], rubric, "EMT")
    result_emr = compose_active_checklist([], rubric, "EMR")
    emt_ids = {i.id for i in result_emt.items}
    emr_ids = {i.id for i in result_emr.items}
    # EMR-excluded items must not be in the EMR result
    for ct_item in rubric.items:
        if ct_item.applicable_levels and "EMR" not in ct_item.applicable_levels:
            assert ct_item.item_id not in emr_ids, (
                f"item '{ct_item.item_id}' is not applicable to EMR but appeared in EMR result"
            )


def test_respiratory_distress_ecg_not_in_emt_checklist():
    """12-lead ECG is not an EMT-scope respiratory-distress checklist item."""
    rubric = load_call_type_rubric("respiratory_distress", "training")
    assert rubric is not None
    result = compose_active_checklist([], rubric, "EMT")
    assert "resp_distress.ecg_12lead" not in {item.id for item in result.items}


def test_compose_active_all_logic_items_have_tier1_matches():
    """Items with requirement_logic='all' are converted with tier1_matches (not single tier1_match)."""
    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    result = compose_active_checklist([], rubric, "Paramedic")
    for item in result.items:
        if item.requirement_logic == "all":
            assert item.tier1_matches, (
                f"item '{item.id}' has requirement_logic='all' but tier1_matches is empty"
            )
            assert item.tier1_match is None, (
                f"item '{item.id}' has requirement_logic='all' but also has single tier1_match set"
            )


def test_compose_active_any_logic_items_have_single_tier1_match():
    """Items with requirement_logic='any' and evidence_requirements use single tier1_match."""
    rubric = load_call_type_rubric("respiratory_distress", "training")
    assert rubric is not None
    result = compose_active_checklist([], rubric, "EMT")
    for item in result.items:
        if item.requirement_logic == "any" and item.tier1_matches:
            assert False, f"item '{item.id}' has requirement_logic='any' but tier1_matches is set"


def test_compose_active_suppress_op_removes_item():
    """suppress_item overlay op removes the item from the composed list and records audit entry."""
    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    first_ct_id = rubric.items[0].item_id
    suppress_op = {
        "op": "suppress_item",
        "item_id": first_ct_id,
        "reason": "Not required by test jurisdiction.",
        "protocol_ref": "Test Protocol 1.0",
    }
    result = compose_active_checklist([], rubric, "EMT", overlay_ops=[suppress_op], overlay_id="test_overlay")
    ids_in_result = {i.id for i in result.items}
    assert first_ct_id not in ids_in_result, f"suppressed item '{first_ct_id}' still in composed checklist"
    audit_entries = [a for a in result.overlay_audit if a["item_id"] == first_ct_id]
    assert len(audit_entries) == 1
    assert audit_entries[0]["operation"] == "suppress_item"
    assert audit_entries[0]["overlay_id"] == "test_overlay"
    assert audit_entries[0]["reason"]
    assert audit_entries[0]["protocol_ref"]


def test_compose_active_modify_op_changes_point_value():
    """modify_item overlay op patches point_value on the converted ChecklistItem."""
    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    target = rubric.items[0]
    original_pv = target.point_value
    new_pv = original_pv + 10
    modify_op = {
        "op": "modify_item",
        "item_id": target.item_id,
        "reason": "Jurisdiction increases point weight.",
        "protocol_ref": "Test Protocol 2.0",
        "changes": {"point_value": new_pv},
    }
    result = compose_active_checklist([], rubric, "EMT", overlay_ops=[modify_op], overlay_id="test_overlay")
    modified = next(i for i in result.items if i.id == target.item_id)
    assert modified.point_value == new_pv
    audit = next(a for a in result.overlay_audit if a["item_id"] == target.item_id)
    assert audit["operation"] == "modify_item"


def test_compose_active_overlay_audit_is_serialisable():
    """overlay_audit must be JSON-serialisable for storage in checklist_states."""
    import json as json_mod
    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    suppress_op = {
        "op": "suppress_item",
        "item_id": rubric.items[0].item_id,
        "reason": "Test.",
        "protocol_ref": "Protocol 1.",
    }
    result = compose_active_checklist([], rubric, "EMT", overlay_ops=[suppress_op])
    json_mod.dumps(result.overlay_audit)  # must not raise


def test_compose_active_checklist_items_are_checklist_item_instances():
    """All items in the composed checklist must be ChecklistItem instances."""
    from app.checklist import ChecklistItem
    rubric = load_call_type_rubric("respiratory_distress", "training")
    assert rubric is not None
    result = compose_active_checklist([], rubric, "EMT")
    for item in result.items:
        assert isinstance(item, ChecklistItem), (
            f"Expected ChecklistItem, got {type(item)} for item '{getattr(item, 'id', '?')}'"
        )


def test_all_logic_items_have_allowed_tiers_1_only():
    """
    Items with requirement_logic='all' must have allowed_tiers=[1].
    A flat Tier 2 transcript regex cannot substitute for independent structured
    evidence per sub-requirement — false Tier 2 credit is the safety failure.
    """
    rubric = load_call_type_rubric("hypoglycemia", "training")
    assert rubric is not None
    result = compose_active_checklist([], rubric, "Paramedic")
    for item in result.items:
        if item.requirement_logic == "all":
            assert item.allowed_tiers == [1], (
                f"item '{item.id}' has requirement_logic='all' but allowed_tiers={item.allowed_tiers}; "
                f"must be [1] to prevent false Tier 2 credit from a broad transcript match"
            )


def test_all_logic_items_do_not_allow_tier2_across_all_call_types():
    """
    Cross-rubric check: no 'all' logic item from any known rubric may carry Tier 2
    in its effective allowed_tiers after active composition.
    """
    for call_type in ("respiratory_distress", "pediatric_croup", "hypoglycemia", "head_injury", "nremt_trauma"):
        rubric = load_call_type_rubric(call_type, "training")
        assert rubric is not None
        result = compose_active_checklist([], rubric, "EMT")
        for item in result.items:
            if item.requirement_logic == "all":
                assert 2 not in item.allowed_tiers, (
                    f"[{call_type}] item '{item.id}' has requirement_logic='all' "
                    f"and allowed_tiers contains 2 — Tier 2 would permit false "
                    f"credit from a broad transcript match"
                )


def test_tier1_matches_default_factory_is_independent_per_instance():
    """
    tier1_matches must use default_factory=list so instances don't share a default list.
    This is a Pydantic mutable-default safety check.
    """
    from app.checklist import ChecklistItem
    a = ChecklistItem(
        id="test_a", description="a", category="clinical_performance",
        subtype="assessment", point_value=1,
    )
    b = ChecklistItem(
        id="test_b", description="b", category="clinical_performance",
        subtype="assessment", point_value=1,
    )
    assert a.tier1_matches is not b.tier1_matches, (
        "tier1_matches default must be a separate list per instance (Field(default_factory=list))"
    )
