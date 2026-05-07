# Step 1: Player → Team Feature Engineering Pipeline

## 🎯 Goal

Convert raw **player match stats** into **team-level features per match** that are:

* Normalised
* Rolling (form-based)
* Leak-free
* Suitable for ML / Bayesian models

---

## 🧱 Pipeline Overview

```
RAW PLAYER MATCH DATA
        ↓
[1] Filter + minutes weighting
        ↓
[2] Aggregate to team-match level
        ↓
[3] Normalise (per 90, ratios)
        ↓
[4] Rolling features (form)
        ↓
[5] Opponent adjustment
        ↓
FINAL TEAM FEATURES
```

---

## 1️⃣ Filter + Minutes Weighting (CRITICAL)

Raw stats must be adjusted for playing time.

### Per-90 Normalisation

```sql
stat_per90 = stat_value / minutesPlayed * 90
```

### Why this matters

* Bench players don’t distort signals
* Handles substitutions and injuries
* Makes players comparable

---

## 2️⃣ Aggregate to Team-Match Level

Group by:

```
match_id, team
```

### Attack Features

```python
team_xg = sum(player.expectedGoals)
team_xa = sum(player.expectedAssists)
team_key_passes = sum(player.keyPass)
team_big_chances = sum(player.bigChanceCreated)
```

### Defence Features

```python
team_interceptions = sum(player.interceptionWon)
team_tackles = sum(player.wonTackle)
team_blocks = sum(player.blockedScoringAttempt)
```

### Possession / Control

```python
team_passes = sum(player.accuratePass)
team_touches = sum(player.touches)
team_progression = sum(player.progressiveBallCarriesCount)
```

### Goalkeeper

```python
team_saves = sum(player.saves)
team_goals_prevented = sum(player.goalsPrevented)
```

---

## 3️⃣ Normalisation Layer

### Team Per-90

```
feature_per90 = total_feature / total_team_minutes * 90
```

### Ratios

```python
pass_accuracy = accuratePass / totalPass
aerial_win_rate = aerialWon / (aerialWon + aerialLost)
shot_accuracy = onTargetScoringAttempt / totalShots
```

### Possession Proxy

```python
possession_proxy = team_passes / (team_passes + opponent_passes)
```

---

## 4️⃣ Rolling Features (Form)

Never use raw match stats directly.

### Example (5-match rolling)

```python
df["rolling_xg"] = (
    df.groupby("team")["team_xg"]
    .shift(1)
    .rolling(5)
    .mean()
)
```

### Key Rule

* Always use `.shift(1)` to prevent data leakage

### Useful Rolling Features

* rolling_xg_for
* rolling_xg_against
* rolling_shots
* rolling_big_chances
* rolling_possession

---

## 5️⃣ Opponent Adjustment

Raw stats depend on opponent strength.

### Basic Adjustment

```
adjusted_attack = team_xg / opponent_avg_xg_conceded
```

### Example

```python
adj_xg = team_xg / opponent_rolling_xg_against
```

---

## 6️⃣ Feature Grouping

Organise features into meaningful categories.

### ⚔️ Attack

* rolling_xg_for
* rolling_big_chances
* shot_accuracy

### 🛡️ Defence

* rolling_xg_against
* tackles + interceptions
* blocks

### 🔄 Transition

* progressive carries
* long balls
* possessionLostCtrl (negative)

### 🧤 Goalkeeping

* saves per shot faced
* goalsPrevented

### ⚙️ Control

* possession proxy
* passes per minute

---

## 7️⃣ Minimal Working Example (Python)

```python
# 1. per90
df["xg_per90"] = df["expectedGoals"] / df["minutesPlayed"] * 90

# 2. aggregate
team_df = df.groupby(["match_id", "team"]).agg({
    "xg_per90": "sum",
    "expectedAssists": "sum",
    "keyPass": "sum",
    "interceptionWon": "sum",
    "wonTackle": "sum",
    "touches": "sum"
}).reset_index()

# 3. rolling
team_df = team_df.sort_values("date")

team_df["rolling_xg"] = (
    team_df.groupby("team")["xg_per90"]
    .shift(1)
    .rolling(5)
    .mean()
)

# 4. opponent join
team_df = team_df.merge(
    team_df[["match_id", "team", "rolling_xg"]],
    left_on=["match_id", "opponent"],
    right_on=["match_id", "team"],
    suffixes=("", "_opp")
)

# 5. adjusted
team_df["adj_xg"] = team_df["rolling_xg"] / team_df["rolling_xg_opp"]
```

---

## ⚠️ Common Mistakes

### ❌ Data Leakage

* Using current match stats in rolling features
* Forgetting `.shift(1)`

### ❌ Double Counting

* Using both player aggregates and team stats redundantly

### ❌ No Minutes Normalisation

* Leads to biased signals

### ❌ No Opponent Adjustment

* Inflates strong teams

---

## 🧠 Final Output Example

```
team | opponent | date |
rolling_xg_for | rolling_xg_against |
adj_attack | adj_defence |
possession | tempo | ...
```

---

## ✅ Summary

This pipeline produces:

* Clean
* Comparable
* Predictive

team-level features ready for:

* XGBoost
* Bayesian goal models
* Monte Carlo simulation

# Step 2: XGBoost Modelling Plan (Inputs, Outputs, Forms)

## 🎯 Objective

Train an XGBoost model to predict **team-level expected goals created (xG_for)** for a given match, using lineup-aware, leak-free features derived from player data.

---

## 🧾 Data Units & Shapes

### Unit of observation (row)

match_id | team | opponent | home_away | date | features... | target

- Granularity: one row per (team, match) → 2 rows per match
- Primary target: xG_for

---

## 🎯 Target Definition

xG_for = sum of shot-level expected goals for this team in the match

This is the **true label** you train on.

---

## 🧱 Inputs (Features)

All features MUST be known **before the match starts**.

---

### 1) Team Attacking Form (rolling)

- rolling_xg_for_3
- rolling_xg_for_5
- rolling_xg_for_10
- rolling_shots_5
- rolling_big_chances_5
- shot_accuracy_5

Form:
- per-90
- shifted by 1 match (no leakage)

---

### 2) Team Defensive Form (rolling)

- rolling_xg_against_5
- rolling_shots_against_5
- tackles_won_5
- interceptions_5
- blocks_5

---

### 3) Opponent Features (CRITICAL)

Join opponent stats onto each row:

- opp_rolling_xg_for_5
- opp_rolling_xg_against_5
- opp_shot_accuracy_5

This allows the model to learn:

> attack vs defence interaction

---

### 4) Lineup / Player Aggregation (YOUR EDGE)

From player data (projected XI or proxy):

- xi_xg_sum
- xi_xa_sum
- xi_key_pass_sum
- xi_progressive_carries
- xi_def_actions (tackles + interceptions)
- xi_goalkeeper_strength

Notes:
- per-90 normalised
- optionally weighted by recency
- if XI unknown → use last match XI or minutes-weighted squad

---

### 5) Control & Tempo

- possession_proxy_5
- passes_per90_5
- final_third_entries_5
- touches_in_box_5

---

### 6) Context Features

- home_away (binary)
- rest_days
- fixture_congestion (matches in last 7/14 days)
- optional: derby flag

---

## 🧮 Feature Rules (IMPORTANT)

- All stats → per 90
- All rolling features → shift(1)
- No current match data
- Opponent features must also be pre-match

---

## 🎯 Model Output

Primary output:

xG_hat_for

A single continuous value per team-match row.

---

## 🔁 Match-Level Outputs

For each match:

xG_home = prediction(home row)
xG_away = prediction(away row)

---

## 🔄 Pipeline Flow

Player data
    ↓
Per-90 normalisation
    ↓
Team aggregation
    ↓
Rolling features (shifted)
    ↓
Opponent join
    ↓
Lineup aggregation
    ↓
Final dataset (team-match rows)
    ↓
XGBoost → predict xG_for

---

## ⚙️ XGBoost Setup

Objective:
- reg:squarederror

Evaluation:
- RMSE
- MAE

Do NOT:
- predict goals
- use classification objectives

---

## 🔁 Train / Validation

Use time-based split:

- Train: past seasons
- Validate: future season

Never random split.

---

## 🔗 Integration with Bayesian Model

Convert predictions into:

λ_home = xG_home  
λ_away = xG_away  

Then:

- apply Dixon-Coles correction
- simulate scorelines
- compute betting EV

---

## ⚠️ Common Mistakes

### Data leakage
- forgetting shift(1)
- using current match stats

### Double counting
- mixing player + team stats incorrectly

### Ignoring lineups
- using only team averages

### Predicting goals
- too noisy → poor generalisation

---

## ✅ Summary

- Input: team-match row
- Target: xG_for
- Model: XGBoost regression
- Output: expected goals created
- Usage: feed into Bayesian goal model

## 🛠️ Implementation Commands

Install the modelling dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Refresh the team feature tables first:

```bash
python3 team_feature_pipeline.py --create-schema --refresh
```

Train the default time-split model:

```bash
python3 xgboost_xg_model.py train
```

Fit the final production model after validation:

```bash
python3 xgboost_xg_model.py train-final
```

`train-final` reads the validated `train` metadata to reuse the best boosting round from early stopping, then fits on all labelled seasons with no validation holdout. If the validated metadata is missing or stale, rerun it first:

```bash
python3 xgboost_xg_model.py train-final --refresh-source-train
```

Default split:

- Train: `22/23`, `23/24`, `24/25`
- Validate: `25/26`

Run rolling-origin cross-validation for evaluation:

```bash
python3 xgboost_xg_model.py cross-validate
```

Default CV folds:

- Train `22/23`, validate `23/24`
- Train `22/23`-`23/24`, validate `24/25`
- Train `22/23`-`24/25`, validate `25/26`

Artifacts are written to:

```text
models/xgboost_xg_for/
```

Final all-data model artifacts are written to:

```text
models/xgboost_xg_for_final/
```

Historical audit predictions:

```bash
python3 xgboost_xg_model.py predict-history
```

Predict both team rows for one match:

```bash
python3 xgboost_xg_model.py predict-match --match-id 123
```

Validation output reports:

- model RMSE
- model MAE
- baseline RMSE/MAE using `rolling_xg_for_5`
- train/validation row counts in `metadata.json`

---

## 🚀 Future Upgrades

- minute-split features (0–75 vs 75+)
- red card modelling
- player embeddings
- uncertainty-aware models

# Step 3: XGBoost Signal Decomposition (Shot Quality & Defensive Fragility)

## 🎯 Objective

Extend the XGBoost layer to predict additional structured signals beyond xG:

- Shot Quality (attacking efficiency)
- Defensive Fragility (defensive weakness)

These are separate regression targets, trained independently using the same feature set as the xG model.

---

## ⚽ Model 2: Shot Quality

### 🎯 Target Definition

shot_quality_for = xG_for / shots_for

Represents:

> average quality of chances created by the team

---

### ⚠️ Target Construction Rules

Handle edge cases:

```python
shot_quality = xG_for / max(shots_for, 1)
```

Optional stabilisation:

- Drop matches where shots_for < 3
- Clip values:

```python
shot_quality = np.clip(shot_quality, 0, 0.5)
```

### 🧾 Inputs

Use the exact same feature set as the xG model:

- rolling_xg_for_5
- rolling_shots_5
- rolling_big_chances
- shot_accuracy
- rolling_xg_against
- tackles / interceptions / blocks
- opponent rolling stats
- lineup features (xi_xg_sum, xi_key_pass_sum, etc.)
- context (home_away, rest_days)

### 🎯 Output

shot_quality_hat

- continuous value
- typical range: 0.05 – 0.25

### 🧠 Interpretation

Captures:

- chance type (high vs low quality)
- attacking style
- efficiency of chance creation

## 🛡️ Model 3: Defensive Fragility

### 🎯 Target Definition

fragility = xG_against / shots_against

Represents:

> how easily a team concedes high-quality chances

### ⚠️ Target Construction Rules

```python
fragility = xG_against / max(shots_against, 1)
```

Optional:

- Filter matches with low shots_against
- Clip extreme values if needed

### 🧾 Inputs

Use the same feature set again

Key signals include:

- team defensive stats (tackles, interceptions, blocks)
- opponent attacking stats
- lineup defensive strength
- goalkeeper metrics

### 🎯 Output

fragility_hat

- continuous value
- typical range: 0.07 – 0.30

### 🧠 Interpretation

Captures:

- defensive structure quality
- positioning / spacing
- susceptibility to high-quality chances

### 🔗 Relationship Between Models

You now have:

- xG_for → total attacking output
- shot_quality → quality of chances
- fragility → defensive weakness

These are independent predictions.

### ⚠️ Important Constraint

Do NOT derive predictions from each other:

```python
# WRONG
shot_quality_hat = xG_hat / shots_hat
fragility_hat = xG_against_hat / shots_against_hat
```

Instead:

- each model is trained separately
- each predicts directly from features

### 🧩 Optional Extension (Advanced)

Add a shots model:

shots_for_hat

Then reconstruct:

xG ≈ shots × shot_quality

This can improve stability and interpretability.

### 🚀 Final Architecture

INPUT FEATURES (team-match rows)
↓
XGBoost Model 1 → xG_for_hat
XGBoost Model 2 → shot_quality_hat
XGBoost Model 3 → fragility_hat

### 🧭 Summary

- Shot Quality = attacking efficiency (xG per shot)
- Fragility = defensive weakness (xG conceded per shot)
- Both are:
        - derived for training targets
        - predicted independently by XGBoost

## 🛠️ Implementation Commands

The XGBoost CLI now supports multiple independent model targets. The default remains the original xG-for model:

```bash
python3 xgboost_xg_model.py train
```

Train and validate the Step 3 models:

```bash
python3 xgboost_xg_model.py --model shot_quality train
python3 xgboost_xg_model.py --model fragility train
```

Run rolling-origin cross-validation:

```bash
python3 xgboost_xg_model.py --model shot_quality cross-validate
python3 xgboost_xg_model.py --model fragility cross-validate
```

Fit final all-labelled-data models after validation:

```bash
python3 xgboost_xg_model.py --model shot_quality train-final
python3 xgboost_xg_model.py --model fragility train-final
```

Score historical labelled rows:

```bash
python3 xgboost_xg_model.py --model shot_quality predict-history
python3 xgboost_xg_model.py --model fragility predict-history
```

Score both team rows for a match:

```bash
python3 xgboost_xg_model.py --model shot_quality predict-match --match-id 123
python3 xgboost_xg_model.py --model fragility predict-match --match-id 123
```

Default artifact directories:

```text
models/xgboost_shot_quality/
models/xgboost_shot_quality_final/
models/xgboost_fragility/
models/xgboost_fragility_final/
```

Step 3 defaults:

- `shot_quality` target: `xg / GREATEST(total_shots, 1)`
- `fragility` target: `xg_against / GREATEST(shots_against, 1)`
- both targets filter labelled rows with at least `3` relevant shots by default
- both targets and predictions are clipped to `[0.0, 0.5]`
- baselines use matching rolling 5-match xG-per-shot expressions
- predictions are independent columns: `shot_quality_hat` and `fragility_hat`

Override the low-shot filter when needed:

```bash
python3 xgboost_xg_model.py --model shot_quality --min-shots 5 train
python3 xgboost_xg_model.py --model fragility --min-shots 5 train
```

---

Short answer first:

- ❌ This is still baseline-level performance
- ❌ You do not yet have a betting edge
- ✅ But your pipeline is structurally correct and stable

Now let’s break it down properly.

## 📊 Your results (final model)
BTTS
Brier: 0.2488
Log loss: 0.6907

👉 This is basically:

> “near-naive model territory”

Typical benchmark:

- good: ≤ 0.235
- strong: ≤ 0.225
Over 2.5
Brier: 0.2448
Log loss: 0.6824

👉 This is:

> slightly above trivial baseline

Typical:

good: ≤ 0.235
strong: ≤ 0.225
1X2
Brier: 0.6207
Log loss: 1.0333

👉 This is:

standard Poisson-quality baseline

Typical:

good: < 1.00
strong: ~0.95 or lower
Scoreline NLL
3.00

👉 This is:

completely normal for a simple Poisson/Dixon-Coles system

Not bad — but not sharp.

## 🧠 What this actually means

This is the key insight:

> Your system is not wrong — it’s just not adding extra information beyond structure

In plain terms:

You currently have:
- good probabilistic framework ✔
- decent xG signals ✔
- reasonable calibration ✔
But:
- no strong predictive lift over baseline ❌
🔥 The most important diagnostic

Compare mentally:

your model ≈ rolling xG + Poisson

So what’s happening is:

XGBoost layer is NOT yet injecting strong new signal into λ

## 🧩 Why this happens (almost certainly in your case)

1. λ function is too linear

You are effectively doing:

λ ≈ xG_for

So fragility / opponent effects are:

not strong enough to move probabilities meaningfully

2. “Opponent adjustment” is weak

Most systems fail here.

If:

attack strength ≈ defence weakness

but you combine them weakly → you get baseline performance.

3. XGBoost signal is already “baked into xG”

Your features:

- rolling xG
- shots
- big chances

👉 already correlate strongly with outcome

So ML is:

re-learning Poisson structure, not adding new information

4. No calibration layer on top

Your probabilities are:

- structurally correct
- but not sharpened vs market

## 📉 The key conclusion

Let’s be very explicit:

You have built a correct probabilistic model
but NOT yet a profitable model

That’s exactly where you are.

## 🧠 What “good” would look like

To beat the market consistently, you need:

For 1X2:
Log loss: < 1.00
For BTTS / O/U:
Brier: < 0.235

Right now you're:

~0.01–0.02 away from meaningful edge

That sounds small, but in betting terms:

that’s the difference between break-even and profitable

## 🚀 What will actually improve this (priority order)

### 🥇 1. Fix λ interaction model (BIGGEST LEVER)

Right now you're likely doing:

λ_home = xg_home * adjustment

You need:

NONLINEAR interaction:
λ_home = xg_home ** a * (fragility_away) ** b

or learned mapping:

small neural layer OR
gradient boosted second layer

👉 This is where edge lives

### 🥈 2. Add calibration layer (CRITICAL)

Apply:

isotonic regression per market OR
Platt scaling on probabilities

Especially for:

BTTS
Over/Under

### 🥉 3. Introduce market anchoring

This is what sharp models do:

final_prob = blend(model_prob, market_implied_prob)

Even:

5–20% weight on market improves calibration massively

### 🧪 4. Fix “signal dilution”

Right now too many features are:

correlated
redundant
smoothed (rolling xG, shots, etc.)

👉 XGBoost is not learning new signal, just smoothing noise

### ⚠️ Honest verdict
What you have:

- ✔ correct architecture
- ✔ correct statistical layer
- ✔ stable outputs

What you DON’T yet have:

- ❌ edge over baseline
- ❌ calibration advantage
- ❌ strong opponent interaction modelling

💡 The key insight (this is important)

Most betting models fail not because the probability model is wrong
but because the rate model is too weakly coupled to outcomes

That is exactly your current situation.

### 🧭 Final takeaway

You are at this stage:

>🟡 “Correct system, weak signal injection”

Next stage:

>🟢 “Strong interaction model + calibrated probabilities = edge”