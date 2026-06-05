from pathlib import Path

import pandas as pd
import pytest

from probabilistic_markets import (
    CalibrationParams,
    build_match_inputs,
    build_probability_outputs,
    calibrated_market_rows_for_match,
    construct_lambdas,
    derive_market_probabilities,
    fit_market_calibrators,
    grid_total,
    market_probability_lookup,
    poisson_pmf,
    probability_artifact_paths,
    scoreline_grid,
    tempo_multiplier_for_match,
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
            "feature_coverage_score_home": 0.0,
            "feature_coverage_score_away": 0.0,
            "xg_feature_available_home": False,
            "xg_feature_available_away": False,
            "rolling_history_count_home": None,
            "rolling_history_count_away": None,
            "tempo_feature_coverage_score_home": 0.0,
            "tempo_feature_coverage_score_away": 0.0,
            "rolling_tempo_count_home": None,
            "rolling_tempo_count_away": None,
            "match_tempo_index": 1.0,
        }
    ]


def test_build_match_inputs_carries_tempo_quality_fields():
    df = pd.DataFrame(
        [
            {
                "match_id": 2,
                "side": "home",
                "team_id": 10,
                "team_name": "Home",
                "sofascore_event_id": 200,
                "season_year": "25/26",
                "match_date": "2025-08-16",
                "goals_for": 0,
                "xg_hat_for": 1.0,
                "shot_quality_hat": 0.10,
                "fragility_hat": 0.11,
                "tempo_feature_coverage_score": 0.75,
                "rolling_tempo_count": 4,
                "match_tempo_index": 1.20,
            },
            {
                "match_id": 2,
                "side": "away",
                "team_id": 20,
                "team_name": "Away",
                "sofascore_event_id": 200,
                "season_year": "25/26",
                "match_date": "2025-08-16",
                "goals_for": 2,
                "xg_hat_for": 1.3,
                "shot_quality_hat": 0.13,
                "fragility_hat": 0.09,
                "tempo_feature_coverage_score": 0.50,
                "rolling_tempo_count": 2,
                "match_tempo_index": 1.10,
            },
        ]
    )

    rows = build_match_inputs(df)

    assert rows[0]["tempo_feature_coverage_score_home"] == pytest.approx(0.75)
    assert rows[0]["tempo_feature_coverage_score_away"] == pytest.approx(0.50)
    assert rows[0]["rolling_tempo_count_home"] == 4
    assert rows[0]["rolling_tempo_count_away"] == 2
    assert rows[0]["match_tempo_index"] == pytest.approx(1.15)


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


def test_construct_lambdas_applies_shared_tempo_multiplier():
    params = CalibrationParams(
        alpha=0.0,
        home_multiplier=1.0,
        away_multiplier=1.0,
        rho=0.0,
        league_avg_fragility=0.1,
        tempo_beta=0.5,
        league_avg_tempo_index=1.0,
    )
    row = {
        "xg_home": 1.2,
        "xg_away": 0.8,
        "fragility_home": 0.1,
        "fragility_away": 0.1,
        "match_tempo_index": 1.2,
    }

    assert tempo_multiplier_for_match(row, params) == pytest.approx(1.1)
    assert construct_lambdas(row, params) == pytest.approx((1.32, 0.88))


def test_dixon_coles_rho_changes_market_probabilities():
    independent = derive_market_probabilities(
        scoreline_grid(lambda_home=1.4, lambda_away=1.1, rho=0.0, max_goals=12)
    )
    correlated = derive_market_probabilities(
        scoreline_grid(lambda_home=1.4, lambda_away=1.1, rho=-0.1, max_goals=12)
    )

    independent_lookup = market_probability_lookup(independent)
    correlated_lookup = market_probability_lookup(correlated)
    assert correlated_lookup[("1x2", "draw", None)] != pytest.approx(
        independent_lookup[("1x2", "draw", None)]
    )
    assert correlated_lookup[("btts", "yes", None)] != pytest.approx(
        independent_lookup[("btts", "yes", None)]
    )


def synthetic_calibration_matches():
    matches = []
    for index in range(45):
        outcome = index % 3
        if outcome == 0:
            home_goals, away_goals = 3, 1
        elif outcome == 1:
            home_goals, away_goals = 0, 0
        else:
            home_goals, away_goals = 1, 3
        high_quality = index % 2 == 0
        matches.append(
            {
                "match_id": index + 1,
                "season_year": "25/26",
                "home_goals": home_goals,
                "away_goals": away_goals,
                "xg_home": 1.1 + 0.03 * outcome,
                "xg_away": 1.0 + 0.02 * (2 - outcome),
                "shot_quality_home": 0.18 if high_quality else 0.07,
                "shot_quality_away": 0.06 if high_quality else 0.17,
                "fragility_home": 0.08 if high_quality else 0.15,
                "fragility_away": 0.16 if high_quality else 0.09,
                "feature_coverage_score_home": 0.9,
                "feature_coverage_score_away": 0.8,
                "tempo_feature_coverage_score_home": 0.7,
                "tempo_feature_coverage_score_away": 0.6,
                "match_tempo_index": 1.15 if high_quality else 0.9,
            }
        )
    return matches


def test_market_calibration_serializes_low_dimensional_calibrators():
    matches = synthetic_calibration_matches()
    params = CalibrationParams(
        alpha=0.0,
        home_multiplier=1.0,
        away_multiplier=1.0,
        rho=0.0,
        league_avg_fragility=0.11,
    )

    calibrated = fit_market_calibrators(matches, params)

    assert "1x2" in calibrated.market_calibrators
    assert "btts" in calibrated.market_calibrators
    assert "total_goals" in calibrated.market_calibrators
    # Calibrators map the structural probabilities (outcome log-probs / market
    # logits) rather than the full feature vector — this low-variance form
    # generalises better out-of-sample. See experiments/calib*.py.
    assert calibrated.market_calibrators["1x2"]["feature_names"] == [
        "log_p_home",
        "log_p_draw",
        "log_p_away",
    ]
    assert calibrated.market_calibrators["btts"]["feature_names"] == ["logit_p_yes"]
    line_key = next(iter(calibrated.market_calibrators["total_goals"]))
    assert calibrated.market_calibrators["total_goals"][line_key]["feature_names"] == [
        "logit_p_over"
    ]


def test_calibrated_market_rows_override_direct_markets_but_keep_scorelines():
    matches = synthetic_calibration_matches()
    params = CalibrationParams(
        alpha=0.0,
        home_multiplier=1.0,
        away_multiplier=1.0,
        rho=0.0,
        league_avg_fragility=0.11,
    )
    calibrated = fit_market_calibrators(matches, params)
    match = matches[0]
    base_lookup = market_probability_lookup(
        derive_market_probabilities(
            scoreline_grid(*construct_lambdas(match, params), params.rho)
        )
    )
    calibrated_lookup = market_probability_lookup(
        calibrated_market_rows_for_match(match, calibrated)
    )

    assert calibrated_lookup[("1x2", "home", None)] != pytest.approx(
        base_lookup[("1x2", "home", None)]
    )
    assert calibrated_lookup[("btts", "yes", None)] != pytest.approx(
        base_lookup[("btts", "yes", None)]
    )
    assert calibrated_lookup[("total_goals", "over", 2.5)] != pytest.approx(
        base_lookup[("total_goals", "over", 2.5)]
    )
    assert calibrated_lookup[("exact_score", "1-0", None)] == pytest.approx(
        base_lookup[("exact_score", "1-0", None)]
    )


def test_probability_outputs_include_tempo_public_fields():
    match = synthetic_calibration_matches()[0]
    params = CalibrationParams(
        alpha=0.0,
        home_multiplier=1.0,
        away_multiplier=1.0,
        rho=0.0,
        league_avg_fragility=0.11,
        tempo_beta=0.5,
        league_avg_tempo_index=1.0,
    )

    input_rows, summary_rows, _ = build_probability_outputs([match], params)

    assert input_rows[0]["match_tempo_index"] == pytest.approx(1.15)
    assert input_rows[0]["tempo_multiplier"] == pytest.approx(1.075)
    assert summary_rows[0]["tempo_multiplier"] == pytest.approx(1.075)


def test_probability_schema_contract_mentions_expected_tables_and_indexes():
    sql = Path("schemas/probabilistic_markets.sql").read_text(encoding="utf-8")

    assert "CREATE SCHEMA IF NOT EXISTS model_outputs" in sql
    assert "model_outputs.market_probability_runs" in sql
    assert "model_outputs.match_probability_inputs" in sql
    assert "model_outputs.market_probabilities" in sql
    assert "tempo_multiplier NUMERIC" in sql
    assert "match_tempo_index NUMERIC" in sql
    assert "idx_market_probabilities_match_market" in sql


def test_probability_artifact_paths_contract():
    paths = probability_artifact_paths(Path("models/probabilistic_markets"))

    assert paths["calibration"].name == "calibration.json"
    assert paths["validation_metrics"].name == "validation_metrics.json"
    assert paths["validation_summary"].name == "validation_probabilities.csv"
    assert paths["market_probabilities"].name == "market_probabilities.csv"
    assert paths["match_inputs"].name == "match_probability_inputs.csv"
