CREATE SCHEMA IF NOT EXISTS model_outputs;

CREATE TABLE IF NOT EXISTS model_outputs.match_simulation_runs (
    id BIGSERIAL PRIMARY KEY,
    run_name TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    probability_run_id BIGINT NOT NULL REFERENCES model_outputs.market_probability_runs(id) ON DELETE CASCADE,
    player_prop_run_id BIGINT NOT NULL REFERENCES model_outputs.player_prop_runs(id) ON DELETE CASCADE,
    draws INTEGER NOT NULL CHECK (draws > 0),
    seed BIGINT NOT NULL CHECK (seed >= 0),
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS model_outputs.match_simulation_market_summaries (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES model_outputs.match_simulation_runs(id) ON DELETE CASCADE,
    match_id BIGINT NOT NULL,
    market_key TEXT NOT NULL,
    selection TEXT NOT NULL,
    line NUMERIC,
    simulated_probability NUMERIC NOT NULL CHECK (simulated_probability >= 0 AND simulated_probability <= 1),
    simulated_count INTEGER NOT NULL CHECK (simulated_count >= 0),
    draws INTEGER NOT NULL CHECK (draws > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_outputs.player_simulation_market_summaries (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES model_outputs.match_simulation_runs(id) ON DELETE CASCADE,
    match_id BIGINT NOT NULL,
    team_id BIGINT NOT NULL,
    player_id BIGINT NOT NULL,
    player_name TEXT NOT NULL,
    player_position TEXT,
    market_key TEXT NOT NULL CHECK (market_key IN ('player_shots', 'player_shots_on_target')),
    selection TEXT NOT NULL CHECK (selection IN ('over', 'under')),
    line NUMERIC NOT NULL,
    simulated_probability NUMERIC NOT NULL CHECK (simulated_probability >= 0 AND simulated_probability <= 1),
    simulated_mean NUMERIC NOT NULL CHECK (simulated_mean >= 0),
    source_expected_value NUMERIC NOT NULL CHECK (source_expected_value >= 0),
    draws INTEGER NOT NULL CHECK (draws > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_match_simulation_runs_created
    ON model_outputs.match_simulation_runs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_match_simulation_goal_run_match
    ON model_outputs.match_simulation_market_summaries (run_id, match_id, market_key);

CREATE INDEX IF NOT EXISTS idx_player_simulation_run_match
    ON model_outputs.player_simulation_market_summaries (run_id, match_id, player_id, market_key);
