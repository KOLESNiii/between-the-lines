# Stage 5a: Odds Normalisation

## Purpose

Convert provider-specific odds payloads into model-facing market rows that can be joined to `model_outputs.market_probabilities`.

## Source

Use `odds_api` as the only application-facing odds interface:

```bash
./venv/bin/python ev_pipeline.py fetch-live
```

Saved snapshots can be replayed without another provider request:

```bash
./venv/bin/python ev_pipeline.py from-json path/to/snapshot.json
```

## Normalised Markets

V1 supports whole-match team markets only:

| Provider market type | Normalised model key | Selection values | Line |
| --- | --- | --- | --- |
| `moneyline` | `1x2` | `home`, `draw`, `away` | `NULL` |
| `total` | `total_goals` | `over`, `under` | total goals line |

Prices with unsupported market types, non-whole-match periods, missing lines for totals, or invalid decimal odds are skipped before persistence.

## Persistence

`ev_pipeline.py` writes:

- one `model_outputs.odds_snapshots` row per fetch or replay
- one `model_outputs.odds_prices` row per normalized price

`odds_prices.matched_match_id` is nullable so unmatched provider events are retained for debugging and future mapping fixes.
