# Trading Bot: Login, Crypto Selection & Kraken Connection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the login 401, add a curated crypto-pair selector, and add per-user encrypted Kraken credential storage with connection testing.

**Architecture:** Keep the existing OAuth2 form login for the current frontend and add a JSON login branch. Use the existing `RiskConfig.trading_pair` field but populate it from a backend-curated list. Extend the `users` table with encrypted Kraken key columns and introduce a small encryption service; expose new settings endpoints and update the live-trading safety flow to use per-user credentials first, env credentials as fallback.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, React/TypeScript/Vite, `cryptography` (Fernet).

**Spec:** `docs/superpowers/specs/2026-09-18-trading-bot-auth-crypto-kraken-design.md`

## Global Constraints
- Plaintext Kraken credentials must never be logged or returned by the API.
- `SECRET_KEY` must be ≥ 32 characters (existing validator).
- Withdrawal permission must be rejected before live mode can be enabled.
- Existing form-encoded login must keep working.
- All new endpoints under `/api/v1`.

---

## File map

### Backend
- `backend/app/schemas/auth.py` — add `UserLoginJSON` schema.
- `backend/app/api/v1/auth.py` — add JSON login branch via custom dependency.
- `backend/app/api/v1/market.py` — add `GET /pairs`.
- `backend/app/models/user.py` — add encrypted Kraken columns.
- `backend/app/services/exchange_service.py` — new encryption helpers.
- `backend/app/core/config.py` — add optional `KRAKEN_ENCRYPTION_KEY`.
- `backend/app/schemas/settings.py` — new exchange request/response schemas.
- `backend/app/api/v1/settings.py` — add exchange endpoints, update safety/enable-live.
- `backend/migrations/versions/` — Alembic migration for new columns.
- `backend/requirements.txt` — add `cryptography`.
- `backend/tests/test_auth.py` — new.
- `backend/tests/test_market.py` — new.
- `backend/tests/test_settings.py` — new.

### Frontend
- `frontend/src/services/api.ts` — add `marketApi.getPairs`, `settingsApi.getExchange`, `settingsApi.saveExchange`, `settingsApi.testExchange`.
- `frontend/src/pages/Settings.tsx` — trading-pair dropdown + Kraken connection card.
- `frontend/src/pages/Dashboard.tsx` — load risk config and use `trading_pair` instead of hard-coded `BTC/EUR`.

### Config
- `.env.example` — add optional `KRAKEN_ENCRYPTION_KEY`.

---

## Task 1: JSON login schema and endpoint

**Files:**
- Modify: `backend/app/schemas/auth.py`
- Modify: `backend/app/api/v1/auth.py`
- Create: `backend/tests/test_auth.py`

**Interfaces:**
- Consumes: `authenticate_user(db, email, password)` and `generate_token(user)` from `app.services.auth_service`.
- Produces: `POST /api/v1/auth/login` accepts both `application/x-www-form-urlencoded` (`username`, `password`) and `application/json` (`{"email": ..., "password": ...}`). Response unchanged: `{"access_token": ..., "token_type": "bearer"}`.

- [ ] **Step 1: Add JSON login schema**

Modify `backend/app/schemas/auth.py`:

```python
class UserLoginJSON(BaseModel):
    email: EmailStr
    password: str
```

- [ ] **Step 2: Implement dual-mode login dependency**

Modify `backend/app/api/v1/auth.py` to replace the single form-only endpoint with a custom dependency that detects content type:

```python
from fastapi import Request
from app.schemas.auth import UserLoginJSON

class LoginData:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password

async def get_login_data(request: Request) -> LoginData:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        body = await request.json()
        email = body.get("email")
        password = body.get("password")
    else:
        form = await request.form()
        email = form.get("username")
        password = form.get("password")
    if not email or not password:
        raise HTTPException(status_code=422, detail="Email and password are required")
    return LoginData(email=email, password=password)


@router.post("/login", response_model=Token)
def login(data: LoginData = Depends(get_login_data), db: Session = Depends(get_db)):
    user = authenticate_user(db, data.email, data.password)
    return {"access_token": generate_token(user), "token_type": "bearer"}
```

- [ ] **Step 3: Write login tests**

Create `backend/tests/test_auth.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import create_application
from app.db.base import Base
from app.db.session import get_db

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def client():
    Base.metadata.create_all(bind=engine)
    app = create_application()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)


def test_register_and_login_json(client):
    client.post("/api/v1/auth/register", json={"email": "test@example.com", "password": "secret"})
    res = client.post("/api/v1/auth/login", json={"email": "test@example.com", "password": "secret"})
    assert res.status_code == 200
    assert "access_token" in res.json()


def test_register_and_login_form(client):
    client.post("/api/v1/auth/register", json={"email": "test@example.com", "password": "secret"})
    res = client.post(
        "/api/v1/auth/login",
        data={"username": "test@example.com", "password": "secret"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert res.status_code == 200
    assert "access_token" in res.json()


def test_login_wrong_password_json(client):
    client.post("/api/v1/auth/register", json={"email": "test@example.com", "password": "secret"})
    res = client.post("/api/v1/auth/login", json={"email": "test@example.com", "password": "wrong"})
    assert res.status_code == 401
```

- [ ] **Step 4: Run auth tests**

Run: `cd backend && pytest tests/test_auth.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/auth.py backend/app/api/v1/auth.py backend/tests/test_auth.py
git commit -m "feat(auth): accept JSON or form-encoded login"
```

---

## Task 2: Market pairs endpoint

**Files:**
- Modify: `backend/app/api/v1/market.py`
- Create: `backend/tests/test_market.py`

**Interfaces:**
- Produces: `GET /api/v1/market/pairs` returns `list[str]` of curated Kraken pairs.

- [ ] **Step 1: Add pairs endpoint**

Modify `backend/app/api/v1/market.py`:

```python
CURATED_PAIRS = ["BTC/EUR", "ETH/EUR", "SOL/EUR", "XRP/EUR", "ADA/EUR"]


@router.get("/pairs")
def get_pairs():
    return CURATED_PAIRS
```

- [ ] **Step 2: Write test**

Create `backend/tests/test_market.py`:

```python
from fastapi.testclient import TestClient
from app.main import create_application


def test_get_pairs():
    app = create_application()
    with TestClient(app) as client:
        res = client.get("/api/v1/market/pairs")
    assert res.status_code == 200
    assert "BTC/EUR" in res.json()
```

- [ ] **Step 3: Run test**

Run: `cd backend && pytest tests/test_market.py -v`
Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/v1/market.py backend/tests/test_market.py
git commit -m "feat(market): add curated trading pairs endpoint"
```

---

## Task 3: User model migration for encrypted Kraken credentials

**Files:**
- Modify: `backend/app/models/user.py`
- Create: `backend/migrations/versions/0002_add_kraken_credentials.py`

**Interfaces:**
- Produces: `User.kraken_api_key_encrypted` and `User.kraken_api_secret_encrypted` nullable strings.

- [ ] **Step 1: Add columns to model**

Modify `backend/app/models/user.py`:

```python
kraken_api_key_encrypted = Column(String, nullable=True)
kraken_api_secret_encrypted = Column(String, nullable=True)
```

- [ ] **Step 2: Create Alembic migration**

Run:

```bash
cd backend
alembic revision --autogenerate -m "add kraken credentials to users"
```

Verify the generated migration adds only the two columns. If not using Alembic in dev, the `create_all` in `main.py` will create them; still commit the migration for production.

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/user.py backend/migrations/versions/
git commit -m "feat(db): add encrypted kraken credential columns"
```

---

## Task 4: Exchange credential encryption service

**Files:**
- Create: `backend/app/services/exchange_service.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/requirements.txt`
- Modify: `.env.example`

**Interfaces:**
- Produces: `encrypt_value(value: str) -> str`, `decrypt_value(token: str) -> str`, `mask_key(key: str) -> str`.

- [ ] **Step 1: Add cryptography dependency**

Modify `backend/requirements.txt`, add:

```text
cryptography==42.0.8
```

- [ ] **Step 2: Add optional encryption key config**

Modify `backend/app/core/config.py`, add after `KRAKEN_API_SECRET`:

```python
KRAKEN_ENCRYPTION_KEY: str = ""
```

Modify `.env.example`, add after `KRAKEN_API_SECRET`:

```text
# Optional: dedicated key for encrypting per-user Kraken credentials. Falls back to SECRET_KEY if empty.
KRAKEN_ENCRYPTION_KEY=
```

- [ ] **Step 3: Implement encryption helpers**

Create `backend/app/services/exchange_service.py`:

```python
import base64
from hashlib import sha256
from cryptography.fernet import Fernet
from app.core.config import settings


def _get_fernet() -> Fernet:
    key = settings.KRAKEN_ENCRYPTION_KEY or settings.SECRET_KEY
    if not key:
        raise ValueError("KRAKEN_ENCRYPTION_KEY or SECRET_KEY must be configured")
    hashed = sha256(key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(hashed))


def encrypt_value(value: str) -> str:
    return _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(token: str) -> str:
    return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")


def mask_key(key: str) -> str:
    if len(key) <= 4:
        return "****"
    return "****" + key[-4:]
```

- [ ] **Step 4: Add unit test**

Create a small test file `backend/tests/test_exchange_service.py`:

```python
from app.services.exchange_service import encrypt_value, decrypt_value, mask_key


def test_encrypt_decrypt_roundtrip():
    plain = "my-secret-key"
    encrypted = encrypt_value(plain)
    assert encrypted != plain
    assert decrypt_value(encrypted) == plain


def test_mask_key():
    assert mask_key("ABCDEFGHIJ") == "****HIJ"
    assert mask_key("AB") == "****"
```

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/test_exchange_service.py -v`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/exchange_service.py backend/app/core/config.py backend/requirements.txt .env.example backend/tests/test_exchange_service.py
git commit -m "feat(settings): add fernet encryption for exchange credentials"
```

---

## Task 5: Settings exchange endpoints

**Files:**
- Create: `backend/app/schemas/settings.py`
- Modify: `backend/app/api/v1/settings.py`
- Create: `backend/tests/test_settings.py`

**Interfaces:**
- Consumes: `encrypt_value`, `decrypt_value`, `mask_key` from `app.services.exchange_service`; `KrakenExchange` from `app.exchanges.kraken`.
- Produces:
  - `POST /settings/exchange` — saves encrypted credentials.
  - `GET /settings/exchange` — returns `{"connected": bool, "masked_key": str}`.
  - `POST /settings/exchange/test` — tests connection.
  - Updated `GET /settings/safety` — includes `user_credentials_present`.
  - Updated `POST /settings/enable-live` — uses user credentials first, env fallback.

- [ ] **Step 1: Add schemas**

Create `backend/app/schemas/settings.py`:

```python
from pydantic import BaseModel


class ExchangeCredentialsIn(BaseModel):
    api_key: str
    api_secret: str


class ExchangeStatusOut(BaseModel):
    connected: bool
    masked_key: str
```

- [ ] **Step 2: Implement exchange endpoints and update live flow**

Modify `backend/app/api/v1/settings.py`. Replace the existing `safety_status` and `enable_live` functions and add the new endpoints:

```python
from app.services.exchange_service import encrypt_value, decrypt_value, mask_key
from app.schemas.settings import ExchangeCredentialsIn, ExchangeStatusOut


def _get_user_kraken_credentials(user: User):
    if user.kraken_api_key_encrypted and user.kraken_api_secret_encrypted:
        return (
            decrypt_value(user.kraken_api_key_encrypted),
            decrypt_value(user.kraken_api_secret_encrypted),
        )
    return settings.KRAKEN_API_KEY, settings.KRAKEN_API_SECRET


@router.get("/exchange", response_model=ExchangeStatusOut)
def get_exchange_status(current_user: User = Depends(get_current_user)):
    key, _ = _get_user_kraken_credentials(current_user)
    return ExchangeStatusOut(connected=bool(key), masked_key=mask_key(key) if key else "****")


@router.post("/exchange")
def save_exchange_credentials(
    payload: ExchangeCredentialsIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.kraken_api_key_encrypted = encrypt_value(payload.api_key)
    current_user.kraken_api_secret_encrypted = encrypt_value(payload.api_secret)
    db.commit()
    return {"detail": "Credentials saved"}


@router.post("/exchange/test")
async def test_exchange_credentials(current_user: User = Depends(get_current_user)):
    key, secret = _get_user_kraken_credentials(current_user)
    if not key or not secret:
        raise HTTPException(status_code=400, detail="No Kraken credentials configured")
    exchange = KrakenExchange(api_key=key, api_secret=secret)
    try:
        await exchange.get_balances()
        return {"detail": "Connection successful"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kraken connection failed: {e}")
    finally:
        await exchange.client.close()


@router.get("/safety")
def safety_status(current_user: User = Depends(get_current_user)):
    user_key, user_secret = _get_user_kraken_credentials(current_user)
    has_creds = bool(user_key and user_secret)
    return {
        "enable_live_trading_env": settings.ENABLE_LIVE_TRADING,
        "api_credentials_present": has_creds,
        "live_possible": settings.ENABLE_LIVE_TRADING and has_creds,
        "message": "Live trading is disabled by default. It requires explicit env flag, credentials, UI opt-in, and confirmation.",
    }


@router.post("/enable-live")
async def enable_live(
    confirm: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not settings.ENABLE_LIVE_TRADING:
        raise HTTPException(status_code=403, detail="Live trading is disabled in server configuration")

    key, secret = _get_user_kraken_credentials(current_user)
    if not (key and secret):
        raise HTTPException(status_code=400, detail="Exchange API credentials not configured")

    if not confirm:
        raise HTTPException(
            status_code=400,
            detail=(
                "You must confirm that you understand the risks. "
                "Live trading can lose money. Withdrawal functionality is never used. "
                "Pass confirm=true to proceed."
            ),
        )

    portfolio = db.query(Portfolio).filter(Portfolio.user_id == current_user.id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    exchange = KrakenExchange(api_key=key, api_secret=secret)
    try:
        has_withdrawal = await exchange.check_withdrawal_permission()
        if has_withdrawal:
            raise HTTPException(status_code=400, detail="API key has withdrawal permission. Use a key without withdrawal rights.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Unable to verify API key permissions. Live mode blocked.")
    finally:
        await exchange.client.close()

    portfolio.mode = "LIVE"
    db.commit()
    return {"detail": "Live trading enabled. Emergency stop is available."}
```

- [ ] **Step 3: Write settings tests**

Create `backend/tests/test_settings.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import create_application
from app.db.base import Base
from app.db.session import get_db
from app.services.auth_service import create_user, generate_token

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def client():
    Base.metadata.create_all(bind=engine)
    app = create_application()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)


def _auth_header(client, email, password):
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_save_and_get_exchange_status(client):
    headers = _auth_header(client, "u@example.com", "pass")
    res = client.post("/api/v1/settings/exchange", json={"api_key": "key12345", "api_secret": "secret12345"}, headers=headers)
    assert res.status_code == 200
    res = client.get("/api/v1/settings/exchange", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["connected"] is True
    assert body["masked_key"].endswith("2345")
```

- [ ] **Step 4: Run settings tests**

Run: `cd backend && pytest tests/test_settings.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/settings.py backend/app/api/v1/settings.py backend/tests/test_settings.py
git commit -m "feat(settings): per-user encrypted kraken credentials and connection test"
```

---

## Task 6: Frontend API updates

**Files:**
- Modify: `frontend/src/services/api.ts`

**Interfaces:**
- Produces: `marketApi.getPairs()`, `settingsApi.getExchange()`, `settingsApi.saveExchange(key, secret)`, `settingsApi.testExchange()`.

- [ ] **Step 1: Add new API methods**

Modify `frontend/src/services/api.ts`. Add to `marketApi`:

```typescript
export const marketApi = {
  getPrice: (symbol: string) => api.get(`/market/price/${symbol}`),
  getOHLCV: (symbol: string, timeframe = '1h', limit = 100) =>
    api.get(`/market/ohlcv/${symbol}?timeframe=${timeframe}&limit=${limit}`),
  backtest: (symbol: string, initialCash = 500, feePct = 0.0026) =>
    api.post('/market/backtest', { symbol, initial_cash: initialCash, fee_pct: feePct }),
  getPairs: () => api.get<string[]>('/market/pairs'),
};
```

Add to `settingsApi`:

```typescript
export const settingsApi = {
  getRisk: () => api.get('/settings/risk'),
  updateRisk: (data: Partial<{
    max_position_pct: number;
    stop_loss_pct: number;
    take_profit_pct: number;
    fee_pct: number;
    max_daily_trades: number;
    trading_pair: string;
    prediction_horizon: number;
  }>) => api.put('/settings/risk', data),
  resetPaper: () => api.post('/settings/reset-paper?confirm=true'),
  getSafety: () => api.get('/settings/safety'),
  enableLive: () => api.post('/settings/enable-live?confirm=true'),
  disableLive: () => api.post('/settings/disable-live'),
  getExchange: () => api.get<{ connected: boolean; masked_key: string }>('/settings/exchange'),
  saveExchange: (api_key: string, api_secret: string) =>
    api.post('/settings/exchange', { api_key, api_secret }),
  testExchange: () => api.post('/settings/exchange/test'),
};
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/services/api.ts
git commit -m "feat(frontend): add exchange and pairs API methods"
```

---

## Task 7: Frontend Settings page

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`

**Interfaces:**
- Consumes: `marketApi.getPairs`, `settingsApi.getExchange`, `settingsApi.saveExchange`, `settingsApi.testExchange`.
- Produces: trading-pair `<select>` and Kraken connection card.

- [ ] **Step 1: Load pairs and exchange status**

At the top of `Settings.tsx`, add state:

```typescript
const [pairs, setPairs] = useState<string[]>([]);
const [exchange, setExchange] = useState<{ connected: boolean; masked_key: string } | null>(null);
const [krakenKey, setKrakenKey] = useState('');
const [krakenSecret, setKrakenSecret] = useState('');
```

Update `load()`:

```typescript
const load = async () => {
  try {
    const [riskRes, safetyRes, pairsRes, exchangeRes] = await Promise.all([
      settingsApi.getRisk(),
      settingsApi.getSafety(),
      marketApi.getPairs(),
      settingsApi.getExchange(),
    ]);
    setRisk(riskRes.data);
    setSafety(safetyRes.data);
    setPairs(pairsRes.data);
    setExchange(exchangeRes.data);
    setError('');
  } catch (err: any) {
    setError(err.response?.data?.detail || 'Failed to load settings');
  }
};
```

- [ ] **Step 2: Replace trading pair input with select**

In the Risk Parameters form, replace:

```tsx
<input value={risk.trading_pair} onChange={(e) => setRisk({ ...risk, trading_pair: e.target.value })} />
```

with:

```tsx
<select value={risk.trading_pair} onChange={(e) => setRisk({ ...risk, trading_pair: e.target.value })}>
  {pairs.map((pair) => (
    <option key={pair} value={pair}>{pair}</option>
  ))}
</select>
```

- [ ] **Step 3: Add Kraken connection card handlers**

Add functions before the return:

```typescript
const saveKraken = async (e: React.FormEvent) => {
  e.preventDefault();
  try {
    await settingsApi.saveExchange(krakenKey, krakenSecret);
    setKrakenKey('');
    setKrakenSecret('');
    setMessage('Kraken credentials saved');
    load();
  } catch (err: any) {
    setError(err.response?.data?.detail || 'Failed to save credentials');
  }
};

const testKraken = async () => {
  try {
    const res = await settingsApi.testExchange();
    setMessage(res.data.detail);
  } catch (err: any) {
    setError(err.response?.data?.detail || 'Connection test failed');
  }
};
```

- [ ] **Step 4: Add Kraken connection card UI**

Add a new card after the Risk Parameters card:

```tsx
<div className="card">
  <h3>Kraken Connection</h3>
  <p className="text-muted">Status: {exchange?.connected ? `Connected (${exchange.masked_key})` : 'Not connected'}</p>
  <form onSubmit={saveKraken} style={{ display: 'grid', gap: '1rem', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
    <label>
      API Key
      <input type="password" value={krakenKey} onChange={(e) => setKrakenKey(e.target.value)} placeholder="Enter API key" />
    </label>
    <label>
      API Secret
      <input type="password" value={krakenSecret} onChange={(e) => setKrakenSecret(e.target.value)} placeholder="Enter API secret" />
    </label>
    <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '1rem' }}>
      <button className="btn-primary" type="submit">Save Credentials</button>
      <button className="btn-primary" type="button" onClick={testKraken} disabled={!exchange?.connected}>Test Connection</button>
    </div>
  </form>
</div>
```

- [ ] **Step 5: Update live trading button condition**

The existing enable-live button uses `safety?.live_possible`. No change needed because the backend now computes `live_possible` from the user's credentials.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Settings.tsx
git commit -m "feat(frontend): trading pair dropdown and kraken connection card"
```

---

## Task 8: Frontend Dashboard active pair

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`

**Interfaces:**
- Consumes: `settingsApi.getRisk`.
- Produces: Dashboard uses `risk.trading_pair` instead of hard-coded `BTC/EUR`.

- [ ] **Step 1: Import settingsApi and risk state**

At the top, add `RiskConfig` to the type import if needed and import `settingsApi`:

```typescript
import { RiskConfig, Portfolio, Position, Trade, Signal, BotState, OHLCV } from '../types';
import { portfolioApi, marketApi, botApi, settingsApi } from '../services/api';
```

Add state:

```typescript
const [risk, setRisk] = useState<RiskConfig | null>(null);
const symbol = risk?.trading_pair || 'BTC/EUR';
```

- [ ] **Step 2: Load risk config on mount**

Add a `loadRisk` function and call it in `useEffect`:

```typescript
const loadRisk = async () => {
  try {
    const res = await settingsApi.getRisk();
    setRisk(res.data);
  } catch (err: any) {
    setError(err.response?.data?.detail || 'Failed to load risk config');
  }
};

useEffect(() => {
  loadRisk();
}, []);
```

The existing `fetchAll` `useEffect` already depends on `symbol`, so it will re-run when `symbol` is known.

- [ ] **Step 3: Display active pair**

In the Mode card, add:

```tsx
<div className="text-muted">Pair: {symbol}</div>
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx
git commit -m "feat(frontend): use user's trading pair on dashboard"
```

---

## Task 9: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Run backend test suite**

Run:

```bash
cd backend
pytest -v
```

Expected: all tests pass.

- [ ] **Step 2: Run frontend type check and build**

Run:

```bash
cd frontend
npm run build
```

Expected: build succeeds with no TypeScript errors.

- [ ] **Step 3: Manual smoke test**

With docker-compose running:

1. Register a user at `http://localhost:3000/register`.
2. Log in with JSON via curl and confirm 200:
   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email":"test@test.at","password":"test"}'
   ```
3. Log in via the frontend and confirm it still works.
4. In Settings, select a new trading pair and save.
5. Refresh Dashboard and confirm the pair is reflected in price/chart.
6. In Settings, enter a Kraken sandbox key and secret, save, then click Test Connection.
7. Confirm safety status shows credentials present and enable-live button reflects state.

- [ ] **Step 4: Final commit (if any fixes)**

```bash
git add -A
git commit -m "fix: login, crypto selection, and kraken connection flow"
```

---

## Self-review

- **Spec coverage:**
  - Login JSON/form dual mode → Task 1.
  - Crypto pair selection → Tasks 2, 7, 8.
  - Encrypted per-user Kraken credentials → Tasks 3, 4, 5.
  - Kraken test/status endpoints → Task 5.
  - Frontend UI updates → Tasks 6, 7, 8.
  - Security (encryption, no plaintext return, withdrawal check) → Tasks 4, 5.
- **Placeholder scan:** all steps contain concrete code or commands; no TBD/TODO.
- **Type consistency:** `trading_pair` is `str` throughout; exchange status schema is `ExchangeStatusOut`; API methods match.

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2026-09-18-trading-bot-auth-crypto-kraken-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints.

Which approach?
