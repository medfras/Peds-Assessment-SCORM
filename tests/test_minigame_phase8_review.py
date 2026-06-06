from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def test_speed_game_review_panels_exist():
    html = _read("static/index.html")

    for prefix in ("pat", "ten4"):
        assert f'id="{prefix}-review"' in html
        assert f'id="{prefix}-review-list"' in html


def test_swipe_engine_collects_and_renders_missed_review():
    js = _read("static/js/app.js")

    assert "missedCards" in js
    assert "this._state.missedCards.push" in js
    assert "_renderMissedReview(this._state.missedCards || [])" in js
    assert "_socraticReviewText" in js
    assert "card.socratic_feedback" in js


def test_review_styles_are_available():
    css = _read("static/css/style.css")

    assert ".mg-review-panel" in css
    assert ".mg-review-card" in css
    assert ".mg-review-choice-line" in css
