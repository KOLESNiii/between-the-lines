"""
Upcoming-matches pipeline for the BetPredictor dashboard.

Flow (all stages report status and degrade gracefully):
  1. scrape  — run the bet365 web scraper (the user's own tool) for upcoming fixtures + odds.
  2. map     — map each scraped team name to a sofascore team_id (via raw.team_name_aliases).
  3. model   — score the fixture with the FINAL models (trained on all data) by synthesising
               a temporary rolling-feature anchor, scoring, then deleting it (nothing persists).
  4. ev      — compute EV = model_prob * decimal_odds - 1 for every priced selection.

If the scraper returns no fixtures (e.g. off-season), the result is simply
"No upcoming games" — no fabricated data.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VENV_PY = str(ROOT / "venv" / "bin" / "python")
DB_URL = os.getenv("DB_URL", "postgresql://user:pwd@localhost:5433/betting_historical_data")
CACHE_FILE = Path(__file__).resolve().parent / ".upcoming_cache.json"
SCRAPE_TIMEOUT = int(os.getenv("BET365_SCRAPE_TIMEOUT", "240"))

# Markets we both model and price.
MODEL_MARKETS = ("1x2", "btts", "total_goals")

_synth_counter = threading.Lock()
_synth_seq = [0]


# --------------------------------------------------------------------------- #
# 1. bet365 scrape
# --------------------------------------------------------------------------- #
def run_bet365_scrape(mode: str = "api", timeout: int = SCRAPE_TIMEOUT) -> dict:
    """Invoke the bet365 scraper as a subprocess and return its parsed JSON.

    `mode='api'` uses the direct content endpoints (no browser); 'rendered' drives
    a real browser (needs Playwright + a logged-in profile). Raises on failure.
    """
    cmd = [VENV_PY, "bet365_web_scraper.py", "--json"]
    if mode == "api":
        cmd.append("--api")
    proc = subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout,
        env={**os.environ},
    )
    out = proc.stdout
    # The scraper logs plain lines to stdout before emitting the pretty-printed
    # JSON document; locate the JSON object that carries "matches".
    idx = out.find('{\n  "matches"')
    if idx == -1:
        idx = out.find('{"matches"')
    if idx == -1:
        raise RuntimeError(
            f"scraper produced no JSON (exit {proc.returncode}). "
            f"stderr: {proc.stderr.strip()[:400] or 'none'} | stdout tail: {out.strip()[-300:]!r}"
        )
    try:
        return json.loads(out[idx:])
    except json.JSONDecodeError as e:
        raise RuntimeError(f"could not parse scraper JSON: {e}")


# --------------------------------------------------------------------------- #
# 2. team mapping
# --------------------------------------------------------------------------- #
def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def load_team_index(conn) -> dict[str, int]:
    idx: dict[str, int] = {}
    with conn.cursor() as c:
        c.execute("select source_team_name, team_id from raw.team_name_aliases")
        for nm, tid in c.fetchall():
            idx[_norm(nm)] = tid
        c.execute("select id, name, short_name from raw.sofascore_teams")
        for tid, name, short in c.fetchall():
            idx.setdefault(_norm(name), tid)
            if short:
                idx.setdefault(_norm(short), tid)
    return idx


def map_team(name: str, index: dict[str, int]) -> int | None:
    n = _norm(name)
    if n in index:
        return index[n]
    # loose contains match as a fallback
    for key, tid in index.items():
        if key and (key in n or n in key):
            return tid
    return None


# --------------------------------------------------------------------------- #
# 3. model scoring via synthetic feature anchor
# --------------------------------------------------------------------------- #
def _notnull_cols(cur, schema, table) -> list[str]:
    cur.execute(
        """select column_name from information_schema.columns
           where table_schema=%s and table_name=%s and is_nullable='NO'""",
        [schema, table],
    )
    return [r[0] for r in cur.fetchall()]


def _synth_value(col, ident):
    if col in ident:
        return ident[col]
    if col.startswith("has_"):
        return False
    if col.endswith("_count"):
        return 0
    return None


def _insert_synth(cur, schema, table, ident):
    cols = _notnull_cols(cur, schema, table)
    names, ph, vals = [], [], []
    for c in cols:
        names.append(c)
        if c == "refreshed_at":
            ph.append("now()")
        else:
            ph.append("%s")
            vals.append(_synth_value(c, ident))
    cur.execute(
        f'insert into {schema}.{table} ({",".join(names)}) values ({",".join(ph)})', vals
    )


def _next_sentinel() -> int:
    with _synth_counter:
        _synth_seq[0] += 1
        return -900_000_000 - _synth_seq[0] - (int(time.time()) % 100_000) * 1000


def predict_fixture(home_id: int, away_id: int, kickoff: datetime | None = None) -> dict:
    """Score one upcoming fixture with the FINAL models.

    Returns {"summary": {...}, "markets": {market_key: [{selection,line,probability}]}}.
    Inserts a temporary anchor (raw match + two feature rows), scores, then deletes it
    in a finally block so the database is left untouched.
    """
    import probabilistic_markets as pm

    sent = _next_sentinel()
    kickoff = kickoff or datetime.now(timezone.utc)
    season = _season_for(kickoff)
    with psycopg.connect(DB_URL) as conn:
        _cleanup(conn, sent)
        try:
            with conn.cursor() as c:
                row = c.execute(
                    "select tournament_id, season_id from raw.sofascore_matches order by id desc limit 1"
                ).fetchone()
                tour, seas = row if row else (None, None)
                names = dict(
                    c.execute(
                        "select id,name from raw.sofascore_teams where id in (%s,%s)"
                        % (int(home_id), int(away_id))
                    ).fetchall()
                )
                if home_id not in names or away_id not in names:
                    raise RuntimeError("unknown team id(s)")
                ts = int(kickoff.timestamp())
                c.execute(
                    """insert into raw.sofascore_matches
                       (id, sofascore_event_id, tournament_id, tournament_name, season_id,
                        season_year, start_timestamp, start_datetime, status_code,
                        status_description, home_team_id, away_team_id, raw_event)
                       values (%s,%s,%s,'Premier League',%s,%s,%s,%s,0,'Not started',%s,%s,'{}'::jsonb)""",
                    [sent, sent, tour, seas, season, ts, kickoff, home_id, away_id],
                )
                for tid, opp, side in ((home_id, away_id, "home"), (away_id, home_id, "away")):
                    ident = dict(
                        match_id=sent, sofascore_event_id=sent, season_id=seas,
                        season_year=season, start_timestamp=ts, start_datetime=kickoff,
                        match_date=kickoff.date(), team_id=tid, opponent_id=opp,
                        team_name=names[tid], opponent_name=names[opp], side=side,
                        active_player_count=11,
                    )
                    _insert_synth(c, "features", "sofascore_team_match_aggregates", ident)
                    _insert_synth(c, "features", "sofascore_team_match_features", ident)
            conn.commit()

            sources = {
                k: pm.xgb_model.MODEL_SPECS[k].default_final_model_dir
                for k in ("xg_for", "shot_quality", "fragility")
            }
            calib = pm.load_json(
                pm.probability_artifact_paths(pm.DEFAULT_FINAL_MODEL_DIR)["calibration"]
            )
            params = pm.CalibrationParams(**calib["parameters"])
            scored = pm.score_xgboost_models(DB_URL, sources, match_id=sent)
            matches = pm.build_match_inputs(scored)
            _, summary, market = pm.build_probability_outputs(matches, params, max_goals=10)

            markets: dict[str, list] = {}
            for r in market:
                mk = r["market_key"]
                if mk == "exact_score":
                    continue
                markets.setdefault(mk, []).append(
                    {
                        "selection": r["selection"],
                        "line": float(r["line"]) if r.get("line") is not None else None,
                        "probability": float(r["probability"]),
                    }
                )
            return {"summary": _jsonify(summary[0]) if summary else None, "markets": markets}
        finally:
            _cleanup(conn, sent)


def _cleanup(conn, sent):
    with conn.cursor() as c:
        c.execute("delete from features.sofascore_team_match_features where match_id=%s", [sent])
        c.execute("delete from features.sofascore_team_match_aggregates where match_id=%s", [sent])
        c.execute("delete from raw.sofascore_matches where id=%s", [sent])
    conn.commit()


def _season_for(d: datetime) -> str:
    # EPL season spans Aug→May; "26/27" style label.
    y = d.year % 100
    if d.month >= 7:
        return f"{y:02d}/{(y + 1) % 100:02d}"
    return f"{(y - 1) % 100:02d}/{y:02d}"


# --------------------------------------------------------------------------- #
# 4. odds normalisation + EV
# --------------------------------------------------------------------------- #
def normalize_odds(match: dict, home_name: str, away_name: str) -> list[dict]:
    """Map bet365 selections to (market_key, selection, line, decimal_odds)."""
    out = []
    hn, an = _norm(home_name), _norm(away_name)
    for sel in match.get("odds", []):
        if sel.get("suspended"):
            continue
        market = (sel.get("market") or "").lower()
        name = sel.get("name") or ""
        nn = _norm(name)
        dec = sel.get("decimal_odds")
        line = sel.get("line")
        if dec is None:
            continue
        mk = selkey = None
        ln = None
        if "full time result" in market or market in ("1x2", "match result"):
            mk = "1x2"
            if nn == hn or "home" in nn:
                selkey = "home"
            elif nn == an or "away" in nn:
                selkey = "away"
            elif "draw" in nn or nn == "x":
                selkey = "draw"
        elif "both teams to score" in market or market.startswith("btts"):
            mk = "btts"
            selkey = "yes" if name.lower().startswith("y") else "no" if name.lower().startswith("n") else None
        elif ("over/under" in market or "total goals" in market or "goals over" in market) and (
            "corner" not in market and "card" not in market and "team" not in market
        ):
            mk = "total_goals"
            low = name.lower()
            if low.startswith("over") or low == "o":
                selkey = "over"
            elif low.startswith("under") or low == "u":
                selkey = "under"
            ln = _parse_line(line) or _parse_line(_line_from_text(market))
        if mk and selkey:
            out.append(
                {"market_key": mk, "selection": selkey, "line": ln,
                 "decimal_odds": float(dec)}
            )
    return out


def _parse_line(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _line_from_text(s):
    m = re.search(r"(\d+\.\d+)", s or "")
    return m.group(1) if m else None


def ev_for(prob: float, decimal_odds: float):
    if prob is None or decimal_odds is None or decimal_odds <= 1:
        return None
    implied = 1.0 / decimal_odds
    return {
        "implied_probability": implied,
        "edge": prob - implied,
        "expected_value": prob * decimal_odds - 1.0,
    }


def _match_model_prob(markets: dict, market_key: str, selection: str, line):
    for r in markets.get(market_key, []):
        if r["selection"] != selection:
            continue
        if market_key == "total_goals":
            if r["line"] is not None and line is not None and abs(r["line"] - line) < 1e-6:
                return r["probability"]
        else:
            return r["probability"]
    return None


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def build_upcoming(refresh: bool = False, mode: str = "api",
                   snapshot: dict | None = None, ev_threshold: float = 0.0) -> dict:
    """Return the upcoming-matches view. Uses cache unless refresh/snapshot given."""
    if not refresh and snapshot is None:
        if CACHE_FILE.exists():
            try:
                return json.loads(CACHE_FILE.read_text())
            except Exception:
                pass
        # No cached run and not explicitly refreshing: stay idle rather than
        # firing a slow scrape on every page load.
        return {"generated_at": None, "matches": [], "stages": [],
                "message": "Click “Scrape bet365 & run models” to fetch upcoming fixtures."}

    stages = []
    result = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "matches": [], "stages": stages, "message": None}

    # ---- stage 1: scrape ----
    if snapshot is None:
        try:
            snapshot = run_bet365_scrape(mode=mode)
            n = len(snapshot.get("matches", []))
            stages.append({"stage": "scrape", "status": "ok",
                           "detail": f"bet365 returned {n} fixture(s)"})
        except Exception as e:
            stages.append({"stage": "scrape", "status": "error", "detail": str(e)[:300]})
            result["message"] = "Could not reach bet365 — see pipeline status below."
            _save_cache(result)
            return result
    else:
        stages.append({"stage": "scrape", "status": "ok",
                       "detail": f"injected snapshot ({len(snapshot.get('matches', []))} fixture(s))"})

    raw_matches = snapshot.get("matches", [])
    if not raw_matches:
        result["message"] = "No upcoming games."
        _save_cache(result)
        return result

    # ---- stages 2-4 ----
    mapped = modelled = priced = 0
    with psycopg.connect(DB_URL) as conn:
        index = load_team_index(conn)

    for m in raw_matches:
        home_name, away_name = m.get("home"), m.get("away")
        entry = {
            "home": home_name, "away": away_name,
            "competition": m.get("competition"), "start_time": m.get("start_time"),
            "fixture_id": m.get("fixture_id"),
            "home_team_id": None, "away_team_id": None,
            "model": None, "selections": [], "best_ev": None, "notes": [],
        }
        hid = map_team(home_name or "", index)
        aid = map_team(away_name or "", index)
        entry["home_team_id"], entry["away_team_id"] = hid, aid
        if not hid or not aid:
            entry["notes"].append("could not map one or both teams to a known club")
            result["matches"].append(entry)
            continue
        mapped += 1

        # model
        try:
            kickoff = _parse_dt(m.get("start_time"))
            pred = predict_fixture(hid, aid, kickoff)
            entry["model"] = pred["summary"]
            modelled += 1
        except Exception as e:
            entry["notes"].append(f"model scoring failed: {str(e)[:160]}")
            result["matches"].append(entry)
            continue

        # odds + EV
        odds = normalize_odds(m, home_name, away_name)
        sels = []
        for o in odds:
            p = _match_model_prob(pred["markets"], o["market_key"], o["selection"], o["line"])
            ev = ev_for(p, o["decimal_odds"]) if p is not None else None
            sels.append({
                "market_key": o["market_key"], "selection": o["selection"],
                "line": o["line"], "decimal_odds": o["decimal_odds"],
                "model_probability": p,
                "expected_value": ev["expected_value"] if ev else None,
                "edge": ev["edge"] if ev else None,
                "implied_probability": ev["implied_probability"] if ev else None,
            })
        sels.sort(key=lambda s: (s["expected_value"] is None, -(s["expected_value"] or 0)))
        entry["selections"] = sels
        evs = [s["expected_value"] for s in sels if s["expected_value"] is not None]
        entry["best_ev"] = max(evs) if evs else None
        if odds:
            priced += 1
        else:
            entry["notes"].append("no priced markets matched (1x2/btts/total_goals)")
        result["matches"].append(entry)

    stages.append({"stage": "map", "status": "ok" if mapped else "warn",
                   "detail": f"{mapped}/{len(raw_matches)} fixtures mapped to known clubs"})
    stages.append({"stage": "model", "status": "ok" if modelled else "warn",
                   "detail": f"{modelled} fixture(s) scored with final models"})
    stages.append({"stage": "ev", "status": "ok" if priced else "warn",
                   "detail": f"{priced} fixture(s) had priced markets for EV"})
    # rank matches by best EV
    result["matches"].sort(key=lambda e: (e["best_ev"] is None, -(e["best_ev"] or 0)))
    _save_cache(result)
    return result


def _parse_dt(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _jsonify(obj):
    """Coerce a row of model outputs to JSON-native types (handles numpy/Decimal)."""
    out = {}
    for k, v in obj.items():
        if isinstance(v, (str, bool)) or v is None:
            out[k] = v
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                out[k] = str(v)
    return out


def _save_cache(result):
    try:
        CACHE_FILE.write_text(json.dumps(result, default=str))
    except Exception:
        pass
