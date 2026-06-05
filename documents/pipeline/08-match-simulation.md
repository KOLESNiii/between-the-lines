# Stage 8: Match Simulation

## Purpose

Generate reproducible summary simulations from existing team score probabilities and current player shot prop means.

This stage is implemented in `match_simulation.py`. It persists summary frequencies only; raw draws are not stored.

## Inputs

V1 requires explicit source runs:

- `model_outputs.market_probabilities` exact-score rows from one `market_probability_runs` row
- `model_outputs.player_prop_probabilities` paired `player_shots` and `player_shots_on_target` expected values from one `player_prop_runs` row

Historical simulation uses the intersection of matches present in both source runs. One-match simulation fails if either goal or player prop inputs are missing.

## Draw Rules

Goal scores are sampled categorically from the persisted exact-score distribution. The distribution is normalized before sampling so small numeric drift does not change the contract.

Player shot props use the current allocation means:

```text
player_shots ~ Poisson(player_shots_expected_value)
p_sot = min(player_sot_expected_value / player_shots_expected_value, 1)
player_shots_on_target ~ Binomial(player_shots, p_sot)
```

If expected shots are zero, simulated shots and shots on target are zero. The conditional SOT draw keeps:

```text
player_shots_on_target <= player_shots
```

SOT ratio clipping and incomplete player prop pairs are recorded in run metadata.

## Outputs

Tables:

- `model_outputs.match_simulation_runs`
- `model_outputs.match_simulation_market_summaries`
- `model_outputs.player_simulation_market_summaries`

Goal summaries cover:

- `1x2`
- `btts`
- `total_goals`
- observed `exact_score` frequencies

Player summaries cover the existing allocation lines for:

- `player_shots`
- `player_shots_on_target`

Each player summary keeps the simulated probability, simulated mean count, and source expected value.

## Commands

Create tables and simulate overlapping historical matches:

```bash
./venv/bin/python match_simulation.py --create-schema simulate-history \
  --probability-run-id 123 \
  --player-prop-run-id 456 \
  --draws 10000 \
  --seed 42
```

Simulate one match:

```bash
./venv/bin/python match_simulation.py simulate-match \
  --match-id 4171 \
  --probability-run-id 123 \
  --player-prop-run-id 456 \
  --draws 10000 \
  --seed 42
```

If `--seed` is omitted, the stage generates and persists the actual seed used.

## Boundaries

- Simulation summaries do not replace calibrated market probabilities.
- Simulation outputs do not enter `ev_pipeline.py` yet.
- V1 does not persist raw draws or model learned cross-player or cross-market correlations.
- V1 player draws are limited to player shots and shots on target.
