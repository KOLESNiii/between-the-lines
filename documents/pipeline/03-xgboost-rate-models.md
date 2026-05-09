# Stage 3: XGBoost Rate Models

## Purpose

Train independent regression models that convert leak-free team-match features into rate estimates. These rates feed probability distributions rather than direct betting probabilities.

## Implemented Models

| Model | Target | Prediction | Validation artifacts | Final artifacts |
| --- | --- | --- | --- | --- |
| `xg_for` | `target_xg_for` | `xg_hat_for` | `models/xgboost_xg_for/` | `models/xgboost_xg_for_final/` |
| `shots_for` | `target_shots_for` | `shots_for_hat` | `models/xgboost_shots_for/` | `models/xgboost_shots_for_final/` |
| `shots_against` | `target_shots_against` | `shots_against_hat` | `models/xgboost_shots_against/` | `models/xgboost_shots_against_final/` |
| `shot_quality` | `target_shot_quality` | `shot_quality_hat` | `models/xgboost_shot_quality/` | `models/xgboost_shot_quality_final/` |
| `fragility` | `target_fragility` | `fragility_hat` | `models/xgboost_fragility/` | `models/xgboost_fragility_final/` |

## Target Rules

- `xg_for` predicts `f.xg_actual`.
- `shots_for` predicts `f.shots_actual`.
- `shots_against` predicts `f.shots_against_actual`.
- `shot_quality` predicts clipped `xg_actual / shots_actual`, with the default low-shot filter.
- `fragility` predicts clipped `xg_against_actual / shots_against_actual`, with the default low-shot filter.

All models share the current feature set: rolling form, tempo, pressure, progression, crossing, possession, opponent, context, and lineup proxy features.

## Commands

Train validation models:

```bash
python3 xgboost_xg_model.py train
python3 xgboost_xg_model.py --model shots_for train
python3 xgboost_xg_model.py --model shots_against train
python3 xgboost_xg_model.py --model shot_quality train
python3 xgboost_xg_model.py --model fragility train
```

Run rolling-origin cross-validation:

```bash
python3 xgboost_xg_model.py cross-validate
python3 xgboost_xg_model.py --model shots_for cross-validate
python3 xgboost_xg_model.py --model shots_against cross-validate
python3 xgboost_xg_model.py --model shot_quality cross-validate
python3 xgboost_xg_model.py --model fragility cross-validate
```

Fit final all-labelled-data models:

```bash
python3 xgboost_xg_model.py train-final
python3 xgboost_xg_model.py --model shots_for train-final
python3 xgboost_xg_model.py --model shots_against train-final
python3 xgboost_xg_model.py --model shot_quality train-final
python3 xgboost_xg_model.py --model fragility train-final
```

Score labelled historical rows:

```bash
python3 xgboost_xg_model.py predict-history
python3 xgboost_xg_model.py --model shots_for predict-history
python3 xgboost_xg_model.py --model shots_against predict-history
python3 xgboost_xg_model.py --model shot_quality predict-history
python3 xgboost_xg_model.py --model fragility predict-history
```

Score both team rows for one match:

```bash
python3 xgboost_xg_model.py predict-match --match-id 123
python3 xgboost_xg_model.py --model shots_for predict-match --match-id 123
python3 xgboost_xg_model.py --model shots_against predict-match --match-id 123
python3 xgboost_xg_model.py --model shot_quality predict-match --match-id 123
python3 xgboost_xg_model.py --model fragility predict-match --match-id 123
```

## Evaluation

- Default split: train `22/23`, `23/24`, `24/25`; validate `25/26`.
- Cross-validation uses rolling-origin season folds.
- Metrics are RMSE and MAE against the direct target plus the matching rolling baseline.
- Shots predictions are clipped to `[0.0, 40.0]`.

## Downstream Contract

The probability layer currently consumes `xg_hat_for`, `shot_quality_hat`, and `fragility_hat` for team goal markets. The shots models are now available as upstream rates for future shots, SOT, corners, and player prop stages.
