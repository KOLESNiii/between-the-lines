"""Fresh Bet365 web scraper prototype.

This module intentionally does not import or reuse the existing Bet365 provider
code in this repository. It uses the public web boot flow:

1. GET the sportsbook shell to receive locale/country cookies.
2. GET sports-configuration to receive flashvars needed by content APIs.
3. GET website routing rules to map Bet365 page-data topics to endpoints.
4. Fetch target content endpoints and parse Bet365's compact text wire format.

Bet365 can return an empty body for some content endpoints depending on cookies,
region, page topic, and Cloudflare routing. The homepage pod endpoint has been
the most reliable source during inspection, so the CLI uses it as a fallback.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from fractions import Fraction
from typing import Any, Iterable
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

import requests


BET365_URL = "https://www.bet365.com/"
UPCOMING_SOCCER_HASH = "#/AC/B1/C1/D1002/E91422157/G40/"
UPCOMING_SOCCER_TOPIC = "#AC#B1#C1#D1002#E91422157#G40#"
DEFAULT_DIRECT_DISCOVERY_TOPICS = (UPCOMING_SOCCER_TOPIC,)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# 2025/26 Premier League teams. Keep this configurable in production because
# promoted/relegated teams change every season.
DEFAULT_PREMIER_LEAGUE_TEAMS = {
    "arsenal",
    "aston villa",
    "bournemouth",
    "brentford",
    "brighton",
    "brighton and hove albion",
    "burnley",
    "chelsea",
    "crystal palace",
    "everton",
    "fulham",
    "leeds",
    "leeds united",
    "liverpool",
    "manchester city",
    "man city",
    "manchester united",
    "man utd",
    "newcastle",
    "newcastle united",
    "nottingham forest",
    "sunderland",
    "tottenham",
    "tottenham hotspur",
    "west ham",
    "west ham united",
    "wolves",
    "wolverhampton",
    "wolverhampton wanderers",
}

MARKET_CODE_NAMES = {
    "40": "Full Time Result",
    "64": "To Score",
    "1175": "Most Corners",
    "10150": "Both Teams to Score",
    "10878": "Team Goals",
    "10889": "Team Corners - 1st Half",
    "10890": "Team Corners - 2nd Half",
    "10893": "Team Corners - 1st Half",
    "10894": "Team Corners - 2nd Half",
    "50134": "To be Booked",
    "50538": "Player Shots on Target",
    "50539": "Player Shots",
    "50540": "Player Tackles",
    "50920": "Player Shots on Target",
    "50921": "Player Shots",
    "50922": "Player Tackles",
    "177702": "Player Fouls",
    "177704": "Score or Assist",
    "177717": "Team Shots on Target - 1st Half",
    "177718": "Team Shots on Target - 2nd Half",
    "177719": "Team Shots on Target - 1st Half",
    "177720": "Team Shots on Target - 2nd Half",
    "177759": "Player Fouls",
    "177788": "Most Cards",
    "177791": "Most Shots on Target",
}
MAIN_MARKET_CODES = {
    "40",
    "5031",
    "5035",
    "5039",
    "1175",
    "10150",
    "10878",
    "10889",
    "10890",
    "10893",
    "10894",
    "177717",
    "177718",
    "177719",
    "177720",
    "177788",
    "177791",
}
PLAYER_TABLE_MARKET_CODES = {
    "50538",
    "50539",
    "50540",
    "50920",
    "50921",
    "50922",
    "177702",
    "177759",
}
ODDS_LINE_RE = re.compile(r"^(?:\d{1,4}/\d{1,4}|\d+\.\d+)$")
LINE_VALUE_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
PLAYER_RENDERED_MARKET_TERMS = {
    "player",
}
PREBUILT_RENDERED_MARKET_TERMS = {
    "bet builder",
    "boost",
    "request a bet",
    "featured",
    "popular",
    "special",
    "enhanced",
}
SKIPPED_RENDERED_MARKET_TERMS = PLAYER_RENDERED_MARKET_TERMS | PREBUILT_RENDERED_MARKET_TERMS


def console_log(message: str) -> None:
    print(message, flush=True)


def topic_with_trailing_hash(topic: str) -> str:
    return topic if topic.endswith("#") else topic + "#"


def direct_discovery_topics() -> tuple[str, ...]:
    configured = os.getenv("BET365_DISCOVERY_TOPICS")
    if not configured:
        return DEFAULT_DIRECT_DISCOVERY_TOPICS
    topics = [
        topic
        for item in re.split(r"[,\s]+", configured)
        if (topic := discovery_topic_from_item(item.strip()))
    ]
    return tuple(topics) or DEFAULT_DIRECT_DISCOVERY_TOPICS


def discovery_topic_from_item(item: str) -> str | None:
    if not item:
        return None
    parts = urlsplit(item)
    if parts.scheme and parts.netloc:
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        item = query.get("pd", item)
    return topic_with_trailing_hash(item)


@dataclass
class Selection:
    id: str | None
    name: str
    odds: str
    decimal_odds: float | None = None
    market: str | None = None
    market_code: str | None = None
    line: str | None = None
    suspended: bool = False


@dataclass
class Match:
    fixture_id: str
    home: str
    away: str
    start_time: str | None = None
    competition: str | None = None
    page_data: str | None = None
    url: str | None = None
    odds: list[Selection] = field(default_factory=list)


@dataclass
class EndpointResult:
    url: str
    status_code: int
    bytes: int
    body: str
    source: str = "topic"


@dataclass
class HttpResponse:
    url: str
    status_code: int
    text: str

    @property
    def content(self) -> bytes:
        return self.text.encode("utf-8")

    def json(self) -> Any:
        try:
            return json.loads(self.text)
        except json.JSONDecodeError as exc:
            preview = re.sub(r"\s+", " ", self.text[:300]).strip()
            raise RuntimeError(
                f"Expected JSON from {self.url}, got {len(self.text)} bytes: {preview!r}"
            ) from exc

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} response for {self.url}")


def normalize_team(value: str) -> str:
    value = value.lower().replace("&", " and ")
    value = re.sub(r"\b(fc|afc|cf|the)\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def fractional_to_decimal(value: str) -> float | None:
    try:
        if "/" in value:
            frac = Fraction(value)
            return round(float(frac + 1), 6)
        return round(float(value), 6)
    except Exception:
        return None


def parse_bet365_datetime(value: str | None) -> str | None:
    if not value or not re.fullmatch(r"\d{14}", value):
        return value
    return datetime.strptime(value, "%Y%m%d%H%M%S").isoformat()


def parse_fields(segment: str) -> tuple[str, dict[str, str]]:
    parts = segment.split(";")
    node_type = parts[0]
    fields: dict[str, str] = {}
    for part in parts[1:]:
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        fields[key] = unquote(value)
    return node_type, fields


def iter_nodes(payload: str) -> Iterable[tuple[str, dict[str, str]]]:
    for frame in payload.split("\x08"):
        for segment in frame.split("|"):
            if not segment or segment in {"F", "U", "D", "I"}:
                continue
            yield parse_fields(segment)


def market_name_for_code(code: str | None, fallback: str | None = None) -> str | None:
    if code and code in MARKET_CODE_NAMES:
        return MARKET_CODE_NAMES[code]
    return fallback


def infer_market_name(selection_name: str, market_code: str | None = None, fallback: str | None = None) -> str | None:
    if market_code and market_code in MARKET_CODE_NAMES:
        return MARKET_CODE_NAMES[market_code]
    value = selection_name.strip()
    if value.startswith("FT Result:"):
        return "Full Time Result"
    if "Shots on Target" in value:
        return "Player Shots on Target" if ":" in value else "Shots on Target"
    if value.startswith("Both Teams to Score"):
        return "Both Teams to Score"
    if value.startswith("Most Corners"):
        return "Most Corners"
    if value.startswith("Most Cards"):
        return "Most Cards"
    if value.startswith("Most Shots on Target"):
        return "Most Shots on Target"
    if " to Assist" in value:
        return "To Assist"
    if " to Score" in value:
        return "To Score"
    return fallback


def clean_selection_name(selection_name: str, match: Match | None = None) -> str:
    value = re.sub(r"\s+", " ", selection_name).strip()
    if value.startswith("FT Result:"):
        return value.partition(":")[2].strip() or value
    if ":" in value:
        market_prefix, _, selection = value.partition(":")
        if market_prefix in {"Most Corners", "Most Cards", "Most Shots on Target"}:
            return selection.strip() or value
    if value == "Both Teams to Score":
        return "Yes"
    if match and value == "1":
        return match.home
    if match and value == "X":
        return "Draw"
    if match and value == "2":
        return match.away
    if value.lower().startswith("over ") or value.lower().startswith("under "):
        return value
    return value


def clean_rendered_market_name(market_name: str | None, line: str | None = None) -> str | None:
    value = re.sub(r"\s+", " ", market_name or "").strip()
    value = re.sub(r"\bBB\b", " ", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" -:")
    if line and value and line not in value:
        value = f"{value} {line}"
    return value or None


def fixture_market_topics(match: Match, start: int = 4, stop: int = 9) -> list[tuple[str, str]]:
    return [
        (f"fixture_f{market_index}", f"#AC#B1#C1#D8#E{match.fixture_id}#F3#F{market_index}#")
        for market_index in range(start, stop + 1)
    ]


def fixture_rendered_tab_topics(match: Match, start: int = 4, stop: int = 9) -> list[tuple[str, str]]:
    return [
        (f"fixture_i{tab_index}", f"#AC#B1#C1#D8#E{match.fixture_id}#F3#I{tab_index}#")
        for tab_index in range(start, stop + 1)
    ]


def fixture_rendered_market_topics(match: Match) -> list[tuple[str, str]]:
    return [
        ("full_time_result_i1", f"#AC#B1#C1#D8#E{match.fixture_id}#F3#I1#"),
        ("cards_i4", f"#AC#B1#C1#D8#E{match.fixture_id}#F3#I4#"),
        ("corners_i5", f"#AC#B1#C1#D8#E{match.fixture_id}#F3#I5#"),
        ("goals_i6", f"#AC#B1#C1#D8#E{match.fixture_id}#F3#I6#"),
        ("player_props_i8", f"#AC#B1#C1#D8#E{match.fixture_id}#F3#I8#"),
        ("shots_i9", f"#AC#B1#C1#D8#E{match.fixture_id}#F3#I9#"),
    ]


def fixture_id_from(data: dict[str, str]) -> str | None:
    value = data.get("FI") or data.get("PF") or data.get("OI")
    if not value or value == "0":
        return None
    return value


def parse_visible_odds_text(
    text: str,
    match: Match,
    *,
    include_player_props: bool = False,
    include_prebuilt_bets: bool = False,
) -> list[Selection]:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    selections: list[Selection] = []
    seen: set[tuple[str | None, str, str]] = set()
    market: str | None = None
    recent_labels: list[str] = []

    def is_skipped(value: str | None) -> bool:
        lowered = (value or "").lower()
        if not include_player_props and any(term in lowered for term in PLAYER_RENDERED_MARKET_TERMS):
            return True
        if not include_prebuilt_bets and any(term in lowered for term in PREBUILT_RENDERED_MARKET_TERMS):
            return True
        return False

    for line in lines:
        if ODDS_LINE_RE.fullmatch(line):
            if not recent_labels:
                continue
            name = recent_labels[-1]
            if not include_player_props and is_skipped(market):
                continue
            if not include_player_props and is_skipped(name):
                continue
            selection = Selection(
                id=None,
                name=clean_selection_name(name, match),
                odds=line,
                decimal_odds=fractional_to_decimal(line),
                market=market,
            )
            key = (selection.market, selection.name, selection.odds)
            if key not in seen:
                seen.add(key)
                selections.append(selection)
            continue

        if is_skipped(line):
            market = line
            recent_labels.clear()
            continue

        if len(line) <= 80 and not ODDS_LINE_RE.search(line):
            if line in {"1", "X", "2"}:
                recent_labels.append(line)
                recent_labels = recent_labels[-4:]
                continue
            if re.search(r"\b(result|goals?|corners?|cards?|half|handicap|score|teams?|draw)\b", line, re.I):
                market = line
                recent_labels.clear()
                continue

        if len(line) <= 120 and not is_skipped(line):
            recent_labels.append(line)
            recent_labels = recent_labels[-4:]

    return selections


def parse_bet365_market_group_dom_items(items: Iterable[dict[str, str]], match: Match) -> list[Selection]:
    selections: list[Selection] = []
    seen: set[tuple[str | None, str, str]] = set()
    for item in items:
        market = clean_rendered_market_name(item.get("market") or None)
        name = item.get("name") or ""
        odds = item.get("odds") or ""
        line = item.get("line") or None
        context = item.get("context") or ""
        if name.upper() == "BB" or LINE_VALUE_RE.fullmatch(name):
            name = ""
        if context and context.upper() == "BB":
            context = ""
        if not name or not ODDS_LINE_RE.fullmatch(odds):
            continue
        if line and name.lower() in {"over", "under", "exactly"}:
            market = clean_rendered_market_name(market, line)
        elif line and line not in name and not LINE_VALUE_RE.fullmatch(name):
            name = f"{name} {line}"
        if context and context not in name and name.lower() in {"yes", "no"}:
            name = f"{context}: {name}"
        selection = Selection(
            id=None,
            name=clean_selection_name(name, match),
            odds=odds,
            decimal_odds=fractional_to_decimal(odds),
            market=market,
            line=line,
        )
        key = (selection.market, selection.name, selection.odds)
        if key in seen:
            continue
        seen.add(key)
        selections.append(selection)
    return selections


def parse_full_time_result_dom_items(items: Iterable[dict[str, str]], match: Match) -> list[Selection]:
    selections: list[Selection] = []
    seen: set[tuple[str, str, str]] = set()
    normalized_home = normalize_team(match.home)
    normalized_away = normalize_team(match.away)
    for item in items:
        market = item.get("market") if item.get("market") in {"Full Time Result", "Full Time Result - Enhanced"} else "Full Time Result"
        name = re.sub(r"\s+", " ", item.get("name") or "").strip()
        odds = re.sub(r"\s+", " ", item.get("odds") or "").strip()
        normalized_name = normalize_team(name)
        if normalized_name == normalized_home:
            selection_name = match.home
        elif name.lower() == "draw":
            selection_name = "Draw"
        elif normalized_name == normalized_away:
            selection_name = match.away
        else:
            continue
        if not ODDS_LINE_RE.fullmatch(odds):
            continue
        key = (market, selection_name, odds)
        if key in seen:
            continue
        seen.add(key)
        selections.append(
            Selection(
                id=None,
                name=selection_name,
                odds=odds,
                decimal_odds=fractional_to_decimal(odds),
                market=market,
                market_code="40",
            )
        )
    return selections


def parse_goals_dom_items(items: Iterable[dict[str, str]], match: Match) -> list[Selection]:
    selections: list[Selection] = []
    seen: set[tuple[str | None, str, str, str | None]] = set()
    allowed_markets = {
        "Goals Over/Under",
        "Alternative Total Goals",
        "Both Teams To Score",
        "Teams to Score",
    }
    for item in items:
        raw_market = re.sub(r"\s+", " ", item.get("market") or "").strip()
        name = re.sub(r"\s+", " ", item.get("name") or "").strip()
        odds = re.sub(r"\s+", " ", item.get("odds") or "").strip()
        line = re.sub(r"\s+", " ", item.get("line") or "").strip() or None
        if raw_market not in allowed_markets or not name or not ODDS_LINE_RE.fullmatch(odds):
            continue

        market = raw_market
        market_code = None
        if raw_market in {"Goals Over/Under", "Alternative Total Goals"}:
            if name.lower() not in {"over", "under"} or not line or not LINE_VALUE_RE.fullmatch(line):
                continue
            market = f"{raw_market} {line}"
        elif raw_market == "Both Teams To Score":
            if name.lower() not in {"yes", "no"}:
                continue
            market_code = "10150"

        selection = Selection(
            id=None,
            name=name,
            odds=odds,
            decimal_odds=fractional_to_decimal(odds),
            market=market,
            market_code=market_code,
            line=line,
        )
        key = (selection.market, selection.name, selection.odds, selection.line)
        if key in seen:
            continue
        seen.add(key)
        selections.append(selection)
    return selections


def parse_corners_dom_items(items: Iterable[dict[str, str]], match: Match) -> list[Selection]:
    selections: list[Selection] = []
    seen: set[tuple[str | None, str, str, str | None]] = set()
    allowed_markets = {
        "Corners",
        "Alternative Corners",
        "Corners 2-Way",
        "Corners Race",
    }
    allowed_names = {
        "Corners": {"over", "exactly", "under"},
        "Alternative Corners": {"over", "exactly", "under"},
        "Corners 2-Way": {"over", "under"},
    }
    for item in items:
        raw_market = re.sub(r"\s+", " ", item.get("market") or "").strip()
        name = re.sub(r"\s+", " ", item.get("name") or "").strip()
        odds = re.sub(r"\s+", " ", item.get("odds") or "").strip()
        line = re.sub(r"\s+", " ", item.get("line") or "").strip() or None
        if raw_market not in allowed_markets or not name or not line or not ODDS_LINE_RE.fullmatch(odds):
            continue
        if not LINE_VALUE_RE.fullmatch(line):
            continue
        if raw_market in allowed_names and name.lower() not in allowed_names[raw_market]:
            continue
        if raw_market == "Corners Race":
            normalized_name = normalize_team(name)
            if normalized_name == normalize_team(match.home):
                name = match.home
            elif normalized_name == normalize_team(match.away):
                name = match.away
            elif name.lower() != "neither":
                continue

        selection = Selection(
            id=None,
            name=name,
            odds=odds,
            decimal_odds=fractional_to_decimal(odds),
            market=f"{raw_market} {line}",
            line=line,
        )
        key = (selection.market, selection.name, selection.odds, selection.line)
        if key in seen:
            continue
        seen.add(key)
        selections.append(selection)
    return selections


def parse_cards_dom_items(items: Iterable[dict[str, str]], match: Match) -> list[Selection]:
    selections: list[Selection] = []
    seen: set[tuple[str | None, str, str, str | None]] = set()
    allowed_markets = {
        "Number Of Cards In Match",
        "Both Teams to Receive Cards",
    }
    for item in items:
        raw_market = re.sub(r"\s+", " ", item.get("market") or "").strip()
        name = re.sub(r"\s+", " ", item.get("name") or "").strip()
        odds = re.sub(r"\s+", " ", item.get("odds") or "").strip()
        line = re.sub(r"\s+", " ", item.get("line") or "").strip() or None
        if raw_market not in allowed_markets or not name or not line or not ODDS_LINE_RE.fullmatch(odds):
            continue

        if raw_market == "Number Of Cards In Match":
            if name.lower() not in {"over", "under"} or not LINE_VALUE_RE.fullmatch(line):
                continue
        elif raw_market == "Both Teams to Receive Cards":
            if name.lower() not in {"yes", "no"}:
                continue

        selection = Selection(
            id=None,
            name=name,
            odds=odds,
            decimal_odds=fractional_to_decimal(odds),
            market=f"{raw_market} {line}",
            line=line,
        )
        key = (selection.market, selection.name, selection.odds, selection.line)
        if key in seen:
            continue
        seen.add(key)
        selections.append(selection)
    return selections


def parse_player_props_dom_items(items: Iterable[dict[str, str]], match: Match) -> list[Selection]:
    selections: list[Selection] = []
    seen: set[tuple[str | None, str, str, str | None]] = set()
    for item in items:
        raw_market = re.sub(r"\s+", " ", item.get("market") or "").strip()
        player = re.sub(r"\s+", " ", item.get("name") or "").strip()
        odds = re.sub(r"\s+", " ", item.get("odds") or "").strip()
        line = re.sub(r"\s+", " ", item.get("line") or "").strip() or None
        option = re.sub(r"\s+", " ", item.get("context") or "").strip()
        if not raw_market or not player or not ODDS_LINE_RE.fullmatch(odds):
            continue

        market = raw_market
        if raw_market == "Player to Score or Assist":
            if option == "Score":
                market = "Player to Score"
            elif option == "Assist":
                market = "Player to Assist"
            elif option == "Score or Assist":
                market = "Player Score or Assist"
            else:
                continue
        elif raw_market in {"Player Shots On Target", "Player Shots"}:
            if not line or not LINE_VALUE_RE.fullmatch(line):
                continue
            market = f"{raw_market} {line}"
        else:
            continue

        selection = Selection(
            id=None,
            name=player,
            odds=odds,
            decimal_odds=fractional_to_decimal(odds),
            market=market,
            line=line,
        )
        key = (selection.market, selection.name, selection.odds, selection.line)
        if key in seen:
            continue
        seen.add(key)
        selections.append(selection)
    return selections


def parse_shots_dom_items(items: Iterable[dict[str, str]], match: Match) -> list[Selection]:
    selections: list[Selection] = []
    seen: set[tuple[str | None, str, str, str | None]] = set()

    def canonical_market(value: str) -> str | None:
        normalized = re.sub(r"\s+", " ", value).strip().lower()
        if normalized == "match shots on target":
            return "Match Shots On Target"
        if normalized == "match shots":
            return "Match Shots"
        if normalized == "team shots on target":
            return "Team Shots on Target"
        if normalized == "team shots":
            return "Team Shots"
        return None

    for item in items:
        raw_market = canonical_market(item.get("market") or "")
        name = re.sub(r"\s+", " ", item.get("name") or "").strip()
        odds = re.sub(r"\s+", " ", item.get("odds") or "").strip()
        line = re.sub(r"\s+", " ", item.get("line") or "").strip() or None
        team = re.sub(r"\s+", " ", item.get("context") or "").strip()
        if not raw_market or not name or not line or not ODDS_LINE_RE.fullmatch(odds):
            continue
        if name.lower() not in {"over", "under"} or not LINE_VALUE_RE.fullmatch(line):
            continue

        market = f"{raw_market} {line}"
        if raw_market.startswith("Team "):
            normalized_team = normalize_team(team)
            if normalized_team == normalize_team(match.home):
                team = match.home
            elif normalized_team == normalize_team(match.away):
                team = match.away
            else:
                continue
            market = f"{team} {raw_market} {line}"

        selection = Selection(
            id=None,
            name=name,
            odds=odds,
            decimal_odds=fractional_to_decimal(odds),
            market=market,
            line=line,
        )
        key = (selection.market, selection.name, selection.odds, selection.line)
        if key in seen:
            continue
        seen.add(key)
        selections.append(selection)
    return selections


def strip_match_odds(matches: Iterable[Match]) -> list[Match]:
    stripped: list[Match] = []
    for match in matches:
        stripped.append(
            Match(
                fixture_id=match.fixture_id,
                home=match.home,
                away=match.away,
                start_time=match.start_time,
                competition=match.competition,
                page_data=match.page_data,
                url=match.url,
            )
        )
    return stripped


def parse_matches(
    payload: str,
    *,
    include_player_props: bool = False,
    include_prebuilt_bets: bool = False,
    known_matches: Iterable[Match] | None = None,
) -> list[Match]:
    nodes = list(iter_nodes(payload))
    fixtures: dict[str, Match] = {}

    for match in known_matches or []:
        fixtures[match.fixture_id] = Match(
            fixture_id=match.fixture_id,
            home=match.home,
            away=match.away,
            start_time=match.start_time,
            competition=match.competition,
            page_data=match.page_data,
            url=match.url,
        )

    for node_type, data in nodes:
        if node_type in {"PA", "EV"} and data.get("FI") and data.get("NA") and data.get("N2") and not data.get("OD"):
            fid = data["FI"]
            page_data = data.get("PD")
            fixtures[fid] = Match(
                fixture_id=fid,
                home=data["NA"],
                away=data["N2"],
                start_time=parse_bet365_datetime(data.get("BC") or data.get("SM")),
                competition=data.get("L3") or data.get("CT") or data.get("CD"),
                page_data=page_data,
                url=topic_to_url(page_data) if page_data else None,
            )

    seen_odds: dict[str, set[tuple[str | None, str | None, str, str]]] = {fid: set() for fid in fixtures}
    active_coupon_selection: str | None = None
    active_coupon_market: str | None = None
    active_market_fixture: str | None = None
    active_market_code: str | None = None
    active_market_name: str | None = None
    player_by_fixture_or: dict[str, dict[str, str]] = {}
    active_player_list_fixture: str | None = None
    active_player_grid_market: dict[str, str | None] = {}
    active_player_name: str | None = None
    active_player_market: str | None = None
    active_promo_market_by_fixture: dict[str, str | None] = {}
    active_prebuilt_fixture: str | None = None

    def add_selection(fid: str, selection: Selection) -> None:
        key = (selection.id, selection.market, selection.name, selection.odds)
        if key in seen_odds.setdefault(fid, set()):
            return
        seen_odds[fid].add(key)
        fixtures[fid].odds.append(selection)

    for node_type, data in nodes:
        fid = fixture_id_from(data)
        if not fid and node_type == "PA" and active_market_fixture:
            fid = active_market_fixture

        if node_type in {"CL", "EV"}:
            active_prebuilt_fixture = None
            active_market_fixture = None
            active_market_code = None
            active_market_name = None

        if node_type == "MG" and data.get("SY") != "pbd":
            active_prebuilt_fixture = None

        if node_type == "MG" and data.get("SY") == "pbd" and data.get("PF"):
            active_prebuilt_fixture = data["PF"]
            active_promo_market_by_fixture[data["PF"]] = market_name_for_code(data.get("MA"))
            active_player_name = None
            active_player_market = None
            if not include_prebuilt_bets:
                continue

        if active_prebuilt_fixture and fid == active_prebuilt_fixture and not include_prebuilt_bets:
            continue

        if node_type == "MG" and data.get("SY") in {"mgi", "mgl"}:
            active_market_code = data.get("ID") or data.get("MA")
            active_market_name = data.get("NA") or market_name_for_code(active_market_code)
            active_market_fixture = None
            continue

        if node_type == "MA" and fid and data.get("MA") and not data.get("OD"):
            active_market_fixture = fid
            active_market_code = data.get("MA")
            active_market_name = data.get("NA") or active_market_name or market_name_for_code(active_market_code)

        if node_type == "MA" and data.get("SY") == "cpce" and data.get("NA"):
            active_coupon_selection = data["NA"]
            active_coupon_market = market_name_for_code(data.get("MA") or active_market_code, "Full Time Result")
            active_market_code = data.get("MA") or active_market_code
            continue

        if node_type == "MA" and data.get("SY") == "phs" and fid:
            active_coupon_selection = None
            active_coupon_market = None
            active_player_list_fixture = fid
            player_by_fixture_or.setdefault(fid, {})
            active_player_grid_market[fid] = data.get("NA") or "Player Props"
            continue

        if (
            node_type == "PA"
            and active_player_list_fixture
            and data.get("ID", "").startswith("PC")
            and data.get("NA")
            and data.get("OR")
            and not data.get("OD")
        ):
            player_by_fixture_or.setdefault(active_player_list_fixture, {})[data["OR"]] = data["NA"]
            continue

        if node_type == "CO" and fid and data.get("SY") == "pot":
            active_coupon_selection = None
            active_coupon_market = None
            active_player_grid_market[fid] = data.get("NA") or market_name_for_code(data.get("MA"), "Player Props")
            continue

        if node_type == "MG" and data.get("SY") == "pmm":
            active_coupon_selection = None
            active_coupon_market = None
            active_player_name = None
            active_player_market = market_name_for_code(data.get("ID", "").removeprefix("M"), data.get("NA"))
            continue

        if node_type == "MA" and data.get("ID", "").startswith("M") and data.get("NA") and data.get("PD"):
            active_player_name = data["NA"]
            continue

        if not fid or fid not in fixtures or not data.get("OD"):
            continue

        match = fixtures[fid]
        raw_selection_name = data.get("NA") or ""
        if node_type == "MG" and data.get("SY") == "pbd" and data.get("CH"):
            raw_selection_name = data["CH"]
        market_name = data.get("MN")
        market_code = data.get("MA") or active_market_code

        if active_coupon_selection and not raw_selection_name:
            raw_selection_name = active_coupon_selection
            market_name = market_name or active_coupon_market
        elif data.get("OR") and data["OR"] in player_by_fixture_or.get(fid, {}) and not raw_selection_name:
            raw_selection_name = player_by_fixture_or[fid][data["OR"]]
            market_name = market_name or active_player_grid_market.get(fid) or "Player Props"
        elif active_player_name and raw_selection_name and market_code in PLAYER_TABLE_MARKET_CODES:
            market_name = market_name or market_name_for_code(market_code, active_player_market)
            raw_selection_name = f"{active_player_name}: {raw_selection_name}"
        elif raw_selection_name:
            market_name = market_name or infer_market_name(
                raw_selection_name,
                market_code,
                active_market_name or active_promo_market_by_fixture.get(fid),
            )
        else:
            raw_selection_name = data.get("ID") or "Selection"
            market_name = market_name or market_name_for_code(
                market_code,
                active_market_name or active_promo_market_by_fixture.get(fid),
            )

        if not include_player_props and market_code and market_code not in MAIN_MARKET_CODES:
            continue
        if not include_player_props and market_name and market_name.startswith("Player "):
            continue
        if not include_player_props and market_name in {"To Score", "To Assist", "Score or Assist", "To be Booked"}:
            continue

        selection = Selection(
            id=data.get("ID"),
            name=clean_selection_name(raw_selection_name, match),
            odds=data["OD"],
            decimal_odds=fractional_to_decimal(data["OD"]),
            market=market_name,
            market_code=market_code,
            line=data.get("HD") or data.get("HA"),
            suspended=data.get("SU") == "1",
        )
        add_selection(fid, selection)

    return list(fixtures.values())


def _merge_selections(existing: list[Selection], incoming: list[Selection]) -> list[Selection]:
    merged = list(existing)
    seen = {(selection.id, selection.market_code, selection.market, selection.name, selection.odds) for selection in merged}
    for selection in incoming:
        key = (selection.id, selection.market_code, selection.market, selection.name, selection.odds)
        if key in seen:
            continue
        seen.add(key)
        merged.append(selection)
    return merged


def merge_matches(existing: list[Match], incoming: list[Match]) -> list[Match]:
    by_id = {match.fixture_id: match for match in existing}
    for match in incoming:
        current = by_id.get(match.fixture_id)
        if current is None:
            by_id[match.fixture_id] = match
            continue
        current.odds = _merge_selections(current.odds, match.odds)
        if match.page_data and not current.page_data:
            current.page_data = match.page_data
            current.url = match.url
        if match.start_time and not current.start_time:
            current.start_time = match.start_time
        if match.competition and not current.competition:
            current.competition = match.competition
    return list(by_id.values())


def topic_to_hash(topic: str) -> str:
    return "#/" + topic.strip("#").replace("#", "/") + "/"


def topic_to_url(topic: str) -> str:
    return BET365_URL + topic_to_hash(topic)


class Bet365WebScraper:
    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: int = 20,
        cookie: str | None = None,
        accept_language: str = "en-GB,en;q=0.9",
    ) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": accept_language,
            }
        )
        if cookie:
            self.session.headers["Cookie"] = cookie
        self.timeout = timeout
        self.boot_html = ""
        self.config: dict[str, Any] = {}
        self.flashvars: dict[str, Any] = {}
        self.routing: dict[str, Any] = {}
        self.cookie_jar = tempfile.NamedTemporaryFile(prefix="bet365-cookies-", suffix=".txt", delete=False).name

    def bootstrap(self, page_hash: str = UPCOMING_SOCCER_HASH) -> None:
        boot_url = BET365_URL + page_hash
        response = self._get(boot_url)
        response.raise_for_status()
        self.boot_html = response.text

        config_path = self._extract_config_path(self.boot_html)
        config_url = self._with_query_params(BET365_URL.rstrip("/") + config_path, {"pd": page_hash})
        config_response = self._get(
            config_url,
            headers={"Accept": "application/json,text/plain,*/*", "Referer": boot_url},
        )
        config_response.raise_for_status()
        self.config = config_response.json()
        self.flashvars = self.config.get("flashvars", {})

        routing_path = self._extract_routing_path(self.boot_html)
        routing_response = self._get(
            BET365_URL.rstrip("/") + routing_path,
            headers={"Accept": "application/json,text/plain,*/*", "Referer": boot_url},
        )
        routing_response.raise_for_status()
        self.routing = routing_response.json()

    def fetch_topic(self, topic: str, source: str = "topic") -> EndpointResult:
        if not self.flashvars or not self.routing:
            self.bootstrap()
        endpoint, qs_params = self._endpoint_for_topic(topic)
        url = self._build_content_url(endpoint, topic, qs_params)
        response = self._get(
            url,
            headers={"Accept": "*/*", "Referer": topic_to_url(topic)},
        )
        return EndpointResult(
            url=url,
            status_code=response.status_code,
            bytes=len(response.content),
            body=response.text,
            source=source,
        )

    def fetch_match_markets_topic(self, topic: str, source: str = "matchmarkets_markets") -> EndpointResult:
        url = self._build_match_markets_url(topic_with_trailing_hash(topic))
        response = self._get(
            url,
            headers={"Accept": "*/*", "Referer": topic_to_url(topic)},
        )
        return EndpointResult(
            url=response.url,
            status_code=response.status_code,
            bytes=len(response.content),
            body=response.text,
            source=source,
        )

    def fetch_fixture_market_topics(self, match: Match) -> list[EndpointResult]:
        return [
            self.fetch_fixture_market_topic(topic, source=source)
            for source, topic in fixture_market_topics(match)
        ]

    def fetch_fixture_market_topic(self, topic: str, source: str) -> EndpointResult:
        try:
            self.bootstrap(topic_to_hash(topic))
        except Exception:
            if not self.flashvars or not self.routing:
                self.bootstrap()
        try:
            endpoint, qs_params = self._endpoint_for_topic(topic)
        except LookupError:
            endpoint, qs_params = "/matchbettingcontentapi/coupon", {"csidex": "1"}
        url = self._build_content_url(endpoint, topic, qs_params)
        response = self._get(url, headers={"Accept": "*/*", "Referer": topic_to_url(topic)})
        return EndpointResult(
            url=response.url,
            status_code=response.status_code,
            bytes=len(response.content),
            body=response.text,
            source=source,
        )

    def fetch_homepage_pods(self) -> EndpointResult:
        if not self.flashvars:
            self.bootstrap()

        fv = self.flashvars
        params = {
            "lid": fv.get("LANGUAGE_ID", "1"),
            "zid": fv.get("ZID", "1"),
            "pd": "#HO#COL1#",
            "cid": fv.get("REGISTERED_COUNTRY_CODE", "197"),
            "cstid": fv.get("CUSTOMER_TYPE", "1"),
            "tcstid": fv.get("CUSTOMER_TYPE", "1"),
            "crid": fv.get("CURRENCY_ID", "1"),
        }
        if fv.get("EXCLUSION_LEVEL") == "2":
            params["cgid"] = fv.get("COUNTRY_GROUP_ID", "")
            params["ctid"] = fv.get("REGISTERED_COUNTRY_CODE", "")
        elif fv.get("EXCLUSION_LEVEL") == "1":
            params["cgid"] = fv.get("COUNTRY_GROUP_ID", "")

        request = requests.Request("GET", BET365_URL + "pullpodapi/gethomepagepods", params=params)
        url = request.prepare().url or ""
        response = self._get(
            url,
            headers={"Accept": "*/*", "Referer": BET365_URL, "boot": "1"},
        )
        return EndpointResult(
            url=response.url,
            status_code=response.status_code,
            bytes=len(response.content),
            body=response.text,
            source="homepage_pods",
        )

    def find_premier_league_matches(
        self,
        teams: set[str] | None = None,
        include_homepage_fallback: bool = True,
        include_player_props: bool = False,
        include_prebuilt_bets: bool = False,
        max_matches: int = 0,
    ) -> tuple[list[Match], list[EndpointResult]]:
        filtered, results = self.discover_premier_league_matches(
            teams=teams,
            include_homepage_fallback=include_homepage_fallback,
            include_player_props=include_player_props,
            include_prebuilt_bets=include_prebuilt_bets,
        )
        if max_matches > 0:
            filtered = filtered[:max_matches]

        for match in filtered:
            match.url = topic_to_url(f"#AC#B1#C1#D8#E{match.fixture_id}#F3#F4#")
            match.odds = []
            for market_result in self.fetch_fixture_market_topics(match):
                results.append(market_result)
                if not market_result.body:
                    continue
                for detailed_match in parse_matches(
                    market_result.body,
                    include_player_props=include_player_props,
                    include_prebuilt_bets=include_prebuilt_bets,
                    known_matches=[match],
                ):
                    if detailed_match.fixture_id != match.fixture_id or not detailed_match.odds:
                        continue
                    match.odds = _merge_selections(match.odds, detailed_match.odds)
                    if detailed_match.page_data and not match.page_data:
                        match.page_data = detailed_match.page_data
                    if detailed_match.start_time and not match.start_time:
                        match.start_time = detailed_match.start_time
                    if detailed_match.competition and not match.competition:
                        match.competition = detailed_match.competition
        return filtered, results

    def discover_premier_league_matches(
        self,
        teams: set[str] | None = None,
        include_homepage_fallback: bool = True,
        include_player_props: bool = False,
        include_prebuilt_bets: bool = False,
    ) -> tuple[list[Match], list[EndpointResult]]:
        normalized_teams = {normalize_team(team) for team in (teams or DEFAULT_PREMIER_LEAGUE_TEAMS)}
        results: list[EndpointResult] = []
        matches: list[Match] = []

        for topic in direct_discovery_topics():
            direct = self.fetch_match_markets_topic(topic)
            results.append(direct)
            if direct.status_code >= 400 or not direct.body:
                continue
            matches.extend(
                parse_matches(
                    direct.body,
                    include_player_props=include_player_props,
                    include_prebuilt_bets=include_prebuilt_bets,
                )
            )

        if not matches:
            upcoming = self.fetch_topic(UPCOMING_SOCCER_TOPIC)
            results.append(upcoming)
            if upcoming.body:
                matches.extend(
                    parse_matches(
                        upcoming.body,
                        include_player_props=include_player_props,
                        include_prebuilt_bets=include_prebuilt_bets,
                    )
                )

        if include_homepage_fallback and not matches:
            homepage = self.fetch_homepage_pods()
            results.append(homepage)
            if homepage.body:
                matches.extend(
                    strip_match_odds(
                        parse_matches(
                            homepage.body,
                            include_player_props=False,
                            include_prebuilt_bets=False,
                        )
                    )
                )

        seen: set[str] = set()
        filtered: list[Match] = []
        for match in matches:
            if match.fixture_id in seen:
                continue
            home = normalize_team(match.home)
            away = normalize_team(match.away)
            competition = normalize_team(match.competition or "")
            is_epl_match = (
                home in normalized_teams and away in normalized_teams
            ) or "premier league" in competition
            if is_epl_match:
                seen.add(match.fixture_id)
                filtered.append(match)
        return filtered, results

    def _build_content_url(self, endpoint: str, topic: str, qs_params: dict[str, str]) -> str:
        fv = self.flashvars
        params = {
            "lid": fv.get("LANGUAGE_ID", "1"),
            "zid": fv.get("ZID", "1"),
            "pd": topic,
            "cid": fv.get("REGISTERED_COUNTRY_CODE", "197"),
        }
        params.update(self._inclusion_params())
        params.update(qs_params)
        request = requests.Request("GET", BET365_URL.rstrip("/") + endpoint, params=params)
        return request.prepare().url or ""

    def _build_match_markets_url(self, topic: str) -> str:
        fv = self.flashvars
        params = {
            "lid": fv.get("LANGUAGE_ID", "1"),
            "zid": fv.get("ZID", "1"),
            "pd": topic,
            "cid": fv.get("REGISTERED_COUNTRY_CODE", "197"),
        }
        params.update(self._contentdata_inclusion_params())
        request = requests.Request(
            "GET",
            BET365_URL.rstrip("/") + "/contentdata/matchmarketscontentapi/markets",
            params=params,
        )
        return request.prepare().url or ""

    @staticmethod
    def _with_query_params(url: str, params: dict[str, str]) -> str:
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update(params)
        prepared = requests.Request("GET", urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")), params=query)
        return prepared.prepare().url or url

    def _get(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse:
        merged_headers = dict(self.session.headers)
        if headers:
            merged_headers.update(headers)

        try:
            response = self.session.get(url, headers=merged_headers, timeout=self.timeout)
            if response.status_code not in {403, 500}:
                return HttpResponse(url=response.url, status_code=response.status_code, text=response.text)
        except requests.RequestException:
            pass

        return self._curl_get(url, merged_headers)

    def _curl_get(self, url: str, headers: dict[str, str]) -> HttpResponse:
        marker = "__BET365_CURL_STATUS__"
        command = [
            "curl",
            "-sS",
            "--max-time",
            str(self.timeout),
            "--compressed",
            "-b",
            self.cookie_jar,
            "-c",
            self.cookie_jar,
            "-A",
            headers.get("User-Agent", DEFAULT_USER_AGENT),
            "-w",
            f"\n{marker}%{{http_code}} %{{url_effective}}",
        ]
        for key, value in headers.items():
            if key.lower() == "user-agent":
                continue
            command.extend(["-H", f"{key}: {value}"])
        command.append(url)

        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        body, _, trailer = completed.stdout.rpartition(f"\n{marker}")
        if not trailer:
            return HttpResponse(url=url, status_code=0, text=completed.stdout)
        status, _, effective_url = trailer.partition(" ")
        return HttpResponse(url=effective_url.strip() or url, status_code=int(status), text=body)

    def _inclusion_params(self) -> dict[str, str]:
        fv = self.flashvars
        mode = str(fv.get("EXCLUSION_LEVEL", ""))
        if mode == "1":
            return {"cgid": str(fv.get("COUNTRY_GROUP_ID", ""))}
        if mode == "2":
            return {
                "cgid": str(fv.get("COUNTRY_GROUP_ID", "")),
                "ctid": str(fv.get("REGISTERED_COUNTRY_CODE", "")),
            }
        if mode == "3":
            return {
                "cgid": str(fv.get("COUNTRY_GROUP_ID", "")),
                "ctid": str(fv.get("REGISTERED_COUNTRY_CODE", "")),
                "csid": str(fv.get("COUNTRY_STATE_ID", "")),
            }
        return {}

    def _contentdata_inclusion_params(self) -> dict[str, str]:
        params = self._inclusion_params()
        if params:
            return params
        return {"cgid": "2", "ctid": str(self.flashvars.get("REGISTERED_COUNTRY_CODE", "197"))}

    def _endpoint_for_topic(self, topic: str) -> tuple[str, dict[str, str]]:
        for rule in sorted(self.routing.get("manifest", []), key=lambda item: int(item.get("o", 0))):
            if self._rule_matches(rule, topic):
                return rule["e"], self._rule_qs_params(rule)
        raise LookupError(f"No Bet365 routing rule matched topic {topic!r}")

    def _rule_qs_params(self, rule: dict[str, Any]) -> dict[str, str]:
        result: dict[str, str] = {}
        for param in str(rule.get("q", "")).split(","):
            if param == "tzo":
                result["tzo"] = str(self.flashvars.get("TZAM") or self.flashvars.get("TZA") or "0")
            elif param == "cstid":
                result["cstid"] = str(self.flashvars.get("CUSTOMER_TYPE", "1"))
            elif param == "csidex":
                result["csidex"] = "1"
        return result

    @staticmethod
    def _rule_matches(rule: dict[str, Any], topic: str) -> bool:
        rule_type = rule.get("t")
        if rule_type and f"#{rule_type}#" not in topic:
            return False
        raw_matches = rule.get("m")
        if not raw_matches:
            return True
        topic = topic if topic.endswith("#") else topic + "#"
        for chunk in raw_matches.split("~"):
            key, _, values = chunk.partition(":")
            allowed = values.split(",")
            if not any(f"#{key}{value}#" in topic for value in allowed):
                return False
        return True

    @staticmethod
    def _extract_config_path(html: str) -> str:
        match = re.search(r'"SITE_CONFIG_LOCATION":"([^"]+)"', html)
        if not match:
            raise RuntimeError("Could not find SITE_CONFIG_LOCATION in Bet365 boot HTML")
        return match.group(1)

    @staticmethod
    def _extract_routing_path(html: str) -> str:
        match = re.search(r'"SERVICE_RULES_LOCATION":"([^"]+)"', html)
        if not match:
            raise RuntimeError("Could not find SERVICE_RULES_LOCATION in Bet365 boot HTML")
        return match.group(1)


class Bet365RenderedPageScraper:
    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        accept_language: str = "en-GB,en;q=0.9",
        headed: bool = False,
        timeout_ms: int = 60000,
        settle_ms: int = 5000,
        user_data_dir: str | None = None,
        executable_path: str | None = None,
        clone_profile: bool = True,
        keep_open_seconds: int = 0,
    ) -> None:
        self.user_agent = user_agent
        self.accept_language = accept_language
        self.headed = headed
        self.timeout_ms = timeout_ms
        self.settle_ms = settle_ms
        self.keep_open_seconds = keep_open_seconds
        self.user_data_dir = user_data_dir or os.getenv("BET365_BROWSER_USER_DATA_DIR")
        self.clone_profile = clone_profile
        self.cloned_user_data_dir: str | None = None
        self.executable_path = executable_path or os.getenv("BET365_BROWSER_EXECUTABLE")
        if not self.executable_path and os.path.exists("/usr/bin/google-chrome"):
            self.executable_path = "/usr/bin/google-chrome"

    def find_premier_league_matches(
        self,
        teams: set[str] | None = None,
        include_player_props: bool = False,
        include_prebuilt_bets: bool = False,
        max_matches: int = 0,
    ) -> tuple[list[Match], list[EndpointResult]]:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Rendered-page mode requires Playwright. Install dependencies from requirements.txt.") from exc

        visited_pages: list[EndpointResult] = []
        normalized_teams = {normalize_team(team) for team in (teams or DEFAULT_PREMIER_LEAGUE_TEAMS)}
        console_log("Discovering fixtures via HTTP payloads before opening browser...")
        discovery_scraper = Bet365WebScraper(
            user_agent=self.user_agent,
            cookie=os.getenv("BET365_COOKIE") or os.getenv("COOKIE"),
            accept_language=self.accept_language,
        )
        matches: list[Match] = []
        try:
            matches, discovery_results = discovery_scraper.discover_premier_league_matches(
                teams=teams,
                include_player_props=include_player_props,
                include_prebuilt_bets=include_prebuilt_bets,
            )
            visited_pages.extend(discovery_results)
        except Exception as exc:
            console_log(f"HTTP fixture discovery failed; falling back to rendered discovery: {exc}")
        for match in matches:
            match.odds = []
        if max_matches > 0:
            matches = matches[:max_matches]
        console_log(f"Discovered {len(matches)} Premier League fixture(s) via HTTP.")

        launch_user_data_dir = self._launch_user_data_dir()
        console_log(
            "Rendered browser mode starting "
            f"executable={self.executable_path or 'playwright chromium'} "
            f"profile={launch_user_data_dir or 'temporary'} headed={self.headed}"
        )

        with sync_playwright() as playwright:
            browser = None
            attached_existing_browser = False
            opened_pages: list[Any] = []
            context_kwargs = {
                "user_agent": self.user_agent,
                "locale": self.accept_language.split(",", 1)[0],
                "timezone_id": "Europe/London",
                "viewport": {"width": 1440, "height": 1000},
            }
            launch_kwargs = {
                "headless": not self.headed,
                "timeout": self.timeout_ms,
            }
            try:
                console_log("Attempting to attach to existing chrome")
                browser = playwright.chromium.connect_over_cdp("http://localhost:9222")
                context = browser.contexts[0]
                attached_existing_browser = True
            except Exception as e:
                console_log("Failed to attach: " + e.__str__())
                if self.executable_path:
                    launch_kwargs["executable_path"] = self.executable_path
                if launch_user_data_dir:
                    console_log("Launching persistent Chrome context...")
                    context = playwright.chromium.launch_persistent_context(
                        launch_user_data_dir,
                        **launch_kwargs,
                        **context_kwargs,
                    )
                else:
                    console_log("Launching temporary Chrome context...")
                    browser = playwright.chromium.launch(**launch_kwargs)
                    context = browser.new_context(**context_kwargs)
            console_log("Chrome context launched; opening a new page...")

            last_page = None

            if not matches:
                discovery_url = BET365_URL + UPCOMING_SOCCER_HASH
                console_log(f"Opening rendered fixture discovery page {discovery_url}")
                page = context.new_page()
                opened_pages.append(page)
                network_results: list[EndpointResult] = []
                self._capture_bet365_content_responses(page, network_results)
                page.bring_to_front()
                self._goto(page, discovery_url, PlaywrightTimeoutError)
                visited_pages.extend(network_results)
                text = self._page_text(page)
                visited_pages.append(
                    EndpointResult(
                        url=page.url,
                        status_code=200,
                        bytes=len(text.encode("utf-8")),
                        body=text,
                        source="rendered_fixture_discovery",
                    )
                )
                matches = self._premier_league_matches_from_results(
                    network_results,
                    normalized_teams,
                    include_player_props=include_player_props,
                    include_prebuilt_bets=include_prebuilt_bets,
                )
                if matches:
                    console_log(f"Discovered {len(matches)} Premier League fixture(s) via rendered network payloads.")
                else:
                    matches = self._extract_rendered_fixtures(page, normalized_teams)
                for match in matches:
                    match.odds = []
                if max_matches > 0:
                    matches = matches[:max_matches]
                console_log(f"Discovered {len(matches)} Premier League fixture(s) via rendered page.")
                last_page = page
                if self.keep_open_seconds <= 0:
                    page.close()
                    opened_pages.remove(page)

            if not matches:
                console_log("No Premier League fixtures found after HTTP and rendered discovery.")

            for match in matches:
                for source, topic in fixture_rendered_market_topics(match):
                    url = topic_to_url(topic)
                    console_log(f"Opening match {match.home} v {match.away} ({match.fixture_id}) {source}")
                    page = context.new_page()
                    opened_pages.append(page)
                    page.bring_to_front()
                    self._goto(page, url, PlaywrightTimeoutError)
                    text = self._page_text(page)
                    visited_pages.append(
                        EndpointResult(
                            url=page.url,
                            status_code=200,
                            bytes=len(text.encode("utf-8")),
                            body=text,
                            source=f"rendered_{source}",
                        )
                    )
                    match.url = url
                    match.odds = _merge_selections(
                        match.odds,
                        self._extract_rendered_market_odds(
                            page,
                            match,
                            source=source,
                            include_player_props=include_player_props,
                            include_prebuilt_bets=include_prebuilt_bets,
                        ),
                    )
                    last_page = page
                    if self.keep_open_seconds <= 0:
                        page.close()
                        opened_pages.remove(page)

            if self.keep_open_seconds > 0:
                console_log(f"Keeping browser open for {self.keep_open_seconds} seconds...")
                if last_page is not None:
                    last_page.wait_for_timeout(self.keep_open_seconds * 1000)

            for page in list(opened_pages):
                try:
                    page.close()
                except Exception:
                    pass
            if not attached_existing_browser:
                context.close()
            if browser is not None and not attached_existing_browser:
                browser.close()
            if self.cloned_user_data_dir:
                shutil.rmtree(self.cloned_user_data_dir, ignore_errors=True)

        return matches, visited_pages

    def _launch_user_data_dir(self) -> str | None:
        if not self.user_data_dir:
            return None
        if not self.clone_profile:
            self._raise_if_profile_locked(self.user_data_dir)
            return self.user_data_dir

        clone_parent = tempfile.mkdtemp(prefix="bet365-chrome-profile-")
        clone_dir = os.path.join(clone_parent, "user-data")
        console_log(f"Copying Chrome profile to temporary directory {clone_dir}")
        shutil.copytree(
            self.user_data_dir,
            clone_dir,
            symlinks=True,
            ignore=shutil.ignore_patterns(
                "Singleton*",
                "Crash Reports",
                "GrShaderCache",
                "ShaderCache",
                "GraphiteDawnCache",
                "component_crx_cache",
                "extensions_crx_cache",
                "BrowserMetrics*",
                "Safe Browsing*",
                "OptimizationHints",
                "optimization_guide_model_store",
                "Default/Cache",
                "Default/Code Cache",
                "Default/GPUCache",
                "Default/Service Worker/CacheStorage",
                "Profile */Cache",
                "Profile */Code Cache",
                "Profile */GPUCache",
                "Profile */Service Worker/CacheStorage",
            ),
        )
        self.cloned_user_data_dir = clone_parent
        self._raise_if_profile_locked(clone_dir)
        console_log("Chrome profile copy complete.")
        return clone_dir

    def _goto(self, page: Any, url: str, timeout_error: type[Exception]) -> None:
        console_log(f"Opening {url}")
        try:
            page.bring_to_front()
            page.goto(url, wait_until="commit", timeout=self.timeout_ms)
        except timeout_error:
            console_log(f"Timed out starting navigation to {url}; forcing location.href")
            try:
                page.evaluate("target => window.location.href = target", url)
            except Exception as exc:
                console_log(f"Could not force navigation to {url}: {exc}")
        except Exception as exc:
            console_log(f"Navigation error for {url}: {exc}")
        try:
            page.wait_for_load_state("domcontentloaded", timeout=min(self.timeout_ms, 15000))
        except timeout_error:
            pass
        except Exception:
            pass
        try:
            page.wait_for_function(
                r"""
                () => {
                  const text = document.body?.innerText || '';
                  return /(?:\d{1,4}\/\d{1,4}|\d+\.\d+)/.test(text) || text.length > 2000;
                }
                """,
                timeout=min(self.timeout_ms, 15000),
            )
        except timeout_error:
            console_log(f"Timed out waiting for rendered content at {url}")
        except Exception:
            pass
        page.wait_for_timeout(self.settle_ms)
        console_log(f"Current page {page.url}")

    @staticmethod
    def _capture_bet365_content_responses(page: Any, sink: list[EndpointResult]) -> None:
        def on_response(response: Any) -> None:
            url = response.url
            if "/contentdata/" not in url and "matchmarketscontentapi" not in url:
                return
            try:
                body = response.text()
            except Exception:
                return
            if not body:
                return
            sink.append(
                EndpointResult(
                    url=url,
                    status_code=response.status,
                    bytes=len(body.encode("utf-8")),
                    body=body,
                    source="rendered_network_contentdata",
                )
            )

        page.on("response", on_response)

    @staticmethod
    def _raise_if_profile_locked(user_data_dir: str) -> None:
        lock_paths = [
            os.path.join(user_data_dir, "SingletonLock"),
            os.path.join(user_data_dir, "SingletonSocket"),
            os.path.join(user_data_dir, "SingletonCookie"),
        ]
        existing = [path for path in lock_paths if os.path.exists(path)]
        if existing:
            joined = ", ".join(existing)
            raise RuntimeError(
                "Chrome profile appears to be in use, so Playwright may open Chrome and then stall before navigation. "
                "Close every Chrome window using this profile, or copy the profile and pass the copy. "
                f"Lock files found: {joined}"
            )

    @staticmethod
    def _page_text(page: Any) -> str:
        try:
            return page.locator("body").inner_text(timeout=5000)
        except Exception:
            return ""

    @staticmethod
    def _premier_league_matches_from_results(
        results: Iterable[EndpointResult],
        normalized_teams: set[str],
        *,
        include_player_props: bool = False,
        include_prebuilt_bets: bool = False,
    ) -> list[Match]:
        matches: list[Match] = []
        seen: set[str] = set()
        for result in results:
            if result.status_code >= 400 or not result.body or result.body.lstrip().startswith("<"):
                continue
            for match in parse_matches(
                result.body,
                include_player_props=include_player_props,
                include_prebuilt_bets=include_prebuilt_bets,
            ):
                if match.fixture_id in seen:
                    continue
                home = normalize_team(match.home)
                away = normalize_team(match.away)
                competition = normalize_team(match.competition or "")
                if (home in normalized_teams and away in normalized_teams) or "premier league" in competition:
                    seen.add(match.fixture_id)
                    matches.append(match)
        return matches

    def _extract_rendered_market_odds(
        self,
        page: Any,
        match: Match,
        *,
        source: str,
        include_player_props: bool = False,
        include_prebuilt_bets: bool = False,
    ) -> list[Selection]:
        if source == "full_time_result_i1":
            return self._extract_full_time_result_odds(page, match)
        if source == "cards_i4":
            return self._extract_cards_market_odds(page, match)
        if source == "corners_i5":
            return self._extract_corners_market_odds(page, match)
        if source == "goals_i6":
            return self._extract_goals_market_odds(page, match)
        if source == "player_props_i8":
            return self._extract_player_props_market_odds(page, match)
        if source.startswith("shots_i"):
            return self._extract_shots_market_odds(page, match)
        return self._extract_rendered_odds(
            page,
            match,
            include_player_props=include_player_props,
            include_prebuilt_bets=include_prebuilt_bets,
        )

    def _extract_full_time_result_odds(self, page: Any, match: Match) -> list[Selection]:
        extraction = page.evaluate(
            r"""
            () => {
              const oddsRe = /^(?:\d{1,4}\/\d{1,4}|\d+\.\d+)$/;
              const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
              const textOf = (el) => clean(el?.innerText || el?.textContent || '');
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const box = el.getBoundingClientRect();
                return style && style.visibility !== 'hidden' && style.display !== 'none' && box.width > 0 && box.height > 0;
              };
              const marketTitleFor = (group) => {
                const titleSelectors = [
                  '.sc-MarketGroupButtonWithStats_Text',
                  '.cm-MarketGroupWithIconsButton_Text',
                  '.gl-MarketGroupButton_Text',
                  '[class*="MarketGroupButton"][class*="Text"]',
                  '[class*="MarketGroup"][class*="Text"]',
                ];
                for (const selector of titleSelectors) {
                  const title = Array.from(group.querySelectorAll(selector))
                    .filter(visible)
                    .map(textOf)
                    .find(Boolean);
                  if (title) return title;
                }
                return '';
              };
              const participantNameFor = (participant) => {
                const selectors = [
                  '.srb-ParticipantResponsiveText_Name',
                  '[class*="ParticipantResponsiveText_Name"]',
                  '[class*="Participant"][class*="Name"]',
                  '[class*="ParticipantName"]',
                ];
                for (const selector of selectors) {
                  const name = Array.from(participant.querySelectorAll(selector))
                    .filter(visible)
                    .map(textOf)
                    .find(Boolean);
                  if (name) return name;
                }
                return '';
              };
              const participantOddsFor = (participant) => {
                const selectors = [
                  '.srb-ParticipantResponsiveText_Odds',
                  '[class*="ParticipantResponsiveText_Odds"]',
                  '[class*="Participant"][class*="Odds"]',
                  '[class*="_Odds"]',
                ];
                for (const selector of selectors) {
                  const odds = Array.from(participant.querySelectorAll(selector))
                    .filter(visible)
                    .map(textOf)
                    .find((value) => oddsRe.test(value));
                  if (odds) return odds;
                }
                return '';
              };
              const fullTimeResultMarketFor = (group) => {
                const groupText = textOf(group);
                return /\benhanced(?:\s+prices?)?\b/i.test(groupText)
                  ? 'Full Time Result - Enhanced'
                  : 'Full Time Result';
              };
              const groups = Array.from(document.querySelectorAll(
                '.gl-MarketGroupPod.gl-MarketGroup, .gl-MarketGroupPod, .gl-MarketGroup'
              )).filter(visible);
              const results = [];
              const unresolved = [];
              for (const group of groups) {
                const title = marketTitleFor(group);
                if (!/\bfull time result\b/i.test(title)) continue;
                const market = fullTimeResultMarketFor(group);
                const participants = Array.from(group.querySelectorAll(
                  '.srb-ParticipantResponsiveText.gl-Participant_General, .gl-Participant_General, div[class*="ParticipantResponsiveText"]'
                )).filter(visible);
                for (const participant of participants) {
                  const name = participantNameFor(participant);
                  const odds = participantOddsFor(participant);
                  const item = {
                    market,
                    name,
                    odds,
                    line: '',
                    context: '',
                    container: textOf(participant).slice(0, 300),
                    participant_class: String(participant.className || ''),
                    html: clean(participant.outerHTML || '').slice(0, 700),
                  };
                  if (name && oddsRe.test(odds)) {
                    results.push(item);
                  } else {
                    unresolved.push({
                      ...item,
                      reason: !name ? 'missing full-time result participant name' : 'missing full-time result odds',
                    });
                  }
                }
              }
              return {results, unresolved};
            }
            """
        )
        if isinstance(extraction, list):
            candidates = extraction
            unresolved: list[dict[str, str]] = []
        else:
            unresolved = extraction.get("unresolved", [])
            candidates = extraction.get("results", [])
        self._log_unparsed_rendered_odds(unresolved, match, page.url)
        return parse_full_time_result_dom_items(candidates, match)

    def _extract_cards_market_odds(self, page: Any, match: Match) -> list[Selection]:
        extraction = page.evaluate(
            r"""
            () => {
              const oddsRe = /^(?:\d{1,4}\/\d{1,4}|\d+\.\d+)$/;
              const lineRe = /^[+-]?\d+(?:\.\d+)?$/;
              const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
              const textOf = (el) => clean(el?.innerText || el?.textContent || '');
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const box = el.getBoundingClientRect();
                return style && style.visibility !== 'hidden' && style.display !== 'none' && box.width > 0 && box.height > 0;
              };
              const marketTitleFor = (group) => {
                const titleSelectors = [
                  '.sc-MarketGroupButtonWithStats_Text',
                  '.cm-MarketGroupWithIconsButton_Text',
                  '.gl-MarketGroupButton_Text',
                  '[class*="MarketGroupButton"][class*="Text"]',
                  '[class*="MarketGroup"][class*="Text"]',
                ];
                for (const selector of titleSelectors) {
                  const title = Array.from(group.querySelectorAll(selector))
                    .filter(visible)
                    .map(textOf)
                    .find(Boolean);
                  if (title) return title;
                }
                return '';
              };
              const columnHeaderFor = (column) => {
                const header = Array.from(column.querySelectorAll('.gl-MarketColumnHeader, [class*="MarketColumnHeader"]'))
                  .filter(visible)
                  .map(textOf)
                  .find((value) => value && value !== '\u00a0');
                return header || '';
              };
              const rowLabelsFor = (column) => {
                const selectors = [
                  '.srb-ParticipantLabelCentered_Name',
                  '[class*="ParticipantLabelCentered_Name"]',
                  '.srb-ParticipantLabel_Name',
                  '[class*="ParticipantLabel_Name"]',
                ];
                const labels = [];
                for (const selector of selectors) {
                  labels.push(...Array.from(column.querySelectorAll(selector)).filter(visible).map(textOf).filter(Boolean));
                }
                if (labels.length > 0) return labels;
                return (column.innerText || column.textContent || '')
                  .split(/\n+/)
                  .map(clean)
                  .filter(Boolean)
                  .filter((value) => value !== '\u00a0');
              };
              const oddsValuesFor = (column) => {
                return Array.from(column.querySelectorAll('.gl-ParticipantOddsOnly_Odds, [class*="ParticipantOddsOnly_Odds"], [class*="_Odds"]'))
                  .filter(visible)
                  .map(textOf)
                  .filter((value) => oddsRe.test(value));
              };
              const extractColumnMajorGrid = (group, market, acceptedHeaders, rowFilter) => {
                const columns = Array.from(group.querySelectorAll('.gl-Market.gl-Market_General, .gl-Market'))
                  .filter(visible);
                const labelColumn = columns[0];
                const rowLabels = labelColumn ? rowLabelsFor(labelColumn).filter(rowFilter) : [];
                if (!labelColumn || rowLabels.length === 0) {
                  return {
                    results: [],
                    unresolved: [{
                      market,
                      name: '',
                      odds: '',
                      line: '',
                      reason: 'missing cards row label column',
                      container: textOf(group).slice(0, 500),
                      html: clean(group.outerHTML || '').slice(0, 900),
                    }],
                  };
                }

                const oddsColumns = columns
                  .slice(1)
                  .map((column) => ({
                    name: columnHeaderFor(column),
                    odds: oddsValuesFor(column),
                  }))
                  .filter((column) => column.name && column.odds.length > 0)
                  .filter((column) => acceptedHeaders.some((header) => header.test(column.name)));

                const results = [];
                const unresolved = [];
                for (const column of oddsColumns) {
                  const count = Math.min(rowLabels.length, column.odds.length);
                  for (let index = 0; index < count; index += 1) {
                    results.push({market, name: column.name, odds: column.odds[index], line: rowLabels[index], context: ''});
                  }
                  if (rowLabels.length !== column.odds.length) {
                    unresolved.push({
                      market,
                      name: column.name,
                      odds: '',
                      line: '',
                      reason: `column length mismatch rows=${rowLabels.length} ${column.name}=${column.odds.length}`,
                      container: textOf(group).slice(0, 500),
                      html: clean(group.outerHTML || '').slice(0, 900),
                    });
                  }
                }
                if (oddsColumns.length === 0) {
                  unresolved.push({
                    market,
                    name: '',
                    odds: '',
                    line: '',
                    reason: 'missing cards odds columns',
                    container: textOf(group).slice(0, 500),
                    html: clean(group.outerHTML || '').slice(0, 900),
                  });
                }
                return {results, unresolved};
              };
              const groups = Array.from(document.querySelectorAll(
                '.gl-MarketGroupPod.gl-MarketGroup, .gl-MarketGroupPod, .gl-MarketGroup'
              )).filter(visible);
              const results = [];
              const unresolved = [];
              for (const group of groups) {
                const title = marketTitleFor(group);
                if (/^Number Of Cards In Match$/i.test(title)) {
                  const extracted = extractColumnMajorGrid(
                    group,
                    'Number Of Cards In Match',
                    [/^over$/i, /^under$/i],
                    (value) => lineRe.test(value)
                  );
                  results.push(...extracted.results);
                  unresolved.push(...extracted.unresolved);
                } else if (/^Both Teams to Receive Cards$/i.test(title)) {
                  const extracted = extractColumnMajorGrid(
                    group,
                    'Both Teams to Receive Cards',
                    [/^yes$/i, /^no$/i],
                    (value) => !oddsRe.test(value)
                  );
                  results.push(...extracted.results);
                  unresolved.push(...extracted.unresolved);
                }
              }
              return {results, unresolved};
            }
            """
        )
        if isinstance(extraction, list):
            candidates = extraction
            unresolved: list[dict[str, str]] = []
        else:
            unresolved = extraction.get("unresolved", [])
            candidates = extraction.get("results", [])
        self._log_unparsed_rendered_odds(unresolved, match, page.url)
        return parse_cards_dom_items(candidates, match)

    def _extract_player_props_market_odds(self, page: Any, match: Match) -> list[Selection]:
        extraction = page.evaluate(
            r"""
            () => {
              const oddsRe = /^(?:\d{1,4}\/\d{1,4}|\d+\.\d+)$/;
              const lineRe = /^[+-]?\d+(?:\.\d+)?$/;
              const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
              const textOf = (el) => clean(el?.innerText || el?.textContent || '');
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const box = el.getBoundingClientRect();
                return style && style.visibility !== 'hidden' && style.display !== 'none' && box.width > 0 && box.height > 0;
              };
              const marketTitleFor = (group) => {
                const titleSelectors = [
                  '.sc-MarketGroupButtonWithStats_Text',
                  '.cm-MarketGroupWithIconsButton_Text',
                  '.srb-ButtonWithBetBuilderIcon_Text',
                  '.gl-MarketGroupButton_Text',
                  '[class*="MarketGroupButton"][class*="Text"]',
                  '[class*="ButtonWithBetBuilderIcon_Text"]',
                  '[class*="MarketGroup"][class*="Text"]',
                ];
                for (const selector of titleSelectors) {
                  const title = Array.from(group.querySelectorAll(selector))
                    .filter(visible)
                    .map(textOf)
                    .find(Boolean);
                  if (title) return title;
                }
                return '';
              };
              const columnHeaderFor = (column) => {
                const selectors = [
                  '.srb-MarketColumnHeaderTruncate_Label',
                  '.srb-HScrollPlaceHeader',
                  '.srb-HScrollParticipantHeader',
                  '.srb-MarketColumnHeaderLeftAlign',
                  '.gl-MarketColumnHeader',
                  '[class*="MarketColumnHeaderTruncate_Label"]',
                  '[class*="HScrollPlaceHeader"]',
                  '[class*="HScrollParticipantHeader"]',
                  '[class*="MarketColumnHeaderLeftAlign"]',
                  '[class*="MarketColumnHeader"]',
                ];
                for (const selector of selectors) {
                  const header = Array.from(column.querySelectorAll(selector))
                    .filter(visible)
                    .map(textOf)
                    .find(Boolean);
                  if (header) return header;
                }
                return '';
              };
              const playerNamesFor = (column) => {
                return Array.from(column.querySelectorAll('.srb-ParticipantLabelWithTeam_Name, [class*="ParticipantLabelWithTeam_Name"]'))
                  .filter(visible)
                  .map(textOf)
                  .filter(Boolean);
              };
              const oddsValuesFor = (column) => {
                return Array.from(column.querySelectorAll('.gl-ParticipantOddsOnly, [class*="ParticipantOddsOnly"]'))
                  .filter(visible)
                  .map((participant) => {
                    const odds = Array.from(participant.querySelectorAll('.gl-ParticipantOddsOnly_Odds, [class*="ParticipantOddsOnly_Odds"], [class*="_Odds"]'))
                      .filter(visible)
                      .map(textOf)
                      .find((value) => oddsRe.test(value));
                    return odds || '';
                  });
              };
              const extractGrid = (group, market, mode) => {
                const columns = Array.from(group.querySelectorAll('.gl-Market.gl-Market_General, .gl-Market'))
                  .filter(visible);
                const playerColumn = columns.find((column) => playerNamesFor(column).length > 0);
                const players = playerColumn ? playerNamesFor(playerColumn) : [];
                if (!playerColumn || players.length === 0) {
                  return {
                    results: [],
                    unresolved: [{
                      market,
                      name: '',
                      odds: '',
                      line: '',
                      reason: 'missing player label column',
                      container: textOf(group).slice(0, 500),
                      html: clean(group.outerHTML || '').slice(0, 900),
                    }],
                  };
                }

                const oddsColumns = columns
                  .filter((column) => column !== playerColumn)
                  .map((column) => ({
                    header: columnHeaderFor(column),
                    odds: oddsValuesFor(column),
                  }))
                  .filter((column) => column.header && column.odds.length > 0);

                const results = [];
                const unresolved = [];
                for (const column of oddsColumns) {
                  const isScoreAssist = mode === 'score-assist'
                    && /^(?:score|assist|score or assist)$/i.test(column.header);
                  const isLine = mode === 'line'
                    && lineRe.test(column.header);
                  if (!isScoreAssist && !isLine) continue;

                  const count = Math.min(players.length, column.odds.length);
                  for (let index = 0; index < count; index += 1) {
                    const odds = column.odds[index] || '';
                    if (!oddsRe.test(odds)) continue;
                    results.push({
                      market,
                      name: players[index],
                      odds,
                      line: isLine ? column.header : '',
                      context: isScoreAssist ? column.header : '',
                    });
                  }
                  if (players.length !== column.odds.length) {
                    unresolved.push({
                      market,
                      name: column.header,
                      odds: '',
                      line: '',
                      reason: `column length mismatch players=${players.length} ${column.header}=${column.odds.length}`,
                      container: textOf(group).slice(0, 500),
                      html: clean(group.outerHTML || '').slice(0, 900),
                    });
                  }
                }
                if (results.length === 0) {
                  unresolved.push({
                    market,
                    name: '',
                    odds: '',
                    line: '',
                    reason: 'missing player prop odds columns',
                    container: textOf(group).slice(0, 500),
                    html: clean(group.outerHTML || '').slice(0, 900),
                  });
                }
                return {results, unresolved};
              };
              const groups = Array.from(document.querySelectorAll(
                '.gl-MarketGroupPod, .gl-MarketGroup'
              )).filter(visible);
              const results = [];
              const unresolved = [];
              for (const group of groups) {
                const title = marketTitleFor(group);
                if (/^Player to Score or Assist$/i.test(title)) {
                  const extracted = extractGrid(group, 'Player to Score or Assist', 'score-assist');
                  results.push(...extracted.results);
                  unresolved.push(...extracted.unresolved);
                } else if (/^Player Shots On Target$/i.test(title)) {
                  const extracted = extractGrid(group, 'Player Shots On Target', 'line');
                  results.push(...extracted.results);
                  unresolved.push(...extracted.unresolved);
                } else if (/^Player Shots$/i.test(title)) {
                  const extracted = extractGrid(group, 'Player Shots', 'line');
                  results.push(...extracted.results);
                  unresolved.push(...extracted.unresolved);
                }
              }
              return {results, unresolved};
            }
            """
        )
        if isinstance(extraction, list):
            candidates = extraction
            unresolved: list[dict[str, str]] = []
        else:
            unresolved = extraction.get("unresolved", [])
            candidates = extraction.get("results", [])
        self._log_unparsed_rendered_odds(unresolved, match, page.url)
        return parse_player_props_dom_items(candidates, match)

    def _extract_corners_market_odds(self, page: Any, match: Match) -> list[Selection]:
        extraction = page.evaluate(
            r"""
            () => {
              const oddsRe = /^(?:\d{1,4}\/\d{1,4}|\d+\.\d+)$/;
              const lineRe = /^[+-]?\d+(?:\.\d+)?$/;
              const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
              const textOf = (el) => clean(el?.innerText || el?.textContent || '');
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const box = el.getBoundingClientRect();
                return style && style.visibility !== 'hidden' && style.display !== 'none' && box.width > 0 && box.height > 0;
              };
              const titleSelectors = [
                '.sc-MarketGroupButtonWithStats_Text',
                '.cm-MarketGroupWithIconsButton_Text',
                '.gl-MarketGroupButton_Text',
                '[class*="MarketGroupButton"][class*="Text"]',
                '[class*="MarketGroup"][class*="Text"]',
              ];
              const columnsFor = (root) => Array.from(root.querySelectorAll('.gl-Market.gl-Market_General, .gl-Market'))
                .filter(visible);
              const marketTitleFor = (group) => {
                for (const selector of titleSelectors) {
                  const title = Array.from(group.querySelectorAll(selector))
                    .filter(visible)
                    .map(textOf)
                    .find(Boolean);
                  if (title) return title;
                }
                return '';
              };
              const columnHeaderFor = (column) => {
                const header = Array.from(column.querySelectorAll('.gl-MarketColumnHeader, [class*="MarketColumnHeader"]'))
                  .filter(visible)
                  .map(textOf)
                  .find((value) => value && value !== '\u00a0');
                return header || '';
              };
              const lineValuesFor = (column) => {
                const explicit = Array.from(column.querySelectorAll('.srb-ParticipantLabelCentered_Name, [class*="ParticipantLabelCentered_Name"]'))
                  .filter(visible)
                  .map(textOf)
                  .filter((value) => lineRe.test(value));
                if (explicit.length > 0) return explicit;
                return (column.innerText || column.textContent || '')
                  .split(/\s+/)
                  .map(clean)
                  .filter((value) => lineRe.test(value));
              };
              const oddsValuesFor = (column) => {
                return Array.from(column.querySelectorAll('.gl-ParticipantOddsOnly_Odds, [class*="ParticipantOddsOnly_Odds"], [class*="_Odds"]'))
                  .filter(visible)
                  .map(textOf)
                  .filter((value) => oddsRe.test(value));
              };
              const extractColumnMajorGrid = (group, market, acceptedHeaders) => {
                const columns = Array.from(group.querySelectorAll('.gl-Market.gl-Market_General, .gl-Market'))
                  .filter(visible);
                const lineColumn = columns.find((column) => {
                  const header = columnHeaderFor(column);
                  return !/^(?:over|under)$/i.test(header) && lineValuesFor(column).length > 0;
                });
                if (!lineColumn) {
                  return {
                    results: [],
                    unresolved: [{
                      market,
                      name: '',
                      odds: '',
                      line: '',
                      reason: 'missing corners line column',
                      container: textOf(group).slice(0, 500),
                      html: clean(group.outerHTML || '').slice(0, 900),
                    }],
                  };
                }

                const lines = lineValuesFor(lineColumn);
                const oddsColumns = columns
                  .filter((column) => column !== lineColumn)
                  .map((column) => ({
                    name: columnHeaderFor(column),
                    odds: oddsValuesFor(column),
                  }))
                  .filter((column) => column.name && column.odds.length > 0)
                  .filter((column) => !acceptedHeaders || acceptedHeaders.some((header) => header.test(column.name)));

                const results = [];
                const unresolved = [];
                for (const column of oddsColumns) {
                  const count = Math.min(lines.length, column.odds.length);
                  for (let index = 0; index < count; index += 1) {
                    results.push({market, name: column.name, odds: column.odds[index], line: lines[index], context: ''});
                  }
                  if (lines.length !== column.odds.length) {
                    unresolved.push({
                      market,
                      name: column.name,
                      odds: '',
                      line: '',
                      reason: `column length mismatch lines=${lines.length} ${column.name}=${column.odds.length}`,
                      container: textOf(group).slice(0, 500),
                      html: clean(group.outerHTML || '').slice(0, 900),
                    });
                  }
                }
                if (oddsColumns.length === 0) {
                  unresolved.push({
                    market,
                    name: '',
                    odds: '',
                    line: '',
                    reason: 'missing corners odds columns',
                    container: textOf(group).slice(0, 500),
                    html: clean(group.outerHTML || '').slice(0, 900),
                  });
                }
                return {results, unresolved};
              };
              const groups = Array.from(document.querySelectorAll(
                '.gl-MarketGroupPod.gl-MarketGroup, .gl-MarketGroupPod, .gl-MarketGroup'
              )).filter(visible);
              const results = [];
              const unresolved = [];
              for (const group of groups) {
                const title = marketTitleFor(group);
                if (/^Corners$/i.test(title)) {
                  const extracted = extractColumnMajorGrid(group, 'Corners', [/^over$/i, /^exactly$/i, /^under$/i]);
                  results.push(...extracted.results);
                  unresolved.push(...extracted.unresolved);
                } else if (/^Alternative Corners$/i.test(title)) {
                  const extracted = extractColumnMajorGrid(group, 'Alternative Corners', [/^over$/i, /^exactly$/i, /^under$/i]);
                  results.push(...extracted.results);
                  unresolved.push(...extracted.unresolved);
                } else if (/^Corners 2-Way$/i.test(title)) {
                  const extracted = extractColumnMajorGrid(group, 'Corners 2-Way', [/^over$/i, /^under$/i]);
                  results.push(...extracted.results);
                  unresolved.push(...extracted.unresolved);
                } else if (/^Corners Race$/i.test(title)) {
                  const extracted = extractColumnMajorGrid(group, 'Corners Race', null);
                  results.push(...extracted.results);
                  unresolved.push(...extracted.unresolved);
                }
              }
              return {results, unresolved};
            }
            """
        )
        if isinstance(extraction, list):
            candidates = extraction
            unresolved: list[dict[str, str]] = []
        else:
            unresolved = extraction.get("unresolved", [])
            candidates = extraction.get("results", [])
        self._log_unparsed_rendered_odds(unresolved, match, page.url)
        return parse_corners_dom_items(candidates, match)

    @staticmethod
    def _click_rendered_market_headers(page: Any, titles: Iterable[str]) -> None:
        clicked: list[str] = []
        for title in titles:
            try:
                box = page.evaluate(
                    r"""
                    (title) => {
                      const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
                      const visible = (el) => {
                        const style = window.getComputedStyle(el);
                        const box = el.getBoundingClientRect();
                        return style && style.visibility !== 'hidden' && style.display !== 'none' && box.width > 0 && box.height > 0;
                      };
                      const titleSelectors = [
                        '.sc-MarketGroupButtonWithStats_Text',
                        '.cm-MarketGroupWithIconsButton_Text',
                        '.gl-MarketGroupButton_Text',
                        '[class*="MarketGroupButton"][class*="Text"]',
                        '[class*="MarketGroup"][class*="Text"]',
                      ];
                      const wanted = clean(title).toLowerCase();
                      const element = Array.from(document.querySelectorAll(titleSelectors.join(',')))
                        .filter(visible)
                        .find((candidate) => clean(candidate.innerText || candidate.textContent).toLowerCase() === wanted);
                      if (!element) return null;
                      element.scrollIntoView({block: 'center', inline: 'nearest'});
                      const rect = element.getBoundingClientRect();
                      return {
                        x: rect.left + rect.width / 2,
                        y: rect.top + rect.height / 2,
                      };
                    }
                    """,
                    title,
                )
                if not box:
                    console_log(f"Shots market header not found for click: {title}")
                    continue
                page.mouse.click(box["x"], box["y"])
                clicked.append(title)
                page.wait_for_timeout(750)
            except Exception as exc:
                console_log(f"Could not click rendered market header {title!r}: {exc}")
        if clicked:
            console_log(f"Clicked rendered market header(s): {', '.join(clicked)}")
            page.wait_for_timeout(2000)

    def _extract_shots_market_odds(self, page: Any, match: Match) -> list[Selection]:
        self._click_rendered_market_headers(
            page,
            ["Match Shots On Target", "Match Shots", "Team Shots on Target", "Team Shots"],
        )
        extraction = page.evaluate(
            r"""
            () => {
              const oddsRe = /^(?:\d{1,4}\/\d{1,4}|\d+\.\d+)$/;
              const lineRe = /^[+-]?\d+(?:\.\d+)?$/;
              const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
              const textOf = (el) => clean(el?.innerText || el?.textContent || '');
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const box = el.getBoundingClientRect();
                return style && style.visibility !== 'hidden' && style.display !== 'none' && box.width > 0 && box.height > 0;
              };
              const titleSelectors = [
                '.sc-MarketGroupButtonWithStats_Text',
                '.cm-MarketGroupWithIconsButton_Text',
                '.gl-MarketGroupButton_Text',
                '[class*="MarketGroupButton"][class*="Text"]',
                '[class*="MarketGroup"][class*="Text"]',
              ];
              const columnsFor = (root) => Array.from(root.querySelectorAll('.gl-Market.gl-Market_General, .gl-Market'))
                .filter(visible);
              const columnHeaderFor = (column) => {
                const header = Array.from(column.querySelectorAll('.gl-MarketColumnHeader, [class*="MarketColumnHeader"]'))
                  .filter(visible)
                  .map(textOf)
                  .find((value) => value && value !== '\u00a0');
                return header || '';
              };
              const lineValuesFor = (column) => {
                const explicit = Array.from(column.querySelectorAll('.srb-ParticipantLabelCentered_Name, [class*="ParticipantLabelCentered_Name"]'))
                  .filter(visible)
                  .map(textOf)
                  .filter((value) => lineRe.test(value));
                if (explicit.length > 0) return explicit;
                return (column.innerText || column.textContent || '')
                  .split(/\s+/)
                  .map(clean)
                  .filter((value) => lineRe.test(value));
              };
              const oddsValuesFor = (column) => {
                return Array.from(column.querySelectorAll('.gl-ParticipantOddsOnly_Odds, [class*="ParticipantOddsOnly_Odds"], [class*="_Odds"]'))
                  .filter(visible)
                  .map(textOf)
                  .filter((value) => oddsRe.test(value));
              };
              const extractMatchOverUnderGrid = (group, market) => {
                const columns = columnsFor(group);
                const lineColumn = columns[0];
                const lines = lineColumn ? lineValuesFor(lineColumn) : [];
                if (!lineColumn || lines.length === 0) {
                  return {
                    results: [],
                    unresolved: [{
                      market,
                      name: '',
                      odds: '',
                      line: '',
                      reason: 'missing shots line column',
                      container: textOf(group).slice(0, 500),
                      html: clean(group.outerHTML || '').slice(0, 900),
                    }],
                  };
                }
                const oddsColumns = columns
                  .slice(1)
                  .map((column) => ({
                    name: columnHeaderFor(column),
                    odds: oddsValuesFor(column),
                  }))
                  .filter((column) => /^(?:over|under)$/i.test(column.name) && column.odds.length > 0);
                const results = [];
                const unresolved = [];
                for (const column of oddsColumns) {
                  const count = Math.min(lines.length, column.odds.length);
                  for (let index = 0; index < count; index += 1) {
                    results.push({market, name: column.name, odds: column.odds[index], line: lines[index], context: ''});
                  }
                  if (lines.length !== column.odds.length) {
                    unresolved.push({
                      market,
                      name: column.name,
                      odds: '',
                      line: '',
                      reason: `column length mismatch lines=${lines.length} ${column.name}=${column.odds.length}`,
                      container: textOf(group).slice(0, 500),
                      html: clean(group.outerHTML || '').slice(0, 900),
                    });
                  }
                }
                if (oddsColumns.length === 0) {
                  unresolved.push({
                    market,
                    name: '',
                    odds: '',
                    line: '',
                    reason: 'missing shots over/under odds columns',
                    container: textOf(group).slice(0, 500),
                    html: clean(group.outerHTML || '').slice(0, 900),
                  });
                }
                return {results, unresolved};
              };
              const extractTeamStackedGrid = (group, market) => {
                const columns = columnsFor(group);
                const results = [];
                const unresolved = [];
                for (const column of columns) {
                  const team = columnHeaderFor(column);
                  if (!team) continue;
                  const participants = Array.from(column.querySelectorAll(
                    'div.srb-ParticipantCenteredStackedWithMarketBorders2, div[class*="ParticipantCenteredStackedWithMarketBorders2"]'
                  )).filter(visible);
                  for (const participant of participants) {
                    const handicap = Array.from(participant.querySelectorAll(
                      '.srb-ParticipantCenteredStackedWithMarketBorders_Handicap, [class*="ParticipantCenteredStackedWithMarketBorders_Handicap"]'
                    )).filter(visible).map(textOf).find(Boolean) || '';
                    const odds = Array.from(participant.querySelectorAll(
                      '.srb-ParticipantCenteredStackedWithMarketBorders_Odds, [class*="ParticipantCenteredStackedWithMarketBorders_Odds"], [class*="_Odds"]'
                    )).filter(visible).map(textOf).find((value) => oddsRe.test(value)) || '';
                    const handicapMatch = /^(over|under)\s+([+-]?\d+(?:\.\d+)?)$/i.exec(handicap);
                    if (handicapMatch && odds) {
                      results.push({
                        market,
                        name: handicapMatch[1],
                        odds,
                        line: handicapMatch[2],
                        context: team,
                      });
                    } else {
                      unresolved.push({
                        market,
                        name: handicap,
                        odds,
                        line: '',
                        context: team,
                        reason: !handicapMatch ? 'missing team shots handicap' : 'missing team shots odds',
                        container: textOf(participant).slice(0, 500),
                        html: clean(participant.outerHTML || '').slice(0, 900),
                      });
                    }
                  }
                }
                if (results.length === 0) {
                  unresolved.push({
                    market,
                    name: '',
                    odds: '',
                    line: '',
                    reason: 'missing team shots stacked participants',
                    container: textOf(group).slice(0, 500),
                    html: clean(group.outerHTML || '').slice(0, 900),
                  });
                }
                return {results, unresolved};
              };
              const allTitleElements = Array.from(document.querySelectorAll(titleSelectors.join(',')))
                .filter(visible)
                .filter((element, index, elements) => elements.indexOf(element) === index)
                .filter((element) => /^(?:Match Shots On Target|Match Shots|Team Shots on Target|Team Shots)$/i.test(textOf(element)))
                .sort((left, right) => {
                  if (left === right) return 0;
                  return left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
                });
              const realGroupForTitle = (titleEl, titleIndex) => {
                let current = titleEl.parentElement;
                for (let depth = 0; current && depth < 10; depth += 1, current = current.parentElement) {
                  if (visible(current) && columnsFor(current).length > 0) return current;
                }

                const nextTitle = allTitleElements[titleIndex + 1] || null;
                const containers = Array.from(document.querySelectorAll('.gl-MarketGroupContainer, [class*="MarketGroupContainer"]'))
                  .filter(visible)
                  .filter((container) => columnsFor(container).length > 0);
                for (const container of containers) {
                  const afterTitle = titleEl.compareDocumentPosition(container) & Node.DOCUMENT_POSITION_FOLLOWING;
                  const beforeNextTitle = !nextTitle || (container.compareDocumentPosition(nextTitle) & Node.DOCUMENT_POSITION_FOLLOWING);
                  if (afterTitle && beforeNextTitle) return container;
                }
                return null;
              };
              const results = [];
              const unresolved = [];
              for (let index = 0; index < allTitleElements.length; index += 1) {
                const title = textOf(allTitleElements[index]);
                const group = realGroupForTitle(allTitleElements[index], index);
                if (!group) {
                  unresolved.push({
                    market: title,
                    name: '',
                    odds: '',
                    line: '',
                    reason: 'missing shots market content',
                    container: title,
                    html: clean(allTitleElements[index].outerHTML || '').slice(0, 900),
                  });
                  continue;
                }
                if (/^Match Shots On Target$/i.test(title)) {
                  const extracted = extractMatchOverUnderGrid(group, 'Match Shots On Target');
                  results.push(...extracted.results);
                  unresolved.push(...extracted.unresolved);
                } else if (/^Match Shots$/i.test(title)) {
                  const extracted = extractMatchOverUnderGrid(group, 'Match Shots');
                  results.push(...extracted.results);
                  unresolved.push(...extracted.unresolved);
                } else if (/^Team Shots on Target$/i.test(title)) {
                  const extracted = extractTeamStackedGrid(group, 'Team Shots on Target');
                  results.push(...extracted.results);
                  unresolved.push(...extracted.unresolved);
                } else if (/^Team Shots$/i.test(title)) {
                  const extracted = extractTeamStackedGrid(group, 'Team Shots');
                  results.push(...extracted.results);
                  unresolved.push(...extracted.unresolved);
                }
              }
              return {results, unresolved};
            }
            """
        )
        if isinstance(extraction, list):
            candidates = extraction
            unresolved: list[dict[str, str]] = []
        else:
            unresolved = extraction.get("unresolved", [])
            candidates = extraction.get("results", [])
        self._log_unparsed_rendered_odds(unresolved, match, page.url)
        return parse_shots_dom_items(candidates, match)

    def _extract_goals_market_odds(self, page: Any, match: Match) -> list[Selection]:
        extraction = page.evaluate(
            r"""
            () => {
              const oddsRe = /^(?:\d{1,4}\/\d{1,4}|\d+\.\d+)$/;
              const lineRe = /^[+-]?\d+(?:\.\d+)?$/;
              const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
              const textOf = (el) => clean(el?.innerText || el?.textContent || '');
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const box = el.getBoundingClientRect();
                return style && style.visibility !== 'hidden' && style.display !== 'none' && box.width > 0 && box.height > 0;
              };
              const marketTitleFor = (group) => {
                const titleSelectors = [
                  '.sc-MarketGroupButtonWithStats_Text',
                  '.cm-MarketGroupWithIconsButton_Text',
                  '.gl-MarketGroupButton_Text',
                  '[class*="MarketGroupButton"][class*="Text"]',
                  '[class*="MarketGroup"][class*="Text"]',
                ];
                for (const selector of titleSelectors) {
                  const title = Array.from(group.querySelectorAll(selector))
                    .filter(visible)
                    .map(textOf)
                    .find(Boolean);
                  if (title) return title;
                }
                return '';
              };
              const columnHeaderFor = (column) => {
                const header = Array.from(column.querySelectorAll('.gl-MarketColumnHeader, [class*="MarketColumnHeader"]'))
                  .filter(visible)
                  .map(textOf)
                  .find((value) => value && value !== '\u00a0');
                return header || '';
              };
              const extractTotalGoalsGrid = (group, market) => {
                const columns = Array.from(group.querySelectorAll('.gl-Market.gl-Market_General, .gl-Market'))
                  .filter(visible);
                const lineColumn = columns.find((column) => {
                  return Array.from(column.querySelectorAll('.srb-ParticipantLabelCentered_Name, [class*="ParticipantLabelCentered_Name"]'))
                    .filter(visible)
                    .map(textOf)
                    .some((value) => lineRe.test(value));
                });
                const overColumn = columns.find((column) => /^over$/i.test(columnHeaderFor(column)));
                const underColumn = columns.find((column) => /^under$/i.test(columnHeaderFor(column)));
                if (!lineColumn || !overColumn || !underColumn) {
                  return {
                    results: [],
                    unresolved: [{
                      market,
                      name: '',
                      odds: '',
                      line: '',
                      reason: 'missing total-goals line/over/under column',
                      container: textOf(group).slice(0, 500),
                      html: clean(group.outerHTML || '').slice(0, 900),
                    }],
                  };
                }
                const lines = Array.from(lineColumn.querySelectorAll('.srb-ParticipantLabelCentered_Name, [class*="ParticipantLabelCentered_Name"]'))
                  .filter(visible)
                  .map(textOf)
                  .filter((value) => lineRe.test(value));
                const overOdds = Array.from(overColumn.querySelectorAll('.gl-ParticipantOddsOnly_Odds, [class*="ParticipantOddsOnly_Odds"], [class*="_Odds"]'))
                  .filter(visible)
                  .map(textOf)
                  .filter((value) => oddsRe.test(value));
                const underOdds = Array.from(underColumn.querySelectorAll('.gl-ParticipantOddsOnly_Odds, [class*="ParticipantOddsOnly_Odds"], [class*="_Odds"]'))
                  .filter(visible)
                  .map(textOf)
                  .filter((value) => oddsRe.test(value));
                const count = Math.min(lines.length, overOdds.length, underOdds.length);
                const results = [];
                const unresolved = [];
                for (let index = 0; index < count; index += 1) {
                  results.push({market, name: 'Over', odds: overOdds[index], line: lines[index], context: ''});
                  results.push({market, name: 'Under', odds: underOdds[index], line: lines[index], context: ''});
                }
                if (lines.length !== overOdds.length || lines.length !== underOdds.length) {
                  unresolved.push({
                    market,
                    name: '',
                    odds: '',
                    line: '',
                    reason: `column length mismatch lines=${lines.length} over=${overOdds.length} under=${underOdds.length}`,
                    container: textOf(group).slice(0, 500),
                    html: clean(group.outerHTML || '').slice(0, 900),
                  });
                }
                return {results, unresolved};
              };
              const extractBothTeamsToScore = (group) => {
                const participants = Array.from(group.querySelectorAll(
                  '.gl-ParticipantBorderless.gl-Participant_General, .gl-ParticipantBorderless, [class*="ParticipantBorderless"]'
                )).filter(visible);
                const results = [];
                const unresolved = [];
                for (const participant of participants) {
                  const name = Array.from(participant.querySelectorAll('.gl-ParticipantBorderless_Name, [class*="ParticipantBorderless_Name"], [class*="Participant"][class*="Name"]'))
                    .filter(visible)
                    .map(textOf)
                    .find((value) => /^(?:yes|no)$/i.test(value)) || '';
                  const odds = Array.from(participant.querySelectorAll('.gl-ParticipantBorderless_Odds, [class*="ParticipantBorderless_Odds"], [class*="Participant"][class*="Odds"], [class*="_Odds"]'))
                    .filter(visible)
                    .map(textOf)
                    .find((value) => oddsRe.test(value)) || '';
                  const item = {
                    market: 'Both Teams To Score',
                    name,
                    odds,
                    line: '',
                    context: '',
                    container: textOf(participant).slice(0, 300),
                    html: clean(participant.outerHTML || '').slice(0, 700),
                  };
                  if (name && odds) {
                    results.push(item);
                  } else {
                    unresolved.push({
                      ...item,
                      reason: !name ? 'missing BTTS selection name' : 'missing BTTS odds',
                    });
                  }
                }
                return {results, unresolved};
              };
              const groups = Array.from(document.querySelectorAll(
                '.gl-MarketGroupPod.gl-MarketGroup, .gl-MarketGroupPod, .gl-MarketGroup'
              )).filter(visible);
              const results = [];
              const unresolved = [];
              for (const group of groups) {
                const title = marketTitleFor(group);
                if (/^Goals Over\/Under$/i.test(title)) {
                  const extracted = extractTotalGoalsGrid(group, 'Goals Over/Under');
                  results.push(...extracted.results);
                  unresolved.push(...extracted.unresolved);
                } else if (/^Alternative Total Goals$/i.test(title)) {
                  const extracted = extractTotalGoalsGrid(group, 'Alternative Total Goals');
                  results.push(...extracted.results);
                  unresolved.push(...extracted.unresolved);
                } else if (/^Both Teams To Score$/i.test(title)) {
                  const extracted = extractBothTeamsToScore(group);
                  results.push(...extracted.results);
                  unresolved.push(...extracted.unresolved);
                } else if (/^Teams to Score$/i.test(title)) {
                  unresolved.push({
                    market: 'Teams to Score',
                    name: '',
                    odds: '',
                    line: '',
                    reason: 'Teams to Score header found but parser has no option layout yet',
                    container: textOf(group).slice(0, 500),
                    html: clean(group.outerHTML || '').slice(0, 900),
                  });
                }
              }
              return {results, unresolved};
            }
            """
        )
        if isinstance(extraction, list):
            candidates = extraction
            unresolved: list[dict[str, str]] = []
        else:
            unresolved = extraction.get("unresolved", [])
            candidates = extraction.get("results", [])
        self._log_unparsed_rendered_odds(unresolved, match, page.url)
        return parse_goals_dom_items(candidates, match)

    def _extract_rendered_odds(
        self,
        page: Any,
        match: Match,
        *,
        include_player_props: bool = False,
        include_prebuilt_bets: bool = False,
    ) -> list[Selection]:
        extraction = page.evaluate(
            r"""
            () => {
              const oddsRe = /^(?:\d{1,4}\/\d{1,4}|\d+\.\d+)$/;
              const ignoredLineRe = /^(?:BB|SP|Suspended|Closed|Cash Out|Each Way)$/i;
              const marketWordRe = /\b(result|winner|goals?|corners?|cards?|shots?|teams?|score|half|handicap|draw|both|most|total|asian|booking|booked|fouls?|tackles?|offsides?|set piece|throw in|free kick|goal kick|penalt(?:y|ies)|assist)\b/i;
              const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
              const textOf = (el) => clean(el?.innerText || el?.textContent || '');
              const linesOf = (el) => (el?.innerText || el?.textContent || '')
                .split(/\n+/)
                .map(clean)
                .filter(Boolean);
              const classText = (el) => String(el?.className || '').toLowerCase();
              const hasClassPart = (el, ...parts) => {
                const classes = classText(el);
                return parts.some((part) => classes.includes(part.toLowerCase()));
              };
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const box = el.getBoundingClientRect();
                return style && style.visibility !== 'hidden' && style.display !== 'none' && box.width > 0 && box.height > 0;
              };
              const isUsefulLabel = (value) => {
                const text = clean(value);
                return text && text.length <= 120 && !oddsRe.test(text) && !ignoredLineRe.test(text);
              };
              const hasOddsDescendant = (el) => Array.from(el.querySelectorAll('*')).some((child) => {
                return child !== el && visible(child) && oddsRe.test(textOf(child));
              });
              const shortHtml = (el) => clean(el?.outerHTML || '').slice(0, 700);
              const cssPath = (el) => {
                const parts = [];
                let current = el;
                while (current && current.nodeType === Node.ELEMENT_NODE && parts.length < 6) {
                  const tag = current.tagName.toLowerCase();
                  const classes = String(current.className || '')
                    .split(/\s+/)
                    .filter(Boolean)
                    .slice(0, 3)
                    .join('.');
                  parts.push(classes ? `${tag}.${classes}` : tag);
                  current = current.parentElement;
                }
                return parts.join(' < ');
              };
              const firstLabelIn = (root, selectors, rejectText = '') => {
                for (const selector of selectors) {
                  for (const el of Array.from(root.querySelectorAll(selector)).filter(visible)) {
                    const value = textOf(el);
                    if (!isUsefulLabel(value) || value === rejectText || hasOddsDescendant(el)) continue;
                    return value;
                  }
                }
                return '';
              };
              const participantFor = (oddsEl) => {
                let current = oddsEl;
                for (let depth = 0; current && depth < 9; depth += 1, current = current.parentElement) {
                  if (!visible(current)) continue;
                  const lines = linesOf(current);
                  const text = clean(lines.join(' '));
                  const labelLines = lines.filter(isUsefulLabel);
                  const classLooksRight = hasClassPart(
                    current,
                    'Participant',
                    'selection',
                    'outcome',
                    'price',
                    'CouponParticipant',
                    'MarketCell',
                    'ParticipantOdds'
                  );
                  if (
                    current !== oddsEl
                    && text.length <= 420
                    && labelLines.length > 0
                    && (classLooksRight || lines.length <= 8)
                  ) {
                    return current;
                  }
                }
                return oddsEl.parentElement || oddsEl;
              };
              const nameFromParticipant = (participant, oddsEl, odds) => {
                const selectors = [
                  '[class*="Participant"][class*="Name"]',
                  '[class*="ParticipantName"]',
                  '[class*="Outcome"][class*="Name"]',
                  '[class*="Selection"][class*="Name"]',
                  '[class*="CouponParticipant"][class*="Text"]',
                  '[class*="Name"]',
                  '[class*="Text"]',
                  '[class*="Label"]',
                ];
                const direct = firstLabelIn(participant, selectors, odds);
                if (direct) return direct;

                const lines = linesOf(participant).filter((line) => line !== odds && isUsefulLabel(line));
                const overUnder = lines.find((line) => /^(?:over|under)$/i.test(line));
                if (overUnder) return overUnder;
                const named = lines.find((line) => !/^[+-]?\d+(?:\.\d+)?$/.test(line));
                if (named) return named;

                let sibling = oddsEl.previousElementSibling;
                while (sibling) {
                  const value = textOf(sibling);
                  if (isUsefulLabel(value) && !hasOddsDescendant(sibling)) return value;
                  sibling = sibling.previousElementSibling;
                }
                sibling = participant.previousElementSibling;
                while (sibling) {
                  const value = textOf(sibling);
                  if (isUsefulLabel(value) && !hasOddsDescendant(sibling)) return value;
                  sibling = sibling.previousElementSibling;
                }
                return '';
              };
              const lineFromParticipant = (participant, name, odds) => {
                const lines = linesOf(participant).filter((line) => line !== odds && line !== name && isUsefulLabel(line));
                return lines.find((line) => /^[+-]?\d+(?:\.\d+)?$/.test(line)) || '';
              };
              const marketFromContainer = (container, selectionName) => {
                const selectors = [
                  '.cm-MarketGroupWithIconsButton_Text',
                  '.gl-MarketGroupButton_Text',
                  '.srb-ParticipantLabelCentered_Name',
                  '[class*="MarketGroup"][class*="Header"]',
                  '[class*="MarketGroup"][class*="Text"]',
                  '[class*="MarketGroup"][class*="Name"]',
                  '[class*="Market"][class*="Header"]',
                  '[class*="Market"][class*="Title"]',
                  '[class*="Market"][class*="Name"]',
                  '[class*="Header"][class*="Text"]',
                  '[class*="Title"]',
                ];
                const direct = firstLabelIn(container, selectors, selectionName);
                if (direct && marketWordRe.test(direct)) return direct;

                for (const line of linesOf(container).slice(0, 18)) {
                  if (!isUsefulLabel(line) || line === selectionName) continue;
                  if (marketWordRe.test(line)) return line;
                }
                return '';
              };
              const marketFor = (participant, selectionName) => {
                let current = participant.parentElement;
                for (let depth = 0; current && depth < 10; depth += 1, current = current.parentElement) {
                  if (!visible(current)) continue;
                  const text = textOf(current);
                  if (text.length > 12000) break;
                  const classLooksRight = hasClassPart(
                    current,
                    'MarketGroup',
                    'MarketCoupon',
                    'MarketGrid',
                    'MarketPod',
                    'CouponMarket',
                    'gl-Market',
                    'srb-'
                  );
                  if (classLooksRight || text.length <= 5000) {
                    const market = marketFromContainer(current, selectionName);
                    if (market) return market;
                  }
                  let sibling = current.previousElementSibling;
                  for (let hops = 0; sibling && hops < 4; hops += 1, sibling = sibling.previousElementSibling) {
                    if (!visible(sibling)) continue;
                    const siblingText = textOf(sibling);
                    if (isUsefulLabel(siblingText) && marketWordRe.test(siblingText)) return siblingText;
                    const nested = marketFromContainer(sibling, selectionName);
                    if (nested) return nested;
                  }
                }
                return '';
              };
              const contextFor = (participant, selectionName, odds) => {
                const lines = linesOf(participant)
                  .filter((line) => line !== selectionName && line !== odds && isUsefulLabel(line));
                return lines.find((line) => !/^[+-]?\d+(?:\.\d+)?$/.test(line)) || '';
              };
              const oddsElements = Array.from(document.querySelectorAll('span,div,button,a'))
                .filter(visible)
                .filter((el) => oddsRe.test(textOf(el)));
              const results = [];
              const unresolved = [];
              const seen = new Set();
              for (const oddsEl of oddsElements) {
                const odds = textOf(oddsEl);
                const participant = participantFor(oddsEl);
                const name = nameFromParticipant(participant, oddsEl, odds);
                const market = name ? marketFor(participant, name) : '';
                const line = name ? lineFromParticipant(participant, name, odds) : '';
                const context = name ? contextFor(participant, name, odds) : '';
                const containerText = textOf(participant);
                const key = `${odds}\u0000${name}\u0000${market}\u0000${containerText}`;
                if (seen.has(key)) continue;
                seen.add(key);
                const item = {
                  odds,
                  name,
                  market,
                  line,
                  context,
                  container: containerText.slice(0, 700),
                  odds_class: String(oddsEl.className || ''),
                  participant_class: String(participant.className || ''),
                  path: cssPath(oddsEl),
                  html: shortHtml(participant),
                };
                if (name) {
                  results.push(item);
                }
                if (!name || !market) {
                  unresolved.push({
                    ...item,
                    reason: !name ? 'missing selection name' : 'missing market name',
                  });
                }
              }
              return {results, unresolved, total_odds_nodes: oddsElements.length};
            }
            """
        )
        if isinstance(extraction, list):
            candidates = extraction
            unresolved: list[dict[str, str]] = []
        else:
            candidates = extraction.get("results", [])
            unresolved = extraction.get("unresolved", [])
        self._log_unparsed_rendered_odds(unresolved, match, page.url)

        selections: list[Selection] = []
        seen: set[tuple[str | None, str, str]] = set()
        for selection in parse_bet365_market_group_dom_items(candidates, match):
            market = selection.market
            name = selection.name
            container = next(
                (
                    candidate.get("container") or ""
                    for candidate in candidates
                    if candidate.get("market") == market
                    and clean_selection_name(candidate.get("name") or "", match) == name
                    and candidate.get("odds") == selection.odds
                ),
                "",
            )
            searchable = f"{market or ''} {name} {container}".lower()
            if not include_player_props and any(term in searchable for term in PLAYER_RENDERED_MARKET_TERMS):
                continue
            if not include_prebuilt_bets and any(term in searchable for term in PREBUILT_RENDERED_MARKET_TERMS):
                continue
            if not include_player_props and market and market.startswith("Player "):
                continue
            key = (selection.market, selection.name, selection.odds)
            if key in seen:
                continue
            seen.add(key)
            selections.append(selection)
        if selections:
            return selections
        return parse_visible_odds_text(
            self._page_text(page),
            match,
            include_player_props=include_player_props,
            include_prebuilt_bets=include_prebuilt_bets,
        )

    @staticmethod
    def _log_unparsed_rendered_odds(unresolved: Iterable[dict[str, str]], match: Match, url: str) -> None:
        items = list(unresolved)
        samples = items[:12]
        if not samples:
            return
        console_log(
            "Unparsed rendered odds snippets "
            f"for {match.home} v {match.away} ({match.fixture_id}) at {url}: "
            f"showing {len(samples)} of {len(items)} sample(s)."
        )
        for index, item in enumerate(samples, start=1):
            snippet = re.sub(r"\s+", " ", item.get("container") or item.get("html") or "").strip()
            if len(snippet) > 240:
                snippet = snippet[:237] + "..."
            reason = item.get("reason") or "unknown"
            odds = item.get("odds") or ""
            market = item.get("market") or "?"
            name = item.get("name") or "?"
            path = item.get("path") or ""
            console_log(
                f"  [{index}] reason={reason}; market={market}; name={name}; odds={odds}; path={path}; text={snippet}"
            )

    def _extract_rendered_fixtures(self, page: Any, normalized_teams: set[str]) -> list[Match]:
        rows = page.evaluate(
            """
            () => {
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const box = el.getBoundingClientRect();
                return style && style.visibility !== 'hidden' && style.display !== 'none' && box.width > 0 && box.height > 0;
              };
              return Array.from(document.querySelectorAll('a,[role=button],button,div,span'))
                .filter(visible)
                .map((el) => ({
                  text: (el.innerText || el.textContent || '').trim(),
                  href: el.href || el.getAttribute('href') || '',
                  html: el.outerHTML.slice(0, 1000),
                }))
                .filter((item) => item.text && item.text.length < 800);
            }
            """
        )
        matches: list[Match] = []
        seen: set[str] = set()
        for row in rows:
            text = re.sub(r"\s+", " ", row.get("text", "")).strip()
            home_away = self._home_away_from_text(text, normalized_teams)
            if not home_away:
                continue
            candidate = " ".join([row.get("href", ""), row.get("html", ""), text])
            fixture_match = re.search(r"(?:#/)?AC/B1/C1/D8/E(\d+)|#AC#B1#C1#D8#E(\d+)|/E(\d+)/", candidate)
            if not fixture_match:
                continue
            fixture_id = next(group for group in fixture_match.groups() if group)
            if fixture_id in seen:
                continue
            seen.add(fixture_id)
            home, away = home_away
            matches.append(
                Match(
                    fixture_id=fixture_id,
                    home=home,
                    away=away,
                    url=topic_to_url(f"#AC#B1#C1#D8#E{fixture_id}#F3#F4#"),
                )
            )
        return matches

    @staticmethod
    def _home_away_from_text(text: str, normalized_teams: set[str]) -> tuple[str, str] | None:
        versus_match = re.search(r"(.+?)\s+v\s+(.+?)(?:\s{2,}|$)", text, re.I)
        if versus_match:
            home = versus_match.group(1).strip()
            away = versus_match.group(2).strip()
            if normalize_team(home) in normalized_teams and normalize_team(away) in normalized_teams:
                return home, away

        hits: list[tuple[int, str]] = []
        lowered = normalize_team(text)
        for team in sorted(normalized_teams, key=len, reverse=True):
            match = re.search(rf"\b{re.escape(team)}\b", lowered)
            if match:
                hits.append((match.start(), team.title()))
        hits.sort()
        deduped: list[str] = []
        for _, team in hits:
            if team not in deduped:
                deduped.append(team)
            if len(deduped) == 2:
                return deduped[0], deduped[1]
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Bet365 web odds for Premier League-like soccer matches.")
    parser.add_argument("--json", action="store_true", help="Print full JSON output.")
    parser.add_argument("--api", action="store_true", help="Use direct Bet365 content endpoints instead of rendered pages.")
    parser.add_argument("--headed", action="store_true", help="Show the browser window in rendered-page mode.")
    parser.add_argument("--no-homepage-fallback", action="store_true", help="Only query the upcoming soccer endpoint.")
    parser.add_argument("--include-player-props", action="store_true", help="Include player prop markets.")
    parser.add_argument("--include-prebuilt-bets", action="store_true", help="Include Bet365 pre-built/named bet bundles.")
    parser.add_argument("--test-mode", action="store_true", help="Only scrape detailed markets for the first discovered match.")
    parser.add_argument("--limit", type=int, default=0, help="Limit printed odds per match in text mode. Default: no limit.")
    parser.add_argument("--browser-user-data-dir", default=os.getenv("BET365_BROWSER_USER_DATA_DIR"))
    parser.add_argument(
        "--use-live-browser-profile",
        action="store_true",
        help="Launch directly against --browser-user-data-dir instead of copying it first.",
    )
    parser.add_argument(
        "--keep-open-seconds",
        type=int,
        default=0,
        help="Keep the headed browser open after scraping for this many seconds.",
    )
    parser.add_argument("--settle-ms", type=int, default=int(os.getenv("BET365_BROWSER_SETTLE_MS", "5000")))
    args = parser.parse_args()

    if args.api:
        console_log("Using direct API mode because --api was passed.")
        scraper = Bet365WebScraper(
            user_agent=os.getenv("BET365_USER_AGENT") or os.getenv("USER_AGENT") or DEFAULT_USER_AGENT,
            cookie=os.getenv("BET365_COOKIE") or os.getenv("COOKIE"),
            accept_language=os.getenv("BET365_ACCEPT_LANGUAGE") or os.getenv("ACCEPT_LANGUAGE") or "en-GB,en;q=0.9",
        )
        matches, endpoint_results = scraper.find_premier_league_matches(
            include_homepage_fallback=not args.no_homepage_fallback,
            include_player_props=args.include_player_props,
            include_prebuilt_bets=args.include_prebuilt_bets,
            max_matches=1 if args.test_mode else 0,
        )
    else:
        console_log("Using rendered browser mode.")
        scraper = Bet365RenderedPageScraper(
            user_agent=os.getenv("BET365_USER_AGENT") or os.getenv("USER_AGENT") or DEFAULT_USER_AGENT,
            accept_language=os.getenv("BET365_ACCEPT_LANGUAGE") or os.getenv("ACCEPT_LANGUAGE") or "en-GB,en;q=0.9",
            headed=args.headed,
            settle_ms=args.settle_ms,
            user_data_dir=args.browser_user_data_dir,
            clone_profile=not args.use_live_browser_profile,
            keep_open_seconds=args.keep_open_seconds,
        )
        matches, endpoint_results = scraper.find_premier_league_matches(
            include_player_props=args.include_player_props,
            include_prebuilt_bets=args.include_prebuilt_bets,
            max_matches=1 if args.test_mode else 0,
        )

    output = {
        "matches": [asdict(match) for match in matches],
        "requests": [
            {"url": result.url, "status_code": result.status_code, "bytes": result.bytes, "source": result.source}
            for result in endpoint_results
        ],
    }

    if args.json:
        print(json.dumps(output, indent=2))
        return

    for result in endpoint_results:
        print(f"{result.status_code} {result.bytes:>7} bytes {result.source} {result.url}")
    if not matches:
        print("No Premier League matches found in the fetched Bet365 payloads.")
        return
    for match in matches:
        print(f"\n{match.home} v {match.away}")
        print(f"  fixture_id: {match.fixture_id}")
        if match.start_time:
            print(f"  start_time: {match.start_time}")
        if match.competition:
            print(f"  competition: {match.competition}")
        if match.url:
            print(f"  url: {match.url}")
        print(f"  odds_count: {len(match.odds)}")
        displayed_odds = match.odds[: args.limit] if args.limit > 0 else match.odds
        grouped_odds: dict[str, list[Selection]] = {}
        for selection in displayed_odds:
            grouped_odds.setdefault(selection.market or "Unknown Market", []).append(selection)
        for market, selections in grouped_odds.items():
            print(f"  {market}")
            for selection in selections:
                line = f" {selection.line}" if selection.line and selection.line not in market else ""
                print(f"    {selection.name}{line}: {selection.odds}")
        if args.limit > 0 and len(match.odds) > args.limit:
            print(f"  ... {len(match.odds) - args.limit} more odds")


if __name__ == "__main__":
    main()
