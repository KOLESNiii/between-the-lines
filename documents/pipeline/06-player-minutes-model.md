# Stage 6: Player Minutes Model

## Purpose

Estimate player availability before a match so future player prop models can scale team-level rates to realistic player-level opportunities.

This stage is implemented in `player_minutes_model.py`.

## Why This Stage Comes Next

`EV-Pipeline.md` already identifies shots and shots-on-target models as upstream signals for future player props. Those team rates are not enough on their own: player prop probabilities need expected pitch time before shot, SOT, goal, assist, pass, tackle, or card shares can be trusted.

## Outputs

The stage should produce one pre-match row per likely squad player:

| Output | Meaning |
| --- | --- |
| `expected_minutes` | Expected playing time, clipped to the competition range. |
| `starting_probability` | Calibrated probability the player starts. |
| `sub_probability` | Probability the player appears from the bench. |
| `availability_status` | Model-facing status such as available, doubtful, suspended, injured, or unknown. |

## Inputs

Use only information available before the match:

- `raw.sofascore_player_match_appearances`
- player and team ids from `raw.sofascore_players` and `raw.sofascore_teams`
- match dates and home/away context from `raw.sofascore_matches`
- lineup and formation fields already ingested from Sofascore
- prior-match player minutes, starts, bench appearances, and positions
- fixture congestion features such as days since last match
- optional future injury, suspension, and transfer feeds when available

## Feature Plan

Build leak-free rolling features with prior matches only:

- rolling minutes over 3, 5, and 10 appearances
- rolling start rate over 3, 5, and 10 team matches
- days since last appearance
- consecutive starts and consecutive bench appearances
- season minutes share within team and position group
- last-known position and position-group depth
- team formation and home/away flag
- fixture congestion and rest days

Do not use the current match lineup confirmation as a training feature for pre-match prediction unless the prediction is explicitly made after official lineups are released.

## Model Plan

Start with a transparent baseline before adding heavier models:

1. Baseline expected minutes from rolling player minutes and rolling start rate.
2. Starting classifier for `starting_probability`.
3. Minutes regressor for `expected_minutes`.
4. Optional bench-appearance classifier for `sub_probability`.
5. Probability calibration for start and sub probabilities.

The first production version should prefer stability over complexity. A calibrated logistic model or gradient-boosted tree classifier is acceptable if it beats the rolling baseline on held-out seasons.

## Validation

Use time-based validation by season or rolling-origin folds.

Track:

- minutes MAE
- starter Brier score
- starter log loss
- calibration curve by probability bucket
- top-11 accuracy by team
- comparison against a last-lineup or rolling-minutes baseline

The model should not be promoted to player props until it improves the baseline and has reasonable calibration for common starter-probability buckets.

## Persistence

- `features.player_minutes_features`
- `model_outputs.player_minutes_runs`
- `model_outputs.player_minutes_predictions`

Create tables and refresh the feature snapshot:

```bash
./venv/bin/python player_minutes_model.py --create-schema refresh-features
```

Train validation models:

```bash
./venv/bin/python player_minutes_model.py train
```

Train final all-history models:

```bash
./venv/bin/python player_minutes_model.py train-final
```

Score history or a single match:

```bash
./venv/bin/python player_minutes_model.py predict-history
./venv/bin/python player_minutes_model.py predict-match --match-id 123
```

## Downstream Contract

The [player prop allocation](07-player-prop-allocation.md) stage consumes:

```text
player_expected_shots = team_shots_hat * player_shot_share * minutes_factor
minutes_factor = expected_minutes / 90
```

Player prop probability outputs should remain out of `ev_pipeline.py` until odds normalisation supports prop selections, lines, and player identity matching.

## Documentation Refactor Plan

`documents/EV-Pipeline.md` should stay as the high-level pipeline index only:

- current implemented pipeline map
- planned extension map
- stage order
- command summary
- documentation rules

Detailed notes should live in smaller files under `documents/pipeline/`:

- existing stages `01` through `05b` cover ingestion, team features, rate models, probabilities, odds, and EV
- this file covers the player minutes model
- `07-player-prop-allocation.md` covers implemented player shots and shots-on-target prop allocation
- `08-match-simulation.md` covers summary simulations from team score probabilities and player shot props
- future team count or corners markets should get their own stage file instead of expanding the high-level index
- future uncertainty and bet-filter layers should each get separate stage files when selected from the roadmap
