# BetPredictor — Next Steps Roadmap (`plan.md`)

# 🎯 Objective

You already have:

- Team feature engineering
- XGBoost xG models
- XGBoost team shots models
- XGBoost team corners rate model
- Shot quality + fragility models
- Dixon-Coles score adjustment
- Probability generation
- Calibration framework
- Historical backfill + feature coverage tracking
- Bookmaker odds normalisation
- EV candidate generation

The next phase is turning this into a:

1. Strong probabilistic football engine
2. Multi-market betting model
3. Player props prediction system
4. Production-grade EV monitoring and bet filtering

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
    ├── corners_for_hat
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

# 1. CALIBRATION LAYER (CRITICAL)

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


# 2. PROPER JOINT GOAL MODEL

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

# 3. SIMULATION ENGINE

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


# 4. UNCERTAINTY MODELLING

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

# 5. FEATURE IMPROVEMENTS

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


# 6. META-MODEL / BET FILTER

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

## 🥈 Tier 2 — HIGH VALUE

### 2. Simulation engine

Needed for correlated betting.

---

## 🥉 Tier 3 — ADVANCED

### 3. Quantile uncertainty models

---

### 4. Meta-model / bet filter

---

### 5. Advanced dependency structures

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
    ├── corners rate (implemented as corners_for_hat)
    └── tempo
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
