from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    reason: str | None = None
    retry_after_seconds: int | None = None


class JsonStateStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True))
        tmp_path.replace(self.path)


class DailyRequestBudget:
    def __init__(self, store: JsonStateStore, daily_budget: int):
        self.store = store
        self.daily_budget = daily_budget

    def today_key(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def check(self) -> RateLimitDecision:
        state = self._current_state()
        retry_until = state.get("last_429_retry_until")
        if retry_until:
            retry_at = datetime.fromisoformat(retry_until)
            now = datetime.now(timezone.utc)
            if now < retry_at:
                return RateLimitDecision(
                    allowed=False,
                    reason="retry_after_active",
                    retry_after_seconds=max(0, int((retry_at - now).total_seconds())),
                )

        if state["requests_today_utc"] >= self.daily_budget:
            return RateLimitDecision(allowed=False, reason="daily_budget_exhausted")
        return RateLimitDecision(allowed=True)

    def record_success(self, cursor: str | None = None) -> None:
        state = self._current_state()
        state["requests_today_utc"] += 1
        if cursor is not None:
            state["last_cursor"] = str(cursor)
        self.store.save(state)

    def record_429(self, retry_after_seconds: int | None) -> None:
        state = self._current_state()
        state["requests_today_utc"] += 1
        state["last_429_retry_after"] = retry_after_seconds
        if retry_after_seconds is not None:
            retry_until = datetime.now(timezone.utc).timestamp() + retry_after_seconds
            state["last_429_retry_until"] = datetime.fromtimestamp(
                retry_until, tz=timezone.utc
            ).isoformat()
        self.store.save(state)

    def get_cursor(self) -> str | None:
        return self._current_state().get("last_cursor")

    def _current_state(self) -> dict[str, Any]:
        today = self.today_key()
        state = self.store.load()
        if state.get("day_utc") != today:
            state = {
                "day_utc": today,
                "requests_today_utc": 0,
                "last_cursor": state.get("last_cursor"),
                "last_429_retry_after": None,
                "last_429_retry_until": None,
            }
        state.setdefault("requests_today_utc", 0)
        state.setdefault("day_utc", today)
        return state
