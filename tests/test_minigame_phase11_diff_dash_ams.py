import json
from pathlib import Path

from app.minigame_metadata import get_allowed_minigame_ids, get_minigame_metadata


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def _read_json(path: str):
    return json.loads(_read(path))


def test_diff_dash_ams_data_has_pair_match_contract():
    data = _read_json("static/data/games/diff_dash_ams/game.json")
    pairs = data["pairs"]

    assert data["rounds"] == 4
    assert data["pairs_per_round"] == 3
    assert data["completion_threshold"] == "any_submitted_run"
    assert len(data["round_nudges"]) >= 3
    assert len(pairs) >= 12
    assert len({pair["category_id"] for pair in pairs}) == len(pairs)
    for pair in pairs:
        assert pair["id"].startswith("ams_dd_")
        assert pair.get("category_letter")
        assert pair.get("category_label")
        assert pair.get("finding")
        assert pair.get("explanation")
        assert pair.get("hint")


def test_diff_dash_ams_metadata_is_authoritative_allowed_game():
    metadata = get_minigame_metadata("diff_dash_ams")

    assert "diff_dash_ams" in get_allowed_minigame_ids()
    assert metadata is not None
    assert metadata["display_name"] == "Differential Dash: AMS"
    assert metadata["reference_card"]["id"] == "ref_ams_differential_dash"
    assert metadata["reference_card"]["related_game_ids"] == ["diff_dash_ams"]
    assert "clinical_performance" in metadata["rubric_category_mapping"]
    assert metadata["hint_policy"]


def test_diff_dash_ams_frontend_wiring_and_pairmatch_generalization():
    html = _read("static/index.html")
    js = _read("static/js/app.js")
    main_py = _read("app/main.py")

    assert 'id="screen-diffams-game"' in html
    assert 'id="diffams-pair-grid"' in html
    assert 'game: { id: "diff_dash_ams"' in js
    assert 'const _diffAmsGame = new PairMatchGame({' in js
    assert 'prefix: "diffams"' in js
    assert 'gameId: "diff_dash_ams"' in js
    assert 'dataUrl: "/static/data/games/diff_dash_ams/game.json"' in js
    assert 'if (selection.type === "diff_dash_ams")' in js
    assert '"diff_dash_ams":        _openDiffAmsGameScreen' in js
    assert '"/static/data/games/diff_dash_ams/learning_page.md"' in js
    assert '"diff_dash_ams":        {"title": "Differential Dash: AMS"' in main_py


def test_phase11_diff_dash_ams_checklist_is_closed():
    doc = _read("docs/MINIGAMES_DESIGN.md")

    assert "- [x] **11.3 Differential Dash AMS PM4 (`diff_dash_ams`)" in doc
