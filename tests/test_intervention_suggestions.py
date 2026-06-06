from app.intervention_suggestions import (
    detect_intervention_suggestions,
    message_has_popup_intervention_intent,
)
from app.scenario_engine import load_scenario


def _diabetic_interventions():
    scenario = load_scenario("peds_diabetic_emergency_01")
    return scenario["vitals"]["interventions"]


def test_popup_intervention_suggestions_do_not_fire_for_blood_glucose_assessment():
    suggestions = detect_intervention_suggestions(
        "Alex, please check blood glucose and SpO2.",
        set(),
        _diabetic_interventions(),
    )

    assert all(item["id"] != "oral_glucose" for item in suggestions)


def test_popup_intervention_suggestions_do_not_treat_give_me_vitals_as_action_intent():
    suggestions = detect_intervention_suggestions(
        "Give me blood glucose, pulse, and respirations.",
        set(),
        _diabetic_interventions(),
    )

    assert suggestions == []
    assert not message_has_popup_intervention_intent("Give me blood glucose.")


def test_popup_intervention_suggestions_fire_for_explicit_oral_glucose_treatment():
    suggestions = detect_intervention_suggestions(
        "Administer oral glucose now.",
        set(),
        _diabetic_interventions(),
    )

    assert any(item["id"] == "oral_glucose" for item in suggestions)
    assert message_has_popup_intervention_intent("Administer oral glucose now.")


def test_head_injury_generic_supplemental_o2_does_not_suggest_nasal_cannula():
    scenario = load_scenario("peds_trauma_07_head_injury")

    suggestions = detect_intervention_suggestions(
        "Let's apply supplemental O2.",
        set(),
        scenario["vitals"]["interventions"],
    )

    assert all(item["id"] != "o2_nc" for item in suggestions)
