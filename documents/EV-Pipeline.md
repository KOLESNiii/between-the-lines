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
       - corners_for_hat
    -> probabilistic team markets
       - 1X2
       - BTTS
       - total goals
       - exact score
    -> bookmaker odds comparison
    -> EV candidate generation
```

The implemented probability layer currently uses goal-rate outputs for team goal markets. Shots, SOT, and corners rate models produce upstream signals for future team count markets, corners markets, and player props.

## Player Props Extension

```text
raw player appearances and lineup context
    -> player minutes model
       - expected_minutes
       - starting_probability
       - sub_probability
    -> team shots/SOT rates plus player allocation
    -> player prop distributions
       - player_shots
       - player_shots_on_target
    -> player prop market probabilities
    -> bookmaker odds comparison once prop odds joins exist
```

The player minutes model feeds the implemented player prop allocation stage. Player prop probabilities are generated separately from EV candidate generation until bookmaker prop odds can be matched by player identity.

## Simulation Extension

```text
probabilistic team markets
    -> exact-score distribution
player prop allocation
    -> player shot/SOT expected values
    -> match simulation summaries
       - goal market frequencies
       - player shots over/under frequencies
       - player shots-on-target over/under frequencies
```

The simulation engine consumes persisted probability and player prop runs. It writes summary frequencies for downstream analysis and does not replace calibrated market probabilities or EV candidate generation.

## Stage Order

1. [Data ingestion](pipeline/01-data-ingestion.md)
2. [Team feature engineering](pipeline/02-team-feature-engineering.md)
3. [XGBoost rate models](pipeline/03-xgboost-rate-models.md)
   - [Corners rate model](pipeline/03a-corners-rate-model.md)
4. [Probabilistic markets](pipeline/04-probabilistic-markets.md)
5. [Odds and EV](pipeline/05-odds-and-ev.md)
   - [Odds normalisation](pipeline/05a-odds-normalisation.md)
   - [EV candidate generation](pipeline/05b-ev-candidate-generation.md)
6. [Player minutes model](pipeline/06-player-minutes-model.md)
7. [Player prop allocation](pipeline/07-player-prop-allocation.md)
8. [Match simulation](pipeline/08-match-simulation.md)

## Documentation Rules

- Keep this file as the high-level index.
- Put stage-specific details in `documents/pipeline/`.
- Document new model outputs in the stage where they are created and mention downstream use only where that integration exists.
- Keep planned extensions marked as planned until code, schemas, and validation artifacts exist.
