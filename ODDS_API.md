# Live Odds API Library

Use `odds_api` as the application-facing interface for live odds. The raw Bet365 scripts remain reference code; new application code should use this package.

## Configuration

Pinnacle free/trial tier is REST-only and should be polled sparingly.

```bash
PINNACLE_API_KEY=...
PINNACLE_BASE_URL=https://pinnodds.com
PINNACLE_DAILY_REQUEST_BUDGET=80
PINNACLE_STATE_PATH=.cache/odds_api/pinnacle_state.json
```

Bet365 uses the HTTP in-play diary endpoint first. Cookies and user-agent are optional but usually needed for scraping.

```bash
BET365_INPLAY_URL=...
BET365_COOKIE=...
BET365_USER_AGENT=...
```

For the newer Android/TLS scraper path, configure the token service used to generate `X-Net-Sync-Term-Android`:

```bash
BET365_MODE=android
BET365_HOST=www.bet365.com
BET365_X_NET_API_URL=...
BET365_X_NET_API_KEY=...
BET365_PROXY=...
```

`BET365_MODE=auto` tries Android mode when the X-Net settings are present, then falls back to the diary endpoint. `BET365_MODE=diary` always uses the simple diary endpoint.

Legacy names are also accepted for compatibility:

```bash
INPLAYDIARYAPI=...
COOKIE=...
USER_AGENT=...
```

## Usage

```python
from odds_api import OddsClient

client = OddsClient.from_env()

snapshot = client.get_live_odds(
    sport="soccer",
    providers=["pinnacle", "bet365"],
)

for provider_snapshot in snapshot.provider_snapshots:
    if provider_snapshot.skipped:
        print(provider_snapshot.provider, provider_snapshot.skipped.reason)
        continue
    for event in provider_snapshot.events:
        print(provider_snapshot.provider, event.home, event.away, len(event.markets))
```

## Pinnacle Free-Tier Behavior

- Uses `GET /kit/v1/markets?sport_id=1&event_type=live` for soccer live odds.
- Sends the key as `x-portal-apikey`.
- Stores the `last` cursor and sends it back as `since`.
- Does not use SSE endpoints on free tier.
- Defaults to a local daily budget of `80` requests, below the documented `100/day` cap.
- Saves budget/cursor state in `.cache/odds_api/pinnacle_state.json`.

## Public Methods

```python
client.get_live_odds(sport="soccer", providers=None)
client.get_provider_live_odds("pinnacle", sport="soccer")
client.get_provider_live_odds("bet365", sport="soccer")
client.get_pinnacle_event_details(event_id)
client.get_pinnacle_drops(mode="live", sport="soccer", max_age_sec=600)
```

## Bet365 Test

Parser-only and live smoke test:

```bash
./venv/bin/python test_bet365_provider.py
```

Upcoming soccer / Premier League page smoke test:

```bash
./venv/bin/python test_bet365_prematch_page.py
```

The default prematch page hash is:

```text
#/AC/B1/C1/D1002/G40/J99/I1/Q1/F%5E2002/
```

The provider converts it to Bet365 protected request format:

```text
#AC#B1#C1#D1002#G40#J99#I1#Q1#F^2002#
```

Android mode requires extra packages:

```bash
./venv/bin/python -m pip install curl_cffi tls-client
```

## Safety Notes

The new library does not print cookies, API keys, full headers, or session IDs. Keep the raw Bet365 files out of application paths because they print raw responses/cookies and are more suitable as scraping references.
