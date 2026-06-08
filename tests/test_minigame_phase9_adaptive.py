import json
from pathlib import Path

from app.minigame_metadata import get_allowed_minigame_ids


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def _read_json(path: str):
    return json.loads(_read(path))


def test_lung_sounds_pilot_runs_audio_identification_only():
    cards = _read_json("static/data/games/lsm/cards.json")
    playable = [card for card in cards if card.get("license_cleared") is not False]

    assert playable
    # The authored data keeps intervention follow-ups for future expansion, but
    # the SCORM pilot Lung Sounds drill should not surface an intervention round.
    assert all(card.get("follow_up", {}).get("prompt") for card in playable)

    js = _read("static/js/app.js")
    assert 'gameId:       "lung_sounds_matcher"' in js
    lsm_block = js[js.index('gameId:       "lung_sounds_matcher"'):js.index("function _openLsmGameScreen")]
    assert "twoRoundInterventions: false" in lsm_block
    assert "follow_up:   null" in lsm_block
    assert "_renderInterventionCard(card)" in js
    assert "_submitInterventionChoice" in js
    assert 'mode: "audio_identification"' in lsm_block


def test_gcs_adaptive_vignettes_require_scale_inference():
    data = _read_json("static/data/games/peds_gcs_calculator/game.json")
    adaptive = [item for item in data["vignettes"] if item.get("tier") == "adaptive"]

    assert len(adaptive) >= 4
    assert {item["type"] for item in adaptive} == {"child", "infant"}
    assert all(item.get("infer_scale") is True for item in adaptive)
    assert all(item.get("play_hint") for item in adaptive)


def test_gcs_adaptive_engine_suppresses_explicit_scale_labels():
    js = _read("static/js/app.js")

    assert '_mgShouldUseAdaptiveMode("peds_gcs_calculator")' in js
    assert 'v.tier === "adaptive"' in js
    assert '"V — Verbal Response"' in js
    assert '"M — Motor Response"' in js


def test_drill_launch_routes_are_distinct_for_gcs_cpr_and_ams():
    js = _read("static/js/app.js")
    html = _read("static/index.html")

    expected_routes = {
        "peds_gcs_calculator": {
            "screen": 'id="screen-gcs-game"',
            "selection_route": 'if (selection.type === "peds_gcs_calculator")  { _openGcsGameScreen()',
            "intro_route": 'if (type === "peds_gcs_calculator")',
            "intro_button": 'id="btn-gcs-intro-play"',
            "engine_start": "_gcsGame.startRound()",
        },
        "ams_aeioutips": {
            "screen": 'id="screen-aeiou-game"',
            "selection_route": 'if (selection.type === "ams_aeioutips")',
            "intro_route": 'if (type === "ams_aeioutips")',
            "intro_button": 'id="btn-aeiou-intro-play"',
            "engine_start": "_aeiouGame.startRound()",
        },
        "cpr_bls_concepts": {
            "screen": 'id="screen-cpr-bls-concepts-game"',
            "selection_route": 'if (selection.type === "cpr_bls_concepts")',
            "intro_route": 'if (type === "cpr_bls_concepts")',
            "intro_button": 'id="btn-cprconcepts-intro-play"',
            "engine_start": "_cprBlsConceptsGame.startRound()",
        },
        "cpr_bls_sequence": {
            "screen": 'id="screen-cpr-bls-sequence-game"',
            "selection_route": 'if (selection.type === "cpr_bls_sequence")',
            "intro_route": 'if (type === "cpr_bls_sequence")',
            "intro_button": 'id="btn-cprseq-intro-play"',
            "engine_start": "_cprBlsSequenceGame.startRound()",
        },
    }

    for route in expected_routes.values():
        assert route["screen"] in html
        assert route["selection_route"] in js
        assert route["intro_route"] in js
        assert route["intro_button"] in html
        assert route["engine_start"] in js

    assert '<script src="/static/js/app.js?v=20260606-scorm-map-v3"></script>' in html


def test_orientation_treatment_repeats_med_control_prompt_until_logged():
    js = _read("static/js/app.js")

    assert "function _orientationCueFired(triggerKey)" in js
    assert "function _orientationMedControlLogged()" in js
    assert "function _orientationPromptForMedControlIfNeeded()" in js
    assert 'const shouldRepeatMedControlPrompt = _orientationCueFired("after_first_treatment") && !_orientationMedControlLogged();' in js
    assert 'if (shouldRepeatMedControlPrompt) _orientationPromptForMedControlIfNeeded();' in js
    assert "return () => _orientationMedControlLogged();" in js


def test_orientation_guidance_cues_do_not_advance_out_of_order():
    js = _read("static/js/app.js")

    assert "const ORIENTATION_ORDERED_CUE_TRIGGERS = [" in js
    assert "function _orientationBlockedCueReminder(triggerKey)" in js
    assert 'if (triggerKey === "after_first_treatment" && !_orientationCueFired("after_first_exam"))' in js
    assert 'return _orientationCueFired("after_first_vitals") ? "after_first_vitals" : "after_first_message";' in js
    assert "function _orientationRepeatCueToken(triggerKey)" in js
    assert 'if (trigger.startsWith("repeat:")) _orientationRepeatCue(trigger.slice("repeat:".length));' in js


def test_orientation_next_step_button_uses_readiness_gates():
    html = _read("static/index.html")
    js = _read("static/js/app.js")

    assert 'id="btn-orientation-next-step"' in html
    assert "function _orientationShowNextMissingStep()" in js
    assert "buildReadinessCriteria().map(c => ({ ...c, met: c.check() }))" in js
    assert "const nextMissing = results.find(r => !r.met);" in js
    assert "_orientationInjectMessage(_orientationGuideMessageForCriterion(nextMissing));" in js
    assert 'btnNextStep.classList.toggle("hidden", !state.scenarioData?.is_orientation);' in js


def test_drill_nodes_use_learning_glyph_and_drill_copy():
    html = _read("static/index.html")
    js = _read("static/js/app.js")

    assert 'placeholder="Search drills…"' in html
    assert '<div class="hv2-nav-icon">📚</div>' in html
    assert '<span class="tc-header-icon">📚</span>' in html
    assert 'const glyph = "📚";' in js
    assert '<span class="category-map-nav-ico">📚</span>' in js
    assert 'title: "Training Center"' in js
    assert "Replay unlocked drills by skill category." in js
    assert "Unlocked Replay Drills" in js
    assert "No replay drills unlocked yet." in js
    assert 'const glyph = g.gameType === "puzzle" ? "🧩" : "🎮";' not in js


def test_pat_text_only_cards_hide_image_placeholder_and_center_copy():
    js = _read("static/js/app.js")
    css = _read("static/css/style.css")
    cards = _read_json("static/data/games/pat/cards.json")

    assert all(card.get("mode") != "image" for card in cards)
    assert all(not card.get("image_url") for card in cards)
    assert all(not card.get("alt_text") for card in cards)

    assert 'imageShell?.classList.toggle("text-only", !hasImage);' in js
    assert 'fallbackEl?.classList.add("hidden");' in js
    assert ".pat-image-shell.text-only" in css
    assert ".pat-image-shell.text-only .pat-card-image" in css
    assert ".pat-image-shell.text-only .pat-overlay" in css
    start = css.index(".pat-image-shell.text-only .pat-overlay")
    end = css.index(".pat-phone-shell .pat-image-shell.text-only", start)
    text_only_block = css[start:end]
    assert "align-items: center;" in text_only_block
    assert "justify-content: center;" in text_only_block
    assert "text-align: center;" in text_only_block


def test_station1_cpr_training_node_is_labeled_as_drill():
    js = _read("static/js/app.js")

    assert 'title="CPR Training Drill" aria-label="CPR Training Drill"' in js
    assert "CPR training drill completed. Replay the three-round flow any time." in js
    assert 'startScenarioWithOptions(STATION1_CPR_SCENARIO_ID, {' in js
    assert "startDrill: true" in js
    assert 'drillSource: "station1_cpr_training"' in js
    assert "start_drill: startDrill" in js
    assert "drill_source: drillSource" in js
    assert "state.drillMode = startDrill;" in js
    assert "CPR Training Scenario" not in js
    assert "CPR training scenario completed" not in js


def test_station1_cpr_training_is_backend_marked_as_drill():
    main = _read("app/main.py")

    assert 'req.drill_source == "station1_cpr_training"' in main
    assert 'req.scenario_id != "adult_cardiac_arrest_01_bls"' in main
    assert "start_drill = True" in main
    assert 'if not bool((s.narrative_data or {}).get("drill"))' in main


def test_station1_cpr_drills_are_in_training_center_catalog():
    js = _read("static/js/app.js")

    assert 'id: "cardiac_cpr"' in js
    assert 'title: "Cardiac & CPR"' in js
    assert 'type: "cpr_bls_concepts"' in js
    assert 'type: "cpr_bls_sequence"' in js
    assert 'mapId: "station_1"' in js


def test_learner_challenge_details_render_drill_requirements():
    js = _read("static/js/app.js")

    assert "function _challengeDrillTitle" in js
    assert "const drillIds = Array.isArray(req.drill_ids) ? req.drill_ids : [];" in js
    assert "const completedDrillIds = new Set(Array.isArray(req.completed_drill_ids)" in js
    assert "...drillIds.map(id => {" in js
    assert "Completed drill" in js
    assert "No scenarios or drills listed for this requirement." in js
    assert "await _loadChallenges().then(_buildChallengesSection).catch(() => {});" in js
    assert "_loadChallenges().then(_buildChallengesSection).catch(() => {});" in js


def test_challenge_builder_lists_cpr_mastery_as_drills_not_scenarios():
    js = _read("static/js/app.js")

    assert 'id: "cpr_bls_concepts",     label: "CPR Mastery: Key Metrics"' in js
    assert 'id: "cpr_bls_sequence",     label: "CPR Mastery: Chain of Survival"' in js
    assert "function _challengeBuilderScenarios()" in js
    assert "STATION1_CPR_COMPLETION_IDS" in js
    assert "filter(s => !station1CprScenarioIds.has(String(s.id)))" in js
    assert "const scenarios = _challengeBuilderScenarios();" in js


def test_challenge_builder_exposes_drill_requirement_options():
    html = _read("static/index.html")
    js = _read("static/js/app.js")

    assert 'data-ch-add-req="drills"' in html
    assert 'data-ch-add-req="any_n_drills"' in html
    assert "Complete <strong>ALL</strong> of these drills" in html
    assert "Complete <strong>any N</strong> of these drills" in html
    assert 'if (type === "drills") return { type: "specific", target: "drills" };' in js
    assert 'if (type === "any_n_drills") return { type: "any_n", target: "drills" };' in js
    assert "completed_drill_ids" in _read("app/main.py")


def test_drill_try_scenario_bridge_is_hidden_for_pilot():
    js = _read("static/js/app.js")
    css = _read("static/css/style.css")

    assert "function _syncMgScenarioBridgeAvailability(root = document)" in js
    assert 'bridge.querySelector("[id$=\'try-scenario\']")' in js
    bridge_block = js[js.index("function _syncMgScenarioBridgeAvailability"):js.index("function show(id)")]
    assert 'bridge.classList.add("hidden")' in bridge_block
    assert 'bridge.setAttribute("aria-hidden", "true")' in bridge_block
    assert "_syncMgScenarioBridgeAvailability(node);" in js
    assert ".mg-bridge.hidden" in css
    assert '.mg-bridge[aria-hidden="true"]' in css
    assert "display: none !important" in css[css.index(".mg-bridge.hidden"):css.index(".mg-bridge-text")]


def test_pediatric_map_drill_completion_uses_learning_unlocks():
    js = _read("static/js/app.js")

    assert 'function _mapGameCompletionId(mapGameId = "")' in js
    assert 'return mapGameId === "pat_dash" ? "pat" : mapGameId;' in js
    assert "const completedGameIds = _completedLearningGameIds();" in js
    assert "completedGameIds.has(completionId)" in js
    assert "_fetchNotebookLearningData(false)" in js
    assert "_notebookLearningCache = {" in js


def test_swipe_games_have_adaptive_followup_content_and_panel():
    ap_cards = _read_json("static/data/games/ap/cards.json")
    ten4_cards = _read_json("static/data/games/ten4/cards.json")
    pat_cards = _read_json("static/data/games/pat/cards.json")

    assert sum(1 for card in ap_cards if card.get("follow_up", {}).get("correct")) >= 10
    assert sum(1 for card in ten4_cards if card.get("follow_up", {}).get("correct")) >= 6
    assert sum(1 for card in pat_cards if card.get("follow_up", {}).get("correct")) >= 6

    html = _read("static/index.html")
    for prefix in ("ap", "ten4", "pat"):
        assert f'id="{prefix}-adaptive-panel"' in html
        assert f'id="{prefix}-adaptive-choices"' in html


def test_swipe_adaptive_engine_uses_proficiency_and_ce_mode():
    js = _read("static/js/app.js")

    assert "adaptiveMode: true" in js
    assert "_renderAdaptivePanel(card)" in js
    assert "_submitAdaptiveChoice" in js
    assert 'mode: this._state.adaptive ? "ce_adaptive" : undefined' in js
    assert 'gameId:       "adult_child_ap_swipe"' in js
    assert 'gameId:       "ten4_facesp"' in js
    assert 'gameId:       "pat"' in js
    assert "pat" in get_allowed_minigame_ids()


def test_aeioutips_action_priority_adaptive_mode_is_authored_and_wired():
    data = _read_json("static/data/games/ams_aeioutips/game.json")
    cases = data.get("action_cases", [])

    assert len(cases) >= 8
    for case in cases:
        assert case.get("presentation")
        assert case.get("correct") in case.get("choices", [])
        assert case.get("hint")
        assert case.get("feedback")
        assert case.get("mistake_tag")

    js = _read("static/js/app.js")
    assert "_startActionPriorityRound" in js
    assert "_submitActionPriority" in js
    assert "_mgShouldUseAdaptiveMode(this._cfg.gameId)" in js
    assert 'gameId: "ams_aeioutips"' in js
    assert 'mode: "ce_adaptive"' in js
