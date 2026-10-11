# Self-improving trading strategy — 10 October 2026

## Decision

A self-improving trading strategy is only viable if it is designed as a controlled learning system, not as a free-form optimization loop. The baseline research shows that the current momentum candidates underperform cash, so this strategy must be built around three principles:

1. Learn from evidence, not from live wins.
2. Improve only within a validated research sandbox.
3. Fail safe and revert to cash whenever confidence or capital protection degrade.

The proposed system is deliberately conservative. It does not assume that more trading, more models or more frequency will produce better results. Instead, it continuously tests, ranks and retires components using a locked train/validation/test pipeline, strict risk caps and a cash fallback policy.

## Basis in the current baseline

The current development baseline concluded:

- No candidate passed the development gate.
- All tested strategies lost money under normal and doubled-cost conditions.
- Cash outperformed all three strategies.
- The most durable lesson is not “add one more signal” but “do not promote any model without evidence and capital protection.”

This strategy therefore treats the baseline as the negative control: it does not attempt to salvage the existing momentum logic as-is. It creates a separate adaptive architecture that is designed to improve only when it can prove it is better than cash on held-out evidence.

## Objective

Build a portfolio strategy that:

- learns from market regimes and execution friction,
- updates its model set under a governance loop,
- avoids overfitting to a single market regime,
- preserves drawdown discipline,
- defaults to cash whenever signal confidence is poor,
- upgrades strategies only with a strict evidence threshold.

## Core design principles

### 1. Evidence-first promotion

No rule, feature group or model is promoted to live trading unless it passes all of the following:

- out-of-sample validation on a non-overlapping period,
- stress testing with doubled costs,
- drawdown and exposure checks,
- comparison against cash and a baseline passive portfolio,
- a holdout period with no tuning.

The system must maintain a research ledger of every candidate, its data fingerprint, backtest configuration and its performance under both normal and stress assumptions.

### 2. Regime-aware adaptation

The strategy must adapt to market regimes rather than fit one static rule across all markets. Regimes include:

- trend-following contexts,
- trend exhaustion or mean reversion,
- volatility expansion,
- liquidity stress,
- memecoin rotation and correlation bursts,
- low-volatility chop.

Models should be trained on a rolling basis, but only small, explainable changes are promoted. The strategy learns which model families are useful under which conditions, rather than forcing a single single “best” model.

### 3. Capital protection above optimization

The strategy is not allowed to optimize for return alone. It must optimize for risk-adjusted survival. All candidate changes must satisfy:

- max drawdown guardrail,
- max exposure cap,
- daily loss halt,
- trade count control,
- mandatory cash fallback under weak confidence.

### 4. Human governance around automated learning

The learning loop must not be entirely unsupervised. The system should log:

- why a candidate was added,
- what it is meant to improve,
- how it was validated,
- why it was promoted or rejected.

This creates a research trail similar to a controlled experiment, which is essential because naive self-improvement can easily turn into overfitting disguised as adaptation.

## Strategy architecture

### A. Market and feature layer

The strategy consumes the same data integrity discipline used in the baseline research:

- use verified OHLCVT source data only,
- maintain data fingerprints and provenance,
- never create synthetic bars,
- treat gaps as real data constraints,
- avoid filling in missing data with heuristics.

Feature groups should include:

- trend features: slope, z-score, breakout persistence,
- momentum features: relative strength, rolling returns, acceleration,
- volatility features: realized volatility, range expansion, ATR,
- liquidity features: spread, depth proxies, slippage risk,
- regime features: drawdown state, correlation stress, concentration state,
- execution features: spread-adjusted expected return, fee-adjusted edge.

Features are scored for predictive value in a rolling validation window and pruned if they are unstable or weak.

### B. Model ensemble layer

The core logic is not one monolithic predictor. It is a lightweight model ensemble with at least three families:

1. Trend model
   - estimates directional persistence
   - upweights when volatility is controlled and trend is stable

2. Mean-reversion model
   - activates in short, overextended conditions
   - suppressed when large directional moves dominate

3. Risk-adjusted candidate model
   - focused on expected value after fees and slippage
   - incorporates spread cost and probability-of-loss

Each model produces a directional signal and a confidence score. The system only acts when the ensemble agrees, or when a single model has very high confidence and the risk envelope is favorable.

### C. Risk controller layer

The controller decides whether to trade at all. It should enforce:

- maximum 1% risk per trade,
- maximum 20% per asset on a standard allocation,
- total portfolio exposure cap,
- concentration limit by sector or asset group,
- maximum exposure to meme-like or highly correlated assets,
- emergency halt when drawdown exceeds a threshold,
- immediate cash de-risking when market regime becomes unfavorable.

This is a strict portfolio-level constraint, not a soft guideline.

### D. Learning and selection layer

This is the self-improving component. It should:

- score candidate strategies using rolling out-of-sample windows,
- compare them against cash and a simple passive baseline,
- test them with realistic fees and slippage assumptions,
- reject candidates that only win in one narrow regime,
- archive failed ideas without deleting context.

The learning system continuously updates a candidate leaderboard, but the live system only accepts promotions that satisfy the promotion gate.

## Self-improving loop

### Phase 1: Baseline lock

The system starts from a conservative default portfolio:

- cash-heavy baseline,
- minimal trade count,
- strict risk caps,
- no position if confidence is weak.

This acts as the floor performance reference. If adaptation cannot outperform this baseline with statistical durability, the system stays idle.

### Phase 2: Candidate generation

Generate new candidate specifications within a research sandbox, including:

- alternate entry/exit windows,
- varying stop and target ranges,
- model combinations,
- regime-specific parameter sets,
- feature subset searches,
- risk scaling factors.

Candidates are never evaluated directly on the live account. They must be tested on curated historical data and then shadowed in paper mode.

### Phase 3: Rolling validation

Each candidate is measured across multiple windows:

- recent regime,
- earlier regime,
- stress cost scenario,
- drawdown scenario,
- volatility expansion scenario,
- low-volume and high-correlation periods.

The promotion gate requires the candidate to beat the baseline across a majority of relevant windows and not just one narrow segment.

### Phase 4: Shadow deployment

A candidate that passes research validation is deployed in paper or shadow mode for a fixed observation period. During this stage:

- no capital is committed,
- live feed is processed in real time,
- trade logic is executed conceptually,
- results are compared with live market data and execution assumptions,
- all decisions are logged and reviewed.

This stage is used to test information quality, fill behavior, slippage sensitivity and regime drift.

### Phase 5: Promotion or rejection

Promotion requires all criteria to be met:

- net expectancy positive after fees and slippage,
- drawdown below guardrail,
- profit factor above a minimum threshold,
- no single-regime dominance only,
- live shadow result consistent with historical evidence,
- no material degradation in correlation risk or exposure.

If not met, the candidate is rejected or retuned.

### Phase 6: Controlled decay

A strategy should not persist forever just because it once worked. All model families undergo decay monitoring:

- degradation of Sharpe-like behavior,
- increasing false positives,
- rising execution costs,
- reduced predictive stability,
- regime incompatibility.

When a component decays, it is either retrained, replaced, or moved to monitoring-only status.

## Required safeguards

### 1. No direct optimization on live data

The strategy must never search for parameter values by repeatedly watching live account performance. This is the main anti-pattern behind many fragile “self-improving” systems. Live data should only be used for validation, not for unbounded tuning.

### 2. Locked holdout period

Every parameter set and model configuration should be protected by a holdout period. The holdout is not used for tuning; it is used to confirm the result before promotion.

### 3. Hard stop conditions

The live system must have the following emergency rules:

- daily loss limit,
- rolling drawdown limit,
- max exposure cap,
- max single-asset concentration,
- max total positions,
- zero trading when confidence is below threshold,
- immediate revert to cash on abnormal volatility or execution risk.

### 4. Realistic cost assumptions

The system must model:

- taker fees,
- slippage,
- spread costs,
- partial fill impact,
- cost increase during volatility spikes,
- delayed execution risk.

Any strategy that only works with idealized costs is not allowed to promote.

## Performance metrics for the self-improving system

The core evaluation should include at least the following:

- net return,
- drawdown,
- profit factor,
- net expectancy per trade,
- average trade duration,
- cost-adjusted return,
- distribution of wins and losses,
- regime-specific performance,
- turnover and slippage impact,
- correlation to benchmark assets,
- confidence calibration of the model.

A self-improving strategy cannot rely on raw return alone. It must prove that its risk-adjusted decisions remain stable after friction.

## Proposed operational policy

### Default behavior

When no candidate clears the evidence gate, the system should remain in a conservative cash or low-risk portfolio mode. The baseline is not a recommendation to “trade more aggressively”. It is a reminder that inactivity is often the best strategy when predictive edge is absent.

### Candidate update cadence

The system should update on a fixed schedule only, such as:

- weekly model retrains,
- monthly feature review,
- quarterly strategy reset if degradation is observed,
- ad hoc retraining only after major regime shifts.

This prevents the learning loop from reacting to every short-lived market wobble.

## Implementation roadmap

### Phase 1 — research foundation

- lock data sources and fingerprints,
- define benchmark and cash baseline,
- build realistic cost and slippage simulation,
- create a regulated evaluation environment.

### Phase 2 — candidate library

- add trend, mean reversion and alert-based models,
- create feature scoring and pruning,
- add cost and regime segmentation.

### Phase 3 — training and validation loop

- train on rolling windows,
- validate on non-overlapping intervals,
- score against cash and passive benchmark,
- reject unstable or overfit sets.

### Phase 4 — shadow deployment

- run live-paper simulation,
- measure execution drift and fill quality,
- confirm that the model survives real market conditions.

### Phase 5 — promotion governance

- maintain experiment log,
- allow only approved candidates,
- require no-change holdout before live activation.

### Phase 6 — live portfolio management

- allocate only when confidence is high,
- keep cash as the default safety state,
- lower risk immediately if market quality deteriorates.

## Success criteria

The strategy passes only when it demonstrates all of the following:

- better risk-adjusted performance than cash after fees,
- stable result across multiple regimes,
- positive expectancy under realistic execution assumptions,
- disciplined drawdown control,
- no overfitting to a narrow historical pattern,
- measurable improvement from one iteration to the next under evidence.

If the strategy cannot meet these conditions, it remains in cash and the system continues learning without risking capital.

## Final principle

The goal is not to create a strategy that always trades aggressively. The goal is to create a system that knows when to trade, when to wait, and when to do nothing. In the current baseline, the clearest lesson is that capital preservation and evidence quality matter more than strategic ambition.

This self-improving strategy is therefore designed to grow only under strict validation, to scale conservatively, and to prefer robust survival over noisy optimization.
