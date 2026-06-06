import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: str):
    return json.loads((ROOT / path).read_text())


def test_gcs_deck_has_ce_replay_depth_and_infant_cases():
    data = _read_json("static/data/games/peds_gcs_calculator/game.json")
    vignettes = data["vignettes"]

    assert len(vignettes) >= 8
    assert sum(1 for item in vignettes if item.get("type") == "infant") >= 3
    assert all(item.get("play_hint") for item in vignettes)


def test_gcs_media_v2_assets_require_license_and_non_label_prompts():
    data = _read_json("static/data/games/peds_gcs_calculator/game.json")
    prohibited = {
        "withdraws",
        "localizes",
        "abnormal flexion",
        "decorticate",
        "decerebrate",
        "m4",
        "m5",
    }

    for vignette in data["vignettes"]:
        media = vignette.get("media")
        if not media:
            continue
        assert media.get("type") in {"video", "audio", "image_sequence"}
        assert str(media.get("url", "")).strip(), f"{vignette['id']}: media.url required"
        assert str(media.get("license_source", "")).strip(), f"{vignette['id']}: license_source required"
        assert media.get("license_status") == "approved", f"{vignette['id']}: license_status must be approved"
        assert str(media.get("text_alternative", "")).strip(), f"{vignette['id']}: text_alternative required"
        assert media.get("prompt_quality_review") == "pass", f"{vignette['id']}: prompt_quality_review must pass"
        learner_visible = " ".join([
            str(media.get("url", "")),
            str(media.get("text_alternative", "")),
        ]).lower()
        leaked = [label for label in prohibited if label in learner_visible]
        assert not leaked, f"{vignette['id']}: media reveals scoring labels {leaked}"


def test_dmist_phase7_cases_have_required_structure():
    cases = _read_json("static/data/games/dmist_builder/cases.json")

    assert len(cases) >= 8
    for case in cases:
        elements = case["elements"]
        assert len(elements) == 12
        assert sum(1 for item in elements if item["inclusion"] == "required") >= 7
        assert sum(1 for item in elements if item["inclusion"] == "omit") == 2
        assert {1, 2, 3, 4, 5}.issubset({item["priority_band"] for item in elements})
        assert case.get("hint")


def test_protocol_pivot_phase7_cases_have_independent_acts():
    cases = _read_json("static/data/games/protocol_pivot/cases.json")

    assert len(cases) >= 8
    for case in cases:
        act1_choices = {choice["label"] for choice in case["act1"]["choices"]}
        act2_choices = {choice["label"] for choice in case["act2"]["choices"]}
        assert act1_choices
        assert act2_choices
        assert act1_choices.isdisjoint(act2_choices)
        assert any(choice.get("correct") is True for choice in case["act1"]["choices"])
        assert any(choice.get("correct") is True for choice in case["act2"]["choices"])
        assert case["act1"].get("hint")
        assert case["act2"].get("hint")


def test_unresolved_lsm_audio_cards_are_marked_uncleared():
    cards = _read_json("static/data/games/lsm/cards.json")
    unresolved = [card for card in cards if "UNRESOLVED" in card.get("license_source", "")]

    assert unresolved
    assert all(card.get("license_cleared") is False for card in unresolved)


def test_vitals_trend_cases_have_e2e_ready_static_chart_structure():
    cases = _read_json("static/data/games/vitals_trend/cases.json")

    assert len(cases) >= 3
    for case in cases:
        assert str(case.get("id", "")).strip()
        assert case.get("duration_sec", 0) > 0
        assert len(case.get("data_points", [])) >= 4
        assert len(case.get("event_window_ms", [])) == 2
        assert case["event_window_ms"][0] < case["event_window_ms"][1]
        assert set(case.get("channels", [])).issubset({"hr", "spo2", "rr", "bp_sys"})
        assert case.get("etiology_question")
        assert any(choice.get("correct") for choice in case.get("etiology_choices", []))
        assert case.get("response_question")
        assert any(choice.get("correct") for choice in case.get("response_choices", []))
        feedback = case.get("feedback", {})
        assert feedback.get("timeline")
        assert feedback.get("etiology")
        assert feedback.get("response")
        assert case.get("hint")


def test_phase13_vitals_playback_and_gcs_media_hooks_are_wired():
    html = Path("static/index.html").read_text()
    js = Path("static/js/app.js").read_text()

    assert 'id="btn-vitals-playback"' in html
    assert 'id="btn-vitals-pause"' in html
    assert 'id="btn-vitals-replay"' in html
    assert "playTrend()" in js
    assert "pauseTrend()" in js
    assert "replayTrend()" in js

    assert 'id="gcs-media"' in html
    assert "_renderMedia(vignette)" in js
    assert 'media.license_status === "approved"' in js
    assert 'media.prompt_quality_review === "pass"' in js


def test_gcs_wrong_submission_retries_without_evm_answer_reveal():
    js = Path("static/js/app.js").read_text()

    assert "const correct = e === v.correct.e && verb === v.correct.v && m === v.correct.m;" in js
    assert 'verdictEl.textContent = "Not quite. Try again.";' in js
    assert "The answer reveal appears after all three components are correct." in js
    wrong_branch = js.split("if (!correct) {", 1)[1].split("return;", 1)[0]
    assert "this._renderSections(v, true)" not in wrong_branch
    assert "v.hint" not in wrong_branch
