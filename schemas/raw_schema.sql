-- Raw database schema for the BetPredictor ingestion pipelines.
-- Source files:
--   - ingestion.py
--   - sofascore_ingestion.py

CREATE SCHEMA IF NOT EXISTS raw;

-- Historical football-data.co.uk match and odds data ingested by ingestion.py.
CREATE TABLE IF NOT EXISTS raw.matches (
    id BIGSERIAL PRIMARY KEY,
    div TEXT,
    match_date DATE,
    match_time TIME,
    hometeam TEXT,
    awayteam TEXT,
    home_team_id BIGINT,
    away_team_id BIGINT,
    fthg INTEGER,
    ftag INTEGER,
    ftr TEXT,
    hthg INTEGER,
    htag INTEGER,
    htr TEXT,
    referee TEXT,
    hshots INTEGER,
    ashots INTEGER,
    hshotst INTEGER,
    ashotst INTEGER,
    hfouls INTEGER,
    afoulds INTEGER,
    hcorners INTEGER,
    acorners INTEGER,
    hyellow INTEGER,
    ayellow INTEGER,
    hred INTEGER,
    ared INTEGER,
    b365h NUMERIC,
    b365d NUMERIC,
    b365a NUMERIC,
    bfdh NUMERIC,
    bfdd NUMERIC,
    bfda NUMERIC,
    bmgmh NUMERIC,
    bmgmd NUMERIC,
    bmgma NUMERIC,
    bvh NUMERIC,
    bvd NUMERIC,
    bva NUMERIC,
    bwh NUMERIC,
    bwd NUMERIC,
    bwa NUMERIC,
    clh NUMERIC,
    cld NUMERIC,
    cla NUMERIC,
    lbh NUMERIC,
    lbd NUMERIC,
    lba NUMERIC,
    psh NUMERIC,
    psd NUMERIC,
    psa NUMERIC,
    maxh NUMERIC,
    maxd NUMERIC,
    maxa NUMERIC,
    avgh NUMERIC,
    avgd NUMERIC,
    avga NUMERIC,
    bfeh NUMERIC,
    bfed NUMERIC,
    bfea NUMERIC,
    b365_over25 NUMERIC,
    b365_under25 NUMERIC,
    po_over25 NUMERIC,
    po_under25 NUMERIC,
    max_over25 NUMERIC,
    max_under25 NUMERIC,
    avg_over25 NUMERIC,
    avg_under25 NUMERIC,
    bfe_over25 NUMERIC,
    bfe_under25 NUMERIC,
    ah_line NUMERIC,
    b365_ahh NUMERIC,
    b365_aha NUMERIC,
    pahh NUMERIC,
    paha NUMERIC,
    max_ahh NUMERIC,
    max_aha NUMERIC,
    avg_ahh NUMERIC,
    avg_aha NUMERIC,
    bfe_ahh NUMERIC,
    bfe_aha NUMERIC,
    b365ch NUMERIC,
    b365cd NUMERIC,
    b365ca NUMERIC,
    bfdch NUMERIC,
    bfdcd NUMERIC,
    bfdca NUMERIC,
    bmgmch NUMERIC,
    bmgmcd NUMERIC,
    bmgmca NUMERIC,
    bvch NUMERIC,
    bvcd NUMERIC,
    bvca NUMERIC,
    bwch NUMERIC,
    bwcd NUMERIC,
    bwca NUMERIC,
    clch NUMERIC,
    clcd NUMERIC,
    clca NUMERIC,
    lbch NUMERIC,
    lbcd NUMERIC,
    lbca NUMERIC,
    psch NUMERIC,
    pscd NUMERIC,
    psca NUMERIC,
    maxch NUMERIC,
    maxcd NUMERIC,
    maxca NUMERIC,
    avgch NUMERIC,
    avgcd NUMERIC,
    avgca NUMERIC,
    bfech NUMERIC,
    bfecd NUMERIC,
    bfeca NUMERIC,
    b365c_over25 NUMERIC,
    b365c_under25 NUMERIC,
    pc_over25 NUMERIC,
    pc_under25 NUMERIC,
    maxc_over25 NUMERIC,
    maxc_under25 NUMERIC,
    avgc_over25 NUMERIC,
    avgc_under25 NUMERIC,
    bfec_over25 NUMERIC,
    bfec_under25 NUMERIC,
    ahc_line NUMERIC,
    b365c_ahh NUMERIC,
    b365c_aha NUMERIC,
    pca_hh NUMERIC,
    pca_ha NUMERIC,
    maxca_hh NUMERIC,
    maxca_ha NUMERIC,
    avgca_hh NUMERIC,
    avgca_ha NUMERIC,
    bfe_ca_hh NUMERIC,
    bfe_ca_ha NUMERIC
);

ALTER TABLE raw.matches
    ADD COLUMN IF NOT EXISTS home_team_id BIGINT,
    ADD COLUMN IF NOT EXISTS away_team_id BIGINT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_matches_unique_game
    ON raw.matches (match_date, hometeam, awayteam);

CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_matches_unique_game_team_ids
    ON raw.matches (match_date, home_team_id, away_team_id)
    WHERE match_date IS NOT NULL
      AND home_team_id IS NOT NULL
      AND away_team_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_raw_matches_date
    ON raw.matches (match_date);

CREATE INDEX IF NOT EXISTS idx_raw_matches_teams
    ON raw.matches (hometeam, awayteam);

CREATE INDEX IF NOT EXISTS idx_raw_matches_team_ids
    ON raw.matches (home_team_id, away_team_id);

-- Canonical Sofascore teams.
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

-- Stable mapping from external CSV team names to canonical Sofascore teams.
CREATE TABLE IF NOT EXISTS raw.team_name_aliases (
    source_team_name TEXT PRIMARY KEY,
    team_id BIGINT NOT NULL REFERENCES raw.sofascore_teams(id),
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'matches_home_team_id_fkey'
    ) THEN
        ALTER TABLE raw.matches
            ADD CONSTRAINT matches_home_team_id_fkey
            FOREIGN KEY (home_team_id) REFERENCES raw.sofascore_teams(id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'matches_away_team_id_fkey'
    ) THEN
        ALTER TABLE raw.matches
            ADD CONSTRAINT matches_away_team_id_fkey
            FOREIGN KEY (away_team_id) REFERENCES raw.sofascore_teams(id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'matches_named_home_team_id_required'
    ) THEN
        ALTER TABLE raw.matches
            ADD CONSTRAINT matches_named_home_team_id_required
            CHECK (hometeam IS NULL OR home_team_id IS NOT NULL);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'matches_named_away_team_id_required'
    ) THEN
        ALTER TABLE raw.matches
            ADD CONSTRAINT matches_named_away_team_id_required
            CHECK (awayteam IS NULL OR away_team_id IS NOT NULL);
    END IF;
END $$;

-- Canonical Sofascore players.
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

-- Sofascore event-level match metadata.
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

-- Full raw event stats payloads, retained for future key discovery.
CREATE TABLE IF NOT EXISTS raw.sofascore_match_stat_payloads (
    match_id BIGINT PRIMARY KEY REFERENCES raw.sofascore_matches(id) ON DELETE CASCADE,
    team_statistics_payload JSONB,
    lineups_payload JSONB,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per lineup player per match, even when no player stat keys are present.
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

-- Long-format team stats from /event/{event_id}/statistics.
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

-- Long-format player stats from /event/{event_id}/lineups.
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

-- High-water mark for incremental Sofascore ingestion.
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
