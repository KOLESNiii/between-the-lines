# Stage 4: Probabilistic Markets

## Purpose

Convert model rates into market probabilities. This layer should use distributions and calibration rather than asking ML models to predict betting probabilities directly.

## Current Team Goal Markets

Implemented in `probabilistic_markets.py`:

- 1X2
- BTTS
- total goals
- exact score

## Inputs

The current implementation scores these XGBoost models:

- `xg_for`
- `shot_quality`
- `fragility`

For each match, team rows are paired into home and away match inputs.

## Rate Construction

Goal rates are constructed from xG, opponent fragility, home/away multipliers, and tempo:

```text
lambda_home = tempo_multiplier * home_multiplier * xg_home * fragility_adjustment_away
lambda_away = tempo_multiplier * away_multiplier * xg_away * fragility_adjustment_home
```

The scoreline grid uses Poisson goal distributions plus Dixon-Coles low-score adjustment.

## Calibration

The layer fits:

- lambda parameters
- Dixon-Coles rho
- optional logistic market calibrators for 1X2, BTTS, and total goals

Validation only keeps market calibrators that improve held-out metrics.

## Commands

Create output tables and fit held-out calibration:

```bash
./venv/bin/python probabilistic_markets.py --create-schema fit-calibration
```

Fit final all-history calibration:

```bash
./venv/bin/python probabilistic_markets.py fit-final
```

Generate historical probability outputs:

```bash
./venv/bin/python probabilistic_markets.py predict-history
```

Score one match:

```bash
./venv/bin/python probabilistic_markets.py predict-match --match-id 4171
```

## Outputs

Artifacts:

- `models/probabilistic_markets/`
- `models/probabilistic_markets_final/`

Database tables:

- `model_outputs.market_probability_runs`
- `model_outputs.match_probability_inputs`
- `model_outputs.market_probabilities`

## Future Extension

Team count markets should consume `shots_for_hat` and `shots_against_hat` after distribution choice and validation are added. Do not make those models required by the current goal-market scorer until count-market probability outputs exist.

Player prop probabilities are generated in [player prop allocation](07-player-prop-allocation.md), not in this team market stage. Keep team goal markets and player prop probability outputs separate until a shared market abstraction is needed.
