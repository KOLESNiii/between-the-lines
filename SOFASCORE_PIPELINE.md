# Sofascore Premier League Stats Pipeline

This pipeline ingests Premier League team and player match stats from Sofascore into PostgreSQL. It covers seasons from `14/15` onward and uses Sofascore tournament ID `1`.

## Run

Start Postgres:

```bash
docker compose up -d db
```

Run a one-match smoke test:

```bash
python3 sofascore_ingestion.py --limit-events 1
```

Run the full backfill / incremental ingestion:

```bash
python3 sofascore_ingestion.py
```

The default database URL is:

```text
postgresql://user:pwd@localhost:5432/betting_historical_data
```

Override it with:

```bash
DB_URL="postgresql://user:pwd@localhost:5432/betting_historical_data" python3 sofascore_ingestion.py
```

## What Gets Stored

The script creates the `raw` schema and these Sofascore tables if they do not exist:

- `raw.sofascore_teams`
- `raw.sofascore_players`
- `raw.sofascore_matches`
- `raw.sofascore_match_stat_payloads`
- `raw.sofascore_player_match_appearances`
- `raw.sofascore_team_match_stats`
- `raw.sofascore_player_match_stats`
- `raw.sofascore_pipeline_state`
- `raw.team_name_aliases`

Team stats come from:

```text
/api/v1/event/{event_id}/statistics
```

Player stats come from:

```text
/api/v1/event/{event_id}/lineups
```

The long-format stat tables store query-friendly rows. The raw Sofascore payloads are also stored as `JSONB` so stat keys can be inspected later even if Sofascore changes its response shape.

`raw.sofascore_player_match_appearances` stores one row for every player listed in the lineup payload, including players from older matches where Sofascore does not provide per-player stat keys.

`raw.matches.home_team_id` and `raw.matches.away_team_id` reference `raw.sofascore_teams(id)`. The `raw.team_name_aliases` table maps historical CSV names such as `Man United` and `Nott'm Forest` to the canonical Sofascore team rows.

## Idempotency

The pipeline is safe to rerun.

- Teams upsert by `sofascore_team_id`.
- Players upsert by `sofascore_player_id`.
- Matches upsert by `sofascore_event_id`.
- Team stat rows upsert by `match_id`, `team_id`, `period`, `group_name`, `stat_key`.
- Player appearance rows upsert by `match_id`, `player_id`, `team_id`.
- Player stat rows upsert by `match_id`, `player_id`, `team_id`, `stat_key`.

The checkpoint lives in `raw.sofascore_pipeline_state` under pipeline name `sofascore_pl_stats`. After the first successful backfill, later runs only ingest finished events with a `startTimestamp` greater than the stored checkpoint.

## Data-Discovery Tasks

Use these checks to understand what Sofascore returns by season.

1. Confirm season IDs:

```bash
python3 - <<'PY'
from sofascore_ingestion import get_pl_seasons
for season in get_pl_seasons():
    print(season["id"], season["year"], season.get("name"))
PY
```

Confirm `14/15` is `8186` and note the current latest season ID.

2. Count events by season:

```bash
python3 - <<'PY'
from sofascore_ingestion import get_finished_events, get_pl_seasons, request_json
for season in get_pl_seasons():
    payload = request_json(f"/tournament/1/season/{season['id']}/events")
    total = len(payload.get("events", []))
    finished = len(get_finished_events(season["id"]))
    print(season["year"], season["id"], "total=", total, "finished=", finished)
PY
```

Completed seasons should be around `380` finished matches.

3. Inspect team stat keys:

```bash
python3 - <<'PY'
from sofascore_ingestion import request_json
event_id = 12436870
payload = request_json(f"/event/{event_id}/statistics")
for period in payload.get("statistics", []):
    print(period.get("period"))
    for group in period.get("groups", []):
        keys = [item.get("key") for item in group.get("statisticsItems", [])]
        print(" ", group.get("groupName"), keys)
PY
```

Repeat with one old, one middle, and one current-season match. Check whether older seasons are missing newer stats such as `expectedGoals`.

4. Inspect player stat keys:

```bash
python3 - <<'PY'
from sofascore_ingestion import request_json
event_id = 12436870
payload = request_json(f"/event/{event_id}/lineups")
for side in ("home", "away"):
    print(side)
    for entry in payload.get(side, {}).get("players", [])[:3]:
        player = entry["player"]
        print(player["id"], player["name"], sorted((entry.get("statistics") or {}).keys()))
PY
```

Check whether substitutes and unused bench players have `statistics`.

## Useful SQL Checks

Confirm no pre-`14/15` matches were ingested:

```sql
SELECT min(season_year), min(start_datetime)
FROM raw.sofascore_matches;
```

Count matches by season:

```sql
SELECT season_year, count(*)
FROM raw.sofascore_matches
GROUP BY season_year
ORDER BY season_year;
```

Find common team stat keys:

```sql
SELECT stat_key, count(*)
FROM raw.sofascore_team_match_stats
GROUP BY stat_key
ORDER BY count(*) DESC;
```

Find common player stat keys:

```sql
SELECT stat_key, count(*)
FROM raw.sofascore_player_match_stats
GROUP BY stat_key
ORDER BY count(*) DESC;
```

Confirm FK-backed player/team stats exist:

```sql
SELECT count(*) FROM raw.sofascore_team_match_stats;
SELECT count(*) FROM raw.sofascore_player_match_appearances;
SELECT count(*) FROM raw.sofascore_player_match_stats;
```
