CREATE SCHEMA IF NOT EXISTS features;
CREATE SCHEMA IF NOT EXISTS model_outputs;

CREATE TABLE IF NOT EXISTS features.player_prop_allocation_features (
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
    position_group TEXT NOT NULL DEFAULT 'unknown',
    target_player_shots NUMERIC,
    target_player_sot NUMERIC,
    target_minutes NUMERIC,
    is_home INTEGER NOT NULL,
    prior_player_match_count INTEGER NOT NULL DEFAULT 0,
    prior_team_match_count INTEGER NOT NULL DEFAULT 0,
    rolling_player_shot_share_5 NUMERIC,
    rolling_player_sot_share_5 NUMERIC,
    rolling_player_shots_per90_5 NUMERIC,
    rolling_player_sot_per90_5 NUMERIC,
    rolling_team_shots_5 NUMERIC,
    rolling_team_sot_5 NUMERIC,
    rolling_position_shot_share NUMERIC,
    rolling_position_sot_share NUMERIC,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, team_id, player_id)
);

CREATE TABLE IF NOT EXISTS model_outputs.player_prop_runs (
    id BIGSERIAL PRIMARY KEY,
    run_name TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    player_minutes_run_id BIGINT REFERENCES model_outputs.player_minutes_runs(id) ON DELETE SET NULL,
    source_model_dirs JSONB NOT NULL DEFAULT '{}'::jsonb,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS model_outputs.player_prop_probabilities (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES model_outputs.player_prop_runs(id) ON DELETE CASCADE,
    player_minutes_run_id BIGINT REFERENCES model_outputs.player_minutes_runs(id) ON DELETE SET NULL,
    match_id BIGINT NOT NULL,
    sofascore_event_id BIGINT,
    season_year TEXT NOT NULL,
    match_date DATE NOT NULL,
    team_id BIGINT NOT NULL,
    opponent_id BIGINT NOT NULL,
    player_id BIGINT NOT NULL,
    player_name TEXT NOT NULL,
    player_position TEXT,
    market_key TEXT NOT NULL,
    selection TEXT NOT NULL CHECK (selection IN ('over', 'under')),
    line NUMERIC NOT NULL,
    probability NUMERIC NOT NULL CHECK (probability >= 0 AND probability <= 1),
    expected_value NUMERIC NOT NULL CHECK (expected_value >= 0),
    team_shots_hat NUMERIC,
    team_sot_hat NUMERIC,
    player_shot_share NUMERIC,
    player_sot_share NUMERIC,
    expected_minutes NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, match_id, team_id, player_id, market_key, selection, line)
);

CREATE INDEX IF NOT EXISTS idx_player_prop_features_match
    ON features.player_prop_allocation_features (match_id, team_id);

CREATE INDEX IF NOT EXISTS idx_player_prop_features_player
    ON features.player_prop_allocation_features (player_id, start_datetime);

CREATE INDEX IF NOT EXISTS idx_player_prop_runs_created
    ON model_outputs.player_prop_runs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_player_prop_probabilities_match
    ON model_outputs.player_prop_probabilities (match_id, team_id, player_id);

CREATE INDEX IF NOT EXISTS idx_player_prop_probabilities_run_market
    ON model_outputs.player_prop_probabilities (run_id, market_key);
