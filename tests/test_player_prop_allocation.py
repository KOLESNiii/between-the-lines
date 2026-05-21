from pathlib import Path
from types import SimpleNamespace

import pytest

from player_prop_allocation import (
    DEFAULT_SHOTS_MODEL_DIR,
    DEFAULT_SOT_MODEL_DIR,
    FEATURE_COLUMNS,
    MARKET_KEY_SHOTS,
    MARKET_KEY_SOT,
    META_COLUMNS,
    PROP_LINES,
    TARGET_PLAYER_SHOTS,
    TARGET_PLAYER_SOT,
    build_player_prop_features_sql,
    build_refresh_features_sql,
    build_where_clause,
    clip_share,
    poisson_over_probability,
    poisson_under_probability,
    resolve_player_share,
)


def compact_sql(sql: str) -> str:
    return " ".join(sql.split())


def test_public_contract_columns_and_markets():
    assert MARKET_KEY_SHOTS == "player_shots"
    assert MARKET_KEY_SOT == "player_shots_on_target"
    assert PROP_LINES == (0.5, 1.5, 2.5, 3.5)
    assert "match_id" in META_COLUMNS
    assert "player_id" in META_COLUMNS
    assert "team_id" in META_COLUMNS
    assert TARGET_PLAYER_SHOTS not in FEATURE_COLUMNS
    assert TARGET_PLAYER_SOT not in FEATURE_COLUMNS
    assert "rolling_player_shot_share_5" in FEATURE_COLUMNS
    assert "rolling_player_sot_share_5" in FEATURE_COLUMNS
    assert "rolling_position_shot_share" in FEATURE_COLUMNS
    assert "rolling_position_sot_share" in FEATURE_COLUMNS


def test_feature_sql_uses_prior_player_windows_only():
    sql = compact_sql(build_player_prop_features_sql())

    assert "ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING" in sql
    assert "ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING" in sql
    assert "PARTITION BY e.player_id, e.team_id ORDER BY e.start_datetime, e.match_id" in sql
    assert "PARTITION BY t.team_id ORDER BY t.start_datetime, t.match_id" in sql
    assert "PARTITION BY p.team_id, p.position_group ORDER BY p.start_datetime, p.match_id" in sql


def test_current_match_player_stats_are_targets_not_features():
    sql = compact_sql(build_player_prop_features_sql())

    assert "shots.stat_key = 'totalShots'" in sql
    assert "sot.stat_key = 'onTargetScoringAttempt'" in sql
    assert "COALESCE(shots.value_numeric, 0) AS target_player_shots" in sql
    assert "COALESCE(sot.value_numeric, 0) AS target_player_sot" in sql
    assert TARGET_PLAYER_SHOTS not in FEATURE_COLUMNS
    assert TARGET_PLAYER_SOT not in FEATURE_COLUMNS


def test_where_clause_filters_match_identifiers():
    assert build_where_clause(match_id=123) == "WHERE p.match_id = 123"
    assert (
        build_where_clause(sofascore_event_id=456, table_alias="f")
        == "WHERE f.sofascore_event_id = 456"
    )


def test_refresh_features_sql_targets_feature_table():
    sql = compact_sql(build_refresh_features_sql())

    assert "TRUNCATE features.player_prop_allocation_features" in sql
    assert "INSERT INTO features.player_prop_allocation_features" in sql
    assert "FROM ( WITH match_team_rows AS" in sql


def test_share_fallbacks_clip_to_safe_range():
    assert clip_share(1.7, 0.1) == 1.0
    assert clip_share(-0.2, 0.1) == 0.0
    assert clip_share(None, 0.1) == 0.1

    row = SimpleNamespace(
        position_group="forward",
        rolling_player_shot_share_5=None,
        rolling_position_shot_share=1.8,
        rolling_player_sot_share_5=-0.5,
        rolling_position_sot_share=0.2,
    )

    assert resolve_player_share(row, MARKET_KEY_SHOTS) == 1.0
    assert resolve_player_share(row, MARKET_KEY_SOT) == 0.0


def test_poisson_over_under_probabilities_sum_to_one():
    mean = 1.4
    for line in PROP_LINES:
        over = poisson_over_probability(mean, line)
        under = poisson_under_probability(mean, line)
        assert over + under == pytest.approx(1.0)
        assert 0.0 <= over <= 1.0
        assert 0.0 <= under <= 1.0


def test_poisson_zero_mean_makes_overs_zero():
    assert poisson_over_probability(0.0, 0.5) == pytest.approx(0.0)
    assert poisson_under_probability(0.0, 0.5) == pytest.approx(1.0)
    assert poisson_over_probability(float("nan"), 0.5) == pytest.approx(0.0)


def test_default_model_dirs_use_final_rate_artifacts():
    assert DEFAULT_SHOTS_MODEL_DIR == Path("models/xgboost_shots_for_final")
    assert DEFAULT_SOT_MODEL_DIR == Path("models/xgboost_shots_on_target_final")
