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

## Bet365 Web Scraper Reference

`bet365_web_scraper.py` is the raw web-scraping reference path for pre-match Bet365 pages. It is useful for inspection, parser development, and saved JSON snapshots. Application code should still prefer `odds_api` / `ev_pipeline.py` for normal ingestion.

Rendered browser mode is the default and is the most useful mode when Bet365 blocks direct HTTP bootstrapping:

```bash
./venv/bin/python bet365_web_scraper.py --headed
./venv/bin/python bet365_web_scraper.py --headed --json
./venv/bin/python bet365_web_scraper.py --headed --test-mode --keep-open-seconds 60
```

Direct content-endpoint mode is available for cases where the HTTP boot flow is working:

```bash
./venv/bin/python bet365_web_scraper.py --api --json
```

### Browser Configuration

The rendered scraper can attach to an existing Chrome debugging session on `http://localhost:9222`. If that is not available, it launches Chrome or Playwright Chromium.

Useful environment variables:

```bash
BET365_USER_AGENT=...
BET365_ACCEPT_LANGUAGE=en-GB,en;q=0.9
BET365_COOKIE=...
BET365_BROWSER_USER_DATA_DIR=/path/to/chrome/profile
BET365_BROWSER_EXECUTABLE=/usr/bin/google-chrome
BET365_BROWSER_SETTLE_MS=5000
```

By default, `--browser-user-data-dir` is copied to a temporary profile before launch. Use `--use-live-browser-profile` only when the profile is not open elsewhere.

### CLI Flags

| Flag | Purpose |
| --- | --- |
| `--json` | Print structured JSON instead of text output. |
| `--api` | Use direct Bet365 content endpoints instead of rendered pages. |
| `--headed` | Show the browser in rendered mode. |
| `--no-homepage-fallback` | In API mode, skip homepage pod discovery. |
| `--include-player-props` | Include player prop markets when parsers support them. |
| `--include-prebuilt-bets` | Include Bet365 pre-built / named bet bundles. |
| `--test-mode` | Scrape detailed markets only for the first discovered match. |
| `--limit N` | Limit printed selections per match in text mode. |
| `--browser-user-data-dir PATH` | Use this Chrome profile path. |
| `--use-live-browser-profile` | Use the profile directly instead of cloning it first. |
| `--keep-open-seconds N` | Keep the last headed browser page open for inspection. |
| `--settle-ms N` | Wait this many milliseconds after navigation before extraction. |

### Discovery Rules

The scraper discovers fixtures first, then opens fixture-specific market tabs. `homepage_pods` is allowed only as a fixture discovery fallback. Prices parsed from `homepage_pods` are stripped before odds are returned, so downstream output should only contain fixture-level prices.

If direct HTTP discovery fails, rendered mode falls back to opening the upcoming soccer page in Chrome and extracting fixtures from the visible DOM.

### Rendered Market Tabs

The rendered scraper currently opens these fixture tabs:

| Source | Bet365 topic suffix | Market family |
| --- | --- | --- |
| `full_time_result_i1` | `I1` | Full Time Result / enhanced 1X2 prices |
| `cards_i4` | `I4` | Cards markets |
| `corners_i5` | `I5` | Corners markets |
| `goals_i6` | `I6` | Goals Over/Under, Alternative Total Goals, BTTS |
| `player_props_i8` | `I8` | Player score/assist, player shots, player shots on target |
| `shots_i9` | `I9` | Match/team shots and shots on target |

Known structured market names include:

| Output market | Selection examples | Line |
| --- | --- | --- |
| `Full Time Result` | home team, `Draw`, away team | `null` |
| `Full Time Result - Enhanced` | home team, `Draw`, away team | `null` |
| `Goals Over/Under 2.5` | `Over`, `Under` | `2.5` |
| `Alternative Total Goals 0.5` | `Over`, `Under` | goal line |
| `Both Teams To Score` | `Yes`, `No` | `null` |
| `Corners 10.5` / `Alternative Corners 9.5` | `Over`, `Exactly`, `Under` | corner line |
| `Corners 2-Way 10.5` | `Over`, `Under` | corner line |
| `Corners Race 5` | home team, away team, `Neither` | race target |
| `Number Of Cards In Match 4.5` | `Over`, `Under` | card line |
| `Both Teams to Receive Cards 1` | `Yes`, `No` | card threshold |
| `Match Shots 24.5` / `Match Shots On Target 8.5` | `Over`, `Under` | shot line |
| `<Team> Team Shots 11.5` | `Over`, `Under` | shot line |
| `<Team> Team Shots on Target 3.5` | `Over`, `Under` | shot-on-target line |
| `Player to Score` / `Player to Assist` / `Player Score or Assist` | player name | `null` |
| `Player Shots 1.5` / `Player Shots On Target 0.5` | player name | prop line |

### JSON Output Shape

`--json` prints:

```json
{
  "matches": [
    {
      "fixture_id": "192",
      "home": "Tottenham",
      "away": "Leeds",
      "start_time": "2026-05-11T20:00:00",
      "competition": "Premier League",
      "page_data": "#AC#B1#C1#D8#E192#F3#I1#",
      "url": "https://www.bet365.com/#/AC/B1/C1/D8/E192/F3/I6/",
      "odds": [
        {
          "id": null,
          "name": "Tottenham",
          "odds": "3/4",
          "decimal_odds": 1.75,
          "market": "Full Time Result",
          "market_code": "40",
          "line": null,
          "suspended": false
        },
        {
          "id": null,
          "name": "Over",
          "odds": "4/5",
          "decimal_odds": 1.8,
          "market": "Goals Over/Under 2.5",
          "market_code": null,
          "line": "2.5",
          "suspended": false
        }
      ]
    }
  ],
  "requests": [
    {
      "url": "https://www.bet365.com/#/AC/B1/C1/D8/E192/F3/I6/",
      "status_code": 200,
      "bytes": 12345,
      "source": "rendered_goals_i6"
    }
  ]
}
```

Text mode groups selections under market headings:

```text
Tottenham v Leeds
  fixture_id: 192
  odds_count: 8
  Full Time Result
    Tottenham: 3/4
    Draw: 29/10
    Leeds: 7/2
  Goals Over/Under 2.5
    Over: 4/5
    Under: 1/1
```

### EV Integration Status

The scraper can expose more markets than the V1 EV pipeline consumes. The current EV normalisation stage persists only:

- `1x2`: `Full Time Result` selections mapped to `home`, `draw`, `away`
- `total_goals`: goal totals mapped to `over`, `under` with a numeric line

Other scraped markets are retained for inspection/future work until matching probability outputs and normalisers are added.

## Safety Notes

The new library does not print cookies, API keys, full headers, or session IDs. Keep the raw Bet365 files out of application paths because they print raw responses/cookies and are more suitable as scraping references.
