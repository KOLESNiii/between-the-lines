CREATE SCHEMA IF NOT EXISTS features;
CREATE SCHEMA IF NOT EXISTS model_outputs;

CREATE TABLE IF NOT EXISTS features.player_minutes_features (
    match_id BIGINT NOT NULL,
    sofascore_event_id BIGINT NOT NULL,
    season_id BIGINT NOT NULL,
    season_year TEXT NOT NULL,
    start_timestamp BIGINT NOT NULL,
    start_datetime TIMESTAMPTZ NOT NULL,
    match_date DATE NOT NULL,
    team_id BIGINT NOT NULL,
    opponent_id BIGINT NOT NULL,
    team_name TEXT NOT NULL,
    opponent_name TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('home', 'away')),
    player_id BIGINT NOT NULL,
    sofascore_player_id BIGINT,
    player_name TEXT NOT NULL,
    player_position TEXT,
    shirt_number INTEGER,
    jersey_number TEXT,
    match_finished BOOLEAN NOT NULL DEFAULT false,
    target_minutes NUMERIC,
    target_started INTEGER,
    target_sub_appearance INTEGER,
    baseline_expected_minutes NUMERIC,
    baseline_starting_probability NUMERIC,
    baseline_sub_probability NUMERIC,
    is_home INTEGER NOT NULL,
    player_age_years NUMERIC,
    position_goalkeeper INTEGER NOT NULL DEFAULT 0,
    position_defender INTEGER NOT NULL DEFAULT 0,
    position_midfielder INTEGER NOT NULL DEFAULT 0,
    position_forward INTEGER NOT NULL DEFAULT 0,
    prior_player_match_count INTEGER NOT NULL DEFAULT 0,
    prior_team_match_count INTEGER NOT NULL DEFAULT 0,
    rolling_minutes_3 NUMERIC,
    rolling_minutes_5 NUMERIC,
    rolling_minutes_10 NUMERIC,
    rolling_start_rate_3 NUMERIC,
    rolling_start_rate_5 NUMERIC,
    rolling_start_rate_10 NUMERIC,
    rolling_sub_appearance_rate_5 NUMERIC,
    rolling_bench_rate_5 NUMERIC,
    days_since_last_appearance NUMERIC,
    days_since_last_start NUMERIC,
    season_minutes_before_match NUMERIC,
    season_starts_before_match INTEGER,
    season_sub_appearances_before_match INTEGER,
    matches_last_7_days INTEGER NOT NULL DEFAULT 0,
    matches_last_14_days INTEGER NOT NULL DEFAULT 0,
    feature_coverage_score NUMERIC NOT NULL DEFAULT 0,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, team_id, player_id)
);

CREATE TABLE IF NOT EXISTS model_outputs.player_minutes_runs (
    id BIGSERIAL PRIMARY KEY,
    run_name TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    train_seasons TEXT[],
    validation_season TEXT,
    source_model_dir TEXT,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS model_outputs.player_minutes_predictions (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES model_outputs.player_minutes_runs(id) ON DELETE CASCADE,
    match_id BIGINT NOT NULL,
    sofascore_event_id BIGINT,
    season_year TEXT NOT NULL,
    match_date DATE NOT NULL,
    team_id BIGINT NOT NULL,
    opponent_id BIGINT NOT NULL,
    player_id BIGINT NOT NULL,
    player_name TEXT NOT NULL,
    player_position TEXT,
    expected_minutes NUMERIC NOT NULL CHECK (expected_minutes >= 0),
    starting_probability NUMERIC NOT NULL CHECK (starting_probability >= 0 AND starting_probability <= 1),
    sub_probability NUMERIC NOT NULL CHECK (sub_probability >= 0 AND sub_probability <= 1),
    availability_status TEXT NOT NULL DEFAULT 'listed',
    target_minutes NUMERIC,
    target_started INTEGER,
    target_sub_appearance INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, match_id, team_id, player_id)
);

CREATE INDEX IF NOT EXISTS idx_player_minutes_features_match
    ON features.player_minutes_features (match_id, team_id);

CREATE INDEX IF NOT EXISTS idx_player_minutes_features_player
    ON features.player_minutes_features (player_id, start_datetime);

CREATE INDEX IF NOT EXISTS idx_player_minutes_runs_mode_created
    ON model_outputs.player_minutes_runs (mode, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_player_minutes_predictions_match
    ON model_outputs.player_minutes_predictions (match_id, team_id);

CREATE INDEX IF NOT EXISTS idx_player_minutes_predictions_run
    ON model_outputs.player_minutes_predictions (run_id);
