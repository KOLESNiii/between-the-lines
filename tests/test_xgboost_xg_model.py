from pathlib import Path

import pytest

from xgboost_xg_model import (
    DEFAULT_CV_VALIDATION_SEASONS,
    DEFAULT_FINAL_MODEL_DIR,
    DEFAULT_TRAIN_SEASONS,
    DEFAULT_VALIDATION_SEASON,
    FEATURE_COLUMNS,
    META_COLUMNS,
    TARGET_COLUMN,
    artifact_paths,
    best_iteration_count,
    build_cross_validation_folds,
    build_model_dataset_sql,
    build_where_clause,
    parse_seasons,
)


def compact_sql(sql: str) -> str:
    return " ".join(sql.split())


def test_target_is_label_not_feature():
    assert TARGET_COLUMN == "target_xg_for"
    assert TARGET_COLUMN not in FEATURE_COLUMNS
    assert "xg" not in FEATURE_COLUMNS
    assert "goals_for" not in FEATURE_COLUMNS
    assert "goals_against" not in FEATURE_COLUMNS


def test_dataset_sql_labels_target_from_current_xg_only():
    sql = compact_sql(build_model_dataset_sql(labelled_only=True))

    assert "f.xg AS target_xg_for" in sql
    assert "WHERE f.xg IS NOT NULL" in sql


def test_dataset_sql_uses_season_scoped_leak_free_windows():
    sql = compact_sql(build_model_dataset_sql(labelled_only=True))

    assert "PARTITION BY a.team_id, a.season_year" in sql
    assert "ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING" in sql
    assert "ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING" in sql
    assert "ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING" in sql


def test_dataset_sql_lineup_proxy_uses_prior_player_matches_only():
    sql = compact_sql(build_model_dataset_sql(labelled_only=True))

    assert "prior.season_year = target.season_year" in sql
    assert "prior.start_datetime < target.start_datetime" in sql
    assert "WHERE player_rank <= 11" in sql


def test_where_clause_filters_match_identifiers():
    assert build_where_clause(match_id=123) == "WHERE f.match_id = 123"
    assert (
        build_where_clause(labelled_only=True, sofascore_event_id=456)
        == "WHERE f.xg IS NOT NULL AND f.sofascore_event_id = 456"
    )


def test_default_split_is_time_ordered_by_season_label():
    assert DEFAULT_TRAIN_SEASONS == ("22/23", "23/24", "24/25")
    assert DEFAULT_VALIDATION_SEASON == "25/26"
    assert DEFAULT_CV_VALIDATION_SEASONS == ("23/24", "24/25", "25/26")


def test_cross_validation_folds_use_only_prior_seasons():
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


def test_cross_validation_folds_respect_min_train_seasons():
    folds = build_cross_validation_folds(
        ["22/23", "23/24", "24/25", "25/26"],
        validation_seasons=("23/24", "24/25", "25/26"),
        min_train_seasons=2,
    )

    assert folds == [
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


def test_artifact_paths_contract():
    paths = artifact_paths(Path("models/xgboost_xg_for"))

    assert paths["model"].name == "model.json"
    assert paths["metadata"].name == "metadata.json"
    assert paths["feature_columns"].name == "feature_columns.json"
    assert paths["validation_predictions"].name == "validation_predictions.csv"
    assert paths["feature_importance"].name == "feature_importance.csv"
    assert paths["cross_validation_results"].name == "cross_validation_results.csv"


def test_final_model_has_separate_default_directory():
    assert DEFAULT_FINAL_MODEL_DIR == Path("models/xgboost_xg_for_final")


def test_best_iteration_count_uses_one_based_best_iteration():
    class Model:
        best_iteration = 17

    assert best_iteration_count(Model()) == 18


def test_best_iteration_count_falls_back_to_n_estimators():
    class Model:
        best_iteration = None

        def get_params(self):
            return {"n_estimators": 123}

    assert best_iteration_count(Model()) == 123


def test_meta_columns_include_match_identity():
    assert {"match_id", "team_id", "opponent_id", "side"}.issubset(META_COLUMNS)
