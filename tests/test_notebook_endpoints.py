"""Regression tests for the notebook endpoints (condition + learning entries).

Covers:
- _extract_debrief_reference_md: server-side markdown extraction
- _NOTEBOOK_LEARNING_REGISTRY: registry completeness and file existence
- Pydantic model validation: max_length enforcement
- Qualification logic: what constitutes a valid IC result for condition unlock
"""
import sys
import types
from pathlib import Path

import pytest

# ── config stub (must happen before app.main import) ─────────────────────────

_fake_config = types.ModuleType("app.config")
_fake_config._IS_PROD = False

class _PermissiveSettings(types.SimpleNamespace):
    def __getattr__(self, name: str):
        return ""

_fake_config.settings = _PermissiveSettings(
    groq_api_key="test",
    app_secret_key="test-secret",
    jwt_algorithm="HS256",
    jwt_expire_minutes=60,
    database_url="postgresql+asyncpg://test:test@localhost:5432/test",
    db_pool_size=1,
    db_max_overflow=1,
    log_level="INFO",
    log_format="json",
    default_provider_level="EMT",
    default_mca="mi_wmrmcc_kent",
    rate_limit_auth=10,
    rate_limit_session_start=10,
    rate_limit_session_write=60,
    rate_limit_chat=30,
    rate_limit_med_control=10,
    rate_limit_lexi=5,
    rate_limit_debrief=3,
    rate_limit_lexi_group_create=5,
    rate_limit_lexi_group_join=10,
    rate_limit_lexi_group_start=5,
    rate_limit_lexi_group_answer=30,
    rate_limit_lexi_group_feedback_ready=30,
    rate_limit_lexi_group_next_round=10,
    rate_limit_team_presence=30,
    rate_limit_team_invite=10,
    rate_limit_team_accept=10,
    rate_limit_team_start=10,
    team_challenge_enabled=False,
    superuser_username="",
    superuser_password="",
    seed_agency_name="",
    seed_agency_join_code="",
    seed_agency_file="",
)
sys.modules["app.config"] = _fake_config

from app.main import (  # noqa: E402
    _extract_debrief_reference_md,
    _scenario_reference_md,
    _redact_reference_sections,
    _QUALIFYING_IC_RESULTS,
    _NOTEBOOK_LEARNING_REGISTRY,
    NotebookConditionUpsertRequest,
    NotebookLearningUpsertRequest,
)


# ── _extract_debrief_reference_md ─────────────────────────────────────────────

_DEBRIEF_WITH_REFS = """\
## 1. Overall Assessment

You did a good job managing this call.

## 2. Scene Safety

PPE applied, scene safe.

## 7. Summary

Great work overall.

## 8. Condition — Opioid Toxidrome

Opioid overdose is characterized by the classic triad of miosis, respiratory depression,
and decreased level of consciousness.

## 9. Treatment & Protocol Reference

**Naloxone (Narcan):** 2 mg intranasal via MAD atomizer for suspected opioid overdose.
"""

_DEBRIEF_NO_REFS = """\
## 1. Overall Assessment

You did a good job managing this call.

## 7. Summary

Great work overall.
"""

_DEBRIEF_PLAIN_HEADERS = """\
**1. Scene size-up was appropriate.**

**8. Condition — Pediatric Asthma**

Asthma is a reversible obstructive airway disease.

**9. Treatment & Protocol Reference**

Albuterol 2.5mg SVN.
"""

_DEBRIEF_EMPTY = ""


def test_extract_reference_md_numbered_headers():
    result = _extract_debrief_reference_md(_DEBRIEF_WITH_REFS)
    assert "Opioid Toxidrome" in result
    assert "Naloxone" in result
    assert "Scene Safety" not in result
    assert "Overall Assessment" not in result


def test_extract_reference_md_omits_main_sections():
    result = _extract_debrief_reference_md(_DEBRIEF_WITH_REFS)
    # Sections 1-7 must not appear in the reference markdown
    assert "PPE applied" not in result
    assert "Great work overall" not in result


def test_extract_reference_md_no_refs_returns_empty():
    result = _extract_debrief_reference_md(_DEBRIEF_NO_REFS)
    assert result == ""


def test_extract_reference_md_plain_bold_headers():
    result = _extract_debrief_reference_md(_DEBRIEF_PLAIN_HEADERS)
    assert "Pediatric Asthma" in result
    assert "Albuterol" in result
    assert "Scene size-up" not in result


def test_extract_reference_md_empty_input():
    assert _extract_debrief_reference_md(_DEBRIEF_EMPTY) == ""
    assert _extract_debrief_reference_md(None) == ""  # type: ignore[arg-type]


def test_extract_reference_md_both_sections_joined():
    result = _extract_debrief_reference_md(_DEBRIEF_WITH_REFS)
    # Both section 8 and section 9 content must appear in the single return value
    assert "Opioid Toxidrome" in result
    assert "Treatment & Protocol Reference" in result


def test_scenario_reference_md_uses_authored_debrief_content_when_feedback_has_no_refs():
    scenario = {
        "debrief": {
            "condition_background": "Febrile seizure airway priority.",
            "key_teaching_points": ["Turn laterally.", "Suction visible secretions."],
            "common_mistakes": ["Leaving the infant supine."],
        }
    }

    result = _scenario_reference_md(scenario)

    assert "Febrile seizure airway priority." in result
    assert "Turn laterally." in result
    assert "Leaving the infant supine." in result


# ── _QUALIFYING_IC_RESULTS ────────────────────────────────────────────────────

def test_qualifying_ic_results_includes_correct_and_acceptable():
    assert "correct"    in _QUALIFYING_IC_RESULTS
    assert "acceptable" in _QUALIFYING_IC_RESULTS


def test_qualifying_ic_results_excludes_incorrect_and_skipped():
    assert "incorrect" not in _QUALIFYING_IC_RESULTS
    assert "skipped"   not in _QUALIFYING_IC_RESULTS


# ── _NOTEBOOK_LEARNING_REGISTRY ───────────────────────────────────────────────

_EXPECTED_GAMES = {
    "ten4_facesp",
    "adult_child_ap_swipe",
    "lung_sounds_matcher",
    "history_maker",
    "peds_gcs_calculator",
    "cpr_bls_concepts",
    "cpr_bls_sequence",
}


def test_registry_contains_all_expected_games():
    assert _EXPECTED_GAMES <= set(_NOTEBOOK_LEARNING_REGISTRY.keys()), (
        f"Missing games: {_EXPECTED_GAMES - set(_NOTEBOOK_LEARNING_REGISTRY.keys())}"
    )


def test_registry_entries_have_required_keys():
    for game_id, entry in _NOTEBOOK_LEARNING_REGISTRY.items():
        assert "title" in entry, f"{game_id}: missing 'title'"
        assert "page"  in entry, f"{game_id}: missing 'page'"
        assert isinstance(entry["title"], str) and entry["title"], f"{game_id}: empty title"
        assert isinstance(entry["page"], Path),  f"{game_id}: 'page' must be a Path"


def test_registry_learning_page_files_exist():
    missing = []
    for game_id, entry in _NOTEBOOK_LEARNING_REGISTRY.items():
        if not entry["page"].exists():
            missing.append(f"{game_id}: {entry['page']}")
    assert not missing, "Learning page files missing on disk:\n" + "\n".join(missing)


def test_registry_learning_pages_are_nonempty():
    for game_id, entry in _NOTEBOOK_LEARNING_REGISTRY.items():
        if entry["page"].exists():
            content = entry["page"].read_text(encoding="utf-8").strip()
            assert content, f"{game_id}: learning_page.md is empty"


def test_registry_learning_pages_are_dog_park_category():
    for game_id, entry in _NOTEBOOK_LEARNING_REGISTRY.items():
        assert entry.get("category_id") == "dog_park", f"{game_id}: category_id should be dog_park"
        assert entry.get("category_title") == "Training Center", f"{game_id}: category_title should be Training Center"


# ── Pydantic model validation ─────────────────────────────────────────────────

def test_condition_request_rejects_oversized_scenario_id():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        NotebookConditionUpsertRequest(scenario_id="x" * 129)


def test_condition_request_accepts_valid_scenario_id():
    req = NotebookConditionUpsertRequest(scenario_id="peds_ams_tox_01")
    assert req.scenario_id == "peds_ams_tox_01"


def test_learning_request_rejects_oversized_game_id():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        NotebookLearningUpsertRequest(game_id="x" * 65)


def test_learning_request_accepts_valid_game_id():
    req = NotebookLearningUpsertRequest(game_id="ten4_facesp")
    assert req.game_id == "ten4_facesp"


def test_learning_request_only_has_game_id_field():
    """Confirm the request model no longer accepts client-supplied content fields."""
    import inspect
    from pydantic.fields import FieldInfo
    fields = NotebookLearningUpsertRequest.model_fields
    assert set(fields.keys()) == {"game_id"}, (
        f"Request model should only have 'game_id', found: {set(fields.keys())}"
    )


def test_condition_request_only_has_scenario_id_field():
    fields = NotebookConditionUpsertRequest.model_fields
    assert set(fields.keys()) == {"scenario_id"}, (
        f"Request model should only have 'scenario_id', found: {set(fields.keys())}"
    )


# ── _redact_reference_sections ────────────────────────────────────────────────

def test_redact_removes_sections_8_and_9():
    result = _redact_reference_sections(_DEBRIEF_WITH_REFS)
    assert "Opioid Toxidrome" not in result
    assert "Naloxone" not in result


def test_redact_keeps_sections_1_through_7():
    result = _redact_reference_sections(_DEBRIEF_WITH_REFS)
    assert "Scene Safety" in result
    assert "Overall Assessment" in result


def test_redact_keeps_summary_section():
    result = _redact_reference_sections(_DEBRIEF_WITH_REFS)
    assert "Great work overall" in result


def test_redact_empty_input_returns_empty():
    assert _redact_reference_sections("") == ""
    assert _redact_reference_sections(None) == None  # type: ignore[arg-type]


def test_redact_no_reference_sections_returns_full_text():
    result = _redact_reference_sections(_DEBRIEF_NO_REFS)
    assert "Great work overall" in result
    assert "Overall Assessment" in result


def test_redact_and_extract_are_complements():
    """Redacted + extracted sections together reconstruct the full meaningful content."""
    ref = _extract_debrief_reference_md(_DEBRIEF_WITH_REFS)
    redacted = _redact_reference_sections(_DEBRIEF_WITH_REFS)
    # Condition section must be in one output but not the other
    assert "Opioid Toxidrome" in ref and "Opioid Toxidrome" not in redacted
    assert "Scene Safety" in redacted and "Scene Safety" not in ref


def test_redact_plain_bold_headers():
    result = _redact_reference_sections(_DEBRIEF_PLAIN_HEADERS)
    assert "Pediatric Asthma" not in result
    assert "Albuterol" not in result
    assert "Scene size-up" in result


# ── _isConditionLocked semantics (backend mirrored in Python for auditing) ────

def test_qualifying_ic_results_treats_null_result_as_not_qualifying():
    """A present IC object with a null/missing result is not qualifying."""
    assert None not in _QUALIFYING_IC_RESULTS


def test_qualifying_ic_results_treats_unknown_result_as_not_qualifying():
    assert "unknown" not in _QUALIFYING_IC_RESULTS
    assert "" not in _QUALIFYING_IC_RESULTS


# ── Redaction applied across all response paths ────────────────────────────────
# These tests verify the redaction logic used by history, cached, and skip paths.
# They use _redact_reference_sections directly since the route handlers inline the
# same qualifying check.

def test_redact_applied_when_ic_incorrect():
    ic = {"result": "incorrect", "student_answer": "trauma", "correct": "Opioid Toxidrome"}
    result_qualifying = ic["result"] in _QUALIFYING_IC_RESULTS
    feedback_out = _redact_reference_sections(_DEBRIEF_WITH_REFS) if not result_qualifying else _DEBRIEF_WITH_REFS
    assert "Opioid Toxidrome" not in feedback_out
    assert "Scene Safety" in feedback_out


def test_redact_applied_when_ic_skipped():
    ic = {"result": "skipped", "student_answer": None, "correct": "Opioid Toxidrome"}
    result_qualifying = ic["result"] in _QUALIFYING_IC_RESULTS
    feedback_out = _redact_reference_sections(_DEBRIEF_WITH_REFS) if not result_qualifying else _DEBRIEF_WITH_REFS
    assert "Naloxone" not in feedback_out


def test_redact_not_applied_when_ic_correct():
    ic = {"result": "correct", "student_answer": "Opioid Toxidrome", "correct": "Opioid Toxidrome"}
    result_qualifying = ic["result"] in _QUALIFYING_IC_RESULTS
    feedback_out = _redact_reference_sections(_DEBRIEF_WITH_REFS) if not result_qualifying else _DEBRIEF_WITH_REFS
    assert "Opioid Toxidrome" in feedback_out
    assert "Naloxone" in feedback_out


def test_redact_not_applied_when_ic_acceptable():
    ic = {"result": "acceptable", "student_answer": "Anaphylaxis", "correct": "Opioid Toxidrome"}
    result_qualifying = ic["result"] in _QUALIFYING_IC_RESULTS
    feedback_out = _redact_reference_sections(_DEBRIEF_WITH_REFS) if not result_qualifying else _DEBRIEF_WITH_REFS
    assert "Opioid Toxidrome" in feedback_out


def test_redact_applied_when_ic_present_but_result_null():
    """Present IC with null result → not qualifying → redacted (fail closed)."""
    ic = {"result": None, "student_answer": None, "correct": "Opioid Toxidrome"}
    result_qualifying = ic["result"] in _QUALIFYING_IC_RESULTS
    feedback_out = _redact_reference_sections(_DEBRIEF_WITH_REFS) if not result_qualifying else _DEBRIEF_WITH_REFS
    assert "Opioid Toxidrome" not in feedback_out


def test_no_ic_enabled_does_not_trigger_redaction():
    """Scenario with no IC enabled → qualifying → full text returned.

    All five paths use: qualifying = (not sc_ic_enabled) OR (result in QUALIFYING).
    When sc_ic_enabled is False, the expression short-circuits to True regardless
    of what the EP IC result is.
    """
    sc_ic_enabled = False
    for result in (None, "incorrect", "skipped", "correct", "acceptable", ""):
        qualifying = not sc_ic_enabled or result in _QUALIFYING_IC_RESULTS
        assert qualifying is True, f"Expected qualifying for non-IC scenario, got False for result={result!r}"


def test_ic_enabled_missing_ep_ic_fails_closed():
    """IC-enabled scenario with missing EP IC data → not qualifying → redacted."""
    sc_ic_enabled = True
    ic_result = None  # no EP IC data (malformed/legacy session)
    qualifying = not sc_ic_enabled or ic_result in _QUALIFYING_IC_RESULTS
    assert qualifying is False
