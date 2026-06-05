#!/usr/bin/env python3
"""
BetPredictor local dashboard.

Zero-dependency (stdlib http.server + psycopg, both already in the venv).
Serves a JSON API + a single-page multi-view frontend, and proxies the
graphify knowledge-graph artifacts.

Run:
    ./venv/bin/python dashboard/app.py            # http://localhost:8000
    DB_URL=... PORT=8000 ./venv/bin/python dashboard/app.py

The default DB_URL points at the BetPredictor postgres started on host
port 5433 (see dashboard/run.sh). Override with the DB_URL env var.
"""
from __future__ import annotations

import json
import os
import re
import traceback
from datetime import datetime, date
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import psycopg

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
MODELS_DIR = ROOT / "models"
GRAPH_DIR = ROOT / "graphify-out"

DB_URL = os.getenv("DB_URL", "postgresql://user:pwd@localhost:5433/betting_historical_data")
PORT = int(os.getenv("PORT", "8000"))

# Latest "final" probability run drives the predictions views by default.
DEFAULT_RUN_SQL = (
    "select id from model_outputs.market_probability_runs "
    "where mode='final' order by created_at desc limit 1"
)


# --------------------------------------------------------------------------- #
# DB helpers
# --------------------------------------------------------------------------- #
_conn = None


def get_conn():
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg.connect(DB_URL, autocommit=True)
    return _conn


def q(sql, params=None):
    """Run a query, return list[dict]. Reconnects once on a dropped conn."""
    for attempt in range(2):
        try:
            conn = get_conn()
            with conn.cursor() as cur:
                cur.execute(sql, params or [])
                if cur.description is None:
                    return []
                cols = [c.name for c in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        except (psycopg.OperationalError, psycopg.InterfaceError):
            global _conn
            _conn = None
            if attempt == 1:
                raise
    return []


def q1(sql, params=None):
    rows = q(sql, params)
    return rows[0] if rows else None


def default_run_id():
    r = q1(DEFAULT_RUN_SQL)
    return r["id"] if r else None


# --------------------------------------------------------------------------- #
# JSON encoding for psycopg types
# --------------------------------------------------------------------------- #
class Enc(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return super().default(o)


# --------------------------------------------------------------------------- #
# API endpoints
# --------------------------------------------------------------------------- #
def api_overview(_):
    counts = q1(
        """
        select
          (select count(*) from raw.sofascore_matches)                       as matches,
          (select count(*) from raw.sofascore_matches where home_score is not null) as played,
          (select count(*) from raw.sofascore_teams)                         as teams,
          (select count(*) from raw.sofascore_players)                       as players,
          (select count(*) from features.sofascore_team_match_features)      as team_features,
          (select count(*) from model_outputs.market_probability_runs)       as prob_runs,
          (select count(*) from model_outputs.market_probabilities)          as probabilities,
          (select count(*) from model_outputs.match_simulation_runs)         as sim_runs,
          (select count(*) from model_outputs.player_simulation_market_summaries) as player_props
        """
    )
    by_season = q(
        """
        select season_year,
               count(*) as matches,
               sum(case when home_score is not null then 1 else 0 end) as played,
               round(avg(home_score + away_score)::numeric, 2) as avg_goals
        from raw.sofascore_matches
        group by season_year order by season_year
        """
    )
    goals = q(
        """
        select (home_score + away_score) as total_goals, count(*) as n
        from raw.sofascore_matches
        where home_score is not null
        group by 1 order by 1
        """
    )
    results = q(
        """
        select case
                 when home_score > away_score then 'Home'
                 when home_score < away_score then 'Away'
                 else 'Draw' end as result,
               count(*) as n
        from raw.sofascore_matches
        where home_score is not null
        group by 1
        """
    )
    runs = q(
        """
        select id, run_name, mode, validation_season, created_at
        from model_outputs.market_probability_runs
        order by created_at desc limit 8
        """
    )
    latest = q1(
        """
        select max(start_datetime) as last_match,
               min(start_datetime) as first_match
        from raw.sofascore_matches
        """
    )
    return {
        "counts": counts,
        "by_season": by_season,
        "goals": goals,
        "results": results,
        "recent_runs": runs,
        "range": latest,
        "default_run": default_run_id(),
    }


def api_matches(qs):
    season = qs.get("season", [""])[0]
    team = qs.get("team", [""])[0]
    search = qs.get("q", [""])[0].strip()
    limit = min(int(qs.get("limit", ["100"])[0]), 500)
    offset = int(qs.get("offset", ["0"])[0])

    where, params = [], []
    if season:
        where.append("m.season_year = %s")
        params.append(season)
    if team:
        where.append("(m.home_team_id = %s or m.away_team_id = %s)")
        params += [int(team), int(team)]
    if search:
        where.append("(ht.name ilike %s or at.name ilike %s)")
        params += [f"%{search}%", f"%{search}%"]
    wsql = ("where " + " and ".join(where)) if where else ""

    total = q1(
        f"""select count(*) as n
            from raw.sofascore_matches m
            join raw.sofascore_teams ht on ht.id = m.home_team_id
            join raw.sofascore_teams at on at.id = m.away_team_id
            {wsql}""",
        params,
    )["n"]
    rows = q(
        f"""
        select m.id, m.season_year, m.start_datetime, m.tournament_name,
               m.home_team_id, m.away_team_id,
               ht.name as home, at.name as away,
               m.home_score, m.away_score, m.status_description
        from raw.sofascore_matches m
        join raw.sofascore_teams ht on ht.id = m.home_team_id
        join raw.sofascore_teams at on at.id = m.away_team_id
        {wsql}
        order by m.start_datetime desc nulls last
        limit %s offset %s
        """,
        params + [limit, offset],
    )
    return {"total": total, "rows": rows, "limit": limit, "offset": offset}


def api_match(qs):
    mid = int(qs["id"][0])
    run = int(qs.get("run", [default_run_id()])[0]) if default_run_id() else None
    match = q1(
        """
        select m.id, m.season_year, m.start_datetime, m.tournament_name,
               m.home_team_id, m.away_team_id,
               ht.name as home, at.name as away,
               m.home_score, m.away_score, m.status_description
        from raw.sofascore_matches m
        join raw.sofascore_teams ht on ht.id = m.home_team_id
        join raw.sofascore_teams at on at.id = m.away_team_id
        where m.id = %s
        """,
        [mid],
    )
    feats = q(
        """
        select side, team_name, opponent_name, goals_for, goals_against,
               xg, xg_against, total_shots, shots_on_target, big_chances,
               possession_proxy, pass_accuracy, total_pass, saves
        from features.sofascore_team_match_features
        where match_id = %s order by side desc
        """,
        [mid],
    )
    probs = q(
        """
        select market_key, selection, line, probability
        from model_outputs.market_probabilities
        where match_id = %s and run_id = %s
          and market_key in ('1x2','btts','total_goals')
        order by market_key, line nulls first, selection
        """,
        [mid, run],
    )
    sims = q(
        """
        select market_key, selection, line, simulated_probability
        from model_outputs.match_simulation_market_summaries
        where match_id = %s and market_key in ('1x2','btts','total_goals')
        order by market_key, line nulls first, selection
        """,
        [mid],
    )
    # top exact scores by probability
    scores = q(
        """
        select selection, probability
        from model_outputs.market_probabilities
        where match_id = %s and run_id = %s and market_key = 'exact_score'
        order by probability desc limit 10
        """,
        [mid, run],
    )
    props = q(
        """
        select player_name, player_position, market_key, line,
               simulated_probability, simulated_mean
        from model_outputs.player_simulation_market_summaries
        where match_id = %s
        order by simulated_mean desc nulls last, player_name limit 60
        """,
        [mid],
    )
    return {
        "match": match,
        "features": feats,
        "probabilities": probs,
        "simulations": sims,
        "exact_scores": scores,
        "player_props": props,
        "run": run,
    }


def api_teams(_):
    rows = q(
        """
        select t.id, t.name, t.short_name, t.country_name,
               count(f.match_id) as matches,
               round(avg(f.goals_for)::numeric, 2)   as gf,
               round(avg(f.goals_against)::numeric,2) as ga,
               round(avg(f.xg)::numeric, 2)          as xg,
               round(avg(f.xg_against)::numeric, 2)  as xga,
               round(avg(f.total_shots)::numeric, 1) as shots
        from raw.sofascore_teams t
        left join features.sofascore_team_match_features f on f.team_id = t.id
        group by t.id, t.name, t.short_name, t.country_name
        order by matches desc, t.name
        """
    )
    return {"rows": rows}


def api_team(qs):
    tid = int(qs["id"][0])
    info = q1("select id, name, short_name, country_name from raw.sofascore_teams where id=%s", [tid])
    form = q(
        """
        select f.match_date, f.side, f.opponent_name, f.goals_for, f.goals_against,
               f.xg, f.xg_against, f.total_shots, f.shots_on_target, f.possession_proxy,
               f.season_year
        from features.sofascore_team_match_features f
        where f.team_id = %s and f.match_date is not null
        order by f.match_date
        """,
        [tid],
    )
    agg = q(
        """
        select season_year,
               count(*) as matches,
               round(avg(goals_for)::numeric,2)  as gf,
               round(avg(goals_against)::numeric,2) as ga,
               round(avg(xg)::numeric,2)         as xg,
               round(avg(xg_against)::numeric,2) as xga
        from features.sofascore_team_match_features
        where team_id = %s group by season_year order by season_year
        """,
        [tid],
    )
    return {"team": info, "form": form, "by_season": agg}


def api_players(qs):
    search = qs.get("q", [""])[0].strip()
    limit = min(int(qs.get("limit", ["100"])[0]), 500)
    where, params = [], []
    if search:
        where.append("p.name ilike %s")
        params.append(f"%{search}%")
    wsql = ("where " + " and ".join(where)) if where else ""
    rows = q(
        f"""
        select p.id, p.name, p.short_name, p.position, p.country_name
        from raw.sofascore_players p
        {wsql}
        order by p.name limit %s
        """,
        params + [limit],
    )
    return {"rows": rows}


def api_probabilities(qs):
    run = int(qs.get("run", [default_run_id()])[0])
    market = qs.get("market", ["1x2"])[0]
    match = qs.get("match", [""])[0]
    limit = min(int(qs.get("limit", ["200"])[0]), 1000)
    offset = int(qs.get("offset", ["0"])[0])
    where = ["mp.run_id = %s", "mp.market_key = %s"]
    params = [run, market]
    if match:
        where.append("mp.match_id = %s")
        params.append(int(match))
    wsql = "where " + " and ".join(where)
    total = q1(
        f"select count(*) as n from model_outputs.market_probabilities mp {wsql}", params
    )["n"]
    rows = q(
        f"""
        select mp.match_id, ht.name as home, at.name as away, m.season_year,
               m.home_score, m.away_score,
               mp.selection, mp.line, mp.probability
        from model_outputs.market_probabilities mp
        join raw.sofascore_matches m on m.id = mp.match_id
        join raw.sofascore_teams ht on ht.id = m.home_team_id
        join raw.sofascore_teams at on at.id = m.away_team_id
        {wsql}
        order by mp.match_id desc, mp.line nulls first, mp.selection
        limit %s offset %s
        """,
        params + [limit, offset],
    )
    return {"total": total, "rows": rows, "run": run, "market": market}


def api_runs(_):
    prob = q(
        """
        select id, run_name, mode, validation_season, train_seasons,
               created_at, metrics
        from model_outputs.market_probability_runs
        order by created_at desc
        """
    )
    sim = q(
        """
        select id, run_name, mode, draws, seed, created_at,
               probability_run_id, player_prop_run_id, metrics
        from model_outputs.match_simulation_runs
        order by created_at desc
        """
    )
    return {"probability_runs": prob, "simulation_runs": sim}


def api_player_props(qs):
    match = qs.get("match", [""])[0]
    player = qs.get("player", [""])[0].strip()
    market = qs.get("market", [""])[0]
    limit = min(int(qs.get("limit", ["200"])[0]), 1000)
    where, params = [], []
    if match:
        where.append("match_id = %s")
        params.append(int(match))
    if player:
        where.append("player_name ilike %s")
        params.append(f"%{player}%")
    if market:
        where.append("market_key = %s")
        params.append(market)
    wsql = ("where " + " and ".join(where)) if where else ""
    rows = q(
        f"""
        select match_id, player_name, player_position, team_id,
               market_key, line, simulated_probability, simulated_mean,
               source_expected_value
        from model_outputs.player_simulation_market_summaries
        {wsql}
        order by simulated_mean desc nulls last
        limit %s
        """,
        params + [limit],
    )
    return {"rows": rows}


def api_value(qs):
    """Surface edges: where the calibrated model probability disagrees most
    with the Monte-Carlo simulation for the same market — a sanity / value
    signal. Also the strongest model convictions per market."""
    run = int(qs.get("run", [default_run_id()])[0])
    market = qs.get("market", ["1x2"])[0]
    limit = min(int(qs.get("limit", ["50"])[0]), 200)
    disagree = q(
        """
        select mp.match_id, ht.name as home, at.name as away, m.season_year,
               mp.selection, mp.line,
               mp.probability as model_p,
               s.simulated_probability as sim_p,
               abs(mp.probability - s.simulated_probability) as gap
        from model_outputs.market_probabilities mp
        join model_outputs.match_simulation_market_summaries s
          on s.match_id = mp.match_id and s.market_key = mp.market_key
         and s.selection = mp.selection
         and coalesce(s.line,-99) = coalesce(mp.line,-99)
        join raw.sofascore_matches m on m.id = mp.match_id
        join raw.sofascore_teams ht on ht.id = m.home_team_id
        join raw.sofascore_teams at on at.id = m.away_team_id
        where mp.run_id = %s and mp.market_key = %s
        order by gap desc limit %s
        """,
        [run, market, limit],
    )
    conviction = q(
        """
        select mp.match_id, ht.name as home, at.name as away, m.season_year,
               mp.selection, mp.line, mp.probability,
               m.home_score, m.away_score
        from model_outputs.market_probabilities mp
        join raw.sofascore_matches m on m.id = mp.match_id
        join raw.sofascore_teams ht on ht.id = m.home_team_id
        join raw.sofascore_teams at on at.id = m.away_team_id
        where mp.run_id = %s and mp.market_key = %s
        order by mp.probability desc limit %s
        """,
        [run, market, limit],
    )
    return {"disagreements": disagree, "convictions": conviction, "run": run, "market": market}


def api_models(_):
    """Read model artifacts from disk."""
    out = []
    for d in sorted(MODELS_DIR.iterdir()):
        if not d.is_dir():
            continue
        meta = _read_json(d / "metadata.json")
        val = _read_json(d / "validation_metrics.json")
        calib = (d / "calibration.json").exists()
        feats = _read_json(d / "feature_columns.json")
        nfeat = len(feats) if isinstance(feats, list) else (
            len(feats.get("feature_columns", [])) if isinstance(feats, dict) else None
        )
        out.append(
            {
                "name": d.name,
                "has_metadata": meta is not None,
                "metadata": meta,
                "validation_metrics": val,
                "has_calibration": calib,
                "n_features": nfeat,
                "files": sorted(f.name for f in d.iterdir() if f.is_file()),
            }
        )
    return {"models": out}


def _read_json(p: Path):
    try:
        if p.exists() and p.stat().st_size < 5_000_000:
            return json.loads(p.read_text())
    except Exception:
        return None
    return None


def api_graph_report(_):
    f = GRAPH_DIR / "GRAPH_REPORT.md"
    return {"markdown": f.read_text() if f.exists() else "# No graph report found"}


_graph_cache = None


def api_graph_data(qs):
    """Summaries + node search over graphify-out/graph.json."""
    global _graph_cache
    if _graph_cache is None:
        f = GRAPH_DIR / "graph.json"
        _graph_cache = json.loads(f.read_text()) if f.exists() else {"nodes": [], "edges": []}
    g = _graph_cache
    nodes = g.get("nodes", [])
    edges = g.get("links", g.get("edges", []))

    search = qs.get("q", [""])[0].strip().lower()
    if "q" in qs:
        def label(n):
            return str(n.get("label") or n.get("id") or n.get("name") or "")
        hits = [n for n in nodes if search in label(n).lower()][:100]
        return {"results": [_node_brief(n) for n in hits], "count": len(hits)}

    # degree ranking
    deg = {}
    for e in edges:
        s = e.get("source") or e.get("from")
        t = e.get("target") or e.get("to")
        deg[s] = deg.get(s, 0) + 1
        deg[t] = deg.get(t, 0) + 1
    ranked = sorted(nodes, key=lambda n: deg.get(n.get("id"), 0), reverse=True)[:25]
    god = [{**_node_brief(n), "degree": deg.get(n.get("id"), 0)} for n in ranked]
    return {
        "n_nodes": len(nodes),
        "n_edges": len(edges),
        "god_nodes": god,
    }


def _node_brief(n):
    return {
        "id": n.get("id"),
        "label": n.get("label") or n.get("norm_label") or n.get("id"),
        "type": n.get("file_type") or n.get("type"),
        "file": n.get("source_file") or n.get("file"),
        "community": n.get("community"),
    }


ROUTES = {
    "/api/overview": api_overview,
    "/api/matches": api_matches,
    "/api/match": api_match,
    "/api/teams": api_teams,
    "/api/team": api_team,
    "/api/players": api_players,
    "/api/probabilities": api_probabilities,
    "/api/runs": api_runs,
    "/api/player-props": api_player_props,
    "/api/value": api_value,
    "/api/models": api_models,
    "/api/graph/report": api_graph_report,
    "/api/graph/data": api_graph_data,
}


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # quiet

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, cls=Enc).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            if path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")

            if path in ROUTES:
                return self._send(200, ROUTES[path](qs))

            # graphify interactive graph + assets
            if path == "/graph" or path == "/graph.html":
                return self._serve_file(GRAPH_DIR / "graph.html", "text/html")
            if path.startswith("/graphify-out/"):
                rel = path[len("/graphify-out/"):]
                return self._serve_file(GRAPH_DIR / rel)

            # static frontend
            if path == "/" or path == "/index.html":
                return self._serve_file(STATIC / "index.html", "text/html")
            if path.startswith("/static/"):
                return self._serve_file(STATIC / path[len("/static/"):])

            return self._send(404, {"error": "not found", "path": path})
        except BrokenPipeError:
            pass
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": str(e)})

    def _serve_file(self, p: Path, ctype=None):
        if not p.exists() or not p.is_file():
            return self._send(404, {"error": "file not found", "path": str(p)})
        if ctype is None:
            ext = p.suffix.lower()
            ctype = {
                ".html": "text/html", ".js": "text/javascript",
                ".css": "text/css", ".json": "application/json",
                ".png": "image/png", ".svg": "image/svg+xml",
            }.get(ext, "application/octet-stream")
        data = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass


def main():
    print(f"BetPredictor dashboard")
    print(f"  DB:   {DB_URL}")
    print(f"  URL:  http://localhost:{PORT}")
    try:
        r = default_run_id()
        print(f"  Default probability run: {r}")
    except Exception as e:
        print(f"  WARNING: could not reach DB: {e}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
