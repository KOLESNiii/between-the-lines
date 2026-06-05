# Graph Report - BetPredictor  (2026-06-05)

## Corpus Check
- 52 files · ~228,779 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1093 nodes · 2868 edges · 49 communities (48 shown, 1 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 144 edges (avg confidence: 0.55)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `2058fb55`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]

## God Nodes (most connected - your core abstractions)
1. `str` - 59 edges
2. `Match` - 46 edges
3. `str` - 44 edges
4. `Any` - 39 edges
5. `PinnacleProvider` - 33 edges
6. `CalibrationParams` - 27 edges
7. `str` - 27 edges
8. `Bet365WebScraper` - 26 edges
9. `RateLimitSkipped` - 26 edges
10. `int` - 24 edges

## Surprising Connections (you probably didn't know these)
- `test_simulation_schema_contract()` --calls--> `Path`  [INFERRED]
  tests/test_match_simulation.py → match_simulation.py
- `test_simulate_match_fails_when_goal_inputs_are_missing()` --calls--> `run_simulation()`  [EXTRACTED]
  tests/test_match_simulation.py → match_simulation.py
- `test_cli_accepts_runtime_options_after_subcommand()` --calls--> `build_parser()`  [EXTRACTED]
  tests/test_match_simulation.py → match_simulation.py
- `test_cli_requires_source_run_ids()` --calls--> `build_parser()`  [EXTRACTED]
  tests/test_match_simulation.py → match_simulation.py
- `test_probability_artifact_paths_contract()` --calls--> `probability_artifact_paths()`  [EXTRACTED]
  tests/test_probabilistic_markets.py → probabilistic_markets.py

## Communities (49 total, 1 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.07
Nodes (68): Any, bool, float, int, str, Bet365RenderedPageScraper, Bet365WebScraper, clean_rendered_market_name() (+60 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (97): attr(), build_arg_parser(), calculate_ev(), create_schema(), decimal_or_none(), EVResult, explicit_mapping_key(), fetch_live_snapshot() (+89 more)

### Community 2 - "Community 2"
Cohesion: 0.11
Nodes (83): base_market_context(), baseline_params(), binary_brier(), binary_log_loss(), build_match_inputs(), build_probability_outputs(), calibrated_market_rows_for_match(), CalibrationParams (+75 more)

### Community 3 - "Community 3"
Cohesion: 0.09
Nodes (65): aggregate_fold_metrics(), artifact_paths(), baseline_expression(), best_iteration_count(), build_cross_validation_folds(), build_model_dataset_sql(), build_where_clause(), clip_predictions() (+57 more)

### Community 4 - "Community 4"
Cohesion: 0.12
Nodes (59): aggregate_fold_metrics(), artifact_paths(), best_iteration_count(), binary_metrics(), build_cross_validation_folds(), build_player_minutes_dataset_sql(), build_refresh_features_sql(), build_where_clause() (+51 more)

### Community 5 - "Community 5"
Cohesion: 0.13
Nodes (51): Any, ArgumentParser, add_subcommand_runtime_options(), build_parser(), collapse_player_prop_rows(), create_schema(), finite_nonnegative(), group_by_match() (+43 more)

### Community 7 - "Community 7"
Cohesion: 0.14
Nodes (41): build_allocations(), build_player_prop_features_sql(), build_probability_rows(), build_refresh_features_sql(), build_where_clause(), clip_share(), default_position_share(), execute_sql_file() (+33 more)

### Community 8 - "Community 8"
Cohesion: 0.05
Nodes (44): 🥇 1. Fix λ interaction model (BIGGEST LEVER), 🥈 2. Add calibration layer (CRITICAL), 🥉 3. Introduce market anchoring, 🧪 4. Fix “signal dilution”, code:python (shot_quality = xG_for / max(shots_for, 1)), code:python (shot_quality = np.clip(shot_quality, 0, 0.5)), code:python (fragility = xG_against / max(shots_against, 1)), code:python (# WRONG) (+36 more)

### Community 9 - "Community 9"
Cohesion: 0.21
Nodes (32): as_decimal(), as_int(), create_schema(), get_finished_events(), get_pipeline_state(), get_pl_seasons(), ingest_event(), main() (+24 more)

### Community 10 - "Community 10"
Cohesion: 0.06
Nodes (29): code:bash (docker compose up -d db), code:sql (ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), code:bash (python3 - <<'PY'), code:bash (python3 - <<'PY'), code:bash (python3 - <<'PY'), code:bash (python3 - <<'PY'), code:sql (SELECT min(season_year), min(start_datetime)), code:sql (SELECT season_year, count(*)) (+21 more)

### Community 11 - "Community 11"
Cohesion: 0.06
Nodes (30): Bet365 Test, Bet365 Web Scraper Reference, Browser Configuration, CLI Flags, code:bash (PINNACLE_API_KEY=...), code:text (#AC#B1#C1#D1002#G40#J99#I1#Q1#F^2002#), code:bash (./venv/bin/python -m pip install curl_cffi tls-client), code:bash (./venv/bin/python bet365_web_scraper.py --headed) (+22 more)

### Community 12 - "Community 12"
Cohesion: 0.18
Nodes (21): build_refresh_sql(), create_schema(), main(), read_schema_sql(), refresh_features(), run(), validate_rolling_window(), bool (+13 more)

### Community 13 - "Community 13"
Cohesion: 0.29
Nodes (21): compare_abs_contributions(), _compute_model_mean_abs_contrib(), gain_importance(), _load_model(), _load_training_module(), main(), _match_identifier(), match_shap() (+13 more)

### Community 14 - "Community 14"
Cohesion: 0.10
Nodes (20): Bet365 Web Scraper Reference, Betting Rule, code:python (from odds_api import OddsClient), code:bash (./venv/bin/python bet365_web_scraper.py --headed --json --te), code:bash (./venv/bin/python ev_pipeline.py --create-schema fetch-live), code:bash (./venv/bin/python ev_pipeline.py from-json path/to/snapshot.), code:bash (./venv/bin/python ev_pipeline.py candidates --probability-ru), code:text (EV = (model_probability * decimal_odds) - 1) (+12 more)

### Community 15 - "Community 15"
Cohesion: 0.12
Nodes (16): code:bash (./venv/bin/python player_minutes_model.py --create-schema re), code:bash (./venv/bin/python player_minutes_model.py train), code:bash (./venv/bin/python player_minutes_model.py train-final), code:bash (./venv/bin/python player_minutes_model.py predict-history), code:text (player_expected_shots = team_shots_hat * player_shot_share *), Documentation Refactor Plan, Downstream Contract, Feature Plan (+8 more)

### Community 16 - "Community 16"
Cohesion: 0.13
Nodes (14): Calibration, code:text (lambda_home = tempo_multiplier * home_multiplier * xg_home *), code:bash (./venv/bin/python probabilistic_markets.py --create-schema f), code:bash (./venv/bin/python probabilistic_markets.py fit-final), code:bash (./venv/bin/python probabilistic_markets.py predict-history), code:bash (./venv/bin/python probabilistic_markets.py predict-match --m), Commands, Current Team Goal Markets (+6 more)

### Community 17 - "Community 17"
Cohesion: 0.14
Nodes (13): code:text (rolling.rolling_tempo_corners_5), code:bash (python3 xgboost_xg_model.py --model corners_for train), code:bash (python3 xgboost_xg_model.py --model corners_for cross-valida), code:bash (python3 xgboost_xg_model.py --model corners_for train-final), code:bash (python3 xgboost_xg_model.py --model corners_for predict-hist), code:bash (python3 xgboost_xg_model.py --model corners_for predict-matc), code:text (match_corners_hat = home corners_for_hat + away corners_for_), Commands (+5 more)

### Community 18 - "Community 18"
Cohesion: 0.14
Nodes (14): 🧾 Data Units & Shapes, 🧮 Feature Rules (IMPORTANT), 🚀 Future Upgrades, 🔗 Integration with Bayesian Model, 🔁 Match-Level Outputs, 🎯 Model Output, 🎯 Objective, 🔄 Pipeline Flow (+6 more)

### Community 19 - "Community 19"
Cohesion: 0.14
Nodes (13): Candidate Formulae, code:text ((provider, provider_event_id) -> match_id), code:text (implied_probability = 1 / decimal_odds), code:text (EV >= threshold), code:bash (./venv/bin/python ev_pipeline.py fetch-live), code:bash (./venv/bin/python ev_pipeline.py candidates --probability-ru), code:bash (./venv/bin/python ev_pipeline.py --ev-threshold 0.05 candida), Commands (+5 more)

### Community 20 - "Community 20"
Cohesion: 0.15
Nodes (13): 1. CALIBRATION LAYER (CRITICAL), code:text (Model says:), code:text (those events only occur 62% of the time), code:text (Isotonic for large datasets), code:text (raw_market_probability), code:text (calibrated_probability), code:text (Raw probability model), ✅ Inputs (+5 more)

### Community 21 - "Community 21"
Cohesion: 0.15
Nodes (12): code:bash (python3 xgboost_xg_model.py train), code:bash (python3 xgboost_xg_model.py cross-validate), code:bash (python3 xgboost_xg_model.py train-final), code:bash (python3 xgboost_xg_model.py predict-history), code:bash (python3 xgboost_xg_model.py predict-match --match-id 123), Commands, Downstream Contract, Evaluation (+4 more)

### Community 22 - "Community 22"
Cohesion: 0.17
Nodes (11): code:text (raw player/team stats), code:sql (ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), code:bash (python3 team_feature_pipeline.py --create-schema --refresh), code:bash (python3 team_feature_pipeline.py --refresh --rolling-window ), Commands, Downstream Contract, Key Rules, Outputs (+3 more)

### Community 23 - "Community 23"
Cohesion: 0.17
Nodes (11): Boundaries, code:text (player_shots ~ Poisson(player_shots_expected_value)), code:text (player_shots_on_target <= player_shots), code:bash (./venv/bin/python match_simulation.py --create-schema simula), code:bash (./venv/bin/python match_simulation.py simulate-match \), Commands, Draw Rules, Inputs (+3 more)

### Community 24 - "Community 24"
Cohesion: 0.18
Nodes (11): code:bash (python3 -m pip install -r requirements.txt), code:bash (python3 team_feature_pipeline.py --create-schema --refresh), code:bash (python3 xgboost_xg_model.py train), code:bash (python3 xgboost_xg_model.py train-final), code:bash (python3 xgboost_xg_model.py train-final --refresh-source-tra), code:bash (python3 xgboost_xg_model.py cross-validate), code:text (models/xgboost_xg_for/), code:text (models/xgboost_xg_for_final/) (+3 more)

### Community 25 - "Community 25"
Cohesion: 0.18
Nodes (10): Allocation Contract, code:text (minutes_factor = expected_minutes / 90), code:text (0.5, 1.5, 2.5, 3.5), code:bash (./venv/bin/python player_prop_allocation.py --create-schema ), Downstream Boundary, Inputs, Probability Outputs, Purpose (+2 more)

### Community 26 - "Community 26"
Cohesion: 0.20
Nodes (9): BetPredictor EV Pipeline, code:text (Sofascore raw data), code:text (raw player appearances and lineup context), code:text (probabilistic team markets), Current Pipeline Map, Documentation Rules, Player Props Extension, Simulation Extension (+1 more)

### Community 27 - "Community 27"
Cohesion: 0.20
Nodes (10): Cons, Cons, Cons, Option A — Dixon-Coles Only (RECOMMENDED), Option B — Bivariate Poisson, Option C — Copula Models, ✅ Options, Pros (+2 more)

### Community 28 - "Community 28"
Cohesion: 0.20
Nodes (10): 2️⃣ Aggregate to Team-Match Level, Attack Features, code:block3 (match_id, team), code:python (team_xg = sum(player.expectedGoals)), code:python (team_interceptions = sum(player.interceptionWon)), code:python (team_passes = sum(player.accuratePass)), code:python (team_saves = sum(player.saves)), Defence Features (+2 more)

### Community 29 - "Community 29"
Cohesion: 0.20
Nodes (9): 7️⃣ Minimal Working Example (Python), code:block1 (RAW PLAYER MATCH DATA), code:python (# 1. per90), code:block15 (team | opponent | date |), 🧠 Final Output Example, 🎯 Goal, 🧱 Pipeline Overview, Step 1: Player → Team Feature Engineering Pipeline (+1 more)

### Community 30 - "Community 30"
Cohesion: 0.20
Nodes (9): code:bash (docker compose up -d db), code:bash (python3 sofascore_ingestion.py --limit-events 1), code:bash (python3 sofascore_ingestion.py), Commands, Inputs, Operational Notes, Outputs, Purpose (+1 more)

### Community 31 - "Community 31"
Cohesion: 0.42
Nodes (8): add_team_ids(), as_null(), clean_row(), get_team_aliases(), ingest_file(), main(), parse_date(), parse_time()

### Community 32 - "Community 32"
Cohesion: 0.22
Nodes (9): 3. UNCERTAINTY MODELLING, Bayesian Boosting, code:text (P10), code:text (Feature layer), ✅ Pipeline Placement, Quantile XGBoost (RECOMMENDED), ✅ Recommended Methods, ✅ What It Improves (+1 more)

### Community 33 - "Community 33"
Cohesion: 0.25
Nodes (7): code:bash (./venv/bin/python ev_pipeline.py fetch-live), code:bash (./venv/bin/python ev_pipeline.py from-json path/to/snapshot.), Normalised Markets, Persistence, Purpose, Source, Stage 5a: Odds Normalisation

### Community 34 - "Community 34"
Cohesion: 0.25
Nodes (8): 2. PROPER JOINT GOAL MODEL, code:text (xG estimates), code:text (home_goals), code:text (Independent Poisson), ✅ Pipeline Placement, ✅ Recommendation, ✅ What It Improves, ✅ What This Is

### Community 35 - "Community 35"
Cohesion: 0.25
Nodes (8): 1. Calibration layer, 2. Quantile uncertainty models, 3. Meta-model / bet filter, 4. Advanced dependency structures, IMPLEMENTATION ORDER (RECOMMENDED), 🥇 Tier 1 — MUST DO NEXT, 🥈 Tier 2 — HIGH VALUE, 🥉 Tier 3 — ADVANCED

### Community 36 - "Community 36"
Cohesion: 0.29
Nodes (6): BetPredictor — Next Steps Roadmap (`plan.md`), code:text (RAW PLAYER DATA), code:text (RAW PLAYER DATA), 📌 CURRENT PIPELINE, ✅ FINAL RECOMMENDED ARCHITECTURE, 🎯 Objective

### Community 37 - "Community 37"
Cohesion: 0.29
Nodes (7): 5. META-MODEL / BET FILTER, code:text (edge), code:text (bet_quality_score), ✅ Inputs, ✅ Outputs, ✅ What This Is, ✅ Why Important

### Community 38 - "Community 38"
Cohesion: 0.29
Nodes (7): Cons, Cons, Option A — Isotonic Regression (RECOMMENDED), Option B — Platt Scaling, Pros, Pros, ✅ Recommended Methods

### Community 39 - "Community 39"
Cohesion: 0.29
Nodes (7): 3️⃣ Normalisation Layer, code:python (possession_proxy = team_passes / (team_passes + opponent_pas), code:block8 (feature_per90 = total_feature / total_team_minutes * 90), code:python (pass_accuracy = accuratePass / totalPass), Possession Proxy, Ratios, Team Per-90

### Community 40 - "Community 40"
Cohesion: 0.29
Nodes (7): 1) Team Attacking Form (rolling), 2) Team Defensive Form (rolling), 3) Opponent Features (CRITICAL), 4) Lineup / Player Aggregation (YOUR EDGE), 5) Control & Tempo, 6) Context Features, 🧱 Inputs (Features)

### Community 41 - "Community 41"
Cohesion: 0.33
Nodes (6): 6️⃣ Feature Grouping, ⚔️ Attack, ⚙️ Control, 🛡️ Defence, 🧤 Goalkeeping, 🔄 Transition

### Community 42 - "Community 42"
Cohesion: 0.40
Nodes (5): 4. FEATURE IMPROVEMENTS, code:text (pressing intensity), ✅ Recommended Additions, ✅ Tempo Features, ✅ What It Improves

### Community 43 - "Community 43"
Cohesion: 0.40
Nodes (4): 4️⃣ Rolling Features (Form), Example (5-match rolling), Key Rule, Useful Rolling Features

### Community 44 - "Community 44"
Cohesion: 0.40
Nodes (5): 5️⃣ Opponent Adjustment, Basic Adjustment, code:block12 (adjusted_attack = team_xg / opponent_avg_xg_conceded), code:python (adj_xg = team_xg / opponent_rolling_xg_against), Example

### Community 45 - "Community 45"
Cohesion: 0.40
Nodes (5): ⚠️ Common Mistakes, ❌ Data Leakage, ❌ Double Counting, ❌ No Minutes Normalisation, ❌ No Opponent Adjustment

### Community 46 - "Community 46"
Cohesion: 0.40
Nodes (5): ⚠️ Common Mistakes, Data leakage, Double counting, Ignoring lineups, Predicting goals

### Community 47 - "Community 47"
Cohesion: 0.50
Nodes (4): 1️⃣ Filter + Minutes Weighting (CRITICAL), code:sql (stat_per90 = stat_value / minutesPlayed * 90), Per-90 Normalisation, Why this matters

## Knowledge Gaps
- **305 isolated node(s):** `code:text (Sofascore raw data)`, `code:text (raw player appearances and lineup context)`, `code:text (probabilistic team markets)`, `Stage Order`, `Documentation Rules` (+300 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `validate_rolling_window()` connect `Community 12` to `Community 5`?**
  _High betweenness centrality (0.024) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `PinnacleProvider` (e.g. with `LiveOddsSnapshot` and `OddsClient`) actually correct?**
  _`PinnacleProvider` has 16 INFERRED edges - model-reasoned connections that need verification._
- **What connects `code:text (Sofascore raw data)`, `code:text (raw player appearances and lineup context)`, `code:text (probabilistic team markets)` to the rest of the system?**
  _306 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.0680018630647415 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.05649000317359568 - nodes in this community are weakly interconnected._
- **Should `Community 2` be split into smaller, more focused modules?**
  _Cohesion score 0.11135430916552667 - nodes in this community are weakly interconnected._
- **Should `Community 3` be split into smaller, more focused modules?**
  _Cohesion score 0.09261261261261261 - nodes in this community are weakly interconnected._