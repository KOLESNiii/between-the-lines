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
| **Upcoming & EV** | Scrapes bet365 for upcoming fixtures + odds, scores each with the **final models (all data)**, computes EV per selection. Empty → "No upcoming games." |
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

## Upcoming & EV pipeline (`dashboard/upcoming.py`)

Four stages, each reporting status; degrades gracefully:

1. **scrape** — runs `bet365_web_scraper.py --json [--api]` as a subprocess and parses its JSON.
2. **map** — maps each scraped team name to a `sofascore` `team_id` via `raw.team_name_aliases`.
3. **model** — scores the fixture with the **final** models (`models/*_final`) by inserting a
   temporary rolling-feature anchor (a synthetic unplayed match + two feature rows), scoring,
   then **deleting it in a `finally` block** — nothing is persisted.
4. **ev** — `EV = model_probability × decimal_odds − 1` for every priced 1X2 / BTTS / total-goals selection.

If bet365 returns no fixtures (e.g. off-season), the screen shows **"No upcoming games."**
`--api` mode needs valid `BET365_COOKIE`; `rendered` mode needs Playwright + a logged-in browser profile.

## Architecture

- `app.py` — stdlib `http.server` JSON API (no Flask/Streamlit needed) + static + graphify proxy.
- `static/index.html` — single-page app (vanilla JS, Chart.js via CDN), hash-routed views.
- Data source: `raw`, `features`, `model_outputs` schemas in Postgres; `models/` JSON; `graphify-out/`.
