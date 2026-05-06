from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import requests

from odds_api.models import (
    LiveEvent,
    Market,
    OddsDrop,
    Outcome,
    ProviderSnapshot,
    RateLimitSkipped,
    utc_now,
)
from odds_api.rate_limits import DailyRequestBudget, JsonStateStore


SPORT_IDS = {
    "soccer": 1,
    "football": 5,
    "tennis": 2,
    "basketball": 3,
    "hockey": 4,
    "baseball": 6,
}


class PinnacleProvider:
    name = "pinnacle"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://pinnodds.com",
        daily_budget: int = 80,
        state_path: Path | None = None,
        session: requests.Session | None = None,
    ):
        if not api_key:
            raise ValueError("Pinnacle API key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.budget = DailyRequestBudget(
            JsonStateStore(state_path or Path(".cache/odds_api/pinnacle_state.json")),
            daily_budget=daily_budget,
        )

    @classmethod
    def from_env(cls) -> "PinnacleProvider | None":
        api_key = os.getenv("PINNACLE_API_KEY")
        if not api_key:
            return None
        return cls(
            api_key=api_key,
            base_url=os.getenv("PINNACLE_BASE_URL", "https://pinnodds.com"),
            daily_budget=int(os.getenv("PINNACLE_DAILY_REQUEST_BUDGET", "80")),
            state_path=Path(
                os.getenv(
                    "PINNACLE_STATE_PATH",
                    ".cache/odds_api/pinnacle_state.json",
                )
            ),
        )

    def get_live_odds(self, sport: str = "soccer") -> ProviderSnapshot:
        decision = self.budget.check()
        if not decision.allowed:
            return ProviderSnapshot(
                provider=self.name,
                fetched_at=utc_now(),
                cursor=self.budget.get_cursor(),
                skipped=RateLimitSkipped(
                    provider=self.name,
                    reason=decision.reason or "rate_limited",
                    retry_after_seconds=decision.retry_after_seconds,
                ),
            )

        params: dict[str, Any] = {
            "sport_id": self._sport_id(sport),
            "event_type": "live",
        }
        cursor = self.budget.get_cursor()
        if cursor is not None:
            params["since"] = cursor

        response = self._get("/kit/v1/markets", params=params)
        if response.status_code == 429:
            retry_after = _parse_int(response.headers.get("Retry-After"))
            self.budget.record_429(retry_after)
            return ProviderSnapshot(
                provider=self.name,
                fetched_at=utc_now(),
                cursor=cursor,
                skipped=RateLimitSkipped(
                    provider=self.name,
                    reason="remote_rate_limited",
                    retry_after_seconds=retry_after,
                ),
                raw=_safe_json(response),
            )

        response.raise_for_status()
        payload = response.json()
        next_cursor = _as_str(payload.get("last"))
        self.budget.record_success(next_cursor)
        return ProviderSnapshot(
            provider=self.name,
            fetched_at=utc_now(),
            cursor=next_cursor,
            events=[
                self._normalize_event(event, sport)
                for event in payload.get("events", [])
            ],
            raw=payload,
        )

    def get_event_details(self, event_id: str | int) -> ProviderSnapshot:
        decision = self.budget.check()
        if not decision.allowed:
            return ProviderSnapshot(
                provider=self.name,
                fetched_at=utc_now(),
                cursor=self.budget.get_cursor(),
                skipped=RateLimitSkipped(
                    provider=self.name,
                    reason=decision.reason or "rate_limited",
                    retry_after_seconds=decision.retry_after_seconds,
                ),
            )
        response = self._get("/kit/v1/details", params={"event_id": event_id})
        if response.status_code == 429:
            retry_after = _parse_int(response.headers.get("Retry-After"))
            self.budget.record_429(retry_after)
            return ProviderSnapshot(
                provider=self.name,
                fetched_at=utc_now(),
                cursor=self.budget.get_cursor(),
                skipped=RateLimitSkipped(
                    provider=self.name,
                    reason="remote_rate_limited",
                    retry_after_seconds=retry_after,
                ),
                raw=_safe_json(response),
            )
        response.raise_for_status()
        self.budget.record_success()
        payload = response.json()
        events = payload.get("events")
        if events is None:
            events = [payload] if payload else []
        return ProviderSnapshot(
            provider=self.name,
            fetched_at=utc_now(),
            events=[self._normalize_event(event, "soccer") for event in events],
            raw=payload,
        )

    def get_drops(
        self,
        mode: str = "live",
        sport: str = "soccer",
        max_age_sec: int = 600,
    ) -> list[OddsDrop]:
        decision = self.budget.check()
        if not decision.allowed:
            return []
        response = self._get(
            "/api/drops",
            params={
                "mode": mode,
                "sport_id": self._sport_id(sport),
                "max_age_sec": max_age_sec,
            },
        )
        if response.status_code == 429:
            retry_after = _parse_int(response.headers.get("Retry-After"))
            self.budget.record_429(retry_after)
            return []
        response.raise_for_status()
        self.budget.record_success()
        payload = response.json()
        return [self._normalize_drop(drop) for drop in payload.get("drops", [])]

    def _get(self, path: str, params: dict[str, Any]) -> requests.Response:
        return self.session.get(
            f"{self.base_url}{path}",
            params=params,
            headers={"x-portal-apikey": self.api_key},
            timeout=20,
        )

    def _sport_id(self, sport: str) -> int:
        key = sport.lower()
        if key not in SPORT_IDS:
            raise ValueError(f"Unsupported Pinnacle sport: {sport}")
        return SPORT_IDS[key]

    def _normalize_event(self, event: dict[str, Any], sport: str) -> LiveEvent:
        starts = _parse_datetime(event.get("starts") or event.get("start_ts"))
        return LiveEvent(
            provider=self.name,
            provider_event_id=_as_str(event.get("event_id")),
            sport=sport,
            league=event.get("league_name"),
            home=event.get("home"),
            away=event.get("away"),
            starts=starts,
            status=event.get("status") or event.get("event_type"),
            markets=self._normalize_periods(event.get("periods") or {}),
            cursor=_as_str(event.get("last")),
            raw=event,
        )

    def _normalize_periods(self, periods: dict[str, Any]) -> list[Market]:
        markets: list[Market] = []
        for period_key, period in periods.items():
            period_number = period.get("number", period_key)
            markets.extend(_moneyline_markets(period, period_number))
            markets.extend(_spread_markets(period, period_number))
            markets.extend(_total_markets(period, period_number))
            markets.extend(_team_total_markets(period, period_number))
        return markets

    def _normalize_drop(self, drop: dict[str, Any]) -> OddsDrop:
        return OddsDrop(
            provider=self.name,
            event_id=_as_str(drop.get("event_id") or drop.get("id")),
            sport=drop.get("sport_name") or drop.get("sport"),
            league=drop.get("league"),
            home=drop.get("home"),
            away=drop.get("away"),
            market=drop.get("market") or drop.get("sect"),
            period=drop.get("period"),
            side=drop.get("side") or drop.get("outcome"),
            points=_decimal(drop.get("points")),
            from_price=_decimal(drop.get("from") or drop.get("from_price")),
            to_price=_decimal(drop.get("to") or drop.get("to_price")),
            drop_pct=_decimal(drop.get("drop_pct")),
            is_live=drop.get("is_live"),
            raw=drop,
        )


def _moneyline_markets(period: dict[str, Any], period_number: str | int) -> list[Market]:
    money_line = period.get("money_line")
    if not isinstance(money_line, dict):
        return []
    outcomes = [
        Outcome(name=name, side=name, price=_decimal(price), raw={name: price})
        for name, price in money_line.items()
        if price is not None
    ]
    return [
        Market(
            market_type="moneyline",
            period=period_number,
            name="moneyline",
            outcomes=outcomes,
            raw=money_line,
        )
    ]


def _spread_markets(period: dict[str, Any], period_number: str | int) -> list[Market]:
    spreads = period.get("spreads")
    if not isinstance(spreads, dict):
        return []
    markets = []
    for key, item in spreads.items():
        if not isinstance(item, dict):
            continue
        points = _decimal(item.get("hdp", key))
        markets.append(
            Market(
                market_type="spread",
                period=period_number,
                name=f"spread {key}",
                outcomes=[
                    Outcome("home", _decimal(item.get("home")), "home", points, item),
                    Outcome("away", _decimal(item.get("away")), "away", points, item),
                ],
                raw=item,
            )
        )
    return markets


def _total_markets(period: dict[str, Any], period_number: str | int) -> list[Market]:
    totals = period.get("totals")
    if not isinstance(totals, dict):
        return []
    markets = []
    for key, item in totals.items():
        if not isinstance(item, dict):
            continue
        points = _decimal(item.get("points", key))
        markets.append(
            Market(
                market_type="total",
                period=period_number,
                name=f"total {key}",
                outcomes=[
                    Outcome("over", _decimal(item.get("over")), "over", points, item),
                    Outcome("under", _decimal(item.get("under")), "under", points, item),
                ],
                raw=item,
            )
        )
    return markets


def _team_total_markets(period: dict[str, Any], period_number: str | int) -> list[Market]:
    team_total = period.get("team_total")
    if not isinstance(team_total, dict):
        return []
    markets = []
    for side, item in team_total.items():
        if not isinstance(item, dict):
            continue
        points = _decimal(item.get("points"))
        markets.append(
            Market(
                market_type="team_total",
                period=period_number,
                name=f"team_total {side}",
                outcomes=[
                    Outcome("over", _decimal(item.get("over")), side, points, item),
                    Outcome("under", _decimal(item.get("under")), side, points, item),
                ],
                raw=item,
            )
        )
    return markets


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _safe_json(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
        return payload if isinstance(payload, dict) else {"payload": payload}
    except ValueError:
        return {}
