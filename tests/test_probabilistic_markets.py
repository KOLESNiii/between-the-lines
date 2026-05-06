from pathlib import Path

import pandas as pd
import pytest

from probabilistic_markets import (
    CalibrationParams,
    build_match_inputs,
    construct_lambdas,
    derive_market_probabilities,
    grid_total,
    poisson_pmf,
    probability_artifact_paths,
    scoreline_grid,
)


def probability(rows, market_key, selection, line=None):
    for row in rows:
        if (
            row["market_key"] == market_key
            and row["selection"] == selection
            and row["line"] == line
        ):
            return row["probability"]
    raise AssertionError(f"Missing market row: {market_key} {selection} {line}")


def test_poisson_pmf_sums_to_nearly_one_with_large_grid():
    assert sum(poisson_pmf(1.4, 30)) == pytest.approx(1.0, abs=1e-9)


def test_dixon_coles_grid_is_nonnegative_and_normalized():
    grid = scoreline_grid(lambda_home=1.5, lambda_away=1.1, rho=-0.08, max_goals=12)

    assert grid_total(grid) == pytest.approx(1.0)
    assert min(prob for row in grid for prob in row) >= 0.0


def test_market_probabilities_are_derived_from_grid():
    grid = [
        [0.10, 0.05],
        [0.20, 0.65],
    ]
    rows = derive_market_probabilities(grid, total_lines=(0.5,))

    assert probability(rows, "1x2", "home") == pytest.approx(0.20)
    assert probability(rows, "1x2", "draw") == pytest.approx(0.75)
    assert probability(rows, "1x2", "away") == pytest.approx(0.05)
    assert probability(rows, "btts", "yes") == pytest.approx(0.65)
    assert probability(rows, "btts", "no") == pytest.approx(0.35)
    assert probability(rows, "total_goals", "over", 0.5) == pytest.approx(0.90)
    assert probability(rows, "exact_score", "1-0") == pytest.approx(0.20)


def test_build_match_inputs_rejects_incomplete_pair():
    df = pd.DataFrame(
        [
            {
                "match_id": 1,
                "side": "home",
                "team_id": 10,
                "team_name": "Home",
                "sofascore_event_id": 100,
                "season_year": "25/26",
                "match_date": "2025-08-15",
                "goals_for": 1,
                "xg_hat_for": 1.2,
                "shot_quality_hat": 0.1,
                "fragility_hat": 0.11,
            }
        ]
    )

    with pytest.raises(ValueError, match="Expected two team rows"):
        build_match_inputs(df)


def test_build_match_inputs_pairs_home_and_away_rows():
    df = pd.DataFrame(
        [
            {
                "match_id": 1,
                "side": "home",
                "team_id": 10,
                "team_name": "Home",
                "sofascore_event_id": 100,
                "season_year": "25/26",
                "match_date": "2025-08-15",
                "goals_for": 2,
                "xg_hat_for": 1.4,
                "shot_quality_hat": 0.12,
                "fragility_hat": 0.10,
            },
            {
                "match_id": 1,
                "side": "away",
                "team_id": 20,
                "team_name": "Away",
                "sofascore_event_id": 100,
                "season_year": "25/26",
                "match_date": "2025-08-15",
                "goals_for": 1,
                "xg_hat_for": 0.9,
                "shot_quality_hat": 0.09,
                "fragility_hat": 0.13,
            },
        ]
    )

    rows = build_match_inputs(df)

    assert rows == [
        {
            "match_id": 1,
            "sofascore_event_id": 100,
            "season_year": "25/26",
            "match_date": "2025-08-15",
            "home_team_id": 10,
            "away_team_id": 20,
            "home_team_name": "Home",
            "away_team_name": "Away",
            "home_goals": 2,
            "away_goals": 1,
            "xg_home": 1.4,
            "xg_away": 0.9,
            "shot_quality_home": 0.12,
            "shot_quality_away": 0.09,
            "fragility_home": 0.10,
            "fragility_away": 0.13,
        }
    ]


def test_construct_lambdas_clips_and_falls_back_for_missing_fragility():
    params = CalibrationParams(
        alpha=5.0,
        home_multiplier=3.0,
        away_multiplier=3.0,
        rho=0.0,
        league_avg_fragility=0.1,
    )
    row = {
        "xg_home": 3.0,
        "xg_away": 3.0,
        "fragility_home": None,
        "fragility_away": None,
    }

    assert construct_lambdas(row, params) == (5.5, 5.5)


def test_probability_schema_contract_mentions_expected_tables_and_indexes():
    sql = Path("schemas/probabilistic_markets.sql").read_text(encoding="utf-8")

    assert "CREATE SCHEMA IF NOT EXISTS model_outputs" in sql
    assert "model_outputs.market_probability_runs" in sql
    assert "model_outputs.match_probability_inputs" in sql
    assert "model_outputs.market_probabilities" in sql
    assert "idx_market_probabilities_match_market" in sql


def test_probability_artifact_paths_contract():
    paths = probability_artifact_paths(Path("models/probabilistic_markets"))

    assert paths["calibration"].name == "calibration.json"
    assert paths["validation_metrics"].name == "validation_metrics.json"
    assert paths["validation_summary"].name == "validation_probabilities.csv"
    assert paths["market_probabilities"].name == "market_probabilities.csv"
    assert paths["match_inputs"].name == "match_probability_inputs.csv"
