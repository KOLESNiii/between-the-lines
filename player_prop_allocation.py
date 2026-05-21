import argparse
import csv
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import xgboost_xg_model as xgb_model


DEFAULT_DB_URL = "postgresql://user:pwd@localhost:5432/betting_historical_data"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "player_prop_allocation.sql"
DEFAULT_OUTPUT_DIR = Path("models/player_prop_allocation")
DEFAULT_SHOTS_MODEL_DIR = xgb_model.MODEL_SPECS["shots_for"].default_final_model_dir
DEFAULT_SOT_MODEL_DIR = xgb_model.MODEL_SPECS["shots_on_target"].default_final_model_dir
PROP_LINES = (0.5, 1.5, 2.5, 3.5)
MARKET_KEY_SHOTS = "player_shots"
MARKET_KEY_SOT = "player_shots_on_target"
TARGET_PLAYER_SHOTS = "target_player_shots"
TARGET_PLAYER_SOT = "target_player_sot"
TARGET_MINUTES = "target_minutes"

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
    "position_group",
]

FEATURE_COLUMNS = [
    "is_home",
    "prior_player_match_count",
    "prior_team_match_count",
    "rolling_player_shot_share_5",
    "rolling_player_sot_share_5",
    "rolling_player_shots_per90_5",
    "rolling_player_sot_per90_5",
    "rolling_team_shots_5",
    "rolling_team_sot_5",
    "rolling_position_shot_share",
    "rolling_position_sot_share",
]

DEFAULT_SHOT_SHARE_BY_POSITION = {
    "goalkeeper": 0.0,
    "defender": 0.03,
    "midfielder": 0.07,
    "forward": 0.14,
    "unknown": 0.06,
}

DEFAULT_SOT_SHARE_BY_POSITION = {
    "goalkeeper": 0.0,
    "defender": 0.02,
    "midfielder": 0.06,
    "forward": 0.16,
    "unknown": 0.05,
}

PLAYER_PROP_FEATURES_SQL = """
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
        1 AS is_home
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
        0 AS is_home
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
        CASE
            WHEN lower(COALESCE(NULLIF(a.position, ''), NULLIF(p.position, ''), '')) IN ('g', 'goalkeeper')
              OR lower(COALESCE(NULLIF(a.position, ''), NULLIF(p.position, ''), '')) LIKE '%keeper%'
            THEN 'goalkeeper'
            WHEN lower(COALESCE(NULLIF(a.position, ''), NULLIF(p.position, ''), '')) IN ('d', 'defender')
              OR lower(COALESCE(NULLIF(a.position, ''), NULLIF(p.position, ''), '')) LIKE '%defender%'
            THEN 'defender'
            WHEN lower(COALESCE(NULLIF(a.position, ''), NULLIF(p.position, ''), '')) IN ('m', 'midfielder')
              OR lower(COALESCE(NULLIF(a.position, ''), NULLIF(p.position, ''), '')) LIKE '%midfielder%'
            THEN 'midfielder'
            WHEN lower(COALESCE(NULLIF(a.position, ''), NULLIF(p.position, ''), '')) IN ('f', 'forward')
              OR lower(COALESCE(NULLIF(a.position, ''), NULLIF(p.position, ''), '')) LIKE '%forward%'
              OR lower(COALESCE(NULLIF(a.position, ''), NULLIF(p.position, ''), '')) LIKE '%striker%'
            THEN 'forward'
            ELSE 'unknown'
        END AS position_group,
        COALESCE(shots.value_numeric, 0) AS target_player_shots,
        COALESCE(sot.value_numeric, 0) AS target_player_sot,
        LEAST(GREATEST(COALESCE(minutes.value_numeric, 0), 0), 120) AS target_minutes
    FROM match_team_rows mt
    JOIN raw.sofascore_player_match_appearances a
      ON a.match_id = mt.match_id
     AND a.team_id = mt.team_id
    JOIN raw.sofascore_players p ON p.id = a.player_id
    LEFT JOIN raw.sofascore_player_match_stats shots
      ON shots.match_id = a.match_id
     AND shots.team_id = a.team_id
     AND shots.player_id = a.player_id
     AND shots.stat_key = 'totalShots'
    LEFT JOIN raw.sofascore_player_match_stats sot
      ON sot.match_id = a.match_id
     AND sot.team_id = a.team_id
     AND sot.player_id = a.player_id
     AND sot.stat_key = 'onTargetScoringAttempt'
    LEFT JOIN raw.sofascore_player_match_stats minutes
      ON minutes.match_id = a.match_id
     AND minutes.team_id = a.team_id
     AND minutes.player_id = a.player_id
     AND minutes.stat_key = 'minutesPlayed'
),
team_player_totals AS (
    SELECT
        match_id,
        team_id,
        SUM(target_player_shots) AS team_player_shots,
        SUM(target_player_sot) AS team_player_sot
    FROM appearance_base
    GROUP BY match_id, team_id
),
enriched AS (
    SELECT
        b.*,
        t.team_player_shots,
        t.team_player_sot,
        b.target_player_shots / NULLIF(t.team_player_shots, 0) AS player_shot_share,
        b.target_player_sot / NULLIF(t.team_player_sot, 0) AS player_sot_share
    FROM appearance_base b
    JOIN team_player_totals t
      ON t.match_id = b.match_id
     AND t.team_id = b.team_id
),
position_match_shares AS (
    SELECT
        match_id,
        team_id,
        start_datetime,
        position_group,
        AVG(player_shot_share) AS position_shot_share,
        AVG(player_sot_share) AS position_sot_share
    FROM enriched
    GROUP BY match_id, team_id, start_datetime, position_group
),
position_windows AS (
    SELECT
        p.*,
        AVG(p.position_shot_share) OVER position_prior AS rolling_position_shot_share,
        AVG(p.position_sot_share) OVER position_prior AS rolling_position_sot_share
    FROM position_match_shares p
    WINDOW position_prior AS (
        PARTITION BY p.team_id, p.position_group
        ORDER BY p.start_datetime, p.match_id
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    )
),
player_windows AS (
    SELECT
        e.*,
        COUNT(*) OVER player_prior AS prior_player_match_count,
        AVG(e.player_shot_share) OVER player_w5 AS rolling_player_shot_share_5,
        AVG(e.player_sot_share) OVER player_w5 AS rolling_player_sot_share_5,
        SUM(e.target_player_shots) OVER player_w5
            / NULLIF(SUM(e.target_minutes) OVER player_w5, 0) * 90
            AS rolling_player_shots_per90_5,
        SUM(e.target_player_sot) OVER player_w5
            / NULLIF(SUM(e.target_minutes) OVER player_w5, 0) * 90
            AS rolling_player_sot_per90_5
    FROM enriched e
    WINDOW
        player_prior AS (
            PARTITION BY e.player_id, e.team_id
            ORDER BY e.start_datetime, e.match_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ),
        player_w5 AS (
            PARTITION BY e.player_id, e.team_id
            ORDER BY e.start_datetime, e.match_id
            ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
        )
),
team_match_totals AS (
    SELECT
        mt.match_id,
        mt.team_id,
        mt.start_datetime,
        COALESCE(t.team_player_shots, 0) AS team_player_shots,
        COALESCE(t.team_player_sot, 0) AS team_player_sot
    FROM match_team_rows mt
    LEFT JOIN team_player_totals t
      ON t.match_id = mt.match_id
     AND t.team_id = mt.team_id
),
team_windows AS (
    SELECT
        t.*,
        COUNT(*) OVER team_prior AS prior_team_match_count,
        AVG(t.team_player_shots) OVER team_w5 AS rolling_team_shots_5,
        AVG(t.team_player_sot) OVER team_w5 AS rolling_team_sot_5
    FROM team_match_totals t
    WINDOW
        team_prior AS (
            PARTITION BY t.team_id
            ORDER BY t.start_datetime, t.match_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ),
        team_w5 AS (
            PARTITION BY t.team_id
            ORDER BY t.start_datetime, t.match_id
            ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
        )
)
SELECT
    p.match_id,
    p.sofascore_event_id,
    p.season_id,
    p.season_year,
    p.start_timestamp,
    p.start_datetime,
    p.match_date,
    p.team_id,
    p.opponent_id,
    p.team_name,
    p.opponent_name,
    p.side,
    p.player_id,
    p.sofascore_player_id,
    p.player_name,
    p.player_position,
    p.position_group,
    p.target_player_shots,
    p.target_player_sot,
    p.target_minutes,
    p.is_home,
    p.prior_player_match_count,
    tw.prior_team_match_count,
    p.rolling_player_shot_share_5,
    p.rolling_player_sot_share_5,
    p.rolling_player_shots_per90_5,
    p.rolling_player_sot_per90_5,
    tw.rolling_team_shots_5,
    tw.rolling_team_sot_5,
    posw.rolling_position_shot_share,
    posw.rolling_position_sot_share
FROM player_windows p
JOIN team_windows tw
  ON tw.match_id = p.match_id
 AND tw.team_id = p.team_id
LEFT JOIN position_windows posw
  ON posw.match_id = p.match_id
 AND posw.team_id = p.team_id
 AND posw.position_group = p.position_group
{where_clause}
ORDER BY p.start_datetime, p.match_id, p.side DESC, p.player_id
"""


def default_position_share(position_group: str | None, market_key: str) -> float:
    key = position_group if position_group in DEFAULT_SHOT_SHARE_BY_POSITION else "unknown"
    if market_key == MARKET_KEY_SOT:
        return DEFAULT_SOT_SHARE_BY_POSITION[key]
    return DEFAULT_SHOT_SHARE_BY_POSITION[key]


def build_where_clause(
    match_id: int | None = None,
    sofascore_event_id: int | None = None,
    table_alias: str = "p",
) -> str:
    filters = []
    if match_id is not None:
        filters.append(f"{table_alias}.match_id = {int(match_id)}")
    if sofascore_event_id is not None:
        filters.append(f"{table_alias}.sofascore_event_id = {int(sofascore_event_id)}")
    return "WHERE " + " AND ".join(filters) if filters else ""


def build_player_prop_features_sql(
    match_id: int | None = None,
    sofascore_event_id: int | None = None,
) -> str:
    return PLAYER_PROP_FEATURES_SQL.replace(
        "{where_clause}",
        build_where_clause(match_id=match_id, sofascore_event_id=sofascore_event_id),
    )


def build_refresh_features_sql() -> str:
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
        "position_group",
        TARGET_PLAYER_SHOTS,
        TARGET_PLAYER_SOT,
        TARGET_MINUTES,
    ] + FEATURE_COLUMNS
    insert_columns = ", ".join(ordered_columns)
    select_columns = ", ".join(f"dataset.{column}" for column in ordered_columns)
    sql = build_player_prop_features_sql()
    return f"""
TRUNCATE features.player_prop_allocation_features;

INSERT INTO features.player_prop_allocation_features ({insert_columns})
SELECT {select_columns}
FROM (
{sql}
) dataset;
"""


def require_runtime_dependencies():
    try:
        import numpy as np
        import pandas as pd
    except ImportError as exc:
        raise SystemExit(
            "Missing runtime dependency. Install requirements first: "
            "python3 -m pip install -r requirements.txt"
        ) from exc
    return np, pd


def require_database_dependency():
    try:
        import psycopg
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise SystemExit(
            "Missing database dependency. Install requirements first: "
            "python3 -m pip install -r requirements.txt"
        ) from exc
    return psycopg, dict_row, Jsonb


def execute_sql_file(db_url: str, path: Path) -> None:
    psycopg, _, _ = require_database_dependency()
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(path.read_text(encoding="utf-8"))


def refresh_features(db_url: str) -> int:
    psycopg, _, _ = require_database_dependency()
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(build_refresh_features_sql())
            cur.execute("SELECT COUNT(*) FROM features.player_prop_allocation_features")
            return int(cur.fetchone()[0])


def load_features(
    db_url: str,
    match_id: int | None = None,
    sofascore_event_id: int | None = None,
):
    _, pd = require_runtime_dependencies()
    psycopg, dict_row, _ = require_database_dependency()
    where = build_where_clause(
        match_id=match_id,
        sofascore_event_id=sofascore_event_id,
        table_alias="f",
    )
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT *
                FROM features.player_prop_allocation_features f
                {where}
                ORDER BY f.start_datetime, f.match_id, f.side DESC, f.player_id
                """
            )
            rows = cur.fetchall()
    return pd.DataFrame(rows)


def latest_player_minutes_run_id(db_url: str) -> int:
    psycopg, _, _ = require_database_dependency()
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.id
                FROM model_outputs.player_minutes_runs r
                WHERE EXISTS (
                    SELECT 1
                    FROM model_outputs.player_minutes_predictions p
                    WHERE p.run_id = r.id
                )
                ORDER BY r.created_at DESC, r.id DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
    if row is None:
        raise SystemExit(
            "No player minutes prediction run found. Run player_minutes_model.py predict-history first."
        )
    return int(row[0])


def load_player_minutes_predictions(
    db_url: str,
    player_minutes_run_id: int | None = None,
    match_id: int | None = None,
    sofascore_event_id: int | None = None,
):
    _, pd = require_runtime_dependencies()
    psycopg, dict_row, _ = require_database_dependency()
    run_id = player_minutes_run_id or latest_player_minutes_run_id(db_url)
    filters = ["p.run_id = %s"]
    params: list[Any] = [run_id]
    if match_id is not None:
        filters.append("p.match_id = %s")
        params.append(match_id)
    if sofascore_event_id is not None:
        filters.append("p.sofascore_event_id = %s")
        params.append(sofascore_event_id)
    where = " AND ".join(filters)
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    p.run_id AS player_minutes_run_id,
                    p.match_id,
                    p.sofascore_event_id,
                    p.team_id,
                    p.player_id,
                    p.expected_minutes,
                    p.starting_probability,
                    p.sub_probability,
                    p.availability_status
                FROM model_outputs.player_minutes_predictions p
                WHERE {where}
                """,
                params,
            )
            rows = cur.fetchall()
    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit(f"No player minutes predictions found for run_id={run_id}")
    return run_id, df


def score_team_rate_models(
    db_url: str,
    shots_model_dir: Path,
    sot_model_dir: Path,
    match_id: int | None = None,
    sofascore_event_id: int | None = None,
):
    _, pd = require_runtime_dependencies()
    base_spec = xgb_model.MODEL_SPECS["shots_for"]
    df = xgb_model.load_dataset(
        db_url,
        labelled_only=False,
        match_id=match_id,
        sofascore_event_id=sofascore_event_id,
        model_spec=base_spec,
    )
    if df.empty:
        raise SystemExit("No team feature rows found for requested scope")

    for model_name, model_dir in (
        ("shots_for", shots_model_dir),
        ("shots_on_target", sot_model_dir),
    ):
        model_spec = xgb_model.MODEL_SPECS[model_name]
        model, feature_columns, metadata = xgb_model.load_model_and_features(model_dir)
        xgb_model.validate_loaded_model_spec(metadata, model_spec)
        clip_min = float(metadata.get("clip_min", model_spec.clip_min))
        clip_max = float(metadata.get("clip_max", model_spec.clip_max))
        df[model_spec.prediction_column] = xgb_model.predict_dataset(
            df,
            model,
            feature_columns,
            clip_min,
            clip_max,
        )

    columns = [
        "match_id",
        "team_id",
        "shots_for_hat",
        "shots_on_target_hat",
    ]
    output = df[columns].copy()
    output["shots_for_hat"] = pd.to_numeric(output["shots_for_hat"], errors="coerce")
    output["shots_on_target_hat"] = pd.to_numeric(
        output["shots_on_target_hat"],
        errors="coerce",
    )
    return output


def clip_share(value: Any, fallback: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = fallback
    if math.isnan(numeric):
        numeric = fallback
    return min(max(numeric, 0.0), 1.0)


def resolve_player_share(row: Any, market_key: str) -> float:
    if market_key == MARKET_KEY_SOT:
        fallback = clip_share(
            getattr(row, "rolling_position_sot_share", None),
            default_position_share(getattr(row, "position_group", None), market_key),
        )
        return clip_share(getattr(row, "rolling_player_sot_share_5", None), fallback)
    fallback = clip_share(
        getattr(row, "rolling_position_shot_share", None),
        default_position_share(getattr(row, "position_group", None), market_key),
    )
    return clip_share(getattr(row, "rolling_player_shot_share_5", None), fallback)


def prepare_numeric_columns(df, pd):
    df = df.copy()
    numeric_columns = [
        *FEATURE_COLUMNS,
        TARGET_PLAYER_SHOTS,
        TARGET_PLAYER_SOT,
        TARGET_MINUTES,
        "shots_for_hat",
        "shots_on_target_hat",
        "expected_minutes",
    ]
    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def build_allocations(features, team_rates, minutes):
    _, pd = require_runtime_dependencies()
    if features.empty:
        raise SystemExit("No player prop feature rows found. Run refresh-features first.")
    merged = features.merge(team_rates, on=["match_id", "team_id"], how="inner")
    merged = merged.merge(
        minutes[
            [
                "player_minutes_run_id",
                "match_id",
                "team_id",
                "player_id",
                "expected_minutes",
            ]
        ],
        on=["match_id", "team_id", "player_id"],
        how="inner",
    )
    if merged.empty:
        raise SystemExit(
            "No joined rows between prop features, team rate predictions, and player minutes."
        )
    merged = prepare_numeric_columns(merged, pd)
    shot_shares = []
    sot_shares = []
    for row in merged.itertuples(index=False):
        shot_shares.append(resolve_player_share(row, MARKET_KEY_SHOTS))
        sot_shares.append(resolve_player_share(row, MARKET_KEY_SOT))
    merged["player_shot_share"] = shot_shares
    merged["player_sot_share"] = sot_shares
    merged["expected_minutes"] = merged["expected_minutes"].fillna(0)
    merged["shots_for_hat"] = merged["shots_for_hat"].fillna(0)
    merged["shots_on_target_hat"] = merged["shots_on_target_hat"].fillna(0)
    merged["minutes_factor"] = merged["expected_minutes"].clip(lower=0, upper=120) / 90.0
    merged["player_expected_shots"] = (
        merged["shots_for_hat"].clip(lower=0)
        * merged["player_shot_share"]
        * merged["minutes_factor"]
    )
    merged["player_expected_sot"] = (
        merged["shots_on_target_hat"].clip(lower=0)
        * merged["player_sot_share"]
        * merged["minutes_factor"]
    )
    return merged


def poisson_under_probability(mean: float, line: float) -> float:
    mean = float(mean)
    if math.isnan(mean):
        mean = 0.0
    mean = max(mean, 0.0)
    threshold = int(math.floor(float(line)))
    cumulative = 0.0
    term = math.exp(-mean)
    for count in range(threshold + 1):
        if count == 0:
            term = math.exp(-mean)
        elif mean == 0.0:
            term = 0.0
        else:
            term *= mean / count
        cumulative += term
    return min(max(cumulative, 0.0), 1.0)


def poisson_over_probability(mean: float, line: float) -> float:
    return min(max(1.0 - poisson_under_probability(mean, line), 0.0), 1.0)


def probability_rows_for_allocation(row: Any) -> list[dict[str, Any]]:
    rows = []
    markets = (
        (MARKET_KEY_SHOTS, float(row.player_expected_shots)),
        (MARKET_KEY_SOT, float(row.player_expected_sot)),
    )
    for market_key, expected_value in markets:
        for line in PROP_LINES:
            under = poisson_under_probability(expected_value, line)
            over = 1.0 - under
            for selection, probability in (("over", over), ("under", under)):
                rows.append(
                    {
                        "player_minutes_run_id": int(row.player_minutes_run_id),
                        "match_id": row.match_id,
                        "sofascore_event_id": row.sofascore_event_id,
                        "season_year": row.season_year,
                        "match_date": row.match_date,
                        "team_id": row.team_id,
                        "opponent_id": row.opponent_id,
                        "player_id": row.player_id,
                        "player_name": row.player_name,
                        "player_position": row.player_position,
                        "market_key": market_key,
                        "selection": selection,
                        "line": line,
                        "probability": probability,
                        "expected_value": expected_value,
                        "team_shots_hat": row.shots_for_hat,
                        "team_sot_hat": row.shots_on_target_hat,
                        "player_shot_share": row.player_shot_share,
                        "player_sot_share": row.player_sot_share,
                        "expected_minutes": row.expected_minutes,
                    }
                )
    return rows


def build_probability_rows(allocations) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in allocations.itertuples(index=False):
        rows.extend(probability_rows_for_allocation(row))
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def upsert_player_prop_run(
    db_url: str,
    run_name: str,
    mode: str,
    player_minutes_run_id: int,
    shots_model_dir: Path,
    sot_model_dir: Path,
    metadata: dict[str, Any],
) -> int:
    psycopg, _, Jsonb = require_database_dependency()
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_outputs.player_prop_runs (
                    run_name, mode, player_minutes_run_id, source_model_dirs,
                    parameters, metrics, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_name) DO UPDATE SET
                    mode = EXCLUDED.mode,
                    created_at = now(),
                    player_minutes_run_id = EXCLUDED.player_minutes_run_id,
                    source_model_dirs = EXCLUDED.source_model_dirs,
                    parameters = EXCLUDED.parameters,
                    metrics = EXCLUDED.metrics,
                    metadata = EXCLUDED.metadata
                RETURNING id
                """,
                (
                    run_name,
                    mode,
                    player_minutes_run_id,
                    Jsonb(
                        {
                            "shots_for": str(shots_model_dir),
                            "shots_on_target": str(sot_model_dir),
                        }
                    ),
                    Jsonb({"lines": list(PROP_LINES), "distribution": "poisson"}),
                    Jsonb(metadata.get("metrics", {})),
                    Jsonb(metadata),
                ),
            )
            return int(cur.fetchone()[0])


def persist_probability_rows(db_url: str, run_id: int, rows: list[dict[str, Any]]) -> int:
    psycopg, _, _ = require_database_dependency()
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM model_outputs.player_prop_probabilities WHERE run_id = %s",
                (run_id,),
            )
            cur.executemany(
                """
                INSERT INTO model_outputs.player_prop_probabilities (
                    run_id, player_minutes_run_id, match_id, sofascore_event_id,
                    season_year, match_date, team_id, opponent_id, player_id,
                    player_name, player_position, market_key, selection, line,
                    probability, expected_value, team_shots_hat, team_sot_hat,
                    player_shot_share, player_sot_share, expected_minutes
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                [
                    (
                        run_id,
                        row["player_minutes_run_id"],
                        row["match_id"],
                        row["sofascore_event_id"],
                        row["season_year"],
                        row["match_date"],
                        row["team_id"],
                        row["opponent_id"],
                        row["player_id"],
                        row["player_name"],
                        row["player_position"],
                        row["market_key"],
                        row["selection"],
                        row["line"],
                        row["probability"],
                        row["expected_value"],
                        row["team_shots_hat"],
                        row["team_sot_hat"],
                        row["player_shot_share"],
                        row["player_sot_share"],
                        row["expected_minutes"],
                    )
                    for row in rows
                ],
            )
    return len(rows)


def prediction_metadata(
    mode: str,
    player_minutes_run_id: int,
    features_count: int,
    allocations_count: int,
    probability_count: int,
    shots_model_dir: Path,
    sot_model_dir: Path,
) -> dict[str, Any]:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "model_name": "player_prop_allocation",
        "markets": [MARKET_KEY_SHOTS, MARKET_KEY_SOT],
        "lines": list(PROP_LINES),
        "distribution": "poisson",
        "player_minutes_run_id": player_minutes_run_id,
        "source_model_dirs": {
            "shots_for": str(shots_model_dir),
            "shots_on_target": str(sot_model_dir),
        },
        "metrics": {
            "feature_rows": features_count,
            "allocation_rows": allocations_count,
            "probability_rows": probability_count,
        },
    }


def run_prediction(
    db_url: str,
    mode: str,
    player_minutes_run_id: int | None,
    shots_model_dir: Path,
    sot_model_dir: Path,
    match_id: int | None = None,
    sofascore_event_id: int | None = None,
    output: Path | None = None,
    write_db: bool = True,
    run_name: str | None = None,
) -> dict[str, Any]:
    if mode == "match_prediction" and match_id is None and sofascore_event_id is None:
        raise SystemExit("predict-match requires --match-id or --sofascore-event-id")
    features = load_features(
        db_url,
        match_id=match_id,
        sofascore_event_id=sofascore_event_id,
    )
    resolved_minutes_run_id, minutes = load_player_minutes_predictions(
        db_url,
        player_minutes_run_id=player_minutes_run_id,
        match_id=match_id,
        sofascore_event_id=sofascore_event_id,
    )
    team_rates = score_team_rate_models(
        db_url,
        shots_model_dir=shots_model_dir,
        sot_model_dir=sot_model_dir,
        match_id=match_id,
        sofascore_event_id=sofascore_event_id,
    )
    allocations = build_allocations(features, team_rates, minutes)
    rows = build_probability_rows(allocations)
    if output is not None:
        write_csv(output, rows)

    metadata = prediction_metadata(
        mode=mode,
        player_minutes_run_id=resolved_minutes_run_id,
        features_count=len(features),
        allocations_count=len(allocations),
        probability_count=len(rows),
        shots_model_dir=shots_model_dir,
        sot_model_dir=sot_model_dir,
    )
    db_run_id = None
    if write_db:
        default_run_name = (
            f"player_props_{mode}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        )
        db_run_id = upsert_player_prop_run(
            db_url,
            run_name=run_name or default_run_name,
            mode=mode,
            player_minutes_run_id=resolved_minutes_run_id,
            shots_model_dir=shots_model_dir,
            sot_model_dir=sot_model_dir,
            metadata=metadata,
        )
        persist_probability_rows(db_url, db_run_id, rows)

    return {
        "feature_rows": len(features),
        "allocation_rows": len(allocations),
        "probability_rows": len(rows),
        "player_minutes_run_id": resolved_minutes_run_id,
        **({"db_run_id": db_run_id} if db_run_id is not None else {}),
        **({"output": str(output)} if output is not None else {}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Allocate team shot/SOT rates to player prop probabilities."
    )
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL", DEFAULT_DB_URL))
    parser.add_argument("--create-schema", action="store_true")
    parser.add_argument("--player-minutes-run-id", type=int)
    parser.add_argument("--shots-model-dir", type=Path, default=DEFAULT_SHOTS_MODEL_DIR)
    parser.add_argument("--shots-on-target-model-dir", type=Path, default=DEFAULT_SOT_MODEL_DIR)
    parser.add_argument("--no-write-db", action="store_true")
    parser.add_argument("--run-name")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "refresh-features",
        help="Refresh leak-free player prop allocation features.",
    )

    history_parser = subparsers.add_parser(
        "predict-history",
        help="Generate historical player prop probabilities.",
    )
    history_parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "history_probabilities.csv",
    )

    match_parser = subparsers.add_parser(
        "predict-match",
        help="Generate player prop probabilities for one match.",
    )
    match_parser.add_argument("--match-id", type=int)
    match_parser.add_argument("--sofascore-event-id", type=int)
    match_parser.add_argument("--output", type=Path)

    args = parser.parse_args()
    if args.create_schema:
        execute_sql_file(args.db_url, SCHEMA_PATH)

    if args.command == "refresh-features":
        rows = refresh_features(args.db_url)
        print(f"Refreshed {rows} player prop allocation feature rows")
    elif args.command == "predict-history":
        result = run_prediction(
            db_url=args.db_url,
            mode="history_prediction",
            player_minutes_run_id=args.player_minutes_run_id,
            shots_model_dir=args.shots_model_dir,
            sot_model_dir=args.shots_on_target_model_dir,
            output=args.output,
            write_db=not args.no_write_db,
            run_name=args.run_name,
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    elif args.command == "predict-match":
        result = run_prediction(
            db_url=args.db_url,
            mode="match_prediction",
            player_minutes_run_id=args.player_minutes_run_id,
            shots_model_dir=args.shots_model_dir,
            sot_model_dir=args.shots_on_target_model_dir,
            match_id=args.match_id,
            sofascore_event_id=args.sofascore_event_id,
            output=args.output,
            write_db=not args.no_write_db,
            run_name=args.run_name,
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
