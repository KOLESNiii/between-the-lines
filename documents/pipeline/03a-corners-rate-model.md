# Stage 3a: Corners Rate Model

## Purpose

Train a dedicated team corners rate model. Corners are treated as a team count signal, not as a direct betting probability.

## Target

Implemented in `xgboost_xg_model.py` as:

| Model | Target | Prediction | Validation artifacts | Final artifacts |
| --- | --- | --- | --- | --- |
| `corners_for` | `target_corners_for` | `corners_for_hat` | `models/xgboost_corners_for/` | `models/xgboost_corners_for_final/` |

The target is `f.tempo_corners`. The baseline is the leak-free prior rolling average:

```text
rolling.rolling_tempo_corners_5
```

Predictions are clipped to `[0.0, 20.0]`.

## Features

The model uses the shared XGBoost feature set:

- rolling corners, shots, box pressure, box touches, and final-third entries
- crossing accuracy, shot box share, blocked-shot pressure, and progression signals
- opponent tempo, pressure, crossing, and shot context
- rest, fixture congestion, home/away, roster value, and lineup proxy features

Current match performance is not used as a feature.

## Commands

Train a validation model:

```bash
python3 xgboost_xg_model.py --model corners_for train
```

Run rolling-origin cross-validation:

```bash
python3 xgboost_xg_model.py --model corners_for cross-validate
```

Fit the final all-labelled-data model:

```bash
python3 xgboost_xg_model.py --model corners_for train-final
```

Score labelled historical rows:

```bash
python3 xgboost_xg_model.py --model corners_for predict-history
```

Score both team rows for one match:

```bash
python3 xgboost_xg_model.py --model corners_for predict-match --match-id 123
```

## Downstream Contract

`corners_for_hat` is a team corners rate. A match corners rate can be derived as:

```text
match_corners_hat = home corners_for_hat + away corners_for_hat
```

Corners betting probabilities, corners odds joins, and corners EV candidates are not implemented yet. Add a probability distribution and validation layer before connecting this rate to `ev_pipeline.py`.
