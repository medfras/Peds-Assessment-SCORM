import json
from pathlib import Path

from app.minigame_metadata import get_allowed_minigame_ids, get_minigame_metadata


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def _read_json(path: str):
    return json.loads(_read(path))


def test_diff_dash_resp_data_has_pair_match_contract():
    data = _read_json("static/data/games/diff_dash_resp/game.json")
    pairs = data["pairs"]

    assert data["rounds"] == 4
    assert data["pairs_per_round"] == 3
    assert len(data["round_nudges"]) >= 3
    assert len(pairs) >= 12
    assert len({pair["category_id"] for pair in pairs}) == len(pairs)
    assert {"asthma_bronchospasm", "croup", "pneumonia", "anaphylaxis"}.issubset(
        {pair["category_id"] for pair in pairs}
    )
    for pair in pairs:
        assert pair["id"].startswith("resp_dd_")
        assert pair.get("category_letter")
        assert pair.get("category_label")
        assert pair.get("finding")
        assert pair.get("explanation")
        assert pair.get("hint")


def test_diff_dash_resp_findings_are_unambiguous_for_pair_matching():
    data = _read_json("static/data/games/diff_dash_resp/game.json")
    findings = [pair["finding"].lower() for pair in data["pairs"]]

    # PairMatch boards need 1:1 cue-category relationships. These terms are
    # useful clinically, but repeated as bare findings they create multiple
    # plausible category matches in the same round.
    assert sum("stridor" in finding for finding in findings) <= 1
    assert sum("wheez" in finding for finding in findings) <= 1


def test_diff_dash_resp_metadata_is_authoritative_allowed_game():
    metadata = get_minigame_metadata("diff_dash_resp")

    assert "diff_dash_resp" in get_allowed_minigame_ids()
    assert metadata is not None
    assert metadata["display_name"] == "Differential Dash: Respiratory"
    assert metadata["reference_card"]["id"] == "ref_respiratory_differential_dash"
    assert metadata["reference_card"]["related_game_ids"] == ["diff_dash_resp"]
    assert "protocols_treatment" in metadata["rubric_category_mapping"]
    assert metadata["hint_policy"]


def test_diff_dash_resp_frontend_wiring():
    html = _read("static/index.html")
    js = _read("static/js/app.js")
    main_py = _read("app/main.py")

    assert 'id="screen-diffresp-game"' in html
    assert 'id="diffresp-pair-grid"' in html
    assert 'game: { id: "diff_dash_resp"' in js
    assert 'const _diffRespGame = new PairMatchGame({' in js
    assert 'prefix: "diffresp"' in js
    assert 'gameId: "diff_dash_resp"' in js
    assert 'dataUrl: "/static/data/games/diff_dash_resp/game.json"' in js
    assert 'if (selection.type === "diff_dash_resp")' in js
    assert '"diff_dash_resp":       _openDiffRespGameScreen' in js
    assert '"/static/data/games/diff_dash_resp/learning_page.md"' in js
    assert '"diff_dash_resp":       {"title": "Differential Dash: Respiratory"' in main_py


def test_phase11_diff_dash_resp_checklist_is_closed():
    doc = _read("docs/MINIGAMES_DESIGN.md")

    assert "- [x] **11.4 Differential Dash Resp PM5 (`diff_dash_resp`)" in doc
