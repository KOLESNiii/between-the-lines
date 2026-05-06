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

Build the player-derived team feature tables:

```bash
python3 team_feature_pipeline.py --create-schema --refresh
```

Use a different rolling window if needed:

```bash
python3 team_feature_pipeline.py --refresh --rolling-window 10
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

## Team Feature Tables

`team_feature_pipeline.py` creates the `features` schema and rebuilds two derived tables from player-level Sofascore stats:

- `features.sofascore_team_match_aggregates`
- `features.sofascore_team_match_features`

The aggregate table has one row per `(match_id, team_id)`. It excludes unused players by requiring `minutesPlayed > 0`, normalises volume stats to a full 11-player match baseline of `990` team minutes, and carries stat availability flags plus player counts for each engineered input.

The final feature table carries the aggregate columns forward and adds leak-free rolling form. Rolling features are season-scoped and use only previous matches with a SQL frame equivalent to:

```sql
ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
```

With the default `--rolling-window 5`, rolling feature values stay `NULL` until the team has five prior same-season matches with the required source feature available.

Engineered feature groups include attack (`xg`, `xa`, shots, key passes, big chances), defence (tackles, interceptions, blocks, aerials), control (passes, touches, possession proxy), transition (progressive carries, possession lost), and goalkeeping (saves, goals prevented).

Opponent-adjusted columns include:

- `adj_attack_xg`
- `adj_defence_xg`
- `adj_shot_volume`

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

Confirm feature row counts match two team rows per match:

```sql
SELECT
    (SELECT count(*) FROM features.sofascore_team_match_features) AS feature_rows,
    (SELECT 2 * count(*) FROM raw.sofascore_matches) AS expected_rows;
```

Confirm no duplicate team-match feature rows:

```sql
SELECT match_id, team_id, count(*)
FROM features.sofascore_team_match_features
GROUP BY match_id, team_id
HAVING count(*) > 1;
```

Check sparse xG/xA coverage by season:

```sql
SELECT
    season_year,
    count(*) AS rows,
    count(xg) AS xg_rows,
    count(xa) AS xa_rows,
    count(rolling_xg_for) AS rolling_xg_rows
FROM features.sofascore_team_match_features
GROUP BY season_year
ORDER BY season_year;
```

Inspect rolling leakage behavior for one team:

```sql
WITH ranked AS (
    SELECT
        team_name,
        season_year,
        match_date,
        history_match_count,
        rolling_shots_for,
        row_number() OVER (
            PARTITION BY team_id, season_year
            ORDER BY start_datetime, match_id
        ) AS team_match_no
    FROM features.sofascore_team_match_features
)
SELECT team_name, season_year, team_match_no, history_match_count, rolling_shots_for
FROM ranked
WHERE season_year = '24/25'
  AND team_name = 'Arsenal'
  AND team_match_no <= 7
ORDER BY team_match_no;
```
