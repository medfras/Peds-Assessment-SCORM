import json
from pathlib import Path


def _read_json(path: str):
    return json.loads(Path(path).read_text())


def test_history_foundation_uses_pair_match_contract():
    data = _read_json("static/data/games/history/game.json")

    assert data["rounds"] == 4
    assert data["pairs_per_round"] == 3
    assert len(data["pairs"]) == data["rounds"] * data["pairs_per_round"]

    labels = [pair["category_label"] for pair in data["pairs"]]
    findings = [pair["finding"] for pair in data["pairs"]]

    assert len(labels) == len(set(labels))
    assert len(findings) == len(set(findings))
    assert all(pair.get("hint") for pair in data["pairs"])
    assert all(pair.get("explanation") for pair in data["pairs"])


def test_history_foundation_pairmatch_wired_to_two_round_flow():
    js = Path("static/js/app.js").read_text()
    html = Path("static/index.html").read_text()

    assert "_hmEngine = new PairMatchGame({" in js
    assert 'dataUrl: "/static/data/games/history/game.json"' in js
    assert 'resultMode: "foundation"' in js
    assert "btn-hm-continue-interview" in html
    assert "Start Round 2: History Maker" in html
