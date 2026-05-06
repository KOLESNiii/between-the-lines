import argparse
import csv
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import xgboost_xg_model as xgb_model


DEFAULT_DB_URL = xgb_model.DEFAULT_DB_URL
DEFAULT_MODEL_DIR = Path("models/probabilistic_markets")
DEFAULT_FINAL_MODEL_DIR = Path("models/probabilistic_markets_final")
DEFAULT_SCHEMA_PATH = Path("schemas/probabilistic_markets.sql")
DEFAULT_TRAIN_SEASONS = xgb_model.DEFAULT_TRAIN_SEASONS
DEFAULT_VALIDATION_SEASON = xgb_model.DEFAULT_VALIDATION_SEASON
DEFAULT_TOTAL_LINES = (0.5, 1.5, 2.5, 3.5, 4.5)
DEFAULT_MAX_GOALS = 12
LAMBDA_CLIP_RANGE = (0.05, 5.5)
EPSILON = 1e-12


@dataclass(frozen=True)
class CalibrationParams:
    alpha: float
    home_multiplier: float
    away_multiplier: float
    rho: float
    league_avg_fragility: float
    lambda_min: float = LAMBDA_CLIP_RANGE[0]
    lambda_max: float = LAMBDA_CLIP_RANGE[1]


def require_pandas():
    try:
        import pandas as pd
    except ImportError as exc:
        raise SystemExit(
            "Missing pandas dependency. Install requirements first: "
            "python3 -m pip install -r requirements.txt"
        ) from exc
    return pd


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Calibration artifact not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def create_schema(db_url: str, schema_path: Path = DEFAULT_SCHEMA_PATH) -> None:
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit(
            "Missing database dependency. Install requirements first: "
            "python3 -m pip install -r requirements.txt"
        ) from exc
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_path.read_text(encoding="utf-8"))
        conn.commit()


def probability_artifact_paths(model_dir: Path) -> dict[str, Path]:
    return {
        "calibration": model_dir / "calibration.json",
        "validation_metrics": model_dir / "validation_metrics.json",
        "validation_summary": model_dir / "validation_probabilities.csv",
        "market_probabilities": model_dir / "market_probabilities.csv",
        "match_inputs": model_dir / "match_probability_inputs.csv",
    }


def poisson_pmf(lambda_value: float, max_goals: int) -> list[float]:
    if lambda_value <= 0:
        raise ValueError("lambda_value must be positive")
    probabilities = [math.exp(-lambda_value)]
    for goals in range(1, max_goals + 1):
        probabilities.append(probabilities[-1] * lambda_value / goals)
    return probabilities


def dixon_coles_tau(
    home_goals: int,
    away_goals: int,
    lambda_home: float,
    lambda_away: float,
    rho: float,
) -> float:
    if home_goals == 0 and away_goals == 0:
        return 1.0 - lambda_home * lambda_away * rho
    if home_goals == 0 and away_goals == 1:
        return 1.0 + lambda_home * rho
    if home_goals == 1 and away_goals == 0:
        return 1.0 + lambda_away * rho
    if home_goals == 1 and away_goals == 1:
        return 1.0 - rho
    return 1.0


def scoreline_grid(
    lambda_home: float,
    lambda_away: float,
    rho: float,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> list[list[float]]:
    home_pmf = poisson_pmf(lambda_home, max_goals)
    away_pmf = poisson_pmf(lambda_away, max_goals)
    grid: list[list[float]] = []
    total = 0.0
    for home_goals, home_prob in enumerate(home_pmf):
        row = []
        for away_goals, away_prob in enumerate(away_pmf):
            tau = dixon_coles_tau(
                home_goals,
                away_goals,
                lambda_home,
                lambda_away,
                rho,
            )
            probability = max(home_prob * away_prob * tau, 0.0)
            row.append(probability)
            total += probability
        grid.append(row)
    if total <= 0:
        raise ValueError("Scoreline grid has zero total probability")
    return [[probability / total for probability in row] for row in grid]


def grid_total(grid: list[list[float]]) -> float:
    return sum(sum(row) for row in grid)


def derive_market_probabilities(
    grid: list[list[float]],
    total_lines: tuple[float, ...] = DEFAULT_TOTAL_LINES,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    max_goals = len(grid) - 1

    home_win = sum(
        grid[home][away]
        for home in range(max_goals + 1)
        for away in range(max_goals + 1)
        if home > away
    )
    draw = sum(grid[goals][goals] for goals in range(max_goals + 1))
    away_win = 1.0 - home_win - draw
    rows.extend(
        [
            market_row("1x2", "home", None, home_win),
            market_row("1x2", "draw", None, draw),
            market_row("1x2", "away", None, away_win),
        ]
    )

    btts_no = sum(
        grid[home][away]
        for home in range(max_goals + 1)
        for away in range(max_goals + 1)
        if home == 0 or away == 0
    )
    rows.extend(
        [
            market_row("btts", "yes", None, 1.0 - btts_no),
            market_row("btts", "no", None, btts_no),
        ]
    )

    for line in total_lines:
        over = sum(
            grid[home][away]
            for home in range(max_goals + 1)
            for away in range(max_goals + 1)
            if home + away > line
        )
        rows.extend(
            [
                market_row("total_goals", "over", line, over),
                market_row("total_goals", "under", line, 1.0 - over),
            ]
        )

    for home in range(max_goals + 1):
        for away in range(max_goals + 1):
            rows.append(market_row("exact_score", f"{home}-{away}", None, grid[home][away]))
    return rows


def market_row(
    market_key: str,
    selection: str,
    line: float | None,
    probability: float,
) -> dict[str, Any]:
    return {
        "market_key": market_key,
        "selection": selection,
        "line": line,
        "probability": min(max(float(probability), 0.0), 1.0),
    }


def market_probability_lookup(rows: list[dict[str, Any]]) -> dict[tuple[str, str, Any], float]:
    return {
        (row["market_key"], row["selection"], row["line"]): row["probability"]
        for row in rows
    }


def top_scorelines(rows: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    exact_scores = [
        row for row in rows if row["market_key"] == "exact_score"
    ]
    return sorted(exact_scores, key=lambda row: row["probability"], reverse=True)[:limit]


def construct_lambdas(row: dict[str, Any], params: CalibrationParams) -> tuple[float, float]:
    fragility_home = coalesce_float(row.get("fragility_home"), params.league_avg_fragility)
    fragility_away = coalesce_float(row.get("fragility_away"), params.league_avg_fragility)
    xg_home = coalesce_float(row.get("xg_home"), 0.0)
    xg_away = coalesce_float(row.get("xg_away"), 0.0)

    lambda_home = params.home_multiplier * xg_home * (
        1.0 + params.alpha * (fragility_away - params.league_avg_fragility)
    )
    lambda_away = params.away_multiplier * xg_away * (
        1.0 + params.alpha * (fragility_home - params.league_avg_fragility)
    )
    return (
        clip_float(lambda_home, params.lambda_min, params.lambda_max),
        clip_float(lambda_away, params.lambda_min, params.lambda_max),
    )


def clip_float(value: float, minimum: float, maximum: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return minimum
    return min(max(value, minimum), maximum)


def coalesce_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        result = float(value)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(result) else result


def build_match_inputs(scored_rows) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for match_id, match_rows in scored_rows.groupby("match_id", sort=False):
        if len(match_rows) != 2:
            raise ValueError(f"Expected two team rows for match_id={match_id}, found {len(match_rows)}")
        sides = set(match_rows["side"])
        if sides != {"home", "away"}:
            raise ValueError(f"Expected one home and one away row for match_id={match_id}")
        home = match_rows[match_rows["side"] == "home"].iloc[0]
        away = match_rows[match_rows["side"] == "away"].iloc[0]
        matches.append(
            {
                "match_id": int(match_id),
                "sofascore_event_id": nullable_int(home.get("sofascore_event_id")),
                "season_year": home["season_year"],
                "match_date": home["match_date"],
                "home_team_id": int(home["team_id"]),
                "away_team_id": int(away["team_id"]),
                "home_team_name": home["team_name"],
                "away_team_name": away["team_name"],
                "home_goals": nullable_int(home.get("goals_for")),
                "away_goals": nullable_int(away.get("goals_for")),
                "xg_home": float(home["xg_hat_for"]),
                "xg_away": float(away["xg_hat_for"]),
                "shot_quality_home": float(home["shot_quality_hat"]),
                "shot_quality_away": float(away["shot_quality_hat"]),
                "fragility_home": float(home["fragility_hat"]),
                "fragility_away": float(away["fragility_hat"]),
            }
        )
    return matches


def nullable_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result):
        return None
    return int(result)


def load_goal_labels(db_url: str, match_id: int | None, sofascore_event_id: int | None):
    pd = require_pandas()
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise SystemExit(
            "Missing database dependency. Install requirements first: "
            "python3 -m pip install -r requirements.txt"
        ) from exc

    filters = []
    params: list[Any] = []
    if match_id is not None:
        filters.append("match_id = %s")
        params.append(match_id)
    if sofascore_event_id is not None:
        filters.append("sofascore_event_id = %s")
        params.append(sofascore_event_id)
    where_clause = "WHERE " + " AND ".join(filters) if filters else ""
    sql = f"""
        SELECT match_id, team_id, goals_for, goals_against
        FROM features.sofascore_team_match_features
        {where_clause}
    """
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return pd.DataFrame(rows)


def score_xgboost_models(
    db_url: str,
    source_model_dirs: dict[str, Path],
    match_id: int | None = None,
    sofascore_event_id: int | None = None,
):
    pd = require_pandas()
    base_spec = xgb_model.MODEL_SPECS["xg_for"]
    df = xgb_model.load_dataset(
        db_url,
        labelled_only=False,
        match_id=match_id,
        sofascore_event_id=sofascore_event_id,
        model_spec=base_spec,
    )
    if df.empty:
        raise SystemExit("No feature rows found for requested scope")

    labels = load_goal_labels(db_url, match_id, sofascore_event_id)
    if not labels.empty:
        df = df.merge(labels, on=["match_id", "team_id"], how="left")
    else:
        df["goals_for"] = None
        df["goals_against"] = None

    for model_name, prediction_column in (
        ("xg_for", "xg_hat_for"),
        ("shot_quality", "shot_quality_hat"),
        ("fragility", "fragility_hat"),
    ):
        model_spec = xgb_model.MODEL_SPECS[model_name]
        model, feature_columns, metadata = xgb_model.load_model_and_features(
            source_model_dirs[model_name]
        )
        xgb_model.validate_loaded_model_spec(metadata, model_spec)
        clip_min = float(metadata.get("clip_min", model_spec.clip_min))
        clip_max = float(metadata.get("clip_max", model_spec.clip_max))
        df[prediction_column] = xgb_model.predict_dataset(
            df,
            model,
            feature_columns,
            clip_min,
            clip_max,
        )

    numeric_columns = [
        "xg_hat_for",
        "shot_quality_hat",
        "fragility_hat",
        "goals_for",
        "goals_against",
    ]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def filtered_finished_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        match
        for match in matches
        if match.get("home_goals") is not None and match.get("away_goals") is not None
    ]


def fit_calibration_params(
    matches: list[dict[str, Any]],
    max_goals: int = DEFAULT_MAX_GOALS,
) -> CalibrationParams:
    if not matches:
        raise ValueError("No matches available for calibration")
    league_avg_fragility = sum(
        (match["fragility_home"] + match["fragility_away"]) / 2.0 for match in matches
    ) / len(matches)
    params = CalibrationParams(
        alpha=0.0,
        home_multiplier=1.0,
        away_multiplier=1.0,
        rho=0.0,
        league_avg_fragility=league_avg_fragility,
    )
    bounds = {
        "alpha": (-5.0, 5.0),
        "home_multiplier": (0.5, 1.8),
        "away_multiplier": (0.5, 1.8),
        "rho": (-0.25, 0.25),
    }
    best_score = scoreline_nll(matches, params, max_goals=max_goals)
    for step in (0.25, 0.1, 0.05, 0.025, 0.01):
        improved = True
        while improved:
            improved = False
            for field in ("alpha", "home_multiplier", "away_multiplier", "rho"):
                for direction in (-1.0, 1.0):
                    candidate_value = getattr(params, field) + direction * step
                    lower, upper = bounds[field]
                    candidate_value = min(max(candidate_value, lower), upper)
                    if candidate_value == getattr(params, field):
                        continue
                    candidate = replace_param(params, field, candidate_value)
                    candidate_score = scoreline_nll(matches, candidate, max_goals=max_goals)
                    if candidate_score + 1e-10 < best_score:
                        params = candidate
                        best_score = candidate_score
                        improved = True
    return params


def replace_param(
    params: CalibrationParams,
    field: str,
    value: float,
) -> CalibrationParams:
    data = asdict(params)
    data[field] = value
    return CalibrationParams(**data)


def scoreline_nll(
    matches: list[dict[str, Any]],
    params: CalibrationParams,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> float:
    losses = []
    for match in matches:
        home_goals = int(match["home_goals"])
        away_goals = int(match["away_goals"])
        grid = scoreline_grid_for_match(match, params, max_goals=max_goals)
        if home_goals > max_goals or away_goals > max_goals:
            probability = EPSILON
        else:
            probability = grid[home_goals][away_goals]
        losses.append(-math.log(max(probability, EPSILON)))
    return sum(losses) / len(losses)


def scoreline_grid_for_match(
    match: dict[str, Any],
    params: CalibrationParams,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> list[list[float]]:
    lambda_home, lambda_away = construct_lambdas(match, params)
    return scoreline_grid(lambda_home, lambda_away, params.rho, max_goals=max_goals)


def evaluate_matches(
    matches: list[dict[str, Any]],
    params: CalibrationParams,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> dict[str, float]:
    if not matches:
        raise ValueError("No matches available for evaluation")
    scoreline_losses = []
    outcome_losses = []
    outcome_briers = []
    btts_losses = []
    btts_briers = []
    over25_losses = []
    over25_briers = []

    for match in matches:
        home_goals = int(match["home_goals"])
        away_goals = int(match["away_goals"])
        markets = market_probability_lookup(
            derive_market_probabilities(
                scoreline_grid_for_match(match, params, max_goals=max_goals)
            )
        )
        if home_goals <= max_goals and away_goals <= max_goals:
            score_probability = markets[("exact_score", f"{home_goals}-{away_goals}", None)]
        else:
            score_probability = EPSILON
        scoreline_losses.append(-math.log(max(score_probability, EPSILON)))

        outcome = "home" if home_goals > away_goals else "away" if away_goals > home_goals else "draw"
        outcome_probs = {
            "home": markets[("1x2", "home", None)],
            "draw": markets[("1x2", "draw", None)],
            "away": markets[("1x2", "away", None)],
        }
        outcome_losses.append(-math.log(max(outcome_probs[outcome], EPSILON)))
        outcome_briers.append(
            sum((outcome_probs[key] - (1.0 if key == outcome else 0.0)) ** 2 for key in outcome_probs)
        )

        btts_actual = home_goals > 0 and away_goals > 0
        btts_probability = markets[("btts", "yes", None)]
        btts_losses.append(binary_log_loss(btts_actual, btts_probability))
        btts_briers.append(binary_brier(btts_actual, btts_probability))

        over25_actual = home_goals + away_goals > 2.5
        over25_probability = markets[("total_goals", "over", 2.5)]
        over25_losses.append(binary_log_loss(over25_actual, over25_probability))
        over25_briers.append(binary_brier(over25_actual, over25_probability))

    return {
        "matches": len(matches),
        "scoreline_nll": mean(scoreline_losses),
        "one_x_two_log_loss": mean(outcome_losses),
        "one_x_two_brier": mean(outcome_briers),
        "btts_log_loss": mean(btts_losses),
        "btts_brier": mean(btts_briers),
        "over_2_5_log_loss": mean(over25_losses),
        "over_2_5_brier": mean(over25_briers),
    }


def binary_log_loss(actual: bool, probability: float) -> float:
    probability = min(max(probability, EPSILON), 1.0 - EPSILON)
    return -math.log(probability if actual else 1.0 - probability)


def binary_brier(actual: bool, probability: float) -> float:
    return (probability - (1.0 if actual else 0.0)) ** 2


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def baseline_params(matches: list[dict[str, Any]]) -> CalibrationParams:
    if not matches:
        raise ValueError("No matches available for baseline")
    league_avg_fragility = sum(
        (match["fragility_home"] + match["fragility_away"]) / 2.0 for match in matches
    ) / len(matches)
    return CalibrationParams(
        alpha=0.0,
        home_multiplier=1.0,
        away_multiplier=1.0,
        rho=0.0,
        league_avg_fragility=league_avg_fragility,
    )


def build_probability_outputs(
    matches: list[dict[str, Any]],
    params: CalibrationParams,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    input_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    market_rows: list[dict[str, Any]] = []
    for match in matches:
        lambda_home, lambda_away = construct_lambdas(match, params)
        input_row = {**match, "lambda_home": lambda_home, "lambda_away": lambda_away}
        input_rows.append(input_row)

        markets = derive_market_probabilities(
            scoreline_grid(lambda_home, lambda_away, params.rho, max_goals=max_goals)
        )
        lookup = market_probability_lookup(markets)
        top_scores = top_scorelines(markets)
        summary = {
            **input_row,
            "p_home_win": lookup[("1x2", "home", None)],
            "p_draw": lookup[("1x2", "draw", None)],
            "p_away_win": lookup[("1x2", "away", None)],
            "p_btts_yes": lookup[("btts", "yes", None)],
            "p_btts_no": lookup[("btts", "no", None)],
            "p_over_2_5": lookup[("total_goals", "over", 2.5)],
            "p_under_2_5": lookup[("total_goals", "under", 2.5)],
        }
        for index, score in enumerate(top_scores, start=1):
            summary[f"top_score_{index}"] = score["selection"]
            summary[f"top_score_{index}_probability"] = score["probability"]
        summary_rows.append(summary)
        for market in markets:
            market_rows.append({"match_id": match["match_id"], **market})
    return input_rows, summary_rows, market_rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_outputs_to_db(
    db_url: str,
    run_metadata: dict[str, Any],
    input_rows: list[dict[str, Any]],
    market_rows: list[dict[str, Any]],
) -> int:
    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise SystemExit(
            "Missing database dependency. Install requirements first: "
            "python3 -m pip install -r requirements.txt"
        ) from exc

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_outputs.market_probability_runs (
                    run_name, mode, train_seasons, validation_season,
                    source_model_dirs, parameters, metrics, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_name) DO UPDATE SET
                    mode = EXCLUDED.mode,
                    created_at = now(),
                    train_seasons = EXCLUDED.train_seasons,
                    validation_season = EXCLUDED.validation_season,
                    source_model_dirs = EXCLUDED.source_model_dirs,
                    parameters = EXCLUDED.parameters,
                    metrics = EXCLUDED.metrics,
                    metadata = EXCLUDED.metadata
                RETURNING id
                """,
                (
                    run_metadata["run_name"],
                    run_metadata["mode"],
                    run_metadata.get("train_seasons"),
                    run_metadata.get("validation_season"),
                    Jsonb(run_metadata.get("source_model_dirs", {})),
                    Jsonb(run_metadata.get("parameters", {})),
                    Jsonb(run_metadata.get("metrics", {})),
                    Jsonb(run_metadata.get("metadata", {})),
                ),
            )
            run_id = cur.fetchone()[0]
            cur.execute(
                "DELETE FROM model_outputs.match_probability_inputs WHERE run_id = %s",
                (run_id,),
            )
            cur.execute(
                "DELETE FROM model_outputs.market_probabilities WHERE run_id = %s",
                (run_id,),
            )
            cur.executemany(
                """
                INSERT INTO model_outputs.match_probability_inputs (
                    run_id, match_id, sofascore_event_id, season_year, match_date,
                    home_team_id, away_team_id, home_team_name, away_team_name,
                    home_goals, away_goals, xg_home, xg_away,
                    shot_quality_home, shot_quality_away,
                    fragility_home, fragility_away, lambda_home, lambda_away
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                [
                    (
                        run_id,
                        row["match_id"],
                        row["sofascore_event_id"],
                        row["season_year"],
                        row["match_date"],
                        row["home_team_id"],
                        row["away_team_id"],
                        row["home_team_name"],
                        row["away_team_name"],
                        row["home_goals"],
                        row["away_goals"],
                        row["xg_home"],
                        row["xg_away"],
                        row["shot_quality_home"],
                        row["shot_quality_away"],
                        row["fragility_home"],
                        row["fragility_away"],
                        row["lambda_home"],
                        row["lambda_away"],
                    )
                    for row in input_rows
                ],
            )
            cur.executemany(
                """
                INSERT INTO model_outputs.market_probabilities (
                    run_id, match_id, market_key, selection, line, probability
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        run_id,
                        row["match_id"],
                        row["market_key"],
                        row["selection"],
                        row["line"],
                        row["probability"],
                    )
                    for row in market_rows
                ],
            )
        conn.commit()
    return int(run_id)


def source_model_dirs(args) -> dict[str, Path]:
    if getattr(args, "use_validation_models", False):
        return {
            "xg_for": xgb_model.MODEL_SPECS["xg_for"].default_model_dir,
            "shot_quality": xgb_model.MODEL_SPECS["shot_quality"].default_model_dir,
            "fragility": xgb_model.MODEL_SPECS["fragility"].default_model_dir,
        }
    return {
        "xg_for": args.xg_model_dir or xgb_model.MODEL_SPECS["xg_for"].default_final_model_dir,
        "shot_quality": (
            args.shot_quality_model_dir
            or xgb_model.MODEL_SPECS["shot_quality"].default_final_model_dir
        ),
        "fragility": (
            args.fragility_model_dir
            or xgb_model.MODEL_SPECS["fragility"].default_final_model_dir
        ),
    }


def run_metadata(
    mode: str,
    model_dir: Path,
    params: CalibrationParams,
    metrics: dict[str, Any],
    sources: dict[str, Path],
    train_seasons: tuple[str, ...] | None = None,
    validation_season: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    return {
        "run_name": f"{mode}_{created_at}",
        "mode": mode,
        "created_at": created_at,
        "train_seasons": list(train_seasons) if train_seasons else None,
        "validation_season": validation_season,
        "source_model_dirs": {key: str(value) for key, value in sources.items()},
        "parameters": asdict(params),
        "metrics": metrics,
        "metadata": {
            "artifact_dir": str(model_dir),
            **(extra or {}),
        },
    }


def fit_calibration(
    db_url: str,
    model_dir: Path,
    sources: dict[str, Path],
    train_seasons: tuple[str, ...],
    validation_season: str,
    max_goals: int,
    write_db: bool,
) -> dict[str, Any]:
    scored_rows = score_xgboost_models(db_url, sources)
    matches = filtered_finished_matches(build_match_inputs(scored_rows))
    train = [match for match in matches if match["season_year"] in train_seasons]
    validation = [match for match in matches if match["season_year"] == validation_season]
    if not train:
        raise SystemExit(f"No calibration training matches found for {', '.join(train_seasons)}")
    if not validation:
        raise SystemExit(f"No validation matches found for {validation_season}")

    params = fit_calibration_params(train, max_goals=max_goals)
    validation_metrics = evaluate_matches(validation, params, max_goals=max_goals)
    baseline_metrics = evaluate_matches(
        validation,
        baseline_params(train),
        max_goals=max_goals,
    )
    metrics = {
        "validation": validation_metrics,
        "baseline": baseline_metrics,
    }
    input_rows, summary_rows, market_rows = build_probability_outputs(
        validation,
        params,
        max_goals=max_goals,
    )
    metadata = run_metadata(
        mode="calibration",
        model_dir=model_dir,
        params=params,
        metrics=metrics,
        sources=sources,
        train_seasons=train_seasons,
        validation_season=validation_season,
        extra={"max_goals": max_goals},
    )
    paths = probability_artifact_paths(model_dir)
    save_json(paths["calibration"], metadata)
    save_json(paths["validation_metrics"], metrics)
    write_csv(paths["validation_summary"], summary_rows)
    write_csv(paths["market_probabilities"], market_rows)
    write_csv(paths["match_inputs"], input_rows)
    if write_db:
        metadata["metadata"]["db_run_id"] = write_outputs_to_db(
            db_url,
            metadata,
            input_rows,
            market_rows,
        )
        save_json(paths["calibration"], metadata)
    return metadata


def fit_final(
    db_url: str,
    model_dir: Path,
    sources: dict[str, Path],
    max_goals: int,
    write_db: bool,
) -> dict[str, Any]:
    scored_rows = score_xgboost_models(db_url, sources)
    matches = filtered_finished_matches(build_match_inputs(scored_rows))
    if not matches:
        raise SystemExit("No finished matches found for final calibration")
    params = fit_calibration_params(matches, max_goals=max_goals)
    metrics = {"training": evaluate_matches(matches, params, max_goals=max_goals)}
    input_rows, summary_rows, market_rows = build_probability_outputs(
        matches,
        params,
        max_goals=max_goals,
    )
    metadata = run_metadata(
        mode="final",
        model_dir=model_dir,
        params=params,
        metrics=metrics,
        sources=sources,
        train_seasons=tuple(sorted({match["season_year"] for match in matches})),
        validation_season=None,
        extra={"max_goals": max_goals},
    )
    paths = probability_artifact_paths(model_dir)
    save_json(paths["calibration"], metadata)
    save_json(paths["validation_metrics"], metrics)
    write_csv(paths["validation_summary"], summary_rows)
    write_csv(paths["market_probabilities"], market_rows)
    write_csv(paths["match_inputs"], input_rows)
    if write_db:
        metadata["metadata"]["db_run_id"] = write_outputs_to_db(
            db_url,
            metadata,
            input_rows,
            market_rows,
        )
        save_json(paths["calibration"], metadata)
    return metadata


def predict_history(
    db_url: str,
    model_dir: Path,
    sources: dict[str, Path],
    max_goals: int,
    write_db: bool,
) -> dict[str, Any]:
    calibration = load_json(probability_artifact_paths(model_dir)["calibration"])
    params = CalibrationParams(**calibration["parameters"])
    scored_rows = score_xgboost_models(db_url, sources)
    matches = build_match_inputs(scored_rows)
    input_rows, summary_rows, market_rows = build_probability_outputs(
        matches,
        params,
        max_goals=max_goals,
    )
    paths = probability_artifact_paths(model_dir)
    write_csv(paths["validation_summary"], summary_rows)
    write_csv(paths["market_probabilities"], market_rows)
    write_csv(paths["match_inputs"], input_rows)
    metadata = run_metadata(
        mode="history_prediction",
        model_dir=model_dir,
        params=params,
        metrics={},
        sources=sources,
        extra={"max_goals": max_goals, "source_calibration": str(paths["calibration"])},
    )
    if write_db:
        metadata["metadata"]["db_run_id"] = write_outputs_to_db(
            db_url,
            metadata,
            input_rows,
            market_rows,
        )
    return {
        "matches": len(matches),
        "market_rows": len(market_rows),
        "summary_path": str(paths["validation_summary"]),
        "market_probabilities_path": str(paths["market_probabilities"]),
        **({"db_run_id": metadata["metadata"]["db_run_id"]} if write_db else {}),
    }


def predict_match(
    db_url: str,
    model_dir: Path,
    sources: dict[str, Path],
    match_id: int | None,
    sofascore_event_id: int | None,
    max_goals: int,
    output: Path | None,
    write_db: bool,
) -> dict[str, Any]:
    if match_id is None and sofascore_event_id is None:
        raise SystemExit("predict-match requires --match-id or --sofascore-event-id")
    calibration = load_json(probability_artifact_paths(model_dir)["calibration"])
    params = CalibrationParams(**calibration["parameters"])
    scored_rows = score_xgboost_models(
        db_url,
        sources,
        match_id=match_id,
        sofascore_event_id=sofascore_event_id,
    )
    matches = build_match_inputs(scored_rows)
    input_rows, summary_rows, market_rows = build_probability_outputs(
        matches,
        params,
        max_goals=max_goals,
    )
    if output is not None:
        write_csv(output, summary_rows)
    else:
        print_probability_summary(summary_rows)
    metadata = run_metadata(
        mode="match_prediction",
        model_dir=model_dir,
        params=params,
        metrics={},
        sources=sources,
        extra={"max_goals": max_goals, "source_calibration": str(probability_artifact_paths(model_dir)["calibration"])},
    )
    if write_db:
        metadata["metadata"]["db_run_id"] = write_outputs_to_db(
            db_url,
            metadata,
            input_rows,
            market_rows,
        )
    return {
        "matches": len(matches),
        "market_rows": len(market_rows),
        **({"db_run_id": metadata["metadata"]["db_run_id"]} if write_db else {}),
    }


def print_probability_summary(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        print(
            "match_id={match_id} {home_team_name} vs {away_team_name} "
            "lambda=({lambda_home:.3f}, {lambda_away:.3f}) "
            "1X2=({p_home_win:.3f}, {p_draw:.3f}, {p_away_win:.3f}) "
            "BTTS_yes={p_btts_yes:.3f} O2.5={p_over_2_5:.3f} "
            "top_score={top_score_1} ({top_score_1_probability:.3f})".format(**row)
        )


def parse_seasons(value: str) -> tuple[str, ...]:
    return xgb_model.parse_seasons(value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calibrate and score team market probabilities from XGBoost rates."
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DB_URL", DEFAULT_DB_URL),
        help="Postgres connection URL. Defaults to DB_URL or the local docker DB.",
    )
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="Create model_outputs probability tables before running the command.",
    )
    parser.add_argument("--xg-model-dir", type=Path)
    parser.add_argument("--shot-quality-model-dir", type=Path)
    parser.add_argument("--fragility-model-dir", type=Path)
    parser.add_argument(
        "--use-validation-models",
        action="store_true",
        help="Use validation XGBoost model directories instead of final model directories.",
    )
    parser.add_argument("--max-goals", type=int, default=DEFAULT_MAX_GOALS)
    parser.add_argument(
        "--no-db-write",
        action="store_true",
        help="Write artifacts only and skip model_outputs table inserts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    calibration_parser = subparsers.add_parser(
        "fit-calibration",
        help="Fit calibration parameters and validate on a held-out season.",
    )
    calibration_parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    calibration_parser.add_argument(
        "--train-seasons",
        default=",".join(DEFAULT_TRAIN_SEASONS),
    )
    calibration_parser.add_argument(
        "--validation-season",
        default=DEFAULT_VALIDATION_SEASON,
    )

    final_parser = subparsers.add_parser(
        "fit-final",
        help="Fit final calibration parameters on all finished labelled matches.",
    )
    final_parser.add_argument("--model-dir", type=Path, default=DEFAULT_FINAL_MODEL_DIR)

    history_parser = subparsers.add_parser(
        "predict-history",
        help="Score historical market probabilities using saved calibration.",
    )
    history_parser.add_argument("--model-dir", type=Path, default=DEFAULT_FINAL_MODEL_DIR)

    match_parser = subparsers.add_parser(
        "predict-match",
        help="Score market probabilities for one match.",
    )
    match_parser.add_argument("--model-dir", type=Path, default=DEFAULT_FINAL_MODEL_DIR)
    match_parser.add_argument("--match-id", type=int)
    match_parser.add_argument("--sofascore-event-id", type=int)
    match_parser.add_argument("--output", type=Path)

    args = parser.parse_args()
    if args.create_schema:
        create_schema(args.db_url)
    sources = source_model_dirs(args)
    write_db = not args.no_db_write

    if args.command == "fit-calibration":
        metadata = fit_calibration(
            db_url=args.db_url,
            model_dir=args.model_dir,
            sources=sources,
            train_seasons=parse_seasons(args.train_seasons),
            validation_season=args.validation_season,
            max_goals=args.max_goals,
            write_db=write_db,
        )
        print(json.dumps(metadata["metrics"], indent=2, sort_keys=True))
        print(f"Saved calibration artifacts to {args.model_dir}")
    elif args.command == "fit-final":
        metadata = fit_final(
            db_url=args.db_url,
            model_dir=args.model_dir,
            sources=sources,
            max_goals=args.max_goals,
            write_db=write_db,
        )
        print(json.dumps(metadata["metrics"], indent=2, sort_keys=True))
        print(f"Saved final probability artifacts to {args.model_dir}")
    elif args.command == "predict-history":
        result = predict_history(
            db_url=args.db_url,
            model_dir=args.model_dir,
            sources=sources,
            max_goals=args.max_goals,
            write_db=write_db,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.command == "predict-match":
        result = predict_match(
            db_url=args.db_url,
            model_dir=args.model_dir,
            sources=sources,
            match_id=args.match_id,
            sofascore_event_id=args.sofascore_event_id,
            max_goals=args.max_goals,
            output=args.output,
            write_db=write_db,
        )
        if args.output is not None:
            print(f"Wrote {result['matches']} match probability rows to {args.output}")


if __name__ == "__main__":
    main()
