import re
from collections.abc import Iterable, Mapping


def detection_match_is_confident(m: re.Match) -> bool:
    """Return True only if the regex match is specific enough to commit.

    Short matches can accidentally land inside longer words, so require whole-word
    context for those. Longer matches and multi-word phrase matches are trusted.
    """
    matched = m.group(0)
    if len(matched) >= 5:
        return True
    src = m.string
    start, end = m.span()
    before_ok = start == 0 or not src[start - 1].isalpha()
    after_ok = end >= len(src) or not src[end].isalpha()
    return before_ok and after_ok


_POPUP_INTERVENTION_ACTION_RE = re.compile(
    r"\b("
    r"administer|admin|give|apply|start|begin|initiate|deliver|place|put|"
    r"set\s*up|setup|prepare|perform|provide|use"
    r")\b",
    re.IGNORECASE,
)

_POPUP_INTERVENTION_PHRASE_RE = re.compile(
    r"\b("
    r"oral\s+glucose|glucose\s+gel|insta[-\s]?glucose|glutose|"
    r"supplemental\s+(?:o2|oxygen)|nasal\s+cannula|non[-\s]?rebreather|"
    r"\bnrb\b|\bcpap\b|\bbvm\b"
    r")\b",
    re.IGNORECASE,
)


def message_has_popup_intervention_intent(message: str) -> bool:
    """Return True when a message likely instructs a popup intervention.

    Popup interventions open treatment workflows. Assessment-only wording like
    "check blood glucose" or "give me vitals" should not surface treatment
    buttons just because it contains an overlapping clinical term.
    """
    msg = (message or "").lower()
    if not msg:
        return False
    if re.search(r"\bgive\s+(?:me|us)\b", msg):
        return False
    return bool(
        _POPUP_INTERVENTION_ACTION_RE.search(msg)
        or _POPUP_INTERVENTION_PHRASE_RE.search(msg)
    )


def detect_intervention_suggestions(
    message: str,
    already_applied: Iterable[str],
    interventions: Mapping[str, Mapping],
) -> list[dict]:
    """Return intervention confirmation chips for likely-but-unapplied actions."""
    applied = set(already_applied or [])
    msg_lower = (message or "").lower()
    suggestions = []
    popup_intervention_intent = message_has_popup_intervention_intent(msg_lower)

    for intervention_id, int_data in (interventions or {}).items():
        if intervention_id in applied:
            continue
        if int_data.get("unavailable_in_scenario"):
            continue
        patterns = int_data.get("detection_patterns", [])
        if not patterns:
            continue

        is_popup = bool(int_data.get("requires_popup", False))
        if is_popup and not popup_intervention_intent:
            continue

        for pattern in patterns:
            m = re.search(pattern, msg_lower)
            if not m:
                continue
            confident = detection_match_is_confident(m)
            if is_popup or not confident:
                suggestions.append({
                    "id": intervention_id,
                    "label": int_data.get("label", intervention_id),
                    "popup_type": int_data.get("popup_type"),
                })
                break

    return suggestions
