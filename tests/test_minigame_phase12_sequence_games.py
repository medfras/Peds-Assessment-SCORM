import json
from pathlib import Path

from app.minigame_metadata import get_allowed_minigame_ids, get_minigame_metadata


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def _read_json(path: str):
    return json.loads(_read(path))


SEQUENCE_GAMES = {
    "stop_the_bleed": {
        "path": "static/data/games/stop_the_bleed/cases.json",
        "min_cases": 5,
        "ref": "ref_stop_the_bleed",
        "screen": "screen-stop-bleed-game",
        "prefix": "stopbleed",
        "label": "Stop the Bleed",
    },
    "bls_sequence": {
        "path": "static/data/games/bls_sequence/cases.json",
        "min_cases": 3,
        "ref": "ref_bls_sequence",
        "screen": "screen-bls-sequence-game",
        "prefix": "blsseq",
        "label": "BLS Sequence",
    },
    "priority_stack": {
        "path": "static/data/games/priority_stack/cases.json",
        "min_cases": 4,
        "ref": "ref_priority_stack",
        "screen": "screen-priority-stack-game",
        "prefix": "prioritystack",
        "label": "Priority Stack",
    },
}


def test_phase12_sequence_data_contracts():
    for game_id, cfg in SEQUENCE_GAMES.items():
        data = _read_json(cfg["path"])
        cases = data["cases"]
        assert len(cases) >= cfg["min_cases"]
        for case in cases:
            step_ids = {step["id"] for step in case["steps"]}
            assert case.get("prompt")
            assert case.get("hint")
            assert case.get("explanation")
            assert case.get("mistake_tag")
            assert len(case["steps"]) >= 5
            assert len(case["correct_order"]) == len(case["steps"])
            assert set(case["correct_order"]) == step_ids
            assert len(case["correct_order"]) == len(set(case["correct_order"])), game_id


def test_phase12_sequence_metadata_is_authoritative():
    allowed = get_allowed_minigame_ids()

    for game_id, cfg in SEQUENCE_GAMES.items():
        metadata = get_minigame_metadata(game_id)
        assert game_id in allowed
        assert metadata is not None
        assert metadata["reference_card"]["id"] == cfg["ref"]
        assert metadata["reference_card"]["related_game_ids"] == [game_id]
        assert metadata["hint_policy"]
        assert "clinical_performance" in metadata["rubric_category_mapping"]


def test_phase12_sequence_frontend_wiring():
    html = _read("static/index.html")
    js = _read("static/js/app.js")
    main_py = _read("app/main.py")

    assert "class SequenceOrderGame" in js
    assert "full order, then submit" in js
    for game_id, cfg in SEQUENCE_GAMES.items():
        prefix = cfg["prefix"]
        assert f'id="{cfg["screen"]}"' in html
        assert f'id="{prefix}-bank"' in html
        assert f'id="{prefix}-order"' in html
        assert f'id="btn-{prefix}-submit"' in html
        assert f'game: {{ id: "{game_id}", label: "{cfg["label"]}"' in js
        assert f'gameId: "{game_id}"' in js
        assert f'if (selection.type === "{game_id}")' in js
        assert f'"/static/data/games/{game_id}/learning_page.md"' in js
        assert f'"{game_id}":' in main_py

    assert "_ph_stop_bleed" not in js
    assert "_ph_bls_seq" not in js
    assert "_ph_priority_stack" not in js


def test_phase13_dmist_sequence_scoring_frontend_wiring():
    html = _read("static/index.html")
    js = _read("static/js/app.js")

    assert 'id="dmist-sequence"' in html
    assert "_renderSequence(kase)" in js
    assert "_submitSequence()" in js
    assert "handoff_sequence" in js
    assert "sequenceData: { cases: sequenceRecords || [] }" in js


def test_phase12_sequence_checklist_is_closed():
    doc = _read("docs/MINIGAMES_DESIGN.md")

    assert "- [x] **Author escalation sequence data**" in doc
    assert "- [x] **Implement scored-order escalation mode**" in doc
    assert "- [x] **Author sequence data**" in doc
    assert "- [x] **Implement ranked-list scored-order mode**" in doc
    assert "- [x] **Author ranked-list synthesis data**" in doc
    assert "- [x] **Implement `PriorityStackGame`**" in doc
