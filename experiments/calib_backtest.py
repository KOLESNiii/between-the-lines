import os,sys,pickle,time
sys.path.insert(0,"."); sys.path.insert(0,"experiments")
import numpy as np, probabilistic_markets as pm, fastmodel as fm
SEASONS=['14/15','15/16','16/17','17/18','18/19','19/20','20/21','21/22','22/23','23/24','24/25','25/26']
matches = pm.filtered_finished_matches(pickle.load(open("experiments/match_inputs.pkl","rb")))
bys=lambda ss:[m for m in matches if str(m["season_year"]) in set(ss)]
TEST=['21/22','22/23','23/24','24/25','25/26']
PFIELDS=("alpha","home_multiplier","away_multiplier","rho","league_avg_fragility","tempo_beta",
         "league_avg_tempo_index","tempo_multiplier_min","tempo_multiplier_max")
def to_cp(p): return pm.CalibrationParams(**{k:p[k] for k in PFIELDS})

def backtest(use_calibrators):
    agg={k:[] for k in ("one_x_two_log_loss","btts_log_loss","over_2_5_log_loss","one_x_two_brier","scoreline_nll")}
    sel=[]
    for ts in TEST:
        i=SEASONS.index(ts); tr=bys(SEASONS[:i]); te=bys([ts])
        p=fm.fit_structural(tr)                      # fast structural fit (== pm result)
        cp=to_cp(p)
        if use_calibrators:
            trs=sorted({str(m["season_year"]) for m in tr}, key=SEASONS.index)
            inner_valid=bys([trs[-1]]); inner_train=bys(trs[:-1])
            cp,meta=pm.fit_validated_market_calibrators(inner_train,inner_valid,cp)
            sel.append(meta["selected_market_calibrators"])
        m=pm.evaluate_matches(te,cp)
        for k in agg: agg[k].append(m[k])
    mean=lambda k: float(np.mean(agg[k]))
    comb=(mean("one_x_two_log_loss")+mean("btts_log_loss")+mean("over_2_5_log_loss"))/3
    return comb,{k:mean(k) for k in agg},sel

print(f"{'variant':22}{'combined':>10}{'1x2_ll':>9}{'btts_ll':>9}{'o25_ll':>9}{'1x2_br':>9}{'score_nll':>10}")
t=time.time(); c0,m0,_=backtest(False); 
print(f"{'structural-only':22}{c0:>10.5f}{m0['one_x_two_log_loss']:>9.4f}{m0['btts_log_loss']:>9.4f}{m0['over_2_5_log_loss']:>9.4f}{m0['one_x_two_brier']:>9.4f}{m0['scoreline_nll']:>10.4f}")
c1,m1,sel=backtest(True)
print(f"{'+ calibrators (BASELINE)':22}{c1:>10.5f}{m1['one_x_two_log_loss']:>9.4f}{m1['btts_log_loss']:>9.4f}{m1['over_2_5_log_loss']:>9.4f}{m1['one_x_two_brier']:>9.4f}{m1['scoreline_nll']:>10.4f}  ({(c1-c0)/c0*100:+.2f}%)")
print("calibrators selected per test season:", sel)
print(f"[{time.time()-t:.0f}s]")
