from pathlib import Path

import pytest

from xgboost_xg_model import (
    BASELINE_COLUMN,
    DEFAULT_CV_VALIDATION_SEASONS,
    DEFAULT_FINAL_MODEL_DIR,
    DEFAULT_TRAIN_SEASONS,
    DEFAULT_VALIDATION_SEASON,
    FEATURE_COLUMNS,
    META_COLUMNS,
    MODEL_SPECS,
    QUALITY_COLUMNS,
    TARGET_COLUMN,
    artifact_paths,
    best_iteration_count,
    build_cross_validation_folds,
    build_model_dataset_sql,
    build_where_clause,
    parse_seasons,
    resolve_model_spec,
)


def compact_sql(sql: str) -> str:
    return " ".join(sql.split())


def test_target_is_label_not_feature():
    assert TARGET_COLUMN == "target_xg_for"
    assert TARGET_COLUMN not in FEATURE_COLUMNS
    assert "xg" not in FEATURE_COLUMNS
    assert "goals_for" not in FEATURE_COLUMNS
    assert "goals_against" not in FEATURE_COLUMNS
    assert "expected_goals_on_target" not in FEATURE_COLUMNS
    assert "shots_actual" not in FEATURE_COLUMNS


def test_model_specs_define_independent_targets_and_outputs():
    assert MODEL_SPECS["xg_for"].target_column == "target_xg_for"
    assert MODEL_SPECS["xg_for"].prediction_column == "xg_hat_for"
    assert MODEL_SPECS["shot_quality"].target_column == "target_shot_quality"
    assert MODEL_SPECS["shot_quality"].prediction_column == "shot_quality_hat"
    assert MODEL_SPECS["fragility"].target_column == "target_fragility"
    assert MODEL_SPECS["fragility"].prediction_column == "fragility_hat"
    assert MODEL_SPECS["shots_for"].target_column == "target_shots_for"
    assert MODEL_SPECS["shots_for"].prediction_column == "shots_for_hat"
    assert MODEL_SPECS["shots_against"].target_column == "target_shots_against"
    assert MODEL_SPECS["shots_against"].prediction_column == "shots_against_hat"
    assert len({spec.prediction_column for spec in MODEL_SPECS.values()}) == 5


def test_model_specs_define_default_artifact_directories():
    assert MODEL_SPECS["xg_for"].default_model_dir == Path("models/xgboost_xg_for")
    assert MODEL_SPECS["shot_quality"].default_model_dir == Path(
        "models/xgboost_shot_quality"
    )
    assert MODEL_SPECS["fragility"].default_model_dir == Path("models/xgboost_fragility")
    assert MODEL_SPECS["shots_for"].default_model_dir == Path(
        "models/xgboost_shots_for"
    )
    assert MODEL_SPECS["shots_against"].default_model_dir == Path(
        "models/xgboost_shots_against"
    )
    assert MODEL_SPECS["shot_quality"].default_final_model_dir == Path(
        "models/xgboost_shot_quality_final"
    )
    assert MODEL_SPECS["fragility"].default_final_model_dir == Path(
        "models/xgboost_fragility_final"
    )
    assert MODEL_SPECS["shots_for"].default_final_model_dir == Path(
        "models/xgboost_shots_for_final"
    )
    assert MODEL_SPECS["shots_against"].default_final_model_dir == Path(
        "models/xgboost_shots_against_final"
    )


def test_dataset_sql_labels_target_from_current_xg_only():
    sql = compact_sql(build_model_dataset_sql(labelled_only=True))

    assert "f.xg_actual AS target_xg_for" in sql
    assert "WHERE f.xg_actual IS NOT NULL" in sql
    assert f"AS {BASELINE_COLUMN}" in sql


def test_shot_quality_sql_uses_direct_target_and_low_shot_filter():
    sql = compact_sql(
        build_model_dataset_sql(
            labelled_only=True,
            model_spec=MODEL_SPECS["shot_quality"],
        )
    )

    assert "f.xg_actual / GREATEST(f.shots_actual, 1)" in sql
    assert "AS target_shot_quality" in sql
    assert "AS baseline_prediction" in sql
    assert "f.shots_actual >= 3" in sql
    assert "xg_hat_for" not in sql


def test_fragility_sql_uses_direct_target_and_low_shot_filter():
    sql = compact_sql(
        build_model_dataset_sql(
            labelled_only=True,
            model_spec=MODEL_SPECS["fragility"],
        )
    )

    assert "f.xg_against_actual / GREATEST(f.shots_against_actual, 1)" in sql
    assert "AS target_fragility" in sql
    assert "AS baseline_prediction" in sql
    assert "f.shots_against_actual >= 3" in sql
    assert "xg_hat_for" not in sql


def test_shots_for_sql_uses_direct_target_and_rolling_baseline():
    sql = compact_sql(
        build_model_dataset_sql(
            labelled_only=True,
            model_spec=MODEL_SPECS["shots_for"],
        )
    )

    assert "f.shots_actual AS target_shots_for" in sql
    assert "rolling.rolling_shots_5 AS baseline_prediction" in sql
    assert "WHERE f.shots_actual IS NOT NULL" in sql
    assert "f.xg_actual / GREATEST" not in sql
    assert "xg_hat_for" not in sql


def test_shots_against_sql_uses_direct_target_and_rolling_baseline():
    sql = compact_sql(
        build_model_dataset_sql(
            labelled_only=True,
            model_spec=MODEL_SPECS["shots_against"],
        )
    )

    assert "f.shots_against_actual AS target_shots_against" in sql
    assert "rolling.rolling_shots_against_5 AS baseline_prediction" in sql
    assert "WHERE f.shots_against_actual IS NOT NULL" in sql
    assert "f.xg_against_actual / GREATEST" not in sql
    assert "xg_hat_for" not in sql


def test_dataset_sql_uses_cross_season_leak_free_windows():
    sql = compact_sql(build_model_dataset_sql(labelled_only=True))

    assert "PARTITION BY a.team_id ORDER BY a.start_datetime, a.match_id" in sql
    assert "ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING" in sql
    assert "ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING" in sql
    assert "ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING" in sql


def test_dataset_sql_lineup_proxy_uses_prior_player_matches_only():
    sql = compact_sql(build_model_dataset_sql(labelled_only=True))

    assert "prior.start_datetime < target.start_datetime" in sql
    assert "recency.weight" in sql
    assert "WHERE player_rank <= 11" in sql


def test_dataset_sql_can_score_first_week_from_prior_team_history():
    sql = compact_sql(build_model_dataset_sql(labelled_only=False))

    assert "COUNT(*) OVER team_prior AS rolling_history_count" in sql
    assert "COALESCE(rolling_xg_for_5_raw, 1.35) AS rolling_xg_for_5" in sql
    assert "rolling.feature_coverage_score" in sql


def test_dataset_sql_uses_prior_tempo_features_only():
    sql = compact_sql(build_model_dataset_sql(labelled_only=True))

    assert "COUNT(a.tempo_total_shots) OVER w5 AS rolling_tempo_shots_5_available_count" in sql
    assert "AVG(a.tempo_touches_in_box) OVER w5 AS rolling_tempo_box_touches_5_raw" in sql
    assert "ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING" in sql
    assert "rolling.rolling_tempo_shots_5" in sql
    assert "rolling.rolling_tempo_count" in sql
    assert "opponent_rolling.rolling_tempo_shots_5 AS opp_rolling_tempo_shots_5" in sql
    assert "AS match_tempo_index" in sql


def test_dataset_sql_uses_prior_expanded_performance_features_only():
    sql = compact_sql(build_model_dataset_sql(labelled_only=True))

    assert "COUNT(a.expected_goals_on_target) OVER w5 AS rolling_xgot_for_5_available_count" in sql
    assert "AVG(a.total_progression) OVER w5 AS rolling_progression_5_raw" in sql
    assert "a.tempo_crosses_completed / NULLIF(a.tempo_crosses_attempted, 0)" in sql
    assert "a.tempo_big_chances_scored / NULLIF(" in sql
    assert "ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING" in sql
    assert "rolling.rolling_xgot_for_5" in sql
    assert "opponent_rolling.rolling_xgot_for_5 AS opp_rolling_xgot_for_5" in sql


def test_dataset_sql_uses_current_lineup_context_without_match_performance():
    sql = compact_sql(build_model_dataset_sql(labelled_only=False))

    assert "CASE WHEN COALESCE(f.confirmed_lineup, false) THEN 1 ELSE 0 END AS confirmed_lineup" in sql
    assert "COALESCE(f.formation_code, 442) AS formation_code" in sql
    assert "COALESCE(f.starter_market_value_eur, f.listed_market_value_eur, 250000000) / 1000000.0 AS starter_market_value_m" in sql
    assert "LEFT JOIN features.sofascore_team_match_features opponent_features" in sql


def test_tempo_features_are_public_model_columns():
    assert "rolling_tempo_shots_5" in FEATURE_COLUMNS
    assert "rolling_tempo_box_touches_5" in FEATURE_COLUMNS
    assert "opp_rolling_tempo_shots_5" in FEATURE_COLUMNS
    assert "match_tempo_index" in FEATURE_COLUMNS
    assert "tempo_feature_coverage_score" in QUALITY_COLUMNS


def test_expanded_features_are_public_model_columns():
    assert "rolling_xgot_for_5" in FEATURE_COLUMNS
    assert "rolling_progression_5" in FEATURE_COLUMNS
    assert "rolling_cross_accuracy_5" in FEATURE_COLUMNS
    assert "confirmed_lineup" in FEATURE_COLUMNS
    assert "starter_market_value_m" in FEATURE_COLUMNS
    assert "opp_rolling_xgot_for_5" in FEATURE_COLUMNS
    assert "adj_roster_value" in FEATURE_COLUMNS
    assert "xi_player_value_sum" in FEATURE_COLUMNS
    assert "extended_feature_coverage_score" in QUALITY_COLUMNS


def test_where_clause_filters_match_identifiers():
    assert build_where_clause(match_id=123) == "WHERE f.match_id = 123"
    assert (
        build_where_clause(labelled_only=True, sofascore_event_id=456)
        == "WHERE f.xg_actual IS NOT NULL AND f.sofascore_event_id = 456"
    )


def test_where_clause_uses_target_specific_label_filters():
    assert (
        build_where_clause(labelled_only=True, model_spec=MODEL_SPECS["shot_quality"])
        == "WHERE f.xg_actual IS NOT NULL AND f.shots_actual IS NOT NULL AND f.shots_actual >= 3"
    )
    assert (
        build_where_clause(labelled_only=True, model_spec=MODEL_SPECS["fragility"])
        == "WHERE f.xg_against_actual IS NOT NULL AND f.shots_against_actual IS NOT NULL "
        "AND f.shots_against_actual >= 3"
    )
    assert (
        build_where_clause(labelled_only=True, model_spec=MODEL_SPECS["shots_for"])
        == "WHERE f.shots_actual IS NOT NULL"
    )
    assert (
        build_where_clause(labelled_only=True, model_spec=MODEL_SPECS["shots_against"])
        == "WHERE f.shots_against_actual IS NOT NULL"
    )


def test_resolve_model_spec_rejects_unknown_model():
    assert resolve_model_spec("xg_for") == MODEL_SPECS["xg_for"]
    with pytest.raises(ValueError):
        resolve_model_spec("goals")


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
