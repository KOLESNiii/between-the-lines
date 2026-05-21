from pathlib import Path

import pytest

from player_minutes_model import (
    BASELINE_MINUTES_COLUMN,
    BASELINE_START_COLUMN,
    DEFAULT_CV_VALIDATION_SEASONS,
    DEFAULT_FINAL_MODEL_DIR,
    DEFAULT_MODEL_DIR,
    DEFAULT_TRAIN_SEASONS,
    DEFAULT_VALIDATION_SEASON,
    FEATURE_COLUMNS,
    META_COLUMNS,
    MINUTES_TARGET,
    STARTER_TARGET,
    SUB_TARGET,
    artifact_paths,
    build_cross_validation_folds,
    build_player_minutes_dataset_sql,
    build_refresh_features_sql,
    build_where_clause,
    default_model_dir_for_command,
    parse_seasons,
)


def compact_sql(sql: str) -> str:
    return " ".join(sql.split())


def test_public_contract_columns():
    assert MINUTES_TARGET == "target_minutes"
    assert STARTER_TARGET == "target_started"
    assert SUB_TARGET == "target_sub_appearance"
    assert BASELINE_MINUTES_COLUMN == "baseline_expected_minutes"
    assert BASELINE_START_COLUMN == "baseline_starting_probability"
    assert "match_id" in META_COLUMNS
    assert "player_id" in META_COLUMNS
    assert "team_id" in META_COLUMNS
    assert MINUTES_TARGET not in FEATURE_COLUMNS
    assert STARTER_TARGET not in FEATURE_COLUMNS
    assert SUB_TARGET not in FEATURE_COLUMNS


def test_feature_columns_include_player_history_and_context():
    assert "rolling_minutes_5" in FEATURE_COLUMNS
    assert "rolling_start_rate_5" in FEATURE_COLUMNS
    assert "rolling_sub_appearance_rate_5" in FEATURE_COLUMNS
    assert "days_since_last_appearance" in FEATURE_COLUMNS
    assert "season_minutes_before_match" in FEATURE_COLUMNS
    assert "matches_last_7_days" in FEATURE_COLUMNS
    assert "position_forward" in FEATURE_COLUMNS


def test_dataset_sql_uses_prior_player_windows_only():
    sql = compact_sql(build_player_minutes_dataset_sql(labelled_only=True))

    assert "ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING" in sql
    assert "ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING" in sql
    assert "PARTITION BY b.player_id, b.team_id ORDER BY b.start_datetime, b.match_id" in sql
    assert "ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING" in sql
    assert "f.match_finished = true" in sql


def test_dataset_sql_does_not_use_current_substitute_as_feature():
    sql = compact_sql(build_player_minutes_dataset_sql(labelled_only=False))

    assert "COALESCE(a.substitute, false) AS listed_as_substitute" in sql
    assert "CASE WHEN COALESCE(a.substitute, false) THEN 0 ELSE 1 END AS target_started" in sql
    assert "listed_as_substitute" not in FEATURE_COLUMNS


def test_where_clause_filters_match_identifiers():
    assert build_where_clause(match_id=123) == "WHERE f.match_id = 123"
    assert (
        build_where_clause(labelled_only=True, sofascore_event_id=456)
        == "WHERE f.match_finished = true AND f.sofascore_event_id = 456"
    )


def test_refresh_features_sql_targets_feature_table():
    sql = compact_sql(build_refresh_features_sql())

    assert "TRUNCATE features.player_minutes_features" in sql
    assert "INSERT INTO features.player_minutes_features" in sql
    assert "FROM ( WITH match_team_rows AS" in sql


def test_artifact_paths_contract():
    paths = artifact_paths(Path("models/player_minutes"))

    assert paths["minutes_model"].name == "minutes_model.json"
    assert paths["starter_model"].name == "starter_model.json"
    assert paths["sub_model"].name == "sub_model.json"
    assert paths["metadata"].name == "metadata.json"
    assert paths["feature_columns"].name == "feature_columns.json"
    assert paths["validation_predictions"].name == "validation_predictions.csv"


def test_defaults_are_time_ordered():
    assert DEFAULT_MODEL_DIR == Path("models/player_minutes")
    assert DEFAULT_FINAL_MODEL_DIR == Path("models/player_minutes_final")
    assert DEFAULT_TRAIN_SEASONS == ("22/23", "23/24", "24/25")
    assert DEFAULT_VALIDATION_SEASON == "25/26"
    assert DEFAULT_CV_VALIDATION_SEASONS == ("23/24", "24/25", "25/26")


def test_default_model_dir_uses_final_artifacts_for_final_training_and_scoring():
    assert default_model_dir_for_command("train") == DEFAULT_MODEL_DIR
    assert default_model_dir_for_command("cross-validate") == DEFAULT_MODEL_DIR
    assert default_model_dir_for_command("train-final") == DEFAULT_FINAL_MODEL_DIR
    assert default_model_dir_for_command("predict-history") == DEFAULT_FINAL_MODEL_DIR
    assert default_model_dir_for_command("predict-match") == DEFAULT_FINAL_MODEL_DIR


def test_cross_validation_folds_use_prior_seasons():
    folds = build_cross_validation_folds(
        ["22/23", "23/24", "24/25", "25/26"],
        validation_seasons=("23/24", "24/25", "25/26"),
    )

    assert folds == [
        {"train_seasons": ("22/23",), "validation_season": "23/24"},
        {"train_seasons": ("22/23", "23/24"), "validation_season": "24/25"},
        {
            "train_seasons": ("22/23", "23/24", "24/25"),
            "validation_season": "25/26",
        },
    ]


def test_parse_seasons():
    assert parse_seasons("22/23, 23/24") == ("22/23", "23/24")
    with pytest.raises(ValueError):
        parse_seasons(" , ")
