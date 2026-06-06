import json
from pathlib import Path

from app.minigame_metadata import get_allowed_minigame_ids, get_minigame_metadata


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def _read_json(path: str):
    return json.loads(_read(path))


def test_shock_spotter_med_data_has_required_swipe_contract():
    cards = _read_json("static/data/games/shock_spotter_med/cards.json")
    decisions = {card["decision"] for card in cards}

    assert len(cards) >= 12
    assert decisions == {"compensated_shock", "decompensated_shock"}
    assert sum(1 for card in cards if card["decision"] == "compensated_shock") >= 5
    assert sum(1 for card in cards if card["decision"] == "decompensated_shock") >= 5
    assert any(card.get("follow_up") for card in cards)
    for card in cards:
        assert card["id"].startswith("shock_med_")
        assert card.get("prompt")
        assert card.get("bucket")
        assert card.get("explanation")
        assert card.get("mistake_tag")
        assert card.get("hint")


def test_shock_spotter_med_metadata_is_authoritative_allowed_game():
    metadata = get_minigame_metadata("shock_spotter_med")

    assert "shock_spotter_med" in get_allowed_minigame_ids()
    assert metadata is not None
    assert metadata["display_name"] == "Shock Spotter: Medical"
    assert metadata["reference_card"]["id"] == "ref_shock_spotter_medical"
    assert metadata["reference_card"]["related_game_ids"] == ["shock_spotter_med"]
    assert "clinical_performance" in metadata["rubric_category_mapping"]
    assert metadata["hint_policy"]


def test_shock_spotter_med_frontend_wiring_and_map_node():
    html = _read("static/index.html")
    js = _read("static/js/app.js")
    main_py = _read("app/main.py")

    assert 'id="screen-shockmed-game"' in html
    assert 'id="btn-shockmed-start"' in html
    assert '{ id: "shock_spotter_med",    label: "Shock Spotter Med"' in js
    assert 'gameId:       "shock_spotter_med"' in js
    assert 'cardsUrl:     "/static/data/games/shock_spotter_med/cards.json"' in js
    assert 'if (selection.type === "shock_spotter_med")' in js
    assert '"shock_spotter_med":    _openShockMedGameScreen' in js
    assert '"/static/data/games/shock_spotter_med/learning_page.md"' in js
    assert '"shock_spotter_med":    {"title": "Shock Spotter: Medical"' in main_py


def test_phase11_shock_spotter_med_checklist_is_closed():
    doc = _read("docs/MINIGAMES_DESIGN.md")

    assert "- [x] **11.2 Shock Spotter Med PM3 (`shock_spotter_med`)" in doc
