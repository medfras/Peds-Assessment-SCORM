import json
from pathlib import Path

from app.minigame_metadata import get_allowed_minigame_ids, get_minigame_metadata


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def _read_json(path: str):
    return json.loads(_read(path))


def test_rule_of_nines_data_has_body_map_and_followup_contract():
    data = _read_json("static/data/games/rule_of_nines/game.json")
    regions = data["regions"]
    vignettes = data["vignettes"]
    region_ids = {region["id"] for region in regions}

    assert len(regions) >= 8
    assert sum(int(region["percent"]) for region in regions) == 100
    assert data["pediatric_notes"]
    assert len(vignettes) >= 6
    for vignette in vignettes:
        assert vignette["id"].startswith("rule9_")
        assert vignette.get("prompt")
        assert set(vignette["answer_regions"]).issubset(region_ids)
        assert vignette.get("hint")
        assert vignette.get("explanation")
        assert vignette.get("mistake_tag")
        follow_up = vignette["follow_up"]
        assert follow_up.get("prompt")
        assert follow_up.get("correct")
        assert len(follow_up.get("distractors", [])) >= 3
        assert follow_up.get("explanation")


def test_rule_of_nines_metadata_is_authoritative_allowed_game():
    metadata = get_minigame_metadata("rule_of_nines")

    assert "rule_of_nines" in get_allowed_minigame_ids()
    assert metadata is not None
    assert metadata["display_name"] == "Rule of Nines"
    assert metadata["reference_card"]["id"] == "ref_rule_of_nines"
    assert metadata["reference_card"]["related_game_ids"] == ["rule_of_nines"]
    assert "clinical_performance" in metadata["rubric_category_mapping"]
    assert "protocols_treatment" in metadata["rubric_category_mapping"]
    assert metadata["hint_policy"]


def test_rule_of_nines_frontend_wiring_and_gateway_replacement():
    html = _read("static/index.html")
    js = _read("static/js/app.js")
    main_py = _read("app/main.py")

    assert 'id="screen-rule-of-nines-game"' in html
    assert 'id="rule9-body-svg"' in html
    assert 'id="rule9-region-grid"' in html
    assert 'id="rule9-percent-bottom"' in html
    assert 'id="btn-rule9-submit-bsa"' in html
    assert 'id="rule9-followup-choices"' in html
    assert 'type: "rule_of_nines"' in js and '"Rule of Nines"' in js
    assert "class BodyMapGame" in js
    assert "const _rule9Game = new BodyMapGame({" in js
    assert 'dataUrl: "/static/data/games/rule_of_nines/game.json"' in js
    assert "_allowedRegionValues() { return [0, 1, 9, 18]; }" in js
    assert "Not quite. Try again" in js
    assert "Correct BSA estimate" in js
    assert 'if (selection.type === "rule_of_nines")' in js
    assert '"rule_of_nines":        _openRule9GameScreen' in js
    assert '"/static/data/games/rule_of_nines/learning_page.md"' in js
    assert '"rule_of_nines":        {"title": "Rule of Nines"' in main_py
    assert 'body.game_id == "rule_of_nines" and score >= _MINIGAME_LEARNING_PASSING_SCORE' in main_py
    assert "PT1 is gated by rule_of_nines which is still a placeholder" not in js
    assert "currentMapId === \"pt1\"" not in js


def test_phase12_rule_of_nines_checklist_is_closed():
    doc = _read("docs/MINIGAMES_DESIGN.md")

    assert "- [x] **Author game data**" in doc
    assert "- [x] **Implement `BodyMapGame` engine**" in doc
    assert "- [x] **Wire PT1 gateway and remove auto-complete placeholder**" in doc
