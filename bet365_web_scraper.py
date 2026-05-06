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
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from fractions import Fraction
from typing import Any, Iterable
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit

import requests


BET365_URL = "https://www.bet365.com/"
UPCOMING_SOCCER_HASH = "#/AC/B1/C1/D1002/G40/J99/I1/Q1/F%5E2002/"
UPCOMING_SOCCER_TOPIC = "#AC#B1#C1#D1002#G40#J99#I1#Q1#F^2002#"

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


@dataclass
class Selection:
    id: str | None
    name: str
    odds: str
    decimal_odds: float | None = None
    market: str | None = None


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


@dataclass
class HttpResponse:
    url: str
    status_code: int
    text: str

    @property
    def content(self) -> bytes:
        return self.text.encode("utf-8")

    def json(self) -> Any:
        return json.loads(self.text)

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


def parse_matches(payload: str) -> list[Match]:
    fixtures: dict[str, Match] = {}
    current_market_by_fixture: dict[str, str] = {}
    current_selection_by_fixture: dict[str, str] = {}

    for node_type, data in iter_nodes(payload):
        fixture_id = data.get("FI") or data.get("PF") or data.get("OI")

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
            continue

        if not fixture_id:
            continue

        if node_type in {"MG", "MA"}:
            market_name = data.get("MN") or data.get("NA")
            if market_name and market_name.strip() and market_name not in {"1", "X", "2"}:
                current_market_by_fixture[fixture_id] = market_name
            if node_type == "MA" and data.get("NA") in {"1", "X", "2"}:
                current_selection_by_fixture[fixture_id] = data["NA"]
                current_market_by_fixture.setdefault(fixture_id, "Full Time Result")

        if data.get("OD") and fixture_id in fixtures:
            selection_name = data.get("NA") or current_selection_by_fixture.get(fixture_id) or data.get("ID") or "Selection"
            market_name = data.get("MN") or current_market_by_fixture.get(fixture_id)
            selection = Selection(
                id=data.get("ID"),
                name=selection_name,
                odds=data["OD"],
                decimal_odds=fractional_to_decimal(data["OD"]),
                market=market_name,
            )
            fixtures[fixture_id].odds.append(selection)

    return list(fixtures.values())


def topic_to_hash(topic: str) -> str:
    return "#/" + topic.strip("#").replace("#", "/") + "/"


def topic_to_url(topic: str) -> str:
    return BET365_URL + topic_to_hash(topic)


class Bet365WebScraper:
    def __init__(self, user_agent: str = DEFAULT_USER_AGENT, timeout: int = 20) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-GB,en;q=0.9",
            }
        )
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

    def fetch_topic(self, topic: str) -> EndpointResult:
        if not self.flashvars or not self.routing:
            self.bootstrap()
        endpoint, qs_params = self._endpoint_for_topic(topic)
        url = self._build_content_url(endpoint, topic, qs_params)
        response = self._get(
            url,
            headers={"Accept": "*/*", "Referer": topic_to_url(topic)},
        )
        return EndpointResult(url=url, status_code=response.status_code, bytes=len(response.content), body=response.text)

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
        )

    def find_premier_league_matches(
        self,
        teams: set[str] | None = None,
        include_homepage_fallback: bool = True,
    ) -> tuple[list[Match], list[EndpointResult]]:
        normalized_teams = {normalize_team(team) for team in (teams or DEFAULT_PREMIER_LEAGUE_TEAMS)}
        results: list[EndpointResult] = []
        matches: list[Match] = []

        upcoming = self.fetch_topic(UPCOMING_SOCCER_TOPIC)
        results.append(upcoming)
        if upcoming.body:
            matches.extend(parse_matches(upcoming.body))

        if include_homepage_fallback:
            homepage = self.fetch_homepage_pods()
            results.append(homepage)
            if homepage.body:
                matches.extend(parse_matches(homepage.body))

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Bet365 web odds for Premier League-like soccer matches.")
    parser.add_argument("--json", action="store_true", help="Print full JSON output.")
    parser.add_argument("--no-homepage-fallback", action="store_true", help="Only query the upcoming soccer endpoint.")
    args = parser.parse_args()

    scraper = Bet365WebScraper()
    matches, endpoint_results = scraper.find_premier_league_matches(
        include_homepage_fallback=not args.no_homepage_fallback
    )

    output = {
        "matches": [asdict(match) for match in matches],
        "requests": [
            {"url": result.url, "status_code": result.status_code, "bytes": result.bytes}
            for result in endpoint_results
        ],
    }

    if args.json:
        print(json.dumps(output, indent=2))
        return

    for result in endpoint_results:
        print(f"{result.status_code} {result.bytes:>7} bytes {result.url}")
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
        for selection in match.odds[:12]:
            market = f" [{selection.market}]" if selection.market else ""
            print(f"  {selection.name}: {selection.odds}{market}")


if __name__ == "__main__":
    main()
