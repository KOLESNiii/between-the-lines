from pathlib import Path

from odds_api import OddsClient
from odds_api.providers.pinnacle import PinnacleProvider


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "params": params,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return self.response


def test_pinnacle_normalizes_live_markets(tmp_path):
    payload = {
        "sport_id": 1,
        "last": 523864,
        "events": [
            {
                "event_id": 1628594960,
                "sport_id": 1,
                "league_name": "England - Premier League",
                "starts": "2026-05-04T16:30:00Z",
                "home": "Arsenal",
                "away": "Chelsea",
                "event_type": "live",
                "last": 523864,
                "periods": {
                    "num_0": {
                        "number": 0,
                        "money_line": {"home": 2.45, "draw": 3.3, "away": 2.9},
                        "spreads": {"-0.5": {"hdp": -0.5, "home": 2.06, "away": 1.82}},
                        "totals": {"2.5": {"points": 2.5, "over": 1.9, "under": 1.98}},
                        "team_total": {"home": {"points": 1.5, "over": 1.86, "under": 2.0}},
                    }
                },
            }
        ],
    }
    session = FakeSession(FakeResponse(payload))
    provider = PinnacleProvider(
        api_key="test-key",
        state_path=tmp_path / "state.json",
        session=session,
    )

    snapshot = provider.get_live_odds("soccer")

    assert snapshot.cursor == "523864"
    assert len(snapshot.events) == 1
    assert {market.market_type for market in snapshot.events[0].markets} == {
        "moneyline",
        "spread",
        "total",
        "team_total",
    }
    assert session.calls[0]["headers"] == {"x-portal-apikey": "test-key"}


def test_pinnacle_daily_budget_blocks_without_request(tmp_path):
    state_path = tmp_path / "state.json"
    provider = PinnacleProvider(
        api_key="test-key",
        daily_budget=0,
        state_path=state_path,
        session=FakeSession(FakeResponse({"events": []})),
    )

    snapshot = provider.get_live_odds("soccer")

    assert snapshot.skipped is not None
    assert snapshot.skipped.reason == "daily_budget_exhausted"


def test_pinnacle_429_records_retry_after(tmp_path):
    session = FakeSession(
        FakeResponse(
            {"error": "rate_limited"},
            status_code=429,
            headers={"Retry-After": "41"},
        )
    )
    provider = PinnacleProvider(
        api_key="test-key",
        state_path=tmp_path / "state.json",
        session=session,
    )

    snapshot = provider.get_live_odds("soccer")

    assert snapshot.skipped is not None
    assert snapshot.skipped.reason == "remote_rate_limited"
    assert snapshot.skipped.retry_after_seconds == 41


def test_client_skips_unconfigured_providers():
    client = OddsClient()

    snapshot = client.get_live_odds(providers=["pinnacle"])

    assert len(snapshot.provider_snapshots) == 1
    assert all(item.skipped is not None for item in snapshot.provider_snapshots)
