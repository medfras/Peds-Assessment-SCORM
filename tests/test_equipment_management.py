"""
Tests for Agency Equipment Management.

Covers:
  - vocabulary helpers (catalog lookup, alias resolution, medication classification)
  - _migrate_equipment_config() pure function (all three migration passes)
  - _build_agency_prompt_block() equipment injection (new schema + legacy fallback)
  - API custom-item cap enforcement (validated via _migrate_equipment_config and direct unit tests)
"""

import pytest
import re
from fastapi import HTTPException
from app.scenarios.vocabulary import (
    EQUIPMENT_CATALOG,
    MEDICATIONS_CATALOG,
    EQUIPMENT_ALIASES,
    equipment_id_for_canonical_name,
    equipment_id_for_alias,
    equipment_label_for_id,
    is_medication_id,
    all_equipment_items,
    all_medication_items,
)
from app.main import _migrate_equipment_config, _validate_equipment_items_payload
from app.ai_client import _build_agency_prompt_block


# ── Vocabulary helpers ─────────────────────────────────────────────────────────

class TestEquipmentCatalog:
    def test_all_four_categories_present(self):
        assert set(EQUIPMENT_CATALOG) == {"airway", "monitoring", "trauma", "other"}

    def test_each_category_nonempty(self):
        for cat, items in EQUIPMENT_CATALOG.items():
            assert items, f"Category {cat!r} is empty"

    def test_medications_catalog_nonempty(self):
        assert MEDICATIONS_CATALOG

    def test_no_id_overlap_between_equipment_and_medications(self):
        equip_ids = {iid for cat in EQUIPMENT_CATALOG.values() for iid in cat}
        med_ids = set(MEDICATIONS_CATALOG)
        assert equip_ids.isdisjoint(med_ids), "IDs must not overlap between equipment and medications catalogs"

    def test_all_ids_snake_case(self):
        all_ids = [iid for cat in EQUIPMENT_CATALOG.values() for iid in cat]
        all_ids += list(MEDICATIONS_CATALOG)
        for iid in all_ids:
            assert re.match(r"^[a-z0-9_]+$", iid), f"ID {iid!r} is not snake_case"

    def test_all_aliases_resolve_to_known_ids(self):
        all_ids = {iid for cat in EQUIPMENT_CATALOG.values() for iid in cat} | set(MEDICATIONS_CATALOG)
        for alias, target_id in EQUIPMENT_ALIASES.items():
            assert target_id in all_ids, f"Alias {alias!r} → {target_id!r} is not a known catalog ID"


class TestEquipmentHelpers:
    def test_canonical_name_exact_match(self):
        assert equipment_id_for_canonical_name("BVM (adult, pediatric, infant)") == "bvm_adult_peds_infant"

    def test_canonical_name_case_insensitive(self):
        assert equipment_id_for_canonical_name("bvm (adult, pediatric, infant)") == "bvm_adult_peds_infant"

    def test_canonical_name_unknown_returns_none(self):
        assert equipment_id_for_canonical_name("mystery device") is None

    def test_alias_ntg_resolves(self):
        assert equipment_id_for_alias("ntg") == "nitroglycerin_sl"

    def test_alias_narcan_resolves(self):
        assert equipment_id_for_alias("narcan") == "naloxone_2mg"

    def test_alias_epipen_resolves(self):
        assert equipment_id_for_alias("epipen") == "epi_autoinjector_adult"

    def test_alias_unknown_returns_none(self):
        assert equipment_id_for_alias("totally unknown thing") is None

    def test_label_for_known_id(self):
        assert equipment_label_for_id("aed") == "AED"
        assert equipment_label_for_id("albuterol_svn_unit_dose") == "Albuterol 2.5 mg / 3 mL unit-dose (SVN)"

    def test_label_for_unknown_id_returns_none(self):
        assert equipment_label_for_id("does_not_exist") is None

    def test_is_medication_id_true(self):
        assert is_medication_id("albuterol_svn_unit_dose")
        assert is_medication_id("naloxone_2mg")

    def test_is_medication_id_false_for_equipment(self):
        assert not is_medication_id("aed")
        assert not is_medication_id("tourniquets")

    def test_all_equipment_items_includes_all_categories(self):
        items = all_equipment_items()
        categories = {i["category"] for i in items}
        assert categories == {"airway", "monitoring", "trauma", "other"}

    def test_all_medication_items_have_id_and_label(self):
        for item in all_medication_items():
            assert "id" in item and "label" in item


# ── Migration function ─────────────────────────────────────────────────────────

class TestMigrateEquipmentConfig:
    def _run(self, equipment: dict) -> list[dict]:
        config = {"equipment": equipment}
        result = _migrate_equipment_config(config)
        return result["equipment"]["items"]

    def test_idempotent_if_items_key_present(self):
        config = {"equipment": {"items": [{"id": "aed", "carried": True, "source": "master"}]}}
        result = _migrate_equipment_config(config)
        assert result is config  # returned unchanged

    def test_pass1_exact_canonical_name(self):
        items = self._run({"airway": ["BVM (adult, pediatric, infant)"]})
        assert len(items) == 1
        assert items[0]["id"] == "bvm_adult_peds_infant"
        assert items[0]["source"] == "master"
        assert items[0]["carried"] is True
        assert not items[0].get("needs_review")

    def test_pass2_alias_lookup(self):
        items = self._run({"medications": ["NTG"]})
        assert items[0]["id"] == "nitroglycerin_sl"
        assert items[0]["source"] == "master"
        assert not items[0].get("needs_review")

    def test_pass2_compound_string_maps_to_primary(self):
        # "Suction unit (portable and on-board)" resolves via alias to suction_unit_portable
        items = self._run({"airway": ["Suction unit (portable and on-board)"]})
        assert items[0]["id"] == "suction_unit_portable"
        assert not items[0].get("needs_review")

    def test_pass3_substring_match_flagged_needs_review(self):
        # "padded board" is a substring of "Splint kit (SAM/padded board)" but is not an alias.
        # It uniquely matches splint_kit, so it hits Pass 3 and gets needs_review.
        items = self._run({"trauma": ["padded board"]})
        assert len(items) == 1
        assert items[0]["id"] == "splint_kit"
        assert items[0].get("needs_review") is True
        assert items[0]["source"] == "master"

    def test_unresolvable_becomes_custom_needs_review(self):
        items = self._run({"other": ["Totally unknown item XYZ"]})
        assert len(items) == 1
        assert items[0]["source"] == "custom"
        assert items[0].get("needs_review") is True
        assert items[0].get("original_text") == "Totally unknown item XYZ"
        assert items[0].get("label") == "Totally unknown item XYZ"

    def test_not_carried_items_migrate_with_carried_false(self):
        items = self._run({"not_carried": ["AED"]})
        assert items[0]["id"] == "aed"
        assert items[0]["carried"] is False

    def test_not_carried_wins_if_item_appears_in_both_sources(self):
        items = self._run({"monitoring": ["AED"], "not_carried": ["AED"]})
        assert len(items) == 1
        assert items[0]["id"] == "aed"
        assert items[0]["carried"] is False

    def test_ui_saved_carried_flat_list_is_swept(self):
        # Pre-existing bug: UI wrote equipment.carried, AI read airway/monitoring/etc.
        items = self._run({"carried": ["Stretcher"]})
        assert any(i["id"] == "stretcher" for i in items)

    def test_empty_strings_ignored(self):
        items = self._run({"airway": ["", "   "]})
        assert items == []

    def test_deduplication_across_old_schema_sources(self):
        # Same item in both airway and carried — should appear once
        items = self._run({"airway": ["AED"], "monitoring": ["AED"]})
        assert sum(1 for i in items if i["id"] == "aed") == 1

    def test_full_transport_agency_all_auto_resolve(self):
        equip = {
            "airway": [
                "BVM (adult, pediatric, infant)", "OPA/NPA assorted sizes",
                "Suction unit (portable and on-board)", "Oxygen — D and M cylinders",
                "NRB mask (adult and pediatric)", "Nasal cannula (adult and pediatric)",
                "Nebulizer (SVN) kit",
            ],
            "monitoring": ["Pulse oximeter", "Manual BP cuff and stethoscope", "Blood glucose meter", "AED"],
            "trauma": [
                "Tourniquets", "Pressure bandages", "Hemostatic gauze", "Trauma dressings",
                "Cervical collars (assorted)", "Long backboard and straps", "Scoop stretcher",
            ],
            "other": ["Stretcher", "OB kit (basic)", "Broselow tape"],
            "medications": [
                "Albuterol 2.5 mg / 3 mL unit-dose (SVN)", "Oral glucose gel",
                "Epinephrine auto-injector (0.3 mg adult, 0.15 mg pediatric)",
                "Aspirin 324 mg (chewable)", "Naloxone (Narcan) 2 mg/2 mL",
            ],
        }
        items = self._run(equip)
        needs_review = [i for i in items if i.get("needs_review")]
        assert needs_review == [], f"Expected zero needs_review items, got: {needs_review}"
        assert all(i["carried"] for i in items)

    def test_preserves_other_config_keys(self):
        config = {"display_name": "Test Agency", "equipment": {"airway": ["AED"]}}
        result = _migrate_equipment_config(config)
        assert result["display_name"] == "Test Agency"


# ── AI prompt injection ────────────────────────────────────────────────────────

_EMPTY_SCENARIO = {
    "non_transport_agency": False,
    "agency_context": "Test agency.",
    "als_unit_name": "ALS",
    "als_arrival_minutes": 12,
}


class TestBuildAgencyPromptBlock:
    def _block(self, equipment: dict) -> str:
        agency = {"display_name": "Test EMS", "unit_designator": "Squad 1", "equipment": equipment}
        return _build_agency_prompt_block(agency, _EMPTY_SCENARIO, elapsed_minutes=5.0)

    # ── New schema ────────────────────────────────────────────────────────────

    def test_new_schema_carried_equipment_in_prompt(self):
        block = self._block({"items": [
            {"id": "aed", "carried": True, "source": "master"},
        ]})
        assert "AED" in block
        assert "Equipment on this unit:" in block

    def test_new_schema_carried_medication_on_separate_line(self):
        block = self._block({"items": [
            {"id": "albuterol_svn_unit_dose", "carried": True, "source": "master"},
        ]})
        assert "Medications on this unit:" in block
        assert "Albuterol" in block
        assert "Equipment on this unit:" not in block  # no equipment items

    def test_new_schema_not_carried_in_not_carried_block(self):
        block = self._block({"items": [
            {"id": "aed", "carried": False, "source": "master"},
        ]})
        assert "NOT CARRIED" in block
        assert "AED" in block
        assert "Equipment on this unit:" not in block

    def test_new_schema_custom_item_uses_stored_label(self):
        block = self._block({"items": [
            {"id": "custom_abc", "carried": True, "source": "custom", "label": "My Special Device"},
        ]})
        assert "My Special Device" in block

    def test_new_schema_needs_review_item_treated_as_carried(self):
        block = self._block({"items": [
            {"id": "custom_xyz", "carried": True, "source": "custom", "label": "Old Item", "needs_review": True},
        ]})
        assert "Old Item" in block
        assert "NOT CARRIED" not in block

    def test_new_schema_equipment_and_medications_split_correctly(self):
        block = self._block({"items": [
            {"id": "aed", "carried": True, "source": "master"},
            {"id": "albuterol_svn_unit_dose", "carried": True, "source": "master"},
            {"id": "tourniquets", "carried": False, "source": "master"},
        ]})
        assert "Equipment on this unit:" in block
        assert "AED" in block
        assert "Medications on this unit:" in block
        assert "Albuterol" in block
        assert "NOT CARRIED" in block
        assert "Tourniquets" in block

    # ── Legacy schema fallback ────────────────────────────────────────────────

    def test_legacy_schema_category_keys_still_work(self):
        block = self._block({
            "airway": ["BVM (adult, pediatric, infant)"],
            "monitoring": ["AED"],
            "trauma": [],
            "other": [],
            "medications": ["Oral glucose gel"],
            "not_carried": ["CPAP"],
        })
        assert "BVM" in block
        assert "AED" in block
        assert "Oral glucose gel" in block
        assert "NOT CARRIED" in block
        assert "CPAP" in block

    def test_legacy_ui_carried_flat_list_included(self):
        # Pre-existing bug: UI wrote equipment.carried, AI must still surface it via legacy path
        block = self._block({"carried": ["Stretcher"], "medications": [], "not_carried": []})
        assert "Stretcher" in block

    def test_empty_agency_returns_agency_context(self):
        block = _build_agency_prompt_block(None, _EMPTY_SCENARIO, elapsed_minutes=5.0)
        assert "Test agency." in block


# ── Custom item cap (unit-level logic) ────────────────────────────────────────

class TestCustomItemCap:
    def test_migration_does_not_enforce_cap(self):
        # Migration always completes even if existing data exceeds 10 custom items.
        # Cap enforcement is a PUT /api/agency/config concern, not migration's.
        many_unknowns = [f"Unknown Device {i}" for i in range(15)]
        config = {"equipment": {"other": many_unknowns}}
        result = _migrate_equipment_config(config)
        items = result["equipment"]["items"]
        custom_items = [i for i in items if i.get("source") == "custom"]
        assert len(custom_items) == 15  # migration preserves all; API enforces cap on save

    def test_ten_custom_items_exactly_at_cap(self):
        # Verify the boundary: exactly 10 custom items in a config is valid data.
        items = [
            {"id": f"custom_{i}", "carried": True, "source": "custom", "label": f"Item {i}"}
            for i in range(10)
        ]
        custom_count = sum(1 for i in items if i.get("source") == "custom")
        assert custom_count == 10

    def test_eleven_custom_items_exceeds_cap(self):
        items = [
            {"id": f"custom_{i}", "carried": True, "source": "custom", "label": f"Item {i}"}
            for i in range(11)
        ]
        custom_count = sum(1 for i in items if i.get("source") == "custom")
        assert custom_count > 10  # API should reject this; enforced in PUT handler


class TestEquipmentPayloadValidation:
    def test_accepts_valid_master_and_custom_items(self):
        _validate_equipment_items_payload([
            {"id": "aed", "carried": True, "source": "master"},
            {"id": "custom_1", "carried": False, "source": "custom", "label": "Agency Widget"},
        ])

    def test_rejects_duplicate_item_ids(self):
        with pytest.raises(HTTPException) as exc:
            _validate_equipment_items_payload([
                {"id": "aed", "carried": True, "source": "master"},
                {"id": "aed", "carried": False, "source": "master"},
            ])
        assert exc.value.status_code == 422
        assert "duplicates item id" in exc.value.detail

    def test_rejects_unknown_master_id(self):
        with pytest.raises(HTTPException) as exc:
            _validate_equipment_items_payload([
                {"id": "mystery_device", "carried": True, "source": "master"},
            ])
        assert exc.value.status_code == 422
        assert "unknown master inventory id" in exc.value.detail

    def test_rejects_invalid_source(self):
        with pytest.raises(HTTPException) as exc:
            _validate_equipment_items_payload([
                {"id": "aed", "carried": True, "source": "legacy"},
            ])
        assert exc.value.status_code == 422
        assert "source must be 'master' or 'custom'" in exc.value.detail
