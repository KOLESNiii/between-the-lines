import argparse
import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DB_URL = "postgresql://user:pwd@localhost:5432/betting_historical_data"
DEFAULT_MODEL_DIR = Path("models/xgboost_xg_for")
DEFAULT_TRAIN_SEASONS = ("22/23", "23/24", "24/25")
DEFAULT_VALIDATION_SEASON = "25/26"
DEFAULT_CV_VALIDATION_SEASONS = ("23/24", "24/25", "25/26")
TARGET_COLUMN = "target_xg_for"
PREDICTION_COLUMN = "xg_hat_for"
DEFAULT_CLIP_RANGE = (0.05, 5.0)
DEFAULT_FINAL_MODEL_DIR = Path("models/xgboost_xg_for_final")
BASELINE_COLUMN = "baseline_prediction"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    target_column: str
    prediction_column: str
    default_model_dir: Path
    default_final_model_dir: Path
    clip_min: float
    clip_max: float
    default_min_shots: int | None = None


MODEL_SPECS = {
    "xg_for": ModelSpec(
        name="xg_for",
        target_column=TARGET_COLUMN,
        prediction_column=PREDICTION_COLUMN,
        default_model_dir=DEFAULT_MODEL_DIR,
        default_final_model_dir=DEFAULT_FINAL_MODEL_DIR,
        clip_min=DEFAULT_CLIP_RANGE[0],
        clip_max=DEFAULT_CLIP_RANGE[1],
    ),
    "shot_quality": ModelSpec(
        name="shot_quality",
        target_column="target_shot_quality",
        prediction_column="shot_quality_hat",
        default_model_dir=Path("models/xgboost_shot_quality"),
        default_final_model_dir=Path("models/xgboost_shot_quality_final"),
        clip_min=0.0,
        clip_max=0.5,
        default_min_shots=3,
    ),
    "fragility": ModelSpec(
        name="fragility",
        target_column="target_fragility",
        prediction_column="fragility_hat",
        default_model_dir=Path("models/xgboost_fragility"),
        default_final_model_dir=Path("models/xgboost_fragility_final"),
        clip_min=0.0,
        clip_max=0.5,
        default_min_shots=3,
    ),
}

META_COLUMNS = [
    "match_id",
    "sofascore_event_id",
    "season_year",
    "match_date",
    "team_id",
    "opponent_id",
    "team_name",
    "opponent_name",
    "side",
]

FEATURE_COLUMNS = [
    "is_home",
    "rest_days",
    "matches_last_7_days",
    "matches_last_14_days",
    "rolling_history_count",
    "rolling_xg_for_5_available_count",
    "rolling_xg_against_5_available_count",
    "rolling_shots_5_available_count",
    "rolling_shots_against_5_available_count",
    "feature_coverage_score",
    "rolling_xg_for_3",
    "rolling_xg_for_5",
    "rolling_xg_for_10",
    "rolling_xg_against_5",
    "rolling_shots_5",
    "rolling_shots_against_5",
    "rolling_big_chances_5",
    "shot_accuracy_5",
    "tackles_won_5",
    "interceptions_5",
    "blocks_5",
    "possession_proxy_5",
    "passes_per90_5",
    "rolling_tempo_count",
    "tempo_feature_coverage_score",
    "rolling_tempo_shots_5",
    "rolling_tempo_box_touches_5",
    "rolling_tempo_final_third_entries_5",
    "rolling_tempo_corners_5",
    "rolling_tempo_passes_5",
    "rolling_tempo_pass_accuracy_5",
    "rolling_tempo_directness_5",
    "rolling_box_pressure_index_5",
    "rolling_xgot_for_5",
    "rolling_shot_value_5",
    "rolling_pass_value_5",
    "rolling_progression_5",
    "rolling_carry_distance_5",
    "rolling_opp_half_pass_accuracy_5",
    "rolling_dribble_success_5",
    "rolling_fouls_won_5",
    "rolling_clearances_5",
    "rolling_keeper_value_5",
    "rolling_cross_accuracy_5",
    "rolling_long_ball_accuracy_5",
    "rolling_big_chance_conversion_5",
    "rolling_shot_box_share_5",
    "confirmed_lineup",
    "formation_code",
    "starter_market_value_m",
    "missing_market_value_m",
    "doubtful_market_value_m",
    "missing_player_count",
    "doubtful_player_count",
    "starter_avg_age_years",
    "starter_defender_count",
    "starter_midfielder_count",
    "starter_forward_count",
    "opp_rolling_xg_for_5",
    "opp_rolling_xg_against_5",
    "opp_shot_accuracy_5",
    "opp_rolling_shots_5",
    "opp_rolling_shots_against_5",
    "opp_rolling_history_count",
    "opp_feature_coverage_score",
    "opp_rolling_tempo_count",
    "opp_tempo_feature_coverage_score",
    "opp_rolling_tempo_shots_5",
    "opp_rolling_tempo_box_touches_5",
    "opp_rolling_tempo_final_third_entries_5",
    "opp_rolling_tempo_corners_5",
    "opp_rolling_tempo_passes_5",
    "opp_rolling_tempo_pass_accuracy_5",
    "opp_rolling_tempo_directness_5",
    "opp_rolling_box_pressure_index_5",
    "opp_rolling_xgot_for_5",
    "opp_rolling_shot_value_5",
    "opp_rolling_progression_5",
    "opp_rolling_dribble_success_5",
    "opp_rolling_cross_accuracy_5",
    "opp_rolling_shot_box_share_5",
    "opp_starter_market_value_m",
    "opp_missing_market_value_m",
    "opp_missing_player_count",
    "adj_attack_xg_5",
    "adj_defence_xg_5",
    "adj_progression_5",
    "adj_roster_value",
    "match_tempo_index",
    "xi_xg_sum",
    "xi_xa_sum",
    "xi_key_pass_sum",
    "xi_progressive_carries",
    "xi_def_actions",
    "xi_goalkeeper_strength",
    "xi_player_value_sum",
]

QUALITY_COLUMNS = [
    "xg_feature_available",
    "rolling_history_count",
    "feature_coverage_score",
    "rolling_tempo_count",
    "tempo_feature_coverage_score",
    "extended_feature_coverage_score",
    "match_tempo_index",
]

MODEL_PARAMS = {
    "n_estimators": 500,
    "learning_rate": 0.03,
    "max_depth": 3,
    "subsample": 0.85,
    "colsample_bytree": 0.85,
    "reg_lambda": 2.0,
    "objective": "reg:squarederror",
    "random_state": 42,
}


MODEL_DATASET_SQL = """
WITH rolling_base AS (
    SELECT
        a.*,
        COUNT(*) OVER team_prior AS rolling_history_count,
        COUNT(a.xg) OVER w3 AS rolling_xg_for_3_available_count,
        AVG(a.xg) OVER w3 AS rolling_xg_for_3_raw,
        COUNT(a.xg) OVER w5 AS rolling_xg_for_5_available_count,
        AVG(a.xg) OVER w5 AS rolling_xg_for_5_raw,
        COUNT(a.xg) OVER w10 AS rolling_xg_for_10_available_count,
        AVG(a.xg) OVER w10 AS rolling_xg_for_10_raw,
        COUNT(a.xg_against) OVER w5 AS rolling_xg_against_5_available_count,
        AVG(a.xg_against) OVER w5 AS rolling_xg_against_5_raw,
        COUNT(a.total_shots) OVER w5 AS rolling_shots_5_available_count,
        AVG(a.total_shots) OVER w5 AS rolling_shots_5_raw,
        COUNT(a.shots_against) OVER w5 AS rolling_shots_against_5_available_count,
        AVG(a.shots_against) OVER w5 AS rolling_shots_against_5_raw,
        COUNT(a.big_chances) OVER w5 AS rolling_big_chances_5_available_count,
        AVG(a.big_chances) OVER w5 AS rolling_big_chances_5_raw,
        COUNT(a.shot_accuracy) OVER w5 AS shot_accuracy_5_available_count,
        AVG(a.shot_accuracy) OVER w5 AS shot_accuracy_5_raw,
        COUNT(a.tackles) OVER w5 AS tackles_won_5_available_count,
        AVG(a.tackles) OVER w5 AS tackles_won_5_raw,
        COUNT(a.interceptions) OVER w5 AS interceptions_5_available_count,
        AVG(a.interceptions) OVER w5 AS interceptions_5_raw,
        COUNT(a.blocks) OVER w5 AS blocks_5_available_count,
        AVG(a.blocks) OVER w5 AS blocks_5_raw,
        COUNT(a.possession_proxy) OVER w5 AS possession_proxy_5_available_count,
        AVG(a.possession_proxy) OVER w5 AS possession_proxy_5_raw,
        COUNT(a.passes_per_minute) OVER w5 AS passes_per90_5_available_count,
        AVG(a.passes_per_minute * 90) OVER w5 AS passes_per90_5_raw,
        COUNT(a.tempo_total_shots) OVER w5 AS rolling_tempo_shots_5_available_count,
        AVG(a.tempo_total_shots) OVER w5 AS rolling_tempo_shots_5_raw,
        COUNT(a.tempo_touches_in_box) OVER w5 AS rolling_tempo_box_touches_5_available_count,
        AVG(a.tempo_touches_in_box) OVER w5 AS rolling_tempo_box_touches_5_raw,
        COUNT(a.tempo_final_third_entries) OVER w5 AS rolling_tempo_final_third_entries_5_available_count,
        AVG(a.tempo_final_third_entries) OVER w5 AS rolling_tempo_final_third_entries_5_raw,
        COUNT(a.tempo_corners) OVER w5 AS rolling_tempo_corners_5_available_count,
        AVG(a.tempo_corners) OVER w5 AS rolling_tempo_corners_5_raw,
        COUNT(a.tempo_passes) OVER w5 AS rolling_tempo_passes_5_available_count,
        AVG(a.tempo_passes) OVER w5 AS rolling_tempo_passes_5_raw,
        COUNT(
            CASE
                WHEN a.tempo_accurate_passes IS NOT NULL AND a.tempo_passes > 0
                THEN 1
            END
        ) OVER w5 AS rolling_tempo_pass_accuracy_5_available_count,
        AVG(
            CASE
                WHEN a.tempo_accurate_passes IS NOT NULL AND a.tempo_passes > 0
                THEN a.tempo_accurate_passes / NULLIF(a.tempo_passes, 0)
            END
        ) OVER w5 AS rolling_tempo_pass_accuracy_5_raw,
        COUNT(
            CASE
                WHEN a.tempo_final_third_entries IS NOT NULL AND a.tempo_passes > 0
                THEN 1
            END
        ) OVER w5 AS rolling_tempo_directness_5_available_count,
        AVG(
            CASE
                WHEN a.tempo_final_third_entries IS NOT NULL AND a.tempo_passes > 0
                THEN a.tempo_final_third_entries / NULLIF(a.tempo_passes, 0)
            END
        ) OVER w5 AS rolling_tempo_directness_5_raw,
        COUNT(
            CASE
                WHEN a.tempo_touches_in_box IS NOT NULL
                  OR a.tempo_shots_inside_box IS NOT NULL
                  OR a.tempo_corners IS NOT NULL
                THEN 1
            END
        ) OVER w5 AS rolling_box_pressure_index_5_available_count,
        AVG(
            CASE
                WHEN a.tempo_touches_in_box IS NOT NULL
                  OR a.tempo_shots_inside_box IS NOT NULL
                  OR a.tempo_corners IS NOT NULL
                THEN COALESCE(a.tempo_touches_in_box, 0)
                   + COALESCE(a.tempo_shots_inside_box, 0) * 2.0
                   + COALESCE(a.tempo_corners, 0) * 0.5
            END
        ) OVER w5 AS rolling_box_pressure_index_5_raw
        ,
        COUNT(a.expected_goals_on_target) OVER w5 AS rolling_xgot_for_5_available_count,
        AVG(a.expected_goals_on_target) OVER w5 AS rolling_xgot_for_5_raw,
        COUNT(a.shot_value) OVER w5 AS rolling_shot_value_5_available_count,
        AVG(a.shot_value) OVER w5 AS rolling_shot_value_5_raw,
        COUNT(a.pass_value) OVER w5 AS rolling_pass_value_5_available_count,
        AVG(a.pass_value) OVER w5 AS rolling_pass_value_5_raw,
        COUNT(a.total_progression) OVER w5 AS rolling_progression_5_available_count,
        AVG(a.total_progression) OVER w5 AS rolling_progression_5_raw,
        COUNT(a.ball_carry_distance) OVER w5 AS rolling_carry_distance_5_available_count,
        AVG(a.ball_carry_distance) OVER w5 AS rolling_carry_distance_5_raw,
        COUNT(
            CASE
                WHEN a.accurate_opp_half_passes IS NOT NULL AND a.opp_half_passes > 0
                THEN 1
            END
        ) OVER w5 AS rolling_opp_half_pass_accuracy_5_available_count,
        AVG(
            CASE
                WHEN a.accurate_opp_half_passes IS NOT NULL AND a.opp_half_passes > 0
                THEN a.accurate_opp_half_passes / NULLIF(a.opp_half_passes, 0)
            END
        ) OVER w5 AS rolling_opp_half_pass_accuracy_5_raw,
        COUNT(
            CASE
                WHEN a.won_contests IS NOT NULL AND a.total_contests > 0
                THEN 1
            END
        ) OVER w5 AS rolling_dribble_success_5_available_count,
        AVG(
            CASE
                WHEN a.won_contests IS NOT NULL AND a.total_contests > 0
                THEN a.won_contests / NULLIF(a.total_contests, 0)
            END
        ) OVER w5 AS rolling_dribble_success_5_raw,
        COUNT(a.fouls_won) OVER w5 AS rolling_fouls_won_5_available_count,
        AVG(a.fouls_won) OVER w5 AS rolling_fouls_won_5_raw,
        COUNT(a.clearances) OVER w5 AS rolling_clearances_5_available_count,
        AVG(a.clearances) OVER w5 AS rolling_clearances_5_raw,
        COUNT(a.goalkeeper_value) OVER w5 AS rolling_keeper_value_5_available_count,
        AVG(a.goalkeeper_value) OVER w5 AS rolling_keeper_value_5_raw,
        COUNT(
            CASE
                WHEN a.tempo_crosses_completed IS NOT NULL AND a.tempo_crosses_attempted > 0
                THEN 1
            END
        ) OVER w5 AS rolling_cross_accuracy_5_available_count,
        AVG(
            CASE
                WHEN a.tempo_crosses_completed IS NOT NULL AND a.tempo_crosses_attempted > 0
                THEN a.tempo_crosses_completed / NULLIF(a.tempo_crosses_attempted, 0)
            END
        ) OVER w5 AS rolling_cross_accuracy_5_raw,
        COUNT(
            CASE
                WHEN a.tempo_long_balls_completed IS NOT NULL AND a.tempo_long_balls_attempted > 0
                THEN 1
            END
        ) OVER w5 AS rolling_long_ball_accuracy_5_available_count,
        AVG(
            CASE
                WHEN a.tempo_long_balls_completed IS NOT NULL AND a.tempo_long_balls_attempted > 0
                THEN a.tempo_long_balls_completed / NULLIF(a.tempo_long_balls_attempted, 0)
            END
        ) OVER w5 AS rolling_long_ball_accuracy_5_raw,
        COUNT(
            CASE
                WHEN a.tempo_big_chances_scored IS NOT NULL
                  AND COALESCE(a.tempo_big_chances_scored, 0) + COALESCE(a.tempo_big_chances_missed, 0) > 0
                THEN 1
            END
        ) OVER w5 AS rolling_big_chance_conversion_5_available_count,
        AVG(
            CASE
                WHEN a.tempo_big_chances_scored IS NOT NULL
                  AND COALESCE(a.tempo_big_chances_scored, 0) + COALESCE(a.tempo_big_chances_missed, 0) > 0
                THEN a.tempo_big_chances_scored / NULLIF(
                    COALESCE(a.tempo_big_chances_scored, 0)
                    + COALESCE(a.tempo_big_chances_missed, 0),
                    0
                )
            END
        ) OVER w5 AS rolling_big_chance_conversion_5_raw,
        COUNT(
            CASE
                WHEN a.tempo_shots_inside_box IS NOT NULL AND a.tempo_total_shots > 0
                THEN 1
            END
        ) OVER w5 AS rolling_shot_box_share_5_available_count,
        AVG(
            CASE
                WHEN a.tempo_shots_inside_box IS NOT NULL AND a.tempo_total_shots > 0
                THEN a.tempo_shots_inside_box / NULLIF(a.tempo_total_shots, 0)
            END
        ) OVER w5 AS rolling_shot_box_share_5_raw
    FROM features.sofascore_team_match_aggregates a
    WINDOW
        team_prior AS (
            PARTITION BY a.team_id
            ORDER BY a.start_datetime, a.match_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ),
        w3 AS (
            PARTITION BY a.team_id
            ORDER BY a.start_datetime, a.match_id
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
        ),
        w5 AS (
            PARTITION BY a.team_id
            ORDER BY a.start_datetime, a.match_id
            ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
        ),
        w10 AS (
            PARTITION BY a.team_id
            ORDER BY a.start_datetime, a.match_id
            ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
        )
),
rolling AS (
    SELECT
        rolling_base.match_id,
        rolling_base.team_id,
        rolling_base.opponent_id,
        rolling_base.rolling_history_count,
        rolling_base.rolling_xg_for_5_available_count,
        rolling_base.rolling_xg_against_5_available_count,
        rolling_base.rolling_shots_5_available_count,
        rolling_base.rolling_shots_against_5_available_count,
        GREATEST(
            rolling_tempo_shots_5_available_count,
            rolling_tempo_box_touches_5_available_count,
            rolling_tempo_final_third_entries_5_available_count,
            rolling_tempo_corners_5_available_count,
            rolling_tempo_passes_5_available_count,
            rolling_tempo_pass_accuracy_5_available_count,
            rolling_tempo_directness_5_available_count,
            rolling_box_pressure_index_5_available_count
        ) AS rolling_tempo_count,
        (
            (
                CASE WHEN rolling_xg_for_3_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_xg_for_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_xg_for_10_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_xg_against_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_shots_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_shots_against_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_big_chances_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN shot_accuracy_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN tackles_won_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN interceptions_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN blocks_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN possession_proxy_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN passes_per90_5_available_count > 0 THEN 1 ELSE 0 END
            ) / 13.0
        ) AS feature_coverage_score,
        (
            (
                CASE WHEN rolling_tempo_shots_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_tempo_box_touches_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_tempo_final_third_entries_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_tempo_corners_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_tempo_passes_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_tempo_pass_accuracy_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_tempo_directness_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_box_pressure_index_5_available_count > 0 THEN 1 ELSE 0 END
            ) / 8.0
        ) AS tempo_feature_coverage_score,
        (
            (
                CASE WHEN rolling_xgot_for_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_shot_value_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_pass_value_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_progression_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_carry_distance_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_opp_half_pass_accuracy_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_dribble_success_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_fouls_won_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_clearances_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_keeper_value_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_cross_accuracy_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_long_ball_accuracy_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_big_chance_conversion_5_available_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN rolling_shot_box_share_5_available_count > 0 THEN 1 ELSE 0 END
            ) / 14.0
        ) AS extended_feature_coverage_score,
        COALESCE(rolling_xg_for_3_raw, 1.35) AS rolling_xg_for_3,
        COALESCE(rolling_xg_for_5_raw, 1.35) AS rolling_xg_for_5,
        COALESCE(rolling_xg_for_10_raw, 1.35) AS rolling_xg_for_10,
        COALESCE(rolling_xg_against_5_raw, 1.35) AS rolling_xg_against_5,
        COALESCE(rolling_shots_5_raw, 12.0) AS rolling_shots_5,
        COALESCE(rolling_shots_against_5_raw, 12.0) AS rolling_shots_against_5,
        COALESCE(rolling_big_chances_5_raw, 1.5) AS rolling_big_chances_5,
        COALESCE(shot_accuracy_5_raw, 0.35) AS shot_accuracy_5,
        COALESCE(tackles_won_5_raw, 12.0) AS tackles_won_5,
        COALESCE(interceptions_5_raw, 12.0) AS interceptions_5,
        COALESCE(blocks_5_raw, 4.0) AS blocks_5,
        COALESCE(possession_proxy_5_raw, 0.5) AS possession_proxy_5,
        COALESCE(passes_per90_5_raw, 35.0) AS passes_per90_5,
        COALESCE(rolling_tempo_shots_5_raw, 12.0) AS rolling_tempo_shots_5,
        COALESCE(rolling_tempo_box_touches_5_raw, 22.0) AS rolling_tempo_box_touches_5,
        COALESCE(rolling_tempo_final_third_entries_5_raw, 40.0) AS rolling_tempo_final_third_entries_5,
        COALESCE(rolling_tempo_corners_5_raw, 4.5) AS rolling_tempo_corners_5,
        COALESCE(rolling_tempo_passes_5_raw, 400.0) AS rolling_tempo_passes_5,
        COALESCE(rolling_tempo_pass_accuracy_5_raw, 0.78) AS rolling_tempo_pass_accuracy_5,
        COALESCE(rolling_tempo_directness_5_raw, 0.10) AS rolling_tempo_directness_5,
        COALESCE(rolling_box_pressure_index_5_raw, 38.0) AS rolling_box_pressure_index_5,
        COALESCE(rolling_xgot_for_5_raw, 1.25) AS rolling_xgot_for_5,
        COALESCE(rolling_shot_value_5_raw, 0.0) AS rolling_shot_value_5,
        COALESCE(rolling_pass_value_5_raw, 0.0) AS rolling_pass_value_5,
        COALESCE(rolling_progression_5_raw, 700.0) AS rolling_progression_5,
        COALESCE(rolling_carry_distance_5_raw, 1400.0) AS rolling_carry_distance_5,
        COALESCE(rolling_opp_half_pass_accuracy_5_raw, 0.72) AS rolling_opp_half_pass_accuracy_5,
        COALESCE(rolling_dribble_success_5_raw, 0.45) AS rolling_dribble_success_5,
        COALESCE(rolling_fouls_won_5_raw, 10.0) AS rolling_fouls_won_5,
        COALESCE(rolling_clearances_5_raw, 18.0) AS rolling_clearances_5,
        COALESCE(rolling_keeper_value_5_raw, 0.0) AS rolling_keeper_value_5,
        COALESCE(rolling_cross_accuracy_5_raw, 0.28) AS rolling_cross_accuracy_5,
        COALESCE(rolling_long_ball_accuracy_5_raw, 0.45) AS rolling_long_ball_accuracy_5,
        COALESCE(rolling_big_chance_conversion_5_raw, 0.35) AS rolling_big_chance_conversion_5,
        COALESCE(rolling_shot_box_share_5_raw, 0.55) AS rolling_shot_box_share_5,
        (
            COALESCE(rolling_tempo_shots_5_raw, 12.0) / 12.0
            + COALESCE(rolling_tempo_box_touches_5_raw, 22.0) / 22.0
            + COALESCE(rolling_tempo_final_third_entries_5_raw, 40.0) / 40.0
            + COALESCE(rolling_box_pressure_index_5_raw, 38.0) / 38.0
        ) / 4.0 AS team_tempo_index
    FROM rolling_base
),
context AS (
    SELECT
        a.match_id,
        a.team_id,
        EXTRACT(
            EPOCH FROM (
                a.start_datetime
                - LAG(a.start_datetime) OVER (
                    PARTITION BY a.team_id
                    ORDER BY a.start_datetime, a.match_id
                )
            )
        ) / 86400.0 AS rest_days,
        (
            SELECT COUNT(*)
            FROM features.sofascore_team_match_aggregates prior
            WHERE prior.team_id = a.team_id
              AND prior.start_datetime < a.start_datetime
              AND prior.start_datetime >= a.start_datetime - INTERVAL '7 days'
        )::integer AS matches_last_7_days,
        (
            SELECT COUNT(*)
            FROM features.sofascore_team_match_aggregates prior
            WHERE prior.team_id = a.team_id
              AND prior.start_datetime < a.start_datetime
              AND prior.start_datetime >= a.start_datetime - INTERVAL '14 days'
        )::integer AS matches_last_14_days
    FROM features.sofascore_team_match_aggregates a
),
active_player_values AS (
    SELECT
        a.match_id,
        a.team_id,
        a.player_id,
        m.season_year,
        m.start_datetime,
        minutes.value_numeric AS minutes_played,
        xg.value_numeric / NULLIF(minutes.value_numeric, 0) * 90 AS xg_per90,
        xa.value_numeric / NULLIF(minutes.value_numeric, 0) * 90 AS xa_per90,
        key_pass.value_numeric / NULLIF(minutes.value_numeric, 0) * 90 AS key_pass_per90,
        progressive.value_numeric / NULLIF(minutes.value_numeric, 0) * 90 AS progressive_carries_per90,
        (
            COALESCE(pass_value.value_numeric, 0)
            + COALESCE(shot_value.value_numeric, 0)
            + COALESCE(dribble_value.value_numeric, 0)
            + COALESCE(defensive_value.value_numeric, 0)
        ) AS player_value,
        NULLIF(p.raw_player -> 'proposedMarketValueRaw' ->> 'value', '')::numeric / 1000000.0 AS market_value_m,
        (
            COALESCE(tackles.value_numeric, 0)
            + COALESCE(interceptions.value_numeric, 0)
        ) / NULLIF(minutes.value_numeric, 0) * 90 AS def_actions_per90,
        (
            COALESCE(saves.value_numeric, 0)
            + COALESCE(goals_prevented.value_numeric, 0)
        ) / NULLIF(minutes.value_numeric, 0) * 90 AS goalkeeper_strength_per90
    FROM raw.sofascore_player_match_appearances a
    JOIN raw.sofascore_matches m ON m.id = a.match_id
    JOIN raw.sofascore_players p ON p.id = a.player_id
    JOIN raw.sofascore_player_match_stats minutes
      ON minutes.match_id = a.match_id
     AND minutes.team_id = a.team_id
     AND minutes.player_id = a.player_id
     AND minutes.stat_key = 'minutesPlayed'
    LEFT JOIN raw.sofascore_player_match_stats xg
      ON xg.match_id = a.match_id
     AND xg.team_id = a.team_id
     AND xg.player_id = a.player_id
     AND xg.stat_key = 'expectedGoals'
    LEFT JOIN raw.sofascore_player_match_stats xa
      ON xa.match_id = a.match_id
     AND xa.team_id = a.team_id
     AND xa.player_id = a.player_id
     AND xa.stat_key = 'expectedAssists'
    LEFT JOIN raw.sofascore_player_match_stats key_pass
      ON key_pass.match_id = a.match_id
     AND key_pass.team_id = a.team_id
     AND key_pass.player_id = a.player_id
     AND key_pass.stat_key = 'keyPass'
    LEFT JOIN raw.sofascore_player_match_stats progressive
      ON progressive.match_id = a.match_id
     AND progressive.team_id = a.team_id
     AND progressive.player_id = a.player_id
     AND progressive.stat_key = 'progressiveBallCarriesCount'
    LEFT JOIN raw.sofascore_player_match_stats pass_value
      ON pass_value.match_id = a.match_id
     AND pass_value.team_id = a.team_id
     AND pass_value.player_id = a.player_id
     AND pass_value.stat_key = 'passValueNormalized'
    LEFT JOIN raw.sofascore_player_match_stats shot_value
      ON shot_value.match_id = a.match_id
     AND shot_value.team_id = a.team_id
     AND shot_value.player_id = a.player_id
     AND shot_value.stat_key = 'shotValueNormalized'
    LEFT JOIN raw.sofascore_player_match_stats dribble_value
      ON dribble_value.match_id = a.match_id
     AND dribble_value.team_id = a.team_id
     AND dribble_value.player_id = a.player_id
     AND dribble_value.stat_key = 'dribbleValueNormalized'
    LEFT JOIN raw.sofascore_player_match_stats defensive_value
      ON defensive_value.match_id = a.match_id
     AND defensive_value.team_id = a.team_id
     AND defensive_value.player_id = a.player_id
     AND defensive_value.stat_key = 'defensiveValueNormalized'
    LEFT JOIN raw.sofascore_player_match_stats tackles
      ON tackles.match_id = a.match_id
     AND tackles.team_id = a.team_id
     AND tackles.player_id = a.player_id
     AND tackles.stat_key = 'wonTackle'
    LEFT JOIN raw.sofascore_player_match_stats interceptions
      ON interceptions.match_id = a.match_id
     AND interceptions.team_id = a.team_id
     AND interceptions.player_id = a.player_id
     AND interceptions.stat_key = 'interceptionWon'
    LEFT JOIN raw.sofascore_player_match_stats saves
      ON saves.match_id = a.match_id
     AND saves.team_id = a.team_id
     AND saves.player_id = a.player_id
     AND saves.stat_key = 'saves'
    LEFT JOIN raw.sofascore_player_match_stats goals_prevented
      ON goals_prevented.match_id = a.match_id
     AND goals_prevented.team_id = a.team_id
     AND goals_prevented.player_id = a.player_id
     AND goals_prevented.stat_key = 'goalsPrevented'
    WHERE minutes.value_numeric > 0
),
player_recent AS (
    SELECT
        target.match_id,
        target.team_id,
        prior.player_id,
        SUM(prior.minutes_played * recency.weight) AS recent_minutes,
        SUM(prior.xg_per90 * prior.minutes_played * recency.weight) / NULLIF(SUM(prior.minutes_played * recency.weight) FILTER (WHERE prior.xg_per90 IS NOT NULL), 0) AS xg_per90,
        SUM(prior.xa_per90 * prior.minutes_played * recency.weight) / NULLIF(SUM(prior.minutes_played * recency.weight) FILTER (WHERE prior.xa_per90 IS NOT NULL), 0) AS xa_per90,
        SUM(prior.key_pass_per90 * prior.minutes_played * recency.weight) / NULLIF(SUM(prior.minutes_played * recency.weight) FILTER (WHERE prior.key_pass_per90 IS NOT NULL), 0) AS key_pass_per90,
        SUM(prior.progressive_carries_per90 * prior.minutes_played * recency.weight) / NULLIF(SUM(prior.minutes_played * recency.weight) FILTER (WHERE prior.progressive_carries_per90 IS NOT NULL), 0) AS progressive_carries_per90,
        SUM(prior.player_value * prior.minutes_played * recency.weight) / NULLIF(SUM(prior.minutes_played * recency.weight) FILTER (WHERE prior.player_value IS NOT NULL), 0) AS player_value,
        MAX(prior.market_value_m) AS market_value_m,
        SUM(prior.def_actions_per90 * prior.minutes_played * recency.weight) / NULLIF(SUM(prior.minutes_played * recency.weight) FILTER (WHERE prior.def_actions_per90 IS NOT NULL), 0) AS def_actions_per90,
        SUM(prior.goalkeeper_strength_per90 * prior.minutes_played * recency.weight) / NULLIF(SUM(prior.minutes_played * recency.weight) FILTER (WHERE prior.goalkeeper_strength_per90 IS NOT NULL), 0) AS goalkeeper_strength_per90
    FROM features.sofascore_team_match_aggregates target
    JOIN active_player_values prior
      ON prior.team_id = target.team_id
     AND prior.start_datetime < target.start_datetime
    CROSS JOIN LATERAL (
        SELECT 1.0 / (
            1.0
            + EXTRACT(EPOCH FROM (target.start_datetime - prior.start_datetime)) / 86400.0 / 180.0
        ) AS weight
    ) recency
    GROUP BY target.match_id, target.team_id, prior.player_id
),
likely_xi AS (
    SELECT
        player_recent.*,
        ROW_NUMBER() OVER (
            PARTITION BY player_recent.match_id, player_recent.team_id
            ORDER BY player_recent.recent_minutes DESC, player_recent.player_id
        ) AS player_rank
    FROM player_recent
),
lineup_proxy AS (
    SELECT
        match_id,
        team_id,
        SUM(xg_per90) FILTER (WHERE xg_per90 IS NOT NULL) AS xi_xg_sum,
        SUM(xa_per90) FILTER (WHERE xa_per90 IS NOT NULL) AS xi_xa_sum,
        SUM(key_pass_per90) FILTER (WHERE key_pass_per90 IS NOT NULL) AS xi_key_pass_sum,
        SUM(progressive_carries_per90) FILTER (WHERE progressive_carries_per90 IS NOT NULL) AS xi_progressive_carries,
        SUM(player_value) FILTER (WHERE player_value IS NOT NULL) AS xi_player_value_sum,
        SUM(market_value_m) FILTER (WHERE market_value_m IS NOT NULL) AS xi_market_value_sum,
        SUM(def_actions_per90) FILTER (WHERE def_actions_per90 IS NOT NULL) AS xi_def_actions,
        SUM(goalkeeper_strength_per90) FILTER (WHERE goalkeeper_strength_per90 IS NOT NULL) AS xi_goalkeeper_strength
    FROM likely_xi
    WHERE player_rank <= 11
    GROUP BY match_id, team_id
)
SELECT
    f.match_id,
    f.sofascore_event_id,
    f.season_year,
    f.match_date,
    f.team_id,
    f.opponent_id,
    f.team_name,
    f.opponent_name,
    f.side,
    {target_expression} AS {target_column},
    {baseline_expression} AS baseline_prediction,
    f.xg_actual IS NOT NULL AS xg_feature_available,
    CASE WHEN f.side = 'home' THEN 1 ELSE 0 END AS is_home,
    COALESCE(context.rest_days, 14.0) AS rest_days,
    context.matches_last_7_days,
    context.matches_last_14_days,
    rolling.rolling_history_count,
    rolling.rolling_xg_for_5_available_count,
    rolling.rolling_xg_against_5_available_count,
    rolling.rolling_shots_5_available_count,
    rolling.rolling_shots_against_5_available_count,
    rolling.feature_coverage_score,
    rolling.rolling_xg_for_3,
    rolling.rolling_xg_for_5,
    rolling.rolling_xg_for_10,
    rolling.rolling_xg_against_5,
    rolling.rolling_shots_5,
    rolling.rolling_shots_against_5,
    rolling.rolling_big_chances_5,
    rolling.shot_accuracy_5,
    rolling.tackles_won_5,
    rolling.interceptions_5,
    rolling.blocks_5,
    rolling.possession_proxy_5,
    rolling.passes_per90_5,
    rolling.rolling_tempo_count,
    rolling.tempo_feature_coverage_score,
    rolling.extended_feature_coverage_score,
    rolling.rolling_tempo_shots_5,
    rolling.rolling_tempo_box_touches_5,
    rolling.rolling_tempo_final_third_entries_5,
    rolling.rolling_tempo_corners_5,
    rolling.rolling_tempo_passes_5,
    rolling.rolling_tempo_pass_accuracy_5,
    rolling.rolling_tempo_directness_5,
    rolling.rolling_box_pressure_index_5,
    rolling.rolling_xgot_for_5,
    rolling.rolling_shot_value_5,
    rolling.rolling_pass_value_5,
    rolling.rolling_progression_5,
    rolling.rolling_carry_distance_5,
    rolling.rolling_opp_half_pass_accuracy_5,
    rolling.rolling_dribble_success_5,
    rolling.rolling_fouls_won_5,
    rolling.rolling_clearances_5,
    rolling.rolling_keeper_value_5,
    rolling.rolling_cross_accuracy_5,
    rolling.rolling_long_ball_accuracy_5,
    rolling.rolling_big_chance_conversion_5,
    rolling.rolling_shot_box_share_5,
    CASE WHEN COALESCE(f.confirmed_lineup, false) THEN 1 ELSE 0 END AS confirmed_lineup,
    COALESCE(f.formation_code, 442) AS formation_code,
    COALESCE(f.starter_market_value_eur, f.listed_market_value_eur, 250000000) / 1000000.0 AS starter_market_value_m,
    COALESCE(f.missing_market_value_eur, 0) / 1000000.0 AS missing_market_value_m,
    COALESCE(f.doubtful_market_value_eur, 0) / 1000000.0 AS doubtful_market_value_m,
    COALESCE(f.missing_player_count, 0) AS missing_player_count,
    COALESCE(f.doubtful_player_count, 0) AS doubtful_player_count,
    COALESCE(f.starter_avg_age_years, f.listed_avg_age_years, 27.0) AS starter_avg_age_years,
    COALESCE(f.starter_defender_count, 4.0) AS starter_defender_count,
    COALESCE(f.starter_midfielder_count, 4.0) AS starter_midfielder_count,
    COALESCE(f.starter_forward_count, 2.0) AS starter_forward_count,
    opponent_rolling.rolling_xg_for_5 AS opp_rolling_xg_for_5,
    opponent_rolling.rolling_xg_against_5 AS opp_rolling_xg_against_5,
    opponent_rolling.shot_accuracy_5 AS opp_shot_accuracy_5,
    opponent_rolling.rolling_shots_5 AS opp_rolling_shots_5,
    opponent_rolling.rolling_shots_against_5 AS opp_rolling_shots_against_5,
    opponent_rolling.rolling_history_count AS opp_rolling_history_count,
    opponent_rolling.feature_coverage_score AS opp_feature_coverage_score,
    opponent_rolling.rolling_tempo_count AS opp_rolling_tempo_count,
    opponent_rolling.tempo_feature_coverage_score AS opp_tempo_feature_coverage_score,
    opponent_rolling.rolling_tempo_shots_5 AS opp_rolling_tempo_shots_5,
    opponent_rolling.rolling_tempo_box_touches_5 AS opp_rolling_tempo_box_touches_5,
    opponent_rolling.rolling_tempo_final_third_entries_5 AS opp_rolling_tempo_final_third_entries_5,
    opponent_rolling.rolling_tempo_corners_5 AS opp_rolling_tempo_corners_5,
    opponent_rolling.rolling_tempo_passes_5 AS opp_rolling_tempo_passes_5,
    opponent_rolling.rolling_tempo_pass_accuracy_5 AS opp_rolling_tempo_pass_accuracy_5,
    opponent_rolling.rolling_tempo_directness_5 AS opp_rolling_tempo_directness_5,
    opponent_rolling.rolling_box_pressure_index_5 AS opp_rolling_box_pressure_index_5,
    opponent_rolling.rolling_xgot_for_5 AS opp_rolling_xgot_for_5,
    opponent_rolling.rolling_shot_value_5 AS opp_rolling_shot_value_5,
    opponent_rolling.rolling_progression_5 AS opp_rolling_progression_5,
    opponent_rolling.rolling_dribble_success_5 AS opp_rolling_dribble_success_5,
    opponent_rolling.rolling_cross_accuracy_5 AS opp_rolling_cross_accuracy_5,
    opponent_rolling.rolling_shot_box_share_5 AS opp_rolling_shot_box_share_5,
    COALESCE(opponent_features.starter_market_value_eur, opponent_features.listed_market_value_eur, 250000000) / 1000000.0 AS opp_starter_market_value_m,
    COALESCE(opponent_features.missing_market_value_eur, 0) / 1000000.0 AS opp_missing_market_value_m,
    COALESCE(opponent_features.missing_player_count, 0) AS opp_missing_player_count,
    rolling.rolling_xg_for_5 / NULLIF(opponent_rolling.rolling_xg_against_5, 0) AS adj_attack_xg_5,
    rolling.rolling_xg_against_5 / NULLIF(opponent_rolling.rolling_xg_for_5, 0) AS adj_defence_xg_5,
    rolling.rolling_progression_5 / NULLIF(opponent_rolling.rolling_progression_5, 0) AS adj_progression_5,
    COALESCE(f.starter_market_value_eur, f.listed_market_value_eur, 250000000)
        / NULLIF(COALESCE(opponent_features.starter_market_value_eur, opponent_features.listed_market_value_eur, 250000000), 0)
        AS adj_roster_value,
    (
        COALESCE(rolling.team_tempo_index, 1.0)
        + COALESCE(opponent_rolling.team_tempo_index, 1.0)
    ) / 2.0 AS match_tempo_index,
    COALESCE(lineup_proxy.xi_xg_sum, rolling.rolling_xg_for_5) AS xi_xg_sum,
    COALESCE(lineup_proxy.xi_xa_sum, rolling.rolling_xg_for_5 * 0.65) AS xi_xa_sum,
    COALESCE(lineup_proxy.xi_key_pass_sum, 5.0) AS xi_key_pass_sum,
    COALESCE(lineup_proxy.xi_progressive_carries, 20.0) AS xi_progressive_carries,
    COALESCE(lineup_proxy.xi_def_actions, 45.0) AS xi_def_actions,
    COALESCE(lineup_proxy.xi_goalkeeper_strength, 3.0) AS xi_goalkeeper_strength,
    COALESCE(lineup_proxy.xi_player_value_sum, 0.0) AS xi_player_value_sum
FROM features.sofascore_team_match_features f
LEFT JOIN rolling
  ON rolling.match_id = f.match_id
 AND rolling.team_id = f.team_id
LEFT JOIN rolling opponent_rolling
  ON opponent_rolling.match_id = f.match_id
 AND opponent_rolling.team_id = f.opponent_id
LEFT JOIN context
  ON context.match_id = f.match_id
 AND context.team_id = f.team_id
LEFT JOIN lineup_proxy
  ON lineup_proxy.match_id = f.match_id
 AND lineup_proxy.team_id = f.team_id
LEFT JOIN features.sofascore_team_match_features opponent_features
  ON opponent_features.match_id = f.match_id
 AND opponent_features.team_id = f.opponent_id
{where_clause}
ORDER BY f.start_datetime, f.match_id, f.side DESC;
"""


def parse_seasons(value: str | None) -> tuple[str, ...]:
    if not value:
        return DEFAULT_TRAIN_SEASONS
    seasons = tuple(item.strip() for item in value.split(",") if item.strip())
    if not seasons:
        raise ValueError("at least one train season is required")
    return seasons


def artifact_paths(model_dir: Path) -> dict[str, Path]:
    return {
        "model": model_dir / "model.json",
        "metadata": model_dir / "metadata.json",
        "feature_columns": model_dir / "feature_columns.json",
        "validation_predictions": model_dir / "validation_predictions.csv",
        "feature_importance": model_dir / "feature_importance.csv",
        "cross_validation_results": model_dir / "cross_validation_results.csv",
    }


def resolve_model_spec(model_name: str = "xg_for") -> ModelSpec:
    try:
        return MODEL_SPECS[model_name]
    except KeyError as exc:
        choices = ", ".join(sorted(MODEL_SPECS))
        raise ValueError(f"Unknown model '{model_name}'. Choose one of: {choices}") from exc


def effective_min_shots(model_spec: ModelSpec, min_shots: int | None = None) -> int | None:
    if model_spec.default_min_shots is None:
        return None
    return model_spec.default_min_shots if min_shots is None else min_shots


def target_expression(model_spec: ModelSpec) -> str:
    if model_spec.name == "xg_for":
        return "f.xg_actual"
    if model_spec.name == "shot_quality":
        return (
            "CASE WHEN f.xg_actual IS NOT NULL AND f.shots_actual IS NOT NULL "
            "THEN LEAST(GREATEST(f.xg_actual / GREATEST(f.shots_actual, 1), 0.0), 0.5) END"
        )
    if model_spec.name == "fragility":
        return (
            "CASE WHEN f.xg_against_actual IS NOT NULL AND f.shots_against_actual IS NOT NULL "
            "THEN LEAST(GREATEST(f.xg_against_actual / GREATEST(f.shots_against_actual, 1), 0.0), 0.5) END"
        )
    raise ValueError(f"Unsupported model spec: {model_spec.name}")


def baseline_expression(model_spec: ModelSpec) -> str:
    if model_spec.name == "xg_for":
        return "rolling.rolling_xg_for_5"
    if model_spec.name == "shot_quality":
        return (
            "CASE WHEN rolling.rolling_xg_for_5 IS NOT NULL "
            "AND rolling.rolling_shots_5 IS NOT NULL "
            "THEN LEAST(GREATEST(rolling.rolling_xg_for_5 / "
            "GREATEST(rolling.rolling_shots_5, 1), 0.0), 0.5) END"
        )
    if model_spec.name == "fragility":
        return (
            "CASE WHEN rolling.rolling_xg_against_5 IS NOT NULL "
            "AND rolling.rolling_shots_against_5 IS NOT NULL "
            "THEN LEAST(GREATEST(rolling.rolling_xg_against_5 / "
            "GREATEST(rolling.rolling_shots_against_5, 1), 0.0), 0.5) END"
        )
    raise ValueError(f"Unsupported model spec: {model_spec.name}")


def labelled_filter(model_spec: ModelSpec, min_shots: int | None = None) -> str:
    if model_spec.name == "xg_for":
        return "f.xg_actual IS NOT NULL"
    min_shots = effective_min_shots(model_spec, min_shots)
    if model_spec.name == "shot_quality":
        return (
            "f.xg_actual IS NOT NULL "
            "AND f.shots_actual IS NOT NULL "
            f"AND f.shots_actual >= {int(min_shots)}"
        )
    if model_spec.name == "fragility":
        return (
            "f.xg_against_actual IS NOT NULL "
            "AND f.shots_against_actual IS NOT NULL "
            f"AND f.shots_against_actual >= {int(min_shots)}"
        )
    raise ValueError(f"Unsupported model spec: {model_spec.name}")


def best_iteration_count(model) -> int:
    best_iteration = getattr(model, "best_iteration", None)
    if best_iteration is None:
        return int(model.get_params().get("n_estimators", MODEL_PARAMS["n_estimators"]))
    return int(best_iteration) + 1


def build_where_clause(
    labelled_only: bool = False,
    match_id: int | None = None,
    sofascore_event_id: int | None = None,
    model_spec: ModelSpec | None = None,
    min_shots: int | None = None,
) -> str:
    model_spec = model_spec or MODEL_SPECS["xg_for"]
    filters = []
    if labelled_only:
        filters.append(labelled_filter(model_spec, min_shots=min_shots))
    if match_id is not None:
        filters.append(f"f.match_id = {int(match_id)}")
    if sofascore_event_id is not None:
        filters.append(f"f.sofascore_event_id = {int(sofascore_event_id)}")
    return "WHERE " + " AND ".join(filters) if filters else ""


def build_model_dataset_sql(
    labelled_only: bool = False,
    match_id: int | None = None,
    sofascore_event_id: int | None = None,
    model_spec: ModelSpec | None = None,
    min_shots: int | None = None,
) -> str:
    model_spec = model_spec or MODEL_SPECS["xg_for"]
    return (
        MODEL_DATASET_SQL.replace("{target_expression}", target_expression(model_spec))
        .replace("{target_column}", model_spec.target_column)
        .replace("{baseline_expression}", baseline_expression(model_spec))
        .replace(
            "{where_clause}",
            build_where_clause(
                labelled_only=labelled_only,
                match_id=match_id,
                sofascore_event_id=sofascore_event_id,
                model_spec=model_spec,
                min_shots=min_shots,
            ),
        )
    )


def require_runtime_dependencies() -> tuple[Any, Any, Any]:
    try:
        import numpy as np
        import pandas as pd
        from xgboost import XGBRegressor
    except ImportError as exc:
        raise SystemExit(
            "Missing ML runtime dependency. Install requirements first: "
            "python3 -m pip install -r requirements.txt"
        ) from exc
    return np, pd, XGBRegressor


def load_dataset(
    db_url: str,
    labelled_only: bool = False,
    match_id: int | None = None,
    sofascore_event_id: int | None = None,
    model_spec: ModelSpec | None = None,
    min_shots: int | None = None,
):
    _, pd, _ = require_runtime_dependencies()
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise SystemExit(
            "Missing database dependency. Install requirements first: "
            "python3 -m pip install -r requirements.txt"
        ) from exc

    sql = build_model_dataset_sql(
        labelled_only=labelled_only,
        match_id=match_id,
        sofascore_event_id=sofascore_event_id,
        model_spec=model_spec,
        min_shots=min_shots,
    )
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    return pd.DataFrame(rows)


def train_validation_split(df, train_seasons: tuple[str, ...], validation_season: str):
    train = df[df["season_year"].isin(train_seasons)].copy()
    validation = df[df["season_year"] == validation_season].copy()
    if train.empty:
        raise ValueError(f"No training rows found for seasons: {', '.join(train_seasons)}")
    if validation.empty:
        raise ValueError(f"No validation rows found for season: {validation_season}")
    max_train_date = train["match_date"].max()
    min_validation_date = validation["match_date"].min()
    if max_train_date >= min_validation_date:
        raise ValueError(
            "Validation period must be strictly after training period. "
            f"max_train_date={max_train_date}, min_validation_date={min_validation_date}"
        )
    return train, validation


def season_start_year(season: str) -> int:
    start = int(season.split("/", 1)[0])
    return 1900 + start if start >= 90 else 2000 + start


def ordered_seasons(seasons) -> tuple[str, ...]:
    return tuple(sorted(set(seasons), key=season_start_year))


def build_cross_validation_folds(
    seasons,
    validation_seasons: tuple[str, ...] | None = None,
    min_train_seasons: int = 1,
) -> list[dict[str, Any]]:
    available = ordered_seasons(seasons)
    validation_set = set(validation_seasons or available[1:])
    folds = []
    for validation_season in available:
        if validation_season not in validation_set:
            continue
        train_seasons = tuple(
            season
            for season in available
            if season_start_year(season) < season_start_year(validation_season)
        )
        if len(train_seasons) < min_train_seasons:
            continue
        folds.append(
            {
                "train_seasons": train_seasons,
                "validation_season": validation_season,
            }
        )
    if not folds:
        raise ValueError("No valid time-series cross-validation folds could be built")
    return folds


def prepare_model_dataframe(df, pd, model_spec: ModelSpec | None = None):
    model_spec = model_spec or MODEL_SPECS["xg_for"]
    df = df.copy()
    df[FEATURE_COLUMNS] = df[FEATURE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    df[model_spec.target_column] = pd.to_numeric(
        df[model_spec.target_column],
        errors="coerce",
    )
    df[BASELINE_COLUMN] = pd.to_numeric(df[BASELINE_COLUMN], errors="coerce")
    return df


def existing_columns(df, columns: list[str]) -> list[str]:
    return [column for column in columns if column in df.columns]


def metric_summary(actual, predicted, baseline, np) -> dict[str, float | None]:
    actual_values = np.asarray(actual, dtype=float)
    predicted_values = np.asarray(predicted, dtype=float)
    errors = predicted_values - actual_values
    metrics: dict[str, float | None] = {
        "rmse": float(np.sqrt(np.mean(errors**2))),
        "mae": float(np.mean(np.abs(errors))),
    }

    baseline_values = np.asarray(baseline, dtype=float)
    baseline_mask = ~np.isnan(baseline_values)
    if baseline_mask.any():
        baseline_errors = baseline_values[baseline_mask] - actual_values[baseline_mask]
        metrics["baseline_rmse"] = float(np.sqrt(np.mean(baseline_errors**2)))
        metrics["baseline_mae"] = float(np.mean(np.abs(baseline_errors)))
        metrics["baseline_rows"] = int(baseline_mask.sum())
    else:
        metrics["baseline_rmse"] = None
        metrics["baseline_mae"] = None
        metrics["baseline_rows"] = 0
    return metrics


def clip_predictions(values, clip_min: float, clip_max: float, np):
    return np.clip(values, clip_min, clip_max)


def save_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")


def save_feature_importance(path: Path, model, feature_columns: list[str]) -> None:
    scores = model.get_booster().get_score(importance_type="gain")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["feature", "gain"])
        writer.writeheader()
        for feature in feature_columns:
            writer.writerow({"feature": feature, "gain": scores.get(feature, 0.0)})


def fit_regressor(
    XGBRegressor,
    train,
    validation,
    early_stopping_rounds: int,
    model_spec: ModelSpec | None = None,
):
    model_spec = model_spec or MODEL_SPECS["xg_for"]
    params = dict(MODEL_PARAMS)
    params["early_stopping_rounds"] = early_stopping_rounds
    model = XGBRegressor(**params)
    model.fit(
        train[FEATURE_COLUMNS],
        train[model_spec.target_column].astype(float),
        eval_set=[
            (
                validation[FEATURE_COLUMNS],
                validation[model_spec.target_column].astype(float),
            )
        ],
        verbose=False,
    )
    return model, params


def fit_final_regressor(
    XGBRegressor,
    df,
    n_estimators: int,
    model_spec: ModelSpec | None = None,
):
    model_spec = model_spec or MODEL_SPECS["xg_for"]
    params = dict(MODEL_PARAMS)
    params["n_estimators"] = int(n_estimators)
    model = XGBRegressor(**params)
    model.fit(
        df[FEATURE_COLUMNS],
        df[model_spec.target_column].astype(float),
        verbose=False,
    )
    return model, params


def train_model(
    db_url: str,
    model_dir: Path,
    train_seasons: tuple[str, ...],
    validation_season: str,
    clip_min: float,
    clip_max: float,
    early_stopping_rounds: int,
    model_spec: ModelSpec | None = None,
    min_shots: int | None = None,
) -> dict[str, Any]:
    model_spec = model_spec or MODEL_SPECS["xg_for"]
    np, pd, XGBRegressor = require_runtime_dependencies()
    df = prepare_model_dataframe(
        load_dataset(
            db_url,
            labelled_only=True,
            model_spec=model_spec,
            min_shots=min_shots,
        ),
        pd,
        model_spec=model_spec,
    )
    train, validation = train_validation_split(df, train_seasons, validation_season)

    x_validation = validation[FEATURE_COLUMNS]
    y_validation = validation[model_spec.target_column].astype(float)

    model, params = fit_regressor(
        XGBRegressor,
        train=train,
        validation=validation,
        early_stopping_rounds=early_stopping_rounds,
        model_spec=model_spec,
    )

    validation_predictions = clip_predictions(
        model.predict(x_validation),
        clip_min=clip_min,
        clip_max=clip_max,
        np=np,
    )
    metrics = metric_summary(
        actual=y_validation,
        predicted=validation_predictions,
        baseline=validation[BASELINE_COLUMN].astype(float),
        np=np,
    )

    model_dir.mkdir(parents=True, exist_ok=True)
    paths = artifact_paths(model_dir)
    model.save_model(paths["model"])
    save_json(paths["feature_columns"], FEATURE_COLUMNS)

    output = validation[
        META_COLUMNS
        + [model_spec.target_column, BASELINE_COLUMN]
        + existing_columns(validation, QUALITY_COLUMNS)
    ].copy()
    output[model_spec.prediction_column] = validation_predictions
    output["prediction_error"] = (
        output[model_spec.prediction_column] - output[model_spec.target_column]
    )
    output.to_csv(paths["validation_predictions"], index=False)
    save_feature_importance(paths["feature_importance"], model, FEATURE_COLUMNS)

    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_name": model_spec.name,
        "target_column": model_spec.target_column,
        "prediction_column": model_spec.prediction_column,
        "baseline_column": BASELINE_COLUMN,
        "train_seasons": list(train_seasons),
        "validation_season": validation_season,
        "train_rows": int(len(train)),
        "validation_rows": int(len(validation)),
        "all_labelled_rows": int(len(df)),
        "feature_count": len(FEATURE_COLUMNS),
        "feature_columns": FEATURE_COLUMNS,
        "quality_columns": QUALITY_COLUMNS,
        "model_params": params,
        "best_iteration": getattr(model, "best_iteration", None),
        "best_iteration_count": best_iteration_count(model),
        "best_score": getattr(model, "best_score", None),
        "clip_min": clip_min,
        "clip_max": clip_max,
        "min_shots": effective_min_shots(model_spec, min_shots),
        "metrics": metrics,
    }
    save_json(paths["metadata"], metadata)
    return metadata


def train_final_model(
    db_url: str,
    model_dir: Path,
    source_model_dir: Path,
    clip_min: float,
    clip_max: float,
    early_stopping_rounds: int,
    refresh_source_train: bool,
    model_spec: ModelSpec | None = None,
    min_shots: int | None = None,
) -> dict[str, Any]:
    model_spec = model_spec or MODEL_SPECS["xg_for"]
    _, pd, XGBRegressor = require_runtime_dependencies()
    source_paths = artifact_paths(source_model_dir)
    source_metadata: dict[str, Any] = {}
    if refresh_source_train or not source_paths["metadata"].exists():
        source_metadata = train_model(
            db_url=db_url,
            model_dir=source_model_dir,
            train_seasons=DEFAULT_TRAIN_SEASONS,
            validation_season=DEFAULT_VALIDATION_SEASON,
            clip_min=clip_min,
            clip_max=clip_max,
            early_stopping_rounds=early_stopping_rounds,
            model_spec=model_spec,
            min_shots=min_shots,
        )
    else:
        source_metadata = json.loads(source_paths["metadata"].read_text(encoding="utf-8"))

    best_rounds = source_metadata.get("best_iteration_count")
    if best_rounds is None:
        source_metadata = train_model(
            db_url=db_url,
            model_dir=source_model_dir,
            train_seasons=DEFAULT_TRAIN_SEASONS,
            validation_season=DEFAULT_VALIDATION_SEASON,
            clip_min=clip_min,
            clip_max=clip_max,
            early_stopping_rounds=early_stopping_rounds,
            model_spec=model_spec,
            min_shots=min_shots,
        )
        best_rounds = source_metadata["best_iteration_count"]

    df = prepare_model_dataframe(
        load_dataset(
            db_url,
            labelled_only=True,
            model_spec=model_spec,
            min_shots=min_shots,
        ),
        pd,
        model_spec=model_spec,
    )
    model, params = fit_final_regressor(
        XGBRegressor,
        df=df,
        n_estimators=int(best_rounds),
        model_spec=model_spec,
    )

    model_dir.mkdir(parents=True, exist_ok=True)
    paths = artifact_paths(model_dir)
    model.save_model(paths["model"])
    save_json(paths["feature_columns"], FEATURE_COLUMNS)
    save_feature_importance(paths["feature_importance"], model, FEATURE_COLUMNS)

    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "final",
        "model_name": model_spec.name,
        "target_column": model_spec.target_column,
        "prediction_column": model_spec.prediction_column,
        "baseline_column": BASELINE_COLUMN,
        "train_seasons": list(ordered_seasons(df["season_year"].unique())),
        "train_rows": int(len(df)),
        "feature_count": len(FEATURE_COLUMNS),
        "feature_columns": FEATURE_COLUMNS,
        "quality_columns": QUALITY_COLUMNS,
        "model_params": params,
        "source_model_dir": str(source_model_dir),
        "source_validation_season": source_metadata.get("validation_season"),
        "source_metrics": source_metadata.get("metrics"),
        "source_best_iteration": source_metadata.get("best_iteration"),
        "source_best_iteration_count": int(best_rounds),
        "source_best_score": source_metadata.get("best_score"),
        "clip_min": clip_min,
        "clip_max": clip_max,
        "min_shots": effective_min_shots(model_spec, min_shots),
    }
    save_json(paths["metadata"], metadata)
    return metadata


def aggregate_fold_metrics(folds: list[dict[str, Any]]) -> dict[str, float | None]:
    weighted: dict[str, float | None] = {}
    for metric_name in ("rmse", "mae"):
        total_rows = sum(fold["validation_rows"] for fold in folds)
        weighted[metric_name] = (
            sum(fold[metric_name] * fold["validation_rows"] for fold in folds)
            / total_rows
            if total_rows
            else None
        )
    for metric_name in ("baseline_rmse", "baseline_mae"):
        numerator = 0.0
        denominator = 0
        for fold in folds:
            if fold[metric_name] is None:
                continue
            numerator += fold[metric_name] * fold["baseline_rows"]
            denominator += fold["baseline_rows"]
        weighted[metric_name] = numerator / denominator if denominator else None
    weighted["validation_rows"] = sum(fold["validation_rows"] for fold in folds)
    weighted["baseline_rows"] = sum(fold["baseline_rows"] for fold in folds)
    return weighted


def cross_validate_model(
    db_url: str,
    output_path: Path,
    validation_seasons: tuple[str, ...],
    clip_min: float,
    clip_max: float,
    early_stopping_rounds: int,
    min_train_seasons: int,
    model_spec: ModelSpec | None = None,
    min_shots: int | None = None,
) -> dict[str, Any]:
    model_spec = model_spec or MODEL_SPECS["xg_for"]
    np, pd, XGBRegressor = require_runtime_dependencies()
    df = prepare_model_dataframe(
        load_dataset(
            db_url,
            labelled_only=True,
            model_spec=model_spec,
            min_shots=min_shots,
        ),
        pd,
        model_spec=model_spec,
    )
    folds = build_cross_validation_folds(
        df["season_year"].unique(),
        validation_seasons=validation_seasons,
        min_train_seasons=min_train_seasons,
    )

    rows = []
    for fold in folds:
        train, validation = train_validation_split(
            df,
            train_seasons=fold["train_seasons"],
            validation_season=fold["validation_season"],
        )
        model, _ = fit_regressor(
            XGBRegressor,
            train=train,
            validation=validation,
            early_stopping_rounds=early_stopping_rounds,
            model_spec=model_spec,
        )
        predictions = clip_predictions(
            model.predict(validation[FEATURE_COLUMNS]),
            clip_min=clip_min,
            clip_max=clip_max,
            np=np,
        )
        metrics = metric_summary(
            actual=validation[model_spec.target_column].astype(float),
            predicted=predictions,
            baseline=validation[BASELINE_COLUMN].astype(float),
            np=np,
        )
        rows.append(
            {
                "train_seasons": ",".join(fold["train_seasons"]),
                "validation_season": fold["validation_season"],
                "train_rows": int(len(train)),
                "validation_rows": int(len(validation)),
                **metrics,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "train_seasons",
            "validation_season",
            "train_rows",
            "validation_rows",
            "rmse",
            "mae",
            "baseline_rmse",
            "baseline_mae",
            "baseline_rows",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_name": model_spec.name,
        "target_column": model_spec.target_column,
        "prediction_column": model_spec.prediction_column,
        "min_shots": effective_min_shots(model_spec, min_shots),
        "folds": rows,
        "weighted_average": aggregate_fold_metrics(rows),
        "output_path": str(output_path),
    }


def load_model_and_features(model_dir: Path):
    _, _, XGBRegressor = require_runtime_dependencies()
    paths = artifact_paths(model_dir)
    if not paths["model"].exists() or not paths["feature_columns"].exists():
        raise SystemExit(f"Model artifacts not found in {model_dir}. Run train first.")
    model = XGBRegressor()
    model.load_model(paths["model"])
    feature_columns = json.loads(paths["feature_columns"].read_text(encoding="utf-8"))
    metadata = {}
    if paths["metadata"].exists():
        metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    return model, feature_columns, metadata


def predict_dataset(df, model, feature_columns: list[str], clip_min: float, clip_max: float):
    np, pd, _ = require_runtime_dependencies()
    features = df[feature_columns].apply(pd.to_numeric, errors="coerce")
    predictions = model.predict(features)
    return clip_predictions(predictions, clip_min=clip_min, clip_max=clip_max, np=np)


def validate_loaded_model_spec(metadata: dict[str, Any], model_spec: ModelSpec) -> None:
    metadata_model = metadata.get("model_name")
    if metadata_model and metadata_model != model_spec.name:
        raise SystemExit(
            f"Loaded model is for '{metadata_model}', but --model is '{model_spec.name}'."
        )


def predict_history(
    db_url: str,
    model_dir: Path,
    output_path: Path,
    model_spec: ModelSpec | None = None,
    min_shots: int | None = None,
) -> int:
    model_spec = model_spec or MODEL_SPECS["xg_for"]
    _, pd, _ = require_runtime_dependencies()
    model, feature_columns, metadata = load_model_and_features(model_dir)
    validate_loaded_model_spec(metadata, model_spec)
    clip_min = float(metadata.get("clip_min", model_spec.clip_min))
    clip_max = float(metadata.get("clip_max", model_spec.clip_max))
    df = load_dataset(
        db_url,
        labelled_only=True,
        model_spec=model_spec,
        min_shots=min_shots,
    )
    df[model_spec.prediction_column] = predict_dataset(
        df,
        model,
        feature_columns,
        clip_min,
        clip_max,
    )
    if model_spec.target_column in df:
        df[model_spec.target_column] = pd.to_numeric(
            df[model_spec.target_column],
            errors="coerce",
        )
        df["prediction_error"] = (
            df[model_spec.prediction_column] - df[model_spec.target_column]
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df[
        META_COLUMNS
        + existing_columns(df, QUALITY_COLUMNS)
        + [model_spec.target_column, model_spec.prediction_column, "prediction_error"]
    ].to_csv(output_path, index=False)
    return len(df)


def predict_match(
    db_url: str,
    model_dir: Path,
    output_path: Path | None,
    match_id: int | None,
    sofascore_event_id: int | None,
    model_spec: ModelSpec | None = None,
    min_shots: int | None = None,
) -> int:
    model_spec = model_spec or MODEL_SPECS["xg_for"]
    if match_id is None and sofascore_event_id is None:
        raise SystemExit("predict-match requires --match-id or --sofascore-event-id")
    model, feature_columns, metadata = load_model_and_features(model_dir)
    validate_loaded_model_spec(metadata, model_spec)
    clip_min = float(metadata.get("clip_min", model_spec.clip_min))
    clip_max = float(metadata.get("clip_max", model_spec.clip_max))
    df = load_dataset(
        db_url,
        labelled_only=False,
        match_id=match_id,
        sofascore_event_id=sofascore_event_id,
        model_spec=model_spec,
        min_shots=min_shots,
    )
    if df.empty:
        raise SystemExit("No feature rows found for requested match")
    df[model_spec.prediction_column] = predict_dataset(
        df,
        model,
        feature_columns,
        clip_min,
        clip_max,
    )
    columns = (
        META_COLUMNS
        + existing_columns(df, QUALITY_COLUMNS)
        + [model_spec.target_column, model_spec.prediction_column]
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df[columns].to_csv(output_path, index=False)
    else:
        print(df[columns].to_string(index=False))
    return len(df)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train and run XGBoost football signal regression models."
    )
    parser.add_argument(
        "--model",
        choices=sorted(MODEL_SPECS),
        default="xg_for",
        help="Model target to train or score. Defaults to xg_for.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DB_URL", DEFAULT_DB_URL),
        help="Postgres connection URL. Defaults to DB_URL or the local docker DB.",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=None,
        help="Directory for model artifacts. Defaults to the selected model directory.",
    )
    parser.add_argument(
        "--min-shots",
        type=int,
        default=None,
        help="Minimum shots for shot_quality/fragility labelled rows. Defaults to 3.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    train_parser = subparsers.add_parser(
        "train",
        help="Train and save the selected validation model.",
    )
    train_parser.add_argument(
        "--train-seasons",
        default=",".join(DEFAULT_TRAIN_SEASONS),
        help="Comma-separated season_year values used for training.",
    )
    train_parser.add_argument(
        "--validation-season",
        default=DEFAULT_VALIDATION_SEASON,
        help="Future season_year used for validation.",
    )
    train_parser.add_argument("--clip-min", type=float, default=None)
    train_parser.add_argument("--clip-max", type=float, default=None)
    train_parser.add_argument("--early-stopping-rounds", type=int, default=50)

    final_parser = subparsers.add_parser(
        "train-final",
        help=(
            "Use the validated train run to choose n_estimators, then fit a final "
            "model on all labelled seasons without validation."
        ),
    )
    final_parser.add_argument(
        "--source-model-dir",
        type=Path,
        default=None,
        help="Validated train artifact directory used to read or create best_iteration_count.",
    )
    final_parser.add_argument(
        "--final-model-dir",
        type=Path,
        default=None,
        help="Output directory for the final all-data model.",
    )
    final_parser.add_argument(
        "--refresh-source-train",
        action="store_true",
        help="Rerun the validated train command before fitting the final model.",
    )
    final_parser.add_argument("--clip-min", type=float, default=None)
    final_parser.add_argument("--clip-max", type=float, default=None)
    final_parser.add_argument("--early-stopping-rounds", type=int, default=50)

    cv_parser = subparsers.add_parser(
        "cross-validate",
        help="Run rolling-origin season-based cross-validation without saving a model.",
    )
    cv_parser.add_argument(
        "--validation-seasons",
        default=",".join(DEFAULT_CV_VALIDATION_SEASONS),
        help="Comma-separated season_year values to validate as rolling-origin folds.",
    )
    cv_parser.add_argument(
        "--min-train-seasons",
        type=int,
        default=1,
        help="Minimum number of prior seasons required before a validation fold.",
    )
    cv_parser.add_argument("--clip-min", type=float, default=None)
    cv_parser.add_argument("--clip-max", type=float, default=None)
    cv_parser.add_argument("--early-stopping-rounds", type=int, default=50)
    cv_parser.add_argument(
        "--output",
        type=Path,
        default=None,
    )

    history_parser = subparsers.add_parser(
        "predict-history",
        help="Score all labelled historical feature rows.",
    )
    history_parser.add_argument(
        "--output",
        type=Path,
        default=None,
    )

    match_parser = subparsers.add_parser(
        "predict-match",
        help="Score both team rows for one match.",
    )
    match_parser.add_argument("--match-id", type=int)
    match_parser.add_argument("--sofascore-event-id", type=int)
    match_parser.add_argument("--output", type=Path)

    args = parser.parse_args()
    model_spec = resolve_model_spec(args.model)
    model_dir = args.model_dir or model_spec.default_model_dir
    clip_min = (
        model_spec.clip_min
        if getattr(args, "clip_min", None) is None
        else args.clip_min
    )
    clip_max = (
        model_spec.clip_max
        if getattr(args, "clip_max", None) is None
        else args.clip_max
    )

    if args.command == "train":
        metadata = train_model(
            db_url=args.db_url,
            model_dir=model_dir,
            train_seasons=parse_seasons(args.train_seasons),
            validation_season=args.validation_season,
            clip_min=clip_min,
            clip_max=clip_max,
            early_stopping_rounds=args.early_stopping_rounds,
            model_spec=model_spec,
            min_shots=args.min_shots,
        )
        print(json.dumps(metadata["metrics"], indent=2, sort_keys=True))
        print(f"Saved model artifacts to {model_dir}")
    elif args.command == "train-final":
        source_model_dir = args.source_model_dir or model_spec.default_model_dir
        final_model_dir = args.final_model_dir or model_spec.default_final_model_dir
        metadata = train_final_model(
            db_url=args.db_url,
            model_dir=final_model_dir,
            source_model_dir=source_model_dir,
            clip_min=clip_min,
            clip_max=clip_max,
            early_stopping_rounds=args.early_stopping_rounds,
            refresh_source_train=args.refresh_source_train,
            model_spec=model_spec,
            min_shots=args.min_shots,
        )
        print(json.dumps(metadata, indent=2, sort_keys=True))
        print(f"Saved final model artifacts to {final_model_dir}")
    elif args.command == "cross-validate":
        output = args.output or model_dir / "cross_validation_results.csv"
        results = cross_validate_model(
            db_url=args.db_url,
            output_path=output,
            validation_seasons=parse_seasons(args.validation_seasons),
            clip_min=clip_min,
            clip_max=clip_max,
            early_stopping_rounds=args.early_stopping_rounds,
            min_train_seasons=args.min_train_seasons,
            model_spec=model_spec,
            min_shots=args.min_shots,
        )
        print(json.dumps(results, indent=2, sort_keys=True))
    elif args.command == "predict-history":
        output = args.output or model_dir / "history_predictions.csv"
        rows = predict_history(
            db_url=args.db_url,
            model_dir=model_dir,
            output_path=output,
            model_spec=model_spec,
            min_shots=args.min_shots,
        )
        print(f"Wrote {rows} historical predictions to {output}")
    elif args.command == "predict-match":
        rows = predict_match(
            db_url=args.db_url,
            model_dir=model_dir,
            output_path=args.output,
            match_id=args.match_id,
            sofascore_event_id=args.sofascore_event_id,
            model_spec=model_spec,
            min_shots=args.min_shots,
        )
        if args.output is not None:
            print(f"Wrote {rows} match predictions to {args.output}")


if __name__ == "__main__":
    main()
