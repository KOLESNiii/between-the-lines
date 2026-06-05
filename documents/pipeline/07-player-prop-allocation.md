# Stage 7: Player Prop Allocation

## Purpose

Allocate team shot and shots-on-target rate predictions to individual players using leak-free historical player shares and expected minutes.

This stage is implemented in `player_prop_allocation.py`.

## Inputs

- `features.player_prop_allocation_features`
- final `shots_for` model artifacts in `models/xgboost_shots_for_final/`
- final `shots_on_target` model artifacts in `models/xgboost_shots_on_target_final/`
- `model_outputs.player_minutes_predictions`

The feature refresh builds prior-only player history from raw Sofascore appearances and player match stats. Current-match shots and SOT are retained only as labels/reference columns, not allocation features.

## Allocation Contract

V1 writes only:

- `player_shots`
- `player_shots_on_target`

The allocation formula is:

```text
minutes_factor = expected_minutes / 90
player_expected_shots = shots_for_hat * player_shot_share * minutes_factor
player_expected_sot = shots_on_target_hat * player_sot_share * minutes_factor
```

Player shares prefer 5-match rolling player shares. If a player has sparse history, the stage falls back to prior team-position shares, then conservative position defaults.

## Probability Outputs

The stage uses a Poisson distribution for V1 and writes over/under probabilities for lines:

```text
0.5, 1.5, 2.5, 3.5
```

Tables:

- `features.player_prop_allocation_features`
- `model_outputs.player_prop_runs`
- `model_outputs.player_prop_probabilities`

Commands:

```bash
./venv/bin/python player_prop_allocation.py --create-schema refresh-features
./venv/bin/python player_prop_allocation.py predict-history
./venv/bin/python player_prop_allocation.py predict-match --match-id 123
```

Use `--player-minutes-run-id` to pin a specific minutes prediction run. If omitted, the latest player minutes run with persisted predictions is used.

## Validation Checks

- Verify player share features use only prior matches.
- Compare expected player shot/SOT means against historical outcomes by position and line.
- Check over/under calibration by probability bucket before using the probabilities for betting decisions.
- Revisit Negative Binomial distributions if observed player prop variance is materially higher than the Poisson mean.

## Downstream Boundary

Player prop probabilities do not enter `ev_pipeline.py` yet. EV joins should wait until odds normalisation supports prop market lines, selection names, and stable player identity matching.

The [match simulation](08-match-simulation.md) stage consumes the persisted `expected_value` means for paired `player_shots` and `player_shots_on_target` rows. Its V1 shot chain keeps simulated shots on target at or below simulated shots.
