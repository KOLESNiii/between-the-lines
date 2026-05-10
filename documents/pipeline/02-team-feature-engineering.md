# Stage 2: Team Feature Engineering

## Purpose

Convert raw player and team match stats into leak-free team-match features suitable for modelling. The unit is one row per `(match_id, team_id)`, so each match has one home row and one away row.

## Pipeline

```text
raw player/team stats
    -> active-player filter
    -> team-match aggregation
    -> per-90 and ratio normalisation
    -> rolling form windows
    -> opponent feature joins
    -> model-ready feature rows
```

## Key Rules

- Exclude unused players with `minutesPlayed > 0`.
- Normalise player-derived volume to a full 11-player match baseline of `990` team minutes.
- Build rolling windows with prior matches only:

```sql
ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
```

- Do not use current match performance as a model feature.
- Keep opponent features pre-match by joining the opponent's prior rolling row for the same fixture.

## Outputs

`team_feature_pipeline.py` rebuilds:

- `features.sofascore_team_match_aggregates`
- `features.sofascore_team_match_features`

Feature groups include:

- attack: xG, xA, shots, key passes, big chances
- defence: tackles, interceptions, blocks, aerials
- control: passes, touches, possession proxy
- tempo: shots, box touches, final-third entries, corners, pass volume
- expanded performance: xGOT, shot value, pass value, progression, crossing
- lineup context: formation, starter value, missing and doubtful player value

## Commands

Create or migrate the schema and refresh features:

```bash
python3 team_feature_pipeline.py --create-schema --refresh
```

Use a different rolling window:

```bash
python3 team_feature_pipeline.py --refresh --rolling-window 10
```

## Downstream Contract

The XGBoost layer consumes the feature table through `xgboost_xg_model.py`. Current direct labels include:

- `xg_actual`
- `xg_against_actual`
- `shots_actual`
- `shots_against_actual`
- `shots_on_target`

The shots labels power the independent `shots_for`, `shots_against`, and `shots_on_target` rate models.
