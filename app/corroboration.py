"""app/corroboration.py

Deterministic documentation corroboration module.

Coverage boundary
-----------------
The deterministic corroborator intentionally under-flags.  It only raises a
HIGH-confidence flag when it can make a claim with near-certainty from
structured state:

  • An intervention named in the DMIST / narrative is not present in
    applied_intervention_ids AND the pattern is unique to a single intervention
    ID (single-match).  Multi-match patterns → ambiguous_count only (no flag).

  • A vital sign value is stated in the DMIST / narrative but the vital type
    was not present in assessed_vital_types.  SpO2 is exempt (passively
    monitored).

  • A vital sign value is stated in the DMIST / narrative and assessed vital
    values were provided, but the stated value does not match any value the
    student actually assessed within a conservative tolerance.

  • A demographic field (age, sex, weight) in the DMIST / narrative
    contradicts the authoritative patient record by more than tolerance.

Anything the module cannot evaluate deterministically — free-text reasoning,
clinical judgement claims, partial documentation, ambiguous phrasings that
match multiple interventions — is left to the LLM pre-pass and is counted in
ambiguous_count but never flagged HIGH here.

Matching safety
---------------
All intervention patterns are matched with word-boundary anchors (\\b...\\b) to
prevent short tokens (e.g. "epi", "mad", "asa") from matching inside longer
unrelated words ("epigastric", "made", "Kansas").

Negation
--------
When a pattern match is found but the immediately surrounding text (±30 chars
preceding, ±20 chars following) contains a negation indicator ("not", "no",
"withheld", "denied", etc.), the mention is treated as ambiguous and counted in
ambiguous_count rather than flagged HIGH.  False positives are worse than false
negatives in this module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.scenarios.vocabulary import INTERVENTION_PARAPHRASE_PATTERNS

# ── Constants ─────────────────────────────────────────────────────────────────

PASSIVELY_MONITORED_VITAL_TYPES: frozenset[str] = frozenset({"spo2"})

# ── Vital-key canonicalization ─────────────────────────────────────────────────
# SessionFinding.key for vital findings originates from frontend LLM tag parsing,
# which preserves whatever the LLM emits: "HR", "Heart Rate", "Blood Pressure", etc.
# The shadow mode must canonicalize these before passing assessed_vital_types into
# check_documentation_claims(), which uses the lowercase canonical keys below.
# Keys not in this dict (e.g. "skin_color", "cap_refill", "etco2") are not tracked
# by the corroborator and are filtered out by canonicalize_vital_key().
_VITAL_KEY_CANONICAL: dict[str, str] = {
    # ── Heart rate ─────────────────────────────────────────────────────────────
    "hr": "hr",
    "heart rate": "hr",
    "heart rate & pulse quality": "hr",
    "heart rate and pulse quality": "hr",
    "pulse": "hr",
    "pulse rate": "hr",
    "pulse quality": "hr",
    # ── Respiratory rate ───────────────────────────────────────────────────────
    "rr": "rr",
    "resp rate": "rr",
    "respiratory rate": "rr",
    "respiratory rate and effort": "rr",
    "respirations": "rr",
    "respiratory effort": "rr",
    # ── Blood pressure ─────────────────────────────────────────────────────────
    "bp": "bp",
    "blood pressure": "bp",
    "blood_pressure": "bp",
    # ── GCS ────────────────────────────────────────────────────────────────────
    "gcs": "gcs",
    "glasgow coma scale": "gcs",
    "glasgow coma score": "gcs",
    "gcs score": "gcs",
    # ── Temperature ────────────────────────────────────────────────────────────
    "temp": "temp",
    "temperature": "temp",
    # ── Blood glucose ──────────────────────────────────────────────────────────
    "blood_glucose": "blood_glucose",
    "blood glucose": "blood_glucose",
    "blood sugar": "blood_glucose",
    "bgl": "blood_glucose",
    "bg": "blood_glucose",
    "glucose": "blood_glucose",
    # ── SpO2 (passively monitored — included so the shadow set is complete) ────
    "spo2": "spo2",
    "sp o2": "spo2",
    "spo₂": "spo2",
    "o2 sat": "spo2",
    "o2 saturation": "spo2",
    "oxygen saturation": "spo2",
    "pulse ox": "spo2",
    "pulse oximetry": "spo2",
}


def canonicalize_vital_key(raw_key: str) -> str | None:
    """Map a SessionFinding vital key to the canonical form used by check_documentation_claims().

    Normalizes separators before lookup so that underscore, hyphen, slash, and
    repeated-whitespace variants (e.g. "heart_rate", "resp-rate", "oxygen_saturation")
    resolve the same as their space-separated equivalents.

    Returns the canonical key string (e.g. "hr", "bp", "blood_glucose"), or None if
    the key does not correspond to a vital type tracked by the corroborator.
    Unrecognized keys (skin_color, cap_refill, etco2, etc.) return None and are
    silently dropped from the assessed_vital_types set.
    """
    normalized = re.sub(r"[_\-/]+", " ", raw_key.strip().lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return _VITAL_KEY_CANONICAL.get(normalized)

# Vital sign claim patterns.  Each pattern requires a numeric value adjacent
# to the vital keyword to distinguish "HR 96" from a generic mention of "heart
# rate assessment".  SpO2 is intentionally absent (passive monitoring exemption).
_VITAL_CLAIM_PATTERNS: dict[str, re.Pattern[str]] = {
    "hr": re.compile(
        r"\b(?:hr|heart\s+rate|pulse)\s*:?\s*\d+|\b\d+\s*(?:bpm|beats\s+per\s+minute)",
        re.IGNORECASE,
    ),
    "rr": re.compile(
        r"\b(?:rr|resp(?:iratory)?\s+rate|respirations)\s*:?\s*\d+|\b\d+\s*(?:rpm|breaths\s+per\s+minute)",
        re.IGNORECASE,
    ),
    "bp": re.compile(
        r"\b(?:bp|blood\s+pressure)\s*:?\s*\d+/\d+|\b\d+/\d+\s*(?:mmhg)?",
        re.IGNORECASE,
    ),
    "gcs": re.compile(
        r"\b(?:gcs|glasgow\s+coma\s+scale)\s*:?\s*\d+|\bgcs\s+(?:score\s+)?\d+",
        re.IGNORECASE,
    ),
    "temp": re.compile(
        r"\b(?:temp(?:erature)?)\s*:?\s*\d+\.?\d*\s*°?[FC]?|\b\d+\.?\d*\s*degrees",
        re.IGNORECASE,
    ),
    "blood_glucose": re.compile(
        r"\b(?:blood\s+glucose|blood\s+sugar|bgl|bg)\s*:?\s*\d+|\b\d+\s*mg/dl",
        re.IGNORECASE,
    ),
}

_VITAL_VALUE_PATTERNS: dict[str, re.Pattern[str]] = {
    "hr": re.compile(
        r"(?:\b(?:hr|heart\s+rate|pulse)\s*:?\s*(\d+(?:\.\d+)?)|\b(\d+(?:\.\d+)?)\s*(?:bpm|beats\s+per\s+minute))",
        re.IGNORECASE,
    ),
    "rr": re.compile(
        r"(?:\b(?:rr|resp(?:iratory)?\s+rate|respirations)\s*:?\s*(\d+(?:\.\d+)?)|\b(\d+(?:\.\d+)?)\s*(?:rpm|breaths\s+per\s+minute))",
        re.IGNORECASE,
    ),
    "bp": re.compile(
        r"(?:\b(?:bp|blood\s+pressure)\s*:?\s*(\d{2,3}/\d{2,3})|\b(\d{2,3}/\d{2,3})\s*(?:mmhg)?)",
        re.IGNORECASE,
    ),
    "gcs": re.compile(
        r"(?:\b(?:gcs|glasgow\s+coma\s+scale)\s*:?\s*(\d+)(?:/15)?|\bgcs\s+(?:score\s+)?(\d+)(?:/15)?)",
        re.IGNORECASE,
    ),
    "temp": re.compile(
        r"(?:\b(?:temp(?:erature)?)\s*:?\s*(\d+\.?\d*)\s*°?[FC]?|\b(\d+\.?\d*)\s*degrees)",
        re.IGNORECASE,
    ),
    "blood_glucose": re.compile(
        r"(?:\b(?:blood\s+glucose|blood\s+sugar|bgl|bg)\s*:?\s*(\d+(?:\.\d+)?)|\b(\d+(?:\.\d+)?)\s*mg/dl)",
        re.IGNORECASE,
    ),
    "spo2": re.compile(
        r"\b(?:spo2|sp\s*o2|spo₂|o2\s*sat(?:uration)?|oxygen\s*sat(?:uration)?|pulse\s*ox(?:imetry)?)\b[^\d]{0,30}(\d+(?:\.\d+)?)\s*%?",
        re.IGNORECASE,
    ),
}

_VITAL_VALUE_TOLERANCE: dict[str, float] = {
    "hr": 5.0,
    "rr": 2.0,
    "bp": 0.0,
    "gcs": 0.0,
    "temp": 1.0,
    "blood_glucose": 5.0,
    "spo2": 1.0,
}

_AGE_PATTERN = re.compile(
    r"\b(\d+)\s*[-]?\s*(?:year[- ]old|yo|y\.?o\.?|yoa|years?\s+old)",
    re.IGNORECASE,
)

_WEIGHT_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*kg\b",
    re.IGNORECASE,
)

_SEX_MALE_TERMS = re.compile(r"\b(?:male|boy|man|him|his)\b", re.IGNORECASE)
_SEX_FEMALE_TERMS = re.compile(r"\b(?:female|girl|woman|her|she)\b", re.IGNORECASE)

_NEGATION_PATTERN = re.compile(
    r"\b(?:not|no|without|withheld|denied|unavailable|refused|contraindicated|"
    r"allerg(?:y|ic)|withhold|unable)\b",
    re.IGNORECASE,
)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class UnsupportedClaim:
    document: str   # "dmist" | "narrative"
    component: str  # DMIST letter (D/M/I/S/T) or CHART letter (C/H/A/R/T)
    claim: str      # verbatim matched text fragment
    reason: str     # human-readable explanation
    claim_type: str  # "intervention_not_applied" | "vital_not_assessed" | "demographic_mismatch"
    confidence: str  # "high" | "medium"


@dataclass
class CorroborationResult:
    available: bool
    dmist_unsupported: list[UnsupportedClaim] = field(default_factory=list)
    narrative_unsupported: list[UnsupportedClaim] = field(default_factory=list)
    method: str = "deterministic"
    ambiguous_count: int = 0


# ── Reverse index: compiled word-boundary patterns → intervention ID lists ────

def _build_reverse_index() -> dict[re.Pattern[str], list[str]]:
    """Build word-boundary regex → [intervention_id, ...] lookup from vocabulary.

    Each pattern string is compiled with \\b anchors so that short tokens like
    "epi", "mad", and "asa" only match as standalone words.
    """
    str_index: dict[str, list[str]] = {}
    for iid, patterns in INTERVENTION_PARAPHRASE_PATTERNS.items():
        for p in patterns:
            str_index.setdefault(p.lower(), []).append(iid)

    compiled: dict[re.Pattern[str], list[str]] = {}
    for p_str, iid_list in str_index.items():
        compiled[re.compile(r"\b" + re.escape(p_str) + r"\b", re.IGNORECASE)] = iid_list
    return compiled


_REVERSE_INDEX: dict[re.Pattern[str], list[str]] = _build_reverse_index()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_negated(text: str, match_start: int, match_end: int) -> bool:
    """Return True if the matched span appears to be negated by surrounding context.

    Checks 30 characters before and 20 characters after the match for negation
    indicators.  Conservative windows balance catching "EpiPen not available"
    and "aspirin withheld" without absorbing unrelated "not" clauses that appear
    several sentences later.
    """
    preceding = text[max(0, match_start - 30):match_start]
    following = text[match_end:min(len(text), match_end + 20)]
    return bool(_NEGATION_PATTERN.search(preceding) or _NEGATION_PATTERN.search(following))


def _check_interventions(
    text: str,
    applied_set: set[str],
    document: str,
    component: str,
    ambiguous_ref: list[int],
) -> list[UnsupportedClaim]:
    """Return HIGH-confidence intervention flags for *text*.

    Order of precedence for each matched pattern:
      1. Any matching ID applied → supported, no flag.
      2. Negation indicator in surrounding context → ambiguous_count++, no flag.
      3. Multi-match (pattern shared by >1 ID) and none applied → ambiguous_count++.
      4. Single-match, not applied, not negated → HIGH confidence flag.
    """
    if not text:
        return []

    flags: list[UnsupportedClaim] = []
    flagged_ids: set[str] = set()
    counted_groups: set[frozenset[str]] = set()

    for pattern_re, iid_list in _REVERSE_INDEX.items():
        match = pattern_re.search(text)
        if not match:
            continue

        # 1. Supported — at least one matching ID was applied.
        if any(iid in applied_set for iid in iid_list):
            continue

        group_key = frozenset(iid_list)

        # 2. Negated mention → ambiguous, not a HIGH flag.
        if _is_negated(text, match.start(), match.end()):
            if group_key not in counted_groups:
                ambiguous_ref[0] += 1
                counted_groups.add(group_key)
            continue

        # 3. Multi-match and none applied → ambiguous.
        if len(iid_list) > 1:
            if group_key not in counted_groups:
                ambiguous_ref[0] += 1
                counted_groups.add(group_key)
            continue

        # 4. Single-match, not applied, not negated → HIGH flag.
        iid = iid_list[0]
        if iid in flagged_ids:
            continue

        flagged_ids.add(iid)
        claim_text = match.group(0)
        flags.append(UnsupportedClaim(
            document=document,
            component=component,
            claim=claim_text,
            reason=(
                f"Documentation references '{claim_text}' but intervention "
                f"'{iid}' was not applied during the session."
            ),
            claim_type="intervention_not_applied",
            confidence="high",
        ))

    return flags


def _check_vitals(
    text: str,
    assessed_vital_types: set[str],
    document: str,
    component: str = "S",
) -> list[UnsupportedClaim]:
    """Flag vitals claimed in *text* that were never assessed.

    component: DMIST component letter ("S") or CHART element ("A" for narrative).
    """
    if not text:
        return []

    flags: list[UnsupportedClaim] = []
    for vital_type, pattern in _VITAL_CLAIM_PATTERNS.items():
        if vital_type in PASSIVELY_MONITORED_VITAL_TYPES:
            continue
        match = pattern.search(text)
        if match and vital_type not in assessed_vital_types:
            flags.append(UnsupportedClaim(
                document=document,
                component=component,
                claim=match.group(0).strip(),
                reason=(
                    f"Documentation states a {vital_type.upper()} value but "
                    f"this vital was not recorded as assessed during the session."
                ),
                claim_type="vital_not_assessed",
                confidence="high",
            ))

    return flags


def _extract_vital_values(text: str, vital_type: str) -> list[str]:
    pattern = _VITAL_VALUE_PATTERNS.get(vital_type)
    if not pattern:
        return []
    values: list[str] = []
    for match in pattern.finditer(text):
        value = next((g for g in match.groups() if g), "")
        if value:
            values.append(value)
    return values


def _numeric_value(value: str) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def _vital_value_supported(vital_type: str, stated: str, assessed_values: list[str]) -> bool:
    if not assessed_values:
        return True

    if vital_type == "bp":
        normalized = re.sub(r"\s+", "", stated.lower())
        return any(normalized == re.sub(r"\s+", "", str(v).lower()) for v in assessed_values)

    stated_num = _numeric_value(stated)
    if stated_num is None:
        return True
    tolerance = _VITAL_VALUE_TOLERANCE.get(vital_type, 0.0)
    for assessed in assessed_values:
        assessed_num = _numeric_value(assessed)
        if assessed_num is not None and abs(stated_num - assessed_num) <= tolerance:
            return True
    return False


def _check_vital_value_mismatches(
    text: str,
    assessed_vital_values: dict[str, list[str]],
    document: str,
    component: str = "S",
) -> list[UnsupportedClaim]:
    """Flag vital values that disagree with what the student actually recorded.

    This is optional and only runs when assessed_vital_values is supplied.  The
    check is intentionally one-flag-per-vital-type to prevent over-penalizing a
    single documentation section that repeats the same unsupported value.
    """
    if not text or not assessed_vital_values:
        return []

    flags: list[UnsupportedClaim] = []
    for vital_type, assessed_values in assessed_vital_values.items():
        if not assessed_values:
            continue
        for stated in _extract_vital_values(text, vital_type):
            if _vital_value_supported(vital_type, stated, assessed_values):
                continue
            flags.append(UnsupportedClaim(
                document=document,
                component=component,
                claim=stated,
                reason=(
                    f"Documentation states {vital_type.upper()} value {stated}, "
                    f"but assessed value(s) recorded during the run were: "
                    f"{', '.join(map(str, assessed_values))}."
                ),
                claim_type="vital_value_mismatch",
                confidence="high",
            ))
            break

    return flags


def _check_demographics(
    text: str,
    patient: dict,
    document: str,
    component: str = "D",
) -> list[UnsupportedClaim]:
    """Flag demographic claims in *text* that contradict the authoritative patient record.

    component: DMIST component letter ("D") or CHART element ("C" for narrative).
    """
    if not text:
        return []

    flags: list[UnsupportedClaim] = []

    # ── Age ───────────────────────────────────────────────────────────────────
    patient_age = patient.get("age")
    if patient_age is not None:
        for m in _AGE_PATTERN.finditer(text):
            stated_age = int(m.group(1))
            if stated_age != patient_age:
                flags.append(UnsupportedClaim(
                    document=document,
                    component=component,
                    claim=m.group(0),
                    reason=(
                        f"Documentation states age {stated_age} but patient "
                        f"record shows age {patient_age}."
                    ),
                    claim_type="demographic_mismatch",
                    confidence="high",
                ))
                break  # one flag per field

    # ── Sex ───────────────────────────────────────────────────────────────────
    patient_sex = (patient.get("sex") or "").lower()
    if patient_sex in ("male", "female"):
        opposite_pattern = _SEX_FEMALE_TERMS if patient_sex == "male" else _SEX_MALE_TERMS
        same_pattern = _SEX_MALE_TERMS if patient_sex == "male" else _SEX_FEMALE_TERMS
        # Only flag if an opposite-sex term is present AND no same-sex term that
        # would indicate co-reference (e.g. "the boy and his sister").
        opp_match = opposite_pattern.search(text)
        same_match = same_pattern.search(text)
        if opp_match and not same_match:
            flags.append(UnsupportedClaim(
                document=document,
                component=component,
                claim=opp_match.group(0),
                reason=(
                    f"Documentation uses '{opp_match.group(0)}' but patient "
                    f"record shows sex={patient_sex}."
                ),
                claim_type="demographic_mismatch",
                confidence="high",
            ))

    # ── Weight ────────────────────────────────────────────────────────────────
    patient_weight = patient.get("weight_kg")
    if patient_weight is not None:
        for m in _WEIGHT_PATTERN.finditer(text):
            stated_weight = float(m.group(1))
            if abs(stated_weight - patient_weight) > 1.0:
                flags.append(UnsupportedClaim(
                    document=document,
                    component=component,
                    claim=m.group(0),
                    reason=(
                        f"Documentation states {stated_weight} kg but patient "
                        f"record shows {patient_weight} kg (tolerance: ±1 kg)."
                    ),
                    claim_type="demographic_mismatch",
                    confidence="high",
                ))
                break

    return flags


# ── Public API ────────────────────────────────────────────────────────────────

def check_documentation_claims(
    *,
    dmist_text: str,
    narrative_text: str,
    applied_intervention_ids: list[str],
    assessed_vital_types: set[str],
    patient: dict,
    assessed_vital_values: dict[str, list[str]] | None = None,
) -> CorroborationResult:
    """Deterministically check documentation claims against authoritative session state.

    Parameters
    ----------
    dmist_text:
        Full text of the student's DMIST entry.
    narrative_text:
        Full text of the student's run narrative.
    applied_intervention_ids:
        Stable intervention IDs applied during the session (authoritative,
        from session state — never from documentation).
    assessed_vital_types:
        Vital type strings (e.g. "hr", "spo2") that were actively assessed,
        from SessionFinding records.
    assessed_vital_values:
        Optional canonical vital type → observed values map. When provided,
        documented vital values are checked against actual student-recorded
        values with conservative tolerances.
    patient:
        Dict with keys "age" (int), "sex" (str), "weight_kg" (float|int).

    Returns
    -------
    CorroborationResult with available=True and only HIGH-confidence flags.
    DMIST components use DMIST letters (D/M/I/S/T).
    Narrative components use CHART letters (C/H/A/R/T):
      R — Rx/treatment (intervention claims)
      A — Assessment (vital sign claims)
      C — Chief complaint/presentation (demographic claims)
    """
    applied_set = set(applied_intervention_ids)
    ambiguous_ref = [0]

    dmist_flags: list[UnsupportedClaim] = []
    narrative_flags: list[UnsupportedClaim] = []

    if dmist_text:
        dmist_flags.extend(
            _check_interventions(dmist_text, applied_set, "dmist", "I", ambiguous_ref)
        )
        dmist_flags.extend(
            _check_vitals(dmist_text, assessed_vital_types, "dmist", component="S")
        )
        dmist_flags.extend(
            _check_vital_value_mismatches(
                dmist_text, assessed_vital_values or {}, "dmist", component="S"
            )
        )
        dmist_flags.extend(
            _check_demographics(dmist_text, patient, "dmist", component="D")
        )

    if narrative_text:
        narrative_flags.extend(
            _check_interventions(
                narrative_text, applied_set, "narrative", "R", ambiguous_ref
            )
        )
        narrative_flags.extend(
            _check_vitals(narrative_text, assessed_vital_types, "narrative", component="A")
        )
        narrative_flags.extend(
            _check_vital_value_mismatches(
                narrative_text, assessed_vital_values or {}, "narrative", component="A"
            )
        )
        narrative_flags.extend(
            _check_demographics(narrative_text, patient, "narrative", component="C")
        )

    return CorroborationResult(
        available=True,
        dmist_unsupported=dmist_flags,
        narrative_unsupported=narrative_flags,
        method="deterministic",
        ambiguous_count=ambiguous_ref[0],
    )


def to_prepass_result(result: CorroborationResult) -> dict:
    """Adapt a CorroborationResult to the LLM pre-pass dict schema."""
    return {
        "available": result.available,
        "dmist_unsupported": [
            {
                "component": c.component,
                "claim": c.claim,
                "reason": c.reason,
            }
            for c in result.dmist_unsupported
        ],
        "narrative_unsupported": [
            {
                "chart_element": c.component,
                "claim": c.claim,
                "reason": c.reason,
            }
            for c in result.narrative_unsupported
        ],
    }
