from pathlib import Path

import pytest

from team_feature_pipeline import build_refresh_sql, validate_rolling_window


def compact_sql(sql: str) -> str:
    return " ".join(sql.split())


def test_refresh_sql_sources_player_stats_only():
    sql = build_refresh_sql(5)

    assert "raw.sofascore_player_match_stats" in sql
    assert "raw.sofascore_player_match_appearances" in sql
    assert "raw.sofascore_team_match_stats" not in sql


def test_refresh_sql_excludes_unused_players_with_minutes_filter():
    sql = compact_sql(build_refresh_sql(5))

    assert "minutes.stat_key = 'minutesPlayed'" in sql
    assert "WHERE minutes.value_numeric > 0" in sql


def test_refresh_sql_uses_season_scoped_leak_free_window():
    sql = compact_sql(build_refresh_sql(5))

    assert "PARTITION BY a.team_id, a.season_year" in sql
    assert "ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING" in sql


def test_refresh_sql_requires_full_available_window_for_rolling_values():
    sql = compact_sql(build_refresh_sql(5))

    assert "CASE WHEN rolling_xg_for_available_count = 5 THEN rolling_xg_for_raw END" in sql
    assert (
        "CASE WHEN rolling_shots_for_available_count = 5 "
        "THEN rolling_shots_for_raw END"
    ) in sql


def test_validate_rolling_window_rejects_non_positive_values():
    with pytest.raises(ValueError):
        validate_rolling_window(0)


def test_schema_defines_feature_tables_and_indexes():
    schema_sql = Path("schemas/team_features.sql").read_text(encoding="utf-8")

    assert "CREATE SCHEMA IF NOT EXISTS features" in schema_sql
    assert "features.sofascore_team_match_aggregates" in schema_sql
    assert "features.sofascore_team_match_features" in schema_sql
    assert "idx_sofascore_team_features_team_form" in schema_sql
