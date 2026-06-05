"""Vectorised reimplementation of the probabilistic-markets structural model
(lambda construction -> Dixon-Coles Poisson grid -> 1x2/btts/totals + scoreline).
Validated cell-for-cell against probabilistic_markets.py so it can drive fast
coordinate-descent fitting and walk-forward backtests.
"""
import numpy as np
import probabilistic_markets as pm

G = pm.DEFAULT_MAX_GOALS            # 12
LINES = pm.DEFAULT_TOTAL_LINES      # (0.5,1.5,2.5,3.5,4.5)
LMIN, LMAX = pm.LAMBDA_CLIP_RANGE
EPS = pm.EPSILON

_k = np.arange(G + 1)
_logfact = np.array([0.0] + list(np.cumsum(np.log(np.arange(1, G + 1)))))  # log k!
_H = _k[:, None]            # (G+1,1) home goals
_A = _k[None, :]            # (1,G+1) away goals
_diag = (_H == _A)
_home_gt = (_H > _A)
_btts_no = (_H == 0) | (_A == 0)
_over_masks = {ln: (_H + _A > ln) for ln in LINES}


def to_arrays(matches):
    f = lambda key, d: np.array([pm.coalesce_float(m.get(key), d) for m in matches], float)
    return {
        "xg_home": f("xg_home", 0.0), "xg_away": f("xg_away", 0.0),
        "frag_home": np.array([pm.coalesce_float(m.get("fragility_home"), np.nan) for m in matches]),
        "frag_away": np.array([pm.coalesce_float(m.get("fragility_away"), np.nan) for m in matches]),
        "tempo": np.array([pm.coalesce_float(m.get("match_tempo_index"), np.nan) for m in matches]),
        "hg": np.array([int(m["home_goals"]) for m in matches]),
        "ag": np.array([int(m["away_goals"]) for m in matches]),
        "season": [str(m["season_year"]) for m in matches],
    }


def poisson_pmf(lam):
    """lam: (M,) -> (M, G+1)"""
    lam = np.clip(lam, EPS, None)
    logp = -lam[:, None] + _k[None, :] * np.log(lam[:, None]) - _logfact[None, :]
    return np.exp(logp)


def construct_lambdas(a, p):
    league_frag = p["league_avg_fragility"]; league_tempo = p["league_avg_tempo_index"]
    frag_home = np.where(np.isnan(a["frag_home"]), league_frag, a["frag_home"])
    frag_away = np.where(np.isnan(a["frag_away"]), league_frag, a["frag_away"])
    tempo = np.where(np.isnan(a["tempo"]), league_tempo, a["tempo"])
    tmult = np.clip(1.0 + p["tempo_beta"] * (tempo - league_tempo),
                    p.get("tempo_multiplier_min", 0.75), p.get("tempo_multiplier_max", 1.30))
    gamma = p.get("xg_power", 1.0)
    xgh, xga = a["xg_home"], a["xg_away"]
    if gamma != 1.0:
        xgh = np.power(np.clip(xgh, EPS, None), gamma)
        xga = np.power(np.clip(xga, EPS, None), gamma)
    lh = tmult * p["home_multiplier"] * xgh * (1.0 + p["alpha"] * (frag_away - league_frag))
    la = tmult * p["away_multiplier"] * xga * (1.0 + p["alpha"] * (frag_home - league_frag))
    return np.clip(lh, LMIN, LMAX), np.clip(la, LMIN, LMAX)


def grids(lh, la, rho):
    """Return normalised (M, G+1, G+1) Dixon-Coles grids."""
    ph = poisson_pmf(lh); pa = poisson_pmf(la)              # (M,G+1)
    grid = ph[:, :, None] * pa[:, None, :]                  # (M,G+1,G+1)
    # Dixon-Coles tau on the four low-score corners
    grid[:, 0, 0] *= (1.0 - lh * la * rho)
    grid[:, 0, 1] *= (1.0 + lh * rho)
    grid[:, 1, 0] *= (1.0 + la * rho)
    grid[:, 1, 1] *= (1.0 - rho)
    np.clip(grid, 0.0, None, out=grid)
    grid /= grid.sum(axis=(1, 2), keepdims=True)
    return grid


def market_probs(grid):
    home = grid[:, _home_gt].sum(1)
    draw = grid[:, _diag].sum(1)
    away = 1.0 - home - draw
    btts_yes = 1.0 - grid[:, _btts_no].sum(1)
    overs = {ln: grid[:, _over_masks[ln]].sum(1) for ln in LINES}
    return home, draw, away, btts_yes, overs


def structural_metrics(a, p):
    """Pre-calibrator metrics matching pm.evaluate_matches (no market calibrators)."""
    lh, la = construct_lambdas(a, p)
    grid = grids(lh, la, p["rho"])
    home, draw, away, btts_yes, overs = market_probs(grid)
    hg, ag = a["hg"], a["ag"]
    # 1x2 log loss / brier
    oc = np.stack([home, draw, away], 1)
    oc = np.clip(oc, EPS, 1.0)
    y = np.where(hg > ag, 0, np.where(ag > hg, 2, 1))
    ll_1x2 = -np.log(oc[np.arange(len(y)), y]).mean()
    onehot = np.eye(3)[y]
    br_1x2 = ((np.stack([home, draw, away], 1) - onehot) ** 2).sum(1).mean()
    # btts
    bt = (hg > 0) & (ag > 0)
    p_b = np.clip(btts_yes, EPS, 1 - EPS)
    ll_btts = -np.where(bt, np.log(p_b), np.log(1 - p_b)).mean()
    # over 2.5
    o25 = np.clip(overs[2.5], EPS, 1 - EPS)
    a25 = (hg + ag) > 2.5
    ll_o25 = -np.where(a25, np.log(o25), np.log(1 - o25)).mean()
    # scoreline nll
    M = len(hg)
    hc, ac = np.clip(hg, 0, G), np.clip(ag, 0, G)
    sp = grid[np.arange(M), hc, ac]
    sp = np.where((hg <= G) & (ag <= G), sp, EPS)
    nll = -np.log(np.clip(sp, EPS, None)).mean()
    return {"one_x_two_log_loss": ll_1x2, "one_x_two_brier": br_1x2,
            "btts_log_loss": ll_btts, "over_2_5_log_loss": ll_o25, "scoreline_nll": nll}


def combined(a, p):
    m = structural_metrics(a, p)
    return (m["one_x_two_log_loss"] + m["btts_log_loss"] + m["over_2_5_log_loss"]) / 3.0


def base_params(matches):
    lf = sum((m["fragility_home"] + m["fragility_away"]) / 2 for m in matches) / len(matches)
    lt = sum(pm.coalesce_float(m.get("match_tempo_index"), 1.0) for m in matches) / len(matches)
    return {"alpha": 0.0, "home_multiplier": 1.0, "away_multiplier": 1.0, "rho": 0.0,
            "league_avg_fragility": lf, "tempo_beta": 0.0, "league_avg_tempo_index": lt,
            "tempo_multiplier_min": 0.75, "tempo_multiplier_max": 1.30, "xg_power": 1.0}


DEFAULT_BOUNDS = {"alpha": (-5, 5), "home_multiplier": (0.5, 1.8), "away_multiplier": (0.5, 1.8),
                  "rho": (-0.25, 0.25), "tempo_beta": (-1, 1), "xg_power": (0.5, 1.5)}
DEFAULT_FIELDS = ("alpha", "home_multiplier", "away_multiplier", "rho", "tempo_beta")


def fit_structural(matches, extra_objective=None, fields=DEFAULT_FIELDS, bounds=None, init=None):
    """Coordinate descent replicating pm.fit_calibration_params (combined market log loss).
    `fields` selects which params to optimise; `init` overrides starting values."""
    a = to_arrays(matches)
    p = base_params(matches)
    if init:
        p.update(init)
    bounds = {**DEFAULT_BOUNDS, **(bounds or {})}
    obj = extra_objective or combined
    best = obj(a, p)
    for step in (0.25, 0.1, 0.05, 0.025, 0.01):
        improved = True
        while improved:
            improved = False
            for field in fields:
                for d in (-1.0, 1.0):
                    cv = min(max(p[field] + d * step, bounds[field][0]), bounds[field][1])
                    if cv == p[field]:
                        continue
                    cand = dict(p); cand[field] = cv
                    cs = obj(a, cand)
                    if cs + 1e-10 < best:
                        p = cand; best = cs; improved = True
    return p
