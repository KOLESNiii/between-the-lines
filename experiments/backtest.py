"""Walk-forward backtest for the probabilistic markets model.

For each test season, fit on all earlier seasons (structural params + market
calibrators selected on an inner validation split that never sees the test
season), then evaluate out-of-sample on the test season.
"""
import os, sys, pickle, math
sys.path.insert(0, "/home/kolesniii/BetPredictor"); os.chdir("/home/kolesniii/BetPredictor")
import probabilistic_markets as pm

SEASON_ORDER = ['14/15','15/16','16/17','17/18','18/19','19/20','20/21','21/22','22/23','23/24','24/25','25/26']

def load():
    with open("experiments/match_inputs.pkl","rb") as f:
        return pm.filtered_finished_matches(pickle.load(f))

def by_seasons(matches, seasons):
    s=set(seasons); return [m for m in matches if str(m["season_year"]) in s]

def fit_model(train, fit_params_fn=None, use_calibrators=True, max_goals=10):
    """Fit structural params on train, then select calibrators on an inner split."""
    fit_params_fn = fit_params_fn or pm.fit_calibration_params
    params = fit_params_fn(train, max_goals=max_goals)
    meta = {}
    if use_calibrators:
        tr_seasons = sorted({str(m["season_year"]) for m in train}, key=SEASON_ORDER.index)
        if len(tr_seasons) >= 2:
            inner_valid = by_seasons(train, [tr_seasons[-1]])
            inner_train = by_seasons(train, tr_seasons[:-1])
        else:
            inner_train = inner_valid = train
        params, meta = pm.fit_validated_market_calibrators(inner_train, inner_valid, params, max_goals=max_goals)
    return params, meta

def backtest(matches, test_seasons, fit_params_fn=None, use_calibrators=True, label="model"):
    rows=[]
    agg={"one_x_two_log_loss":[], "btts_log_loss":[], "over_2_5_log_loss":[],
         "one_x_two_brier":[], "btts_brier":[], "over_2_5_brier":[], "scoreline_nll":[]}
    for ts in test_seasons:
        idx = SEASON_ORDER.index(ts)
        train = by_seasons(matches, SEASON_ORDER[:idx])
        test  = by_seasons(matches, [ts])
        if not train or not test: continue
        params,_ = fit_model(train, fit_params_fn, use_calibrators)
        m = pm.evaluate_matches(test, params)
        rows.append((ts, m, len(test)))
        for k in agg: agg[k].append(m[k])
    print(f"\n=== {label} ===")
    print(f"{'season':7} {'n':>4} {'1x2_ll':>8} {'btts_ll':>8} {'o25_ll':>8} {'1x2_br':>8} {'score_nll':>9}")
    for ts,m,n in rows:
        print(f"{ts:7} {n:>4} {m['one_x_two_log_loss']:8.4f} {m['btts_log_loss']:8.4f} {m['over_2_5_log_loss']:8.4f} {m['one_x_two_brier']:8.4f} {m['scoreline_nll']:9.4f}")
    mean=lambda k: sum(agg[k])/len(agg[k]) if agg[k] else float('nan')
    print(f"{'MEAN':7} {'':>4} {mean('one_x_two_log_loss'):8.4f} {mean('btts_log_loss'):8.4f} {mean('over_2_5_log_loss'):8.4f} {mean('one_x_two_brier'):8.4f} {mean('scoreline_nll'):9.4f}")
    overall = (mean('one_x_two_log_loss')+mean('btts_log_loss')+mean('over_2_5_log_loss'))/3
    print(f"combined market log-loss: {overall:.5f}")
    return {"rows":rows, "combined":overall, "means":{k:mean(k) for k in agg}}

if __name__ == "__main__":
    matches = load()
    TEST = ['21/22','22/23','23/24','24/25','25/26']
    backtest(matches, TEST, label="BASELINE (current model)")
