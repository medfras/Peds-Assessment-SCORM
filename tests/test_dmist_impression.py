from app.dmist_utils import extract_primary_impression_from_dmist


def test_extract_primary_impression_from_dmist_m_line():
    report = """D — Marcus, 8-year-old male.
M — Severe hypoglycemia / diabetic emergency after PE and missed snack.
I — Oral glucose given.
S — GCS improving.
T — ALS handoff."""

    assert (
        extract_primary_impression_from_dmist(report)
        == "Severe hypoglycemia / diabetic emergency after PE and missed snack."
    )


def test_extract_primary_impression_from_dmist_supports_plain_cue():
    report = "Patient is an 8-year-old male. Working diagnosis is severe hypoglycemia after missed snack."

    assert extract_primary_impression_from_dmist(report) == "severe hypoglycemia after missed snack"


def test_extract_primary_impression_from_dmist_supports_plain_chief_complaint_phrase():
    report = "This is Chloe, six month old female with an active seizure upon arrival."

    assert extract_primary_impression_from_dmist(report) == "an active seizure upon arrival"


def test_extract_primary_impression_from_dmist_returns_none_for_empty_report():
    assert extract_primary_impression_from_dmist("  ") is None
