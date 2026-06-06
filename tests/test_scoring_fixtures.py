"""Calibration fixtures for the scoring evidence packet.

Each fixture in tests/fixtures/scoring/*.json declares:
  inputs               — session state fed to _build_evidence_packet
  target_expected      — what clinical behavior should be (encode truth, not code)
  known_failing_baselines — assertions currently failing; documented gaps awaiting
                           Group A/B/C fixes

Test outcomes
─────────────
  PASS    assertion passes against current code
  XFAIL   assertion_id is in known_failing_baselines; current code diverges from
          clinical expectation but the gap is documented and expected
  FAIL    unexpected failure — may be a regression or an undocumented gap that
          needs a known_failing_baselines entry

IMPORTANT: never change target_expected to match the current code.
  Encode clinical truth.  When code diverges, add a known_failing_baselines entry
  that explains the current behavior, the target, and which fix group closes it.

When a known_failing_baselines entry unexpectedly PASSES the test will FAIL with
a clear message: remove the stale baseline entry (the fix was applied).
"""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest

# ── Stub app.config before any app imports ────────────────────────────────────
_fake_config = types.ModuleType("app.config")
_fake_config.settings = types.SimpleNamespace(
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
    groq_lexi_model="llama-3.1-8b-instant",
)
sys.modules["app.config"] = _fake_config

from app.ai_client import _build_evidence_packet  # noqa: E402

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "scoring"


# ── Object constructors ───────────────────────────────────────────────────────

def _make_intervention(name: str, applied_at_iso: str | None = None):
    applied_at = datetime.fromisoformat(applied_at_iso) if applied_at_iso else None
    return types.SimpleNamespace(name=name, applied_at=applied_at)


def _make_finding(
    key: str,
    value: str,
    finding_type: str = "vital",
    captured_at_iso: str | None = None,
):
    captured_at = datetime.fromisoformat(captured_at_iso) if captured_at_iso else None
    return types.SimpleNamespace(
        key=key, value=value, finding_type=finding_type, captured_at=captured_at
    )


def _make_message(content: str):
    return types.SimpleNamespace(content=content)


def _make_session_event(
    event_type: str,
    event_key: str,
    source: str = "backend_auto",
    occurred_at_iso: str | None = None,
):
    occurred_at = (
        datetime.fromisoformat(occurred_at_iso)
        if occurred_at_iso
        else datetime(2026, 1, 1, 12, 0, 0)
    )
    return types.SimpleNamespace(
        event_type=event_type,
        event_key=event_key,
        source=source,
        occurred_at=occurred_at,
    )


# ── Fixture loader ────────────────────────────────────────────────────────────

def _load_fixtures() -> list[dict]:
    if not FIXTURES_DIR.exists():
        return []
    fixtures = []
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        with open(path) as f:
            fixtures.append(json.load(f))
    return fixtures


# ── Build evidence packet from fixture inputs ─────────────────────────────────

def _build_from_inputs(inputs: dict) -> dict:
    interventions = [
        _make_intervention(iv["name"], iv.get("applied_at"))
        for iv in (inputs.get("interventions") or [])
    ]
    session = types.SimpleNamespace(
        interventions=interventions,
        checklist_states=inputs.get("checklist_states") or {},
        ended_at=inputs.get("session_ended_at"),
    )
    findings = [
        _make_finding(
            f["key"],
            f["value"],
            f.get("finding_type", "vital"),
            f.get("captured_at"),
        )
        for f in (inputs.get("findings") or [])
    ]
    student_messages = [_make_message(m) for m in (inputs.get("student_messages") or [])]
    session_events = [
        _make_session_event(
            ev["event_type"],
            ev["event_key"],
            ev.get("source", "backend_auto"),
            ev.get("occurred_at"),
        )
        for ev in (inputs.get("session_events") or [])
    ] or None

    return _build_evidence_packet(
        inputs["scenario"],
        session,
        inputs.get("submitted_docs") or {},
        findings,
        elapsed_min=inputs.get("elapsed_min", 10.0),
        effective_level=inputs.get("effective_level", "EMT"),
        agency=inputs.get("agency") or {"transports_patients": True},
        student_messages=student_messages,
        scene_entry_scoring_result=inputs.get("scene_entry_scoring_result"),
        greeting_detected=inputs.get("greeting_detected", False),
        greeting_text=inputs.get("greeting_text", ""),
        prepass_result=inputs.get("prepass_result"),
        critical_actions=inputs.get("critical_actions"),
        grace_items=inputs.get("grace_items"),
        scene_entry_dict=inputs.get("scene_entry_dict"),
        session_events=session_events,
    )


# ── Assertion evaluator ───────────────────────────────────────────────────────

def _check_assertion(assertion: dict, packet: dict) -> tuple[bool, str]:
    """Evaluate one assertion against the evidence packet.

    Returns (passed: bool, detail: str).
    """
    atype = assertion["type"]

    if atype == "no_evaluate_tags":
        actions = packet.get("critical_actions_classified", {}).get("actions", [])
        bad = [a.get("description", "?") for a in actions if a.get("tag") == "EVALUATE"]
        if bad:
            return False, f"EVALUATE tags present for: {bad}"
        return True, "No EVALUATE tags"

    elif atype == "no_likely_missed_tags":
        actions = packet.get("critical_actions_classified", {}).get("actions", [])
        bad = [a.get("description", "?") for a in actions if a.get("tag") == "LIKELY_MISSED"]
        if bad:
            return False, f"LIKELY_MISSED tags present for: {bad}"
        return True, "No LIKELY_MISSED tags"

    elif atype == "critical_action_tag":
        desc_fragment = assertion["description_contains"].lower()
        expected_tag = assertion["expected_tag"]
        actions = packet.get("critical_actions_classified", {}).get("actions", [])
        matching = [a for a in actions if desc_fragment in a.get("description", "").lower()]
        if not matching:
            return False, f"No action with description containing {desc_fragment!r}"
        actual_tag = matching[0].get("tag")
        if actual_tag != expected_tag:
            return False, (
                f"Action {desc_fragment!r}: tag={actual_tag!r}, expected={expected_tag!r}"
            )
        return True, f"Action {desc_fragment!r}: tag={actual_tag!r} ✓"

    elif atype == "universal_base_present":
        element = assertion["element"]
        present = packet.get("universal_base", {}).get("present", [])
        if element not in present:
            return False, f"{element!r} not in universal_base.present (present={present})"
        return True, f"{element!r} in universal_base.present ✓"

    elif atype == "universal_base_gap":
        element = assertion["element"]
        gap_ids = [g["element"] for g in packet.get("universal_base", {}).get("gaps", [])]
        if element not in gap_ids:
            return False, f"{element!r} not in universal_base.gaps (gaps={gap_ids})"
        return True, f"{element!r} in universal_base.gaps ✓"

    elif atype == "corroboration_tier":
        expected = assertion["expected"]
        actual = packet.get("corroboration", {}).get("tier")
        if actual != expected:
            return False, f"corroboration.tier={actual!r}, expected={expected!r}"
        return True, f"corroboration.tier={actual!r} ✓"

    elif atype == "no_dmist_ceiling":
        ceilings = packet.get("ceilings", {})
        if "dmist" in ceilings:
            return False, f"Unexpected DMIST ceiling: {ceilings.get('dmist')}"
        return True, "No DMIST ceiling ✓"

    elif atype == "no_narrative_ceiling":
        ceilings = packet.get("ceilings", {})
        if "narrative" in ceilings:
            return False, f"Unexpected narrative ceiling: {ceilings.get('narrative')}"
        return True, "No narrative ceiling ✓"

    elif atype == "dmist_ceiling_enforced":
        ceilings = packet.get("ceilings", {})
        if ceilings.get("dmist") != 0 or not ceilings.get("dmist_enforce"):
            return False, (
                f"DMIST ceiling not enforced "
                f"(dmist={ceilings.get('dmist')}, enforce={ceilings.get('dmist_enforce')})"
            )
        return True, "DMIST ceiling enforced at 0 ✓"

    elif atype == "narrative_ceiling_enforced":
        ceilings = packet.get("ceilings", {})
        if ceilings.get("narrative") != 0 or not ceilings.get("narrative_enforce"):
            return False, (
                f"Narrative ceiling not enforced "
                f"(narrative={ceilings.get('narrative')}, "
                f"enforce={ceilings.get('narrative_enforce')})"
            )
        return True, "Narrative ceiling enforced at 0 ✓"

    elif atype == "dmist_ceiling_value":
        expected = assertion["expected"]
        actual = packet.get("ceilings", {}).get("dmist")
        if actual != expected:
            return False, f"DMIST ceiling={actual!r}, expected={expected!r}"
        return True, f"DMIST ceiling={actual!r} ✓"

    elif atype == "narrative_ceiling_value":
        expected = assertion["expected"]
        actual = packet.get("ceilings", {}).get("narrative")
        if actual != expected:
            return False, f"Narrative ceiling={actual!r}, expected={expected!r}"
        return True, f"Narrative ceiling={actual!r} ✓"

    elif atype == "greeting_detected":
        expected = assertion["expected"]
        actual = packet.get("professionalism", {}).get("greeting_detected")
        if actual != expected:
            return False, f"greeting_detected={actual!r}, expected={expected!r}"
        return True, f"greeting_detected={actual!r} ✓"

    elif atype == "dmist_unsupported_claims_min":
        min_count = assertion["min_count"]
        actual = len(packet.get("corroboration", {}).get("dmist_unsupported_claims", []))
        if actual < min_count:
            return False, f"dmist_unsupported_claims={actual}, expected>={min_count}"
        return True, f"dmist_unsupported_claims={actual} ✓"

    elif atype == "narrative_unsupported_claims_min":
        min_count = assertion["min_count"]
        actual = len(packet.get("corroboration", {}).get("narrative_unsupported_claims", []))
        if actual < min_count:
            return False, f"narrative_unsupported_claims={actual}, expected>={min_count}"
        return True, f"narrative_unsupported_claims={actual} ✓"

    else:
        return False, f"Unknown assertion type: {atype!r}"


# ── Test parametrization ──────────────────────────────────────────────────────

def _collect_test_cases() -> list[tuple]:
    """Yield (fixture_id, assertion, known_failing_entry | None, inputs) tuples."""
    cases = []
    for fixture in _load_fixtures():
        fixture_id = fixture["fixture_id"]
        known_failing: dict[str, dict] = {
            kb["assertion_id"]: kb
            for kb in (fixture.get("known_failing_baselines") or [])
        }
        inputs = fixture["inputs"]
        for assertion in fixture.get("target_expected", {}).get("assertions", []):
            aid = assertion["id"]
            cases.append((fixture_id, assertion, known_failing.get(aid), inputs))
    return cases


_TEST_CASES = _collect_test_cases()

# Pytest skips parametrize when the list is empty, but we want an explicit guard.
if not _TEST_CASES:
    pytest.skip(
        "No scoring fixtures found in tests/fixtures/scoring/ — "
        "create fixture JSON files to enable these tests.",
        allow_module_level=True,
    )


@pytest.mark.parametrize(
    "fixture_id,assertion,known_failing,inputs",
    _TEST_CASES,
    ids=[f"{c[0]}/{c[1]['id']}" for c in _TEST_CASES],
)
def test_scoring_fixture(fixture_id, assertion, known_failing, inputs):
    """Run one assertion from a calibration fixture.

    PASS    — clinical expectation met by current code.
    XFAIL   — assertion_id in known_failing_baselines; documented gap, not regression.
    FAIL    — unexpected: either a regression (no baseline entry) or the fix was
              applied but the baseline entry was not removed (stale entry).
    """
    packet = _build_from_inputs(inputs)
    passed, detail = _check_assertion(assertion, packet)

    if known_failing:
        if passed:
            # The fix was applied but the baseline entry was not removed.
            pytest.fail(
                f"[STALE BASELINE] {fixture_id}/{assertion['id']} is in "
                f"known_failing_baselines but the assertion now PASSES.\n"
                f"Remove it from known_failing_baselines and update the fixture.\n"
                f"Detail: {detail}"
            )
        else:
            pytest.xfail(
                f"[KNOWN GAP] current: {known_failing.get('current_behavior', '?')} | "
                f"target: {known_failing.get('target_behavior', '?')} | "
                f"fix: {known_failing.get('fixed_by', '?')}"
            )
    else:
        if not passed:
            pytest.fail(
                f"[UNEXPECTED FAILURE] {fixture_id}/{assertion['id']}\n"
                f"{detail}\n"
                f"If this is known current behavior diverging from clinical truth, "
                f"add it to known_failing_baselines with current_behavior, "
                f"target_behavior, and fixed_by."
            )
