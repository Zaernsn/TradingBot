# Research and forward validation

Implemented 21 September 2026. These tools do not place orders or automatically promote a candidate to live trading.

Verification: 107 backend tests passed, including migration upgrade/downgrade with position preservation, intrabar/gap stops, listing timelines, source checksums, holdout reuse rejection, risk sizing, forward snapshots and frontend hint reasons. TypeScript checking, the production frontend build, and tracked-coin rendering/calculation checks passed. Existing dependency deprecations and the frontend bundle-size advisory remain. These checks establish implementation behavior, not profitable results or real exchange acceptance.

## What is available

- Backtests use the supplied saved risk configuration, shared entry budgets and open-price exit rules. The HTTP backtest defaults to `use_saved_risk: true`; explicit request fee/horizon/slot overrides apply only with `use_saved_risk: false`.
- Different listing dates no longer truncate the entire portfolio to the intersection of histories. Missing held-asset prices are flagged, never converted into fictitious terminal fills.
- Completed hourly high/low data detects stop/target touches. If both occur, the stop wins. Gaps execute at the adverse open. Historical volume constrains entries using the preceding candle, without looking at future volume. Exit liquidity and historical spread/depth remain assumptions.
- Experiment artifacts contain the complete risk configuration, data hashes, deterministic run IDs, equity curves, monthly/asset P&L, profit concentration, drawdown, time underwater, and moving-block bootstrap intervals. Intervals are diagnostics; correlated trades and many tested variants still require careful interpretation.
- Three preregisterable research candidates: existing `signal-v2`, simple `momentum`, and a conditional historical `payoff` challenger. The payoff model estimates fixed-horizon outcomes, not the exact payoff of every exit policy. Research challengers are not wired into live execution.
- Each run compares the candidate against cash, available full-period BTC/equal-weight holdings, a momentum strategy, and doubled fee/slippage assumptions. Simple return superiority plus the configured drawdown ceiling is a conservative screening rule, not a complete risk-adjusted comparison.
- Optional planned-loss sizing and maximum holding time are available through Settings, both disabled by default. Larger observed volatility reduces the permitted allocation; stop gaps can exceed the planned loss budget.
- Runtime snapshots collect equity, configuration/code identity, health errors, and cycle duration every five minutes. Protective exits are checked before discovery. Training/discovery still share the worker cycle; complete independent protective monitoring remains outstanding.
- Tracked coins show the latest entry reason and check time. Stopped bots and stale checks are explicitly labeled. An hourly BUY that failed a gate is reconsidered on the next completed candle under the existing signal schedule.

## Database migration on startup

Both development and production Docker Compose already run `python -m app.cli.migrate` before starting the backend. This upgrades to the latest migration, including `h90221risk` and `i90221drift`; an error prevents the backend from starting. Applied migrations are tracked and are not reapplied on each restart.

For the development stack, rebuild and start the updated containers:

```powershell
docker compose up -d --build
```

An already-running backend does not run startup migrations until its container restarts or is recreated. No separate migration command is needed with either Compose file. For a backend started directly outside Docker, run this from `backend/` after the normal database backup:

```powershell
.\.venv\Scripts\python.exe -m app.cli.migrate
```

Migration `h90221risk` adds optional risk fields, research snapshots, and bot entry-reason storage. It preserves existing positions and order records. No database migration or application deployment was performed as part of this implementation.

## Prepare historical data

No verified multi-year CSV dataset was present in this workspace during implementation. Supply chronological UTC hourly CSVs with columns:

```text
timestamp,open,high,low,close,volume
2024-01-01T00:00:00Z,100,102,99,101,500
```

The example row is synthetic format documentation, not market evidence. Invalid OHLCV, missing hours, duplicates, unfinished candles, changed checksums, and missing timezone offsets are rejected. Do not fabricate candles to repair gaps. Keep the original source, conversion steps, listing/category evidence, and checksums.

[Kraken publishes downloadable historical OHLCVT data](https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data). Its raw format may need conversion to the above named-column UTC format. This implementation does not download the entire exchange archive or verify a historical universe on your behalf.

Example manifest, saved beside the CSV:

```json
{
  "assets": [{
    "symbol": "BTC/EUR",
    "file": "btc-eur-hourly.csv",
    "source": "Replace with exact source URL and retrieval/conversion notes",
    "sha256": "Replace with actual SHA256 of the CSV"
  }]
}
```

Use `Get-FileHash -Algorithm SHA256` to calculate a file checksum; use lowercase hexadecimal in the manifest.

Example protocol (dates and costs are illustrative; choose and freeze them before evaluating):

```json
{
  "development_start": "2024-01-01T00:00:00Z",
  "holdout_start": "2025-01-01T00:00:00Z",
  "end": "2026-01-01T00:00:00Z",
  "initial_cash": 500,
  "warmup": 720,
  "select_assets": true,
  "candidates": ["signal-v2", "momentum", "payoff"],
  "participation_rate": 0.01,
  "minimum_order_eur": 10,
  "risk": {
    "max_position_pct": 0.2,
    "stop_loss_pct": 0.03,
    "take_profit_pct": 0.06,
    "fee_pct": 0.004,
    "slippage_pct": 0.001,
    "max_daily_trades": 10,
    "trading_pair": null,
    "prediction_horizon": 12,
    "max_open_positions": 5,
    "memecoins_enabled": false
  }
}
```

Include pre-evaluation history for warmup. Short history is not sufficient to evaluate multiple regimes. New listings need their own actual start dates. Backtests do not reconstruct historical category membership from today's list.

## Register, compare, freeze, evaluate

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m app.cli.research register --manifest ../research-data/manifest.json --protocol ../research-data/protocol.json --output ../research-runs/first
.\.venv\Scripts\python.exe -m app.cli.research run ../research-runs/first --candidate signal-v2
.\.venv\Scripts\python.exe -m app.cli.research run ../research-runs/first --candidate momentum
.\.venv\Scripts\python.exe -m app.cli.research run ../research-runs/first --candidate payoff
.\.venv\Scripts\python.exe -m app.cli.research freeze ../research-runs/first --candidate signal-v2
.\.venv\Scripts\python.exe -m app.cli.research run ../research-runs/first --stage holdout --candidate signal-v2
```

Choose the candidate from development evidence, not from the example command. The development run does not pass holdout candles to the engine. The holdout is marked consumed before execution, including a failed attempt. Do not delete its marker to retry or tune; investigate failure and record that the holdout was exposed. Exclusive artifact creation prevents accidental overwrite; these local files are an audit aid, not tamper-proof storage.

Changes to research code or datasets require a new registered protocol. An already exposed holdout does not become untouched merely because you create a new directory. Keep all experiments, including failures, to account for selection bias.

## Forward reports

After deployment and explicit paper-bot start, snapshots accumulate. Starting this work did not start the bot. The authenticated `GET /api/v1/bot/research/forward` returns the current user's active-book report and a conservative go/no-go assessment. It cannot inspect another user's book.

CLI export for the operator:

```powershell
.\.venv\Scripts\python.exe -m app.cli.research forward --portfolio-id 1 --output ../research-runs/forward.json
.\.venv\Scripts\python.exe -m app.cli.research assess --historical ../research-runs/first/HOLDOUT-ARTIFACT.json --forward ../research-runs/forward.json --output ../research-runs/assessment.json
```

Replace the portfolio ID and artifact path. An identity change, insufficient observation, weak results, missing costs, unresolved orders, or incomplete provenance produces NO_GO. Paper execution cannot supply actual exchange slippage evidence, so the automated report explicitly retains that limitation. No report authorizes or activates live trading. Daily retraining is part of the recorded strategy policy; the individual trained model is not frozen for 8 weeks.

## Still required before phases 2–5 can be called complete

1. Obtain and validate multi-regime histories and contemporaneous listing/liquidity evidence; run real candidate experiments. No profitability conclusion was produced from synthetic regression fixtures.
2. Extend execution replay with finer historical quotes/depth, precision by market, and actual partial fills. Add regime-specific evaluation, broader parameter-neighborhood tests, and risk-matched benchmark analysis.
3. Validate any selected model/exit changes; rolling-window normalized-feature comparisons, trailing exits, and a separate fast memecoin strategy remain research work. Runtime recovery can automatically select a qualified normalized-v1 model; see the drift and watchlist plan.
4. Complete independent protective monitoring, configured external alerts, execution-quality/rolling-loss halts, and exchange-hosted protection with order-lifecycle reconciliation.
5. Collect forward observations and assess evidence as it arrives. The default promotion policy has no minimum calendar duration; minimum trade counts, uncertainty, drawdown, costs and order-integrity requirements still apply. Then conduct separately authorized supervised exchange acceptance and staged capital increases.

Exchange-native stops were investigated but not bolted onto the current IOC ledger: [Kraken documents that stop orders can be independent of positions and require cancellation after another exit](https://support.kraken.com/hc/articles/7699391647892-stop-loss-orders). Safe support requires persistent protection ownership and reconciliation of both protection fills and normal exits. That lifecycle is not implemented here.
