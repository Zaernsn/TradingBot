# Trading bot review and priorities

Updated 19 September 2026. This report distinguishes implemented behavior from exchange and strategy evidence still needed.

## Current verdict

The autonomous paper-trading task and the implementation defects identified in the earlier review have been addressed. Real Kraken spot execution is now wired into the orchestrator, with a persistent order ledger, actual-fill accounting, and a separate live portfolio. Password reset is implemented.

**This does not establish profitable trading or verify your Kraken account.** No real orders were placed, no live credentials were used for acceptance testing, and live mode has not been enabled on your behalf. Deployment, SMTP delivery, and a supervised exchange acceptance test remain necessary.

## What is good now

| Area | Implemented behavior |
|---|---|
| Training labels | Unknown future outcomes are excluded. Labels require returns to exceed modeled round-trip fees and slippage. |
| Chronological learning | Separate training, calibration, and validation windows with horizon gaps. The scaler sees training data only. Models retrain daily or after configuration changes; extreme feature drift withholds entries. |
| Data | Incomplete hourly/daily candles are excluded. Completed candles accumulate in the database. Stale histories are rejected and training uses a contiguous segment. CSV imports support longer histories. |
| Backtest | Fresh independent models, walk-forward training, next-bar execution, shared cash and allocation limits, net entry/exit fees, drawdown, expectancy, turnover, exposure and cash/BTC/equal-weight benchmarks. |
| Selection | Five curated EUR pairs, daily momentum/volatility/volume ranking, positive trend gate. Cash is permitted; slots are a maximum, not a target that must be filled. |
| Risk | Position, total exposure, correlated exposure and drawdown caps. A drawdown halt blocks new entries until explicitly reset while stopped. Exits remain permitted. |
| Monitoring | Nominal 30-second cycles, exits before training. Training runs off the async event loop. A database lease prevents ordinary overlapping workers; startup restores persisted running jobs and unresolved-order reconciliation. |
| Live execution | Explicit server flag and Settings opt-in, verified non-withdrawal permissions, exchange precision/minimums, fee reserve, entry depth checks, price-limited IOC orders. |
| Recovery | Intent recorded before submission. Partial fills booked incrementally and repeated reconciliation does not duplicate them. Uncertain submissions block further orders and are never automatically resent. |
| Accounting | Entry fees allocated into realized P/L, remaining entry fees included in unrealized P/L, base-currency fees supported. Paper and actual EUR-funded live books remain separate. |
| Operator controls | Live order IDs/status/errors visible in Settings. Emergency stop halts new orders and reconciles/cancels pending orders; it preserves real holdings and their LIVE label. |
| Password reset | SMTP email, 30-minute hashed single-use tokens, persistent request limits, account-neutral responses, password confirmation UI. Reset invalidates sessions and stops the bot, leaving actual holdings intact. |
| Deployment preparation | Production Compose, HTTPS reverse proxy, persistent PostgreSQL/model volumes, one backend worker. Local environment files excluded from future Git additions and Docker images. |

## What is not proven or still limited

- **No demonstrated trading edge.** No multi-year, untouched out-of-sample evaluation or extended forward-paper record was produced. Calibrated probability is not expected monetary profit. Thresholds 0.60/0.40, horizon, trend filter and risk defaults remain hypotheses to evaluate.
- **Initial history is short.** Kraken's REST endpoint returns at most 720 candles, including an unfinished candle. The archive grows over time; it cannot retroactively fetch years through pagination. Import independently verified historical CSVs for longer tests. Models with insufficient data or one-class windows HOLD. [Kraken OHLC documentation](https://docs.kraken.com/api-reference/market-data/get-ohlc-data)
- **Backtesting approximates execution.** Stops are checked at hourly opens, whereas live monitoring runs nominally every 30 seconds. It has no historical depth/partial-fill replay, funding/deposit simulation, or statistical confidence intervals. It uses documented default risk fractions, not all of the saved account settings. A separate simple-rule strategy benchmark remains future research.
- **Stops depend on availability.** They are application checks, not exchange-hosted stop orders. Outages and long iterations delay checks. IOC protection can leave an exit partially filled or unfilled in a fast market; small residual amounts may be below exchange minimums. A configured stop percentage does not guarantee that exit price.
- **Dedicated account requirement.** Live activation requires EUR funding and initially no curated-asset holdings or open orders. External trades, deposits, withdrawals, or fee adjustments can cause a balance mismatch and block execution. API-key fingerprints prevent reuse of the same key across local users; they cannot detect different keys belonging to the same Kraken account. Use only one bot/key for that account.
- **Manual recovery may be required.** Missing exchange outcomes, revised fees, unmatched balances or old orders outside exchange query results deliberately block trading. Never clear an UNKNOWN record or retry it without checking Kraken. There is no one-click financial-ledger rewrite or key-rotation workflow.
- **Legacy accounting.** Old open positions retain entry_fees=0 because historical fee allocation cannot safely be reconstructed from incomplete records. New fills use corrected accounting.
- **Operational acceptance remains.** Automated tests use SQLite and mocked Kraken/SMTP. Real permission responses, actual fee currency behavior, real email delivery and real fills were not tested here. Production HTTPS hosting remains untested. Local Docker/PostgreSQL upgrade and frontend-proxy registration/login were verified after locating Docker Desktop outside PATH. Use one backend worker and one deployment; leases are not a claim of audited distributed financial execution.
- **Secret history.** `.env` was tracked by Git. It has been removed from the index, kept locally, and ignored. This does not remove previous commits. If that history ever contained real exposed credentials, replace them before deployment.

## Focus for better trading results

1. **Net expectancy:** evaluate average net P/L per completed trade, including both fees, spread and slippage. A high win rate alone is insufficient. Match the reserve to your actual Kraken taker tier; the live entry gate refuses a reserve below the reported tier. [Kraken fees](https://www.kraken.com/features/fee-schedule)
2. **Untouched evaluation:** collect/import longer histories, reserve a final period before tuning, and compare the full portfolio on the same dates with cash, BTC and equal-weight holdings. Avoid changing parameters based on the final test period.
3. **Downside:** compare return with maximum drawdown, time underwater and exposure. Several crypto pairs can fall together. Defaults are controls, not a personalized allocation recommendation.
4. **Robustness:** examine results by pair and regime, vary nearby thresholds, increase cost assumptions, and check whether a handful of trades account for the result. Track Brier score relative to its baseline rather than trusting the confidence display.
5. **Execution evidence:** forward-test in paper mode, reconcile every supervised live acceptance fill with Kraken, and measure unfilled orders, latency, actual fees and slippage. More frequent trading is not automatically better.
6. **Availability:** keep the backend and database running, back up the ledger, test restart recovery, and monitor bot health. Free sleeping web services are unsuitable for this application's stop monitoring.

## Verification performed

- 50 backend tests pass, including migration upgrade/downgrade/upgrade preserving existing positions.
- Tests cover future-label exclusion, purged calibration/scaler fitting, net fees, walk-forward accounting, partial-fill idempotency, uncertain-order recovery without retry, book separation/reactivation, permission failure, lease exclusion, password reset expiry/reuse, session revocation and request limits.
- Frontend production build passes. Browser checks verified the reset-request screen and missing-token state.
- Earlier deterministic smoke coverage verifies registration, configuring slots, starting paper trading, positions/watchlist consistency and emergency-stop API behavior.
- The existing local PostgreSQL database was backed up and migrated; its missing bot_states.lock_token column had prevented startup. Docker was rebuilt and registration/login verified through the frontend proxy with a temporary account, removed afterward. No actual Kraken trade, external deployment, or real password-reset email was performed.

See [deployment and operation guide](DEPLOYMENT.md) for the remaining setup steps.

## Kraken memecoin extension

Settings now offers an explicit memecoin toggle. Candidates are DOGE/EUR, SHIB/EUR, PEPE/EUR, BONK/EUR, WIF/EUR and FLOKI/EUR. These are candidates only: the bot checks the current Kraken market catalog for an active EUR spot market. Availability can differ by region/account and a symbol's inclusion is not a recommendation.

Defaults: off; maximum 5% equity per memecoin position, 10% across the memecoin group, maximum 0.3% spread, and at least EUR 1,000,000 of pair-specific 24-hour turnover. If Kraken omits quote turnover, base volume times last price is used as an approximation. The usual history, trend, model, fee, depth, correlation and drawdown gates also apply. Entries are rechecked before execution. Disabling memecoins blocks new entries but keeps existing positions monitored for exits.

Tests cover opt-in behavior, inactive/unavailable markets, missing quotes, excessive spreads, insufficient turnover, group caps and exits after disabling. These tests demonstrate controls, not strategy profitability. No memecoin was bought during this work.

Large percentage moves do not imply a high or reliable net profit margin. Liquidity, concentration and abrupt reversals can dominate outcomes. [Kraken's memecoin trading guide](https://www.kraken.com/learn/trading-memecoins)

Individual supported memecoin pairs can be backtested (for example DOGE/EUR), with default memecoin caps and historical turnover checks; at least 720 past hourly candles are required for entries. PORTFOLIO remains the five-core-pair benchmark. There is no full historical memecoin-universe replay with contemporaneous listings/spread/depth, and no on-chain wallet/DEX integration.
