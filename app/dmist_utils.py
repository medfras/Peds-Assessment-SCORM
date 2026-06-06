from __future__ import annotations

import re


def extract_primary_impression_from_dmist(report: str) -> str | None:
    """Best-effort deterministic extraction of the final impression from DMIST text.

    DMIST's M component carries mechanism of injury or chief complaint. The UI
    compares the early challenge answer with the final handoff impression, so
    do not leave that field blank just because an older client only submitted
    the free-text report.
    """
    text = (report or "").strip()
    if not text:
        return None

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        match = re.match(
            r"^(?:M|MOI|Mechanism|Chief Complaint|Nature of Illness|Mechanism/Chief Complaint)\s*(?:[-—:])\s*(.+)$",
            line,
            re.I,
        )
        if match:
            return match.group(1).strip()[:240] or None

    # Fallback for one-line handoffs: capture the phrase after a common
    # impression cue without invoking the LLM or moving authority out of code.
    match = re.search(
        r"\b(?:suspected|impression(?:\s+is)?|working\s+diagnosis(?:\s+is)?|appears\s+to\s+be|consistent\s+with)\s+([^.;\n]+)",
        text,
        re.I,
    )
    if match:
        return match.group(1).strip(" .;:-")[:240] or None

    chief_complaint = re.search(
        r"\b(?:with|for|complaint(?:\s+of)?|chief complaint(?:\s+of)?)\s+"
        r"((?:an?\s+)?(?:active\s+)?(?:seizure|febrile seizure|syncope|chest pain|"
        r"shortness of breath|difficulty breathing|altered mental status|overdose|trauma)[^.;\n]*)",
        text,
        re.I,
    )
    if chief_complaint:
        return chief_complaint.group(1).strip(" .;:-")[:240] or None

    return None
