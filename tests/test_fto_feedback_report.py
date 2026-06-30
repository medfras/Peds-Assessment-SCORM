from scripts.fto_feedback_report import (
    _html_doc,
    _normalize_debrief_markdown_for_report,
    _professionalism_cues,
)


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


def test_professionalism_cues_do_not_treat_action_statement_as_intro():
    cues = dict(_professionalism_cues({
        "transcript": [
            {"role": "user", "content": "I am preparing a nasal cannula for oxygen administration."},
            {"role": "user", "content": "2 lpm"},
        ]
    }))

    assert cues["Greeting or self-introduction"] is False
    assert cues["Explained actions or care plan"] is True


def test_professionalism_cues_detect_agency_abbreviation_intro():
    cues = dict(_professionalism_cues({
        "transcript": [
            {"role": "user", "content": "hi im allison from pfd"},
        ]
    }))

    assert cues["Greeting or self-introduction"] is True
    assert cues["Agency or responder-role introduction"] is True


def test_professionalism_cues_detect_past_tense_treatment_explanation():
    cues = dict(_professionalism_cues({
        "transcript": [
            {"role": "user", "content": "he seems to be having another asthma attack, we gave him some albuterol. Does he usually keep some at home?"},
        ]
    }))

    assert cues["Explained actions or care plan"] is True
    assert cues["Addressed caregiver/family"] is True


def test_report_missed_points_styles_force_dark_text():
    result = _html_doc([])

    assert ".deduction-row p" in result
    assert "color:#030712 !important" in result
    assert ".deduction-list li strong" in result
