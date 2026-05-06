from dotenv import load_dotenv

from odds_api.providers.bet365 import (
    DEFAULT_PREMATCH_SOCCER_PAGE_HASH,
    Bet365Provider,
    bet365_hash_to_pd,
    is_premier_league_matchup,
)


def main() -> None:
    load_dotenv(dotenv_path=".env")
    provider = Bet365Provider.from_env()
    if provider is None:
        raise SystemExit("Bet365 provider is not configured in .env")

    page_hash = DEFAULT_PREMATCH_SOCCER_PAGE_HASH
    print("page_hash:", page_hash)
    print("pd:", bet365_hash_to_pd(page_hash))

    snapshot = provider.get_premier_league_prematch_odds(page_hash=page_hash)
    print("provider:", snapshot.provider)
    print("events:", len(snapshot.events))
    print("raw:", snapshot.raw)

    for event in snapshot.events[:25]:
        print()
        print(event.provider_event_id, event.league, event.home, "v", event.away)
        print("is_pl:", is_premier_league_matchup(event.home, event.away, event.league))
        for market in event.markets[:5]:
            prices = [
                (outcome.name, str(outcome.price), outcome.side, str(outcome.points))
                for outcome in market.outcomes
            ]
            print(" ", market.market_type, market.name, prices)


if __name__ == "__main__":
    main()
