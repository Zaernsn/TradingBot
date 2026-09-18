# Trading Bot: Login, Crypto Selection & Kraken Connection

## Overview
Fix the login 401, add a user-facing crypto-selection flow, and add a per-user encrypted Kraken connection flow.

## Current state
- FastAPI backend with OAuth2 form-encoded login at `POST /api/v1/auth/login`.
- React/Vite frontend that already sends form-encoded login correctly.
- `RiskConfig.trading_pair` is a free-text field in Settings.
- Kraken credentials are global env vars (`KRAKEN_API_KEY`, `KRAKEN_API_SECRET`).
- Live trading is gated by env flag, global credentials, and UI confirmation.

## Goals
1. Make login work for both form-encoded and JSON clients.
2. Let users pick a trading pair from a curated list.
3. Let each user save and test their own Kraken API credentials securely.

---

## 1. Login fix

### Root cause
`POST /api/v1/auth/login` uses `OAuth2PasswordRequestForm`, which requires:
- `Content-Type: application/x-www-form-urlencoded`
- fields `username` (carries email) and `password`

The failing curl sent `Content-Type: application/json` with a URL-encoded body, so FastAPI could not bind the form fields. The lookup ran with an empty email and returned 401.

### Change
Keep the existing OAuth2 form endpoint for the current frontend, and add a JSON branch that accepts `{"email": "...", "password": "..."}`. Both branches call the same `authenticate_user` service.

### API
```http
POST /api/v1/auth/login
Content-Type: application/json

{"email": "test@test.at", "password": "test"}
```

Response (same as today):
```json
{"access_token": "...", "token_type": "bearer"}
```

---

## 2. Crypto selection flow

### Change
Replace the free-text `trading_pair` input in Settings with a dropdown populated from the backend.

### Backend
- New endpoint: `GET /api/v1/market/pairs`
- Returns a curated list of Kraken-style pairs:
  ```json
  ["BTC/EUR", "ETH/EUR", "SOL/EUR", "XRP/EUR", "ADA/EUR"]
  ```

### Frontend
- `Settings.tsx` fetches the list on load and renders a `<select>` for `trading_pair`.
- `Dashboard.tsx` displays the active trading pair near the portfolio summary.
- The existing `settingsApi.updateRisk` continues to persist the selection.

---

## 3. Kraken connection flow

### Change
Store per-user encrypted Kraken credentials and use them for live-trading checks.

### Database
Add to the `users` table:
- `kraken_api_key_encrypted` (String, nullable)
- `kraken_api_secret_encrypted` (String, nullable)

Alternative: a separate `user_exchange_credentials` table. For this scope, columns on `users` are simpler and keep the one-to-one user relationship.

### Encryption
- Add `cryptography` to `backend/requirements.txt`.
- Use `Fernet` with a key derived from `SECRET_KEY` (or a new `KRAKEN_ENCRYPTION_KEY` env var if present).
- Plaintext keys exist only in memory during the request that uses them.

### Backend endpoints

#### Save credentials
```http
POST /api/v1/settings/exchange
{
  "api_key": "...",
  "api_secret": "..."
}
```
- Encrypts and stores the keys.
- Returns `{"detail": "Credentials saved"}`.

#### Get connection status
```http
GET /api/v1/settings/exchange
```
- Returns masked status only, never the full keys:
  ```json
  {"connected": true, "masked_key": "****ABCD"}
  ```

#### Test connection
```http
POST /api/v1/settings/exchange/test
```
- Decrypts credentials, instantiates `KrakenExchange`, and calls a read-only API such as `fetch_balance()`.
- Returns success or a clear error message.

#### Update live-trading enable
Modify `POST /settings/enable-live`:
- Use the current user's stored credentials first.
- Fall back to env credentials for existing single-key deployments.
- Keep the withdrawal-permission check.

#### Update safety status
Modify `GET /settings/safety`:
- Report whether the current user has stored credentials.
- Keep the env-level flags.

### Frontend
Add a new "Kraken Connection" card in `Settings.tsx`:
- Inputs for API key and API secret.
- "Save & Test" button.
- Connection status display.
- Enable-live button is disabled unless `live_possible` is true for this user.

### Security
- Credentials are encrypted at rest.
- Withdrawal permission is rejected before live mode can be enabled.
- Plaintext keys are never logged or returned by the API.

---

## Files changed

### Backend
- `backend/app/api/v1/auth.py` — add JSON login branch.
- `backend/app/api/v1/settings.py` — add exchange endpoints and update live/safety endpoints.
- `backend/app/api/v1/market.py` — add `GET /market/pairs`.
- `backend/app/models/user.py` — add encrypted credential columns.
- `backend/app/schemas/auth.py` or new `backend/app/schemas/settings.py` — request/response schemas.
- `backend/app/services/exchange_service.py` (new) — encryption/decryption helpers.
- `backend/app/exchanges/kraken.py` — no breaking changes; used with per-user keys.
- `backend/migrations/versions/` — Alembic migration for new columns.
- `backend/requirements.txt` — add `cryptography`.
- `.env.example` — add optional `KRAKEN_ENCRYPTION_KEY`.

### Frontend
- `frontend/src/services/api.ts` — add exchange endpoints and pair list endpoint.
- `frontend/src/pages/Settings.tsx` — add Kraken connection card and trading-pair dropdown.
- `frontend/src/pages/Dashboard.tsx` — display active trading pair.

---

## Testing plan
1. Register a user via frontend or curl.
2. Login with both form-encoded and JSON payloads.
3. Select a trading pair in Settings and verify it persists and displays on Dashboard.
4. Save Kraken test credentials (sandbox/paper key) and run "Test Connection".
5. Verify live-trading enable uses the stored credentials and rejects withdrawal keys.

## Open questions / out of scope
- Fetching the full Kraken market list dynamically is out of scope; use a curated list.
- OAuth or other exchange connections are out of scope.
- Key rotation UI is out of scope; users can overwrite by saving again.
