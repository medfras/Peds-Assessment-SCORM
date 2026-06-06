from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def test_dev_sort_to_dev_flags_mastery_button_exists_and_is_wired():
    html = _read("static/index.html")
    js = _read("static/js/app.js")

    assert 'id="btn-sort-continue-red-flags"' in html
    assert 'el("btn-sort-continue-red-flags")?.classList.remove("hidden")' in js
    assert 'el("btn-sort-continue-red-flags")?.addEventListener("click"' in js
    assert "_openDfGameScreen()" in js


def test_lung_sounds_mastery_summary_is_visible_on_results():
    html = _read("static/index.html")

    assert "Mastery flow:" in html
    assert "audio identification and scope-appropriate intervention selection" in html


def test_notebook_reference_card_library_exists_and_fetches_endpoint():
    html = _read("static/index.html")
    js = _read("static/js/app.js")
    css = _read("static/css/style.css")

    assert 'id="nb-reference-card-list"' in html
    assert 'id="nb-reference-card-empty"' in html
    assert "/api/me/minigames/reference-cards" in js
    assert "_loadReferenceCardsForNotebook" in js
    assert "nb-reference-card--locked" in js
    assert ".nb-reference-card" in css


def test_phase10_checklist_is_closed():
    doc = _read("docs/MINIGAMES_DESIGN.md")

    for item in ("10.1", "10.2", "10.3", "10.4"):
        assert f"- [x] **{item}" in doc
