# Stage 5: Odds and EV

## Purpose

Join model probabilities to bookmaker prices, calculate expected value, and track whether edges survive market movement.

## Odds API

Use the `odds_api` package as the application-facing interface. Raw Bet365 scripts are reference tooling and should not be used directly in application paths.

Example:

```python
from odds_api import OddsClient

client = OddsClient.from_env()
snapshot = client.get_live_odds(
    sport="soccer",
    providers=["pinnacle", "bet365"],
)
```

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
- The project does not yet have a production EV join that maps bookmaker selections to model market rows and persists bet candidates.

## Future EV Join Contract

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

## Safety Notes

- Keep bookmaker probabilities out of the core football model.
- Use odds for validation, monitoring, EV calculation, and later reliability filtering.
- Track closing-line value so the model can be evaluated against market movement, not only final match outcomes.
