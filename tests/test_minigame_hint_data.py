import json
from pathlib import Path


def _read_json(path: str):
    return json.loads(Path(path).read_text())


def _assert_all_have_text(items, key: str):
    missing = [item.get("id", "<unknown>") for item in items if not str(item.get(key, "")).strip()]
    assert not missing, f"Missing {key}: {missing}"


def test_card_based_games_have_non_answer_hints():
    _assert_all_have_text(_read_json("static/data/games/ap/cards.json"), "hint")
    _assert_all_have_text(_read_json("static/data/games/dev_red_flags/cards.json"), "hint")
    _assert_all_have_text(_read_json("static/data/games/lsm/cards.json"), "hint")
    _assert_all_have_text(_read_json("static/data/games/history/game.json")["pairs"], "hint")


def test_ams_pair_match_pairs_have_hints():
    data = _read_json("static/data/games/ams_aeioutips/game.json")
    _assert_all_have_text(data["pairs"], "hint")


def test_gcs_vignettes_have_play_hints_separate_from_answer_reveal():
    data = _read_json("static/data/games/peds_gcs_calculator/game.json")
    _assert_all_have_text(data["vignettes"], "play_hint")


def test_case_based_games_have_hints():
    _assert_all_have_text(_read_json("static/data/games/dmist_builder/cases.json"), "hint")
    _assert_all_have_text(_read_json("static/data/games/history/interview_builder.json")["cases"], "hint")
    _assert_all_have_text(_read_json("static/data/games/history/vignettes.json"), "hint")
    _assert_all_have_text(_read_json("static/data/games/vitals_trend/cases.json"), "hint")

    pivot_cases = _read_json("static/data/games/protocol_pivot/cases.json")
    missing = [
        case.get("id", "<unknown>")
        for case in pivot_cases
        if not str(case.get("act1", {}).get("hint", "")).strip()
        or not str(case.get("act2", {}).get("hint", "")).strip()
    ]
    assert not missing, f"Missing pivot act hints: {missing}"
