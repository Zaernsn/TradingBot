# Next trading system improvement plan

Date: 11 October 2026
Baseline implementation commit: `bf6ed5d`
Status: proposed implementation sequence; no deployment or trading activation performed.

Implementation checkpoint: incremental shadow replay with persistence, full-replay comparison, and timing telemetry is now implemented locally. See [the release report](INCREMENTAL_SHADOW_RELEASE_2026_10_11.md). The full suite passes 301 tests; the synthetic replay benchmark measures 5.39–7.64× faster updates. Database/network time is excluded. Quote collection, feature caching, execution-cost attribution, and the later research/allocation phases remain outstanding.

Subsequent checkpoint: bounded public quote/depth collection, live execution-cost summaries, replay cost attribution, saved development-loss diagnosis and Strategy Lab displays are implemented locally. See [the execution-cost release](EXECUTION_COST_EVIDENCE_RELEASE_2026_10_11.md). Collection starts after deployment; continuous quote replay, longer retention/export, feature caching, regime attribution and later research/allocation phases remain outstanding.

## Objective

Find useful strategies with less repeated computation and more credible evidence. Improve net performance, execution reliability, and visibility into decisions. A successful research cycle can reject every candidate; profitability is not an assumed outcome.

The current system has 24 baselines across five strategy families, bounded mutations, historical and forward qualification, 15-minute and hourly evidence, and a limited initial live pilot. The latest three intraday development variants lost 9.9–10.3% after modeled costs. Keep those failures and the untouched reserved final-test period intact.

This plan builds on the October releases. It supersedes delivery ordering in older plans where features have already been implemented. It adds no fixed seven-day qualification wait. Later learning generations currently require two weeks of new evidence; changing that policy requires a separately evaluated research protocol.

## 1. Make forward testing incremental

**Purpose:** reduce repeated simulation work without changing the strategy's decisions.

- Measure current research/shadow run duration, database reads, bars processed, and delay imposed on protective monitoring. Save a reproducible performance baseline before optimization.
- Extract a replay transition that advances one completed candle while retaining cash, positions, cost basis, cooldowns, rolling loss state, regime history, and pending execution semantics.
- Persist independent normal-cost, doubled-cost, and benchmark shadow states, each with its last processed timestamp and frozen data/code/risk identity.
- Resume from the checkpoint after restart. Duplicate job delivery must not duplicate trades or advance the same bar twice.
- Define how revised or late candles invalidate a checkpoint. Preserve missing-bar behavior, warmup restarts, next-bar fills, and terminal liquidation rules.
- Cache immutable candle/features inputs across compatible candidates. Avoid sharing mutable portfolio state. Add bounded workers only after measuring lease, database, and protective-monitor contention.

**Acceptance:** incremental and full replay produce matching decisions, trades, fees, and equity for hourly/15-minute fixtures, including gaps and restarts. Work per update scales with new bars rather than the entire shadow history. Record measured runtime improvement; do not claim a speed multiplier in advance.

**Main areas:** `strategy_research.py`, `backtest.py`, persistence models and migrations.

## 2. Collect and measure actual execution conditions

**Purpose:** determine whether potential signals can survive the costs of trading them.

- Archive timestamped best bid/ask and bounded order-book snapshots for the watched markets, with source, age, and collection failures. Start collection while step 1 is developed.
- Preserve fee provenance and order constraints with each decision. Keep offline cost scenarios distinct from verified account fees.
- Log why each opportunity was skipped and its expected spread, fees, slippage, size, and available liquidity at decision time.
- Compare predicted costs with actual fills and fees when already-authorized trading produces them. Attribute partial fills and unknown outcomes explicitly.
- Add replay of recorded quote/depth observations, including stale quotes, partial fills, rejected orders, and limited liquidity. Label older candle-only studies as lower execution fidelity.

**Acceptance:** every recorded decision can be traced to observations available at that time. Execution-cost reports reconcile fills to accounting and expose missing evidence. Replay cannot use a later quote to justify an earlier fill.

**Main areas:** exchange adapters, `live_execution.py`, `bot_service.py`, market-data persistence, research reports.

## 3. Diagnose failures and validate across market conditions

**Purpose:** discover whether a candidate has an enduring advantage rather than a favorable test period.

- Decompose existing losses by fees, turnover, asset, entry/exit reason, exposure, holding duration, and market regime before adding strategy complexity.
- Register chronological walk-forward folds and horizon-aware embargoes before tuning. Separate development, validation, and final evaluation roles.
- Record the historical tradable universe and listing/data availability where evidence exists. Report survivor-selection limitations where it does not.
- Compare candidates with cash and simple baselines on matching dates, prices, costs, and exposure context.
- Account for dependence and the number of attempted candidates in uncertainty reports. Specify confidence and minimum-effective-sample rules before enabling them as promotion gates.
- Keep a permanent experiment registry and sealed final-test accounting across generations. Never select mutation parents from final-test outcomes.

**Acceptance:** a candidate report shows performance and uncertainty by fold and regime, all related trials, concentration, and cost sensitivity. Weak evidence remains unqualified. New rules must not retroactively approve an old candidate without fresh evaluation.

**Main areas:** `evaluation.py`, `research.py`, `strategy_research.py`, research CLI and artifact registry.

## 4. Improve the bounded search using those diagnostics

**Purpose:** spend computation on explicit hypotheses supported by development evidence.

- Test one change at a time: fewer marginal entries, persistence/volume confirmation, regime-specific eligibility, or an exit-policy change. Register the hypothesis and its parameter bounds first.
- Track which neighboring parameters remain useful after costs instead of selecting a single sharp optimum.
- Prioritize candidates by potential information gained and computational cost, with a documented allowance for exploring other families.
- Consider smaller, evidence-triggered later generations instead of the current two-week trigger only after step 3 can track fresh evidence and repeated testing. Measure effective independent opportunities; elapsed time or extra bars alone is insufficient.
- Keep candidate budgets, deduplication, frozen parent selection, and risk bounds. A child must earn its own approval.
- Add a new strategy family only when collected data supports its inputs and a registered study can evaluate its incremental value.

**Acceptance:** each generated child has a traceable parent, bounded changes, hypothesis, and evaluation record. A search-policy change is compared with the current bounded search on development data without consuming the reserved final test for tuning.

**Main areas:** `strategy_factory.py`, `strategy_research.py`, experiment registry.

## 5. Improve allocation and live evidence attribution

**Purpose:** choose among qualified opportunities and assess the controller's own results.

- Rank eligible opportunities using development-estimated net payoff, downside, execution cost, uncertainty, and diversification. Compare with current watchlist-order allocation under equal risk constraints.
- Attribute complete round trips to the exact controller/version, including partial fills and fees. Preexisting holdings must not qualify a new controller.
- Define capital stages supported by reconciled live evidence and execution quality. Preserve the current one-position/5% pilot until a separately validated change is implemented.
- Add cost deterioration, stale-data, and strategy-performance entry suspension criteria with clear recovery requirements. Exits and reconciliation remain available during suspension.

**Acceptance:** deterministic allocation comparisons show where ranking adds value. Only a controller's own reconciled trades count toward its progression; restarts and partial fills cannot double-count evidence. No rollout or capital increase is performed as part of planning.

**Main areas:** `bot_service.py`, `risk_service.py`, `live_execution.py`, `strategy_research.py`.

## 6. Make research and operations understandable

- Show the current hypothesis, rejection reason, cost breakdown, evidence freshness, and next qualification requirement in Strategy Lab.
- Distinguish missing data, failed performance, insufficient evidence, active shadow testing, and operational suspension.
- Display research/shadow latency and protective-monitor health. Define operating targets after measurement.
- Exercise recovery from API failures, stale candles, lease expiry, database interruption, duplicate jobs, and unresolved orders. Verify protective exits and accounting throughout.

**Acceptance:** the interface explains why the bot is waiting and what evidence would change that state. Recovery drills preserve order idempotency and reconcile positions without duplicate entries or exits.

## Delivery sequence and first implementation slice

1. Record timing baselines and add decision/cost telemetry; begin bounded public quote collection.
2. Implement incremental shadow replay behind an internal comparison mode, then enable it only after parity checks.
3. Produce the loss-attribution report and registered walk-forward evaluation protocol.
4. Trial a small diagnostic-driven candidate cohort and compare research scheduling policies.
5. Implement controller-specific live attribution before considering progression changes; evaluate opportunity ranking separately.
6. Add the corresponding interface explanations and recovery checks alongside each release.

The first major implementation should be **incremental shadow testing with restart parity**. Deliver it as a focused change with checkpoint migration, full-replay comparison fixtures, performance measurements, and an updated evidence report. Quote collection can begin independently, but collecting data must not activate trading.

Research and execution/accounting changes should remain separate reviewable releases. Source/configuration changes invalidate incompatible approval evidence. Deployment verification is a separate task: rebuild/restart, confirm worker health and data collection, and verify existing account state without altering activation or exposure.
