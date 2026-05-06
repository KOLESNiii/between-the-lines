CREATE SCHEMA IF NOT EXISTS model_outputs;

CREATE TABLE IF NOT EXISTS model_outputs.market_probability_runs (
    id BIGSERIAL PRIMARY KEY,
    run_name TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    train_seasons TEXT[],
    validation_season TEXT,
    source_model_dirs JSONB NOT NULL DEFAULT '{}'::jsonb,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS model_outputs.match_probability_inputs (
    run_id BIGINT NOT NULL REFERENCES model_outputs.market_probability_runs(id) ON DELETE CASCADE,
    match_id BIGINT NOT NULL,
    sofascore_event_id BIGINT,
    season_year TEXT NOT NULL,
    match_date DATE NOT NULL,
    home_team_id BIGINT NOT NULL,
    away_team_id BIGINT NOT NULL,
    home_team_name TEXT NOT NULL,
    away_team_name TEXT NOT NULL,
    home_goals INTEGER,
    away_goals INTEGER,
    xg_home NUMERIC,
    xg_away NUMERIC,
    shot_quality_home NUMERIC,
    shot_quality_away NUMERIC,
    fragility_home NUMERIC,
    fragility_away NUMERIC,
    lambda_home NUMERIC NOT NULL,
    lambda_away NUMERIC NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, match_id)
);

CREATE TABLE IF NOT EXISTS model_outputs.market_probabilities (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES model_outputs.market_probability_runs(id) ON DELETE CASCADE,
    match_id BIGINT NOT NULL,
    market_key TEXT NOT NULL,
    selection TEXT NOT NULL,
    line NUMERIC,
    probability NUMERIC NOT NULL CHECK (probability >= 0 AND probability <= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_market_probability_runs_mode_created
    ON model_outputs.market_probability_runs (mode, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_match_probability_inputs_match
    ON model_outputs.match_probability_inputs (match_id);

CREATE INDEX IF NOT EXISTS idx_market_probabilities_match_market
    ON model_outputs.market_probabilities (match_id, market_key);

CREATE INDEX IF NOT EXISTS idx_market_probabilities_run_market
    ON model_outputs.market_probabilities (run_id, market_key);
