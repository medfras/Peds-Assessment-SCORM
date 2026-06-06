import json
from pathlib import Path

from app.minigame_metadata import get_allowed_minigame_ids, get_minigame_metadata


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def _read_json(path: str):
    return json.loads(_read(path))


def test_moi_mapper_data_has_required_swipe_contract():
    cards = _read_json("static/data/games/moi_mapper/cards.json")
    decisions = {card["decision"] for card in cards}

    assert len(cards) >= 12
    assert decisions == {"high_risk_moi", "focused_assessment"}
    assert sum(1 for card in cards if card["decision"] == "high_risk_moi") >= 8
    assert any(card["decision"] == "focused_assessment" for card in cards)
    for card in cards:
        assert card["id"].startswith("moi_")
        assert card.get("prompt")
        assert card.get("bucket")
        assert card.get("explanation")
        assert card.get("mistake_tag")
        assert card.get("hint")


def test_shock_spotter_trauma_data_has_required_swipe_contract():
    cards = _read_json("static/data/games/shock_spotter_trauma/cards.json")
    decisions = {card["decision"] for card in cards}

    assert len(cards) >= 12
    assert decisions == {"compensated_shock", "decompensated_shock"}
    assert sum(1 for card in cards if card["decision"] == "compensated_shock") >= 5
    assert sum(1 for card in cards if card["decision"] == "decompensated_shock") >= 5
    for card in cards:
        assert card["id"].startswith("shock_trauma_")
        assert card.get("prompt")
        assert card.get("bucket")
        assert card.get("explanation")
        assert card.get("mistake_tag")
        assert card.get("hint")


def test_temp_check_data_has_required_vignette_contract():
    cases = _read_json("static/data/games/temp_check/cases.json")

    assert len(cases) >= 8
    for case in cases:
        choices = [case["correct"], *case.get("distractors", [])]
        assert case["id"].startswith("temp_")
        assert case.get("prompt")
        assert case["correct"] in choices
        assert len(choices) >= 4
        assert len(set(choices)) == len(choices)
        assert case.get("explanation")
        assert case.get("mistake_tag")
        assert case.get("hint")


def test_phase11_closeout_metadata_is_authoritative():
    expected = {
        "moi_mapper": "ref_moi_mapper",
        "shock_spotter_trauma": "ref_shock_spotter_trauma",
        "temp_check": "ref_temperature_emergency_care",
    }

    allowed = get_allowed_minigame_ids()
    for game_id, ref_id in expected.items():
        metadata = get_minigame_metadata(game_id)
        assert game_id in allowed
        assert metadata is not None
        assert metadata["reference_card"]["id"] == ref_id
        assert "clinical_performance" in metadata["rubric_category_mapping"]
        assert "protocols_treatment" in metadata["rubric_category_mapping"]
        assert metadata["hint_policy"]
        assert metadata["reference_card"]["field_examples"]


def test_phase11_closeout_frontend_wiring_and_learning_routes():
    html = _read("static/index.html")
    js = _read("static/js/app.js")
    main_py = _read("app/main.py")

    for screen_id in ("screen-moi-game", "screen-shocktrauma-game", "screen-temp-game"):
        assert f'id="{screen_id}"' in html

    assert 'game: { id: "moi_mapper"' in js
    assert 'game: { id: "shock_spotter_trauma"' in js
    assert 'game: { id: "temp_check"' in js
    assert 'const _moiEngine = new SwipeGameEngine({' in js
    assert 'const _shockTraumaEngine = new SwipeGameEngine({' in js
    assert 'const _tempEngine = new TapChoiceGame({' in js
    assert 'gameId: "moi_mapper"' in js
    assert 'gameId: "shock_spotter_trauma"' in js
    assert 'gameId: "temp_check"' in js
    assert 'cardsUrl: "/static/data/games/moi_mapper/cards.json"' in js
    assert 'cardsUrl: "/static/data/games/shock_spotter_trauma/cards.json"' in js
    assert 'cardsUrl: "/static/data/games/temp_check/cases.json"' in js

    assert 'if (selection.type === "moi_mapper")' in js
    assert 'if (selection.type === "shock_spotter_trauma")' in js
    assert 'if (selection.type === "temp_check")' in js
    assert '"moi_mapper":           _openMoiGameScreen' in js
    assert '"shock_spotter_trauma": _openShockTraumaGameScreen' in js
    assert '"temp_check":           _openTempGameScreen' in js
    assert '"/static/data/games/moi_mapper/learning_page.md"' in js
    assert '"/static/data/games/shock_spotter_trauma/learning_page.md"' in js
    assert '"/static/data/games/temp_check/learning_page.md"' in js

    assert '"moi_mapper":           {"title": "MOI Mapper"' in main_py
    assert '"shock_spotter_trauma": {"title": "Shock Spotter: Trauma"' in main_py
    assert '"temp_check":           {"title": "Temp Check"' in main_py


def test_map_game_nodes_use_generic_preview_fallback_for_new_games():
    js = _read("static/js/app.js")

    assert 'if (gid && !gid.startsWith("_ph")) { _openMgPreview(gid, g?.label || "Training Drill"); return; }' in js
    for game_id in (
        "dev_flags",
        "dmist_builder",
        "protocol_pivot",
        "vitals_trend_spotter",
        "diff_dash_ams",
        "diff_dash_resp",
        "rule_of_nines",
        "stop_the_bleed",
        "bls_sequence",
        "priority_stack",
        "moi_mapper",
        "shock_spotter_trauma",
        "temp_check",
    ):
        assert f'id: "{game_id}"' in js or f'"{game_id}"' in js


def test_phase11_closeout_checklist_is_closed():
    doc = _read("docs/MINIGAMES_DESIGN.md")

    assert "- [x] **11.5 MOI Mapper PT4 (`moi_mapper`)" in doc
    assert "- [x] **11.6 Shock Spotter Trauma PT5 (`shock_spotter_trauma`)" in doc
    assert "- [x] **11.7 Temp Check PT7 (`temp_check`)" in doc
