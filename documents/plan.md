# BetPredictor — Next Steps Roadmap (`plan.md`)

# 🎯 Objective

You already have:

- Team feature engineering
- XGBoost xG models
- XGBoost team shots models
- Shot quality + fragility models
- Dixon-Coles score adjustment
- Probability generation
- Calibration framework
- Historical backfill + feature coverage tracking

The next phase is turning this into a:

1. Strong probabilistic football engine
2. Multi-market betting model
3. Player props prediction system
4. Production-grade EV pipeline

---

# 📌 CURRENT PIPELINE

```text
RAW PLAYER DATA
    ↓
Feature Engineering
    ↓
Rolling + opponent-adjusted team features
    ↓
XGBoost regressors
    ├── xG_for_hat
    ├── shots_for_hat
    ├── shots_against_hat
    ├── shot_quality_hat
    └── fragility_hat
    ↓
Goal probability model
    ↓
Dixon-Coles correction
    ↓
Market probabilities
    ↓
EV calculation
```

# 1. PLAYER PROP MODELS

## ✅ What This Is

Convert team-level probabilities into:

- player shots
- player SOT
- assists
- goals
- passes
- tackles
- cards

## ✅ What It Improves

This is where sportsbooks are weakest.

Player props are MUCH softer markets than:

- 1X2
- totals
- BTTS


## ✅ Core Idea

First predict:

```text
team shot volume
```

Then allocate share to players.


## ✅ Recommended Architecture

### Team Layer

Predict:

```text
team_shots_hat
team_xg_hat
team_sot_hat
```

### Allocation Layer

Allocate using:

```text
player_share
```

Example:

```python
player_expected_shots =
    team_shots_hat * player_rolling_shot_share
```


## ✅ Inputs

### Team Inputs

Existing team features.

### Player Inputs

```text
rolling_shots_per90
rolling_sot_per90
rolling_xg_per90
expected_minutes
starting_probability
position
opponent weakness
```

## ✅ Outputs

```text
player_shots_mean
player_sot_mean
player_goal_prob
player_assist_prob
```

## ✅ Distribution Choice

### Recommended

#### Poisson

Good for:

- shots
- SOT
- passes

### Alternative

#### Negative Binomial

Better tails.

Use if variance > mean.


## ✅ Pipeline Placement

```text
Team models
    ↓
Player allocation
    ↓
Player distributions
    ↓
Player prop probabilities
```

# 2. CALIBRATION LAYER (CRITICAL)

## ✅ What This Is

Raw probabilities are NOT calibrated.

Example:

```text
Model says:
70% probability
```

But historically:

```text
those events only occur 62% of the time
```

Calibration fixes this.

## ✅ What It Improves

Massively improves:

- EV estimates
- betting stability
- probability realism
- bankroll growth

This is one of the MOST IMPORTANT components.


## ✅ Recommended Methods

### Option A — Isotonic Regression (RECOMMENDED)

#### Pros

- non-linear
- excellent for betting
- very common professionally

#### Cons

- can overfit small samples

---

### Option B — Platt Scaling

#### Pros

- stable
- simple

#### Cons

- less flexible


## ✅ Recommendation

Use:

```text
Isotonic for large datasets
Platt for small datasets
```


## ✅ Inputs

```text
raw_market_probability
actual_outcome
```


## ✅ Outputs

```text
calibrated_probability
```


## ✅ Pipeline Placement

```text
Raw probability model
    ↓
Calibration layer
    ↓
Final probability
```


# 3. PROPER JOINT GOAL MODEL

## ✅ What This Is

You already use Dixon-Coles.

Now improve dependency structure between:

```text
home_goals
away_goals
```


## ✅ What It Improves

Better:

- BTTS
- exact score
- same-game correlations
- totals
- tails


## ✅ Options

### Option A — Dixon-Coles Only (RECOMMENDED)

#### Pros

- proven
- stable
- simple
- industry standard

#### Cons

- limited dependency flexibility

---

### Option B — Bivariate Poisson

#### Pros

- explicit covariance

#### Cons

- often unstable
- little real-world gain

---

### Option C — Copula Models

#### Pros

- extremely flexible

#### Cons

- hard to calibrate
- overkill for football


## ✅ Recommendation

Use:

```text
Independent Poisson
+ Dixon-Coles correction
```

This is the best tradeoff.


## ✅ Pipeline Placement

```text
xG estimates
    ↓
Goal distributions
    ↓
Dixon-Coles adjustment
    ↓
Final score matrix
```

# 4. MARKET CALIBRATION AGAINST BOOKMAKERS

## ✅ What This Is

Use bookmaker odds AFTER modelling.

NOT inside the football prediction model.


## ✅ What It Improves

- catches structural biases
- improves EV filtering
- reduces catastrophic errors


## ✅ Recommendation

Use bookmaker probabilities ONLY for:

```text
validation
monitoring
meta-models
```

NOT:

```text
core football prediction
```


## ✅ Example

```python
edge =
    model_probability - market_probability
```

Then train:

```text
edge reliability model
```


## ✅ Pipeline Placement

```text
Football probabilities
    ↓
Compare with market
    ↓
EV filtering / meta-model
```


# 5. SIMULATION ENGINE

## ✅ What This Is

Monte Carlo match simulation.


## ✅ What It Improves

Allows:

- same-game parlays
- correlated markets
- player correlations
- portfolio betting


## ✅ Inputs

```text
goal distributions
player distributions
tempo distributions
```


## ✅ Outputs

Simulated match universe.


## ✅ Recommendation

Do AFTER calibration.


# 6. UNCERTAINTY MODELLING

## ✅ What This Is

Model confidence / variance.


## ✅ What It Improves

Critical for:

- lineup uncertainty
- promoted teams
- injuries
- sparse data


## ✅ Recommended Methods

### Quantile XGBoost (RECOMMENDED)

Predict:

```text
P10
P50
P90
```


### Bayesian Boosting

More advanced.

Harder operationally.


## ✅ Pipeline Placement

```text
Feature layer
    ↓
Prediction intervals
    ↓
Probability distributions
```

# 7. FEATURE IMPROVEMENTS

## ✅ Tempo Features

Already helping substantially.

Continue expanding.


## ✅ Recommended Additions

```text
pressing intensity
PPDA
counterattack speed
deep completions
zone entries
set-piece quality
```


## ✅ What It Improves

Especially:

- corners
- shots
- props
- over/under


# 8. PLAYER MINUTES MODEL

## ✅ What This Is

Predict expected minutes played.


## ✅ Why Important

Player props are impossible without this.

A striker projected:

```text
90 mins
```

vs

```text
28 mins
```

changes everything.


## ✅ Outputs

```text
expected_minutes
starting_probability
sub_probability
```


## ✅ Recommendation

Very important before advanced player props.


# 9. CORNERS MODEL

## ✅ What This Is

Dedicated corners prediction model.


## ✅ Why Corners Need Separate Modelling

Corners are more related to:

- pressure
- crossing
- territorial dominance

than raw xG.


## ✅ Important Features

```text
cross accuracy
box entries
final third entries
tempo
shots blocked
```


## ✅ Outputs

```text
team_corners_hat
match_corners_hat
```


# 10. META-MODEL / BET FILTER

## ✅ What This Is

Model which bets are ACTUALLY profitable.


## ✅ Inputs

```text
edge
market disagreement
line movement
confidence
calibration
liquidity
```


## ✅ Outputs

```text
bet_quality_score
```


## ✅ Why Important

Many positive-EV bets are still bad bets.

This layer filters noise.


# IMPLEMENTATION ORDER (RECOMMENDED)

## 🥇 Tier 1 — MUST DO NEXT

### 1. Calibration layer

Essential before serious EV betting.

---

### 2. Player minutes model

Required before meaningful player props.

---

## 🥈 Tier 2 — HIGH VALUE

### 3. Player allocation layer

Convert team outputs → player probabilities.

---

### 4. Corners model

Very beatable market.

---

### 5. Simulation engine

Needed for correlated betting.

---

## 🥉 Tier 3 — ADVANCED

### 6. Quantile uncertainty models

---

### 7. Meta-model / bet filter

---

### 8. Advanced dependency structures

Only after everything else works well.

---

# ✅ FINAL RECOMMENDED ARCHITECTURE

```text
RAW PLAYER DATA
    ↓
Feature Engineering
    ↓
Team Feature Layer
    ↓
XGBoost Models
    ├── xG
    ├── shots
    ├── shots on target
    ├── shot quality
    ├── fragility
    ├── corners
    └── tempo
    ↓
Player Minutes Model
    ↓
Player Allocation Layer
    ↓
Goal Distributions
    ↓
Dixon-Coles Adjustment
    ↓
Probability Layer
    ↓
Calibration Layer
    ↓
Simulation Engine
    ↓
Market Probabilities
    ↓
Bookmaker Comparison
    ↓
EV Calculation
    ↓
Meta Bet Filter
```
