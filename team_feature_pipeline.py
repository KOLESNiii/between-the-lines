import argparse
import os
from pathlib import Path


DEFAULT_DB_URL = "postgresql://user:pwd@localhost:5432/betting_historical_data"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "team_features.sql"
FULL_MATCH_TEAM_MINUTES = 990


REFRESH_SQL_TEMPLATE = """
TRUNCATE features.sofascore_team_match_features;
TRUNCATE features.sofascore_team_match_aggregates;

INSERT INTO features.sofascore_team_match_aggregates (
    match_id, sofascore_event_id, season_id, season_year, start_timestamp,
    start_datetime, match_date, team_id, opponent_id, team_name, opponent_name,
    side, goals_for, goals_against, active_player_count, total_team_minutes,
    xg_actual, xg_against_actual, shots_actual, shots_against_actual,
    tempo_ball_possession, tempo_total_shots, tempo_shots_on_target,
    tempo_shots_inside_box, tempo_touches_in_box, tempo_final_third_entries,
    tempo_corners, tempo_passes, tempo_accurate_passes, tempo_fouls,
    tempo_tackles, tempo_ball_recoveries,
    tempo_shots_off_target, tempo_blocked_shots, tempo_shots_outside_box,
    tempo_big_chances_scored, tempo_big_chances_missed, tempo_clearances,
    tempo_yellow_cards, tempo_goal_kicks, tempo_goals_prevented,
    tempo_crosses_completed, tempo_crosses_attempted,
    tempo_long_balls_completed, tempo_long_balls_attempted,
    tempo_dribbles_won, tempo_dribbles_attempted,
    tempo_tackles_won, tempo_tackles_attempted,
    confirmed_lineup, formation_code, listed_player_count, starter_count,
    bench_count, missing_player_count, doubtful_player_count,
    listed_market_value_eur, starter_market_value_eur,
    missing_market_value_eur, doubtful_market_value_eur,
    listed_avg_age_years, starter_avg_age_years, starter_defender_count,
    starter_midfielder_count, starter_forward_count,
    xg, xa, key_passes, big_chances, total_shots, shots_on_target,
    interceptions, tackles, blocks, aerial_won, aerial_lost, accurate_pass,
    total_pass, touches, long_balls, accurate_long_balls, progressive_carries,
    possession_lost_ctrl, saves, goals_prevented, expected_goals_on_target,
    pass_value, shot_value, dribble_value, defensive_value, total_progression,
    ball_carries, ball_carry_distance, progressive_carry_distance,
    opp_half_passes, accurate_opp_half_passes, total_contests, won_contests,
    fouls_committed, fouls_won, clearances, keeper_save_value,
    goalkeeper_value, xg_against, shots_against,
    big_chances_against, shots_on_target_against, pass_accuracy,
    aerial_win_rate, shot_accuracy, possession_proxy, passes_per_minute,
    saves_per_shot_faced, tackles_interceptions, has_xg, has_xa,
    has_key_passes, has_big_chances, has_total_shots, has_shots_on_target,
    has_interceptions, has_tackles, has_blocks, has_aerial_won, has_aerial_lost,
    has_accurate_pass, has_total_pass, has_touches, has_long_balls,
    has_accurate_long_balls, has_progressive_carries, has_possession_lost_ctrl,
    has_saves, has_goals_prevented, xg_player_count, xa_player_count,
    key_passes_player_count, big_chances_player_count, total_shots_player_count,
    shots_on_target_player_count, interceptions_player_count,
    tackles_player_count, blocks_player_count, aerial_won_player_count,
    aerial_lost_player_count, accurate_pass_player_count,
    total_pass_player_count, touches_player_count, long_balls_player_count,
    accurate_long_balls_player_count, progressive_carries_player_count,
    possession_lost_ctrl_player_count, saves_player_count,
    goals_prevented_player_count
)
WITH match_teams AS (
    SELECT
        m.id AS match_id,
        m.sofascore_event_id,
        m.season_id,
        m.season_year,
        m.start_timestamp,
        m.start_datetime,
        m.start_datetime::date AS match_date,
        m.home_team_id AS team_id,
        m.away_team_id AS opponent_id,
        home.name AS team_name,
        away.name AS opponent_name,
        'home'::text AS side,
        m.home_score AS goals_for,
        m.away_score AS goals_against
    FROM raw.sofascore_matches m
    JOIN raw.sofascore_teams home ON home.id = m.home_team_id
    JOIN raw.sofascore_teams away ON away.id = m.away_team_id

    UNION ALL

    SELECT
        m.id AS match_id,
        m.sofascore_event_id,
        m.season_id,
        m.season_year,
        m.start_timestamp,
        m.start_datetime,
        m.start_datetime::date AS match_date,
        m.away_team_id AS team_id,
        m.home_team_id AS opponent_id,
        away.name AS team_name,
        home.name AS opponent_name,
        'away'::text AS side,
        m.away_score AS goals_for,
        m.home_score AS goals_against
    FROM raw.sofascore_matches m
    JOIN raw.sofascore_teams home ON home.id = m.home_team_id
    JOIN raw.sofascore_teams away ON away.id = m.away_team_id
),
active_players AS (
    SELECT
        a.match_id,
        a.team_id,
        a.player_id,
        a.side,
        minutes.value_numeric AS minutes_played
    FROM raw.sofascore_player_match_appearances a
    JOIN raw.sofascore_player_match_stats minutes
      ON minutes.match_id = a.match_id
     AND minutes.team_id = a.team_id
     AND minutes.player_id = a.player_id
     AND minutes.stat_key = 'minutesPlayed'
    WHERE minutes.value_numeric > 0
),
active_summary AS (
    SELECT
        match_id,
        team_id,
        COUNT(*)::integer AS active_player_count,
        SUM(minutes_played) AS total_team_minutes
    FROM active_players
    GROUP BY match_id, team_id
),
stat_summary AS (
    SELECT
        ap.match_id,
        ap.team_id,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'expectedGoals') AS xg_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'expectedAssists') AS xa_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'keyPass') AS key_passes_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'bigChanceCreated') AS big_chances_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'totalShots') AS total_shots_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'onTargetScoringAttempt') AS shots_on_target_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'interceptionWon') AS interceptions_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'wonTackle') AS tackles_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'blockedScoringAttempt') AS blocks_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'aerialWon') AS aerial_won_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'aerialLost') AS aerial_lost_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'accuratePass') AS accurate_pass_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'totalPass') AS total_pass_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'touches') AS touches_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'totalLongBalls') AS long_balls_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'accurateLongBalls') AS accurate_long_balls_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'progressiveBallCarriesCount') AS progressive_carries_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'possessionLostCtrl') AS possession_lost_ctrl_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'saves') AS saves_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'goalsPrevented') AS goals_prevented_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'expectedGoalsOnTarget') AS expected_goals_on_target_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'passValueNormalized') AS pass_value_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'shotValueNormalized') AS shot_value_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'dribbleValueNormalized') AS dribble_value_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'defensiveValueNormalized') AS defensive_value_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'totalProgression') AS total_progression_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'ballCarriesCount') AS ball_carries_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'totalBallCarriesDistance') AS ball_carry_distance_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'totalProgressiveBallCarriesDistance') AS progressive_carry_distance_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'totalOppositionHalfPasses') AS opp_half_passes_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'accurateOppositionHalfPasses') AS accurate_opp_half_passes_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'totalContest') AS total_contests_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'wonContest') AS won_contests_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'fouls') AS fouls_committed_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'wasFouled') AS fouls_won_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'totalClearance') AS clearances_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'keeperSaveValue') AS keeper_save_value_raw,
        SUM(COALESCE(s.value_numeric, 0)) FILTER (WHERE s.stat_key = 'goalkeeperValueNormalized') AS goalkeeper_value_raw,

        COUNT(*) FILTER (WHERE s.stat_key = 'expectedGoals')::integer AS xg_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'expectedAssists')::integer AS xa_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'keyPass')::integer AS key_passes_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'bigChanceCreated')::integer AS big_chances_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'totalShots')::integer AS total_shots_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'onTargetScoringAttempt')::integer AS shots_on_target_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'interceptionWon')::integer AS interceptions_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'wonTackle')::integer AS tackles_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'blockedScoringAttempt')::integer AS blocks_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'aerialWon')::integer AS aerial_won_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'aerialLost')::integer AS aerial_lost_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'accuratePass')::integer AS accurate_pass_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'totalPass')::integer AS total_pass_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'touches')::integer AS touches_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'totalLongBalls')::integer AS long_balls_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'accurateLongBalls')::integer AS accurate_long_balls_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'progressiveBallCarriesCount')::integer AS progressive_carries_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'possessionLostCtrl')::integer AS possession_lost_ctrl_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'saves')::integer AS saves_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'goalsPrevented')::integer AS goals_prevented_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'expectedGoalsOnTarget')::integer AS expected_goals_on_target_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'passValueNormalized')::integer AS pass_value_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'shotValueNormalized')::integer AS shot_value_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'dribbleValueNormalized')::integer AS dribble_value_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'defensiveValueNormalized')::integer AS defensive_value_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'totalProgression')::integer AS total_progression_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'ballCarriesCount')::integer AS ball_carries_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'totalBallCarriesDistance')::integer AS ball_carry_distance_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'totalProgressiveBallCarriesDistance')::integer AS progressive_carry_distance_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'totalOppositionHalfPasses')::integer AS opp_half_passes_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'accurateOppositionHalfPasses')::integer AS accurate_opp_half_passes_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'totalContest')::integer AS total_contests_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'wonContest')::integer AS won_contests_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'fouls')::integer AS fouls_committed_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'wasFouled')::integer AS fouls_won_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'totalClearance')::integer AS clearances_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'keeperSaveValue')::integer AS keeper_save_value_player_count,
        COUNT(*) FILTER (WHERE s.stat_key = 'goalkeeperValueNormalized')::integer AS goalkeeper_value_player_count
    FROM active_players ap
    JOIN raw.sofascore_player_match_stats s
      ON s.match_id = ap.match_id
     AND s.team_id = ap.team_id
     AND s.player_id = ap.player_id
     AND s.stat_key IN (
        'expectedGoals', 'expectedAssists', 'keyPass', 'bigChanceCreated',
        'totalShots', 'onTargetScoringAttempt', 'interceptionWon',
        'wonTackle', 'blockedScoringAttempt', 'aerialWon', 'aerialLost',
        'accuratePass', 'totalPass', 'touches', 'totalLongBalls',
        'accurateLongBalls', 'progressiveBallCarriesCount',
        'possessionLostCtrl', 'saves', 'goalsPrevented',
        'expectedGoalsOnTarget', 'passValueNormalized', 'shotValueNormalized',
        'dribbleValueNormalized', 'defensiveValueNormalized', 'totalProgression',
        'ballCarriesCount', 'totalBallCarriesDistance',
        'totalProgressiveBallCarriesDistance', 'totalOppositionHalfPasses',
        'accurateOppositionHalfPasses', 'totalContest', 'wonContest',
        'fouls', 'wasFouled', 'totalClearance', 'keeperSaveValue',
        'goalkeeperValueNormalized'
     )
    GROUP BY ap.match_id, ap.team_id
),
team_stat_summary AS (
    SELECT
        match_id,
        team_id,
        MAX(value_numeric) FILTER (WHERE stat_key = 'ballPossession') AS tempo_ball_possession,
        MAX(value_numeric) FILTER (WHERE stat_key = 'totalShotsOnGoal') AS tempo_total_shots,
        MAX(value_numeric) FILTER (WHERE stat_key = 'shotsOnGoal') AS tempo_shots_on_target,
        MAX(value_numeric) FILTER (WHERE stat_key = 'totalShotsInsideBox') AS tempo_shots_inside_box,
        MAX(value_numeric) FILTER (WHERE stat_key = 'touchesInOppBox') AS tempo_touches_in_box,
        MAX(value_numeric) FILTER (WHERE stat_key = 'finalThirdEntries') AS tempo_final_third_entries,
        MAX(value_numeric) FILTER (WHERE stat_key = 'cornerKicks') AS tempo_corners,
        MAX(value_numeric) FILTER (WHERE stat_key = 'passes') AS tempo_passes,
        MAX(value_numeric) FILTER (WHERE stat_key = 'accuratePasses') AS tempo_accurate_passes,
        MAX(value_numeric) FILTER (WHERE stat_key = 'fouls') AS tempo_fouls,
        MAX(value_numeric) FILTER (WHERE stat_key = 'totalTackle') AS tempo_tackles,
        MAX(value_numeric) FILTER (WHERE stat_key = 'ballRecovery') AS tempo_ball_recoveries,
        MAX(value_numeric) FILTER (WHERE stat_key = 'shotsOffGoal') AS tempo_shots_off_target,
        MAX(value_numeric) FILTER (WHERE stat_key = 'blockedScoringAttempt') AS tempo_blocked_shots,
        MAX(value_numeric) FILTER (WHERE stat_key = 'totalShotsOutsideBox') AS tempo_shots_outside_box,
        MAX(value_numeric) FILTER (WHERE stat_key = 'bigChanceScored') AS tempo_big_chances_scored,
        MAX(value_numeric) FILTER (WHERE stat_key = 'bigChanceMissed') AS tempo_big_chances_missed,
        MAX(value_numeric) FILTER (WHERE stat_key = 'totalClearance') AS tempo_clearances,
        MAX(value_numeric) FILTER (WHERE stat_key = 'yellowCards') AS tempo_yellow_cards,
        MAX(value_numeric) FILTER (WHERE stat_key = 'goalKicks') AS tempo_goal_kicks,
        MAX(value_numeric) FILTER (WHERE stat_key = 'goalsPrevented') AS tempo_goals_prevented,
        MAX(value_numeric) FILTER (WHERE stat_key = 'accurateCross') AS tempo_crosses_completed,
        MAX(
            CASE
                WHEN stat_key = 'accurateCross'
                THEN NULLIF(raw_item ->> (side || 'Total'), '')::numeric
            END
        ) AS tempo_crosses_attempted,
        MAX(value_numeric) FILTER (WHERE stat_key = 'accurateLongBalls') AS tempo_long_balls_completed,
        MAX(
            CASE
                WHEN stat_key = 'accurateLongBalls'
                THEN NULLIF(raw_item ->> (side || 'Total'), '')::numeric
            END
        ) AS tempo_long_balls_attempted,
        MAX(value_numeric) FILTER (WHERE stat_key = 'dribblesPercentage') AS tempo_dribbles_won,
        MAX(
            CASE
                WHEN stat_key = 'dribblesPercentage'
                THEN NULLIF(raw_item ->> (side || 'Total'), '')::numeric
            END
        ) AS tempo_dribbles_attempted,
        MAX(value_numeric) FILTER (WHERE stat_key = 'wonTacklePercent') AS tempo_tackles_won,
        MAX(
            CASE
                WHEN stat_key = 'wonTacklePercent'
                THEN NULLIF(raw_item ->> (side || 'Total'), '')::numeric
            END
        ) AS tempo_tackles_attempted
    FROM raw.sofascore_team_match_stats
    WHERE period = 'ALL'
      AND stat_key IN (
        'ballPossession', 'totalShotsOnGoal', 'shotsOnGoal',
        'totalShotsInsideBox', 'touchesInOppBox', 'finalThirdEntries',
        'cornerKicks', 'passes', 'accuratePasses', 'fouls',
        'totalTackle', 'ballRecovery', 'shotsOffGoal',
        'blockedScoringAttempt', 'totalShotsOutsideBox', 'bigChanceScored',
        'bigChanceMissed', 'totalClearance', 'yellowCards', 'goalKicks',
        'goalsPrevented', 'accurateCross', 'accurateLongBalls',
        'dribblesPercentage', 'wonTacklePercent'
      )
    GROUP BY match_id, team_id
),
lineup_players AS (
    SELECT
        mt.match_id,
        mt.team_id,
        player_entry,
        COALESCE((player_entry ->> 'substitute')::boolean, false) AS is_substitute,
        player_entry ->> 'position' AS lineup_position,
        NULLIF(
            player_entry -> 'player' -> 'proposedMarketValueRaw' ->> 'value',
            ''
        )::numeric AS market_value_eur,
        CASE
            WHEN player_entry -> 'player' ->> 'dateOfBirthTimestamp' IS NOT NULL
            THEN (
                mt.match_date
                - to_timestamp(
                    (player_entry -> 'player' ->> 'dateOfBirthTimestamp')::bigint
                )::date
            ) / 365.25
        END AS age_years
    FROM match_teams mt
    JOIN raw.sofascore_match_stat_payloads payloads
      ON payloads.match_id = mt.match_id
    CROSS JOIN LATERAL jsonb_array_elements(
        COALESCE(payloads.lineups_payload -> mt.side -> 'players', '[]'::jsonb)
    ) AS players(player_entry)
),
lineup_missing AS (
    SELECT
        mt.match_id,
        mt.team_id,
        missing_entry ->> 'type' AS missing_type,
        NULLIF(
            missing_entry -> 'player' -> 'proposedMarketValueRaw' ->> 'value',
            ''
        )::numeric AS market_value_eur
    FROM match_teams mt
    JOIN raw.sofascore_match_stat_payloads payloads
      ON payloads.match_id = mt.match_id
    CROSS JOIN LATERAL jsonb_array_elements(
        COALESCE(payloads.lineups_payload -> mt.side -> 'missingPlayers', '[]'::jsonb)
    ) AS missing(missing_entry)
),
lineup_summary AS (
    SELECT
        mt.match_id,
        mt.team_id,
        (payloads.lineups_payload ->> 'confirmed')::boolean AS confirmed_lineup,
        NULLIF(
            regexp_replace(
                COALESCE(payloads.lineups_payload -> mt.side ->> 'formation', ''),
                '[^0-9]',
                '',
                'g'
            ),
            ''
        )::numeric AS formation_code,
        COUNT(lp.player_entry)::numeric AS listed_player_count,
        COUNT(lp.player_entry) FILTER (WHERE NOT lp.is_substitute)::numeric AS starter_count,
        COUNT(lp.player_entry) FILTER (WHERE lp.is_substitute)::numeric AS bench_count,
        COALESCE(missing_summary.missing_player_count, 0) AS missing_player_count,
        COALESCE(missing_summary.doubtful_player_count, 0) AS doubtful_player_count,
        SUM(lp.market_value_eur) AS listed_market_value_eur,
        SUM(lp.market_value_eur) FILTER (WHERE NOT lp.is_substitute) AS starter_market_value_eur,
        COALESCE(missing_summary.missing_market_value_eur, 0) AS missing_market_value_eur,
        COALESCE(missing_summary.doubtful_market_value_eur, 0) AS doubtful_market_value_eur,
        AVG(lp.age_years) AS listed_avg_age_years,
        AVG(lp.age_years) FILTER (WHERE NOT lp.is_substitute) AS starter_avg_age_years,
        COUNT(lp.player_entry) FILTER (WHERE NOT lp.is_substitute AND lp.lineup_position = 'D')::numeric AS starter_defender_count,
        COUNT(lp.player_entry) FILTER (WHERE NOT lp.is_substitute AND lp.lineup_position = 'M')::numeric AS starter_midfielder_count,
        COUNT(lp.player_entry) FILTER (WHERE NOT lp.is_substitute AND lp.lineup_position = 'F')::numeric AS starter_forward_count
    FROM match_teams mt
    JOIN raw.sofascore_match_stat_payloads payloads
      ON payloads.match_id = mt.match_id
    LEFT JOIN lineup_players lp
      ON lp.match_id = mt.match_id
     AND lp.team_id = mt.team_id
    LEFT JOIN (
        SELECT
            match_id,
            team_id,
            COUNT(*) FILTER (WHERE missing_type = 'missing')::numeric AS missing_player_count,
            COUNT(*) FILTER (WHERE missing_type = 'doubtful')::numeric AS doubtful_player_count,
            SUM(market_value_eur) FILTER (WHERE missing_type = 'missing') AS missing_market_value_eur,
            SUM(market_value_eur) FILTER (WHERE missing_type = 'doubtful') AS doubtful_market_value_eur
        FROM lineup_missing
        GROUP BY match_id, team_id
    ) missing_summary
      ON missing_summary.match_id = mt.match_id
     AND missing_summary.team_id = mt.team_id
    GROUP BY mt.match_id, mt.team_id, payloads.lineups_payload, mt.side,
        missing_summary.missing_player_count,
        missing_summary.doubtful_player_count,
        missing_summary.missing_market_value_eur,
        missing_summary.doubtful_market_value_eur
),
team_raw AS (
    SELECT
        mt.*,
        COALESCE(active.active_player_count, 0) AS active_player_count,
        active.total_team_minutes,
        stat.xg_raw,
        stat.xa_raw,
        stat.key_passes_raw,
        stat.big_chances_raw,
        stat.total_shots_raw,
        stat.shots_on_target_raw,
        stat.interceptions_raw,
        stat.tackles_raw,
        stat.blocks_raw,
        stat.aerial_won_raw,
        stat.aerial_lost_raw,
        stat.accurate_pass_raw,
        stat.total_pass_raw,
        stat.touches_raw,
        stat.long_balls_raw,
        stat.accurate_long_balls_raw,
        stat.progressive_carries_raw,
        stat.possession_lost_ctrl_raw,
        stat.saves_raw,
        stat.goals_prevented_raw,
        stat.expected_goals_on_target_raw,
        stat.pass_value_raw,
        stat.shot_value_raw,
        stat.dribble_value_raw,
        stat.defensive_value_raw,
        stat.total_progression_raw,
        stat.ball_carries_raw,
        stat.ball_carry_distance_raw,
        stat.progressive_carry_distance_raw,
        stat.opp_half_passes_raw,
        stat.accurate_opp_half_passes_raw,
        stat.total_contests_raw,
        stat.won_contests_raw,
        stat.fouls_committed_raw,
        stat.fouls_won_raw,
        stat.clearances_raw,
        stat.keeper_save_value_raw,
        stat.goalkeeper_value_raw,
        team_stat.tempo_ball_possession,
        team_stat.tempo_total_shots,
        team_stat.tempo_shots_on_target,
        team_stat.tempo_shots_inside_box,
        team_stat.tempo_touches_in_box,
        team_stat.tempo_final_third_entries,
        team_stat.tempo_corners,
        team_stat.tempo_passes,
        team_stat.tempo_accurate_passes,
        team_stat.tempo_fouls,
        team_stat.tempo_tackles,
        team_stat.tempo_ball_recoveries,
        team_stat.tempo_shots_off_target,
        team_stat.tempo_blocked_shots,
        team_stat.tempo_shots_outside_box,
        team_stat.tempo_big_chances_scored,
        team_stat.tempo_big_chances_missed,
        team_stat.tempo_clearances,
        team_stat.tempo_yellow_cards,
        team_stat.tempo_goal_kicks,
        team_stat.tempo_goals_prevented,
        team_stat.tempo_crosses_completed,
        team_stat.tempo_crosses_attempted,
        team_stat.tempo_long_balls_completed,
        team_stat.tempo_long_balls_attempted,
        team_stat.tempo_dribbles_won,
        team_stat.tempo_dribbles_attempted,
        team_stat.tempo_tackles_won,
        team_stat.tempo_tackles_attempted,
        lineup.confirmed_lineup,
        lineup.formation_code,
        lineup.listed_player_count,
        lineup.starter_count,
        lineup.bench_count,
        lineup.missing_player_count,
        lineup.doubtful_player_count,
        lineup.listed_market_value_eur,
        lineup.starter_market_value_eur,
        lineup.missing_market_value_eur,
        lineup.doubtful_market_value_eur,
        lineup.listed_avg_age_years,
        lineup.starter_avg_age_years,
        lineup.starter_defender_count,
        lineup.starter_midfielder_count,
        lineup.starter_forward_count,
        COALESCE(stat.xg_player_count, 0) AS xg_player_count,
        COALESCE(stat.xa_player_count, 0) AS xa_player_count,
        COALESCE(stat.key_passes_player_count, 0) AS key_passes_player_count,
        COALESCE(stat.big_chances_player_count, 0) AS big_chances_player_count,
        COALESCE(stat.total_shots_player_count, 0) AS total_shots_player_count,
        COALESCE(stat.shots_on_target_player_count, 0) AS shots_on_target_player_count,
        COALESCE(stat.interceptions_player_count, 0) AS interceptions_player_count,
        COALESCE(stat.tackles_player_count, 0) AS tackles_player_count,
        COALESCE(stat.blocks_player_count, 0) AS blocks_player_count,
        COALESCE(stat.aerial_won_player_count, 0) AS aerial_won_player_count,
        COALESCE(stat.aerial_lost_player_count, 0) AS aerial_lost_player_count,
        COALESCE(stat.accurate_pass_player_count, 0) AS accurate_pass_player_count,
        COALESCE(stat.total_pass_player_count, 0) AS total_pass_player_count,
        COALESCE(stat.touches_player_count, 0) AS touches_player_count,
        COALESCE(stat.long_balls_player_count, 0) AS long_balls_player_count,
        COALESCE(stat.accurate_long_balls_player_count, 0) AS accurate_long_balls_player_count,
        COALESCE(stat.progressive_carries_player_count, 0) AS progressive_carries_player_count,
        COALESCE(stat.possession_lost_ctrl_player_count, 0) AS possession_lost_ctrl_player_count,
        COALESCE(stat.saves_player_count, 0) AS saves_player_count,
        COALESCE(stat.goals_prevented_player_count, 0) AS goals_prevented_player_count,
        COALESCE(stat.expected_goals_on_target_player_count, 0) AS expected_goals_on_target_player_count,
        COALESCE(stat.pass_value_player_count, 0) AS pass_value_player_count,
        COALESCE(stat.shot_value_player_count, 0) AS shot_value_player_count,
        COALESCE(stat.dribble_value_player_count, 0) AS dribble_value_player_count,
        COALESCE(stat.defensive_value_player_count, 0) AS defensive_value_player_count,
        COALESCE(stat.total_progression_player_count, 0) AS total_progression_player_count,
        COALESCE(stat.ball_carries_player_count, 0) AS ball_carries_player_count,
        COALESCE(stat.ball_carry_distance_player_count, 0) AS ball_carry_distance_player_count,
        COALESCE(stat.progressive_carry_distance_player_count, 0) AS progressive_carry_distance_player_count,
        COALESCE(stat.opp_half_passes_player_count, 0) AS opp_half_passes_player_count,
        COALESCE(stat.accurate_opp_half_passes_player_count, 0) AS accurate_opp_half_passes_player_count,
        COALESCE(stat.total_contests_player_count, 0) AS total_contests_player_count,
        COALESCE(stat.won_contests_player_count, 0) AS won_contests_player_count,
        COALESCE(stat.fouls_committed_player_count, 0) AS fouls_committed_player_count,
        COALESCE(stat.fouls_won_player_count, 0) AS fouls_won_player_count,
        COALESCE(stat.clearances_player_count, 0) AS clearances_player_count,
        COALESCE(stat.keeper_save_value_player_count, 0) AS keeper_save_value_player_count,
        COALESCE(stat.goalkeeper_value_player_count, 0) AS goalkeeper_value_player_count
    FROM match_teams mt
    LEFT JOIN active_summary active
      ON active.match_id = mt.match_id
     AND active.team_id = mt.team_id
    LEFT JOIN stat_summary stat
      ON stat.match_id = mt.match_id
     AND stat.team_id = mt.team_id
    LEFT JOIN team_stat_summary team_stat
      ON team_stat.match_id = mt.match_id
     AND team_stat.team_id = mt.team_id
    LEFT JOIN lineup_summary lineup
      ON lineup.match_id = mt.match_id
     AND lineup.team_id = mt.team_id
),
normalised AS (
    SELECT
        team_raw.*,
        CASE WHEN xg_player_count > 0 THEN xg_raw END AS xg_actual,
        CASE WHEN total_shots_player_count > 0 THEN total_shots_raw END AS shots_actual,
        CASE WHEN xg_player_count > 0 THEN xg_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS xg,
        CASE WHEN xa_player_count > 0 THEN xa_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS xa,
        CASE WHEN key_passes_player_count > 0 THEN key_passes_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS key_passes,
        CASE WHEN big_chances_player_count > 0 THEN big_chances_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS big_chances,
        CASE WHEN total_shots_player_count > 0 THEN total_shots_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS total_shots,
        CASE WHEN shots_on_target_player_count > 0 THEN shots_on_target_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS shots_on_target,
        CASE WHEN interceptions_player_count > 0 THEN interceptions_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS interceptions,
        CASE WHEN tackles_player_count > 0 THEN tackles_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS tackles,
        CASE WHEN blocks_player_count > 0 THEN blocks_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS blocks,
        CASE WHEN aerial_won_player_count > 0 THEN aerial_won_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS aerial_won,
        CASE WHEN aerial_lost_player_count > 0 THEN aerial_lost_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS aerial_lost,
        CASE WHEN accurate_pass_player_count > 0 THEN accurate_pass_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS accurate_pass,
        CASE WHEN total_pass_player_count > 0 THEN total_pass_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS total_pass,
        CASE WHEN touches_player_count > 0 THEN touches_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS touches,
        CASE WHEN long_balls_player_count > 0 THEN long_balls_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS long_balls,
        CASE WHEN accurate_long_balls_player_count > 0 THEN accurate_long_balls_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS accurate_long_balls,
        CASE WHEN progressive_carries_player_count > 0 THEN progressive_carries_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS progressive_carries,
        CASE WHEN possession_lost_ctrl_player_count > 0 THEN possession_lost_ctrl_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS possession_lost_ctrl,
        CASE WHEN saves_player_count > 0 THEN saves_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS saves,
        CASE WHEN goals_prevented_player_count > 0 THEN goals_prevented_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS goals_prevented,
        CASE WHEN expected_goals_on_target_player_count > 0 THEN expected_goals_on_target_raw END AS expected_goals_on_target,
        CASE WHEN pass_value_player_count > 0 THEN pass_value_raw END AS pass_value,
        CASE WHEN shot_value_player_count > 0 THEN shot_value_raw END AS shot_value,
        CASE WHEN dribble_value_player_count > 0 THEN dribble_value_raw END AS dribble_value,
        CASE WHEN defensive_value_player_count > 0 THEN defensive_value_raw END AS defensive_value,
        CASE WHEN total_progression_player_count > 0 THEN total_progression_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS total_progression,
        CASE WHEN ball_carries_player_count > 0 THEN ball_carries_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS ball_carries,
        CASE WHEN ball_carry_distance_player_count > 0 THEN ball_carry_distance_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS ball_carry_distance,
        CASE WHEN progressive_carry_distance_player_count > 0 THEN progressive_carry_distance_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS progressive_carry_distance,
        CASE WHEN opp_half_passes_player_count > 0 THEN opp_half_passes_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS opp_half_passes,
        CASE WHEN accurate_opp_half_passes_player_count > 0 THEN accurate_opp_half_passes_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS accurate_opp_half_passes,
        CASE WHEN total_contests_player_count > 0 THEN total_contests_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS total_contests,
        CASE WHEN won_contests_player_count > 0 THEN won_contests_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS won_contests,
        CASE WHEN fouls_committed_player_count > 0 THEN fouls_committed_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS fouls_committed,
        CASE WHEN fouls_won_player_count > 0 THEN fouls_won_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS fouls_won,
        CASE WHEN clearances_player_count > 0 THEN clearances_raw * {full_match_team_minutes} / NULLIF(total_team_minutes, 0) END AS clearances,
        CASE WHEN keeper_save_value_player_count > 0 THEN keeper_save_value_raw END AS keeper_save_value,
        CASE WHEN goalkeeper_value_player_count > 0 THEN goalkeeper_value_raw END AS goalkeeper_value,
        CASE WHEN accurate_pass_player_count > 0 AND total_pass_player_count > 0 THEN accurate_pass_raw / NULLIF(total_pass_raw, 0) END AS pass_accuracy,
        CASE WHEN aerial_won_player_count > 0 OR aerial_lost_player_count > 0 THEN aerial_won_raw / NULLIF(COALESCE(aerial_won_raw, 0) + COALESCE(aerial_lost_raw, 0), 0) END AS aerial_win_rate,
        CASE WHEN shots_on_target_player_count > 0 AND total_shots_player_count > 0 THEN shots_on_target_raw / NULLIF(total_shots_raw, 0) END AS shot_accuracy,
        CASE WHEN accurate_pass_player_count > 0 THEN accurate_pass_raw / NULLIF(total_team_minutes, 0) END AS passes_per_minute
    FROM team_raw
),
with_opponent AS (
    SELECT
        n.*,
        opponent.xg_actual AS xg_against_actual,
        opponent.shots_actual AS shots_against_actual,
        opponent.xg AS xg_against,
        opponent.total_shots AS shots_against,
        opponent.big_chances AS big_chances_against,
        opponent.shots_on_target AS shots_on_target_against,
        n.accurate_pass / NULLIF(n.accurate_pass + opponent.accurate_pass, 0) AS possession_proxy,
        n.saves / NULLIF(opponent.shots_on_target, 0) AS saves_per_shot_faced,
        CASE
            WHEN n.tackles IS NOT NULL OR n.interceptions IS NOT NULL
            THEN COALESCE(n.tackles, 0) + COALESCE(n.interceptions, 0)
        END AS tackles_interceptions
    FROM normalised n
    LEFT JOIN normalised opponent
      ON opponent.match_id = n.match_id
     AND opponent.team_id = n.opponent_id
)
SELECT
    match_id, sofascore_event_id, season_id, season_year, start_timestamp,
    start_datetime, match_date, team_id, opponent_id, team_name, opponent_name,
    side, goals_for, goals_against, active_player_count, total_team_minutes,
    xg_actual, xg_against_actual, shots_actual, shots_against_actual,
    tempo_ball_possession, tempo_total_shots, tempo_shots_on_target,
    tempo_shots_inside_box, tempo_touches_in_box, tempo_final_third_entries,
    tempo_corners, tempo_passes, tempo_accurate_passes, tempo_fouls,
    tempo_tackles, tempo_ball_recoveries,
    tempo_shots_off_target, tempo_blocked_shots, tempo_shots_outside_box,
    tempo_big_chances_scored, tempo_big_chances_missed, tempo_clearances,
    tempo_yellow_cards, tempo_goal_kicks, tempo_goals_prevented,
    tempo_crosses_completed, tempo_crosses_attempted,
    tempo_long_balls_completed, tempo_long_balls_attempted,
    tempo_dribbles_won, tempo_dribbles_attempted,
    tempo_tackles_won, tempo_tackles_attempted,
    confirmed_lineup, formation_code, listed_player_count, starter_count,
    bench_count, missing_player_count, doubtful_player_count,
    listed_market_value_eur, starter_market_value_eur,
    missing_market_value_eur, doubtful_market_value_eur,
    listed_avg_age_years, starter_avg_age_years, starter_defender_count,
    starter_midfielder_count, starter_forward_count,
    xg, xa, key_passes, big_chances, total_shots, shots_on_target,
    interceptions, tackles, blocks, aerial_won, aerial_lost, accurate_pass,
    total_pass, touches, long_balls, accurate_long_balls, progressive_carries,
    possession_lost_ctrl, saves, goals_prevented, expected_goals_on_target,
    pass_value, shot_value, dribble_value, defensive_value, total_progression,
    ball_carries, ball_carry_distance, progressive_carry_distance,
    opp_half_passes, accurate_opp_half_passes, total_contests, won_contests,
    fouls_committed, fouls_won, clearances, keeper_save_value,
    goalkeeper_value, xg_against, shots_against,
    big_chances_against, shots_on_target_against, pass_accuracy,
    aerial_win_rate, shot_accuracy, possession_proxy, passes_per_minute,
    saves_per_shot_faced, tackles_interceptions, xg_player_count > 0,
    xa_player_count > 0, key_passes_player_count > 0,
    big_chances_player_count > 0, total_shots_player_count > 0,
    shots_on_target_player_count > 0, interceptions_player_count > 0,
    tackles_player_count > 0, blocks_player_count > 0,
    aerial_won_player_count > 0, aerial_lost_player_count > 0,
    accurate_pass_player_count > 0, total_pass_player_count > 0,
    touches_player_count > 0, long_balls_player_count > 0,
    accurate_long_balls_player_count > 0, progressive_carries_player_count > 0,
    possession_lost_ctrl_player_count > 0, saves_player_count > 0,
    goals_prevented_player_count > 0, xg_player_count, xa_player_count,
    key_passes_player_count, big_chances_player_count, total_shots_player_count,
    shots_on_target_player_count, interceptions_player_count,
    tackles_player_count, blocks_player_count, aerial_won_player_count,
    aerial_lost_player_count, accurate_pass_player_count,
    total_pass_player_count, touches_player_count, long_balls_player_count,
    accurate_long_balls_player_count, progressive_carries_player_count,
    possession_lost_ctrl_player_count, saves_player_count,
    goals_prevented_player_count
FROM with_opponent;

INSERT INTO features.sofascore_team_match_features (
    match_id, sofascore_event_id, season_id, season_year, start_timestamp,
    start_datetime, match_date, team_id, opponent_id, team_name, opponent_name,
    side, goals_for, goals_against, active_player_count, total_team_minutes,
    xg_actual, xg_against_actual, shots_actual, shots_against_actual,
    tempo_ball_possession, tempo_total_shots, tempo_shots_on_target,
    tempo_shots_inside_box, tempo_touches_in_box, tempo_final_third_entries,
    tempo_corners, tempo_passes, tempo_accurate_passes, tempo_fouls,
    tempo_tackles, tempo_ball_recoveries,
    tempo_shots_off_target, tempo_blocked_shots, tempo_shots_outside_box,
    tempo_big_chances_scored, tempo_big_chances_missed, tempo_clearances,
    tempo_yellow_cards, tempo_goal_kicks, tempo_goals_prevented,
    tempo_crosses_completed, tempo_crosses_attempted,
    tempo_long_balls_completed, tempo_long_balls_attempted,
    tempo_dribbles_won, tempo_dribbles_attempted,
    tempo_tackles_won, tempo_tackles_attempted,
    confirmed_lineup, formation_code, listed_player_count, starter_count,
    bench_count, missing_player_count, doubtful_player_count,
    listed_market_value_eur, starter_market_value_eur,
    missing_market_value_eur, doubtful_market_value_eur,
    listed_avg_age_years, starter_avg_age_years, starter_defender_count,
    starter_midfielder_count, starter_forward_count,
    xg, xa, key_passes, big_chances, total_shots, shots_on_target,
    interceptions, tackles, blocks, aerial_won, aerial_lost, accurate_pass,
    total_pass, touches, long_balls, accurate_long_balls, progressive_carries,
    possession_lost_ctrl, saves, goals_prevented, expected_goals_on_target,
    pass_value, shot_value, dribble_value, defensive_value, total_progression,
    ball_carries, ball_carry_distance, progressive_carry_distance,
    opp_half_passes, accurate_opp_half_passes, total_contests, won_contests,
    fouls_committed, fouls_won, clearances, keeper_save_value,
    goalkeeper_value, xg_against, shots_against,
    big_chances_against, shots_on_target_against, pass_accuracy,
    aerial_win_rate, shot_accuracy, possession_proxy, passes_per_minute,
    saves_per_shot_faced, tackles_interceptions, has_xg, has_xa,
    has_key_passes, has_big_chances, has_total_shots, has_shots_on_target,
    has_interceptions, has_tackles, has_blocks, has_aerial_won, has_aerial_lost,
    has_accurate_pass, has_total_pass, has_touches, has_long_balls,
    has_accurate_long_balls, has_progressive_carries, has_possession_lost_ctrl,
    has_saves, has_goals_prevented, xg_player_count, xa_player_count,
    key_passes_player_count, big_chances_player_count, total_shots_player_count,
    shots_on_target_player_count, interceptions_player_count,
    tackles_player_count, blocks_player_count, aerial_won_player_count,
    aerial_lost_player_count, accurate_pass_player_count,
    total_pass_player_count, touches_player_count, long_balls_player_count,
    accurate_long_balls_player_count, progressive_carries_player_count,
    possession_lost_ctrl_player_count, saves_player_count,
    goals_prevented_player_count, history_match_count,
    rolling_xg_for_available_count, rolling_xg_against_available_count,
    rolling_shots_for_available_count, rolling_shots_against_available_count,
    rolling_big_chances_for_available_count,
    rolling_big_chances_against_available_count,
    rolling_possession_proxy_available_count,
    rolling_pass_accuracy_available_count,
    rolling_tackles_interceptions_available_count,
    rolling_saves_per_shot_faced_available_count, rolling_xg_for,
    rolling_xg_against, rolling_shots_for, rolling_shots_against,
    rolling_big_chances_for, rolling_big_chances_against,
    rolling_possession_proxy, rolling_pass_accuracy,
    rolling_tackles_interceptions, rolling_saves_per_shot_faced,
    opponent_history_match_count, opponent_rolling_xg_for,
    opponent_rolling_xg_against, opponent_rolling_shots_for,
    opponent_rolling_shots_against, adj_attack_xg, adj_defence_xg,
    adj_shot_volume
)
WITH rolling_calc AS (
    SELECT
        a.*,
        (COUNT(*) OVER w)::integer AS history_match_count,
        (COUNT(a.xg) OVER w)::integer AS rolling_xg_for_available_count,
        (COUNT(a.xg_against) OVER w)::integer AS rolling_xg_against_available_count,
        (COUNT(a.total_shots) OVER w)::integer AS rolling_shots_for_available_count,
        (COUNT(a.shots_against) OVER w)::integer AS rolling_shots_against_available_count,
        (COUNT(a.big_chances) OVER w)::integer AS rolling_big_chances_for_available_count,
        (COUNT(a.big_chances_against) OVER w)::integer AS rolling_big_chances_against_available_count,
        (COUNT(a.possession_proxy) OVER w)::integer AS rolling_possession_proxy_available_count,
        (COUNT(a.pass_accuracy) OVER w)::integer AS rolling_pass_accuracy_available_count,
        (COUNT(a.tackles_interceptions) OVER w)::integer AS rolling_tackles_interceptions_available_count,
        (COUNT(a.saves_per_shot_faced) OVER w)::integer AS rolling_saves_per_shot_faced_available_count,
        AVG(a.xg) OVER w AS rolling_xg_for_raw,
        AVG(a.xg_against) OVER w AS rolling_xg_against_raw,
        AVG(a.total_shots) OVER w AS rolling_shots_for_raw,
        AVG(a.shots_against) OVER w AS rolling_shots_against_raw,
        AVG(a.big_chances) OVER w AS rolling_big_chances_for_raw,
        AVG(a.big_chances_against) OVER w AS rolling_big_chances_against_raw,
        AVG(a.possession_proxy) OVER w AS rolling_possession_proxy_raw,
        AVG(a.pass_accuracy) OVER w AS rolling_pass_accuracy_raw,
        AVG(a.tackles_interceptions) OVER w AS rolling_tackles_interceptions_raw,
        AVG(a.saves_per_shot_faced) OVER w AS rolling_saves_per_shot_faced_raw
    FROM features.sofascore_team_match_aggregates a
    WINDOW w AS (
        PARTITION BY a.team_id
        ORDER BY a.start_datetime, a.match_id
        ROWS BETWEEN {rolling_window} PRECEDING AND 1 PRECEDING
    )
),
rolling AS (
    SELECT
        rolling_calc.*,
        COALESCE(rolling_xg_for_raw, 1.35) AS rolling_xg_for,
        COALESCE(rolling_xg_against_raw, 1.35) AS rolling_xg_against,
        COALESCE(rolling_shots_for_raw, 12.0) AS rolling_shots_for,
        COALESCE(rolling_shots_against_raw, 12.0) AS rolling_shots_against,
        COALESCE(rolling_big_chances_for_raw, 1.5) AS rolling_big_chances_for,
        COALESCE(rolling_big_chances_against_raw, 1.5) AS rolling_big_chances_against,
        COALESCE(rolling_possession_proxy_raw, 0.5) AS rolling_possession_proxy,
        COALESCE(rolling_pass_accuracy_raw, 0.78) AS rolling_pass_accuracy,
        COALESCE(rolling_tackles_interceptions_raw, 25.0) AS rolling_tackles_interceptions,
        COALESCE(rolling_saves_per_shot_faced_raw, 0.3) AS rolling_saves_per_shot_faced
    FROM rolling_calc
)
SELECT
    r.match_id, r.sofascore_event_id, r.season_id, r.season_year,
    r.start_timestamp, r.start_datetime, r.match_date, r.team_id,
    r.opponent_id, r.team_name, r.opponent_name, r.side, r.goals_for,
    r.goals_against, r.active_player_count, r.total_team_minutes,
    r.xg_actual, r.xg_against_actual, r.shots_actual, r.shots_against_actual,
    r.tempo_ball_possession, r.tempo_total_shots, r.tempo_shots_on_target,
    r.tempo_shots_inside_box, r.tempo_touches_in_box,
    r.tempo_final_third_entries, r.tempo_corners, r.tempo_passes,
    r.tempo_accurate_passes, r.tempo_fouls, r.tempo_tackles,
    r.tempo_ball_recoveries,
    r.tempo_shots_off_target, r.tempo_blocked_shots,
    r.tempo_shots_outside_box, r.tempo_big_chances_scored,
    r.tempo_big_chances_missed, r.tempo_clearances, r.tempo_yellow_cards,
    r.tempo_goal_kicks, r.tempo_goals_prevented, r.tempo_crosses_completed,
    r.tempo_crosses_attempted, r.tempo_long_balls_completed,
    r.tempo_long_balls_attempted, r.tempo_dribbles_won,
    r.tempo_dribbles_attempted, r.tempo_tackles_won,
    r.tempo_tackles_attempted, r.confirmed_lineup, r.formation_code,
    r.listed_player_count, r.starter_count, r.bench_count,
    r.missing_player_count, r.doubtful_player_count,
    r.listed_market_value_eur, r.starter_market_value_eur,
    r.missing_market_value_eur, r.doubtful_market_value_eur,
    r.listed_avg_age_years, r.starter_avg_age_years,
    r.starter_defender_count, r.starter_midfielder_count,
    r.starter_forward_count,
    r.xg, r.xa,
    r.key_passes, r.big_chances, r.total_shots, r.shots_on_target,
    r.interceptions, r.tackles, r.blocks, r.aerial_won, r.aerial_lost,
    r.accurate_pass, r.total_pass, r.touches, r.long_balls,
    r.accurate_long_balls, r.progressive_carries, r.possession_lost_ctrl,
    r.saves, r.goals_prevented, r.expected_goals_on_target, r.pass_value,
    r.shot_value, r.dribble_value, r.defensive_value, r.total_progression,
    r.ball_carries, r.ball_carry_distance, r.progressive_carry_distance,
    r.opp_half_passes, r.accurate_opp_half_passes, r.total_contests,
    r.won_contests, r.fouls_committed, r.fouls_won, r.clearances,
    r.keeper_save_value, r.goalkeeper_value, r.xg_against, r.shots_against,
    r.big_chances_against, r.shots_on_target_against, r.pass_accuracy,
    r.aerial_win_rate, r.shot_accuracy, r.possession_proxy,
    r.passes_per_minute, r.saves_per_shot_faced, r.tackles_interceptions,
    r.has_xg, r.has_xa, r.has_key_passes, r.has_big_chances,
    r.has_total_shots, r.has_shots_on_target, r.has_interceptions,
    r.has_tackles, r.has_blocks, r.has_aerial_won, r.has_aerial_lost,
    r.has_accurate_pass, r.has_total_pass, r.has_touches, r.has_long_balls,
    r.has_accurate_long_balls, r.has_progressive_carries,
    r.has_possession_lost_ctrl, r.has_saves, r.has_goals_prevented,
    r.xg_player_count, r.xa_player_count, r.key_passes_player_count,
    r.big_chances_player_count, r.total_shots_player_count,
    r.shots_on_target_player_count, r.interceptions_player_count,
    r.tackles_player_count, r.blocks_player_count, r.aerial_won_player_count,
    r.aerial_lost_player_count, r.accurate_pass_player_count,
    r.total_pass_player_count, r.touches_player_count,
    r.long_balls_player_count, r.accurate_long_balls_player_count,
    r.progressive_carries_player_count, r.possession_lost_ctrl_player_count,
    r.saves_player_count, r.goals_prevented_player_count,
    r.history_match_count, r.rolling_xg_for_available_count,
    r.rolling_xg_against_available_count, r.rolling_shots_for_available_count,
    r.rolling_shots_against_available_count,
    r.rolling_big_chances_for_available_count,
    r.rolling_big_chances_against_available_count,
    r.rolling_possession_proxy_available_count,
    r.rolling_pass_accuracy_available_count,
    r.rolling_tackles_interceptions_available_count,
    r.rolling_saves_per_shot_faced_available_count, r.rolling_xg_for,
    r.rolling_xg_against, r.rolling_shots_for, r.rolling_shots_against,
    r.rolling_big_chances_for, r.rolling_big_chances_against,
    r.rolling_possession_proxy, r.rolling_pass_accuracy,
    r.rolling_tackles_interceptions, r.rolling_saves_per_shot_faced,
    opponent.history_match_count AS opponent_history_match_count,
    opponent.rolling_xg_for AS opponent_rolling_xg_for,
    opponent.rolling_xg_against AS opponent_rolling_xg_against,
    opponent.rolling_shots_for AS opponent_rolling_shots_for,
    opponent.rolling_shots_against AS opponent_rolling_shots_against,
    r.rolling_xg_for / NULLIF(opponent.rolling_xg_against, 0) AS adj_attack_xg,
    r.rolling_xg_against / NULLIF(opponent.rolling_xg_for, 0) AS adj_defence_xg,
    r.rolling_shots_for / NULLIF(opponent.rolling_shots_against, 0) AS adj_shot_volume
FROM rolling r
LEFT JOIN rolling opponent
  ON opponent.match_id = r.match_id
 AND opponent.team_id = r.opponent_id;
"""


def read_schema_sql() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


def validate_rolling_window(rolling_window: int) -> int:
    if rolling_window < 1:
        raise ValueError("--rolling-window must be at least 1")
    return rolling_window


def build_refresh_sql(rolling_window: int) -> str:
    rolling_window = validate_rolling_window(rolling_window)
    return (
        REFRESH_SQL_TEMPLATE.replace("{rolling_window}", str(rolling_window))
        .replace("{full_match_team_minutes}", str(FULL_MATCH_TEAM_MINUTES))
    )


def create_schema(conn) -> None:
    conn.execute(read_schema_sql())


def refresh_features(conn, rolling_window: int) -> tuple[int, int]:
    conn.execute(build_refresh_sql(rolling_window))
    aggregate_count = conn.execute(
        "SELECT count(*) FROM features.sofascore_team_match_aggregates"
    ).fetchone()[0]
    feature_count = conn.execute(
        "SELECT count(*) FROM features.sofascore_team_match_features"
    ).fetchone()[0]
    return aggregate_count, feature_count


def run(create_schema_first: bool, refresh: bool, db_url: str, rolling_window: int) -> None:
    import psycopg

    with psycopg.connect(db_url) as conn:
        with conn.transaction():
            if create_schema_first or refresh:
                create_schema(conn)
            if refresh:
                aggregate_count, feature_count = refresh_features(conn, rolling_window)
            else:
                aggregate_count = feature_count = None

    if create_schema_first:
        print("Feature schema is ready.")
    if refresh:
        print(f"Refreshed {aggregate_count} aggregate rows.")
        print(f"Refreshed {feature_count} feature rows.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Sofascore player-derived team-match feature tables."
    )
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="Create the features schema and feature tables if they do not exist.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Rebuild aggregate and final feature tables from raw Sofascore player stats.",
    )
    parser.add_argument(
        "--rolling-window",
        type=int,
        default=5,
        help="Number of previous team matches used for rolling form.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DB_URL", DEFAULT_DB_URL),
        help="Postgres connection URL. Defaults to DB_URL or the local docker DB.",
    )
    args = parser.parse_args()

    if not args.create_schema and not args.refresh:
        parser.error("choose at least one of --create-schema or --refresh")

    run(
        create_schema_first=args.create_schema,
        refresh=args.refresh,
        db_url=args.db_url,
        rolling_window=args.rolling_window,
    )


if __name__ == "__main__":
    main()
