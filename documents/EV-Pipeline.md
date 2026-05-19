# BetPredictor EV Pipeline

This is the high-level map for the project pipeline. Detailed implementation notes live in the smaller stage documents under `documents/pipeline/`.

## Current Pipeline Map

```text
Sofascore raw data
    -> team/player ingestion
    -> team-match feature engineering
    -> XGBoost rate models
       - xG_for_hat
       - shots_for_hat
       - shots_against_hat
       - shots_on_target_hat
       - shot_quality_hat
       - fragility_hat
    -> probabilistic team markets
       - 1X2
       - BTTS
       - total goals
       - exact score
    -> bookmaker odds comparison
    -> EV candidate generation
```

The implemented probability layer currently uses goal-rate outputs for team goal markets. The new shots models produce upstream rate signals for future team count markets, SOT, corners, and player props.

## Stage Order

1. [Data ingestion](pipeline/01-data-ingestion.md)
2. [Team feature engineering](pipeline/02-team-feature-engineering.md)
3. [XGBoost rate models](pipeline/03-xgboost-rate-models.md)
4. [Probabilistic markets](pipeline/04-probabilistic-markets.md)
5. [Odds and EV](pipeline/05-odds-and-ev.md)
   - [Odds normalisation](pipeline/05a-odds-normalisation.md)
   - [EV candidate generation](pipeline/05b-ev-candidate-generation.md)

## Command Summary

Refresh raw and feature data:

```bash
python3 sofascore_ingestion.py
python3 team_feature_pipeline.py --create-schema --refresh
```

Train validated rate models:

```bash
python3 xgboost_xg_model.py train
python3 xgboost_xg_model.py --model shots_for train
python3 xgboost_xg_model.py --model shots_against train
python3 xgboost_xg_model.py --model shots_on_target train
python3 xgboost_xg_model.py --model shot_quality train
python3 xgboost_xg_model.py --model fragility train
```

Fit final all-history rate models after validation:

```bash
python3 xgboost_xg_model.py train-final
python3 xgboost_xg_model.py --model shots_for train-final
python3 xgboost_xg_model.py --model shots_against train-final
python3 xgboost_xg_model.py --model shots_on_target train-final
python3 xgboost_xg_model.py --model shot_quality train-final
python3 xgboost_xg_model.py --model fragility train-final
```

Fit and score team market probabilities:

```bash
./venv/bin/python probabilistic_markets.py --create-schema fit-calibration
./venv/bin/python probabilistic_markets.py fit-final
./venv/bin/python probabilistic_markets.py predict-history
```

Fetch bookmaker odds through the application API:

```python
from odds_api import OddsClient

client = OddsClient.from_env()
snapshot = client.get_live_odds(sport="soccer", providers=["pinnacle"])
```

Inspect Bet365 pre-match web markets as structured JSON:

```bash
./venv/bin/python bet365_web_scraper.py --headed --json --test-mode
```

Persist odds and generate EV candidates:

```bash
./venv/bin/python ev_pipeline.py --create-schema fetch-live
./venv/bin/python ev_pipeline.py from-json path/to/snapshot.json
./venv/bin/python ev_pipeline.py candidates --probability-run-id 123
```

## Documentation Rules

- Keep this file as the high-level index.
- Put stage-specific details in `documents/pipeline/`.
- Document new model outputs in the stage where they are created and mention downstream use only where that integration exists.
