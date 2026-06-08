import json
from pathlib import Path

from app.minigame_metadata import (
    REFERENCE_CARD_CONTENT,
    get_allowed_minigame_ids,
    get_minigame_metadata,
)

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def _read_json(path: str):
    return json.loads(_read(path))


# ── Data contract tests ────────────────────────────────────────────────────────

def test_cpr_bls_sequence_data_contract():
    data = _read_json("static/data/games/cpr_bls_sequence/cases.json")
    assert "cases" in data
    cases = data["cases"]
    assert len(cases) >= 3, "Need at least 3 CPR sequence cases"
    for case in cases:
        step_ids = {step["id"] for step in case["steps"]}
        assert case.get("prompt"), f"{case.get('id')}: missing prompt"
        assert case.get("hint"), f"{case.get('id')}: missing hint"
        assert case.get("explanation"), f"{case.get('id')}: missing explanation"
        assert case.get("mistake_tag") == "bls_sequence_error", (
            f"{case.get('id')}: mistake_tag must be 'bls_sequence_error'"
        )
        assert len(case["steps"]) >= 5, f"{case.get('id')}: need at least 5 steps"
        assert len(case["correct_order"]) == len(case["steps"])
        assert set(case["correct_order"]) == step_ids
        # no duplicate step IDs in correct_order
        assert len(case["correct_order"]) == len(set(case["correct_order"]))


def test_cpr_bls_concepts_data_contract():
    data = _read_json("static/data/games/cpr_bls_concepts/game.json")
    rounds = data.get("rounds", 0)
    ppr    = data.get("pairs_per_round", 0)
    assert rounds >= 3
    assert ppr >= 2
    pairs = data.get("pairs", [])
    assert len(pairs) >= 9, "Need at least 9 CPR concepts pairs"
    # All pairs must be shown in every playthrough — deck must not exceed capacity
    assert len(pairs) <= rounds * ppr, (
        f"Deck has {len(pairs)} pairs but config only shows {rounds * ppr} per game — "
        "safety-critical cards (adult/peds airway split) may be omitted. "
        "Increase rounds × pairs_per_round to cover the full deck."
    )

    for pair in pairs:
        assert pair.get("id"), "pair missing id"
        assert pair.get("category_id"), f"{pair.get('id')}: missing category_id"
        assert pair.get("category_label"), f"{pair.get('id')}: missing category_label"
        assert pair.get("finding"), f"{pair.get('id')}: missing finding"
        assert pair.get("explanation"), f"{pair.get('id')}: missing explanation"
        assert pair.get("hint"), f"{pair.get('id')}: missing hint"

    # action_cases must all carry the correct mistake_tag
    for ac in data.get("action_cases", []):
        assert ac.get("mistake_tag") == "cpr_metric_confusion", (
            f"{ac.get('id')}: action_case mistake_tag must be 'cpr_metric_confusion'"
        )

    pair_ids = [p["id"] for p in pairs]
    assert len(pair_ids) == len(set(pair_ids)), "Duplicate pair IDs in cpr_bls_concepts"


def test_cpr_bls_concepts_adult_peds_airway_split():
    """Adult and pediatric post-airway ventilation rates must be separate cards."""
    data = _read_json("static/data/games/cpr_bls_concepts/game.json")
    cat_ids = {p["category_id"] for p in data["pairs"]}
    assert "post_airway_rate_adult" in cat_ids, (
        "Missing adult post-airway card (post_airway_rate_adult)"
    )
    assert "post_airway_rate_peds" in cat_ids, (
        "Missing pediatric post-airway card (post_airway_rate_peds) — "
        "do not collapse adult and pediatric rates into one card"
    )
    # The old overgeneralized ID must not exist
    assert "post_airway_rate" not in cat_ids, (
        "Found overgeneralized 'post_airway_rate' card — must be split into "
        "post_airway_rate_adult and post_airway_rate_peds"
    )

    adult_pair = next(p for p in data["pairs"] if p["category_id"] == "post_airway_rate_adult")
    peds_pair  = next(p for p in data["pairs"] if p["category_id"] == "post_airway_rate_peds")
    assert "6 seconds" in adult_pair["category_label"] or "10/min" in adult_pair["category_label"]
    assert "2" in peds_pair["category_label"] or "20" in peds_pair["category_label"]


def test_cpr_bls_concepts_learning_page_covers_peds_airway():
    text = _read("static/data/games/cpr_bls_concepts/learning_page.md")
    assert "2–3 seconds" in text or "2-3 seconds" in text, (
        "learning_page.md must document the pediatric post-airway rate"
    )
    assert "20–30" in text or "20-30" in text
    assert "Chest compression fraction (CCF): greater than 80%" in text
    assert "score at least 4 out of 5" in text
    assert "AED analysis" in text
    assert "5-10 seconds" in text
    assert "Reversible Causes: Hs and Ts" in text
    assert "Hypovolemia" in text
    assert "Tension pneumothorax" in text


def test_cpr_bls_sequence_learning_page_covers_chain_and_peds_airway():
    text = _read("static/data/games/cpr_bls_sequence/learning_page.md")
    assert "Out-of-Hospital Chain of Survival" in text
    assert "1 breath every 2-3 sec" in text
    assert "Keep the total interruption under 10 seconds" in text
    assert "During AED analysis" in text
    assert "5-10 seconds" in text
    assert "Reversible Causes: Hs and Ts" in text
    assert "hypovolemia" in text
    assert "tension pneumothorax" in text


# ── Metadata tests ─────────────────────────────────────────────────────────────

def test_cpr_games_registered_in_allowed_ids():
    allowed = get_allowed_minigame_ids()
    assert "cpr_bls_sequence" in allowed
    assert "cpr_bls_concepts" in allowed


def test_cpr_games_pass_threshold_is_70():
    for game_id in ("cpr_bls_sequence", "cpr_bls_concepts"):
        meta = get_minigame_metadata(game_id)
        assert meta is not None
        pt = meta.get("pass_threshold") or {}
        assert pt.get("score_gte") == 70, (
            f"{game_id}: pass_threshold.score_gte must be 70 to align with mastery routing"
        )


def test_cpr_games_mastery_flow():
    seq = get_minigame_metadata("cpr_bls_sequence")
    assert seq["mastery_flow"] == {"previous": "cpr_bls_concepts", "next": "adult_cardiac_arrest_01_bls"}

    concepts = get_minigame_metadata("cpr_bls_concepts")
    assert concepts["mastery_flow"] == {"next": "cpr_bls_sequence"}


def test_cpr_games_reference_card():
    for game_id in ("cpr_bls_sequence", "cpr_bls_concepts"):
        meta = get_minigame_metadata(game_id)
        card = meta["reference_card"]
        assert card["id"] == "ref_aha_cpr_guide"
        assert "cpr_bls_sequence" in card["unlock_condition"]["all_passed"]
        assert "cpr_bls_concepts" in card["unlock_condition"]["all_passed"]


def test_ref_aha_cpr_guide_content():
    card = REFERENCE_CARD_CONTENT.get("ref_aha_cpr_guide")
    assert card is not None, "ref_aha_cpr_guide missing from REFERENCE_CARD_CONTENT"
    assert card.get("title")
    assert len(card.get("framework_summary", [])) >= 2
    assert len(card.get("common_traps", [])) >= 2
    assert len(card.get("field_examples", [])) >= 2
    assert "cpr_bls_sequence" in card.get("related_game_ids", [])
    assert "cpr_bls_concepts" in card.get("related_game_ids", [])


def test_cpr_games_have_hint_policy():
    for game_id in ("cpr_bls_sequence", "cpr_bls_concepts"):
        meta = get_minigame_metadata(game_id)
        assert meta.get("hint_policy"), f"{game_id}: hint_policy required"


# ── Frontend wiring tests ──────────────────────────────────────────────────────

def test_cpr_sequence_game_frontend_wiring():
    html = _read("static/index.html")
    js   = _read("static/js/app.js")

    # Screen exists with correct prefix elements
    assert 'id="screen-cpr-bls-sequence-game"' in html
    assert 'id="cprseq-bank"' in html
    assert 'id="cprseq-order"' in html
    assert 'id="btn-cprseq-submit"' in html

    # Drill result modals should not route learners directly into scenarios.
    assert 'id="btn-cprseq-round2"' not in html

    # JS registrations
    assert 'gameId: "cpr_bls_sequence"' in js
    assert 'if (selection.type === "cpr_bls_sequence")' in js
    assert '"cpr_bls_sequence"' in js  # _MG_TYPES
    assert 'cpr_bls_sequence: {' in js  # _MG_EDUCATION
    assert '"/static/data/games/cpr_bls_sequence/learning_page.md"' in js
    assert "_openCprBlsSequenceGameScreen" in js


def test_cpr_concepts_game_frontend_wiring():
    html = _read("static/index.html")
    js   = _read("static/js/app.js")

    # Screen exists with correct prefix elements
    assert 'id="screen-cpr-bls-concepts-game"' in html
    assert 'id="cprconcepts-pair-grid"' in html
    assert 'id="cprconcepts-results"' in html

    # Drill result modals should not route learners directly into scenarios.
    assert 'id="btn-cprconcepts-round3"' not in html

    # Nudge overlay wired
    assert 'id="cprconcepts-nudge-overlay"' in html
    assert 'btn-cprconcepts-nudge-continue' in html
    assert 'btn-cprconcepts-nudge-continue' in js

    # JS registrations
    assert 'gameId: "cpr_bls_concepts"' in js
    assert 'if (selection.type === "cpr_bls_concepts")' in js
    assert '"cpr_bls_concepts"' in js  # _MG_TYPES
    assert 'cpr_bls_concepts: {' in js  # _MG_EDUCATION
    assert '"/static/data/games/cpr_bls_concepts/learning_page.md"' in js
    assert "_openCprBlsConceptsGameScreen" in js
    assert "function _makeCprBlsConceptsGame()" in js
    assert "function _ensureCprBlsConceptsGame()" in js
    assert '_cprBlsConceptsGame = _makeCprBlsConceptsGame();' in js


def test_cpr_mastery_does_not_offer_scenario_routing_from_drill_results():
    """CPR mastery drills can be retried, but should not expose a scenario off-ramp."""
    js = _read("static/js/app.js")
    html = _read("static/index.html")

    assert 'btn-cprseq-round2' not in js
    assert 'btn-cprconcepts-round3' not in js
    assert "Round 3: CPR Scenario" not in html
    assert "Phase 2: CPR Scenario" not in html
    assert "const required = 4;" in js
    assert 'Score at least ${required}/${questionTotal} correct to unlock Phase 2' in js
    assert '_openCprBlsSequenceGameScreen' in js


def test_phase14_checklist_data_and_metadata_closed():
    doc = _read("docs/MINIGAMES_DESIGN.md")
    assert "- [x] **Author sequence and pair-match data**" in doc
    assert "- [x] **Wire the 3-Round Gauntlet routing**" in doc
    assert "- [x] **Register metadata and reference card**" in doc
    # Micro-scenario wrapper correctly left pending
    assert "- [ ] **Author micro-scenario wrapper**" in doc
