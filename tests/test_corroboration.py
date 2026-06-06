"""Tests for C2 — app/corroboration.check_documentation_claims() contract.

These are the C1 gate fixtures: they pin the deterministic corroboration
interface and policy before any C2 implementation is written.

The module is skipped entirely if app.corroboration does not yet exist, so
the existing suite stays green while C2 is pending. Once C2 lands, all tests
here must pass before shadow mode (C3) can begin.

Coverage:
  Fixture 11 — Legitimate paraphrase not flagged
  Fixture 12 — Vital never assessed → vital_not_assessed; SpO2 passive exemption
  Fixture 13 — Demographic contradiction → demographic_mismatch
  Fixture 14 — All claims supported → zero flags
  Fixture 15 — Empty DMIST → zero flags, available=True
"""
from __future__ import annotations

import pytest

corroboration = pytest.importorskip(
    "app.corroboration",
    reason="C2 not yet implemented — skipping corroboration contract tests",
)

check_documentation_claims = corroboration.check_documentation_claims
CorroborationResult = corroboration.CorroborationResult
UnsupportedClaim = corroboration.UnsupportedClaim
canonicalize_vital_key = corroboration.canonicalize_vital_key


# ── Shared patient stub ───────────────────────────────────────────────────────

_PATIENT_8YO_MALE = {"age": 8, "sex": "male", "weight_kg": 25}


# ── Fixture 11: legitimate paraphrase — must not be flagged ──────────────────

def test_breathing_treatment_paraphrase_not_flagged():
    """'breathing treatment' is a legitimate paraphrase of albuterol SVN — no flag."""
    result = check_documentation_claims(
        dmist_text="I: Breathing treatment via nebulizer. Applied high-flow O2 via NRB.",
        narrative_text="",
        applied_intervention_ids=["albuterol_svn", "o2_nrb"],
        assessed_vital_types={"spo2", "hr"},
        patient=_PATIENT_8YO_MALE,
    )
    assert isinstance(result, CorroborationResult)
    assert result.available is True
    assert result.dmist_unsupported == [], (
        f"Expected no flags; got: {result.dmist_unsupported}"
    )
    assert result.narrative_unsupported == []


def test_nrb_paraphrase_not_flagged():
    """'non-rebreather' is an accepted paraphrase of o2_nrb — no flag."""
    result = check_documentation_claims(
        dmist_text="I: Supplemental oxygen via non-rebreather mask. Albuterol given.",
        narrative_text="",
        applied_intervention_ids=["albuterol_svn", "o2_nrb"],
        assessed_vital_types={"spo2"},
        patient=_PATIENT_8YO_MALE,
    )
    assert result.dmist_unsupported == []


# ── Fixture 12: vital never assessed → vital_not_assessed; SpO2 exempted ─────

def test_unassessed_hr_flagged_as_vital_not_assessed():
    """HR claimed in DMIST but never assessed (not in assessed_vital_types) → flagged."""
    result = check_documentation_claims(
        dmist_text="S: HR 96, SpO2 94%",
        narrative_text="",
        applied_intervention_ids=["o2_nrb"],
        assessed_vital_types={"spo2"},  # HR was not assessed
        patient=_PATIENT_8YO_MALE,
    )
    assert result.available is True
    hr_flags = [
        c for c in result.dmist_unsupported
        if c.claim_type == "vital_not_assessed"
    ]
    assert len(hr_flags) >= 1, (
        "Expected at least one vital_not_assessed flag for HR; "
        f"got dmist_unsupported={result.dmist_unsupported}"
    )


def test_spo2_not_flagged_when_passively_monitored():
    """SpO2 is passively monitored — must not be flagged even without a SessionFinding."""
    result = check_documentation_claims(
        dmist_text="S: SpO2 94%, HR 96",
        narrative_text="",
        applied_intervention_ids=["o2_nrb"],
        assessed_vital_types=set(),  # student assessed nothing explicitly
        patient=_PATIENT_8YO_MALE,
    )
    spo2_flags = [
        c for c in result.dmist_unsupported
        if "spo2" in c.claim.lower() or "94" in c.claim
    ]
    assert spo2_flags == [], (
        f"SpO2 must not be flagged (passive monitoring exemption); got: {spo2_flags}"
    )


# ── Fixture 13: demographic contradiction → demographic_mismatch ─────────────

def test_wrong_age_in_dmist_flagged():
    """DMIST states age that contradicts patient record → demographic_mismatch."""
    result = check_documentation_claims(
        dmist_text="D: 6-year-old male, 25 kg.",
        narrative_text="",
        applied_intervention_ids=[],
        assessed_vital_types=set(),
        patient=_PATIENT_8YO_MALE,  # age 8
    )
    assert result.available is True
    demo_flags = [
        c for c in result.dmist_unsupported
        if c.claim_type == "demographic_mismatch"
    ]
    assert len(demo_flags) >= 1, (
        f"Expected demographic_mismatch for wrong age; got: {result.dmist_unsupported}"
    )


def test_wrong_sex_in_dmist_flagged():
    """DMIST states sex that contradicts patient record → demographic_mismatch."""
    result = check_documentation_claims(
        dmist_text="D: 8-year-old female.",
        narrative_text="",
        applied_intervention_ids=[],
        assessed_vital_types=set(),
        patient=_PATIENT_8YO_MALE,  # sex: male
    )
    demo_flags = [
        c for c in result.dmist_unsupported
        if c.claim_type == "demographic_mismatch"
    ]
    assert len(demo_flags) >= 1


# ── Fixture 14: all claims supported → zero unsupported ─────────────────────

def test_fully_supported_dmist_produces_zero_flags():
    """When every claim in the DMIST matches the authoritative record → no flags."""
    result = check_documentation_claims(
        dmist_text=(
            "D: 8-year-old male, 25 kg. "
            "M: History of asthma, no known allergies. "
            "I: Albuterol via SVN, high-flow O2 via NRB mask. "
            "S: SpO2 83%, HR 134. "
            "T: ALS intercept en route, transporting to pediatric ED."
        ),
        narrative_text="",
        applied_intervention_ids=["albuterol_svn", "o2_nrb", "als_intercept"],
        assessed_vital_types={"spo2", "hr"},
        patient=_PATIENT_8YO_MALE,
    )
    assert result.available is True
    assert result.dmist_unsupported == [], (
        f"All claims are supported — expected no flags; got: {result.dmist_unsupported}"
    )
    assert result.narrative_unsupported == []


# ── Fixture 15: empty DMIST → no corroboration flags ─────────────────────────

def test_empty_dmist_produces_no_corroboration_flags():
    """Empty DMIST is a structural gap (Tier 1), not a corroboration violation — no flags."""
    result = check_documentation_claims(
        dmist_text="",
        narrative_text="",
        applied_intervention_ids=["o2_nrb", "albuterol_svn"],
        assessed_vital_types={"spo2"},
        patient=_PATIENT_8YO_MALE,
    )
    assert result.available is True
    assert result.dmist_unsupported == [], (
        "Empty DMIST must not produce corroboration flags (structural gap only)"
    )
    assert result.narrative_unsupported == []


# ── Structural assertions on CorroborationResult ─────────────────────────────

def test_corroboration_result_has_required_fields():
    result = check_documentation_claims(
        dmist_text="",
        narrative_text="",
        applied_intervention_ids=[],
        assessed_vital_types=set(),
        patient=_PATIENT_8YO_MALE,
    )
    assert hasattr(result, "available")
    assert hasattr(result, "dmist_unsupported")
    assert hasattr(result, "narrative_unsupported")
    assert hasattr(result, "method")
    assert hasattr(result, "ambiguous_count")
    assert result.method == "deterministic"
    assert isinstance(result.ambiguous_count, int)


def test_unsupported_claim_has_required_fields():
    """Any returned UnsupportedClaim must carry the required contract fields."""
    result = check_documentation_claims(
        dmist_text="D: 6-year-old female.",
        narrative_text="",
        applied_intervention_ids=[],
        assessed_vital_types=set(),
        patient=_PATIENT_8YO_MALE,
    )
    for claim in result.dmist_unsupported + result.narrative_unsupported:
        assert isinstance(claim, UnsupportedClaim)
        assert claim.document in ("dmist", "narrative")
        assert isinstance(claim.component, str)
        assert isinstance(claim.claim, str) and claim.claim
        assert isinstance(claim.reason, str) and claim.reason
        assert claim.claim_type in (
            "intervention_not_applied", "vital_not_assessed",
            "vital_value_mismatch", "demographic_mismatch"
        )
        assert claim.confidence in ("high", "medium")


def test_only_high_confidence_claims_in_unsupported_lists():
    """dmist_unsupported and narrative_unsupported must contain only high-confidence claims."""
    result = check_documentation_claims(
        dmist_text="D: 6-year-old female.",
        narrative_text="",
        applied_intervention_ids=[],
        assessed_vital_types=set(),
        patient=_PATIENT_8YO_MALE,
    )
    for claim in result.dmist_unsupported + result.narrative_unsupported:
        assert claim.confidence == "high", (
            f"Only high-confidence claims may appear in unsupported lists; "
            f"got confidence={claim.confidence!r} for claim {claim.claim!r}"
        )


# ── Fixture 16: word-boundary matching — short tokens must not match substrings ──

def test_epigastric_pain_does_not_flag_epinephrine():
    """'epi' in 'epigastric' must not produce an epinephrine flag (word-boundary required)."""
    result = check_documentation_claims(
        dmist_text="S: Patient complained of epigastric pain.",
        narrative_text="",
        applied_intervention_ids=[],
        assessed_vital_types=set(),
        patient=_PATIENT_8YO_MALE,
    )
    epi_flags = [
        c for c in result.dmist_unsupported
        if "epinephrine" in c.reason or c.claim.lower() == "epi"
    ]
    assert epi_flags == [], (
        f"'epigastric' must not flag epinephrine_im; got: {epi_flags}"
    )


def test_made_word_does_not_flag_naloxone_mad():
    """'mad' inside 'made' must not flag naloxone (word-boundary required)."""
    result = check_documentation_claims(
        dmist_text="I: Freshly made coffee in hand at scene.",
        narrative_text="",
        applied_intervention_ids=[],
        assessed_vital_types=set(),
        patient=_PATIENT_8YO_MALE,
    )
    mad_flags = [
        c for c in result.dmist_unsupported
        if "naloxone" in c.reason or c.claim.lower() == "mad"
    ]
    assert mad_flags == [], (
        f"'made' must not flag naloxone MAD; got: {mad_flags}"
    )


# ── Fixture 17: negation handling — negated mentions must not produce HIGH flags ─

def test_negated_epipen_not_flagged():
    """'EpiPen not available on scene' must not flag epinephrine as fabricated care."""
    result = check_documentation_claims(
        dmist_text="I: EpiPen not available on scene.",
        narrative_text="",
        applied_intervention_ids=[],
        assessed_vital_types=set(),
        patient=_PATIENT_8YO_MALE,
    )
    interv_flags = [
        c for c in result.dmist_unsupported
        if c.claim_type == "intervention_not_applied"
    ]
    assert interv_flags == [], (
        f"Negated 'EpiPen not available' must not flag as fabricated; got: {interv_flags}"
    )


def test_negated_aspirin_withheld_not_flagged():
    """'Aspirin withheld due to allergy' must not flag aspirin as fabricated care."""
    result = check_documentation_claims(
        dmist_text="I: Aspirin withheld due to allergy.",
        narrative_text="",
        applied_intervention_ids=[],
        assessed_vital_types=set(),
        patient=_PATIENT_8YO_MALE,
    )
    interv_flags = [
        c for c in result.dmist_unsupported
        if c.claim_type == "intervention_not_applied"
    ]
    assert interv_flags == [], (
        f"Negated 'aspirin withheld' must not flag as fabricated; got: {interv_flags}"
    )


# ── Fixture 18: narrative CHART element mapping ───────────────────────────────

def test_narrative_intervention_claim_maps_to_R_component():
    """Intervention claims in the narrative must use CHART component 'R' (Rx/Treatment)."""
    result = check_documentation_claims(
        dmist_text="",
        narrative_text="Performed jaw thrust to open the airway.",
        applied_intervention_ids=[],  # jaw_thrust not applied
        assessed_vital_types=set(),
        patient=_PATIENT_8YO_MALE,
    )
    interv_flags = [
        c for c in result.narrative_unsupported
        if c.claim_type == "intervention_not_applied"
    ]
    assert len(interv_flags) >= 1, (
        f"Expected intervention_not_applied flag in narrative; got: {result.narrative_unsupported}"
    )
    for flag in interv_flags:
        assert flag.component == "R", (
            f"Narrative intervention claims must map to component 'R'; got '{flag.component}'"
        )


def test_narrative_vital_claim_maps_to_A_component():
    """Vital sign claims in the narrative must use CHART component 'A' (Assessment)."""
    result = check_documentation_claims(
        dmist_text="",
        narrative_text="HR 96 noted on initial assessment.",
        applied_intervention_ids=[],
        assessed_vital_types=set(),  # HR not assessed
        patient=_PATIENT_8YO_MALE,
    )
    hr_flags = [
        c for c in result.narrative_unsupported
        if c.claim_type == "vital_not_assessed"
    ]
    assert len(hr_flags) >= 1, (
        f"Expected vital_not_assessed flag in narrative; got: {result.narrative_unsupported}"
    )
    for flag in hr_flags:
        assert flag.component == "A", (
            f"Narrative vital claims must map to component 'A'; got '{flag.component}'"
        )


def test_narrative_demographic_claim_maps_to_C_component():
    """Demographic contradictions in the narrative must use CHART component 'C'."""
    result = check_documentation_claims(
        dmist_text="",
        narrative_text="Responded to a call for a 6-year-old male.",
        applied_intervention_ids=[],
        assessed_vital_types=set(),
        patient=_PATIENT_8YO_MALE,  # age 8 — mismatch
    )
    demo_flags = [
        c for c in result.narrative_unsupported
        if c.claim_type == "demographic_mismatch"
    ]
    assert len(demo_flags) >= 1, (
        f"Expected demographic_mismatch flag in narrative; got: {result.narrative_unsupported}"
    )
    for flag in demo_flags:
        assert flag.component == "C", (
            f"Narrative demographic claims must map to component 'C'; got '{flag.component}'"
        )


# ── Fixture 19: canonicalize_vital_key() — label/synonym/separator variants ──

@pytest.mark.parametrize("raw,expected", [
    # Space-separated label forms (LLM display output)
    ("Heart Rate",                  "hr"),
    ("HR",                          "hr"),
    ("heart rate & pulse quality",  "hr"),
    ("Pulse",                       "hr"),
    ("Respiratory Rate",            "rr"),
    ("RR",                          "rr"),
    ("Resp Rate",                   "rr"),
    ("Blood Pressure",              "bp"),
    ("BP",                          "bp"),
    ("GCS",                         "gcs"),
    ("Glasgow Coma Scale",          "gcs"),
    ("Temperature",                 "temp"),
    ("Temp",                        "temp"),
    ("Blood Glucose",               "blood_glucose"),
    ("BGL",                         "blood_glucose"),
    ("bg",                          "blood_glucose"),
    ("SpO2",                        "spo2"),
    ("spo₂",                        "spo2"),
    ("Oxygen Saturation",           "spo2"),
    ("Pulse Ox",                    "spo2"),
    # Snake_case / hyphen / slash separator variants
    ("heart_rate",                  "hr"),
    ("resp_rate",                   "rr"),
    ("respiratory_rate",            "rr"),
    ("blood_pressure",              "bp"),
    ("blood_glucose",               "blood_glucose"),
    ("oxygen_saturation",           "spo2"),
    ("pulse_ox",                    "spo2"),
    ("pulse-ox",                    "spo2"),
    ("resp-rate",                   "rr"),
    # Untracked vital types → None
    ("skin_color",                  None),
    ("cap_refill",                  None),
    ("etco2",                       None),
    ("cardiac_rhythm",              None),
    ("twelve_lead",                 None),
    ("work_of_breathing",           None),
    ("pain",                        None),
    ("orthostatic",                 None),
])
def test_canonicalize_vital_key(raw, expected):
    """canonicalize_vital_key() maps all label/synonym/separator variants correctly."""
    assert canonicalize_vital_key(raw) == expected


def test_documented_hr_value_mismatch_flagged_when_vital_was_assessed():
    """Assessed vital type alone is not enough; materially wrong values are unsupported."""
    result = check_documentation_claims(
        dmist_text="S: HR 132, RR 44, SpO2 93%.",
        narrative_text="",
        applied_intervention_ids=["o2_blowby"],
        assessed_vital_types={"hr", "rr", "spo2"},
        assessed_vital_values={"hr": ["149 bpm"], "rr": ["44 breaths/min"], "spo2": ["93 %"]},
        patient={"age": None, "sex": "female", "weight_kg": 9},
    )
    mismatch_flags = [
        c for c in result.dmist_unsupported
        if c.claim_type == "vital_value_mismatch"
    ]
    assert len(mismatch_flags) == 1
    assert mismatch_flags[0].claim == "132"
    assert "149 bpm" in mismatch_flags[0].reason


def test_documented_spo2_outside_tolerance_flagged_even_with_passive_monitoring():
    """SpO2 is exempt from not-assessed flags, not from wrong-value corroboration."""
    result = check_documentation_claims(
        dmist_text="",
        narrative_text="Reassessment: SpO2 improved to 95%.",
        applied_intervention_ids=["o2_blowby"],
        assessed_vital_types={"spo2"},
        assessed_vital_values={"spo2": ["93 %"]},
        patient={"age": None, "sex": "female", "weight_kg": 9},
    )
    mismatch_flags = [
        c for c in result.narrative_unsupported
        if c.claim_type == "vital_value_mismatch"
    ]
    assert len(mismatch_flags) == 1
    assert mismatch_flags[0].claim == "95"


def test_documented_temperature_rounded_to_whole_number_is_supported():
    result = check_documentation_claims(
        dmist_text="S: temperature 103 F.",
        narrative_text="",
        applied_intervention_ids=[],
        assessed_vital_types={"temp"},
        assessed_vital_values={"temp": ["103.6 F"]},
        patient={"age": None, "sex": "female", "weight_kg": 9},
    )
    mismatch_flags = [
        c for c in result.dmist_unsupported
        if c.claim_type == "vital_value_mismatch"
    ]
    assert mismatch_flags == []


def test_plain_percentage_does_not_count_as_spo2_claim():
    """A percentage without an SpO2 label is too ambiguous for deterministic mismatch."""
    result = check_documentation_claims(
        dmist_text="",
        narrative_text="Burn estimate: approximately 14% total body surface area.",
        applied_intervention_ids=[],
        assessed_vital_types={"spo2"},
        assessed_vital_values={"spo2": ["93 %"]},
        patient={"age": None, "sex": "female", "weight_kg": 9},
    )
    mismatch_flags = [
        c for c in result.narrative_unsupported
        if c.claim_type == "vital_value_mismatch"
    ]
    assert mismatch_flags == []
