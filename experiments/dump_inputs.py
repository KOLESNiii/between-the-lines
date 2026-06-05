"""Cache per-match probability inputs (xg/shot_quality/fragility/tempo + actual goals)
so calibration-math experiments can run in-memory without re-scoring XGBoost."""
import os, sys, pickle
sys.path.insert(0, "/home/kolesniii/BetPredictor"); os.chdir("/home/kolesniii/BetPredictor")
DB="postgresql://user:pwd@localhost:5433/betting_historical_data"; os.environ["DB_URL"]=DB
import probabilistic_markets as pm

sources = {k: pm.xgb_model.MODEL_SPECS[k].default_final_model_dir for k in ("xg_for","shot_quality","fragility")}
print("scoring all matches with final models ...", flush=True)
scored = pm.score_xgboost_models(DB, sources)              # all matches
matches = pm.build_match_inputs(scored)
finished = pm.filtered_finished_matches(matches)
print(f"matches={len(matches)} finished={len(finished)}", flush=True)
with open("experiments/match_inputs.pkl","wb") as f:
    pickle.dump(finished, f)
# season distribution
from collections import Counter
print(sorted(Counter(str(m["season_year"]) for m in finished).items()))
print("saved experiments/match_inputs.pkl")
