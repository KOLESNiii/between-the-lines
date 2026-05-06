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
