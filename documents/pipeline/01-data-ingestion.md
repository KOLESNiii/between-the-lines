# Stage 1: Data Ingestion

## Purpose

Ingest Premier League match, team, player, lineup, and stat payloads from Sofascore into PostgreSQL. Raw bookmaker odds are handled separately through `odds_api`.

## Inputs

- Sofascore tournament and season endpoints
- Sofascore event statistics
- Sofascore event lineups
- Existing team alias mappings for historical names

## Outputs

The ingestion layer writes long-format raw tables in the `raw` schema:

- `raw.sofascore_teams`
- `raw.sofascore_players`
- `raw.sofascore_matches`
- `raw.sofascore_match_stat_payloads`
- `raw.sofascore_player_match_appearances`
- `raw.sofascore_team_match_stats`
- `raw.sofascore_player_match_stats`
- `raw.sofascore_pipeline_state`
- `raw.team_name_aliases`

## Commands

Start Postgres:

```bash
docker compose up -d db
```

Run a one-match smoke test:

```bash
python3 sofascore_ingestion.py --limit-events 1
```

Run the full backfill or incremental ingestion:

```bash
python3 sofascore_ingestion.py
```

## Operational Notes

- The pipeline is safe to rerun.
- The checkpoint lives in `raw.sofascore_pipeline_state` under `sofascore_pl_stats`.
- After the first successful backfill, later runs ingest finished events newer than the stored checkpoint.
- Raw payloads are stored as `JSONB` so stat keys can be inspected later if Sofascore changes response shape.
