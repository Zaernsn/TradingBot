# Deployment and operation

Updated 19 September 2026. The production files are prepared; no hosting account was created and no server was deployed.

## Where to host

The backend must stay running even when nobody opens the dashboard. Stop monitoring and reconciliation occur there, not in the browser.

- **Possible free option: Oracle Always Free VM.** Resource availability varies and idle instances can be reclaimed. Treat this as a paper-testing option first. ARM availability does not guarantee the pinned Python ML dependencies build successfully; verify on the selected image. [Oracle limits](https://docs.public.content.oci.oraclecloud.com/iaas/Content/FreeTier/resourceref.htm)
- **Recommended for continuous operation: a small paid Linux VPS**, for example Hetzner in an EU region. Start with roughly 2 vCPU / 4 GB RAM for this single-user configuration and monitor memory/training duration. Budget roughly EUR 10/month including potential IP, backup and tax extras; inspect the actual checkout price. [Hetzner plans](https://www.hetzner.com/cloud/cost-optimized/)
- **Render's free web service is unsuitable for the bot backend:** it sleeps after 15 minutes without inbound traffic. Its free PostgreSQL service also has retention limitations. A frontend-only free host does not keep the trading process alive. [Render free-service restrictions](https://render.com/docs/free)

## Production layout

`compose.production.yml` runs one application container containing the FastAPI worker, built static frontend, migration runner, persistent SQLite ledger and Caddy HTTPS proxy. Only ports 80/443 are published. The database, model files and HTTPS state share one named volume at `/var/lib/trading-bot`. Caddy routes `/api/*` to the loopback backend and supports frontend password-reset routes. Do not use the development `docker-compose.yml` on a public server.

Every push to `main` runs the backend and frontend checks before publishing one multi-platform `trading-bot` image to GitHub Container Registry. Releases receive immutable `sha-<commit>` tags, while version tags and `latest` are convenience aliases. Production should use the immutable SHA tag in `.env.production`. The image includes build provenance and an SBOM; the server pulls it and does not compile application source. SQLite runs in WAL mode with foreign-key enforcement and a busy timeout for the single-worker application.

Prerequisites: Linux server, Docker Engine with Compose plugin, a domain pointing to the server, inbound TCP 80/443 (plus SSH restricted to your administration source), and outbound access to Kraken and the Resend API. A paid domain and email service may add cost even on a free VM.

1. Copy the reviewed repository to the server, excluding local `.env`, databases, virtual environments and model files unless deliberately restoring a backup.
2. Copy `deployment.env.example` to `.env.production`. Set `APP_HOST` to your domain, `APP_PUBLIC_URL` to its HTTPS URL, and `APP_IMAGE` to the published immutable commit tag. Set independently generated strong secrets. Preserve `KRAKEN_ENCRYPTION_KEY` across redeployments or existing encrypted API credentials become unreadable.
3. Configure `RESEND_API_KEY`, `RESEND_FROM` (a verified-domain sender) and `APP_PUBLIC_URL`. Password resets use the Resend HTTPS API exclusively. Do not use production recipients in automated tests.
4. Leave `ENABLE_LIVE_TRADING=false` for the first deployment.
5. From the repository root:

```bash
chmod 600 .env.production
docker compose --env-file .env.production -f compose.production.yml config --quiet
docker compose --env-file .env.production -f compose.production.yml pull
docker compose --env-file .env.production -f compose.production.yml up -d
docker compose --env-file .env.production -f compose.production.yml ps
docker compose --env-file .env.production -f compose.production.yml logs --tail=100 app
```

Avoid printing the expanded Compose configuration: it contains secrets. Backend startup runs `python -m app.cli.migrate` before serving. Container restarts restore saved running bot state; stop the bot before planned maintenance if automatic resumption is unwanted.

6. Verify `/health`, registration/login, paper trading, stop, and password-reset email delivery from your real deployment. Check bot health after a controlled server restart. The local development Docker/PostgreSQL stack and frontend-proxy registration/login were verified. External production HTTPS/email hosting still requires this smoke test.

For an existing database, back up the `bot-data` volume first and check `alembic current` before upgrading. The migration runner recognizes known legacy create_all layouts, preserving matching empty tables that a failed startup may already have created. Unknown layouts stop rather than guessing. Downgrading the execution migration refuses to remove existing live financial history.

## Enabling actual Kraken execution

1. Use a dedicated EUR-funded Kraken account with no initial curated-asset holdings or unmanaged orders. Never run multiple keys/bots against the same account.
2. Create a key with balance queries, open/closed order queries, order creation/modification and cancellation. Do not enable withdrawals. The application verifies permissions through Kraken's [GetApiKeyInfo endpoint](https://docs.kraken.com/api-reference/account-data/get-api-key-info).
3. Save that key and secret in Settings. Credentials are encrypted in the database. Live execution uses explicitly saved per-user credentials, not a shared server key.
4. Stop the bot. Set `ENABLE_LIVE_TRADING=true` in the server's `.env.production` and redeploy the backend. Open Settings, review risk fractions and actual fee tier, then confirm **Enable Live Trading**. The live book starts from the actual EUR balance; paper history is preserved.
5. Click **Start Bot** explicitly. A HOLD or empty watchlist is valid; do not force a trade merely to fill slots. Watch health, orders and Kraken balances during supervised acceptance.
6. Compare each accepted order/fill/fee to Kraken. IOC orders may fill partly or not at all. An uncertain submission is never retried automatically. [Kraken order parameters](https://docs.kraken.com/api-reference/trading/add-order)

Emergency stop prevents new submissions as soon as the in-flight code observes it and attempts pending-order reconciliation/cancellation. It does **not** liquidate holdings. An already submitted request cannot be recalled before Kraken processes it. Stop-loss checks require the running server; they are not exchange-hosted protective orders.

Do not delete an UNKNOWN order, change its status manually, or place a replacement until its exchange outcome is established. Inspect Settings > Live order recovery for IDs. On each running live cycle (and when reactivating a live book), EUR deposits/withdrawals synchronize only when a continuous sequence of recent Kraken funding ledger entries exactly explains the balance difference. Enable **Data - Query ledger entries** on the API key for this check. No withdrawal permission is needed. Cash, equity, the net-funding baseline, and the equity peak adjust together; deposits are not trading profit and existing risk halts remain set. Open orders, changed non-EUR holdings, intervening external trades, missing ledger access, or insufficient recent history prevent automatic synchronization. Stopped books synchronize on reactivation; viewing the account overview alone does not change the trading book.

## Longer historical data

Kraken REST provides at most 720 recent candles. For research, import trusted contiguous CSVs with UTC timestamps and columns `timestamp,open,high,low,close,volume`. Import both `1h` and `1d` for portfolio selection tests. Existing archived timestamps are preserved.

From `backend/`, using the application's Python environment:

```bash
python -m app.cli.import_candles btc-hourly.csv --symbol BTC/EUR --timeframe 1h
python -m app.cli.import_candles btc-daily.csv --symbol BTC/EUR --timeframe 1d
```

Repeat for the other curated assets. Settings accepts `PORTFOLIO` to evaluate selection and shared cash. The API supports evaluation start/end dates, horizon, fee/slippage and slot count. The current evaluation window loads at most 8,760 hourly candles and 720 daily candles per pair. Missing periods invalidate a continuous backtest; do not fabricate candles just to make it run.

## Backups and maintenance

Back up the `bot-data` volume and encryption secret securely, and test restoring while the bot is stopped. Preserve the named volume on upgrades; do not use `docker compose down -v`. Never restore an old live ledger and immediately resume trading without comparing it to Kraken. Configure external uptime/error alerts separately; none were provisioned here.

The same image can run without Compose for a local paper instance:

```bash
docker run -d --name trading-bot --restart unless-stopped \
  -p 80:80 -p 443:443 -p 443:443/udp \
  -v trading-bot-data:/var/lib/trading-bot \
  ghcr.io/zaernsn/trading-bot:latest
```

The image defaults to plain HTTP on port 80, SQLite persistence and disabled live execution. Supply production secrets, `APP_HOST`, `APP_PUBLIC_URL` and `ENABLE_LIVE_TRADING` as environment variables when intentionally changing those defaults.

The local `.env` was previously tracked. Removing it from Git does not erase historical commits. If real credentials were ever exposed in that history, replace them before deployment.

## Local registration startup fix (verified)

The supplied log showed `UndefinedColumn: bot_states.lock_token` and `Application startup failed`. `create_all` created missing tables but could not add columns to existing ones. The Docker startup command now runs migrations first and the frontend waits for backend health. Browser API requests use the frontend proxy; the backend always uses the Compose database hostname rather than a host-only localhost database URL.

The existing local database was backed up to `backups/before-20260919.dump`, upgraded to `e90219meme`, and the stack rebuilt. Registration and login were verified through the proxy, and the synthetic account was removed. Existing database volumes were retained.

For subsequent starts from the repository root:

```bash
docker compose up -d --build
docker compose ps
```

Open `http://localhost:3000/register`. If a browser tab predates the rebuild, refresh it. Do not delete the database volume to fix a registration error. Password reset additionally requires the Resend API key and verified sender.

## Memecoin mode

Enable **Settings > Kraken memecoins > Include eligible memecoins**, adjust limits if needed, and save. It affects both PAPER and LIVE books; test in paper mode before enabling real-money execution. Defaults cap each position at 5% and the group at 10%, with 0.3% maximum spread and EUR 1 million minimum 24h pair turnover. Core slots and broader portfolio caps still apply. Disabling the feature leaves existing holdings monitored for exits. It is limited to Kraken EUR spot candidates, with current market availability checked at selection time.
