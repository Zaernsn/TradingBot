# Next trading-bot improvements

Date prepared: 7 October 2026

Follow-up implementation and deployment evidence: [10 October release record](RELEASE_2026_10_10.md). That record supersedes the original first-release checkpoint below and explicitly separates implemented tools from completed research and pending gates.

## Implementation checkpoint — 10 October 2026

The first release implements the protection monitor and shared public market-data feed:

- A dedicated protection task runs during entry cycles, with a separate five-second scheduled job between cycles. Both reuse the existing database lease, and account order operations share a lock.
- Each protection pass has its own session and adapter. Quotes are fetched with bounded concurrency and processed as they arrive. A slow pair does not hold up another pair's exit.
- Stops and targets use the executable bid. Missing, invalid, or older-than-15-second protective quotes produce a visible failure. Failed or overdue monitoring blocks new entries while exits remain available.
- Positions and cash are refreshed before competing order operations; a protective exit prevents same-cycle re-entry. Existing durable intents and partial-fill reconciliation remain the live order path.
- Persisted protection diagnostics include last check/success, duration, quote age/source, delayed-cycle count, and per-market failures. The UI labels overdue checks even if the last stored status was healthy.
- One shared public WebSocket subscribes to best-bid-offer tickers and 100-level books. It preserves decimal precision, validates Kraken CRC32 checksums, invalidates data after disconnects, and resubscribes with backoff.
- Stream data expires after ten seconds. REST fallback is shared per market, briefly cached, concurrency-limited, paced, and labeled; stale REST observations are rejected.
- A read-only Kraken smoke test received a fresh BTC/EUR ticker and validated 100-level book with zero reconnects. This did not place an order.

Deployment requires migration `n61010protection` and a rebuilt application. The normal container startup runs migrations. No production deployment or trading-account setting change was performed during implementation.

Operational limits: the five-second interval and 15-second monitoring target are operational targets, not guaranteed execution times. Network delays, database blocking, process outages, and an in-flight order can delay checks. This monitor still depends on the application process; it is not an exchange-hosted stop. A stale quiet-market stream deliberately falls back to a current REST observation. Subscriptions are bounded at 128 active symbols and expire after ten minutes without use.

Next implementation work remains stages 3–7 below: verified historical evaluation, richer order execution evidence (including trigger-to-submission latency), rolling-loss halts, and separately evaluated exit/15-minute experiments. The public-feed infrastructure does not establish a profitable strategy or validate real-money execution.

## Goal

Improve safety, responsiveness, and evidence quality before increasing trade frequency or loosening liquidity limits. The bot must continue enforcing spread, exposure, fee, order-size, and reconciliation controls.

Profitability is not yet proven. New strategy behavior should remain in paper evaluation until it passes historical, cost-stress, and forward validation.

## Recommended order

### 1. Independent protective-position monitor

Separate open-position protection from slow discovery, model training, research, and watchlist work.

Planned behavior:

- Monitor open positions on a short, defined interval.
- Continue checking stops, profit targets, holding-time exits, and reconciliation while entry discovery is busy.
- Prevent overlapping or duplicate exit orders through the existing execution lease and order-intent controls.
- Record quote age, monitor-cycle duration, and the time between a triggered exit condition and order submission.
- Treat stale prices, unavailable quotes, and unresolved orders as explicit states.
- Never permit the independent monitor and the main bot cycle to sell more than the held quantity.

Acceptance checks:

- A deliberately slow discovery or training job does not delay protective checks beyond the defined target.
- Restart and concurrency tests do not duplicate exits.
- Entry halts and model failures do not disable protective exits.
- Partial fills and unresolved orders continue to reconcile safely.

### 2. Kraken WebSocket price and order-book cache

Introduce a shared market-data service using Kraken Spot WebSocket v2, with REST as a bounded fallback.

Use:

- `ticker` with best-bid-offer updates for current price and spread.
- Level 2 `book` data for entry and exit depth calculations.
- Timestamps and freshness limits on every cached quote/book.
- Reconnection with backoff, resubscription, and snapshot recovery.
- Kraken book checksums where applicable.

The cache must fail closed: stale or invalid data cannot authorize an entry. Final execution checks must still fetch or validate sufficiently fresh executable data.

References:

- [Kraken Spot WebSocket v2 ticker](https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/ticker)
- [Kraken Spot WebSocket v2 Level 2 book](https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/book)

Acceptance checks:

- Multiple symbols share one managed stream instead of creating repeated frontend-driven market requests.
- Reconnects do not retain stale quotes as current.
- Spread and depth calculations match deterministic fixtures.
- REST fallback is rate-limited and visibly marked as fallback data.
- Dashboard and monitor latency improve without weakening entry checks.

### 3. Import verified Kraken history and establish a baseline

Use Kraken's downloadable historical OHLCVT files rather than relying only on the limited recent REST candle window.

Reference:

- [Kraken downloadable historical OHLCVT data](https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data)

Data work:

- Download the complete archive and relevant quarterly updates.
- Verify published checksums before extraction.
- Preserve the original files and Kraken manifest.
- Convert only the required EUR pairs into the repository's importer format.
- Preserve actual listing dates and missing no-trade intervals.
- Record source URLs, retrieval date, conversion version, and output checksums.
- Keep large datasets and generated research runs out of Git unless deliberately stored through an appropriate artifact mechanism.

Evaluation work:

- Register a frozen research protocol before comparing results.
- Reserve a chronological untouched holdout.
- Compare the current automatic strategy, hourly fast momentum, simple momentum, cash, BTC, and equal-weight holding over matching dates.
- Evaluate normal and doubled costs.
- Report net expectancy, profit factor, maximum drawdown, time underwater, turnover, fees, profit concentration, performance by asset/regime, and uncertainty estimates.
- Preserve failed experiments and do not repeatedly tune against the holdout.

Acceptance checks:

- Imported data passes timestamp, gap, duplicate, OHLC, volume, timezone, listing-date, and checksum validation.
- Identical inputs reproduce the same results.
- No future candle affects an earlier decision.
- A baseline report is produced even when the result is negative or inconclusive.

### 4. Execution-quality evidence

Record the difference between what the strategy expected and what the exchange actually delivered.

Capture for each order:

- Decision and submission timestamps.
- Quote timestamp and age.
- Best bid, best ask, spread, and relevant depth.
- Expected price, price limit, requested quantity, and expected fee.
- Filled quantity, weighted fill price, fee amount/currency, cancellations, and remaining quantity.
- Decision-to-submit, submit-to-acknowledgement, and submit-to-fill latency.
- Realized price impact and slippage versus the decision-time executable quote.

Use Kraken's authenticated `executions` stream as an additional event source while retaining restart-safe REST reconciliation.

Reference:

- [Kraken Spot WebSocket v2 executions](https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/executions)

Acceptance checks:

- Repeated events and restarts do not duplicate booked fills or fees.
- Missing or uncertain outcomes block conflicting orders.
- Reports distinguish spread, fee, market impact, and latency rather than combining them into one number.

### 5. Rolling loss and operational entry halts

Add configurable, independently tested entry halts for:

- Daily deposit/withdrawal-adjusted equity loss.
- Rolling seven-day equity loss.
- Excessive realized execution cost or slippage.
- Stale market data.
- Repeated order or reconciliation failures.
- Excessive protective-monitor delay.

Initial paper hypotheses from the existing strategy plan are a 2% daily halt and 5% rolling seven-day halt. These are research starting points, not automatically appropriate live settings.

Acceptance checks:

- Halts block new entries but preserve exits and reconciliation.
- The reason, start time, evidence, and recovery action are visible.
- Restarting the application does not silently clear a halt.
- Resuming a risk halt requires an explicit operator action where appropriate.

### 6. Controlled exit experiments

Evaluate, one change at a time:

- Existing fixed stop and take-profit baseline.
- Volatility-based initial stop.
- Maximum holding time.
- Trailing exit activated only after a defined favorable move.
- Time-based exit when a position fails to make sufficient progress.

Persist any required high-water mark across restarts. Account for gaps, ambiguous candles, fees, spread, slippage, precision, minimum order size, and partial fills.

Do not activate a challenger merely because it creates more trades or a higher gross return. Require improvement after costs at matched risk.

### 7. Fifteen-minute memecoin entry experiment

Only begin after verified 15-minute data and the preceding measurement infrastructure are ready.

Initial registered hypothesis:

1. Hourly market conditions qualify.
2. A completed 15-minute candle closes above the preceding breakout range.
3. Volume confirms the breakout relative to prior completed candles.
4. Overextended entries are skipped using a volatility bound.
5. Fresh spread, depth, fee, cash, exposure, and order-size checks still pass.

Compare this separately with one predefined pullback/retest variant. Do not blend variants after examining holdout results.

## Do not change yet

- Do not raise the maximum spread merely to remove waiting messages.
- Do not increase memecoin exposure or position count before execution and drawdown evidence supports it.
- Do not enable a 15-minute live strategy before matching replay and cost evaluation exist.
- Do not add exchange-native protective orders until ownership, cancellation, partial-fill, restart, and competing-exit reconciliation are fully designed and tested.
- Do not treat more BUY signals, a high win rate, or a lower validation error as proof of positive net expectancy.

## First-release implementation sequence (completed)

Implement the first vertical slice: independent protective monitoring with measurable latency.

Suggested sequence:

1. Document the current exit path and shared resources in `backend/app/services/bot_service.py`, `backend/app/services/trading_service.py`, and `backend/app/services/live_execution.py`.
2. Define a monitor interval, quote-freshness ceiling, and latency target.
3. Extract or introduce one idempotent `monitor_open_positions` operation that does not run discovery, model fitting, or entry selection.
4. Reuse the current execution lease/order-intent protections instead of introducing a second order path.
5. Add concurrency, slow-discovery, restart, partial-fill, stale-quote, and no-oversell tests.
6. Persist and expose monitor duration, last successful check, oldest quote age, and delayed-cycle count.
7. Only after this slice passes, introduce the shared Kraken WebSocket ticker cache behind the same quote interface.

## Definition of done for the next release

- Protective monitoring has a documented and tested latency target.
- Slow entry work cannot strand an open position without checks.
- WebSocket or cached data can never authorize an entry after it becomes stale.
- Existing accounting, lease, partial-fill, and uncertain-order tests remain green.
- The dashboard clearly distinguishes healthy waiting conditions from operational failures.
- Documentation states what was measured and what remains unproven.

