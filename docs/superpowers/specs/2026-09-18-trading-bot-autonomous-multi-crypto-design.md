# Trading Bot: Autonomous Multi-Crypto Trading

## Overview

Move the bot from a single user-selected trading pair to an autonomous portfolio that trades up to 5 curated crypto pairs simultaneously. The bot selects its own watchlist, allocates capital, and manages positions without per-pair user settings.

## Current State

- `BotOrchestrator` runs one APScheduler job per user (`bot_{user.id}`) every 5 minutes.
- Each iteration trades only `RiskConfig.trading_pair` (`backend/app/services/bot_service.py:91`).
- `RiskConfig` stores a single `trading_pair` chosen by the user in `Settings.tsx`.
- `Position` has a `symbol` column, but the data model and business logic assume one open position per user.
- `SignalModel` is cached per `(user, symbol)`; only one model is active per user at a time.
- Frontend dashboard shows the single active pair and its chart.

## Goals

1. Remove the requirement for the user to pick a trading pair.
2. Let the bot autonomously select and maintain a watchlist of up to 5 pairs.
3. Trade all 5 pairs simultaneously, with one position per pair.
4. Keep paper trading default and preserve live-mode safety controls.
5. Update the dashboard to show the autonomous watchlist and multi-position state.

---

## 1. Autonomous Asset Selection

### Change

Add an `AssetSelector` service that scores the curated universe and returns a ranked list. The bot uses the top 5 as its active watchlist.

### Scoring inputs

For each curated pair, compute from daily OHLCV:

- **Momentum**: 7-day return normalized by volatility.
- **Volume**: recent average volume vs. 30-day average.
- **Signal quality (optional v1)**: latest prediction confidence or a simple win-rate estimate for the pair's cached `SignalModel`. A full backtest sharpe is out of scope for the first version because the existing backtest engine has a known bug; signal quality can be added once the backtest is fixed.
- **Volatility filter**: exclude pairs whose 7-day annualized volatility is below a minimum or above a maximum to avoid flat or erratic markets.

### Selection cadence

- Run selection once per day inside the existing 5-minute loop to avoid excessive churn.
- Persist the current watchlist in `BotState` so the dashboard can display it.
- On first run (empty watchlist), select immediately.

### API / Service

```python
class AssetSelector:
    async def select(self, user_id: int, universe: list[str]) -> list[str]:
        """Return up to 5 ranked symbols for the user."""
```

---

## 2. Multi-Position Data Model

### Change

Allow one open position per `(user_id, symbol)` and add portfolio-level controls for the 5-slot strategy.

### Database

- `Position` table: enforce at most one **open** position per `(user_id, symbol)`. Closed historical positions for the same symbol are allowed. Use a partial unique index on `(user_id, symbol)` where `is_open = true` if the database supports it; otherwise enforce in code and rely on `is_open` filtering.
- `RiskConfig`:
  - `trading_pair` becomes optional and is no longer used by the bot (kept for migration/data compatibility).
  - Add `max_open_positions: int = 5` (default 5, clamped 1–10).
  - Add `allocation_mode: str = "equal"` (only `"equal"` supported now).
- `BotState`: add `watchlist: list[str]` (JSON column) and `watchlist_updated_at: datetime`.
- `Portfolio`: add `target_positions: int = 5` mirroring `RiskConfig.max_open_positions` for fast reads.

### Migration

- Alembic migration to add columns and, if needed, adjust the unique constraint on `Position`.
- Existing users with a single position keep it; on the next selection cycle the bot expands to up to 5 pairs.

---

## 3. Bot Orchestrator Changes

### Change

`BotOrchestrator._run_iteration` becomes a per-symbol loop over the autonomous watchlist.

### New flow

```text
1. Load user portfolio + risk config.
2. If watchlist is stale or empty, call AssetSelector.select(...).
3. Fetch equity and compute per-slot budget = equity / max_open_positions.
4. For each symbol in watchlist (sorted by rank):
   a. Fetch ticker + OHLCV.
   b. Update existing Position mark-to-market (create if none and signal fires).
   c. Check stop-loss / take-profit for existing positions.
   d. Fit/predict with SignalModel for this symbol.
   e. If BUY signal and no open position for symbol and slots remain:
      - size = min(slot_budget, max_position_pct * equity)
      - execute paper or live trade
   f. If SELL signal and position exists:
      - close position
5. Enforce global limits: max_open_positions, daily trade count, total exposure.
```

### Scheduler

- Keep one job per user (`bot_{user.id}`) every 5 minutes.
- No per-symbol scheduler jobs; Approach B keeps scheduler load at one event per active user.

### Signal model cache

- Keep `self.models: dict[(user_id, symbol), SignalModel]`.
- Lazy-load/fit when a symbol is first selected.

---

## 4. Capital Allocation

### Equal-weight default

- Each active slot gets `equity / max_open_positions`.
- `RiskManager.slot_budget(portfolio, risk, symbol)` returns this value.
- Per-trade size is capped by both the slot budget and the existing `max_position_pct` setting.
- If a slot is already occupied by an open position, new capital is not added to that symbol; the slot is considered used.

### Example

- Equity = 500 EUR, `max_open_positions = 5`, `max_position_pct = 0.25`.
- Slot budget = 100 EUR; per-trade cap = 125 EUR.
- New BUY size = 100 EUR.

---

## 5. Autonomous Execution

### What the bot decides autonomously

- Which pairs to trade (via `AssetSelector`).
- When to enter/exit per pair (via `SignalModel` + SL/TP).
- Position size per pair (via equal-weight allocation + risk caps).

### What remains manual / safety-gated

- Paper/live mode toggle.
- Emergency stop.
- Global risk settings (max position %, SL/TP %, daily trade limit).
- Kraken credential storage and live-mode enable.

### Stop-loss / take-profit

- Existing SL/TP logic in `trading_service.py` continues to apply per position.
- When SL/TP fires, the position closes and frees the slot; re-entry requires a new signal.

---

## 6. Frontend Updates

### Settings page

- Remove the trading-pair dropdown (the bot now selects pairs).
- Add a read-only "Autonomous Watchlist" section showing the current top 5.
- Add a numeric input for "Max open positions" (default 5, clamped 1–10).
- Keep all other risk settings (SL/TP, daily trade limit, max position %).

### Dashboard

- Replace single-pair chart/price with a watchlist table:
  - symbol, current price, 24h change, signal, position size, PnL.
- Show "Open slots" = `max_open_positions - open_position_count`.
- Show "Next watchlist refresh" timer based on `watchlist_updated_at`.
- Keep portfolio value, mode badge, bot controls, and emergency stop.

### Types

Update `frontend/src/types/index.ts` to reflect:
- `RiskConfig.trading_pair` optional.
- `RiskConfig.max_open_positions: number`.
- `BotState.watchlist: string[]`.

---

## 7. API Changes

### Settings

- `GET /settings/risk` returns the new fields (`max_open_positions`, `allocation_mode`) with `trading_pair` optional/null.
- `POST /settings/risk` accepts the new fields; ignores or rejects `trading_pair`.

### Bot state

- `GET /bot/state` includes `watchlist`, `watchlist_updated_at`, `open_slots`.

### Market

- `GET /market/pairs` unchanged; it remains the curated universe for `AssetSelector`.

---

## 8. Files Changed

### Backend

- `backend/app/services/asset_selector.py` (new) — ranking/scoring service.
- `backend/app/services/bot_service.py` — loop over watchlist, cache by (user, symbol), call selector.
- `backend/app/services/risk_service.py` — add slot budget and multi-position limit checks.
- `backend/app/services/trading_service.py` — ensure SL/TP and execution handle per-symbol positions.
- `backend/app/models/portfolio.py` — add `max_open_positions`, `allocation_mode`, `watchlist`, adjust position constraints.
- `backend/app/schemas/settings.py` / `bot.py` — update request/response schemas.
- `backend/app/api/v1/settings.py` — remove `trading_pair` from writes, expose new fields.
- `backend/app/api/v1/bot.py` — include watchlist in state response.
- `backend/migrations/versions/` — Alembic migration for model changes.

### Frontend

- `frontend/src/pages/Settings.tsx` — remove pair dropdown, add max-open-positions + watchlist display.
- `frontend/src/pages/Dashboard.tsx` — multi-position/watchlist UI.
- `frontend/src/types/index.ts` — updated interfaces.
- `frontend/src/services/api.ts` — updated bot state response handling.

---

## 9. Testing Plan

1. **Unit tests**
   - `AssetSelector` returns up to 5 symbols from a curated universe.
   - `AssetSelector` excludes symbols failing volatility filter.
   - `RiskManager.slot_budget` returns `equity / max_open_positions`.
   - `BotOrchestrator` does not open more than `max_open_positions` positions.

2. **Integration tests**
   - Update risk config with `max_open_positions = 5`; verify bot state returns 5 symbols.
   - Run bot iteration with a mocked exchange; verify trades occur across multiple symbols.
   - Verify closing one position frees a slot for the next ranked symbol.

3. **Frontend verification**
   - `npm run build` passes with updated types.
   - Dashboard renders watchlist and open slots.

4. **Migration verification**
   - Apply Alembic migration; existing single-pair users keep their position and expand on next cycle.

---

## 10. Open Questions / Out of Scope

- Dynamic pair universe (fetching all Kraken pairs) is out of scope; keep the curated list.
- Per-pair risk overrides (e.g., different SL for BTC vs SOL) are out of scope.
- Allocation modes other than equal-weight are out of scope; the column is reserved for future work.
- Rebalancing existing positions (selling winners to buy new signals) is out of scope; only free slots are used for new entries.
