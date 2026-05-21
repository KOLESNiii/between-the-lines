# Stage 5b: EV Candidate Generation

## Purpose

Join normalized bookmaker odds to model probabilities and persist candidate bets above an EV threshold.

## Inputs

- `model_outputs.market_probability_runs`
- `model_outputs.match_probability_inputs`
- `model_outputs.market_probabilities`
- `model_outputs.odds_snapshots`
- `model_outputs.odds_prices`
- `model_outputs.bookmaker_event_mappings`

## Matching

The join uses explicit provider mappings first:

```text
(provider, provider_event_id) -> match_id
```

If no explicit mapping exists, it falls back to normalized home/away names plus match date from the selected probability run.

Unmatched prices stay in `odds_prices`; they do not create EV candidates.

## Candidate Formulae

```text
implied_probability = 1 / decimal_odds
edge = model_probability - implied_probability
EV = (model_probability * decimal_odds) - 1
```

Rows are written to `model_outputs.ev_candidates` only when:

```text
EV >= threshold
```

The default threshold is `0.02`.

## Commands

Generate candidates while fetching odds:

```bash
./venv/bin/python ev_pipeline.py fetch-live
```

Generate candidates from the latest odds snapshot and a specific probability run:

```bash
./venv/bin/python ev_pipeline.py candidates --probability-run-id 123
```

Use a stricter threshold:

```bash
./venv/bin/python ev_pipeline.py --ev-threshold 0.05 candidates --probability-run-id 123
```

## Scope

V1 covers `1x2` and `total_goals`. Player prop probabilities exist in the player prop allocation stage, but they are excluded from EV joins until odds normalisation supports prop lines and stable player identity matching. The `corners_for` rate model does not create corners EV candidates until corners probability distributions and odds joins are implemented. Meta bet filtering, staking, spread joins, corners EV, and closing-line value modelling remain future stages.
