from datetime import datetime, timezone
from dataclasses import replace
from decimal import Decimal

import pytest
import psycopg

import ev_pipeline
from ev_pipeline import (
    MatchReference,
    build_arg_parser,
    calculate_ev,
    match_odds_price,
    normalize_name,
    normalize_snapshot,
    read_snapshot_json,
)
from odds_api import LiveEvent, LiveOddsSnapshot, Market, Outcome, ProviderSnapshot


def sample_snapshot():
    fetched_at = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    return LiveOddsSnapshot(
        fetched_at=fetched_at,
        provider_snapshots=[
            ProviderSnapshot(
                provider="pinnacle",
                fetched_at=fetched_at,
                events=[
                    LiveEvent(
                        provider="pinnacle",
                        provider_event_id="evt-1",
                        sport="soccer",
                        league="England - Premier League",
                        home="Arsenal FC",
                        away="Chelsea",
                        starts=datetime(2026, 5, 10, 16, 30, tzinfo=timezone.utc),
                        status="live",
                        markets=[
                            Market(
                                market_type="moneyline",
                                period=0,
                                name="moneyline",
                                outcomes=[
                                    Outcome("home", Decimal("2.10"), "home"),
                                    Outcome("draw", Decimal("3.30"), "draw"),
                                    Outcome("away", Decimal("3.60"), "away"),
                                ],
                            ),
                            Market(
                                market_type="total",
                                period=0,
                                name="total 2.5",
                                outcomes=[
                                    Outcome("over", Decimal("1.91"), "over", Decimal("2.5")),
                                    Outcome("under", Decimal("1.95"), "under", Decimal("2.5")),
                                ],
                            ),
                            Market(
                                market_type="spread",
                                period=0,
                                name="spread -0.5",
                                outcomes=[
                                    Outcome("home", Decimal("2.01"), "home", Decimal("-0.5")),
                                ],
                            ),
                        ],
                    )
                ],
            )
        ],
    )


def test_market_mapping_supports_moneyline_and_totals_only():
    prices = normalize_snapshot(sample_snapshot())

    assert {(price.market_key, price.selection, price.line) for price in prices} == {
        ("1x2", "home", None),
        ("1x2", "draw", None),
        ("1x2", "away", None),
        ("total_goals", "over", Decimal("2.5")),
        ("total_goals", "under", Decimal("2.5")),
    }
    assert all(price.market_type in {"moneyline", "total"} for price in prices)


def test_ev_math_rejects_invalid_odds():
    result = calculate_ev(Decimal("0.55"), Decimal("2.10"))

    assert result is not None
    assert result.implied_probability == pytest.approx(Decimal("0.4761904762"))
    assert result.edge == pytest.approx(Decimal("0.0738095238"))
    assert result.expected_value == Decimal("0.1550")
    assert calculate_ev(Decimal("0.55"), Decimal("1.00")) is None
    assert calculate_ev(Decimal("1.20"), Decimal("2.00")) is None


def test_event_matching_uses_explicit_mapping_before_fallback():
    price = normalize_snapshot(sample_snapshot())[0]
    fallback_match = MatchReference(
        match_id=100,
        match_date=price.starts.date(),
        home_team_name="Arsenal",
        away_team_name="Chelsea",
    )

    assert match_odds_price(price, {("pinnacle", "evt-1"): 999}, [fallback_match]) == 999


def test_event_matching_falls_back_to_normalized_names_and_date():
    price = normalize_snapshot(sample_snapshot())[0]
    match = MatchReference(
        match_id=100,
        match_date=price.starts.date(),
        home_team_name="Arsenal",
        away_team_name="Chelsea",
    )

    assert normalize_name("Arsenal FC") == "arsenal"
    assert match_odds_price(price, {}, [match]) == 100


def test_unmatched_event_returns_none():
    price = normalize_snapshot(sample_snapshot())[0]
    match = MatchReference(
        match_id=100,
        match_date=price.starts.date(),
        home_team_name="Tottenham",
        away_team_name="Chelsea",
    )

    assert match_odds_price(price, {}, [match]) is None


def test_fallback_matching_requires_start_date():
    price = replace(normalize_snapshot(sample_snapshot())[0], starts=None)
    match = MatchReference(
        match_id=100,
        match_date=datetime(2026, 5, 10, tzinfo=timezone.utc).date(),
        home_team_name="Arsenal",
        away_team_name="Chelsea",
    )

    assert match_odds_price(price, {}, [match]) is None


def test_schema_contains_ev_tables_and_indexes():
    sql = open("schemas/probabilistic_markets.sql", encoding="utf-8").read()

    assert "model_outputs.odds_snapshots" in sql
    assert "model_outputs.odds_prices" in sql
    assert "model_outputs.bookmaker_event_mappings" in sql
    assert "model_outputs.ev_candidates" in sql
    assert "idx_ev_candidates_run_value" in sql


def test_json_snapshot_and_cli_smoke(tmp_path, monkeypatch):
    payload = {
        "fetched_at": "2026-05-10T12:00:00+00:00",
        "provider_snapshots": [
            {
                "provider": "pinnacle",
                "fetched_at": "2026-05-10T12:00:00+00:00",
                "events": [
                    {
                        "provider": "pinnacle",
                        "provider_event_id": "evt-1",
                        "sport": "soccer",
                        "league": "England - Premier League",
                        "home": "Arsenal",
                        "away": "Chelsea",
                        "starts": "2026-05-10T16:30:00+00:00",
                        "markets": [
                            {
                                "market_type": "total",
                                "period": 0,
                                "name": "total 2.5",
                                "outcomes": [
                                    {
                                        "name": "over",
                                        "side": "over",
                                        "points": "2.5",
                                        "price": "1.91",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    path = tmp_path / "snapshot.json"
    path.write_text(__import__("json").dumps(payload), encoding="utf-8")

    args = build_arg_parser().parse_args(["from-json", str(path), "--probability-run-id", "7"])
    snapshot = read_snapshot_json(args.path)
    prices = normalize_snapshot(snapshot)

    assert args.probability_run_id == 7
    assert len(prices) == 1
    assert prices[0].market_key == "total_goals"

    class FakeConnection:
        committed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def commit(self):
            self.committed = True

    fake_connection = FakeConnection()
    monkeypatch.setattr(psycopg, "connect", lambda db_url: fake_connection)
    monkeypatch.setattr(
        ev_pipeline,
        "persist_snapshot",
        lambda conn, snapshot, source, probability_run_id: (11, 1, 1),
    )
    monkeypatch.setattr(
        ev_pipeline,
        "write_ev_candidates",
        lambda conn, snapshot_id, probability_run_id, threshold: 1,
    )

    result = ev_pipeline.run_from_json(args)

    assert result == {
        "snapshot_id": 11,
        "probability_run_id": 7,
        "prices": 1,
        "matched_prices": 1,
        "ev_candidates": 1,
    }
    assert fake_connection.committed
