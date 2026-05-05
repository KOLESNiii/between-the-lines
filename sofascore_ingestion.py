import argparse
import datetime as dt
import logging
import os
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import psycopg
import requests
from psycopg.types.json import Jsonb


DB_URL = os.getenv(
    "DB_URL",
    "postgresql://user:pwd@localhost:5432/betting_historical_data",
)

BASE_URL = "https://api.sofascore.com/api/v1"
PREMIER_LEAGUE_TOURNAMENT_ID = 1
MIN_SEASON_YEAR = "14/15"
MIN_SEASON_ID = 8186
FINISHED_STATUS_CODE = 100
PIPELINE_NAME = "sofascore_pl_stats"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}


SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.sofascore_teams (
    id BIGSERIAL PRIMARY KEY,
    sofascore_team_id BIGINT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    slug TEXT,
    short_name TEXT,
    name_code TEXT,
    country_name TEXT,
    raw_team JSONB NOT NULL DEFAULT '{}'::jsonb,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.sofascore_players (
    id BIGSERIAL PRIMARY KEY,
    sofascore_player_id BIGINT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    short_name TEXT,
    slug TEXT,
    position TEXT,
    jersey_number TEXT,
    height INTEGER,
    gender TEXT,
    country_name TEXT,
    date_of_birth DATE,
    raw_player JSONB NOT NULL DEFAULT '{}'::jsonb,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.sofascore_matches (
    id BIGSERIAL PRIMARY KEY,
    sofascore_event_id BIGINT NOT NULL UNIQUE,
    tournament_id BIGINT NOT NULL,
    tournament_name TEXT,
    season_id BIGINT NOT NULL,
    season_year TEXT NOT NULL,
    start_timestamp BIGINT NOT NULL,
    start_datetime TIMESTAMPTZ NOT NULL,
    status_code INTEGER,
    status_description TEXT,
    home_team_id BIGINT NOT NULL REFERENCES raw.sofascore_teams(id),
    away_team_id BIGINT NOT NULL REFERENCES raw.sofascore_teams(id),
    home_score INTEGER,
    away_score INTEGER,
    raw_event JSONB NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.sofascore_match_stat_payloads (
    match_id BIGINT PRIMARY KEY REFERENCES raw.sofascore_matches(id) ON DELETE CASCADE,
    team_statistics_payload JSONB,
    lineups_payload JSONB,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.sofascore_player_match_appearances (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES raw.sofascore_matches(id) ON DELETE CASCADE,
    team_id BIGINT NOT NULL REFERENCES raw.sofascore_teams(id),
    player_id BIGINT NOT NULL REFERENCES raw.sofascore_players(id),
    side TEXT NOT NULL CHECK (side IN ('home', 'away')),
    position TEXT,
    shirt_number INTEGER,
    jersey_number TEXT,
    substitute BOOLEAN,
    has_statistics BOOLEAN NOT NULL DEFAULT false,
    raw_player_match JSONB NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (match_id, player_id, team_id)
);

CREATE TABLE IF NOT EXISTS raw.sofascore_team_match_stats (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES raw.sofascore_matches(id) ON DELETE CASCADE,
    team_id BIGINT NOT NULL REFERENCES raw.sofascore_teams(id),
    side TEXT NOT NULL CHECK (side IN ('home', 'away')),
    period TEXT NOT NULL,
    group_name TEXT NOT NULL,
    stat_key TEXT NOT NULL,
    stat_name TEXT,
    value_text TEXT,
    value_numeric NUMERIC,
    raw_item JSONB NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.sofascore_player_match_stats (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES raw.sofascore_matches(id) ON DELETE CASCADE,
    team_id BIGINT NOT NULL REFERENCES raw.sofascore_teams(id),
    player_id BIGINT NOT NULL REFERENCES raw.sofascore_players(id),
    side TEXT NOT NULL CHECK (side IN ('home', 'away')),
    position TEXT,
    shirt_number INTEGER,
    jersey_number TEXT,
    substitute BOOLEAN,
    stat_key TEXT NOT NULL,
    stat_name TEXT,
    value_text TEXT,
    value_numeric NUMERIC,
    raw_item JSONB NOT NULL,
    raw_player_match JSONB NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (match_id, player_id, team_id, stat_key)
);

CREATE TABLE IF NOT EXISTS raw.sofascore_pipeline_state (
    pipeline_name TEXT PRIMARY KEY,
    last_successful_event_start_timestamp BIGINT,
    last_successful_run_at TIMESTAMPTZ,
    last_processed_event_id BIGINT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_sofascore_matches_season
    ON raw.sofascore_matches (season_id, start_timestamp);

CREATE INDEX IF NOT EXISTS idx_sofascore_team_stats_lookup
    ON raw.sofascore_team_match_stats (team_id, stat_key, period);

ALTER TABLE raw.sofascore_team_match_stats
    DROP CONSTRAINT IF EXISTS sofascore_team_match_stats_match_id_team_id_period_stat_key_key;

CREATE UNIQUE INDEX IF NOT EXISTS idx_sofascore_team_match_stats_unique
    ON raw.sofascore_team_match_stats (match_id, team_id, period, group_name, stat_key);

CREATE INDEX IF NOT EXISTS idx_sofascore_player_stats_lookup
    ON raw.sofascore_player_match_stats (player_id, stat_key);

CREATE INDEX IF NOT EXISTS idx_sofascore_player_appearances_lookup
    ON raw.sofascore_player_match_appearances (player_id, match_id);
"""


def request_json(path: str) -> dict[str, Any]:
    url = f"{BASE_URL}{path}"
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def create_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()


def parse_season_start(year: str) -> int:
    start = int(year.split("/", 1)[0])
    if start >= 90:
        return 1900 + start
    return 2000 + start


def season_is_in_scope(season: dict[str, Any]) -> bool:
    year = season.get("year")
    if not year or "/" not in year:
        return False
    return parse_season_start(year) >= parse_season_start(MIN_SEASON_YEAR)


def get_pl_seasons() -> list[dict[str, Any]]:
    data = request_json(f"/tournament/{PREMIER_LEAGUE_TOURNAMENT_ID}/seasons")
    seasons = [season for season in data.get("seasons", []) if season_is_in_scope(season)]
    return sorted(seasons, key=lambda item: parse_season_start(item["year"]))


def get_finished_events(season_id: int) -> list[dict[str, Any]]:
    data = request_json(
        f"/tournament/{PREMIER_LEAGUE_TOURNAMENT_ID}/season/{season_id}/events"
    )
    events = data.get("events", [])
    return [
        event
        for event in events
        if event.get("status", {}).get("code") == FINISHED_STATUS_CODE
    ]


def get_pipeline_state(conn: psycopg.Connection) -> int | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT last_successful_event_start_timestamp
            FROM raw.sofascore_pipeline_state
            WHERE pipeline_name = %s
            """,
            (PIPELINE_NAME,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def timestamp_to_datetime(timestamp: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc)


def timestamp_to_date(timestamp: int | None) -> dt.date | None:
    if not timestamp:
        return None
    return timestamp_to_datetime(timestamp).date()


def as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().replace("%", "")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def value_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def upsert_team(cur: psycopg.Cursor, team: dict[str, Any]) -> int:
    country = team.get("country") or {}
    cur.execute(
        """
        INSERT INTO raw.sofascore_teams (
            sofascore_team_id, name, slug, short_name, name_code, country_name, raw_team
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (sofascore_team_id) DO UPDATE SET
            name = EXCLUDED.name,
            slug = EXCLUDED.slug,
            short_name = EXCLUDED.short_name,
            name_code = EXCLUDED.name_code,
            country_name = EXCLUDED.country_name,
            raw_team = EXCLUDED.raw_team,
            updated_at = now()
        RETURNING id
        """,
        (
            team["id"],
            team["name"],
            team.get("slug"),
            team.get("shortName"),
            team.get("nameCode"),
            country.get("name"),
            Jsonb(team),
        ),
    )
    return cur.fetchone()[0]


def upsert_player(cur: psycopg.Cursor, player: dict[str, Any]) -> int:
    country = player.get("country") or {}
    cur.execute(
        """
        INSERT INTO raw.sofascore_players (
            sofascore_player_id, name, first_name, last_name, short_name, slug,
            position, jersey_number, height, gender, country_name, date_of_birth, raw_player
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (sofascore_player_id) DO UPDATE SET
            name = EXCLUDED.name,
            first_name = EXCLUDED.first_name,
            last_name = EXCLUDED.last_name,
            short_name = EXCLUDED.short_name,
            slug = EXCLUDED.slug,
            position = EXCLUDED.position,
            jersey_number = EXCLUDED.jersey_number,
            height = EXCLUDED.height,
            gender = EXCLUDED.gender,
            country_name = EXCLUDED.country_name,
            date_of_birth = EXCLUDED.date_of_birth,
            raw_player = EXCLUDED.raw_player,
            updated_at = now()
        RETURNING id
        """,
        (
            player["id"],
            player["name"],
            player.get("firstName"),
            player.get("lastName"),
            player.get("shortName"),
            player.get("slug"),
            player.get("position"),
            player.get("jerseyNumber"),
            as_int(player.get("height")),
            player.get("gender"),
            country.get("name"),
            timestamp_to_date(player.get("dateOfBirthTimestamp")),
            Jsonb(player),
        ),
    )
    return cur.fetchone()[0]


def upsert_match(
    cur: psycopg.Cursor,
    event: dict[str, Any],
    season: dict[str, Any],
    home_team_id: int,
    away_team_id: int,
) -> int:
    tournament = event.get("tournament") or {}
    status = event.get("status") or {}
    home_score = event.get("homeScore") or {}
    away_score = event.get("awayScore") or {}
    start_timestamp = event["startTimestamp"]
    cur.execute(
        """
        INSERT INTO raw.sofascore_matches (
            sofascore_event_id, tournament_id, tournament_name, season_id,
            season_year, start_timestamp, start_datetime, status_code,
            status_description, home_team_id, away_team_id, home_score,
            away_score, raw_event
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (sofascore_event_id) DO UPDATE SET
            tournament_id = EXCLUDED.tournament_id,
            tournament_name = EXCLUDED.tournament_name,
            season_id = EXCLUDED.season_id,
            season_year = EXCLUDED.season_year,
            start_timestamp = EXCLUDED.start_timestamp,
            start_datetime = EXCLUDED.start_datetime,
            status_code = EXCLUDED.status_code,
            status_description = EXCLUDED.status_description,
            home_team_id = EXCLUDED.home_team_id,
            away_team_id = EXCLUDED.away_team_id,
            home_score = EXCLUDED.home_score,
            away_score = EXCLUDED.away_score,
            raw_event = EXCLUDED.raw_event,
            updated_at = now()
        RETURNING id
        """,
        (
            event["id"],
            tournament.get("id", PREMIER_LEAGUE_TOURNAMENT_ID),
            tournament.get("name"),
            season["id"],
            season["year"],
            start_timestamp,
            timestamp_to_datetime(start_timestamp),
            status.get("code"),
            status.get("description"),
            home_team_id,
            away_team_id,
            as_int(home_score.get("current")),
            as_int(away_score.get("current")),
            Jsonb(event),
        ),
    )
    return cur.fetchone()[0]


def upsert_payloads(
    cur: psycopg.Cursor,
    match_id: int,
    team_statistics: dict[str, Any],
    lineups: dict[str, Any],
) -> None:
    cur.execute(
        """
        INSERT INTO raw.sofascore_match_stat_payloads (
            match_id, team_statistics_payload, lineups_payload
        )
        VALUES (%s, %s, %s)
        ON CONFLICT (match_id) DO UPDATE SET
            team_statistics_payload = EXCLUDED.team_statistics_payload,
            lineups_payload = EXCLUDED.lineups_payload,
            updated_at = now()
        """,
        (match_id, Jsonb(team_statistics), Jsonb(lineups)),
    )


def upsert_team_stats(
    cur: psycopg.Cursor,
    match_id: int,
    home_team_id: int,
    away_team_id: int,
    team_statistics: dict[str, Any],
) -> int:
    inserted = 0
    for period in team_statistics.get("statistics", []):
        period_name = period.get("period") or "UNKNOWN"
        for group in period.get("groups", []):
            group_name = group.get("groupName") or "Unknown"
            for item in group.get("statisticsItems", []):
                stat_key = item.get("key") or item.get("name")
                if not stat_key:
                    continue
                for side, team_id, field in (
                    ("home", home_team_id, "home"),
                    ("away", away_team_id, "away"),
                ):
                    value = item.get(field)
                    numeric = item.get(f"{field}Value", value)
                    cur.execute(
                        """
                        INSERT INTO raw.sofascore_team_match_stats (
                            match_id, team_id, side, period, group_name, stat_key,
                            stat_name, value_text, value_numeric, raw_item
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (match_id, team_id, period, group_name, stat_key)
                        DO UPDATE SET
                            side = EXCLUDED.side,
                            group_name = EXCLUDED.group_name,
                            stat_name = EXCLUDED.stat_name,
                            value_text = EXCLUDED.value_text,
                            value_numeric = EXCLUDED.value_numeric,
                            raw_item = EXCLUDED.raw_item,
                            updated_at = now()
                        """,
                        (
                            match_id,
                            team_id,
                            side,
                            period_name,
                            group_name,
                            stat_key,
                            item.get("name"),
                            value_text(value),
                            as_decimal(numeric),
                            Jsonb(item),
                        ),
                    )
                    inserted += 1
    return inserted


def upsert_player_stats(
    cur: psycopg.Cursor,
    match_id: int,
    home_team_id: int,
    away_team_id: int,
    lineups: dict[str, Any],
) -> int:
    inserted = 0
    for side, team_id in (("home", home_team_id), ("away", away_team_id)):
        side_lineup = lineups.get(side) or {}
        for entry in side_lineup.get("players", []):
            player = entry.get("player") or {}
            if not player.get("id"):
                continue
            player_id = upsert_player(cur, player)
            stats = entry.get("statistics") or {}
            cur.execute(
                """
                INSERT INTO raw.sofascore_player_match_appearances (
                    match_id, team_id, player_id, side, position, shirt_number,
                    jersey_number, substitute, has_statistics, raw_player_match
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (match_id, player_id, team_id) DO UPDATE SET
                    side = EXCLUDED.side,
                    position = EXCLUDED.position,
                    shirt_number = EXCLUDED.shirt_number,
                    jersey_number = EXCLUDED.jersey_number,
                    substitute = EXCLUDED.substitute,
                    has_statistics = EXCLUDED.has_statistics,
                    raw_player_match = EXCLUDED.raw_player_match,
                    updated_at = now()
                """,
                (
                    match_id,
                    team_id,
                    player_id,
                    side,
                    entry.get("position"),
                    as_int(entry.get("shirtNumber")),
                    entry.get("jerseyNumber"),
                    entry.get("substitute"),
                    bool(stats),
                    Jsonb(entry),
                ),
            )
            for stat_key, value in stats.items():
                cur.execute(
                    """
                    INSERT INTO raw.sofascore_player_match_stats (
                        match_id, team_id, player_id, side, position, shirt_number,
                        jersey_number, substitute, stat_key, stat_name, value_text,
                        value_numeric, raw_item, raw_player_match
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (match_id, player_id, team_id, stat_key) DO UPDATE SET
                        side = EXCLUDED.side,
                        position = EXCLUDED.position,
                        shirt_number = EXCLUDED.shirt_number,
                        jersey_number = EXCLUDED.jersey_number,
                        substitute = EXCLUDED.substitute,
                        stat_name = EXCLUDED.stat_name,
                        value_text = EXCLUDED.value_text,
                        value_numeric = EXCLUDED.value_numeric,
                        raw_item = EXCLUDED.raw_item,
                        raw_player_match = EXCLUDED.raw_player_match,
                        updated_at = now()
                    """,
                    (
                        match_id,
                        team_id,
                        player_id,
                        side,
                        entry.get("position"),
                        as_int(entry.get("shirtNumber")),
                        entry.get("jerseyNumber"),
                        entry.get("substitute"),
                        stat_key,
                        stat_key,
                        value_text(value),
                        as_decimal(value),
                        Jsonb({stat_key: value}),
                        Jsonb(entry),
                    ),
                )
                inserted += 1
    return inserted


def update_pipeline_state(
    cur: psycopg.Cursor,
    event: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    cur.execute(
        """
        INSERT INTO raw.sofascore_pipeline_state (
            pipeline_name, last_successful_event_start_timestamp,
            last_successful_run_at, last_processed_event_id, metadata
        )
        VALUES (%s, %s, now(), %s, %s)
        ON CONFLICT (pipeline_name) DO UPDATE SET
            last_successful_event_start_timestamp =
                GREATEST(
                    raw.sofascore_pipeline_state.last_successful_event_start_timestamp,
                    EXCLUDED.last_successful_event_start_timestamp
                ),
            last_successful_run_at = now(),
            last_processed_event_id = EXCLUDED.last_processed_event_id,
            metadata = EXCLUDED.metadata
        """,
        (
            PIPELINE_NAME,
            event["startTimestamp"],
            event["id"],
            Jsonb(metadata),
        ),
    )


def ingest_event(
    conn: psycopg.Connection,
    season: dict[str, Any],
    event: dict[str, Any],
) -> tuple[int, int]:
    team_statistics = request_json(f"/event/{event['id']}/statistics")
    lineups = request_json(f"/event/{event['id']}/lineups")

    with conn.cursor() as cur:
        home_team_id = upsert_team(cur, event["homeTeam"])
        away_team_id = upsert_team(cur, event["awayTeam"])
        match_id = upsert_match(cur, event, season, home_team_id, away_team_id)
        upsert_payloads(cur, match_id, team_statistics, lineups)
        team_stat_count = upsert_team_stats(
            cur, match_id, home_team_id, away_team_id, team_statistics
        )
        player_stat_count = upsert_player_stats(
            cur, match_id, home_team_id, away_team_id, lineups
        )
        update_pipeline_state(
            cur,
            event,
            {
                "season_id": season["id"],
                "season_year": season["year"],
                "team_stat_rows_last_event": team_stat_count,
                "player_stat_rows_last_event": player_stat_count,
            },
        )
    conn.commit()
    return team_stat_count, player_stat_count


def run_pipeline(limit_events: int | None = None, sleep_seconds: float = 0.2) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.info(DB_URL)
    with psycopg.connect(DB_URL) as conn:
        create_schema(conn)
        last_timestamp = get_pipeline_state(conn)
        seasons = get_pl_seasons()
        logging.info(
            "Found %s PL seasons from %s onward. Last checkpoint: %s",
            len(seasons),
            MIN_SEASON_YEAR,
            last_timestamp,
        )

        processed = 0
        failed = 0
        for season in seasons:
            events = get_finished_events(season["id"])
            events = sorted(events, key=lambda item: item["startTimestamp"])
            if last_timestamp is not None:
                events = [
                    event
                    for event in events
                    if event["startTimestamp"] > last_timestamp
                ]
            logging.info(
                "Season %s (%s): %s finished events to ingest",
                season["year"],
                season["id"],
                len(events),
            )
            for event in events:
                if limit_events is not None and processed >= limit_events:
                    logging.info("Stopped after --limit-events=%s", limit_events)
                    return
                try:
                    team_rows, player_rows = ingest_event(conn, season, event)
                    processed += 1
                    logging.info(
                        "Ingested event %s: %s v %s (%s team stat rows, %s player stat rows)",
                        event["id"],
                        event["homeTeam"]["name"],
                        event["awayTeam"]["name"],
                        team_rows,
                        player_rows,
                    )
                except Exception:
                    conn.rollback()
                    failed += 1
                    logging.exception("Failed to ingest event %s", event.get("id"))
                time.sleep(sleep_seconds)
        logging.info("Done. Processed=%s failed=%s", processed, failed)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest Premier League team and player match stats from Sofascore."
    )
    parser.add_argument(
        "--limit-events",
        type=int,
        default=None,
        help="Process only this many events, useful for smoke tests.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.2,
        help="Pause between event ingestions to avoid hammering Sofascore.",
    )
    args = parser.parse_args()
    run_pipeline(limit_events=args.limit_events, sleep_seconds=args.sleep_seconds)


if __name__ == "__main__":
    main()
