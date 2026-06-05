from __future__ import annotations

import argparse
import json
import math
import os
import secrets
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from player_prop_allocation import MARKET_KEY_SHOTS, MARKET_KEY_SOT, PROP_LINES
from probabilistic_markets import DEFAULT_DB_URL, DEFAULT_TOTAL_LINES


DEFAULT_SCHEMA_PATH = Path("schemas/match_simulation.sql")
DEFAULT_DRAWS = 10000
PLAYER_PROP_MARKETS = (MARKET_KEY_SHOTS, MARKET_KEY_SOT)


class MissingSimulationInputError(ValueError):
    pass


@dataclass(frozen=True, order=True)
class ScoreOutcome:
    home_goals: int
    away_goals: int

    @property
    def selection(self) -> str:
        return f"{self.home_goals}-{self.away_goals}"


@dataclass(frozen=True)
class PlayerSimulationInput:
    match_id: int
    team_id: int
    player_id: int
    player_name: str
    player_position: str | None
    expected_shots: float
    expected_sot: float


@dataclass(frozen=True)
class PlayerSimulationDraws:
    player: PlayerSimulationInput
    shots: np.ndarray
    shots_on_target: np.ndarray
    sot_probability: float
    sot_ratio_clipped: bool


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


def create_schema(db_url: str, schema_path: Path = DEFAULT_SCHEMA_PATH) -> None:
    psycopg, _, _ = require_database_dependency()
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_path.read_text(encoding="utf-8"))
        conn.commit()


def row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def parse_exact_score(selection: Any) -> ScoreOutcome:
    parts = str(selection).split("-")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError(f"Invalid exact-score selection: {selection}")
    return ScoreOutcome(home_goals=int(parts[0]), away_goals=int(parts[1]))


def finite_nonnegative(value: Any, name: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite non-negative value") from exc
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError(f"{name} must be a finite non-negative value")
    return numeric


def normalize_exact_score_rows(
    rows: Iterable[Any],
) -> list[tuple[ScoreOutcome, float]]:
    probability_by_score: dict[ScoreOutcome, float] = defaultdict(float)
    for row in rows:
        market_key = row_value(row, "market_key")
        if market_key not in (None, "exact_score"):
            continue
        score = parse_exact_score(row_value(row, "selection"))
        probability = finite_nonnegative(
            row_value(row, "probability"),
            f"exact-score probability for {score.selection}",
        )
        probability_by_score[score] += probability

    total_probability = sum(probability_by_score.values())
    if not probability_by_score:
        raise MissingSimulationInputError("No exact-score probabilities found for match")
    if total_probability <= 0:
        raise ValueError("Exact-score probabilities must have a positive total")

    return [
        (score, probability_by_score[score] / total_probability)
        for score in sorted(probability_by_score)
    ]


def sample_scorelines(
    score_rows: Iterable[Any],
    draws: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    if draws <= 0:
        raise ValueError("draws must be positive")
    distribution = normalize_exact_score_rows(score_rows)
    outcomes = [score for score, _ in distribution]
    probabilities = np.array([probability for _, probability in distribution], dtype=float)
    outcome_indices = rng.choice(len(outcomes), size=draws, p=probabilities)
    home_goals = np.array(
        [outcomes[index].home_goals for index in outcome_indices],
        dtype=int,
    )
    away_goals = np.array(
        [outcomes[index].away_goals for index in outcome_indices],
        dtype=int,
    )
    return home_goals, away_goals


def summary_row(
    match_id: int,
    market_key: str,
    selection: str,
    line: float | None,
    count: int,
    draws: int,
) -> dict[str, Any]:
    return {
        "match_id": match_id,
        "market_key": market_key,
        "selection": selection,
        "line": line,
        "simulated_probability": count / draws,
        "simulated_count": count,
        "draws": draws,
    }


def summarize_goal_draws(
    match_id: int,
    home_goals: np.ndarray,
    away_goals: np.ndarray,
    total_lines: tuple[float, ...] = DEFAULT_TOTAL_LINES,
) -> list[dict[str, Any]]:
    if len(home_goals) == 0 or len(home_goals) != len(away_goals):
        raise ValueError("Goal draws must contain paired non-empty home and away arrays")
    draws = len(home_goals)
    rows = [
        summary_row(match_id, "1x2", "home", None, int(np.sum(home_goals > away_goals)), draws),
        summary_row(match_id, "1x2", "draw", None, int(np.sum(home_goals == away_goals)), draws),
        summary_row(match_id, "1x2", "away", None, int(np.sum(home_goals < away_goals)), draws),
    ]

    btts_yes = int(np.sum((home_goals > 0) & (away_goals > 0)))
    rows.extend(
        [
            summary_row(match_id, "btts", "yes", None, btts_yes, draws),
            summary_row(match_id, "btts", "no", None, draws - btts_yes, draws),
        ]
    )

    total_goals = home_goals + away_goals
    for line in total_lines:
        over = int(np.sum(total_goals > line))
        rows.extend(
            [
                summary_row(match_id, "total_goals", "over", line, over, draws),
                summary_row(match_id, "total_goals", "under", line, draws - over, draws),
            ]
        )

    score_counts = Counter(zip(home_goals.tolist(), away_goals.tolist()))
    for (home, away), count in sorted(score_counts.items()):
        rows.append(summary_row(match_id, "exact_score", f"{home}-{away}", None, count, draws))
    return rows


def int_field(row: Any, key: str) -> int:
    value = row_value(row, key)
    if value is None:
        raise ValueError(f"{key} is required for player simulation input")
    return int(value)


def text_field(row: Any, key: str, default: str = "") -> str:
    value = row_value(row, key)
    return default if value is None else str(value)


def collapse_player_prop_rows(
    rows: Iterable[Any],
) -> tuple[list[PlayerSimulationInput], dict[str, Any]]:
    values_by_player: dict[tuple[int, int, int], dict[str, Any]] = {}
    seen_market_rows = 0
    ignored_market_rows = 0

    for row in rows:
        market_key = row_value(row, "market_key")
        if market_key not in PLAYER_PROP_MARKETS:
            ignored_market_rows += 1
            continue
        seen_market_rows += 1
        identity = (
            int_field(row, "match_id"),
            int_field(row, "team_id"),
            int_field(row, "player_id"),
        )
        player = values_by_player.setdefault(
            identity,
            {
                "match_id": identity[0],
                "team_id": identity[1],
                "player_id": identity[2],
                "player_name": text_field(row, "player_name", default=""),
                "player_position": row_value(row, "player_position"),
                "means": {},
            },
        )
        mean = finite_nonnegative(
            row_value(row, "expected_value"),
            f"{market_key} expected_value for player {identity[2]}",
        )
        previous = player["means"].get(market_key)
        if previous is not None and not math.isclose(previous, mean, abs_tol=1e-12):
            raise ValueError(
                "Conflicting expected_value rows for "
                f"match={identity[0]} team={identity[1]} player={identity[2]} "
                f"market={market_key}"
            )
        player["means"][market_key] = mean

    inputs: list[PlayerSimulationInput] = []
    incomplete_players: list[dict[str, Any]] = []
    for identity in sorted(values_by_player):
        player = values_by_player[identity]
        means = player["means"]
        missing_markets = [
            market_key for market_key in PLAYER_PROP_MARKETS if market_key not in means
        ]
        if missing_markets:
            incomplete_players.append(
                {
                    "match_id": player["match_id"],
                    "team_id": player["team_id"],
                    "player_id": player["player_id"],
                    "missing_markets": missing_markets,
                }
            )
            continue
        inputs.append(
            PlayerSimulationInput(
                match_id=player["match_id"],
                team_id=player["team_id"],
                player_id=player["player_id"],
                player_name=player["player_name"],
                player_position=player["player_position"],
                expected_shots=means[MARKET_KEY_SHOTS],
                expected_sot=means[MARKET_KEY_SOT],
            )
        )

    if not inputs:
        raise MissingSimulationInputError("No paired player shots and SOT inputs found")

    return inputs, {
        "player_input_rows": seen_market_rows,
        "paired_player_inputs": len(inputs),
        "incomplete_player_inputs": incomplete_players,
        "ignored_player_market_rows": ignored_market_rows,
    }


def sot_probability(player: PlayerSimulationInput) -> tuple[float, bool]:
    if player.expected_shots <= 0:
        return 0.0, player.expected_sot > 0
    raw_probability = player.expected_sot / player.expected_shots
    return min(raw_probability, 1.0), raw_probability > 1.0


def simulate_player_draws(
    players: Iterable[PlayerSimulationInput],
    draws: int,
    rng: np.random.Generator,
) -> tuple[list[PlayerSimulationDraws], list[dict[str, Any]]]:
    if draws <= 0:
        raise ValueError("draws must be positive")
    player_draws: list[PlayerSimulationDraws] = []
    clipped_players: list[dict[str, Any]] = []
    for player in players:
        shots = rng.poisson(player.expected_shots, size=draws)
        probability, clipped = sot_probability(player)
        shots_on_target = rng.binomial(shots, probability)
        if clipped:
            clipped_players.append(
                {
                    "match_id": player.match_id,
                    "team_id": player.team_id,
                    "player_id": player.player_id,
                    "expected_shots": player.expected_shots,
                    "expected_sot": player.expected_sot,
                    "used_sot_probability": probability,
                }
            )
        player_draws.append(
            PlayerSimulationDraws(
                player=player,
                shots=shots,
                shots_on_target=shots_on_target,
                sot_probability=probability,
                sot_ratio_clipped=clipped,
            )
        )
    return player_draws, clipped_players


def player_summary_rows(
    player_draws: Iterable[PlayerSimulationDraws],
    lines: tuple[float, ...] = PROP_LINES,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for player_draw in player_draws:
        player = player_draw.player
        for market_key, counts, source_expected_value in (
            (MARKET_KEY_SHOTS, player_draw.shots, player.expected_shots),
            (MARKET_KEY_SOT, player_draw.shots_on_target, player.expected_sot),
        ):
            draws = len(counts)
            simulated_mean = float(np.mean(counts))
            for line in lines:
                over = int(np.sum(counts > line))
                for selection, count in (("over", over), ("under", draws - over)):
                    rows.append(
                        {
                            "match_id": player.match_id,
                            "team_id": player.team_id,
                            "player_id": player.player_id,
                            "player_name": player.player_name,
                            "player_position": player.player_position,
                            "market_key": market_key,
                            "selection": selection,
                            "line": line,
                            "simulated_probability": count / draws,
                            "simulated_mean": simulated_mean,
                            "source_expected_value": source_expected_value,
                            "draws": draws,
                        }
                    )
    return rows


def simulate_match_summaries(
    match_id: int,
    score_rows: Iterable[Any],
    prop_rows: Iterable[Any],
    draws: int,
    rng: np.random.Generator,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    home_goals, away_goals = sample_scorelines(score_rows, draws, rng)
    players, player_diagnostics = collapse_player_prop_rows(prop_rows)
    player_draws, clipped_players = simulate_player_draws(players, draws, rng)
    diagnostics = {
        **player_diagnostics,
        "sot_ratio_clipped_players": clipped_players,
    }
    return (
        summarize_goal_draws(match_id, home_goals, away_goals),
        player_summary_rows(player_draws),
        diagnostics,
    )


def load_exact_score_rows(
    db_url: str,
    probability_run_id: int,
    match_id: int | None = None,
) -> list[dict[str, Any]]:
    psycopg, dict_row, _ = require_database_dependency()
    filters = ["run_id = %s", "market_key = 'exact_score'"]
    params: list[Any] = [probability_run_id]
    if match_id is not None:
        filters.append("match_id = %s")
        params.append(match_id)
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT match_id, market_key, selection, probability
                FROM model_outputs.market_probabilities
                WHERE {' AND '.join(filters)}
                ORDER BY match_id, selection
                """,
                params,
            )
            return list(cur.fetchall())


def load_player_prop_rows(
    db_url: str,
    player_prop_run_id: int,
    match_id: int | None = None,
) -> list[dict[str, Any]]:
    psycopg, dict_row, _ = require_database_dependency()
    filters = [
        "run_id = %s",
        "market_key IN ('player_shots', 'player_shots_on_target')",
    ]
    params: list[Any] = [player_prop_run_id]
    if match_id is not None:
        filters.append("match_id = %s")
        params.append(match_id)
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    match_id, team_id, player_id, player_name, player_position,
                    market_key, expected_value
                FROM model_outputs.player_prop_probabilities
                WHERE {' AND '.join(filters)}
                ORDER BY match_id, team_id, player_id, market_key, line, selection
                """,
                params,
            )
            return list(cur.fetchall())


def group_by_match(rows: Iterable[Any]) -> dict[int, list[Any]]:
    grouped: dict[int, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[int_field(row, "match_id")].append(row)
    return dict(grouped)


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def write_simulation_outputs(
    db_url: str,
    run_name: str,
    mode: str,
    probability_run_id: int,
    player_prop_run_id: int,
    draws: int,
    seed: int,
    metadata: dict[str, Any],
    goal_rows: list[dict[str, Any]],
    player_rows: list[dict[str, Any]],
) -> int:
    psycopg, _, Jsonb = require_database_dependency()
    parameters = {
        "goal_sampling": "categorical_exact_score",
        "player_shots_sampling": "poisson",
        "player_sot_sampling": "binomial_given_shots",
        "total_goal_lines": list(DEFAULT_TOTAL_LINES),
        "player_prop_lines": list(PROP_LINES),
    }
    metrics = metadata.get("metrics", {})
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_outputs.match_simulation_runs (
                    run_name, mode, probability_run_id, player_prop_run_id,
                    draws, seed, parameters, metrics, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_name) DO UPDATE SET
                    mode = EXCLUDED.mode,
                    created_at = now(),
                    probability_run_id = EXCLUDED.probability_run_id,
                    player_prop_run_id = EXCLUDED.player_prop_run_id,
                    draws = EXCLUDED.draws,
                    seed = EXCLUDED.seed,
                    parameters = EXCLUDED.parameters,
                    metrics = EXCLUDED.metrics,
                    metadata = EXCLUDED.metadata
                RETURNING id
                """,
                (
                    run_name,
                    mode,
                    probability_run_id,
                    player_prop_run_id,
                    draws,
                    seed,
                    Jsonb(parameters),
                    Jsonb(json_ready(metrics)),
                    Jsonb(json_ready(metadata)),
                ),
            )
            run_id = int(cur.fetchone()[0])
            cur.execute(
                "DELETE FROM model_outputs.match_simulation_market_summaries WHERE run_id = %s",
                (run_id,),
            )
            cur.execute(
                "DELETE FROM model_outputs.player_simulation_market_summaries WHERE run_id = %s",
                (run_id,),
            )
            cur.executemany(
                """
                INSERT INTO model_outputs.match_simulation_market_summaries (
                    run_id, match_id, market_key, selection, line,
                    simulated_probability, simulated_count, draws
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        run_id,
                        row["match_id"],
                        row["market_key"],
                        row["selection"],
                        row["line"],
                        row["simulated_probability"],
                        row["simulated_count"],
                        row["draws"],
                    )
                    for row in goal_rows
                ],
            )
            cur.executemany(
                """
                INSERT INTO model_outputs.player_simulation_market_summaries (
                    run_id, match_id, team_id, player_id, player_name,
                    player_position, market_key, selection, line,
                    simulated_probability, simulated_mean, source_expected_value,
                    draws
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        run_id,
                        row["match_id"],
                        row["team_id"],
                        row["player_id"],
                        row["player_name"],
                        row["player_position"],
                        row["market_key"],
                        row["selection"],
                        row["line"],
                        row["simulated_probability"],
                        row["simulated_mean"],
                        row["source_expected_value"],
                        row["draws"],
                    )
                    for row in player_rows
                ],
            )
        conn.commit()
    return run_id


def resolve_seed(seed: int | None) -> int:
    if seed is None:
        return secrets.randbits(63)
    if seed < 0:
        raise ValueError("seed must be non-negative")
    return int(seed)


def run_simulation(
    db_url: str,
    mode: str,
    probability_run_id: int,
    player_prop_run_id: int,
    draws: int,
    seed: int | None,
    match_id: int | None = None,
    run_name: str | None = None,
    write_db: bool = True,
) -> dict[str, Any]:
    if draws <= 0:
        raise ValueError("draws must be positive")
    if mode == "match_simulation" and match_id is None:
        raise SystemExit("simulate-match requires --match-id")

    resolved_seed = resolve_seed(seed)
    exact_score_rows = load_exact_score_rows(
        db_url,
        probability_run_id=probability_run_id,
        match_id=match_id,
    )
    player_prop_rows = load_player_prop_rows(
        db_url,
        player_prop_run_id=player_prop_run_id,
        match_id=match_id,
    )
    scores_by_match = group_by_match(exact_score_rows)
    props_by_match = group_by_match(player_prop_rows)
    score_match_ids = set(scores_by_match)
    prop_match_ids = set(props_by_match)

    if mode == "match_simulation":
        if match_id not in score_match_ids:
            raise SystemExit(
                f"No exact-score inputs found for probability run {probability_run_id} "
                f"and match {match_id}"
            )
        if match_id not in prop_match_ids:
            raise SystemExit(
                f"No player prop inputs found for player prop run {player_prop_run_id} "
                f"and match {match_id}"
            )
        target_match_ids = [match_id]
    else:
        target_match_ids = sorted(score_match_ids & prop_match_ids)
        if not target_match_ids:
            raise SystemExit(
                "No overlapping exact-score and player prop inputs found for the selected runs"
            )

    rng = np.random.default_rng(resolved_seed)
    goal_summary_rows: list[dict[str, Any]] = []
    player_summary_rows_out: list[dict[str, Any]] = []
    skipped_matches: list[dict[str, Any]] = []
    incomplete_player_inputs: list[dict[str, Any]] = []
    clipped_players: list[dict[str, Any]] = []

    for target_match_id in target_match_ids:
        try:
            goal_rows, player_rows, diagnostics = simulate_match_summaries(
                match_id=target_match_id,
                score_rows=scores_by_match[target_match_id],
                prop_rows=props_by_match[target_match_id],
                draws=draws,
                rng=rng,
            )
        except MissingSimulationInputError as exc:
            if mode == "match_simulation":
                raise SystemExit(str(exc)) from exc
            skipped_matches.append({"match_id": target_match_id, "reason": str(exc)})
            continue
        goal_summary_rows.extend(goal_rows)
        player_summary_rows_out.extend(player_rows)
        incomplete_player_inputs.extend(diagnostics["incomplete_player_inputs"])
        clipped_players.extend(diagnostics["sot_ratio_clipped_players"])

    if not goal_summary_rows or not player_summary_rows_out:
        raise SystemExit("Simulation produced no summary rows")

    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "coverage": {
            "exact_score_matches": len(score_match_ids),
            "player_prop_matches": len(prop_match_ids),
            "overlap_matches": len(score_match_ids & prop_match_ids),
            "score_only_matches": len(score_match_ids - prop_match_ids),
            "player_prop_only_matches": len(prop_match_ids - score_match_ids),
            "skipped_matches": skipped_matches,
            "incomplete_player_inputs": incomplete_player_inputs,
        },
        "sot_ratio_clipped_players": clipped_players,
        "metrics": {
            "simulated_matches": len({row["match_id"] for row in goal_summary_rows}),
            "goal_summary_rows": len(goal_summary_rows),
            "player_summary_rows": len(player_summary_rows_out),
            "sot_ratio_clipped_players": len(clipped_players),
            "incomplete_player_inputs": len(incomplete_player_inputs),
        },
    }

    db_run_id = None
    if write_db:
        default_run_name = (
            f"match_simulation_{mode}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        )
        db_run_id = write_simulation_outputs(
            db_url=db_url,
            run_name=run_name or default_run_name,
            mode=mode,
            probability_run_id=probability_run_id,
            player_prop_run_id=player_prop_run_id,
            draws=draws,
            seed=resolved_seed,
            metadata=metadata,
            goal_rows=goal_summary_rows,
            player_rows=player_summary_rows_out,
        )

    return {
        "seed": resolved_seed,
        "draws": draws,
        "probability_run_id": probability_run_id,
        "player_prop_run_id": player_prop_run_id,
        "coverage": metadata["coverage"],
        **metadata["metrics"],
        **({"db_run_id": db_run_id} if db_run_id is not None else {}),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Simulate match scores and player shot props from persisted model outputs."
    )
    parser.add_argument("--db-url", default=os.getenv("DB_URL", DEFAULT_DB_URL))
    parser.add_argument("--create-schema", action="store_true")
    parser.add_argument("--run-name")
    parser.add_argument("--draws", type=int, default=DEFAULT_DRAWS)
    parser.add_argument("--seed", type=int)
    subparsers = parser.add_subparsers(dest="command", required=True)

    history_parser = subparsers.add_parser(
        "simulate-history",
        help="Simulate overlapping matches from persisted probability and player prop runs.",
    )
    history_parser.add_argument("--probability-run-id", type=int, required=True)
    history_parser.add_argument("--player-prop-run-id", type=int, required=True)
    add_subcommand_runtime_options(history_parser)

    match_parser = subparsers.add_parser(
        "simulate-match",
        help="Simulate one match from persisted probability and player prop runs.",
    )
    match_parser.add_argument("--match-id", type=int, required=True)
    match_parser.add_argument("--probability-run-id", type=int, required=True)
    match_parser.add_argument("--player-prop-run-id", type=int, required=True)
    add_subcommand_runtime_options(match_parser)
    return parser


def add_subcommand_runtime_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-name", default=argparse.SUPPRESS)
    parser.add_argument("--draws", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--seed", type=int, default=argparse.SUPPRESS)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.create_schema:
        create_schema(args.db_url)

    mode = "history_simulation" if args.command == "simulate-history" else "match_simulation"
    result = run_simulation(
        db_url=args.db_url,
        mode=mode,
        probability_run_id=args.probability_run_id,
        player_prop_run_id=args.player_prop_run_id,
        draws=args.draws,
        seed=args.seed,
        match_id=getattr(args, "match_id", None),
        run_name=args.run_name,
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
