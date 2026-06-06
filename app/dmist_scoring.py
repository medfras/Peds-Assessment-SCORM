"""Deterministic DMIST scoring helpers.

This module is intentionally conservative. It awards credit only for content
that can be matched from authored scenario expectations and authoritative run
evidence. It is designed to run in shadow mode before becoming score-authority.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.corroboration import canonicalize_vital_key


DMIST_COMPONENT_MEANINGS: dict[str, str] = {
    "D": "Demographics",
    "M": "MOI or chief complaint",
    "I": "Injuries or illness",
    "S": "Signs and symptoms",
    "T": "Treatment or transport",
}

_SECTION_RE = re.compile(
    r"(?ims)(?:^|\n)\s*(D|M|I|S|T)\s*(?:[—\-:.)])\s*(.*?)(?=(?:\n\s*[DMIST]\s*(?:[—\-:.)])\s*)|\Z)"
)


@dataclass
class DmistComponentScore:
    component: str
    meaning: str
    score: int
    max_score: int = 2
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


@dataclass
class DmistScoreResult:
    score: int
    max_score: int
    components: dict[str, DmistComponentScore]
    method: str = "deterministic_shadow_v1"
    applicable: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["components"] = {
            key: asdict(value) for key, value in self.components.items()
        }
        return payload


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def segment_dmist(text: str) -> dict[str, str]:
    """Return detected D/M/I/S/T sections, falling back to full text per component."""
    raw = str(text or "").strip()
    if not raw:
        return {component: "" for component in "DMIST"}
    sections = {component: "" for component in "DMIST"}
    found = False
    for match in _SECTION_RE.finditer(raw):
        found = True
        sections[match.group(1).upper()] = match.group(2).strip()
    if found:
        return sections
    return {component: raw for component in "DMIST"}


def _is_pediatric_patient(patient: dict[str, Any]) -> bool:
    if patient.get("age_months") is not None:
        return True
    try:
        return int(patient.get("age", 99)) < 18
    except (TypeError, ValueError):
        return False


def _assessed_vital_keys(findings: list[Any]) -> set[str]:
    keys: set[str] = set()
    for finding in findings or []:
        if getattr(finding, "finding_type", "") != "vital":
            continue
        key = canonicalize_vital_key(str(getattr(finding, "key", "") or ""))
        if key:
            keys.add(key)
    return keys


def _text_has_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _element_patterns(element: str) -> list[str]:
    e = _norm(element)
    patterns: list[str] = []
    if "name:" in e:
        value = e.split("name:", 1)[1].strip()
        if value:
            patterns.append(rf"\b{re.escape(value)}\b")
    age_match = re.search(r"\bage\s*:\s*(\d+)", e)
    if age_match:
        age = age_match.group(1)
        word_map = {
            "1": "one", "2": "two", "3": "three", "4": "four", "5": "five",
            "6": "six", "7": "seven", "8": "eight", "9": "nine", "10": "ten",
            "11": "eleven", "12": "twelve", "13": "thirteen", "14": "fourteen",
            "15": "fifteen", "16": "sixteen", "17": "seventeen",
        }
        word = word_map.get(age)
        age_terms = [re.escape(age)]
        if word:
            age_terms.append(word)
        patterns.append(rf"\b(?:{'|'.join(age_terms)})\s*[- ]?\s*(?:year|yr|yo|yom|yof|month)")
    elif "6-month" in e or "month" in e:
        patterns.extend([r"\b(?:6|six)\s*[- ]?\s*month", r"\binfant\b", r"\bbaby\b"])
    if "weight:" in e or "kg" in e or "lbs" in e:
        weight_numbers = re.findall(r"\b\d+(?:\.\d+)?\b", e)
        weight_terms = []
        for number in weight_numbers[:4]:
            weight_terms.append(rf"\b{re.escape(number)}\s*(?:kg|kilos?|kilograms?|lb|lbs|pounds?)\b")
        patterns.extend(weight_terms or [r"\bweight\b"])
        patterns.append(r"\bweight\b")
    if "female" in e:
        patterns.append(r"\bfemale\b|\bgirl\b")
    if "male" in e:
        patterns.append(r"\bmale\b|\bboy\b")
    if "active seizure" in e or "seizure" in e:
        patterns.append(r"\bseiz(?:ure|ing)\b|\bshaking\b|\bconvuls")
    if "duration" in e or "ongoing" in e or "timing" in e:
        patterns.append(r"\b\d+\s*(?:min|minute)|\bongoing\b|\bstill\b|\bstarted\b|\bbegan\b|\bduration\b")
    if "generalized" in e:
        patterns.append(r"\bgeneralized\b|\bwhole[- ]?body\b|\bfull[- ]?body\b|\ball over\b")
    if "fever" in e or "illness" in e or "febrile" in e:
        patterns.append(r"\bfever\b|\bfebrile\b|\bhot\b|\bcongestion\b|\brunny nose\b|\bill(?:ness)?\b")
    if "uri" in e or "upper respiratory" in e:
        patterns.append(r"\buri\b|\bupper respiratory\b|\bcongestion\b|\brunny nose\b|\bcold\b|\bcough\b")
    if "first seizure" in e or "no prior" in e:
        patterns.append(r"\bfirst\b|\bno prior\b|\bnever happened\b|\bno history\b")
    if "prior respiratory" in e or "prior breathing" in e:
        patterns.append(r"\bno prior\b.{0,40}\b(?:breathing|respiratory|hospital)|\bprior\b.{0,40}\b(?:breathing|respiratory|hospital|intubat|icu)|\bno history\b.{0,40}\b(?:breathing|respiratory)")
    if "trauma" in e:
        patterns.append(r"\bno trauma\b|\bno fall\b|\bfall\b|\btrauma\b|\binjury\b")
    if "fall mechanism" in e or ("fall" in e and "mechanism" in e):
        patterns.append(r"\bfall\b|\bfell\b|\btripp(?:ed|ing)?\b|\brunning\b|\bstruck\b|\bhit\b|\btable\b|\bcorner\b")
    if "fall height" in e:
        patterns.append(r"\b(?:about|approximately|approx\.?)?\s*(?:8|eight)\s*(?:ft|feet|foot)\b|\b(?:8|eight)\s*feet?\s*up\b")
    if "vomiting episode" in e or "single vomiting" in e:
        patterns.append(r"\bvomit(?:ed|ing)?\b|\bthrew up\b|\bthrow up\b|\bgot sick\b|\bfound it\b")
    if "scalp laceration" in e or "laceration" in e:
        patterns.append(r"\blacerat(?:ion|ing|ed)?\b|\bcut\b|\bscalp\b|\bhead\b")
    if "bleeding" in e or "bleeding status" in e:
        patterns.append(r"\bbleed(?:ing)?\b|\bblood\b|\bbloody\b|\bpressure\b|\bdressing\b|\bcontrolled\b")
    if "bleeding control" in e or "bleeding control method" in e:
        patterns.append(r"\bdirect pressure\b|\bpressure dressing\b|\bdressing\b|\bbandag|\bcontrolled\b")
    if "neuro" in e or "gcs" in e or "avpu" in e:
        patterns.append(r"\bgcs\b|\bavpu\b|\ba\s*(?:and|&)\s*o\b|\ba\W*o\b|\boriented\b|\balert\b|\bpupils?\b|\bperrl\b")
    if "confused" in e or "disoriented" in e:
        patterns.append(r"\bconfus(?:ed|ion)\b|\bdisorient(?:ed|ation)?\b|\bgcs\s*(?:of\s*)?14\b|\bgcs\s*14\b")
    if "pupil" in e or "eye" in e:
        patterns.append(
            r"(?:pupils?|eyes?).{0,45}(?:unequal|on\s+equal|sluggish|react(?:ive|ivity)?|brisk|\d\s*mm)|"
            r"(?:unequal|on\s+equal|sluggish|react(?:ive|ivity)?|brisk|\d\s*mm).{0,45}(?:pupils?|eyes?)"
        )
    if "current condition" in e or "current status" in e:
        patterns.append(r"\balert\b|\boriented\b|\bgcs\b|\bavpu\b|\bstable\b|\bcontrolled\b|\bimprov")
    if "choking" in e:
        patterns.append(r"\bno choking\b|\bchok")
    if "stridor" in e:
        patterns.append(r"\bstridor\b|\bstrider\b|\bnoisy breathing\b|\bhigh[- ]?pitched\b")
    if "ingestion" in e:
        patterns.append(r"\bno ingestion\b|\bswallow|\bingest")
    if "airway" in e or "secretions" in e or "gurgling" in e:
        patterns.append(r"\bairway\b|\bsecretions?\b|\bsaliva\b|\bgurgling\b|\bwet\b")
    if "spo2" in e or "oxygenation" in e or "respiratory" in e:
        patterns.append(r"\bspo2\b|\bsp\s*o2\b|\bo2\s*sat\b|\boxygenation\b|\bresp(?:iratory|irations?)\b|\bbreath")
    if "wheez" in e:
        patterns.append(r"\bwheez(?:e|ing|es)?\b|\bwhistl")
    if "asthma" in e:
        patterns.append(r"\basthma\b|\breactive airway\b")
    if "albuterol" in e:
        patterns.append(r"\balbuterol\b|\bsvn\b|\bnebuliz|\bmdi\b|\binhaler\b")
    if "supplemental o2" in e or "oxygen" in e or re.search(r"\bo2\b", e):
        patterns.append(r"\boxygen\b|\bo2\b|\bnrb\b|\bblow[- ]?by\b")
    if "temperature" in e or "febrile" in e:
        patterns.append(r"\btemp(?:erature)?\b|\b\d{2,3}(?:\.\d)?\s*°?\s*f\b|\bfebrile\b|\bfever\b")
    if "blood glucose" in e or "glucose" in e or "bgl" in e:
        patterns.append(r"\bblood glucose\b|\bblood sugar\b|\bbgl\b|\bbg\b|\bglucose\b|\bmg/dl\b")
    if "response" in e:
        patterns.append(r"\bimprov(?:ed|ing|ement)?\b|\bresponse\b|\bcame up\b|\bafter\b")
    if "als" in e or "transport" in e or "disposition" in e:
        patterns.append(r"\bals\b|\bmedic\b|\btransport\b|\bhandoff\b|\bturnover\b|\bhospital\b|\bed\b")
    if "smr" in e or "spinal motion" in e or "c-spine" in e or "cervical" in e:
        patterns.append(r"\bsmr\b|\bspinal motion\b|\bc[- ]?spine\b|\bcervical\b|\bcollar\b|\bbackboard\b|\bin[- ]?line\b|\bmanual stabilization\b|\bhealthy spine\b")
    if not patterns:
        words = [re.escape(w) for w in re.findall(r"[a-z0-9]+", e) if len(w) > 3]
        if words:
            patterns.append(r"\b(?:" + "|".join(words[:4]) + r")\b")
    return patterns


def _score_required_elements(text: str, required: list[str]) -> tuple[list[str], list[str]]:
    matched: list[str] = []
    missing: list[str] = []
    normalized = _norm(text)
    for element in required:
        patterns = _element_patterns(str(element))
        if patterns and _text_has_any(normalized, patterns):
            matched.append(str(element))
        else:
            missing.append(str(element))
    return matched, missing


def _score_from_counts(matched: int, total: int) -> int:
    if total <= 0:
        return 0
    ratio = matched / total
    if ratio >= 0.75:
        return 2
    if ratio > 0:
        return 1
    return 0


def _required_treatment_intervention_id(element: str) -> str | None:
    """Return the intervention id that must corroborate a T required element.

    T is the only DMIST component where authored required_elements often name
    treatments. For those elements, text alone is not enough: the intervention
    must also exist in the authoritative applied-intervention timeline.
    """
    e = _norm(element)
    if "response" in e or "current condition" in e or "trajectory" in e:
        return None
    if "suction" in e:
        return "suction_airway"
    if "lateral" in e or "recovery position" in e:
        return "recovery_position"
    if "supplemental o2" in e or "oxygen" in e or "o2" in e:
        return "__oxygen__"
    if "oral glucose" in e or "glucose gel" in e:
        return "oral_glucose"
    if "albuterol" in e:
        return "__albuterol__"
    if "epinephrine" in e or "epi" in e:
        return "epinephrine_im"
    if "naloxone" in e or "narcan" in e:
        return "naloxone_in"
    if "aspirin" in e:
        return "aspirin"
    if "dressing" in e or "direct pressure" in e:
        return "__bleeding_control__"
    if "smr" in e or "spinal motion" in e or "c-spine" in e or "cervical" in e:
        return "smr"
    return None


def _applied_intervention_matches(required_id: str, applied_intervention_ids: set[str]) -> bool:
    if required_id == "__oxygen__":
        return bool(applied_intervention_ids & {"o2_blowby", "o2_nrb", "o2_nasal_cannula", "oxygen"})
    if required_id == "__albuterol__":
        return bool(applied_intervention_ids & {"albuterol_svn", "albuterol_mdi"})
    if required_id == "__bleeding_control__":
        return bool(applied_intervention_ids & {"direct_pressure", "pressure_dressing", "dry_sterile_dressing"})
    return required_id in applied_intervention_ids


def _generic_component_score(text: str, component: str) -> DmistComponentScore:
    normalized = _norm(text)
    if not normalized:
        return DmistComponentScore(component, DMIST_COMPONENT_MEANINGS[component], 0, missing=["component absent"])
    patterns = {
        "M": [
            r"\bmechanism\b|\bmoi\b|\bchief complaint\b|\bnature of illness\b",
            r"\bchest pain\b|\bdifficulty breathing\b|\bshort(?:ness)? of breath\b|\bseiz(?:ure|ing)\b|\bsyncope\b|\baltered\b",
            r"\btrauma\b|\binjury\b|\bfall\b|\bfell\b|\bstruck\b|\bmvc\b|\bcrash\b",
        ],
        "I": [
            r"\binjur(?:y|ies|ed)\b|\bpain\b|\bbleed(?:ing)?\b|\bdeformity\b|\bburn\b|\bwound\b|\blacerat|\bcut\b",
            r"\bill(?:ness)?\b|\bmedical history\b|\bpmh\b|\ballerg(?:y|ies|ic)\b|\bmedications?\b",
            r"\bonset\b|\bduration\b|\bstarted\b|\bbegan\b|\bfever\b|\bcough\b|\bcongestion\b|\bdenies?\b|\bno\s+(?:loc|loss of consciousness|vomit)|\bgcs\b|\bpupils?\b|\bperrl\b",
        ],
    }.get(component, [])
    matched = [
        f"{component} detail {idx}"
        for idx, pattern in enumerate(patterns, start=1)
        if re.search(pattern, normalized)
    ]
    if len(matched) >= 2:
        score = 2
    elif matched:
        score = 1
    else:
        score = 1
    return DmistComponentScore(component, DMIST_COMPONENT_MEANINGS[component], score, matched=matched)


def _is_legacy_intervention_i_config(component_cfg: dict[str, Any]) -> bool:
    """Detect old scenario configs where DMIST I was authored as interventions.

    The corrected DMIST model uses I for injuries/illness, while treatments
    belong under T. Older scenario files may still contain component text like
    "Interventions performed"; ignore those authored required elements so stale
    content cannot distort deterministic scoring.
    """
    if not isinstance(component_cfg, dict):
        return False
    text = " ".join(
        [
            str(component_cfg.get("description") or ""),
            " ".join(str(item) for item in component_cfg.get("required_elements") or []),
        ]
    ).lower()
    if not text:
        return False
    intervention_terms = (
        "intervention",
        "treatment",
        "administer",
        "oxygen",
        "suction",
        "splint",
        "dressing",
        "albuterol",
        "epinephrine",
        "naloxone",
        "glucose",
        "positioning",
    )
    corrected_terms = ("injur", "illness", "chief complaint", "symptom", "history", "etiology")
    return any(term in text for term in intervention_terms) and not any(term in text for term in corrected_terms)


def _score_demographics(text: str, patient: dict[str, Any]) -> DmistComponentScore:
    normalized = _norm(text)
    pediatric = _is_pediatric_patient(patient)
    checks: list[tuple[str, bool]] = []
    name = str(patient.get("name") or "").strip()
    if name:
        checks.append(("name", bool(re.search(rf"\b{re.escape(name.lower())}\b", normalized))))
    age_words = (
        "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
        "thirteen|fourteen|fifteen|sixteen|seventeen"
    )
    checks.append((
        "age",
        bool(re.search(rf"\b(?:\d+|{age_words})\s*[- ]?\s*(?:month|year)|\binfant\b|\badult\b", normalized)),
    ))
    sex = str(patient.get("sex") or "").lower()
    if sex:
        checks.append(("sex", bool(re.search(rf"\b{re.escape(sex)}\b|\b(?:boy|girl|male|female)\b", normalized))))
    if pediatric:
        checks.append(("pediatric weight", bool(re.search(r"\b\d+(?:\.\d+)?\s*kg\b|\b\d+\s*(?:lb|lbs|pounds?)\b|\bweight\b", normalized))))
    matched = [label for label, ok in checks if ok]
    missing = [label for label, ok in checks if not ok]
    if pediatric and missing:
        # Pediatric weight is not a nice-to-have in handoff: it drives ALS
        # medication and equipment decisions. Any missing pediatric demographic
        # element makes D partial rather than full credit.
        score = 1 if matched else 0
    else:
        required_count = len(checks)
        score = _score_from_counts(len(matched), required_count)
    return DmistComponentScore("D", DMIST_COMPONENT_MEANINGS["D"], score, matched=matched, missing=missing)


def _score_signs(text: str, component_cfg: dict[str, Any], findings: list[Any]) -> DmistComponentScore:
    required = list(component_cfg.get("required_elements") or [])
    matched, missing = _score_required_elements(text, required)
    assessed = _assessed_vital_keys(findings)
    normalized = _norm(text)
    flags: list[str] = []
    claimed_unassessed: list[str] = []
    vital_patterns = {
        "hr": r"\bhr\b|\bheart rate\b|\bpulse\b|\bbpm\b",
        "rr": r"\brr\b|\bresp(?:iratory)? rate\b|\bbreaths?/min\b",
        "bp": r"\bbp\b|\bblood pressure\b|\b\d{2,3}/\d{2,3}\b",
        "temp": r"\btemp(?:erature)?\b|\b\d{2,3}(?:\.\d)?\s*°?\s*f\b",
        "blood_glucose": r"\bblood glucose\b|\bblood sugar\b|\bbgl\b|\bbg\b|\bmg/dl\b",
    }
    for key, pattern in vital_patterns.items():
        if re.search(pattern, normalized) and key not in assessed:
            claimed_unassessed.append(key)
    if claimed_unassessed:
        flags.append("unassessed_vital_claims:" + ",".join(sorted(claimed_unassessed)))
    if required:
        score = _score_from_counts(len(matched), len(required))
    else:
        generic_sign_hit = re.search(
            r"\bspo2\b|\bsaturation\b|\bpulse\b|\bheart rate\b|\bhr\b|\brr\b|"
            r"\bblood pressure\b|\bbp\b|\bgcs\b|\bavpu\b|\bvitals\b|\bsigns?\b|"
            r"\bsymptoms?\b|\bpain\b|\bbreath|\bskin\b|\balert\b|\bunresponsive\b",
            normalized,
        )
        score = 2 if generic_sign_hit else 0
    if claimed_unassessed and score > 1:
        score = 1
    if claimed_unassessed and not matched:
        score = 0
    return DmistComponentScore("S", DMIST_COMPONENT_MEANINGS["S"], score, matched=matched, missing=missing, flags=flags)


def _score_treatment_transport(
    text: str,
    component_cfg: dict[str, Any],
    applied_intervention_ids: set[str],
) -> DmistComponentScore:
    required = list(component_cfg.get("required_elements") or [])
    matched: list[str] = []
    missing: list[str] = []
    flags: list[str] = []
    required_matched_count = 0
    normalized = _norm(text)
    for element in required:
        element_text = str(element)
        required_id = _required_treatment_intervention_id(element_text)
        text_matches = bool(_element_patterns(element_text) and _text_has_any(normalized, _element_patterns(element_text)))
        if required_id:
            applied_matches = _applied_intervention_matches(required_id, applied_intervention_ids)
            if text_matches and applied_matches:
                matched.append(element_text)
                required_matched_count += 1
            else:
                missing.append(element_text)
                if text_matches and not applied_matches:
                    flags.append(f"unsupported_intervention_claim:{required_id}")
            continue
        if text_matches:
            matched.append(element_text)
            required_matched_count += 1
        else:
            missing.append(element_text)
    applied_hits: list[str] = []
    intervention_patterns = {
        "recovery_position": r"\brecovery position\b|\blateral\b|\bon (?:her|his|their) side\b|\bside\b",
        "suction_airway": r"\bsuction(?:ed|ing)?\b",
        "o2_blowby": r"\boxygen\b|\bo2\b|\bnrb\b|\bblow[- ]?by\b",
        "o2_nrb": r"\boxygen\b|\bo2\b|\bnrb\b",
        "blood_glucose_check": r"\bblood glucose\b|\bbgl\b|\bbg\b|\bglucose\b",
        "oral_glucose": r"\boral glucose\b|\bglucose gel\b|\bglucose\b",
        "albuterol_svn": r"\balbuterol\b|\bsvn\b|\bnebuliz",
        "albuterol_mdi": r"\balbuterol\b|\bmdi\b|\binhaler\b",
        "epinephrine_im": r"\bepi(?:nephrine)?\b|\bintramuscular\b|\bim\b",
        "naloxone_in": r"\bnaloxone\b|\bnarcan\b|\bintranasal\b|\bin\b",
        "aspirin": r"\baspirin\b|\basa\b",
        "position_of_comfort": r"\bposition of comfort\b|\bupright\b|\bsitting\b|\btripod\b",
        "smr": r"\bsmr\b|\bspinal motion\b|\bc[- ]?spine\b|\bcervical\b|\bcollar\b|\bbackboard\b|\bin[- ]?line\b|\bmanual stabilization\b|\bhealthy spine\b",
    }
    for iid, pattern in intervention_patterns.items():
        if iid in applied_intervention_ids and re.search(pattern, normalized):
            applied_hits.append(iid)
    matched.extend([f"applied:{iid}" for iid in applied_hits if f"applied:{iid}" not in matched])
    transport_hit = re.search(r"\bals\b|\bmedic\b|\btransport\b|\bhandoff\b|\bturnover\b|\bhospital\b|\bed\b", normalized)
    response_hit = re.search(r"\bimprov(?:ed|ing|ement)?\b|\bresponse\b|\bcame up\b|\bafter\b|\bsp\s*o2\s*(?:came|went|improved|up)", normalized)
    if transport_hit:
        matched.append("transport/turnover plan")
    if response_hit:
        matched.append("treatment response")
    if required:
        required_without_disposition = [
            item for item in required
            if not re.search(r"\b(?:als|transport|disposition|handoff|turnover|hospital|ed)\b", str(item), re.IGNORECASE)
        ]
        effective_total = len(required_without_disposition) or len(required)
        score = _score_from_counts(required_matched_count, effective_total)
        if flags and score > 1:
            score = 1
    else:
        if (applied_hits and response_hit) or transport_hit:
            score = 2
        elif applied_hits:
            score = 1
        else:
            score = 0
    return DmistComponentScore(
        "T",
        DMIST_COMPONENT_MEANINGS["T"],
        score,
        matched=list(dict.fromkeys(matched)),
        missing=list(dict.fromkeys(missing)),
        flags=list(dict.fromkeys(flags)),
    )


def score_dmist(
    dmist_text: str,
    *,
    scenario: dict[str, Any],
    applied_intervention_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    findings: list[Any] | None = None,
    turnover_target: str | None = None,
) -> DmistScoreResult:
    """Score a DMIST report using the corrected D/M/I/S/T meanings.

    The function is deterministic and conservative. It returns a score object
    suitable for shadow comparison before score authority is flipped.
    """
    text = str(dmist_text or "").strip()
    target = turnover_target or scenario.get("turnover_target")
    applicable = target in ("als", "hospital", "dynamic", None)
    if not applicable:
        return DmistScoreResult(score=0, max_score=0, components={}, applicable=False)
    if not text:
        components = {
            comp: DmistComponentScore(comp, meaning, 0, missing=["no DMIST submitted"])
            for comp, meaning in DMIST_COMPONENT_MEANINGS.items()
        }
        return DmistScoreResult(score=0, max_score=10, components=components)

    sections = segment_dmist(text)
    components_cfg = ((scenario.get("scoring") or {}).get("dmist_components") or {})
    patient = scenario.get("patient") or {}
    applied_ids = set(applied_intervention_ids or [])
    findings = findings or []

    scores: dict[str, DmistComponentScore] = {}
    scores["D"] = _score_demographics(sections["D"], patient)

    for comp in ("M", "I"):
        cfg = components_cfg.get(comp) if isinstance(components_cfg.get(comp), dict) else {}
        required = list(cfg.get("required_elements") or [])
        if comp == "I" and _is_legacy_intervention_i_config(cfg):
            score = _generic_component_score(sections[comp], comp)
            score.flags.append("legacy_intervention_i_config_ignored")
            scores[comp] = score
            continue
        if required:
            matched, missing = _score_required_elements(sections[comp], required)
            scores[comp] = DmistComponentScore(
                comp,
                DMIST_COMPONENT_MEANINGS[comp],
                _score_from_counts(len(matched), len(required)),
                matched=matched,
                missing=missing,
            )
        else:
            scores[comp] = _generic_component_score(sections[comp], comp)

    scores["S"] = _score_signs(sections["S"], components_cfg.get("S") or {}, findings)
    scores["T"] = _score_treatment_transport(sections["T"], components_cfg.get("T") or {}, applied_ids)

    total = sum(component.score for component in scores.values())
    return DmistScoreResult(score=total, max_score=10, components=scores)
