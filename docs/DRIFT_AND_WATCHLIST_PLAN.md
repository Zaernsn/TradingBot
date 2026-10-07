# Drift recovery and useful memecoin watchlists

Date: 21 September 2026

## Objective

Explain and resolve persistent drift warnings, prioritize markets that can actually be evaluated and traded, and expand discovery only when measurements justify it. Success is reliable decisions and clearer visibility, not a required number of BUY signals.

This is a follow-on implementation plan. It does not change trading thresholds, enable live execution, or increase capital/exposure limits.

## Findings from current code

- `SignalModel.predict` returns HOLD when any feature exceeds eight training standard deviations. It reports neither the feature nor the measured deviation.
- Moving averages, Bollinger bands, MACD and average volume contain absolute levels. Price/volume regime changes can move these outside the fitted distribution. This is a hypothesis to investigate, not a diagnosis of the running account.
- Drift sets `trained_at=None`, but the orchestrator skips evaluation when it already saved a signal for the latest candle. Therefore retraining normally waits for a new completed hourly candle; the message can imply faster recovery than actually occurs.
- Daily retraining uses the archived contiguous history, up to 8,760 hourly candles. Repeating training on essentially the same distribution need not resolve real drift.
- Discovery queries active EUR markets in the discovered meme category, then retains up to 60 ranked meme candidates. This is not necessarily a cap of 60 ticker requests. The visible watchlist contains up to 30 total assets, including core coins.
- Monitoring intentionally admits coins that fail stricter entry liquidity checks. HOLD can also mean missing history or failed validation. A BUY signal still needs cash, exposure, order-size and live execution checks.

## 1. Diagnose before changing behavior

Implement structured diagnostics per symbol: triggering feature(s), observed value, training mean/scale, deviation, training date, training-history range, usable rows, latest completed candle and validation result. Separate normal HOLD, SELL, unavailable data, model drift, validation failure and execution blockers.

Store diagnostics with signal/entry records and expose a concise frontend explanation with expandable details. Include a summary showing how many coins are blocked for each reason. Never show raw private exchange credentials or request payloads.

Acceptance: a deliberately shifted feature identifies the correct cause; missing/invalid history gets its own status; the dashboard can answer whether most blocked coins share one failure. Capture a baseline of drift frequency, affected features and retraining outcomes before changing features.

Primary files: `backend/app/ml/models.py`, `backend/app/services/bot_service.py`, signal schemas/API, `frontend/src/components/TrackedCoins.tsx`.

## 2. Make retraining recovery explicit and bounded

Replace the implicit timestamp reset with clear states: ready, retraining requested, retraining, waiting for new data, and blocked after retraining. Keep the hourly signal deduplication rule for normal trading, but allow one bounded recovery attempt for a recorded drift event. Re-evaluation must not duplicate an order or re-enter after an exit.

Use a separate fitted candidate while retaining the previous model artifact. Replace it atomically only after successful fitting and the existing validation checks. Persist recovery state so a restart does not create a retry loop. If the same feature still drifts after retraining, stop retrying the same data and explain that fresh history or investigation is needed.

Keep training concurrency bounded. Recovery work must not block protective exit checks; measure cycle/exit-monitor latency during training. Model-driven SELL may be unavailable during drift, so explicitly preserve independent stop, target and configured time exits.

Acceptance: same-candle drift triggers at most one recovery attempt; repeated cycles and restarts do not retrain indefinitely or duplicate buys; failed validation leaves entries blocked; existing-position protective exits still execute.

## 3. Research features that remain comparable across price levels

Create a versioned challenger feature schema using dimensionless quantities: price relative to moving averages, MACD relative to price, Bollinger position/width, relative volume, returns and volatility. Handle zero/near-zero denominators and flat markets explicitly. Fit preprocessing on the training window only.

Keep the existing model as the baseline. Compare rolling 3-, 6- and 12-month training windows where verified data supports them. Collect longer history for development/holdout evaluation; do not treat the present one-year runtime load limit as a complete multi-year dataset. Study robust drift statistics and near-constant features without silently clipping real market shocks away.

Acceptance: multiplying all OHLC prices by a constant leaves the intended normalized features unchanged; no future leakage; real shocks still produce diagnostics. Select a challenger only if unseen-data validation and net trading results justify it. Fewer warnings alone is insufficient. Version artifacts so old pickles cannot be used with incompatible features.

Primary files: `backend/app/ml/features.py`, `backend/app/ml/models.py`, research protocol and tests.

## 4. Separate discovery, eligibility and trade signals

Maintain a cached discovery pool with per-market status and timestamps. Evaluate availability, usable contiguous history, model readiness, spread/turnover, minimum order size and quote freshness before prioritizing the visible shortlist. Keep portfolio cash/exposure limits as a separate, account-specific check.

Add frontend views:

- **Eligible markets:** pass the latest market/data checks; may currently be HOLD or SELL.
- **Buy candidates:** qualified BUY signal and latest preflight checks pass, with a visible check time. This does not guarantee a fill; checks run again immediately before submission.
- **Waiting / blocked:** explicit reason, such as insufficient history, drift recovery, validation failure, wide spread or allocation limit.
- **Held:** always visible and monitored, regardless of current category/watchlist eligibility.

Continue updating eligible HOLD/SELL markets in the background so they can become candidates later. Avoid a circular design that only calculates signals for coins already labeled BUY. Give temporary blockers a cooldown; require stable eligibility before rotating coins into/out of the shortlist. Do not hide a held asset or stop its exits when its entry eligibility fails.

Acceptance: blocked coins no longer monopolize the actionable shortlist; a HOLD-to-BUY transition becomes visible; stale checks cannot appear ready; held assets survive rotation; all final execution guards remain enforced.

Primary files: discovery/eligibility services, `asset_selector.py`, `bot_service.py`, bot-state API, tracked-coin UI.

## 5. Expand scanning only after measuring the bottleneck

Measure funnel counts: discovered markets, quotes available, sufficient history, market eligible, model qualified, BUY candidates, and orders blocked by portfolio limits. Also measure request volume, rate-limit failures, total scan duration and protective monitoring delays.

Make discovery retention and visible shortlist limits distinct validated settings, separate from position count. Use cached market catalogs, incremental quote refresh and bounded request concurrency. Cache historical data and batch model work so a larger discovery pool does not refit every coin every 30 seconds.

Retain the existing limits initially. Expand the retained pool in a controlled paper experiment only when more eligible markets exist outside it and processing has capacity. If the category source does not enumerate all markets, report that coverage limitation rather than promising every Kraken memecoin.

Acceptance: a larger pool produces measurably more usable candidates without increased protective-monitor latency, API failures or unmanageable watchlist churn. Keep position count, per-position allocation and meme/total exposure caps unchanged. If all coins fail the same model/data gate, resolve that gate instead of expanding.

## Delivery and validation order

1. Diagnostics and frontend reason counts.
2. Bounded retraining lifecycle and exit-preservation tests.
3. Versioned normalized-feature research and verified history ingestion.
4. Eligibility-aware shortlist and frontend filters.
5. Measured discovery expansion and forward comparison.

For every release, test relevant accounting/order-idempotency regressions alongside the changed behavior. Use migration-backed persistent state where needed; both Compose configurations already apply pending migrations on backend startup.

Track blocked-reason distribution, drift recurrence after recovery, stale-data frequency, shortlist churn, signal-to-entry conversion, execution costs and paper net performance. A healthy outcome may still contain no current BUY candidates. Broader scans, fewer HOLD labels and higher trade counts are not profitability evidence.

## First implementation slice

Add feature-level drift diagnostics, training/history timestamps and a dashboard blocker summary. Then use those observations to fix the recovery lifecycle. This gives a concrete explanation for the current warning before deciding whether features, data, or discovery breadth need changing.

## Implementation checkpoint

Implemented feature-level diagnostics, persisted background recovery with cooldowns, eligibility-aware watchlists, dashboard readiness filters, and separate discovery/watchlist limits. As requested, runtime recovery now compares legacy and normalized-v1 candidates and automatically saves the qualified candidate with the lowest validation Brier score after checking current drift. Failed candidates retain the incumbent; workers cannot place orders. This predictive validation does not establish profitability.

Migration `i90221drift` is applied by the existing Compose startup migration command; it was also observed in the running database. Verification: 107 existing backend tests and two new recovery tests passed; frontend type checking and tracked-coin tests passed. The recovery tests cover automatic selection, duplicate-candle suppression, failed qualification, and persisted restart cooldown behavior.

Remaining empirical work: verified longer history, rolling-window comparisons, and forward paper measurements of net performance, discovery capacity, and protective-monitor latency. No claim of improved returns or completed forward evaluation is made.
