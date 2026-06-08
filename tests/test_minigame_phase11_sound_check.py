import json
from pathlib import Path
from urllib.parse import unquote

from app.minigame_metadata import get_allowed_minigame_ids, get_minigame_metadata


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def _read_json(path: str):
    return json.loads(_read(path))


def test_sound_check_data_is_playable_and_licensed():
    cards = _read_json("static/data/games/sound_check/cards.json")

    assert len(cards) >= 8
    for card in cards:
        assert card["id"].startswith("sound_")
        assert card["license_cleared"] is True
        assert card.get("license_source")
        assert card.get("audio_url", "").startswith("/static/audio/")
        assert (ROOT / unquote(card["audio_url"].lstrip("/"))).exists()
        assert card.get("correct")
        assert card.get("distractors")
        assert card.get("hint")
        assert card.get("follow_up", {}).get("prompt")
        assert card.get("follow_up", {}).get("hint")
        assert card.get("follow_up", {}).get("mistake_tag")


def test_lung_sounds_matcher_audio_files_exist():
    cards = _read_json("static/data/games/lsm/cards.json")

    assert len(cards) >= 8
    for card in cards:
        assert card["id"].startswith("lsm_")
        assert card.get("license_source")
        assert card.get("audio_url", "").startswith("/static/audio/")
        assert (ROOT / unquote(card["audio_url"].lstrip("/"))).exists()
        assert card.get("correct")


def test_scenario_lung_sound_challenge_audio_files_exist():
    missing = []
    for path in (ROOT / "app/scenarios").rglob("*.json"):
        scenario = json.loads(path.read_text())

        def walk(value):
            if isinstance(value, dict):
                audio_file = value.get("audio_file")
                if isinstance(audio_file, str) and "/static/audio/lung sounds/" in audio_file:
                    if not (ROOT / unquote(audio_file.lstrip("/"))).exists():
                        missing.append(f"{path.relative_to(ROOT)}: {audio_file}")
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(scenario)

    assert missing == []


def test_sound_check_metadata_is_authoritative_allowed_game():
    metadata = get_minigame_metadata("sound_check")

    assert "sound_check" in get_allowed_minigame_ids()
    assert metadata is not None
    assert metadata["display_name"] == "Sound Check"
    assert metadata["reference_card"]["id"] == "ref_breath_sounds_actions"
    assert "sound_check" in metadata["reference_card"]["related_game_ids"]
    assert metadata["hint_policy"]


def test_sound_check_frontend_wiring_and_map_node():
    html = _read("static/index.html")
    js = _read("static/js/app.js")
    main_py = _read("app/main.py")

    assert 'id="screen-sound-game"' in html
    assert 'id="btn-sound-start"' in html
    assert 'game: { id: "sound_check"' in js
    assert 'gameId:       "sound_check"' in js
    assert 'cardsUrl:     "/static/data/games/sound_check/cards.json"' in js
    assert 'if (selection.type === "sound_check")' in js
    assert '"sound_check":          _openSoundGameScreen' in js
    assert '"/static/data/games/sound_check/learning_page.md"' in js
    assert '"sound_check":          {"title": "Sound Check: Breath Sounds"' in main_py


def test_phase11_sound_check_checklist_is_closed():
    doc = _read("docs/MINIGAMES_DESIGN.md")

    assert "- [x] **11.1 Sound Check PM2 (`sound_check`)" in doc
    assert "get_allowed_minigame_ids()" in doc
