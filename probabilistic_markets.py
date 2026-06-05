import argparse
import csv
import json
import math
import os
from dataclasses import asdict, dataclass, field
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
OUTCOME_LABELS = ("home", "draw", "away")
MARKET_FEATURE_NAMES = [
    "base_home_win",
    "base_draw",
    "base_away_win",
    "base_btts_yes",
    "base_over_probability",
    "line",
    "lambda_home",
    "lambda_away",
    "lambda_total",
    "lambda_diff",
    "xg_home",
    "xg_away",
    "xg_total",
    "xg_diff",
    "shot_quality_home",
    "shot_quality_away",
    "shot_quality_diff",
    "fragility_home",
    "fragility_away",
    "fragility_diff",
    "feature_coverage_home",
    "feature_coverage_away",
    "feature_coverage_diff",
    "tempo_feature_coverage_home",
    "tempo_feature_coverage_away",
    "tempo_feature_coverage_diff",
    "match_tempo_index",
    "tempo_multiplier",
]


@dataclass(frozen=True)
class CalibrationParams:
    alpha: float
    home_multiplier: float
    away_multiplier: float
    rho: float
    league_avg_fragility: float
    tempo_beta: float = 0.0
    league_avg_tempo_index: float = 1.0
    tempo_multiplier_min: float = 0.75
    tempo_multiplier_max: float = 1.30
    lambda_min: float = LAMBDA_CLIP_RANGE[0]
    lambda_max: float = LAMBDA_CLIP_RANGE[1]
    market_calibrators: dict[str, Any] = field(default_factory=dict)


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


def require_sklearn_logistic():
    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
    except ImportError as exc:
        raise SystemExit(
            "Missing calibration dependency. Install requirements first: "
            "python3 -m pip install -r requirements.txt"
        ) from exc
    return np, LogisticRegression


def base_market_context(
    match: dict[str, Any],
    params: CalibrationParams,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> dict[str, Any]:
    lambda_home, lambda_away = construct_lambdas(match, params)
    tempo_multiplier = tempo_multiplier_for_match(match, params)
    rows = derive_market_probabilities(
        scoreline_grid(lambda_home, lambda_away, params.rho, max_goals=max_goals)
    )
    return {
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "tempo_multiplier": tempo_multiplier,
        "rows": rows,
        "lookup": market_probability_lookup(rows),
    }


def market_feature_values(
    match: dict[str, Any],
    params: CalibrationParams,
    line: float,
    context: dict[str, Any] | None = None,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> list[float]:
    context = context or base_market_context(match, params, max_goals=max_goals)
    lookup = context["lookup"]
    lambda_home = float(context["lambda_home"])
    lambda_away = float(context["lambda_away"])
    xg_home = coalesce_float(match.get("xg_home"), 0.0)
    xg_away = coalesce_float(match.get("xg_away"), 0.0)
    shot_quality_home = coalesce_float(match.get("shot_quality_home"), 0.0)
    shot_quality_away = coalesce_float(match.get("shot_quality_away"), 0.0)
    fragility_home = coalesce_float(match.get("fragility_home"), params.league_avg_fragility)
    fragility_away = coalesce_float(match.get("fragility_away"), params.league_avg_fragility)
    feature_coverage_home = coalesce_float(match.get("feature_coverage_score_home"), 0.0)
    feature_coverage_away = coalesce_float(match.get("feature_coverage_score_away"), 0.0)
    tempo_feature_coverage_home = coalesce_float(
        match.get("tempo_feature_coverage_score_home"),
        0.0,
    )
    tempo_feature_coverage_away = coalesce_float(
        match.get("tempo_feature_coverage_score_away"),
        0.0,
    )
    match_tempo_index = coalesce_float(
        match.get("match_tempo_index"),
        params.league_avg_tempo_index,
    )
    tempo_multiplier = float(context["tempo_multiplier"])
    return [
        lookup[("1x2", "home", None)],
        lookup[("1x2", "draw", None)],
        lookup[("1x2", "away", None)],
        lookup[("btts", "yes", None)],
        lookup[("total_goals", "over", line)],
        float(line),
        lambda_home,
        lambda_away,
        lambda_home + lambda_away,
        lambda_home - lambda_away,
        xg_home,
        xg_away,
        xg_home + xg_away,
        xg_home - xg_away,
        shot_quality_home,
        shot_quality_away,
        shot_quality_home - shot_quality_away,
        fragility_home,
        fragility_away,
        fragility_home - fragility_away,
        feature_coverage_home,
        feature_coverage_away,
        feature_coverage_home - feature_coverage_away,
        tempo_feature_coverage_home,
        tempo_feature_coverage_away,
        tempo_feature_coverage_home - tempo_feature_coverage_away,
        match_tempo_index,
        tempo_multiplier,
    ]


def serialize_logistic_model(model, feature_names: list[str], class_labels: tuple[str, ...]) -> dict[str, Any]:
    classes = [class_labels[int(class_index)] for class_index in model.classes_]
    return {
        "type": "logistic_regression",
        "feature_names": feature_names,
        "classes": classes,
        "coef": model.coef_.tolist(),
        "intercept": model.intercept_.tolist(),
    }


def fit_serialized_logistic(
    X,
    y,
    class_labels: tuple[str, ...],
    feature_names: list[str],
    C: float = 1.0,
):
    unique_classes = sorted(set(y))
    if len(unique_classes) < 2:
        return None
    _, LogisticRegression = require_sklearn_logistic()
    model = LogisticRegression(C=C, max_iter=2000, random_state=42)
    model.fit(X, y)
    return serialize_logistic_model(model, feature_names, class_labels)


# --- Calibration features ----------------------------------------------------
# The calibrators map the structural (Dixon-Coles Poisson) market probabilities
# to corrected probabilities. They deliberately use a *low-dimensional* view of
# those probabilities (the outcome log-probs / market logits) rather than the
# full feature vector: a richer feature set was found to overfit and degrade
# out-of-sample log-loss across held-out seasons, whereas this low-variance
# parameterisation (multinomial temperature-style scaling for 1X2, Platt scaling
# for the binary markets) generalises and beats both the raw model and the
# previous high-dimensional calibrator. See experiments/calib*.py.
CAL_FEATURE_NAMES = {
    "1x2": ["log_p_home", "log_p_draw", "log_p_away"],
    "btts": ["logit_p_yes"],
    "total_goals": ["logit_p_over"],
}
# Near-unregularised binary calibrators behave like classic Platt scaling.
CAL_C = {"1x2": 1.0, "btts": 1.0e6, "total_goals": 1.0e6}


def _logit(probability: float) -> float:
    p = min(max(float(probability), EPSILON), 1.0 - EPSILON)
    return math.log(p / (1.0 - p))


def calibration_feature_values(
    market_key: str,
    line: float | None,
    context: dict[str, Any],
) -> list[float]:
    lookup = context["lookup"]
    if market_key == "1x2":
        return [
            math.log(max(lookup[("1x2", "home", None)], EPSILON)),
            math.log(max(lookup[("1x2", "draw", None)], EPSILON)),
            math.log(max(lookup[("1x2", "away", None)], EPSILON)),
        ]
    if market_key == "btts":
        return [_logit(lookup[("btts", "yes", None)])]
    if market_key == "total_goals":
        return [_logit(lookup[("total_goals", "over", line)])]
    raise ValueError(f"No calibration features for market {market_key}")


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def softmax(values: list[float]) -> list[float]:
    offset = max(values)
    exps = [math.exp(value - offset) for value in values]
    total = sum(exps)
    return [value / total for value in exps]


def predict_serialized_logistic(calibrator: dict[str, Any], features: list[float]) -> dict[str, float]:
    classes = calibrator["classes"]
    coefficients = calibrator["coef"]
    intercepts = calibrator["intercept"]
    logits = [
        sum(coef * feature for coef, feature in zip(row, features)) + intercept
        for row, intercept in zip(coefficients, intercepts)
    ]
    if len(classes) == 2 and len(logits) == 1:
        positive_probability = sigmoid(logits[0])
        return {
            classes[0]: 1.0 - positive_probability,
            classes[1]: positive_probability,
        }
    probabilities = softmax(logits)
    return dict(zip(classes, probabilities))


def fit_market_calibrators(
    matches: list[dict[str, Any]],
    params: CalibrationParams,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> CalibrationParams:
    np, _ = require_sklearn_logistic()
    contexts = [base_market_context(match, params, max_goals=max_goals) for match in matches]

    def feature_matrix(market_key: str, line: float | None):
        return np.asarray(
            [calibration_feature_values(market_key, line, context) for context in contexts],
            dtype=float,
        )

    outcome_targets = [
        0 if match["home_goals"] > match["away_goals"]
        else 2 if match["away_goals"] > match["home_goals"]
        else 1
        for match in matches
    ]
    btts_targets = [
        int(match["home_goals"] > 0 and match["away_goals"] > 0)
        for match in matches
    ]
    calibrators: dict[str, Any] = {}
    outcome_calibrator = fit_serialized_logistic(
        feature_matrix("1x2", None),
        outcome_targets,
        class_labels=OUTCOME_LABELS,
        feature_names=CAL_FEATURE_NAMES["1x2"],
        C=CAL_C["1x2"],
    )
    if outcome_calibrator is not None:
        calibrators["1x2"] = outcome_calibrator
    btts_calibrator = fit_serialized_logistic(
        feature_matrix("btts", None),
        btts_targets,
        class_labels=("no", "yes"),
        feature_names=CAL_FEATURE_NAMES["btts"],
        C=CAL_C["btts"],
    )
    if btts_calibrator is not None:
        calibrators["btts"] = btts_calibrator

    total_calibrators = {}
    for line in DEFAULT_TOTAL_LINES:
        total_targets = [
            int(match["home_goals"] + match["away_goals"] > line)
            for match in matches
        ]
        total_calibrator = fit_serialized_logistic(
            feature_matrix("total_goals", line),
            total_targets,
            class_labels=("under", "over"),
            feature_names=CAL_FEATURE_NAMES["total_goals"],
            C=CAL_C["total_goals"],
        )
        if total_calibrator is not None:
            total_calibrators[str(line)] = total_calibrator
    if total_calibrators:
        calibrators["total_goals"] = total_calibrators
    return replace_param(params, "market_calibrators", calibrators)


def filter_market_calibrators(
    params: CalibrationParams,
    selected_markets: set[str],
) -> CalibrationParams:
    calibrators = params.market_calibrators or {}
    return replace_param(
        params,
        "market_calibrators",
        {
            market: calibrator
            for market, calibrator in calibrators.items()
            if market in selected_markets
        },
    )


def fit_validated_market_calibrators(
    train: list[dict[str, Any]],
    validation: list[dict[str, Any]],
    params: CalibrationParams,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> tuple[CalibrationParams, dict[str, Any]]:
    candidate = fit_market_calibrators(train, params, max_goals=max_goals)
    base_metrics = evaluate_matches(validation, params, max_goals=max_goals)
    candidate_metrics = evaluate_matches(validation, candidate, max_goals=max_goals)
    selected: set[str] = set()
    comparisons = {
        "1x2": ("one_x_two_log_loss", "1x2"),
        "btts": ("btts_log_loss", "btts"),
        "total_goals_2_5": ("over_2_5_log_loss", "total_goals"),
    }
    details = {}
    for metric_name, market_key in comparisons.values():
        base_value = base_metrics[metric_name]
        candidate_value = candidate_metrics[metric_name]
        improved = candidate_value + 1e-12 < base_value
        if improved:
            selected.add(market_key)
        details[metric_name] = {
            "base": base_value,
            "candidate": candidate_value,
            "selected": improved,
        }
    return (
        filter_market_calibrators(candidate, selected),
        {
            "selected_market_calibrators": sorted(selected),
            "comparisons": details,
        },
    )


def select_calibrators_by_walkforward(
    matches: list[dict[str, Any]],
    max_goals: int = DEFAULT_MAX_GOALS,
    test_seasons: int = 4,
) -> tuple[set[str], dict[str, Any]]:
    """Robustly choose which markets to calibrate, by walk-forward evaluation.

    Selecting a calibrator on a single held-out season is noisy (a market may
    help on average yet hurt on one anomalous season, e.g. COVID 20/21). Here we
    walk forward over the most recent seasons that have at least two seasons of
    history: for each, fit params + calibrators on all prior seasons and compare
    the calibrated vs uncalibrated log-loss on the held-out season. A market is
    selected only if calibration improves the *mean* held-out log-loss.
    """
    season_order = sorted({str(m["season_year"]) for m in matches})
    index = {s: i for i, s in enumerate(season_order)}
    metric_for = {
        "1x2": "one_x_two_log_loss",
        "btts": "btts_log_loss",
        "total_goals": "over_2_5_log_loss",
    }
    agg = {market: {"base": [], "cand": []} for market in metric_for}
    candidates = [s for s in season_order[-test_seasons:] if index[s] >= 2]
    for ts in candidates:
        train = [m for m in matches if index[str(m["season_year"])] < index[ts]]
        test = [m for m in matches if str(m["season_year"]) == ts]
        if not train or not test:
            continue
        params = fit_calibration_params(train, max_goals=max_goals)
        calibrated = fit_market_calibrators(train, params, max_goals=max_goals)
        base_m = evaluate_matches(test, params, max_goals=max_goals)
        cand_m = evaluate_matches(test, calibrated, max_goals=max_goals)
        for market, metric in metric_for.items():
            agg[market]["base"].append(base_m[metric])
            agg[market]["cand"].append(cand_m[metric])
    selected: set[str] = set()
    detail = {}
    for market, metric in metric_for.items():
        base_vals, cand_vals = agg[market]["base"], agg[market]["cand"]
        if not base_vals:
            continue
        base_mean, cand_mean = mean(base_vals), mean(cand_vals)
        improved = cand_mean + 1e-12 < base_mean
        if improved:
            selected.add(market)
        detail[market] = {"base": base_mean, "candidate": cand_mean,
                          "selected": improved, "seasons": len(base_vals)}
    return selected, {"test_seasons": candidates, "comparisons": detail}


def validated_market_families(path: Path = DEFAULT_MODEL_DIR / "calibration.json") -> set[str] | None:
    if not path.exists():
        return None
    calibration = load_json(path)
    selected = calibration.get("metadata", {}).get("selected_market_calibrators")
    if selected is None:
        return None
    return set(selected)


def calibrated_market_rows_for_match(
    match: dict[str, Any],
    params: CalibrationParams,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> list[dict[str, Any]]:
    context = base_market_context(match, params, max_goals=max_goals)
    rows = [dict(row) for row in context["rows"]]
    overrides: dict[tuple[str, str, Any], float] = {}
    calibrators = params.market_calibrators or {}

    outcome_calibrator = calibrators.get("1x2")
    if outcome_calibrator:
        probabilities = predict_serialized_logistic(
            outcome_calibrator,
            calibration_feature_values("1x2", None, context),
        )
        for selection in OUTCOME_LABELS:
            overrides[("1x2", selection, None)] = probabilities[selection]

    btts_calibrator = calibrators.get("btts")
    if btts_calibrator:
        probabilities = predict_serialized_logistic(
            btts_calibrator,
            calibration_feature_values("btts", None, context),
        )
        yes_probability = probabilities["yes"]
        overrides[("btts", "yes", None)] = yes_probability
        overrides[("btts", "no", None)] = 1.0 - yes_probability

    total_calibrators = calibrators.get("total_goals", {})
    for line, total_calibrator in total_calibrators.items():
        line_value = float(line)
        probabilities = predict_serialized_logistic(
            total_calibrator,
            calibration_feature_values("total_goals", line_value, context),
        )
        over_probability = probabilities["over"]
        overrides[("total_goals", "over", line_value)] = over_probability
        overrides[("total_goals", "under", line_value)] = 1.0 - over_probability

    for row in rows:
        key = (row["market_key"], row["selection"], row["line"])
        if key in overrides:
            row["probability"] = min(max(float(overrides[key]), 0.0), 1.0)
    return rows


def tempo_multiplier_for_match(row: dict[str, Any], params: CalibrationParams) -> float:
    tempo_index = coalesce_float(
        row.get("match_tempo_index"),
        params.league_avg_tempo_index,
    )
    multiplier = 1.0 + params.tempo_beta * (
        tempo_index - params.league_avg_tempo_index
    )
    return clip_float(
        multiplier,
        params.tempo_multiplier_min,
        params.tempo_multiplier_max,
    )


def construct_lambdas(row: dict[str, Any], params: CalibrationParams) -> tuple[float, float]:
    fragility_home = coalesce_float(row.get("fragility_home"), params.league_avg_fragility)
    fragility_away = coalesce_float(row.get("fragility_away"), params.league_avg_fragility)
    xg_home = coalesce_float(row.get("xg_home"), 0.0)
    xg_away = coalesce_float(row.get("xg_away"), 0.0)
    tempo_multiplier = tempo_multiplier_for_match(row, params)

    lambda_home = tempo_multiplier * params.home_multiplier * xg_home * (
        1.0 + params.alpha * (fragility_away - params.league_avg_fragility)
    )
    lambda_away = tempo_multiplier * params.away_multiplier * xg_away * (
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
                "feature_coverage_score_home": coalesce_float(
                    home.get("feature_coverage_score"),
                    0.0,
                ),
                "feature_coverage_score_away": coalesce_float(
                    away.get("feature_coverage_score"),
                    0.0,
                ),
                "xg_feature_available_home": coalesce_bool(
                    home.get("xg_feature_available"),
                ),
                "xg_feature_available_away": coalesce_bool(
                    away.get("xg_feature_available"),
                ),
                "rolling_history_count_home": nullable_int(
                    home.get("rolling_history_count"),
                ),
                "rolling_history_count_away": nullable_int(
                    away.get("rolling_history_count"),
                ),
                "tempo_feature_coverage_score_home": coalesce_float(
                    home.get("tempo_feature_coverage_score"),
                    0.0,
                ),
                "tempo_feature_coverage_score_away": coalesce_float(
                    away.get("tempo_feature_coverage_score"),
                    0.0,
                ),
                "rolling_tempo_count_home": nullable_int(
                    home.get("rolling_tempo_count"),
                ),
                "rolling_tempo_count_away": nullable_int(
                    away.get("rolling_tempo_count"),
                ),
                "match_tempo_index": (
                    coalesce_float(home.get("match_tempo_index"), 1.0)
                    + coalesce_float(away.get("match_tempo_index"), 1.0)
                ) / 2.0,
            }
        )
    return matches


def coalesce_bool(value: Any, default: bool = False) -> bool:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            return value.lower() in {"1", "t", "true", "yes", "y"}
        result = float(value)
    except (TypeError, ValueError):
        try:
            return bool(value)
        except TypeError:
            return default
    return default if math.isnan(result) else bool(result)


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
        "feature_coverage_score",
        "rolling_history_count",
        "tempo_feature_coverage_score",
        "rolling_tempo_count",
        "match_tempo_index",
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
    league_avg_tempo_index = sum(
        coalesce_float(match.get("match_tempo_index"), 1.0) for match in matches
    ) / len(matches)
    params = CalibrationParams(
        alpha=0.0,
        home_multiplier=1.0,
        away_multiplier=1.0,
        rho=0.0,
        league_avg_fragility=league_avg_fragility,
        tempo_beta=0.0,
        league_avg_tempo_index=league_avg_tempo_index,
    )
    bounds = {
        "alpha": (-5.0, 5.0),
        "home_multiplier": (0.5, 1.8),
        "away_multiplier": (0.5, 1.8),
        "rho": (-0.25, 0.25),
        "tempo_beta": (-1.0, 1.0),
    }
    best_score = market_log_loss_score(matches, params, max_goals=max_goals)
    for step in (0.25, 0.1, 0.05, 0.025, 0.01):
        improved = True
        while improved:
            improved = False
            for field in ("alpha", "home_multiplier", "away_multiplier", "rho", "tempo_beta"):
                for direction in (-1.0, 1.0):
                    candidate_value = getattr(params, field) + direction * step
                    lower, upper = bounds[field]
                    candidate_value = min(max(candidate_value, lower), upper)
                    if candidate_value == getattr(params, field):
                        continue
                    candidate = replace_param(params, field, candidate_value)
                    candidate_score = market_log_loss_score(
                        matches,
                        candidate,
                        max_goals=max_goals,
                    )
                    if candidate_score + 1e-10 < best_score:
                        params = candidate
                        best_score = candidate_score
                        improved = True
    return params


def replace_param(
    params: CalibrationParams,
    field: str,
    value: Any,
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


def market_log_loss_score(
    matches: list[dict[str, Any]],
    params: CalibrationParams,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> float:
    metrics = evaluate_matches(matches, params, max_goals=max_goals)
    return (
        metrics["one_x_two_log_loss"]
        + metrics["btts_log_loss"]
        + metrics["over_2_5_log_loss"]
    ) / 3.0


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
            calibrated_market_rows_for_match(match, params, max_goals=max_goals)
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
    league_avg_tempo_index = sum(
        coalesce_float(match.get("match_tempo_index"), 1.0) for match in matches
    ) / len(matches)
    return CalibrationParams(
        alpha=0.0,
        home_multiplier=1.0,
        away_multiplier=1.0,
        rho=0.0,
        league_avg_fragility=league_avg_fragility,
        tempo_beta=0.0,
        league_avg_tempo_index=league_avg_tempo_index,
    )


def per_season_metrics(
    matches: list[dict[str, Any]],
    params: CalibrationParams,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for match in matches:
        grouped.setdefault(str(match["season_year"]), []).append(match)
    return {
        season: evaluate_matches(season_matches, params, max_goals=max_goals)
        for season, season_matches in sorted(grouped.items())
    }


def feature_coverage_summary(matches: list[dict[str, Any]]) -> dict[str, Any]:
    if not matches:
        return {
            "matches": 0,
            "avg_feature_coverage_score": None,
            "avg_tempo_feature_coverage_score": None,
            "avg_rolling_history_count": None,
            "avg_rolling_tempo_count": None,
            "xg_labelled_matches": 0,
            "training_backfill_matches": 0,
        }
    coverage_values = []
    tempo_coverage_values = []
    rolling_counts = []
    tempo_counts = []
    xg_labelled_matches = 0
    for match in matches:
        coverage_values.extend(
            [
                coalesce_float(match.get("feature_coverage_score_home"), 0.0),
                coalesce_float(match.get("feature_coverage_score_away"), 0.0),
            ]
        )
        tempo_coverage_values.extend(
            [
                coalesce_float(match.get("tempo_feature_coverage_score_home"), 0.0),
                coalesce_float(match.get("tempo_feature_coverage_score_away"), 0.0),
            ]
        )
        for key in ("rolling_history_count_home", "rolling_history_count_away"):
            value = match.get(key)
            if value is not None:
                rolling_counts.append(float(value))
        for key in ("rolling_tempo_count_home", "rolling_tempo_count_away"):
            value = match.get(key)
            if value is not None:
                tempo_counts.append(float(value))
        if (
            match.get("xg_feature_available_home")
            and match.get("xg_feature_available_away")
        ):
            xg_labelled_matches += 1
    return {
        "matches": len(matches),
        "avg_feature_coverage_score": mean(coverage_values),
        "avg_tempo_feature_coverage_score": mean(tempo_coverage_values),
        "avg_rolling_history_count": mean(rolling_counts) if rolling_counts else None,
        "avg_rolling_tempo_count": mean(tempo_counts) if tempo_counts else None,
        "xg_labelled_matches": xg_labelled_matches,
        "training_backfill_matches": len(matches) - xg_labelled_matches,
    }


def xg_labelled_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        match
        for match in matches
        if match.get("xg_feature_available_home")
        and match.get("xg_feature_available_away")
    ]


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
        input_row = {
            **match,
            "lambda_home": lambda_home,
            "lambda_away": lambda_away,
            "tempo_multiplier": tempo_multiplier_for_match(match, params),
        }
        input_rows.append(input_row)

        markets = calibrated_market_rows_for_match(match, params, max_goals=max_goals)
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
                    fragility_home, fragility_away,
                    feature_coverage_score_home, feature_coverage_score_away,
                    xg_feature_available_home, xg_feature_available_away,
                    rolling_history_count_home, rolling_history_count_away,
                    tempo_feature_coverage_score_home, tempo_feature_coverage_score_away,
                    rolling_tempo_count_home, rolling_tempo_count_away,
                    match_tempo_index, tempo_multiplier,
                    lambda_home, lambda_away
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
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
                        row["feature_coverage_score_home"],
                        row["feature_coverage_score_away"],
                        row["xg_feature_available_home"],
                        row["xg_feature_available_away"],
                        row["rolling_history_count_home"],
                        row["rolling_history_count_away"],
                        row["tempo_feature_coverage_score_home"],
                        row["tempo_feature_coverage_score_away"],
                        row["rolling_tempo_count_home"],
                        row["rolling_tempo_count_away"],
                        row["match_tempo_index"],
                        row["tempo_multiplier"],
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

    params, calibrator_selection = fit_validated_market_calibrators(
        train,
        validation,
        fit_calibration_params(train, max_goals=max_goals),
        max_goals=max_goals,
    )
    baseline = baseline_params(train)
    validation_metrics = evaluate_matches(validation, params, max_goals=max_goals)
    baseline_metrics = evaluate_matches(
        validation,
        baseline,
        max_goals=max_goals,
    )
    metrics = {
        "validation": validation_metrics,
        "baseline": baseline_metrics,
        "validation_by_season": per_season_metrics(
            validation,
            params,
            max_goals=max_goals,
        ),
        "baseline_by_season": per_season_metrics(
            validation,
            baseline,
            max_goals=max_goals,
        ),
        "feature_coverage": {
            "train": feature_coverage_summary(train),
            "validation": feature_coverage_summary(validation),
        },
        "market_calibrator_selection": calibrator_selection,
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
        extra={
            "max_goals": max_goals,
            "selected_market_calibrators": calibrator_selection[
                "selected_market_calibrators"
            ],
        },
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
    training_matches = xg_labelled_matches(matches)
    if not training_matches:
        raise SystemExit("No xG-labelled matches found for final calibration")
    params = fit_market_calibrators(
        training_matches,
        fit_calibration_params(training_matches, max_goals=max_goals),
        max_goals=max_goals,
    )
    selected_markets, walkforward_selection = select_calibrators_by_walkforward(
        training_matches, max_goals=max_goals
    )
    params = filter_market_calibrators(params, selected_markets)
    metrics = {
        "walkforward_calibrator_selection": walkforward_selection,
        "training": evaluate_matches(training_matches, params, max_goals=max_goals),
        "training_by_season": per_season_metrics(
            training_matches,
            params,
            max_goals=max_goals,
        ),
        "training_backfill": evaluate_matches(matches, params, max_goals=max_goals),
        "training_backfill_by_season": per_season_metrics(
            matches,
            params,
            max_goals=max_goals,
        ),
        "feature_coverage": {
            "training": feature_coverage_summary(training_matches),
            "training_backfill": feature_coverage_summary(matches),
        },
    }
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
        train_seasons=tuple(sorted({match["season_year"] for match in training_matches})),
        validation_season=None,
        extra={
            "max_goals": max_goals,
            "selected_market_calibrators": sorted(selected_markets),
        },
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
            "tempo={tempo_multiplier:.3f} "
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
