from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from odds_api import OddsClient
from odds_api.models import utc_now
from probabilistic_markets import DEFAULT_DB_URL


DEFAULT_SCHEMA_PATH = Path("schemas/probabilistic_markets.sql")
DEFAULT_EV_THRESHOLD = Decimal("0.02")
SUPPORTED_MARKET_TYPES = {"moneyline", "total"}


@dataclass(frozen=True)
class NormalizedOddsPrice:
    provider: str
    provider_event_id: str | None
    sport: str | None
    league: str | None
    home_team_name: str | None
    away_team_name: str | None
    starts: datetime | None
    odds_fetched_at: datetime
    market_type: str
    market_key: str
    selection: str
    line: Decimal | None
    decimal_odds: Decimal
    raw: dict[str, Any]


@dataclass(frozen=True)
class MatchReference:
    match_id: int
    match_date: date | None
    home_team_name: str
    away_team_name: str


@dataclass(frozen=True)
class EVResult:
    implied_probability: Decimal
    edge: Decimal
    expected_value: Decimal


def create_schema(db_url: str, schema_path: Path = DEFAULT_SCHEMA_PATH) -> None:
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit(
            "Missing database dependency. Install requirements first: "
            "python3 -m pip install -r requirements.txt"
        ) from exc
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_path.read_text(encoding="utf-8"))
        conn.commit()


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def valid_decimal_odds(value: Any) -> Decimal | None:
    decimal = decimal_or_none(value)
    if decimal is None or decimal <= Decimal("1"):
        return None
    return decimal


def calculate_ev(model_probability: Any, decimal_odds: Any) -> EVResult | None:
    probability = decimal_or_none(model_probability)
    odds = valid_decimal_odds(decimal_odds)
    if probability is None or odds is None:
        return None
    if probability < 0 or probability > 1:
        return None
    implied_probability = Decimal("1") / odds
    return EVResult(
        implied_probability=implied_probability,
        edge=probability - implied_probability,
        expected_value=(probability * odds) - Decimal("1"),
    )


def normalize_name(value: str | None) -> str:
    if value is None:
        return ""
    text = value.lower().replace("&", " and ")
    text = re.sub(r"\b(fc|afc|cf|football club)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def attr(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def parse_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        parsed = parse_datetime(value)
        return parsed.date() if parsed else None


def whole_match_period(period: Any) -> bool:
    return period in (None, 0, "0", "num_0")


def normalize_market_outcome(
    event: Any,
    market: Any,
    outcome: Any,
    fetched_at: datetime,
) -> NormalizedOddsPrice | None:
    market_type = attr(market, "market_type")
    if market_type not in SUPPORTED_MARKET_TYPES:
        return None
    if not whole_match_period(attr(market, "period")):
        return None

    odds = valid_decimal_odds(attr(outcome, "price"))
    if odds is None:
        return None

    side = attr(outcome, "side") or attr(outcome, "name")
    selection = str(side).lower() if side is not None else ""
    line = attr(outcome, "points")
    market_key = ""

    if market_type == "moneyline":
        if selection not in {"home", "draw", "away"}:
            return None
        market_key = "1x2"
        line = None
    elif market_type == "total":
        if selection not in {"over", "under"}:
            return None
        market_key = "total_goals"
        line = decimal_or_none(line)
        if line is None:
            return None

    return NormalizedOddsPrice(
        provider=str(attr(event, "provider")),
        provider_event_id=attr(event, "provider_event_id"),
        sport=attr(event, "sport"),
        league=attr(event, "league"),
        home_team_name=attr(event, "home"),
        away_team_name=attr(event, "away"),
        starts=parse_datetime(attr(event, "starts")),
        odds_fetched_at=fetched_at,
        market_type=str(market_type),
        market_key=market_key,
        selection=selection,
        line=line,
        decimal_odds=odds,
        raw={
            "event": jsonable(event),
            "market": jsonable(market),
            "outcome": jsonable(outcome),
        },
    )


def normalize_snapshot(snapshot: Any) -> list[NormalizedOddsPrice]:
    prices: list[NormalizedOddsPrice] = []
    snapshot_fetched_at = parse_datetime(attr(snapshot, "fetched_at")) or utc_now()
    for provider_snapshot in attr(snapshot, "provider_snapshots", []):
        if attr(provider_snapshot, "skipped") is not None:
            continue
        fetched_at = parse_datetime(attr(provider_snapshot, "fetched_at")) or snapshot_fetched_at
        for event in attr(provider_snapshot, "events", []):
            for market in attr(event, "markets", []):
                for outcome in attr(market, "outcomes", []):
                    price = normalize_market_outcome(event, market, outcome, fetched_at)
                    if price is not None:
                        prices.append(price)
    return prices


def jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def read_snapshot_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "provider_snapshots" not in payload:
        raise SystemExit(f"Snapshot JSON must contain provider_snapshots: {path}")
    return payload


def explicit_mapping_key(provider: str, provider_event_id: str | None) -> tuple[str, str] | None:
    if provider_event_id is None:
        return None
    return (provider, provider_event_id)


def match_odds_price(
    price: NormalizedOddsPrice,
    explicit_mappings: dict[tuple[str, str], int],
    match_refs: Iterable[MatchReference],
) -> int | None:
    mapping_key = explicit_mapping_key(price.provider, price.provider_event_id)
    if mapping_key in explicit_mappings:
        return explicit_mappings[mapping_key]

    price_date = price.starts.date() if price.starts else None
    home = normalize_name(price.home_team_name)
    away = normalize_name(price.away_team_name)
    if price_date is None or not home or not away:
        return None

    for match in match_refs:
        if match.match_date != price_date:
            continue
        if (
            normalize_name(match.home_team_name) == home
            and normalize_name(match.away_team_name) == away
        ):
            return match.match_id
    return None


def load_latest_probability_run_id(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM model_outputs.market_probability_runs
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    if row is None:
        raise SystemExit("No market probability runs found")
    return int(row[0])


def load_latest_snapshot_id(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM model_outputs.odds_snapshots
            ORDER BY fetched_at DESC, id DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    if row is None:
        raise SystemExit("No odds snapshots found")
    return int(row[0])


def load_explicit_mappings(conn) -> dict[tuple[str, str], int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT provider, provider_event_id, match_id
            FROM model_outputs.bookmaker_event_mappings
            """
        )
        return {
            (str(provider), str(provider_event_id)): int(match_id)
            for provider, provider_event_id, match_id in cur.fetchall()
        }


def load_match_refs(conn, probability_run_id: int) -> list[MatchReference]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT match_id, match_date, home_team_name, away_team_name
            FROM model_outputs.match_probability_inputs
            WHERE run_id = %s
            """,
            (probability_run_id,),
        )
        return [
            MatchReference(
                match_id=int(match_id),
                match_date=parse_date(match_date),
                home_team_name=str(home),
                away_team_name=str(away),
            )
            for match_id, match_date, home, away in cur.fetchall()
        ]


def persist_snapshot(
    conn,
    snapshot: Any,
    source: str,
    probability_run_id: int,
) -> tuple[int, int, int]:
    try:
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise SystemExit(
            "Missing database dependency. Install requirements first: "
            "python3 -m pip install -r requirements.txt"
        ) from exc

    prices = normalize_snapshot(snapshot)
    snapshot_fetched_at = parse_datetime(attr(snapshot, "fetched_at")) or utc_now()
    explicit_mappings = load_explicit_mappings(conn)
    match_refs = load_match_refs(conn, probability_run_id)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO model_outputs.odds_snapshots (fetched_at, source, raw)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (snapshot_fetched_at, source, Jsonb(jsonable(snapshot))),
        )
        snapshot_id = int(cur.fetchone()[0])

        matched = 0
        for price in prices:
            match_id = match_odds_price(price, explicit_mappings, match_refs)
            if match_id is not None:
                matched += 1
            cur.execute(
                """
                INSERT INTO model_outputs.odds_prices (
                    snapshot_id, provider, provider_event_id, sport, league,
                    home_team_name, away_team_name, starts, odds_fetched_at,
                    market_type, market_key, selection, line, decimal_odds,
                    matched_match_id, raw
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    snapshot_id,
                    price.provider,
                    price.provider_event_id,
                    price.sport,
                    price.league,
                    price.home_team_name,
                    price.away_team_name,
                    price.starts,
                    price.odds_fetched_at,
                    price.market_type,
                    price.market_key,
                    price.selection,
                    price.line,
                    price.decimal_odds,
                    match_id,
                    Jsonb(price.raw),
                ),
            )
    return snapshot_id, len(prices), matched


def write_ev_candidates(
    conn,
    snapshot_id: int,
    probability_run_id: int,
    threshold: Decimal = DEFAULT_EV_THRESHOLD,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM model_outputs.ev_candidates
            WHERE snapshot_id = %s AND probability_run_id = %s
            """,
            (snapshot_id, probability_run_id),
        )
        cur.execute(
            """
            INSERT INTO model_outputs.ev_candidates (
                snapshot_id, odds_price_id, probability_run_id, match_id,
                provider, provider_event_id, market_key, selection, line,
                model_probability, decimal_odds, implied_probability, edge,
                expected_value, threshold, source_odds_fetched_at
            )
            SELECT
                op.snapshot_id,
                op.id,
                mp.run_id,
                op.matched_match_id,
                op.provider,
                op.provider_event_id,
                op.market_key,
                op.selection,
                op.line,
                mp.probability,
                op.decimal_odds,
                (1.0 / op.decimal_odds),
                (mp.probability - (1.0 / op.decimal_odds)),
                ((mp.probability * op.decimal_odds) - 1.0),
                %s,
                op.odds_fetched_at
            FROM model_outputs.odds_prices op
            JOIN model_outputs.market_probabilities mp
              ON mp.run_id = %s
             AND mp.match_id = op.matched_match_id
             AND mp.market_key = op.market_key
             AND mp.selection = op.selection
             AND mp.line IS NOT DISTINCT FROM op.line
            WHERE op.snapshot_id = %s
              AND op.matched_match_id IS NOT NULL
              AND op.decimal_odds > 1
              AND ((mp.probability * op.decimal_odds) - 1.0) >= %s
            """,
            (threshold, probability_run_id, snapshot_id, threshold),
        )
        return int(cur.rowcount)


def fetch_live_snapshot(sport: str, providers: str | None):
    selected = [item.strip() for item in providers.split(",")] if providers else None
    client = OddsClient.from_env()
    return client.get_live_odds(sport=sport, providers=selected)


def run_fetch_live(args) -> dict[str, Any]:
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit(
            "Missing database dependency. Install requirements first: "
            "python3 -m pip install -r requirements.txt"
        ) from exc

    snapshot = fetch_live_snapshot(args.sport, args.providers)
    with psycopg.connect(args.db_url) as conn:
        probability_run_id = args.probability_run_id or load_latest_probability_run_id(conn)
        snapshot_id, prices, matched = persist_snapshot(
            conn,
            snapshot,
            source="fetch-live",
            probability_run_id=probability_run_id,
        )
        candidates = write_ev_candidates(
            conn,
            snapshot_id=snapshot_id,
            probability_run_id=probability_run_id,
            threshold=args.ev_threshold,
        )
        conn.commit()
    return {
        "snapshot_id": snapshot_id,
        "probability_run_id": probability_run_id,
        "prices": prices,
        "matched_prices": matched,
        "ev_candidates": candidates,
    }


def run_from_json(args) -> dict[str, Any]:
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit(
            "Missing database dependency. Install requirements first: "
            "python3 -m pip install -r requirements.txt"
        ) from exc

    snapshot = read_snapshot_json(args.path)
    with psycopg.connect(args.db_url) as conn:
        probability_run_id = args.probability_run_id or load_latest_probability_run_id(conn)
        snapshot_id, prices, matched = persist_snapshot(
            conn,
            snapshot,
            source=str(args.path),
            probability_run_id=probability_run_id,
        )
        candidates = write_ev_candidates(
            conn,
            snapshot_id=snapshot_id,
            probability_run_id=probability_run_id,
            threshold=args.ev_threshold,
        )
        conn.commit()
    return {
        "snapshot_id": snapshot_id,
        "probability_run_id": probability_run_id,
        "prices": prices,
        "matched_prices": matched,
        "ev_candidates": candidates,
    }


def run_candidates(args) -> dict[str, Any]:
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit(
            "Missing database dependency. Install requirements first: "
            "python3 -m pip install -r requirements.txt"
        ) from exc

    with psycopg.connect(args.db_url) as conn:
        probability_run_id = args.probability_run_id or load_latest_probability_run_id(conn)
        snapshot_id = args.snapshot_id or load_latest_snapshot_id(conn)
        candidates = write_ev_candidates(
            conn,
            snapshot_id=snapshot_id,
            probability_run_id=probability_run_id,
            threshold=args.ev_threshold,
        )
        conn.commit()
    return {
        "snapshot_id": snapshot_id,
        "probability_run_id": probability_run_id,
        "ev_candidates": candidates,
    }


def parse_decimal_arg(value: str) -> Decimal:
    parsed = decimal_or_none(value)
    if parsed is None:
        raise argparse.ArgumentTypeError(f"Invalid decimal value: {value}")
    return parsed


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Persist bookmaker odds and generate EV candidates from model probabilities."
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DB_URL", DEFAULT_DB_URL),
        help="Postgres connection URL. Defaults to DB_URL or the local docker DB.",
    )
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="Create model_outputs EV tables before running the command.",
    )
    parser.add_argument(
        "--ev-threshold",
        type=parse_decimal_arg,
        default=DEFAULT_EV_THRESHOLD,
        help="Minimum expected value required for persisted candidates.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser("fetch-live", help="Fetch live odds and score EV.")
    fetch_parser.add_argument("--sport", default="soccer")
    fetch_parser.add_argument("--providers", help="Comma-separated provider list.")
    fetch_parser.add_argument("--probability-run-id", type=int)

    json_parser = subparsers.add_parser("from-json", help="Load an odds snapshot JSON file.")
    json_parser.add_argument("path", type=Path)
    json_parser.add_argument("--probability-run-id", type=int)

    candidate_parser = subparsers.add_parser(
        "candidates",
        help="Rebuild EV candidates for an existing odds snapshot.",
    )
    candidate_parser.add_argument("--snapshot-id", type=int)
    candidate_parser.add_argument("--probability-run-id", type=int)

    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.create_schema:
        create_schema(args.db_url)

    if args.command == "fetch-live":
        result = run_fetch_live(args)
    elif args.command == "from-json":
        result = run_from_json(args)
    elif args.command == "candidates":
        result = run_candidates(args)
    else:
        raise SystemExit(f"Unsupported command: {args.command}")
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
