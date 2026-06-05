from pathlib import Path

import numpy as np
import pytest

from match_simulation import (
    MARKET_KEY_SHOTS,
    MARKET_KEY_SOT,
    PlayerSimulationInput,
    build_parser,
    collapse_player_prop_rows,
    normalize_exact_score_rows,
    sample_scorelines,
    simulate_match_summaries,
    simulate_player_draws,
    summarize_goal_draws,
    run_simulation,
)


def probability(rows, market_key, selection, line=None):
    for row in rows:
        if (
            row["market_key"] == market_key
            and row["selection"] == selection
            and row["line"] == line
        ):
            return row["simulated_probability"]
    raise AssertionError(f"Missing simulated market row: {market_key} {selection} {line}")


def player_prop_row(market_key, expected_value, selection, line):
    return {
        "match_id": 7,
        "team_id": 11,
        "player_id": 101,
        "player_name": "Finisher",
        "player_position": "F",
        "market_key": market_key,
        "selection": selection,
        "line": line,
        "expected_value": expected_value,
    }


def test_exact_score_rows_normalize_and_seed_score_sampling():
    rows = [
        {"market_key": "exact_score", "selection": "1-0", "probability": 2.0},
        {"market_key": "exact_score", "selection": "0-0", "probability": 1.0},
    ]

    distribution = normalize_exact_score_rows(rows)
    assert sum(probability for _, probability in distribution) == pytest.approx(1.0)
    assert {score.selection: probability for score, probability in distribution} == {
        "0-0": pytest.approx(1 / 3),
        "1-0": pytest.approx(2 / 3),
    }

    first = sample_scorelines(rows, draws=16, rng=np.random.default_rng(42))
    second = sample_scorelines(rows, draws=16, rng=np.random.default_rng(42))
    assert np.array_equal(first[0], second[0])
    assert np.array_equal(first[1], second[1])


def test_goal_draw_summaries_cover_supported_goal_markets():
    rows = summarize_goal_draws(
        match_id=7,
        home_goals=np.array([1, 0, 2, 1]),
        away_goals=np.array([0, 0, 2, 3]),
        total_lines=(0.5, 2.5),
    )

    assert probability(rows, "1x2", "home") == pytest.approx(0.25)
    assert probability(rows, "1x2", "draw") == pytest.approx(0.50)
    assert probability(rows, "1x2", "away") == pytest.approx(0.25)
    assert probability(rows, "btts", "yes") == pytest.approx(0.50)
    assert probability(rows, "total_goals", "over", 2.5) == pytest.approx(0.50)
    assert probability(rows, "exact_score", "1-0") == pytest.approx(0.25)


def test_player_prop_rows_collapse_repeated_lines_and_selections():
    rows = [
        player_prop_row(MARKET_KEY_SHOTS, 2.1, "over", 0.5),
        player_prop_row(MARKET_KEY_SHOTS, 2.1, "under", 0.5),
        player_prop_row(MARKET_KEY_SHOTS, 2.1, "over", 1.5),
        player_prop_row(MARKET_KEY_SOT, 0.8, "over", 0.5),
        player_prop_row(MARKET_KEY_SOT, 0.8, "under", 0.5),
    ]

    players, diagnostics = collapse_player_prop_rows(rows)

    assert players == [
        PlayerSimulationInput(
            match_id=7,
            team_id=11,
            player_id=101,
            player_name="Finisher",
            player_position="F",
            expected_shots=2.1,
            expected_sot=0.8,
        )
    ]
    assert diagnostics["player_input_rows"] == 5
    assert diagnostics["paired_player_inputs"] == 1


def test_player_shot_chain_keeps_sot_below_shots_and_records_clipping():
    players = [
        PlayerSimulationInput(7, 11, 101, "Finisher", "F", 2.0, 3.0),
        PlayerSimulationInput(7, 11, 102, "No Shot", "M", 0.0, 1.0),
    ]

    draws, clipped_players = simulate_player_draws(
        players,
        draws=128,
        rng=np.random.default_rng(9),
    )

    assert len(clipped_players) == 2
    for player_draw in draws:
        assert np.all(player_draw.shots_on_target <= player_draw.shots)
    assert np.all(draws[1].shots == 0)
    assert np.all(draws[1].shots_on_target == 0)


def test_invalid_player_expected_value_is_rejected():
    with pytest.raises(ValueError, match="finite non-negative"):
        collapse_player_prop_rows(
            [
                player_prop_row(MARKET_KEY_SHOTS, -0.1, "over", 0.5),
                player_prop_row(MARKET_KEY_SOT, 0.1, "over", 0.5),
            ]
        )


def test_synthetic_match_simulation_builds_goal_and_player_summaries():
    goal_rows = [
        {"market_key": "exact_score", "selection": "1-0", "probability": 0.70},
        {"market_key": "exact_score", "selection": "0-0", "probability": 0.30},
    ]
    prop_rows = [
        player_prop_row(MARKET_KEY_SHOTS, 1.8, "over", 0.5),
        player_prop_row(MARKET_KEY_SHOTS, 1.8, "under", 0.5),
        player_prop_row(MARKET_KEY_SOT, 0.6, "over", 0.5),
        player_prop_row(MARKET_KEY_SOT, 0.6, "under", 0.5),
    ]

    goal_summaries, player_summaries, diagnostics = simulate_match_summaries(
        match_id=7,
        score_rows=goal_rows,
        prop_rows=prop_rows,
        draws=256,
        rng=np.random.default_rng(21),
    )

    assert any(row["market_key"] == "exact_score" for row in goal_summaries)
    assert any(row["market_key"] == "total_goals" for row in goal_summaries)
    assert {row["market_key"] for row in player_summaries} == {
        MARKET_KEY_SHOTS,
        MARKET_KEY_SOT,
    }
    assert diagnostics["paired_player_inputs"] == 1
    assert diagnostics["sot_ratio_clipped_players"] == []


def test_cli_requires_source_run_ids():
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["simulate-history"])
    with pytest.raises(SystemExit):
        parser.parse_args(["simulate-match", "--match-id", "7"])


def test_cli_accepts_runtime_options_after_subcommand():
    args = build_parser().parse_args(
        [
            "simulate-history",
            "--probability-run-id",
            "12",
            "--player-prop-run-id",
            "34",
            "--draws",
            "10000",
            "--seed",
            "42",
        ]
    )

    assert args.draws == 10000
    assert args.seed == 42


def test_simulate_match_fails_when_goal_inputs_are_missing(monkeypatch):
    monkeypatch.setattr("match_simulation.load_exact_score_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr("match_simulation.load_player_prop_rows", lambda *args, **kwargs: [])

    with pytest.raises(SystemExit, match="No exact-score inputs"):
        run_simulation(
            db_url="unused",
            mode="match_simulation",
            probability_run_id=12,
            player_prop_run_id=34,
            draws=32,
            seed=99,
            match_id=7,
            write_db=False,
        )


def test_simulation_schema_contract():
    sql = Path("schemas/match_simulation.sql").read_text(encoding="utf-8")

    assert "model_outputs.match_simulation_runs" in sql
    assert "probability_run_id" in sql
    assert "player_prop_run_id" in sql
    assert "model_outputs.match_simulation_market_summaries" in sql
    assert "model_outputs.player_simulation_market_summaries" in sql
