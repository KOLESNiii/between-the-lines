# BetPredictor Dashboard

A zero-dependency local web dashboard for the BetPredictor EPL betting model.
It reads directly from the project's Postgres database and the on-disk model
artifacts, and embeds the `graphify` knowledge graph.

## Run

```bash
./dashboard/run.sh          # starts the DB (port 5433) if needed + serves on :8000
```

Then open <http://localhost:8000>.

The launcher ensures a `postgres:16` container named `betpredictor_db` is running
on host port **5433**, backed by the existing `betpredictor_pgdata` Docker volume.
(Port 5433 is used because 5432 is occupied by an unrelated project.)

Override defaults with env vars:

```bash
DB_URL=postgresql://user:pwd@localhost:5433/betting_historical_data \
PORT=8000 ./venv/bin/python dashboard/app.py
```

## Views

| View | What it shows |
|------|---------------|
| **Overview** | KPI counts, matches/goals per season, goal distribution, result split, recent runs |
| **Matches** | Searchable/filterable fixture list → click into a match |
| **Match detail** | Final score, 1X2 model-vs-sim, top scorelines, O/U & BTTS markets, team form, player props |
| **Teams / Team detail** | Career averages; rolling xG-for/against form, per-season splits |
| **Players** | Searchable player pool → jump to their prop lines |
| **Predictions** | Browse calibrated market probabilities (1X2 / BTTS / total goals) per run |
| **Value Finder** | Model↔simulation disagreements, strongest convictions, manual EV calculator |
| **Player Props** | Simulated shots & shots-on-target lines per player/match |
| **Sim & Runs** | Provenance + metrics for every probability and simulation run |
| **Model Registry** | Metadata, feature counts, validation metrics for each model on disk |
| **Knowledge Graph** | Embedded interactive `graphify` graph + node search + god nodes + report |

## Architecture

- `app.py` — stdlib `http.server` JSON API (no Flask/Streamlit needed) + static + graphify proxy.
- `static/index.html` — single-page app (vanilla JS, Chart.js via CDN), hash-routed views.
- Data source: `raw`, `features`, `model_outputs` schemas in Postgres; `models/` JSON; `graphify-out/`.
