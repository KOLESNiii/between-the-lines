import argparse
import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DB_URL = "postgresql://user:pwd@localhost:5432/betting_historical_data"
DEFAULT_MODEL_DIR = Path("models/player_minutes")
DEFAULT_FINAL_MODEL_DIR = Path("models/player_minutes_final")
DEFAULT_TRAIN_SEASONS = ("22/23", "23/24", "24/25")
DEFAULT_VALIDATION_SEASON = "25/26"
DEFAULT_CV_VALIDATION_SEASONS = ("23/24", "24/25", "25/26")
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "player_minutes.sql"

MINUTES_TARGET = "target_minutes"
STARTER_TARGET = "target_started"
SUB_TARGET = "target_sub_appearance"
BASELINE_MINUTES_COLUMN = "baseline_expected_minutes"
BASELINE_START_COLUMN = "baseline_starting_probability"
BASELINE_SUB_COLUMN = "baseline_sub_probability"

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
    "player_id",
    "sofascore_player_id",
    "player_name",
    "player_position",
]

FEATURE_COLUMNS = [
    "is_home",
    "player_age_years",
    "position_goalkeeper",
    "position_defender",
    "position_midfielder",
    "position_forward",
    "prior_player_match_count",
    "prior_team_match_count",
    "rolling_minutes_3",
    "rolling_minutes_5",
    "rolling_minutes_10",
    "rolling_start_rate_3",
    "rolling_start_rate_5",
    "rolling_start_rate_10",
    "rolling_sub_appearance_rate_5",
    "rolling_bench_rate_5",
    "days_since_last_appearance",
    "days_since_last_start",
    "season_minutes_before_match",
    "season_starts_before_match",
    "season_sub_appearances_before_match",
    "matches_last_7_days",
    "matches_last_14_days",
    "feature_coverage_score",
]

PREDICTION_COLUMNS = [
    "expected_minutes",
    "starting_probability",
    "sub_probability",
    "availability_status",
]

MINUTES_MODEL_PARAMS = {
    "n_estimators": 400,
    "learning_rate": 0.04,
    "max_depth": 3,
    "subsample": 0.85,
    "colsample_bytree": 0.85,
    "reg_lambda": 2.0,
    "objective": "reg:squarederror",
    "random_state": 42,
}

CLASSIFIER_MODEL_PARAMS = {
    "n_estimators": 350,
    "learning_rate": 0.04,
    "max_depth": 3,
    "subsample": 0.85,
    "colsample_bytree": 0.85,
    "reg_lambda": 2.0,
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "random_state": 42,
}


@dataclass(frozen=True)
class PlayerMinutesModels:
    minutes_model: Any
    starter_model: Any
    sub_model: Any
    feature_columns: list[str]
    metadata: dict[str, Any]


PLAYER_MINUTES_DATASET_SQL = """
WITH match_team_rows AS (
    SELECT
        m.id AS match_id,
        m.sofascore_event_id,
        m.season_id,
        m.season_year,
        m.start_timestamp,
        m.start_datetime,
        m.start_datetime::date AS match_date,
        m.home_team_id AS team_id,
        m.away_team_id AS opponent_id,
        home.name AS team_name,
        away.name AS opponent_name,
        'home'::text AS side,
        1 AS is_home,
        CASE WHEN m.home_score IS NOT NULL AND m.away_score IS NOT NULL THEN true ELSE false END AS match_finished
    FROM raw.sofascore_matches m
    JOIN raw.sofascore_teams home ON home.id = m.home_team_id
    JOIN raw.sofascore_teams away ON away.id = m.away_team_id

    UNION ALL

    SELECT
        m.id AS match_id,
        m.sofascore_event_id,
        m.season_id,
        m.season_year,
        m.start_timestamp,
        m.start_datetime,
        m.start_datetime::date AS match_date,
        m.away_team_id AS team_id,
        m.home_team_id AS opponent_id,
        away.name AS team_name,
        home.name AS opponent_name,
        'away'::text AS side,
        0 AS is_home,
        CASE WHEN m.home_score IS NOT NULL AND m.away_score IS NOT NULL THEN true ELSE false END AS match_finished
    FROM raw.sofascore_matches m
    JOIN raw.sofascore_teams home ON home.id = m.home_team_id
    JOIN raw.sofascore_teams away ON away.id = m.away_team_id
),
appearance_base AS (
    SELECT
        mt.*,
        a.player_id,
        p.sofascore_player_id,
        p.name AS player_name,
        COALESCE(NULLIF(a.position, ''), NULLIF(p.position, ''), 'unknown') AS player_position,
        a.shirt_number,
        a.jersey_number,
        COALESCE(a.substitute, false) AS listed_as_substitute,
        LEAST(GREATEST(COALESCE(minutes.value_numeric, 0), 0), 120) AS target_minutes,
        CASE WHEN COALESCE(a.substitute, false) THEN 0 ELSE 1 END AS target_started,
        CASE
            WHEN COALESCE(a.substitute, false) AND COALESCE(minutes.value_numeric, 0) > 0
            THEN 1
            ELSE 0
        END AS target_sub_appearance,
        CASE
            WHEN p.date_of_birth IS NOT NULL
            THEN EXTRACT(YEAR FROM AGE(mt.match_date, p.date_of_birth))
        END AS player_age_years
    FROM match_team_rows mt
    JOIN raw.sofascore_player_match_appearances a
      ON a.match_id = mt.match_id
     AND a.team_id = mt.team_id
    JOIN raw.sofascore_players p ON p.id = a.player_id
    LEFT JOIN raw.sofascore_player_match_stats minutes
      ON minutes.match_id = a.match_id
     AND minutes.team_id = a.team_id
     AND minutes.player_id = a.player_id
     AND minutes.stat_key = 'minutesPlayed'
),
player_windows AS (
    SELECT
        b.*,
        COUNT(*) OVER player_prior AS prior_player_match_count,
        AVG(b.target_minutes) OVER player_w3 AS rolling_minutes_3_raw,
        AVG(b.target_minutes) OVER player_w5 AS rolling_minutes_5_raw,
        AVG(b.target_minutes) OVER player_w10 AS rolling_minutes_10_raw,
        AVG(b.target_started) OVER player_w3 AS rolling_start_rate_3_raw,
        AVG(b.target_started) OVER player_w5 AS rolling_start_rate_5_raw,
        AVG(b.target_started) OVER player_w10 AS rolling_start_rate_10_raw,
        AVG(b.target_sub_appearance) OVER player_w5 AS rolling_sub_appearance_rate_5_raw,
        AVG(CASE WHEN b.listed_as_substitute THEN 1 ELSE 0 END) OVER player_w5 AS rolling_bench_rate_5_raw,
        LAG(b.start_datetime) OVER player_prior_order AS last_listed_datetime,
        MAX(CASE WHEN b.target_started = 1 THEN b.start_datetime END) OVER player_prior AS last_start_datetime,
        SUM(b.target_minutes) OVER season_prior AS season_minutes_before_match_raw,
        SUM(b.target_started) OVER season_prior AS season_starts_before_match_raw,
        SUM(b.target_sub_appearance) OVER season_prior AS season_sub_appearances_before_match_raw
    FROM appearance_base b
    WINDOW
        player_prior AS (
            PARTITION BY b.player_id, b.team_id
            ORDER BY b.start_datetime, b.match_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ),
        player_w3 AS (
            PARTITION BY b.player_id, b.team_id
            ORDER BY b.start_datetime, b.match_id
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
        ),
        player_w5 AS (
            PARTITION BY b.player_id, b.team_id
            ORDER BY b.start_datetime, b.match_id
            ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
        ),
        player_w10 AS (
            PARTITION BY b.player_id, b.team_id
            ORDER BY b.start_datetime, b.match_id
            ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
        ),
        season_prior AS (
            PARTITION BY b.player_id, b.team_id, b.season_year
            ORDER BY b.start_datetime, b.match_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ),
        player_prior_order AS (
            PARTITION BY b.player_id, b.team_id
            ORDER BY b.start_datetime, b.match_id
        )
),
team_context AS (
    SELECT
        mt.match_id,
        mt.team_id,
        COUNT(*) OVER team_prior AS prior_team_match_count,
        (
            SELECT COUNT(*)
            FROM match_team_rows prior
            WHERE prior.team_id = mt.team_id
              AND prior.start_datetime < mt.start_datetime
              AND prior.start_datetime >= mt.start_datetime - INTERVAL '7 days'
        )::integer AS matches_last_7_days,
        (
            SELECT COUNT(*)
            FROM match_team_rows prior
            WHERE prior.team_id = mt.team_id
              AND prior.start_datetime < mt.start_datetime
              AND prior.start_datetime >= mt.start_datetime - INTERVAL '14 days'
        )::integer AS matches_last_14_days
    FROM match_team_rows mt
    WINDOW team_prior AS (
        PARTITION BY mt.team_id
        ORDER BY mt.start_datetime, mt.match_id
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    )
),
features AS (
    SELECT
        pw.match_id,
        pw.sofascore_event_id,
        pw.season_id,
        pw.season_year,
        pw.start_timestamp,
        pw.start_datetime,
        pw.match_date,
        pw.team_id,
        pw.opponent_id,
        pw.team_name,
        pw.opponent_name,
        pw.side,
        pw.player_id,
        pw.sofascore_player_id,
        pw.player_name,
        pw.player_position,
        pw.shirt_number,
        pw.jersey_number,
        pw.match_finished,
        pw.target_minutes,
        pw.target_started,
        pw.target_sub_appearance,
        COALESCE(pw.rolling_minutes_5_raw, 0.0) AS baseline_expected_minutes,
        COALESCE(pw.rolling_start_rate_5_raw, 0.0) AS baseline_starting_probability,
        COALESCE(pw.rolling_sub_appearance_rate_5_raw, 0.0) AS baseline_sub_probability,
        pw.is_home,
        COALESCE(pw.player_age_years, 26.0) AS player_age_years,
        CASE WHEN lower(pw.player_position) IN ('g', 'goalkeeper') THEN 1 ELSE 0 END AS position_goalkeeper,
        CASE WHEN lower(pw.player_position) IN ('d', 'defender') THEN 1 ELSE 0 END AS position_defender,
        CASE WHEN lower(pw.player_position) IN ('m', 'midfielder') THEN 1 ELSE 0 END AS position_midfielder,
        CASE WHEN lower(pw.player_position) IN ('f', 'forward') THEN 1 ELSE 0 END AS position_forward,
        pw.prior_player_match_count,
        COALESCE(tc.prior_team_match_count, 0) AS prior_team_match_count,
        COALESCE(pw.rolling_minutes_3_raw, 0.0) AS rolling_minutes_3,
        COALESCE(pw.rolling_minutes_5_raw, 0.0) AS rolling_minutes_5,
        COALESCE(pw.rolling_minutes_10_raw, 0.0) AS rolling_minutes_10,
        COALESCE(pw.rolling_start_rate_3_raw, 0.0) AS rolling_start_rate_3,
        COALESCE(pw.rolling_start_rate_5_raw, 0.0) AS rolling_start_rate_5,
        COALESCE(pw.rolling_start_rate_10_raw, 0.0) AS rolling_start_rate_10,
        COALESCE(pw.rolling_sub_appearance_rate_5_raw, 0.0) AS rolling_sub_appearance_rate_5,
        COALESCE(pw.rolling_bench_rate_5_raw, 0.0) AS rolling_bench_rate_5,
        COALESCE(EXTRACT(EPOCH FROM (pw.start_datetime - pw.last_listed_datetime)) / 86400.0, 999.0) AS days_since_last_appearance,
        COALESCE(EXTRACT(EPOCH FROM (pw.start_datetime - pw.last_start_datetime)) / 86400.0, 999.0) AS days_since_last_start,
        COALESCE(pw.season_minutes_before_match_raw, 0.0) AS season_minutes_before_match,
        COALESCE(pw.season_starts_before_match_raw, 0)::integer AS season_starts_before_match,
        COALESCE(pw.season_sub_appearances_before_match_raw, 0)::integer AS season_sub_appearances_before_match,
        COALESCE(tc.matches_last_7_days, 0) AS matches_last_7_days,
        COALESCE(tc.matches_last_14_days, 0) AS matches_last_14_days,
        (
            (
                CASE WHEN pw.prior_player_match_count > 0 THEN 1 ELSE 0 END
                + CASE WHEN pw.rolling_minutes_5_raw IS NOT NULL THEN 1 ELSE 0 END
                + CASE WHEN pw.rolling_start_rate_5_raw IS NOT NULL THEN 1 ELSE 0 END
                + CASE WHEN pw.last_listed_datetime IS NOT NULL THEN 1 ELSE 0 END
                + CASE WHEN COALESCE(tc.prior_team_match_count, 0) > 0 THEN 1 ELSE 0 END
            ) / 5.0
        ) AS feature_coverage_score
    FROM player_windows pw
    LEFT JOIN team_context tc
      ON tc.match_id = pw.match_id
     AND tc.team_id = pw.team_id
)
SELECT *
FROM features f
{where_clause}
ORDER BY f.start_datetime, f.match_id, f.team_id, f.player_id
"""


def parse_seasons(value: str | None, default: tuple[str, ...] = DEFAULT_TRAIN_SEASONS) -> tuple[str, ...]:
    if not value:
        return default
    seasons = tuple(item.strip() for item in value.split(",") if item.strip())
    if not seasons:
        raise ValueError("at least one season is required")
    return seasons


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


def artifact_paths(model_dir: Path) -> dict[str, Path]:
    return {
        "minutes_model": model_dir / "minutes_model.json",
        "starter_model": model_dir / "starter_model.json",
        "sub_model": model_dir / "sub_model.json",
        "metadata": model_dir / "metadata.json",
        "feature_columns": model_dir / "feature_columns.json",
        "validation_predictions": model_dir / "validation_predictions.csv",
        "feature_importance": model_dir / "feature_importance.csv",
        "cross_validation_results": model_dir / "cross_validation_results.csv",
    }


def default_model_dir_for_command(command: str) -> Path:
    if command in {"train-final", "predict-history", "predict-match"}:
        return DEFAULT_FINAL_MODEL_DIR
    return DEFAULT_MODEL_DIR


def build_where_clause(
    labelled_only: bool = False,
    match_id: int | None = None,
    sofascore_event_id: int | None = None,
) -> str:
    filters = []
    if labelled_only:
        filters.append("f.match_finished = true")
    if match_id is not None:
        filters.append(f"f.match_id = {int(match_id)}")
    if sofascore_event_id is not None:
        filters.append(f"f.sofascore_event_id = {int(sofascore_event_id)}")
    return "WHERE " + " AND ".join(filters) if filters else ""


def build_player_minutes_dataset_sql(
    labelled_only: bool = False,
    match_id: int | None = None,
    sofascore_event_id: int | None = None,
) -> str:
    return PLAYER_MINUTES_DATASET_SQL.replace(
        "{where_clause}",
        build_where_clause(
            labelled_only=labelled_only,
            match_id=match_id,
            sofascore_event_id=sofascore_event_id,
        ),
    )


def build_refresh_features_sql() -> str:
    columns = META_COLUMNS + [
        "season_id",
        "start_timestamp",
        "start_datetime",
        "shirt_number",
        "jersey_number",
        "match_finished",
        MINUTES_TARGET,
        STARTER_TARGET,
        SUB_TARGET,
        BASELINE_MINUTES_COLUMN,
        BASELINE_START_COLUMN,
        BASELINE_SUB_COLUMN,
    ] + FEATURE_COLUMNS
    ordered_columns = [
        "match_id",
        "sofascore_event_id",
        "season_id",
        "season_year",
        "start_timestamp",
        "start_datetime",
        "match_date",
        "team_id",
        "opponent_id",
        "team_name",
        "opponent_name",
        "side",
        "player_id",
        "sofascore_player_id",
        "player_name",
        "player_position",
        "shirt_number",
        "jersey_number",
        "match_finished",
        MINUTES_TARGET,
        STARTER_TARGET,
        SUB_TARGET,
        BASELINE_MINUTES_COLUMN,
        BASELINE_START_COLUMN,
        BASELINE_SUB_COLUMN,
    ] + FEATURE_COLUMNS
    select_columns = ", ".join(f"dataset.{column}" for column in ordered_columns)
    insert_columns = ", ".join(ordered_columns)
    sql = build_player_minutes_dataset_sql(labelled_only=False)
    return f"""
TRUNCATE features.player_minutes_features;

INSERT INTO features.player_minutes_features ({insert_columns})
SELECT {select_columns}
FROM (
{sql}
) dataset;
"""


def require_runtime_dependencies() -> tuple[Any, Any, Any, Any]:
    try:
        import numpy as np
        import pandas as pd
        from xgboost import XGBClassifier, XGBRegressor
    except ImportError as exc:
        raise SystemExit(
            "Missing ML runtime dependency. Install requirements first: "
            "python3 -m pip install -r requirements.txt"
        ) from exc
    return np, pd, XGBRegressor, XGBClassifier


def require_database_dependency():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise SystemExit(
            "Missing database dependency. Install requirements first: "
            "python3 -m pip install -r requirements.txt"
        ) from exc
    return psycopg, dict_row


def execute_sql_file(db_url: str, path: Path) -> None:
    psycopg, _ = require_database_dependency()
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(path.read_text(encoding="utf-8"))


def refresh_features(db_url: str) -> int:
    psycopg, _ = require_database_dependency()
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(build_refresh_features_sql())
            cur.execute("SELECT COUNT(*) FROM features.player_minutes_features")
            return int(cur.fetchone()[0])


def load_dataset(
    db_url: str,
    labelled_only: bool = False,
    match_id: int | None = None,
    sofascore_event_id: int | None = None,
):
    _, pd, _, _ = require_runtime_dependencies()
    psycopg, dict_row = require_database_dependency()
    sql = build_player_minutes_dataset_sql(
        labelled_only=labelled_only,
        match_id=match_id,
        sofascore_event_id=sofascore_event_id,
    )
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    return pd.DataFrame(rows)


def prepare_model_dataframe(df, pd):
    df = df.copy()
    df[FEATURE_COLUMNS] = df[FEATURE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    for column in (
        MINUTES_TARGET,
        STARTER_TARGET,
        SUB_TARGET,
        BASELINE_MINUTES_COLUMN,
        BASELINE_START_COLUMN,
        BASELINE_SUB_COLUMN,
    ):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


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


def clip_probability(values, np):
    return np.clip(values, 0.0, 1.0)


def clip_minutes(values, np):
    return np.clip(values, 0.0, 120.0)


def probability_predictions(model, features, np):
    raw = model.predict_proba(features)
    return clip_probability(raw[:, 1], np)


def safe_log_loss(actual, predicted, np) -> float | None:
    actual_values = np.asarray(actual, dtype=int)
    if len(set(actual_values.tolist())) < 2:
        return None
    probabilities = np.clip(np.asarray(predicted, dtype=float), 1e-6, 1.0 - 1e-6)
    return float(
        -np.mean(
            actual_values * np.log(probabilities)
            + (1 - actual_values) * np.log(1 - probabilities)
        )
    )


def binary_metrics(actual, predicted, baseline, np, prefix: str) -> dict[str, float | int | None]:
    actual_values = np.asarray(actual, dtype=float)
    predicted_values = np.asarray(predicted, dtype=float)
    baseline_values = np.asarray(baseline, dtype=float)
    baseline_mask = ~np.isnan(baseline_values)
    metrics: dict[str, float | int | None] = {
        f"{prefix}_brier": float(np.mean((predicted_values - actual_values) ** 2)),
        f"{prefix}_log_loss": safe_log_loss(actual_values, predicted_values, np),
        f"{prefix}_accuracy": float(np.mean((predicted_values >= 0.5) == actual_values)),
    }
    if baseline_mask.any():
        metrics[f"{prefix}_baseline_brier"] = float(
            np.mean((baseline_values[baseline_mask] - actual_values[baseline_mask]) ** 2)
        )
        metrics[f"{prefix}_baseline_log_loss"] = safe_log_loss(
            actual_values[baseline_mask],
            baseline_values[baseline_mask],
            np,
        )
        metrics[f"{prefix}_baseline_rows"] = int(baseline_mask.sum())
    else:
        metrics[f"{prefix}_baseline_brier"] = None
        metrics[f"{prefix}_baseline_log_loss"] = None
        metrics[f"{prefix}_baseline_rows"] = 0
    return metrics


def minutes_metrics(actual, predicted, baseline, np) -> dict[str, float | int | None]:
    actual_values = np.asarray(actual, dtype=float)
    predicted_values = np.asarray(predicted, dtype=float)
    errors = predicted_values - actual_values
    metrics: dict[str, float | int | None] = {
        "minutes_rmse": float(np.sqrt(np.mean(errors**2))),
        "minutes_mae": float(np.mean(np.abs(errors))),
    }
    baseline_values = np.asarray(baseline, dtype=float)
    baseline_mask = ~np.isnan(baseline_values)
    if baseline_mask.any():
        baseline_errors = baseline_values[baseline_mask] - actual_values[baseline_mask]
        metrics["minutes_baseline_rmse"] = float(np.sqrt(np.mean(baseline_errors**2)))
        metrics["minutes_baseline_mae"] = float(np.mean(np.abs(baseline_errors)))
        metrics["minutes_baseline_rows"] = int(baseline_mask.sum())
    else:
        metrics["minutes_baseline_rmse"] = None
        metrics["minutes_baseline_mae"] = None
        metrics["minutes_baseline_rows"] = 0
    return metrics


def top_11_accuracy(df, probability_column: str = "starting_probability") -> float | None:
    if df.empty:
        return None
    scores = []
    for _, group in df.groupby(["match_id", "team_id"]):
        if len(group) < 11:
            continue
        predicted_starters = set(
            group.sort_values(probability_column, ascending=False).head(11)["player_id"]
        )
        actual_starters = set(group[group[STARTER_TARGET] == 1]["player_id"])
        if not actual_starters:
            continue
        scores.append(len(predicted_starters & actual_starters) / len(actual_starters))
    return float(sum(scores) / len(scores)) if scores else None


def metric_summary(validation, predictions, np) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    metrics.update(
        minutes_metrics(
            validation[MINUTES_TARGET],
            predictions["expected_minutes"],
            validation[BASELINE_MINUTES_COLUMN],
            np,
        )
    )
    metrics.update(
        binary_metrics(
            validation[STARTER_TARGET],
            predictions["starting_probability"],
            validation[BASELINE_START_COLUMN],
            np,
            prefix="starter",
        )
    )
    metrics.update(
        binary_metrics(
            validation[SUB_TARGET],
            predictions["sub_probability"],
            validation[BASELINE_SUB_COLUMN],
            np,
            prefix="sub",
        )
    )
    combined = validation.copy()
    combined["starting_probability"] = predictions["starting_probability"]
    metrics["top_11_accuracy"] = top_11_accuracy(combined)
    return metrics


def save_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")


def save_feature_importance(
    path: Path,
    minutes_model,
    starter_model,
    sub_model,
    feature_columns: list[str],
) -> None:
    model_map = {
        "minutes": minutes_model,
        "starter": starter_model,
        "sub": sub_model,
    }
    with path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = ["feature", "minutes_gain", "starter_gain", "sub_gain"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        scores = {
            name: model.get_booster().get_score(importance_type="gain")
            for name, model in model_map.items()
        }
        for feature in feature_columns:
            writer.writerow(
                {
                    "feature": feature,
                    "minutes_gain": scores["minutes"].get(feature, 0.0),
                    "starter_gain": scores["starter"].get(feature, 0.0),
                    "sub_gain": scores["sub"].get(feature, 0.0),
                }
            )


def best_iteration_count(model, fallback_params: dict[str, Any]) -> int:
    best_iteration = getattr(model, "best_iteration", None)
    if best_iteration is None:
        return int(model.get_params().get("n_estimators", fallback_params["n_estimators"]))
    return int(best_iteration) + 1


def fit_models(
    XGBRegressor,
    XGBClassifier,
    train,
    validation,
    early_stopping_rounds: int,
):
    minutes_params = dict(MINUTES_MODEL_PARAMS)
    starter_params = dict(CLASSIFIER_MODEL_PARAMS)
    sub_params = dict(CLASSIFIER_MODEL_PARAMS)
    minutes_params["early_stopping_rounds"] = early_stopping_rounds
    starter_params["early_stopping_rounds"] = early_stopping_rounds
    sub_params["early_stopping_rounds"] = early_stopping_rounds

    minutes_model = XGBRegressor(**minutes_params)
    starter_model = XGBClassifier(**starter_params)
    sub_model = XGBClassifier(**sub_params)

    minutes_model.fit(
        train[FEATURE_COLUMNS],
        train[MINUTES_TARGET].astype(float),
        eval_set=[(validation[FEATURE_COLUMNS], validation[MINUTES_TARGET].astype(float))],
        verbose=False,
    )
    starter_model.fit(
        train[FEATURE_COLUMNS],
        train[STARTER_TARGET].astype(int),
        eval_set=[(validation[FEATURE_COLUMNS], validation[STARTER_TARGET].astype(int))],
        verbose=False,
    )
    sub_model.fit(
        train[FEATURE_COLUMNS],
        train[SUB_TARGET].astype(int),
        eval_set=[(validation[FEATURE_COLUMNS], validation[SUB_TARGET].astype(int))],
        verbose=False,
    )
    return minutes_model, starter_model, sub_model, minutes_params, starter_params, sub_params


def fit_final_models(
    XGBRegressor,
    XGBClassifier,
    df,
    minutes_rounds: int,
    starter_rounds: int,
    sub_rounds: int,
):
    minutes_params = dict(MINUTES_MODEL_PARAMS)
    starter_params = dict(CLASSIFIER_MODEL_PARAMS)
    sub_params = dict(CLASSIFIER_MODEL_PARAMS)
    minutes_params["n_estimators"] = int(minutes_rounds)
    starter_params["n_estimators"] = int(starter_rounds)
    sub_params["n_estimators"] = int(sub_rounds)

    minutes_model = XGBRegressor(**minutes_params)
    starter_model = XGBClassifier(**starter_params)
    sub_model = XGBClassifier(**sub_params)
    minutes_model.fit(df[FEATURE_COLUMNS], df[MINUTES_TARGET].astype(float), verbose=False)
    starter_model.fit(df[FEATURE_COLUMNS], df[STARTER_TARGET].astype(int), verbose=False)
    sub_model.fit(df[FEATURE_COLUMNS], df[SUB_TARGET].astype(int), verbose=False)
    return minutes_model, starter_model, sub_model, minutes_params, starter_params, sub_params


def predict_with_models(df, minutes_model, starter_model, sub_model, np, pd):
    features = df[FEATURE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    return {
        "expected_minutes": clip_minutes(minutes_model.predict(features), np),
        "starting_probability": probability_predictions(starter_model, features, np),
        "sub_probability": probability_predictions(sub_model, features, np),
    }


def write_prediction_csv(df, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = (
        META_COLUMNS
        + [MINUTES_TARGET, STARTER_TARGET, SUB_TARGET]
        + [BASELINE_MINUTES_COLUMN, BASELINE_START_COLUMN, BASELINE_SUB_COLUMN]
        + PREDICTION_COLUMNS
    )
    existing = [column for column in columns if column in df.columns]
    df[existing].to_csv(output_path, index=False)


def train_model(
    db_url: str,
    model_dir: Path,
    train_seasons: tuple[str, ...],
    validation_season: str,
    early_stopping_rounds: int,
) -> dict[str, Any]:
    np, pd, XGBRegressor, XGBClassifier = require_runtime_dependencies()
    df = prepare_model_dataframe(load_dataset(db_url, labelled_only=True), pd)
    train, validation = train_validation_split(df, train_seasons, validation_season)
    (
        minutes_model,
        starter_model,
        sub_model,
        minutes_params,
        starter_params,
        sub_params,
    ) = fit_models(
        XGBRegressor,
        XGBClassifier,
        train=train,
        validation=validation,
        early_stopping_rounds=early_stopping_rounds,
    )
    predictions = predict_with_models(
        validation,
        minutes_model,
        starter_model,
        sub_model,
        np,
        pd,
    )
    metrics = metric_summary(validation, predictions, np)

    model_dir.mkdir(parents=True, exist_ok=True)
    paths = artifact_paths(model_dir)
    minutes_model.save_model(paths["minutes_model"])
    starter_model.save_model(paths["starter_model"])
    sub_model.save_model(paths["sub_model"])
    save_json(paths["feature_columns"], FEATURE_COLUMNS)
    save_feature_importance(
        paths["feature_importance"],
        minutes_model,
        starter_model,
        sub_model,
        FEATURE_COLUMNS,
    )

    output = validation[
        META_COLUMNS
        + [MINUTES_TARGET, STARTER_TARGET, SUB_TARGET]
        + [BASELINE_MINUTES_COLUMN, BASELINE_START_COLUMN, BASELINE_SUB_COLUMN]
    ].copy()
    for column, values in predictions.items():
        output[column] = values
    output["availability_status"] = "listed"
    write_prediction_csv(output, paths["validation_predictions"])

    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "validation",
        "model_name": "player_minutes",
        "train_seasons": list(train_seasons),
        "validation_season": validation_season,
        "train_rows": int(len(train)),
        "validation_rows": int(len(validation)),
        "all_labelled_rows": int(len(df)),
        "feature_count": len(FEATURE_COLUMNS),
        "feature_columns": FEATURE_COLUMNS,
        "targets": [MINUTES_TARGET, STARTER_TARGET, SUB_TARGET],
        "model_params": {
            "minutes": minutes_params,
            "starter": starter_params,
            "sub": sub_params,
        },
        "best_iteration_count": {
            "minutes": best_iteration_count(minutes_model, MINUTES_MODEL_PARAMS),
            "starter": best_iteration_count(starter_model, CLASSIFIER_MODEL_PARAMS),
            "sub": best_iteration_count(sub_model, CLASSIFIER_MODEL_PARAMS),
        },
        "metrics": metrics,
    }
    save_json(paths["metadata"], metadata)
    return metadata


def train_final_model(
    db_url: str,
    model_dir: Path,
    source_model_dir: Path,
    early_stopping_rounds: int,
    refresh_source_train: bool,
) -> dict[str, Any]:
    _, pd, XGBRegressor, XGBClassifier = require_runtime_dependencies()
    source_paths = artifact_paths(source_model_dir)
    if refresh_source_train or not source_paths["metadata"].exists():
        source_metadata = train_model(
            db_url=db_url,
            model_dir=source_model_dir,
            train_seasons=DEFAULT_TRAIN_SEASONS,
            validation_season=DEFAULT_VALIDATION_SEASON,
            early_stopping_rounds=early_stopping_rounds,
        )
    else:
        source_metadata = json.loads(source_paths["metadata"].read_text(encoding="utf-8"))

    best_rounds = source_metadata.get("best_iteration_count", {})
    df = prepare_model_dataframe(load_dataset(db_url, labelled_only=True), pd)
    (
        minutes_model,
        starter_model,
        sub_model,
        minutes_params,
        starter_params,
        sub_params,
    ) = fit_final_models(
        XGBRegressor,
        XGBClassifier,
        df,
        minutes_rounds=int(best_rounds.get("minutes", MINUTES_MODEL_PARAMS["n_estimators"])),
        starter_rounds=int(best_rounds.get("starter", CLASSIFIER_MODEL_PARAMS["n_estimators"])),
        sub_rounds=int(best_rounds.get("sub", CLASSIFIER_MODEL_PARAMS["n_estimators"])),
    )

    model_dir.mkdir(parents=True, exist_ok=True)
    paths = artifact_paths(model_dir)
    minutes_model.save_model(paths["minutes_model"])
    starter_model.save_model(paths["starter_model"])
    sub_model.save_model(paths["sub_model"])
    save_json(paths["feature_columns"], FEATURE_COLUMNS)
    save_feature_importance(
        paths["feature_importance"],
        minutes_model,
        starter_model,
        sub_model,
        FEATURE_COLUMNS,
    )
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "final",
        "model_name": "player_minutes",
        "train_seasons": list(ordered_seasons(df["season_year"].unique())),
        "train_rows": int(len(df)),
        "feature_count": len(FEATURE_COLUMNS),
        "feature_columns": FEATURE_COLUMNS,
        "targets": [MINUTES_TARGET, STARTER_TARGET, SUB_TARGET],
        "model_params": {
            "minutes": minutes_params,
            "starter": starter_params,
            "sub": sub_params,
        },
        "source_model_dir": str(source_model_dir),
        "source_validation_season": source_metadata.get("validation_season"),
        "source_metrics": source_metadata.get("metrics"),
        "source_best_iteration_count": best_rounds,
    }
    save_json(paths["metadata"], metadata)
    return metadata


def aggregate_fold_metrics(folds: list[dict[str, Any]]) -> dict[str, float | int | None]:
    total_rows = sum(fold["validation_rows"] for fold in folds)
    weighted: dict[str, float | int | None] = {"validation_rows": total_rows}
    metric_names = [
        "minutes_mae",
        "minutes_rmse",
        "starter_brier",
        "starter_accuracy",
        "sub_brier",
        "sub_accuracy",
    ]
    for metric in metric_names:
        weighted[metric] = (
            sum(fold[metric] * fold["validation_rows"] for fold in folds) / total_rows
            if total_rows
            else None
        )
    return weighted


def cross_validate_model(
    db_url: str,
    output_path: Path,
    validation_seasons: tuple[str, ...],
    early_stopping_rounds: int,
    min_train_seasons: int,
) -> dict[str, Any]:
    np, pd, XGBRegressor, XGBClassifier = require_runtime_dependencies()
    df = prepare_model_dataframe(load_dataset(db_url, labelled_only=True), pd)
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
        minutes_model, starter_model, sub_model, *_ = fit_models(
            XGBRegressor,
            XGBClassifier,
            train=train,
            validation=validation,
            early_stopping_rounds=early_stopping_rounds,
        )
        predictions = predict_with_models(
            validation,
            minutes_model,
            starter_model,
            sub_model,
            np,
            pd,
        )
        metrics = metric_summary(validation, predictions, np)
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
            "minutes_rmse",
            "minutes_mae",
            "minutes_baseline_rmse",
            "minutes_baseline_mae",
            "starter_brier",
            "starter_log_loss",
            "starter_accuracy",
            "starter_baseline_brier",
            "sub_brier",
            "sub_log_loss",
            "sub_accuracy",
            "sub_baseline_brier",
            "top_11_accuracy",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_name": "player_minutes",
        "folds": rows,
        "weighted_average": aggregate_fold_metrics(rows),
        "output_path": str(output_path),
    }


def load_models_and_features(model_dir: Path) -> PlayerMinutesModels:
    _, _, XGBRegressor, XGBClassifier = require_runtime_dependencies()
    paths = artifact_paths(model_dir)
    required = [
        paths["minutes_model"],
        paths["starter_model"],
        paths["sub_model"],
        paths["feature_columns"],
    ]
    if any(not path.exists() for path in required):
        raise SystemExit(f"Model artifacts not found in {model_dir}. Run train first.")
    minutes_model = XGBRegressor()
    starter_model = XGBClassifier()
    sub_model = XGBClassifier()
    minutes_model.load_model(paths["minutes_model"])
    starter_model.load_model(paths["starter_model"])
    sub_model.load_model(paths["sub_model"])
    feature_columns = json.loads(paths["feature_columns"].read_text(encoding="utf-8"))
    metadata = {}
    if paths["metadata"].exists():
        metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    return PlayerMinutesModels(
        minutes_model=minutes_model,
        starter_model=starter_model,
        sub_model=sub_model,
        feature_columns=feature_columns,
        metadata=metadata,
    )


def predict_dataframe(df, models: PlayerMinutesModels):
    np, pd, _, _ = require_runtime_dependencies()
    features = df[models.feature_columns].apply(pd.to_numeric, errors="coerce")
    output = df.copy()
    output["expected_minutes"] = clip_minutes(
        models.minutes_model.predict(features),
        np,
    )
    output["starting_probability"] = probability_predictions(
        models.starter_model,
        features,
        np,
    )
    output["sub_probability"] = probability_predictions(models.sub_model, features, np)
    output["availability_status"] = "listed"
    return output


def upsert_prediction_run(
    db_url: str,
    run_name: str,
    mode: str,
    model_dir: Path,
    metadata: dict[str, Any],
) -> int:
    psycopg, _ = require_database_dependency()
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_outputs.player_minutes_runs (
                    run_name, mode, train_seasons, validation_season,
                    source_model_dir, parameters, metrics, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                ON CONFLICT (run_name) DO UPDATE SET
                    mode = EXCLUDED.mode,
                    train_seasons = EXCLUDED.train_seasons,
                    validation_season = EXCLUDED.validation_season,
                    source_model_dir = EXCLUDED.source_model_dir,
                    parameters = EXCLUDED.parameters,
                    metrics = EXCLUDED.metrics,
                    metadata = EXCLUDED.metadata
                RETURNING id
                """,
                (
                    run_name,
                    mode,
                    metadata.get("train_seasons"),
                    metadata.get("validation_season"),
                    str(model_dir),
                    json.dumps(metadata.get("model_params", {}), default=str),
                    json.dumps(metadata.get("metrics", {}), default=str),
                    json.dumps(metadata, default=str),
                ),
            )
            return int(cur.fetchone()[0])


def persist_predictions(db_url: str, run_id: int, df) -> int:
    psycopg, _ = require_database_dependency()
    rows = [
        (
            run_id,
            row.match_id,
            row.sofascore_event_id,
            row.season_year,
            row.match_date,
            row.team_id,
            row.opponent_id,
            row.player_id,
            row.player_name,
            row.player_position,
            float(row.expected_minutes),
            float(row.starting_probability),
            float(row.sub_probability),
            row.availability_status,
            getattr(row, MINUTES_TARGET, None),
            getattr(row, STARTER_TARGET, None),
            getattr(row, SUB_TARGET, None),
        )
        for row in df.itertuples(index=False)
    ]
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM model_outputs.player_minutes_predictions WHERE run_id = %s",
                (run_id,),
            )
            cur.executemany(
                """
                INSERT INTO model_outputs.player_minutes_predictions (
                    run_id, match_id, sofascore_event_id, season_year, match_date,
                    team_id, opponent_id, player_id, player_name, player_position,
                    expected_minutes, starting_probability, sub_probability,
                    availability_status, target_minutes, target_started,
                    target_sub_appearance
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (run_id, match_id, team_id, player_id) DO UPDATE SET
                    expected_minutes = EXCLUDED.expected_minutes,
                    starting_probability = EXCLUDED.starting_probability,
                    sub_probability = EXCLUDED.sub_probability,
                    availability_status = EXCLUDED.availability_status,
                    target_minutes = EXCLUDED.target_minutes,
                    target_started = EXCLUDED.target_started,
                    target_sub_appearance = EXCLUDED.target_sub_appearance
                """,
                rows,
            )
    return len(rows)


def predict_history(
    db_url: str,
    model_dir: Path,
    output_path: Path,
    run_name: str | None,
    skip_db: bool,
) -> int:
    models = load_models_and_features(model_dir)
    df = load_dataset(db_url, labelled_only=True)
    if df.empty:
        raise SystemExit("No labelled player minutes rows found")
    output = predict_dataframe(df, models)
    write_prediction_csv(output, output_path)
    if not skip_db:
        run_name = run_name or f"player_minutes_history_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        run_id = upsert_prediction_run(
            db_url,
            run_name=run_name,
            mode="history",
            model_dir=model_dir,
            metadata=models.metadata,
        )
        persist_predictions(db_url, run_id, output)
    return len(output)


def predict_match(
    db_url: str,
    model_dir: Path,
    output_path: Path | None,
    match_id: int | None,
    sofascore_event_id: int | None,
    run_name: str | None,
    skip_db: bool,
) -> int:
    if match_id is None and sofascore_event_id is None:
        raise SystemExit("predict-match requires --match-id or --sofascore-event-id")
    models = load_models_and_features(model_dir)
    df = load_dataset(
        db_url,
        labelled_only=False,
        match_id=match_id,
        sofascore_event_id=sofascore_event_id,
    )
    if df.empty:
        raise SystemExit("No player rows found for requested match")
    output = predict_dataframe(df, models)
    if output_path is not None:
        write_prediction_csv(output, output_path)
    else:
        columns = META_COLUMNS + PREDICTION_COLUMNS
        print(output[columns].to_string(index=False))
    if not skip_db:
        match_key = match_id if match_id is not None else f"event_{sofascore_event_id}"
        run_name = run_name or f"player_minutes_match_{match_key}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        run_id = upsert_prediction_run(
            db_url,
            run_name=run_name,
            mode="match",
            model_dir=model_dir,
            metadata=models.metadata,
        )
        persist_predictions(db_url, run_id, output)
    return len(output)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train and run player minutes, starter, and substitute models."
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
        help="Directory for model artifacts. Defaults to models/player_minutes.",
    )
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="Create feature and model output tables before running the command.",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Do not write prediction runs or prediction rows to model_outputs.",
    )
    parser.add_argument(
        "--run-name",
        help="Run name for persisted predictions. Defaults to a timestamped name.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("refresh-features", help="Rebuild features.player_minutes_features.")

    train_parser = subparsers.add_parser("train", help="Train validation models.")
    train_parser.add_argument("--train-seasons", default=",".join(DEFAULT_TRAIN_SEASONS))
    train_parser.add_argument("--validation-season", default=DEFAULT_VALIDATION_SEASON)
    train_parser.add_argument("--early-stopping-rounds", type=int, default=40)

    final_parser = subparsers.add_parser("train-final", help="Train all-history final models.")
    final_parser.add_argument(
        "--source-model-dir",
        type=Path,
        default=DEFAULT_MODEL_DIR,
        help="Validation model directory used to choose final boosting rounds.",
    )
    final_parser.add_argument("--early-stopping-rounds", type=int, default=40)
    final_parser.add_argument(
        "--refresh-source-train",
        action="store_true",
        help="Retrain the validation source model before fitting final models.",
    )

    cv_parser = subparsers.add_parser("cross-validate", help="Run rolling-origin validation.")
    cv_parser.add_argument(
        "--validation-seasons",
        default=",".join(DEFAULT_CV_VALIDATION_SEASONS),
    )
    cv_parser.add_argument("--early-stopping-rounds", type=int, default=40)
    cv_parser.add_argument("--min-train-seasons", type=int, default=1)
    cv_parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_MODEL_DIR / "cross_validation_results.csv",
    )

    history_parser = subparsers.add_parser("predict-history", help="Score labelled history.")
    history_parser.add_argument(
        "--output",
        type=Path,
        default=Path("models/player_minutes_history_predictions.csv"),
    )

    match_parser = subparsers.add_parser("predict-match", help="Score listed players for one match.")
    match_parser.add_argument("--match-id", type=int)
    match_parser.add_argument("--sofascore-event-id", type=int)
    match_parser.add_argument("--output", type=Path)

    args = parser.parse_args()
    model_dir = args.model_dir or default_model_dir_for_command(args.command)
    if args.create_schema:
        execute_sql_file(args.db_url, SCHEMA_PATH)

    if args.command == "refresh-features":
        rows = refresh_features(args.db_url)
        print(f"Refreshed {rows} player minutes feature rows.")
        return

    if args.command == "train":
        metadata = train_model(
            db_url=args.db_url,
            model_dir=model_dir,
            train_seasons=parse_seasons(args.train_seasons),
            validation_season=args.validation_season,
            early_stopping_rounds=args.early_stopping_rounds,
        )
        print(json.dumps(metadata, indent=2, sort_keys=True, default=str))
        return

    if args.command == "train-final":
        metadata = train_final_model(
            db_url=args.db_url,
            model_dir=model_dir,
            source_model_dir=args.source_model_dir,
            early_stopping_rounds=args.early_stopping_rounds,
            refresh_source_train=args.refresh_source_train,
        )
        print(json.dumps(metadata, indent=2, sort_keys=True, default=str))
        return

    if args.command == "cross-validate":
        metadata = cross_validate_model(
            db_url=args.db_url,
            output_path=args.output,
            validation_seasons=parse_seasons(
                args.validation_seasons,
                default=DEFAULT_CV_VALIDATION_SEASONS,
            ),
            early_stopping_rounds=args.early_stopping_rounds,
            min_train_seasons=args.min_train_seasons,
        )
        print(json.dumps(metadata, indent=2, sort_keys=True, default=str))
        return

    if args.command == "predict-history":
        rows = predict_history(
            db_url=args.db_url,
            model_dir=model_dir,
            output_path=args.output,
            run_name=args.run_name,
            skip_db=args.skip_db,
        )
        print(f"Scored {rows} historical player rows.")
        return

    if args.command == "predict-match":
        rows = predict_match(
            db_url=args.db_url,
            model_dir=model_dir,
            output_path=args.output,
            match_id=args.match_id,
            sofascore_event_id=args.sofascore_event_id,
            run_name=args.run_name,
            skip_db=args.skip_db,
        )
        print(f"Scored {rows} player rows.")
        return


if __name__ == "__main__":
    main()
