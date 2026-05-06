from __future__ import annotations

from typing import Iterable

from odds_api.models import LiveOddsSnapshot, ProviderSnapshot, RateLimitSkipped, utc_now
from odds_api.providers.pinnacle import PinnacleProvider


class OddsClient:
    def __init__(
        self,
        pinnacle: PinnacleProvider | None = None,
    ):
        self.providers = {
            "pinnacle": pinnacle,
        }

    @classmethod
    def from_env(cls) -> "OddsClient":
        return cls(
            pinnacle=PinnacleProvider.from_env(),
        )

    def get_live_odds(
        self,
        sport: str = "soccer",
        providers: Iterable[str] | None = None,
    ) -> LiveOddsSnapshot:
        selected = list(providers or self.providers.keys())
        snapshots = [
            self.get_provider_live_odds(provider, sport=sport)
            for provider in selected
        ]
        return LiveOddsSnapshot(fetched_at=utc_now(), provider_snapshots=snapshots)

    def get_provider_live_odds(self, provider: str, sport: str = "soccer") -> ProviderSnapshot:
        if provider not in self.providers:
            raise ValueError(f"Unsupported provider: {provider}")
        instance = self.providers[provider]
        if instance is None:
            return ProviderSnapshot(
                provider=provider,  # type: ignore[arg-type]
                fetched_at=utc_now(),
                skipped=RateLimitSkipped(
                    provider=provider,  # type: ignore[arg-type]
                    reason="provider_not_configured",
                ),
            )
        return instance.get_live_odds(sport=sport)

    def get_pinnacle_event_details(self, event_id: str | int) -> ProviderSnapshot:
        pinnacle = self.providers["pinnacle"]
        if pinnacle is None:
            return ProviderSnapshot(
                provider="pinnacle",
                fetched_at=utc_now(),
                skipped=RateLimitSkipped(
                    provider="pinnacle",
                    reason="provider_not_configured",
                ),
            )
        return pinnacle.get_event_details(event_id)

    def get_pinnacle_drops(
        self,
        mode: str = "live",
        sport: str = "soccer",
        max_age_sec: int = 600,
    ):
        pinnacle = self.providers["pinnacle"]
        if pinnacle is None:
            return []
        return pinnacle.get_drops(mode=mode, sport=sport, max_age_sec=max_age_sec)
