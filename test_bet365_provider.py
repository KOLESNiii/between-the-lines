from dotenv import load_dotenv

from odds_api.providers.bet365 import (
    Bet365Provider,
    normalize_android_live_events,
    parse_inplay_records,
)


ANDROID_SAMPLE = (
    "EV;ID=abc123;BC=20260505123000|"
    "CL;NA=England - Premier League|"
    "NA;NA=Arsenal|NA;NA=Chelsea|"
    "MG;NA=Match Result|"
    "PA;NA=Home;OD=11/10|PA;NA=Draw;OD=5/2|PA;NA=Away;OD=2/1|F;"
)

DIARY_SAMPLE = (
    "EVCL=Premier LeagueCI=123NA=Futebol Ao-VivoVI=liveSM=1CN=x"
    "C1=ArsenalC2=ChelseaC3=unusedT1=2.10T2=3.40T3=3.20CR=end"
)


def parser_smoke_test() -> None:
    android_events = normalize_android_live_events(ANDROID_SAMPLE)
    print("android parser events:", len(android_events))
    for event in android_events:
        print(event.provider_event_id, event.league, event.home, "v", event.away)
        for market in event.markets:
            prices = [(outcome.name, str(outcome.price)) for outcome in market.outcomes]
            print(" ", market.market_type, market.name, prices)

    diary_records = parse_inplay_records(DIARY_SAMPLE)
    print("diary parser records:", len(diary_records))
    print(diary_records[0] if diary_records else None)


def live_smoke_test() -> None:
    load_dotenv()
    provider = Bet365Provider.from_env()
    if provider is None:
        raise SystemExit("Bet365 provider is not configured in .env")
    snapshot = provider.get_live_odds("soccer")
    print("provider:", snapshot.provider)
    print("events:", len(snapshot.events))
    print("raw:", snapshot.raw)
    for event in snapshot.events[:10]:
        print(event.provider_event_id, event.league, event.home, "v", event.away, len(event.markets))


if __name__ == "__main__":
    parser_smoke_test()
    print("--- live smoke test ---")
    live_smoke_test()
