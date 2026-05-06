from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal


ProviderName = Literal["pinnacle", "bet365"]
MarketType = Literal["moneyline", "spread", "total", "team_total", "unknown"]


@dataclass(frozen=True)
class Outcome:
    name: str
    price: Decimal | None
    side: str | None = None
    points: Decimal | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Market:
    market_type: MarketType
    period: str | int | None
    name: str
    outcomes: list[Outcome] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LiveEvent:
    provider: ProviderName
    provider_event_id: str | None
    sport: str
    league: str | None
    home: str | None
    away: str | None
    starts: datetime | None
    status: str | None
    markets: list[Market] = field(default_factory=list)
    cursor: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RateLimitSkipped:
    provider: ProviderName
    reason: str
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class ProviderSnapshot:
    provider: ProviderName
    fetched_at: datetime
    cursor: str | None = None
    events: list[LiveEvent] = field(default_factory=list)
    skipped: RateLimitSkipped | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LiveOddsSnapshot:
    fetched_at: datetime
    provider_snapshots: list[ProviderSnapshot] = field(default_factory=list)


@dataclass(frozen=True)
class OddsDrop:
    provider: ProviderName
    event_id: str | None
    sport: str | None
    league: str | None
    home: str | None
    away: str | None
    market: str | None
    period: str | int | None
    side: str | None
    points: Decimal | None
    from_price: Decimal | None
    to_price: Decimal | None
    drop_pct: Decimal | None
    is_live: bool | None
    raw: dict[str, Any] = field(default_factory=dict)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
