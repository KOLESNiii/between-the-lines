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

# Step 4: Probabilistic Modelling Layer (Team & Player Props)

## 🎯 Objective

Convert XGBoost predictions (rates) into **full probability distributions** for:

- match outcomes (1X2)
- totals (goals, corners, etc.)
- player props (shots, goals, assists)

This is the layer where **EV is actually generated**.

---

## 🧱 Core Principle

All markets follow:


features → ML → rate (λ or μ) → distribution → probabilities → EV


Where:

- ML = XGBoost (already built)
- rate = expected count (goals, shots, etc.)
- distribution = Poisson / Negative Binomial

---

## ⚽ SECTION A: TEAM MARKETS (GOALS, 1X2, TOTALS)

---

### 🎯 Inputs (from XGBoost layer)

Per match:


xG_home
xG_away
fragility_home
fragility_away


Optional:


shot_quality_home
shot_quality_away


---

### 🔧 Step 1: Construct Goal Rates (λ)

#### Base formulation


λ_home = f(xG_home, fragility_away)
λ_away = f(xG_away, fragility_home)


#### Minimal working version

```python
lambda_home = xg_home * (1 + alpha * fragility_away)
lambda_away = xg_away * (1 + alpha * fragility_home)
```

Where:

> alpha is a tuned parameter (~0.5–1.5 range)


### 📊 Step 2: Goal Distribution

Model
- Poisson distribution (baseline)
- Dixon-Coles correction (for low scores)

Poisson

For goals k:

```bash
P(G = k) = (λ^k * e^{-λ}) / k!
```

Joint Scoreline

Assuming independence:

```bash
P(home = i, away = j) = P_home(i) * P_away(j)
```

Then apply Dixon-Coles correction.

#### 🎯 Outputs

Scoreline probabilities

```bash
P(0-0), P(1-0), P(2-1), ...
```

Derived markets

1X2

```bash
P(Home Win) = sum_{i > j} P(i,j)
P(Draw)     = sum_{i = j} P(i,j)
P(Away Win) = sum_{i < j} P(i,j)
```

Over/Under

```bash
P(Over 2.5) = P(total_goals ≥ 3)
```

BTTS

```bash
P(BTTS) = 1 - P(home=0) - P(away=0) + P(0-0)
```

## 🟨 SECTION B: TEAM COUNT MARKETS (SHOTS, CORNERS, CARDS)

### 🎯 Inputs

From XGBoost:

```bash
shots_for_hat
corners_for_hat
cards_for_hat
```

(or derive from features if not modelled yet)

### 📊 Step 1: Choose Distribution

Use:
Market | Distribution
Shots | Poisson / NegBin
Corners | Negative Binomial
Cards | Poisson / NegBin

### 📐 Negative Binomial (for overdispersion)

Use when:

- variance > mean
- common in corners/cards

### 🎯 Outputs

For any line (e.g. 9.5 corners):

```bash
P(Over 9.5)
P(Under 9.5)
```

## 🧍 SECTION C: PLAYER PROPS

### 🎯 Inputs

Per player:

```bash
player_rate (shots, xG, assists)  ← from XGBoost
expected_minutes
team context (xG, possession, etc.)
```

### ⚠️ Critical Component: Minutes Model

You must estimate:

`minutes_played`

Because:

> rate × minutes = actual expectation

### 🔧 Step 1: Adjust Rate for Minutes

```python
adjusted_rate = player_rate * (minutes / 90)
```

### 📊 Step 2: Distribution

Use:
Prop Type | Distribution
Shots | Poisson / NegBin
Goals | Poisson
Assists | Poisson

### 🎯 Outputs

Examples:

```bash
P(player shots ≥ 3)
P(player scores)
P(player assists)
```

### 🧠 Example

```python
lambda_shots = player_shots_per90 * (minutes / 90)

P(≥3 shots) = 1 - [P(0) + P(1) + P(2)]
```

## 🔁 SECTION D: MONTE CARLO SIMULATION (OPTIONAL BUT POWERFUL)

### 🎯 Purpose

Simulate full match outcomes using distributions.

Process

Repeat N times:

```bash
sample home_goals ~ Poisson(λ_home)
sample away_goals ~ Poisson(λ_away)
```

Track:

- win/draw/loss
- totals
- player outcomes (optional)
- 
Output

Empirical probabilities:

```bash
P(Home Win)
P(Over 2.5)
P(player ≥ k)
```

## 💰 SECTION E: EV CALCULATION

### 🎯 Inputs

```bash
model_probability
market_odds
```

Formula

`EV = (model_prob × odds) - 1`

Example

```bash
model_prob = 0.55
odds = 2.10

EV = 0.55 × 2.10 - 1 = +0.155
```

Decision Rule

- Bet only if EV > threshold (e.g. 2–5%)
- Track CLV (closing line value)

## ⚠️ Key Constraints

### ❌ Do NOT

- predict probabilities directly with ML
- skip minutes modelling for players
- assume Poisson always fits (check variance)

### ✅ DO

- treat everything as rate → distribution
- calibrate λ if needed
- validate against historical outcomes

## 🧭 Final Summary

You now have:

Inputs:
- XGBoost predictions (rates)
Process:
- construct λ
- choose distribution
- compute probabilities
Outputs:
- full market probabilities
- EV vs bookmaker odds

## 🚀 End State

A complete pipeline:

Player data
    ↓
Team features
    ↓
XGBoost (rates)
    ↓
Probabilistic model (Poisson / NegBin)
    ↓
Probabilities
    ↓
EV calculation

This is the standard architecture used in serious sports betting systems.

## 🛠️ Team Market Implementation Commands

Create the output schema and fit the held-out calibration run:

```bash
./venv/bin/python probabilistic_markets.py --create-schema fit-calibration
```

Fit the final all-history probability calibration:

```bash
./venv/bin/python probabilistic_markets.py fit-final
```

Generate historical probability outputs:

```bash
./venv/bin/python probabilistic_markets.py predict-history
```

Score a single match:

```bash
./venv/bin/python probabilistic_markets.py predict-match --match-id 4171
```

Default artifacts:

```text
models/probabilistic_markets/
models/probabilistic_markets_final/
```

Default DB outputs:

```text
model_outputs.market_probability_runs
model_outputs.match_probability_inputs
model_outputs.market_probabilities
```

The v1 team-market layer outputs 1X2, BTTS, exact-score, and total-goals probabilities. It does not yet join bookmaker odds or calculate EV.


---
