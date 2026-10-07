# Trading bot improvement plan

Date: 20 September 2026

## Objective and scope

Improve net trading performance and resilience through reproducible evidence. Success means positive net expectancy, acceptable drawdown, and a useful advantage over simple alternatives on unseen data and forward execution. Profitability is a hypothesis to test, not an assumed outcome.

This plan authorizes no live activation, capital increase, or change to current account settings. Implementation should preserve existing books, accounting, reconciliation, and exit behavior. Failed entry qualification must never prevent protective exits.

## Phase 1 — Establish trustworthy measurements and fix known inconsistencies

Deliverables:
- Add a reproducible experiment record: strategy/model version, data version, time range, seed, complete risk configuration, costs, and result artifacts.
- Record decision reasons, including skipped entries, alongside trade attribution and expected versus realized execution costs. Keep secrets out of research artifacts.
- Make asset selection explicitly timeframe-aware. Currently hourly memecoin history reaches a selector whose volatility uses sqrt(365); separate hourly and daily lookbacks and annualization. Select thresholds deliberately for each timeframe.
- Surface model validation against its baseline. Mark inadequate validation as unqualified for new entries; keep existing-position exits available. Predictive validation alone must not qualify a strategy for live deployment.
- Snapshot the current strategy as the baseline before changing behavior.

Primary code: `backend/app/services/asset_selector.py`, `backend/app/ml/models.py`, `backend/app/services/bot_service.py`, relevant persistence/API models.

Acceptance: identical experiment inputs reproduce decisions/results; hourly/daily fixtures verify correct timeframe treatment; a model worse than its baseline cannot open a qualified entry; exits still work when entry qualification fails. Every evaluated trade can be attributed to its settings and model version.

## Phase 2 — Build reliable historical evaluation

Deliverables:
- Import verified history, aiming for multiple market regimes and several years for established assets where available. Respect actual listing dates for newer coins.
- Validate timestamps, gaps, duplicates, price/volume sanity, symbol identity, and source provenance. Do not silently fabricate tradable candles.
- Reserve a final chronological holdout before tuning. Use walk-forward development with horizon-aware gaps and an experiment log tracking all attempted variants. Do not repeatedly tune against the final holdout.
- Share pure strategy and risk-decision functions between simulation and runtime; inject the saved configuration rather than constructing hardcoded backtest risk defaults.
- Replay finer candles for exits where available. Specify conservative handling when a candle touches both stop and target and the path is unknown. Simulate gaps, precision/minimums, spread, fees, slippage, and incomplete fills to the extent supported by data.
- Evaluate a changing, point-in-time universe instead of selecting today's survivors. Preserve each asset's valid timeline rather than truncating every asset to the intersection of all candle timestamps. Label unavailable historical spread/depth/listing evidence explicitly.
- Compare with cash, BTC, equal-weight holdings, and a simple momentum strategy over identical dates and cost assumptions; also compare risk/exposure.
- Report net return, net expectancy, drawdown, time underwater, turnover, fees, per-asset/regime results, and concentration of profits. Add block-bootstrap uncertainty estimates that respect serial dependence, plus sensitivity to higher costs and nearby parameters.

Primary code: `backend/app/ml/backtest.py`, `backend/app/services/market_data.py`, `backend/app/cli/import_candles.py`, shared strategy/risk modules to extract.

Acceptance: no future information affects an earlier decision; deterministic scenarios reconcile cash, fills, fees, positions, and equity; equivalent observed inputs/configurations yield matching simulation/runtime decisions. Missing evidence produces limitations, not invented precision. Produce a baseline report even if it shows losses.

## Phase 3 — Improve trade selection through controlled experiments

Deliverables:
- Align research targets with the actual exit policy: today's fixed-horizon probability does not describe the payoff of every stop/target/model exit.
- Compare the current classifier with simple rules and a model estimating net payoff/downside. Use normalized features where appropriate instead of relying on price-level indicators across changing price regimes.
- Rank eligible opportunities by estimated net reward relative to risk and uncertainty before allocating capital. Current runtime entry order follows the watchlist.
- Research a small, preregistered set of regime filters, such as trend, range, and stressed liquidity. Cash remains a valid decision.
- Research memecoin momentum separately from core crypto. Test volume acceleration, momentum persistence, and spread/depth signals only with timestamped data collected before decisions. Faster signals require their own execution and cost evaluation.
- Change one major hypothesis at a time. Retain a challenger only if its improvement survives untouched evaluation and cost/parameter stress.

Acceptance: a report explains incremental value over the frozen baseline, including failed experiments. If no candidate clears qualification, retain paper research rather than relax the standard to force trading.

## Phase 4 — Improve position sizing, exits, and operational resilience

Deliverables:
- Add sizing based on a configurable loss budget and stop distance/volatility, bounded by existing cash, position, correlation, meme, and total-exposure caps. Stops can gap; include stress-loss estimates beyond the planned stop.
- Compare fixed exits with volatility-based stops, trailing exits, and maximum holding periods. Select through Phase 2 evaluation rather than assuming additional exit rules help.
- Add rolling loss/execution-quality entry halts and clear operator recovery states. Retain reconciliation and exit access during halts.
- Decouple protective monitoring from slow discovery/training without permitting concurrent conflicting orders. Measure actual monitor latency and stale-quote age.
- Investigate exchange-native protective orders through current official exchange documentation. Implement only with explicit lifecycle handling for partial fills, cancellations, restarts, and protection replacement; prevent duplicate exits.
- Add health alerts and recovery drills for stale data, API failures, expired leases, unknown orders, database outages, and orphaned holdings. Alert channels need operator configuration.

Primary code: `backend/app/services/risk_service.py`, `backend/app/services/bot_service.py`, `backend/app/services/live_execution.py`, exchange adapters.

Acceptance: stress and restart tests preserve accounting and order idempotency; entry halts cannot strand exits; no protection path can oversell a position. Increased volatility reduces permitted size for otherwise comparable trades. Monitoring latency has a defined and measured operating target.

## Phase 5 — Forward validation and staged rollout

Deliverables:
- Freeze a candidate version and run forward paper trading with the actual discovery, risk, and execution constraints. Record simulated-fill limitations explicitly.
- Use an initial observation window of 8–12 weeks, extending it if there are too few independent opportunities or insufficient market variety. Duration or raw trade count alone is not evidence of an edge.
- Before evaluation, record numeric drawdown, exposure, execution-cost, and uncertainty tolerances for the intended account. Existing settings are initial constraints, not automatically suitable targets.
- Promotion requires positive net expectancy with credible uncertainty analysis, a useful return/risk advantage over simple baselines, robustness to plausible costs, and no unresolved execution/accounting defects. Brier-score improvement alone is insufficient.
- After explicit live authorization, perform a small supervised acceptance run and reconcile every fill and fee against the exchange. Increase capital only through predefined stages after actual execution matches assumptions.
- Automatically suspend new entries when live costs, data quality, or risk limits invalidate the qualification assumptions; preserve exits and reconciliation.

Acceptance: a written go/no-go report distinguishes historical, forward-paper, and actual-live evidence. A no-go outcome is valid. No automatic progression merely because a calendar date arrived.

## Delivery order

1. Phase 1 measurement and correctness changes.
2. Phase 2 historical evaluation and baseline report.
3. Phase 3 candidate research, while collecting forward quote/depth evidence.
4. Phase 4 risk and execution improvements, with urgent availability fixes brought forward when necessary.
5. Phase 5 forward validation and separately authorized live acceptance.

Each implementation slice should include focused regression coverage and an updated evidence report. Keep migrations compatible with existing positions and order records. Avoid combining research changes and financial-ledger changes in a single broad release.

## First implementation slice

Build the experiment/configuration snapshot, fix timeframe-aware selection, and add the model entry-qualification status with exit-preservation tests. Then remove hardcoded backtest risk settings and produce the first reproducible baseline comparison. These changes establish whether subsequent work actually makes the bot better.

### Implementation checkpoint — 20 September 2026

- Implemented the first predictive entry gate in `SignalModel.predict`: BUY becomes HOLD unless finite, valid Brier scores beat the baseline with at least 30 validation rows. Equal/worse, missing, or invalid evidence cannot qualify. SELL signals remain available. This gate applies to runtime and backtests using the real model, including loaded models.
- Added `entry_qualified` to available-model predictions and an explicit explanation for blocked buys. This is a minimum predictive check, not statistical proof of profitability or permission to activate live trading.
- Added parameterized regression coverage in `backend/tests/test_signal_qualification.py` for qualification, blocked buys, retained sells, invalid evidence, and unfitted models.
- No deployment or account-setting changes performed. Existing workspace changes predate this slice and must be preserved.
- Next: fix timeframe-aware selection, add experiment/configuration snapshots, then share backtest risk settings and produce the baseline report. The remaining phases above are still outstanding.

## Deferred until evidence justifies them

Leverage, additional exchanges, social/LLM sentiment, on-chain wallet tracking, more concurrent positions, and higher trading frequency. Each introduces new costs or failure modes and needs its own incremental evidence.

## Implementation checkpoint — 21 September 2026

Research infrastructure for phases 2–5 and frontend entry hints have been added. See [RESEARCH_WORKFLOW.md](RESEARCH_WORKFLOW.md) for commands, migration, evidence limitations, and the explicit outstanding work. Phase 2 now supports provenance manifests, registered development/holdout windows, saved risk settings, listing-aware timelines, conservative intrabar stops, reproducible artifacts, and cost stress. Phase 3 has offline momentum/payoff challengers. Phase 4 has optional loss-budget sizing and time exits plus protective checks before discovery. Phase 5 has runtime evidence snapshots and a fail-closed assessment report. These are partial implementations; none of phases 2–5 is represented as having achieved its full acceptance criteria or proven profitability.
