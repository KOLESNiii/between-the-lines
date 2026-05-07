from pathlib import Path

import pytest

from team_feature_pipeline import build_refresh_sql, validate_rolling_window


def compact_sql(sql: str) -> str:
    return " ".join(sql.split())


def test_refresh_sql_sources_player_and_team_stats():
    sql = build_refresh_sql(5)

    assert "raw.sofascore_player_match_stats" in sql
    assert "raw.sofascore_player_match_appearances" in sql
    assert "raw.sofascore_team_match_stats" in sql


def test_refresh_sql_dedupes_all_period_team_tempo_stats():
    sql = compact_sql(build_refresh_sql(5))

    assert "MAX(value_numeric) FILTER (WHERE stat_key = 'totalShotsOnGoal')" in sql
    assert "MAX(value_numeric) FILTER (WHERE stat_key = 'touchesInOppBox')" in sql
    assert "WHERE period = 'ALL'" in sql
    assert "'finalThirdEntries'" in sql


def test_refresh_sql_extracts_rich_sofascore_team_ratios():
    sql = compact_sql(build_refresh_sql(5))

    assert "raw_item ->> (side || 'Total')" in sql
    assert "tempo_crosses_attempted" in sql
    assert "tempo_long_balls_attempted" in sql
    assert "tempo_dribbles_attempted" in sql
    assert "tempo_tackles_attempted" in sql
    assert "'bigChanceMissed'" in sql
    assert "'goalsPrevented'" in sql


def test_refresh_sql_extracts_pre_match_lineup_context():
    sql = compact_sql(build_refresh_sql(5))

    assert "raw.sofascore_match_stat_payloads" in sql
    assert "lineup_summary AS" in sql
    assert "confirmed_lineup" in sql
    assert "formation_code" in sql
    assert "missing_market_value_eur" in sql
    assert "starter_avg_age_years" in sql


def test_refresh_sql_sources_expanded_player_stats():
    sql = compact_sql(build_refresh_sql(5))

    assert "'expectedGoalsOnTarget'" in sql
    assert "'passValueNormalized'" in sql
    assert "'totalProgression'" in sql
    assert "'totalOppositionHalfPasses'" in sql
    assert "'keeperSaveValue'" in sql


def test_refresh_sql_excludes_unused_players_with_minutes_filter():
    sql = compact_sql(build_refresh_sql(5))

    assert "minutes.stat_key = 'minutesPlayed'" in sql
    assert "WHERE minutes.value_numeric > 0" in sql


def test_refresh_sql_uses_cross_season_leak_free_window():
    sql = compact_sql(build_refresh_sql(5))

    assert "PARTITION BY a.team_id ORDER BY a.start_datetime, a.match_id" in sql
    assert "ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING" in sql


def test_refresh_sql_uses_prior_fallbacks_instead_of_nulling_cold_starts():
    sql = compact_sql(build_refresh_sql(5))

    assert "COALESCE(rolling_xg_for_raw, 1.35) AS rolling_xg_for" in sql
    assert "COALESCE(rolling_shots_for_raw, 12.0) AS rolling_shots_for" in sql


def test_validate_rolling_window_rejects_non_positive_values():
    with pytest.raises(ValueError):
        validate_rolling_window(0)


def test_schema_defines_feature_tables_and_indexes():
    schema_sql = Path("schemas/team_features.sql").read_text(encoding="utf-8")

    assert "CREATE SCHEMA IF NOT EXISTS features" in schema_sql
    assert "features.sofascore_team_match_aggregates" in schema_sql
    assert "features.sofascore_team_match_features" in schema_sql
    assert "xg_actual NUMERIC" in schema_sql
    assert "ADD COLUMN IF NOT EXISTS xg_actual" in schema_sql
    assert "tempo_touches_in_box NUMERIC" in schema_sql
    assert "ADD COLUMN IF NOT EXISTS tempo_total_shots" in schema_sql
    assert "tempo_crosses_attempted NUMERIC" in schema_sql
    assert "starter_market_value_eur NUMERIC" in schema_sql
    assert "expected_goals_on_target NUMERIC" in schema_sql
    assert "idx_sofascore_team_features_team_form" in schema_sql
