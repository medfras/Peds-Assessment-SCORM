from scripts.fto_feedback_report import _normalize_debrief_markdown_for_report


def test_report_normalizes_inline_feedback_sections_and_missed_bullets():
    raw = (
        "## What Went Well\n"
        "Direct pressure applied. - PAT completed. - Mechanism not assessed. "
        "- Vitals missing. ## Protocols & Treatments\n"
        "Reference: Michigan protocol\n"
        "✓ Direct pressure"
    )

    result = _normalize_debrief_markdown_for_report(raw)

    went_well, after_went_well = result.split("## What Could Be Better", 1)
    could_better, rest = after_went_well.split("## Protocols & Treatments", 1)
    assert "- Direct pressure applied." in went_well
    assert "- PAT completed." in went_well
    assert "- Mechanism not assessed." not in went_well
    assert "- Vitals missing." not in went_well
    assert "- Mechanism not assessed." in could_better
    assert "- Vitals missing." in could_better
    assert rest.startswith("\nReference: Michigan protocol")
