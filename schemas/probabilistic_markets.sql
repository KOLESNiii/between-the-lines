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
    feature_coverage_score_home NUMERIC,
    feature_coverage_score_away NUMERIC,
    xg_feature_available_home BOOLEAN,
    xg_feature_available_away BOOLEAN,
    rolling_history_count_home INTEGER,
    rolling_history_count_away INTEGER,
    tempo_feature_coverage_score_home NUMERIC,
    tempo_feature_coverage_score_away NUMERIC,
    rolling_tempo_count_home INTEGER,
    rolling_tempo_count_away INTEGER,
    match_tempo_index NUMERIC,
    tempo_multiplier NUMERIC,
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

CREATE TABLE IF NOT EXISTS model_outputs.odds_snapshots (
    id BIGSERIAL PRIMARY KEY,
    fetched_at TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,
    raw JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_outputs.bookmaker_event_mappings (
    provider TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    match_id BIGINT NOT NULL,
    home_team_name TEXT,
    away_team_name TEXT,
    starts TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, provider_event_id)
);

CREATE TABLE IF NOT EXISTS model_outputs.odds_prices (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL REFERENCES model_outputs.odds_snapshots(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    provider_event_id TEXT,
    sport TEXT,
    league TEXT,
    home_team_name TEXT,
    away_team_name TEXT,
    starts TIMESTAMPTZ,
    odds_fetched_at TIMESTAMPTZ NOT NULL,
    market_type TEXT NOT NULL,
    market_key TEXT NOT NULL,
    selection TEXT NOT NULL,
    line NUMERIC,
    decimal_odds NUMERIC NOT NULL CHECK (decimal_odds > 1),
    matched_match_id BIGINT,
    raw JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_outputs.ev_candidates (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL REFERENCES model_outputs.odds_snapshots(id) ON DELETE CASCADE,
    odds_price_id BIGINT NOT NULL REFERENCES model_outputs.odds_prices(id) ON DELETE CASCADE,
    probability_run_id BIGINT NOT NULL REFERENCES model_outputs.market_probability_runs(id) ON DELETE CASCADE,
    match_id BIGINT NOT NULL,
    provider TEXT NOT NULL,
    provider_event_id TEXT,
    market_key TEXT NOT NULL,
    selection TEXT NOT NULL,
    line NUMERIC,
    model_probability NUMERIC NOT NULL CHECK (model_probability >= 0 AND model_probability <= 1),
    decimal_odds NUMERIC NOT NULL CHECK (decimal_odds > 1),
    implied_probability NUMERIC NOT NULL CHECK (implied_probability > 0 AND implied_probability < 1),
    edge NUMERIC NOT NULL,
    expected_value NUMERIC NOT NULL,
    threshold NUMERIC NOT NULL,
    source_odds_fetched_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (odds_price_id, probability_run_id)
);

ALTER TABLE model_outputs.match_probability_inputs
    ADD COLUMN IF NOT EXISTS feature_coverage_score_home NUMERIC,
    ADD COLUMN IF NOT EXISTS feature_coverage_score_away NUMERIC,
    ADD COLUMN IF NOT EXISTS xg_feature_available_home BOOLEAN,
    ADD COLUMN IF NOT EXISTS xg_feature_available_away BOOLEAN,
    ADD COLUMN IF NOT EXISTS rolling_history_count_home INTEGER,
    ADD COLUMN IF NOT EXISTS rolling_history_count_away INTEGER,
    ADD COLUMN IF NOT EXISTS tempo_feature_coverage_score_home NUMERIC,
    ADD COLUMN IF NOT EXISTS tempo_feature_coverage_score_away NUMERIC,
    ADD COLUMN IF NOT EXISTS rolling_tempo_count_home INTEGER,
    ADD COLUMN IF NOT EXISTS rolling_tempo_count_away INTEGER,
    ADD COLUMN IF NOT EXISTS match_tempo_index NUMERIC,
    ADD COLUMN IF NOT EXISTS tempo_multiplier NUMERIC;

CREATE INDEX IF NOT EXISTS idx_market_probability_runs_mode_created
    ON model_outputs.market_probability_runs (mode, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_match_probability_inputs_match
    ON model_outputs.match_probability_inputs (match_id);

CREATE INDEX IF NOT EXISTS idx_market_probabilities_match_market
    ON model_outputs.market_probabilities (match_id, market_key);

CREATE INDEX IF NOT EXISTS idx_market_probabilities_run_market
    ON model_outputs.market_probabilities (run_id, market_key);

CREATE INDEX IF NOT EXISTS idx_odds_snapshots_fetched
    ON model_outputs.odds_snapshots (fetched_at DESC);

CREATE INDEX IF NOT EXISTS idx_bookmaker_event_mappings_match
    ON model_outputs.bookmaker_event_mappings (match_id);

CREATE INDEX IF NOT EXISTS idx_odds_prices_snapshot_market
    ON model_outputs.odds_prices (snapshot_id, market_key, selection);

CREATE INDEX IF NOT EXISTS idx_odds_prices_matched_match
    ON model_outputs.odds_prices (matched_match_id)
    WHERE matched_match_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ev_candidates_run_value
    ON model_outputs.ev_candidates (probability_run_id, expected_value DESC);

CREATE INDEX IF NOT EXISTS idx_ev_candidates_snapshot
    ON model_outputs.ev_candidates (snapshot_id);
