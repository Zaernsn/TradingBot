# Order placement: repository evidence

Read from the local checkout on 2026-09-20. This is a code trace, not a live exchange test. The HTML is the overview; this guide expands its grouped components. Source links point to the local checkout.

## Signal / exit

[bot_service.py](../../backend/app/services/bot_service.py), `_schedule`, `_run_iteration`, `_iterate` (lines 31, 112, 154): runs every 30 seconds, with scheduler max_instances=1, a per-user asyncio lock and a database lease. Existing holdings are marked to ticker.last and checked for stop-loss/take-profit before model training. Exit orders use the held quantity and bid (last as fallback). Model SELL also exits a held position; HOLD and SELL without a position produce no order.

[models.py](../../backend/app/ml/models.py), `SignalModel.predict`: completed-candle features produce calibrated probability; BUY above 0.6, SELL below 0.4, otherwise HOLD. Unavailable model/features or drift over 8 produce HOLD. Signal persists action, probability, confidence, features and candle timestamp before execution. The latest signal timestamp prevents processing the same candle again; this is not an exchange idempotency guarantee.

## Entry risk + sizing

[bot_service.py](../../backend/app/services/bot_service.py), lines 255–295; [risk_service.py](../../backend/app/services/risk_service.py), `entry_budget`, `can_trade_today`, `check_drawdown`:

- BUY requires a selected watchlist, available selection, no drawdown halt, no position in the symbol, no exit of that symbol this iteration, room under max_open_positions and the daily BUY limit. Live daily limits count ExecutionOrder rows, including unsuccessful intents; paper counts Trade rows.
- Budget is the nonnegative minimum of the optional per-trade EUR cap, memecoin allowance, equity/max_open_positions, equity × max_position_pct, cash, remaining total exposure and remaining correlated exposure. Missing/short history or undefined correlation is treated conservatively as correlated; returns use up to 168 periods and require 30 aligned points.
- [memecoin_service.py](../../backend/app/services/memecoin_service.py) enforces enabled state, valid positive quotes/turnover, spread and EUR-pair turnover limits, plus per-position and aggregate memecoin allocation caps.
- Budget ≤ EUR 0.01 skips entry. Fresh ask (last fallback) must be finite and positive. Live `fetch_trading_fee(symbol)` must provide taker fee no greater than the configured reserve.
- Quantity = budget × (1 − 1e−10) / [price × (1 + slippage_pct) × (1 + fee_pct)]. `prepare_order` applies precision/minimums; `fetch_order_book(limit=100)` caps quantity to ask depth inside the slippage boundary; precision/minimums are checked again. Equity/drawdown is rechecked after network waits.

These entry gates are not all applied to SELL: risk exits can reduce holdings while new entries are halted.

## Execution guards and locally blocked outcomes

[bot_service.py](../../backend/app/services/bot_service.py), `_execution` (131): rechecks running state, lease and active book; refreshes per-trade cap and memecoin exposure/liquidity. PAPER branches here into local accounting. LIVE verifies balances and enters `execute_live`.

[live_execution.py](../../backend/app/services/live_execution.py), `assert_live_enabled` (42), `verify_balances` (111), `execute_live` (130): requires server enable flag, LIVE mode/book, active book, matching credential fingerprint, running state and valid lease. Any unresolved ExecutionOrder blocks a new live order. At iteration start, permissions must allow balance/open/closed order query, modify and cancel, and must not allow withdrawals.

`fetch_balance()` TOTAL holdings must match the local position ledger (asset tolerance max(1e−9, expected × 1e−7)); EUR must match cash within EUR 0.02. `fetch_open_orders()` must not contain unmanaged order IDs. This is ledger reconciliation, not a separate available/free-balance reservation system.

[kraken.py](../../backend/app/exchanges/kraken.py), `prepare_order` (113): load markets; require active EUR spot pair; convert amount and price to exchange precision; check positive amount/cost and exchange amount/cost min/max. LIVE computes limit = quote × (1 + slippage) for BUY or quote × (1 − slippage) for SELL, prepares again, and checks BUY limit notional plus fee reserve against cash.

Most failed guards skip or raise before an ExecutionOrder exists. They do not create exchange rejection records. After an intent exists, stopped/invalid live controls, changed investment cap or changed memecoin cap mark it REJECTED locally before submission. Diagram's “Locally blocked” groups these early exits; every guard can stop its own path.

## Durable intent → Kraken IOC → acknowledgement

[live_execution.py](../../backend/app/services/live_execution.py), lines 140–175: commit ExecutionOrder with UUID client_id, symbol, side, requested_quantity and SUBMITTING before network submission. Recheck live controls and the current investment/memecoin caps.

[kraken.py](../../backend/app/exchanges/kraken.py), `submit_ioc` (147): CCXT `create_order(symbol, 'limit', side.lower(), quantity, limit, {'cl_ord_id': client_id, 'timeinforce': 'IOC', 'oflags': 'fciq'})`. The repository calls CCXT; the exact wire endpoint and library retry behavior are not established by this trace.

A successfully parsed response supplies exchange_id. Commit PENDING, then query status immediately. Acknowledgement alone does not book a fill. The generic `KrakenExchange.place_order` method exists but is not the orchestrator's live execution path.

## Reconcile status → fill or terminal outcome

[live_execution.py](../../backend/app/services/live_execution.py), `reconcile_order` (55), `reconcile_all` (94); [kraken.py](../../backend/app/exchanges/kraken.py), `get_order_status`, `find_order`, `_order_to_result`:

- With exchange_id: `fetch_order(id, symbol)`. Without it: query open and closed orders with cl_ord_id, then match raw info.cl_ord_id. Multiple matches raise; no match sets UNKNOWN.
- Adapter maps open → PENDING, closed → FILLED, canceled/expired → CANCELED, rejected → REJECTED; unrecognized status defaults to PENDING. FILLED is therefore a mapping of closed, not a separate filled-equals-requested assertion.
- Validate order ID, finite/nonnegative cumulative quantity/cost/fees, quantity not above requested, and monotonic totals. New filled quantity requires positive incremental cost. Previously booked cost/fee revisions without new quantity raise for manual reconciliation. Filled orders without fee information or with unsupported fee currency also raise.
- Subtract previously booked totals, pass only the new quantity/cost/quote-fee/base-fee delta to `record_fill(commit=False)`. Commit ledger totals, exchange status and accounting together. Repeated identical cumulative reports do not book the same fill twice.
- PENDING may already have a partial fill. CANCELED may also contain a partial fill, which is booked before terminal status. REJECTED/CANCELED without new filled quantity only update order state. Terminal set is FILLED, CANCELED, REJECTED.

[trading_service.py](../../backend/app/services/trading_service.py), `record_fill` (8): BUY adds net received quantity after base fee, adjusts weighted entry price and entry fees, subtracts gross cost plus quote fee from cash. SELL removes quantity plus base fee, allocates entry fees, computes realized P&L, adds proceeds less fee, and deletes an exhausted position. Both create a Trade and recalculate equity/unrealized P&L. Invalid values, insufficient ledger cash or over-selling raise rather than fabricating accounting.

## UNKNOWN, polling, duplicate protection and errors

Submission or immediate-reconciliation exceptions become UNKNOWN unless already explicitly REJECTED locally. Even an API exception that might mean rejection follows this uncertain path. No submission retry is implemented. Every subsequent scheduled live iteration reconciles first; unresolved outcomes block further live orders. Lookup is retried, not order creation. No bounded retry counter, exponential backoff or automatic timeout-to-rejection was found. CCXT enableRateLimit is configured; that is not evidence of an application retry policy.

[execution_lease.py](../../backend/app/services/execution_lease.py): database lease lasts 120s; orchestrator renews every 20s and checks the token before execution. [portfolio.py](../../backend/app/models/portfolio.py): unique client_id/exchange_id plus unique open portfolio/symbol position. Together with the in-process lock, scheduler cap, saved candle timestamp and unresolved-order barrier, these reduce duplicates. They are not a claim of exactly-once exchange submission.

Reconciliation exceptions roll back accounting, save last_error and block new live orders. Per-symbol failures generally roll back and accumulate errors; a live BUY execution exception breaks the entry loop. Bot health becomes DEGRADED or RISK_HALTED, while outer exceptions set ERROR. Model-exit exceptions can reach the outer handler. Errors do not imply the exchange failed to accept an order.

Stopping keeps reconciliation scheduled for unresolved orders, attempts `cancel_order`, and polls again. Adapter cancellation exceptions return False; reconciliation must establish the actual outcome. Emergency stop does not liquidate holdings. Finally-block cancellation errors are suppressed. Restart sweep schedules running bots or books with unresolved orders.

## Paper branch and implementation boundaries

[trading_service.py](../../backend/app/services/trading_service.py), `execute_paper_trade` (57): verifies PAPER book, applies configured slippage and fee, calls record_fill directly. No real submission, exchange acknowledgement or durable ExecutionOrder is created. [paper.py](../../backend/app/exchanges/paper.py) supplies Kraken public market data; its generic place_order is not used by this orchestrator accounting path.

Unclear/missing in the traced code:

- Client-ID recovery searches open/closed orders without explicit pagination; completeness of exchange history retrieval is not established. Unknown orders can remain blocked indefinitely, requiring inspection/manual reconciliation.
- There is no exchange websocket fill consumer, separate partial-fill status, or resubmission of canceled IOC remainder in this path.
- Entry signal persistence precedes execution; a failed/skipped entry is not retried from the same saved candle. Later candles may generate a new attempt.
- Stop-loss/take-profit checks are polling-based exits, not exchange-native resting protection orders.
- No explicit pre-submit free-balance reservation or separate SELL quantity-versus-position check appears in execute_live; orchestrator supplies held quantity, balance reconciliation precedes submission, and accounting checks over-selling after a fill.
- No external exchange request was made to verify runtime behavior. Configuration, deployed schema and actual Kraken responses may differ from this checkout.
