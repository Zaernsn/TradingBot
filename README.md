# AI trading platform

10 October update: see the [release and deployment record](docs/RELEASE_2026_10_10.md) and [historical baseline results](docs/RESEARCH_BASELINE_2026_10_10.md). Monitoring and optional entry guards are deployed locally; the historical candidates did not pass the development gate. Experimental exits and 15-minute strategies are not enabled live.

## Fast meme momentum

Settings exposes **Fast momentum** as an expert entry strategy: hourly three-hour momentum, six-hour closing-price breakout and volume confirmation. It ranks entries by volatility-adjusted strength, limits orders to 0.1% of daily pair turnover and 5% of available buy/sell depth, and waits one hour after a sale before re-entry. Configure its position, exposure, spread, turnover, and holding-time ceilings in the guided Settings flow; they are not guaranteed order sizes.

The model BUY threshold accepts 40%: BUY strictly above 40%, HOLD at exactly 40%, SELL below 40%, subject to model qualification. Momentum modes do not use a probability threshold. The preset saves 40% for subsequent model use.

After deploying the updated backend/frontend, select Fast momentum under Strategy & markets, review the EUR impact, and save. Alternatively, from `backend/`, run `python -m app.cli.fast_meme --user-id YOUR_ACCOUNT_ID` to select fast momentum and save 40% while preserving that account's existing allocation and fee limits. The CLI tightens liquidity limits only and caps holding time at 24 hours. It does not start the bot or change trading books. No schema migration is required by this change beyond the repository's existing migrations.

There is no mandatory 8–12-week waiting period. Research assessment still requires sufficient evidence and does not activate trading. This version retains fixed stops/profit targets; 15-minute signals, volatility/trailing exits, market-breadth gating and daily/weekly loss halts remain planned work in [the strategy plan](docs/MEMECOIN_STRATEGY_PLAN.md).

## Automatic strategy mode

11 October intraday upgrade: Automatic now includes three bounded **15-minute
breakout** candidates alongside its hourly families. Research, shadow tests and
trading use each candidate's declared candle interval. Public quarter-hour history
is collected automatically; unfinished candles cannot generate signals. See
[the intraday upgrade and development study](docs/INTRADAY_STRATEGY_UPGRADE_2026_10_11.md).

Settings includes an **Automatic** entry strategy. It classifies the completed-hour market basket as defensive, trending, or accelerating. Defensive and insufficient-data regimes remain in cash; broad trends use cost-aware 24-hour momentum; broad acceleration requires the stricter short-term breakout and volume confirmation. Only an explicit `BUY` signal can open a position.

Automatic mode evaluates 24 bounded baseline candidates from five fixed strategy families and may derive at most eight small parameter variants from the best baselines. It never writes or executes strategy code. Research runs in bounded background batches every five minutes, sharing candle snapshots and identical momentum benchmarks within each batch. Failed development or validation gates stop immediately; untested stages remain absent. Tests use chronological development, a 12-hour embargo, validation with two separate positive windows (at least five closed trades each), another embargo, a final test, realistic fee floors, a momentum benchmark and doubled-cost stress. Passing candidates run in a persistent, restart-safe virtual Shadow portfolio while the account remains in Live mode. There is no minimum forward-day wait: 30 closed virtual trades, positive net/stressed performance, benchmark superiority, drawdown limits and bounded profit concentration qualify a candidate for `LIVE_APPROVED_CANARY`. The first live pilot permits at most one position and 5% total exposure against reconciled equity. A realized pilot loss reaching 1% of starting equity suspends new entries; this is not a guaranteed loss cap. Ten reconciled exits with positive aggregate P&L promote it to `LIVE_APPROVED`; unresolved orders, reconciliation/balance failures, excessive costs or a drawdown halt suspend it. Until a candidate qualifies, Live Automatic remains in cash for new entries while monitoring, reconciliation and exits continue. Automatic reevaluates the approved controller's completed hourly or 15-minute signals and current execution conditions each nominal 30-second entry cycle, preserving retry backoff, order controls and a requirement for new completed evidence after an exit. A new timeframe alone does not establish profitability. See [the faster research release](docs/FASTER_AUTOMATIC_RESEARCH_2026_10_11.md).

Research status is available at `GET /api/v1/bot/research/status`. Portable non-authoritative evidence can be exported with `GET /api/v1/bot/research/metadata/export` and imported with `POST /api/v1/bot/research/metadata/import`; imports are always `IMPORTED_UNVERIFIED` until locally re-evaluated.

Autonomous multi-asset paper trading and explicit opt-in Kraken spot execution. Paper mode is the default. Strategy profitability has not been established.

## Local development

Copy `.env.example` to `.env`, set strong secrets, and run `docker compose up --build`. Open `http://localhost:3000`. Both Compose configurations automatically apply pending database migrations before starting the backend, including updates to existing databases. When starting the backend directly outside Docker, run `python -m app.cli.migrate` from `backend/` first. Use `backend/.venv` for the prepared local Python environment.

The bot refreshes its crypto and memecoin watchlist every five minutes (daily in core-only mode) and uses completed hourly signals on nominal 30-second entry cycles. A separate protective task checks holdings every five seconds during and between entry cycles, sharing the existing order/lease controls. Its 15-second timing target is monitored, not guaranteed. The dashboard shows stale checks and quote failures; these block new entries while exits remain available. Configure slots, position/exposure caps, drawdown, fees and slippage in Settings.

Public market data uses a shared Kraken WebSocket ticker and checksum-validated 100-level book cache, with expiring data and bounded REST fallback. Migration `n61010protection` adds persistent monitoring diagnostics; normal container startup applies it. See [the improvement roadmap](docs/NEXT_IMPROVEMENTS.md) for implementation status and remaining work.

## Live trading

Research improvements and tracked-coin entry explanations are documented in [Research workflow](docs/RESEARCH_WORKFLOW.md). Docker Compose applies pending migrations through `m90227shadow` automatically on backend startup. Optional planned-loss sizing and holding-time exits default to disabled. The offline research CLI never activates live trading.

Actual live execution uses separate books and persistent order intents. It requires `ENABLE_LIVE_TRADING=true`, saved per-user Kraken credentials without withdrawal permission, dedicated-account checks, Settings confirmation, and an explicit bot start. Emergency stop halts new orders and reconciles pending orders; it does not sell holdings or switch their label to paper.

## Password reset

The login page links to password reset. Configure `RESEND_API_KEY`, `RESEND_FROM` and `APP_PUBLIC_URL` first. Links expire after 30 minutes and are single-use. A successful reset invalidates existing sessions and stops the bot while preserving actual holdings.

## Deployment and current assessment

- [Production deployment and operation](docs/DEPLOYMENT.md): free/paid hosting options, HTTPS Compose setup, Resend, live activation, backups and history imports.
- [Current review and trading-result priorities](docs/TRADING_BOT_REVIEW.md): resolved findings, verified tests, remaining limitations and evaluation priorities.

The production configuration is `compose.production.yml`, not the development Compose file. The local Docker stack was rebuilt and registration/login verified after fixing automatic migrations and the frontend API proxy. No external hosting deployment or real exchange acceptance trade has been performed.

Container releases are autonomous: pushes to `main` must pass all backend/frontend checks before one multi-platform `trading-bot` image is published to GitHub Container Registry with immutable commit tags, provenance and an SBOM. It contains the API, dashboard, migrations, SQLite ledger and HTTPS proxy. One mounted volume preserves the ledger, models and certificates across image upgrades.

## Kraken memecoins

Memecoin radar and entries are enabled by default; disable them in Settings if desired. The memecoin-focus migration enables this for existing configurations and clears their watchlists for refresh. The bot automatically discovers candidates from Kraken's public meme category and intersects them with active EUR spot markets every five minutes using fresh exchange liquidity checks and completed hourly history, alongside core crypto. The watchlist tracks up to 30 coins total, prioritizing 25–30 eligible memecoins alongside core crypto. The default and maximum concurrent position count is 20. The monitored shortlist is independent of the concurrent position cap; fewer than 30 may be tracked if Kraken EUR markets or quote/history data are unavailable. Entries are checked for market availability, turnover and spread. Defaults cap each position at 5% and total memecoin exposure at 10%; disabling the feature still allows exits from existing holdings. See the review for research and execution limitations.


## Account overview and trade sizing

The dashboard includes a read-only Kraken spot account overview using the signed-in user's saved API key. It records EUR valuations every five minutes while the dashboard is open; history begins with the first sync, not before. Deposits and withdrawals affect balance change, which is not presented as investment return. Unsupported EUR conversions remain unpriced and prevent a misleading account total. Changing API keys starts a separate history. These snapshots never modify paper or live trading books.

Tracked markets show approximate 1-hour, 24-hour and 1-week price changes, estimated 24-hour EUR-pair volume, sorting, search and memecoin/portfolio filters. Missing data is shown as unavailable. Prices and coin quantities support up to seven decimal places.

Settings now uses percentages and grouped controls. Maximum investment per trade is an optional EUR cap, including the fee/slippage reserve (0 disables this additional cap). Smaller allocation/exposure limits still apply. Apply `alembic upgrade head` and rebuild the app to activate the new snapshot table and risk field.


Memecoin discovery uses Kraken category membership and live market/ticker data; you do not maintain a tracked-coin list. Candidates with usable quotes are ranked by liquidity, spread and bounded 24-hour momentum, then evaluated with hourly candle momentum. Tracking does not require the stricter turnover/spread entry limits; these are enforced immediately before buying. Category retrieval failures pause new meme discovery instead of silently reverting to a fixed list. Kraken's category page may cover only its currently displayed assets; this is not an exhaustive catalogue of every meme token. Public market discovery requires no private API credentials.

Connection and live-safety badges both refer to keys saved in the signed-in user's Kraken Connection settings. Server environment keys do not count as personal live credentials. The status distinguishes unsaved and undecryptable keys. Save and Test Connection before explicitly enabling live trading.

Password-reset delivery supports the Resend HTTP API. See [Resend setup](docs/SMTP.md#resend-api-preferred).
