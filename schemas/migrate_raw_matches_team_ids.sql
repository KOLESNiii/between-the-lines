-- One-time migration for existing databases where raw.matches already exists
-- with team names but no Sofascore team foreign keys.
--
-- Run from the repo root after raw.sofascore_teams has been populated:
--   psql "$DB_URL" -v ON_ERROR_STOP=1 -f schemas/migrate_raw_matches_team_ids.sql

BEGIN;

ALTER TABLE raw.matches
    ADD COLUMN IF NOT EXISTS home_team_id BIGINT,
    ADD COLUMN IF NOT EXISTS away_team_id BIGINT;

CREATE TABLE IF NOT EXISTS raw.team_name_aliases (
    source_team_name TEXT PRIMARY KEY,
    team_id BIGINT NOT NULL REFERENCES raw.sofascore_teams(id),
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;

\ir raw_team_aliases.sql

BEGIN;

UPDATE raw.matches m
SET home_team_id = a.team_id
FROM raw.team_name_aliases a
WHERE m.hometeam = a.source_team_name
  AND m.home_team_id IS DISTINCT FROM a.team_id;

UPDATE raw.matches m
SET away_team_id = a.team_id
FROM raw.team_name_aliases a
WHERE m.awayteam = a.source_team_name
  AND m.away_team_id IS DISTINCT FROM a.team_id;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM raw.matches
        WHERE hometeam IS NOT NULL
          AND home_team_id IS NULL
    ) THEN
        RAISE EXCEPTION 'Unmatched raw.matches home team names remain';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM raw.matches
        WHERE awayteam IS NOT NULL
          AND away_team_id IS NULL
    ) THEN
        RAISE EXCEPTION 'Unmatched raw.matches away team names remain';
    END IF;

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

CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_matches_unique_game_team_ids
    ON raw.matches (match_date, home_team_id, away_team_id)
    WHERE match_date IS NOT NULL
      AND home_team_id IS NOT NULL
      AND away_team_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_raw_matches_team_ids
    ON raw.matches (home_team_id, away_team_id);

COMMIT;
