import pytest

from app.minigame_metadata import (
    DEFAULT_PASS_THRESHOLD,
    MINIGAME_METADATA,
    get_allowed_minigame_ids,
    get_minigame_metadata,
    get_reference_card_catalog,
    validate_minigame_metadata,
)
from app.models import MinigameReferenceCard


def test_metadata_registry_validates_current_allowed_games():
    validate_minigame_metadata(get_allowed_minigame_ids())


def test_missing_metadata_fails_loudly():
    registry = {"history_maker": MINIGAME_METADATA["history_maker"]}

    with pytest.raises(ValueError, match="Missing mini-game metadata"):
        validate_minigame_metadata({"history_maker", "missing_game"}, registry=registry)


def test_missing_pass_threshold_defaults_to_score_80():
    metadata = get_minigame_metadata("history_maker")

    assert metadata is not None
    assert metadata["pass_threshold"] == DEFAULT_PASS_THRESHOLD


def test_invalid_rubric_category_rejected():
    registry = {
        "bad_game": {
            **MINIGAME_METADATA["history_maker"],
            "rubric_category_mapping": ["fake_category"],
        }
    }

    with pytest.raises(ValueError, match="invalid rubric_category_mapping"):
        validate_minigame_metadata({"bad_game"}, registry=registry)


def test_reference_card_catalog_contains_mastery_unlock_content():
    catalog = get_reference_card_catalog()
    history_card = catalog["ref_opqrst_sample_peds"]

    assert history_card["title"] == "OPQRST and SAMPLE Pediatric History"
    assert history_card["framework_summary"]
    assert history_card["common_traps"]
    assert history_card["field_examples"]
    assert history_card["unlock_condition"]["all_passed"] == [
        "history_maker:foundation",
        "history_maker:interview_builder",
    ]


def test_metadata_merges_reference_card_content():
    metadata = get_minigame_metadata("peds_gcs_calculator")

    assert metadata is not None
    card = metadata["reference_card"]
    assert card["title"] == "Pediatric GCS"
    assert card["related_game_ids"] == ["peds_gcs_calculator"]
    assert card["field_examples"]


def test_missing_reference_card_content_fails_loudly():
    registry = {
        "bad_game": {
            **MINIGAME_METADATA["history_maker"],
            "reference_card": {
                "id": "ref_missing_content",
                "unlock_condition": {"all_passed": ["history_maker"]},
            },
        }
    }

    with pytest.raises(ValueError, match="reference_card.title"):
        validate_minigame_metadata({"bad_game"}, registry=registry)


def test_reference_card_model_has_user_card_unique_constraint():
    constraint_names = {
        constraint.name
        for constraint in MinigameReferenceCard.__table__.constraints
        if constraint.name
    }

    assert "uq_minigame_reference_card" in constraint_names
