# AI-Powered Algorithmic Trading Platform

A full-stack, safety-first algorithmic trading web application. **Paper trading is the default and only enabled mode out of the box.** Real-money trading requires multiple explicit safety steps.

## Quick Start

1. Copy `.env.example` to `.env` and fill in values.
2. Run with Docker Compose:
   ```bash
   docker compose up --build
   ```
3. Open `http://localhost:3000`, create an account, and start paper trading.

## Modes

- **PAPER** (default): trades against a virtual €500 portfolio using live market data.
- **LIVE_DISABLED**: live trading is globally disabled by `ENABLE_LIVE_TRADING=false`.
- **LIVE**: only possible when the env flag is `true`, credentials exist, the user opts in, confirms warnings, and risk limits are set.

## Safety

- Withdrawal functionality is never implemented or requested.
- API secrets live only in environment variables / backend secrets.
- Backend never returns secrets to the frontend.
- Emergency stop is always available.

## Structure

- `backend/` — FastAPI, SQLAlchemy, ML engine, paper/live exchange adapters.
- `frontend/` — React + TypeScript + Vite dashboard.
