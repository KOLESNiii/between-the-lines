# Stage 5: Odds and EV

## Purpose

Join model probabilities to bookmaker prices, calculate expected value, and track whether edges survive market movement.

This stage is post-model only. Bookmaker odds must not feed the XGBoost rate models, lambda construction, Dixon-Coles adjustment, or probability calibration.

## Odds API

Use the `odds_api` package as the application-facing interface. Raw Bet365 scripts are reference tooling and should not be used directly in application paths.

Example:

```python
from odds_api import OddsClient

client = OddsClient.from_env()
snapshot = client.get_live_odds(
    sport="soccer",
    providers=["pinnacle"],
)
```

## EV Pipeline

Implemented in `ev_pipeline.py`.

Create EV tables and fetch live odds:

```bash
./venv/bin/python ev_pipeline.py --create-schema fetch-live
```

Persist odds from a saved snapshot:

```bash
./venv/bin/python ev_pipeline.py from-json path/to/snapshot.json
```

Rebuild EV candidates for an existing odds snapshot:

```bash
./venv/bin/python ev_pipeline.py candidates --probability-run-id 123
```

The default EV threshold is `0.02`. Override it with `--ev-threshold`.

## EV Formula

```text
EV = (model_probability * decimal_odds) - 1
```

Example:

```text
0.55 * 2.10 - 1 = +0.155
```

## Betting Rule

Use a positive-EV threshold rather than betting every tiny edge. A typical starting threshold is 2-5%, then tighten it based on validation and closing-line value.

## Current Status

- Live odds fetching exists through `odds_api`.
- Team-market probabilities are written by `probabilistic_markets.py`.
- `ev_pipeline.py` persists normalized odds, maps them to model market rows, and writes EV candidates.

## EV Join Contract

The EV layer should join on:

- provider
- event identity / team mapping
- market key
- selection
- line

It should write:

- model probability
- bookmaker odds
- implied probability
- edge
- EV
- timestamp
- source probability run

## Supported Markets

V1 only joins markets that already exist in `model_outputs.market_probabilities`:

| Bookmaker market | Model market | Selections |
| --- | --- | --- |
| `moneyline` | `1x2` | `home`, `draw`, `away` |
| `total` | `total_goals` | `over`, `under` |

Unsupported markets are skipped before odds-price persistence. Spread, team total, player props, corners, and exact-score joins are intentionally out of scope for V1.

## Event Matching

Odds rows are matched to model matches by:

1. `model_outputs.bookmaker_event_mappings` using `(provider, provider_event_id)`.
2. Fallback normalized home/away names plus match date from `model_outputs.match_probability_inputs`.

Unmatched odds remain in `model_outputs.odds_prices` with `matched_match_id = NULL`; they are not written to `model_outputs.ev_candidates`.

## Database Tables

The EV stage uses these `model_outputs` tables:

- `odds_snapshots`: raw odds fetch metadata and payload.
- `odds_prices`: normalized market prices with optional matched match id.
- `bookmaker_event_mappings`: stable provider event to model match mapping.
- `ev_candidates`: filtered candidate bets with model probability, odds, implied probability, edge, EV, threshold, and source odds timestamp.

## Safety Notes

- Keep bookmaker probabilities out of the core football model.
- Use odds for validation, monitoring, EV calculation, and later reliability filtering.
- Track closing-line value so the model can be evaluated against market movement, not only final match outcomes.
- Treat live-odds EV candidates as monitoring output until a reliable pre-match odds source and closing-line tracking are in place.
