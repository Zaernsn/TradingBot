# Autonomous Multi-Crypto Trading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the bot fully autonomous by removing the user-selected single trading pair and enabling it to select, allocate, and trade up to 5 curated crypto pairs simultaneously.

**Architecture:** Keep the existing one-job-per-user scheduler but change each iteration to loop over an autonomous watchlist. A new `AssetSelector` ranks curated pairs once per day; `RiskManager` provides per-slot budgets; `BotOrchestrator` manages one position per symbol and enforces the global slot limit.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, APScheduler, scikit-learn, React + TypeScript + Vite.

**Spec:** `docs/superpowers/specs/2026-09-18-trading-bot-autonomous-multi-crypto-design.md`

## Global Constraints

- Paper trading remains the default; live trading stays opt-in behind env flag + credentials + confirmation.
- Only curated pairs (`backend/app/api/v1/market.py:14`) are eligible for selection.
- `max_open_positions` defaults to 5 and is clamped between 1 and 10.
- Capital allocation is equal-weight only (`allocation_mode = "equal"`).
- At most one open position per `(user_id, symbol)`.
- `RiskConfig.trading_pair` is deprecated but kept in the database for migration compatibility.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/services/asset_selector.py` (new) | Ranks curated pairs into a watchlist of up to `max_open_positions` symbols. |
| `backend/app/models/portfolio.py` (modify) | Adds `max_open_positions`, `allocation_mode`, `watchlist`, `watchlist_updated_at`, `target_positions`. |
| `backend/app/schemas/portfolio.py` (modify) | Adds new fields to `RiskConfigOut`, `RiskConfigUpdate`, `BotStateOut`. |
| `backend/app/services/risk_service.py` (modify) | Adds `slot_budget`, removes single-pair assumption. |
| `backend/app/services/bot_service.py` (modify) | Loops over watchlist, caches models by `(user_id, symbol)`, enforces slot limit. |
| `backend/app/api/v1/settings.py` (modify) | Drops `trading_pair` from writes, exposes `max_open_positions`. |
| `backend/app/api/v1/bot.py` (modify) | Returns watchlist + open slots in state. |
| `backend/migrations/versions/...` (new) | Alembic migration for schema changes. |
| `frontend/src/types/index.ts` (modify) | Adds `max_open_positions`, `watchlist`, `open_slots`; makes `trading_pair` optional. |
| `frontend/src/pages/Settings.tsx` (modify) | Removes pair dropdown, adds max-open-positions input + watchlist display. |
| `frontend/src/pages/Dashboard.tsx` (modify) | Shows watchlist table, open slots, removes single-pair chart dependency. |
| `backend/tests/test_asset_selector.py` (new) | Unit tests for ranking/selection. |
| `backend/tests/test_risk_service.py` (modify) | Tests for `slot_budget` and slot limit helpers. |
| `backend/tests/test_bot_orchestrator.py` (new) | Tests for multi-position iteration. |

---

## Task 1: Data model + migration for autonomous watchlist

**Files:**
- Modify: `backend/app/models/portfolio.py:23-99`
- Create: `backend/migrations/versions/YYYY-MM-DD_autonomous_watchlist.py`
- Test: `backend/tests/test_models.py` (new or extend existing)

**Interfaces:**
- Consumes: existing `Portfolio`, `Position`, `BotState`, `RiskConfig`.
- Produces: `RiskConfig.max_open_positions: int`, `RiskConfig.allocation_mode: str`, `BotState.watchlist: list[str]`, `BotState.watchlist_updated_at: datetime | None`, `Portfolio.target_positions: int`.

- [ ] **Step 1: Write the migration first**

Create `backend/migrations/versions/2026_09_18_autonomous_watchlist.py`:

```python
"""autonomous watchlist and multi-position"""
from alembic import op
import sqlalchemy as sa

revision = "<generate>"
down_revision = "eccc293d6dc0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("risk_configs", sa.Column("max_open_positions", sa.Integer, nullable=False, server_default="5"))
    op.add_column("risk_configs", sa.Column("allocation_mode", sa.String, nullable=False, server_default="equal"))
    op.alter_column("risk_configs", "trading_pair", nullable=True)

    op.add_column("bot_states", sa.Column("watchlist", sa.JSON, nullable=True))
    op.add_column("bot_states", sa.Column("watchlist_updated_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("portfolios", sa.Column("target_positions", sa.Integer, nullable=False, server_default="5"))

    # Optional performance index for position lookups by portfolio + symbol.
    op.create_index("ix_positions_portfolio_symbol", "positions", ["portfolio_id", "symbol"], unique=False)


def downgrade():
    op.drop_index("ix_positions_portfolio_symbol", table_name="positions")
    op.drop_column("portfolios", "target_positions")
    op.drop_column("bot_states", "watchlist_updated_at")
    op.drop_column("bot_states", "watchlist")
    op.alter_column("risk_configs", "trading_pair", nullable=False)
    op.drop_column("risk_configs", "allocation_mode")
    op.drop_column("risk_configs", "max_open_positions")
```

- [ ] **Step 2: Update the SQLAlchemy models**

In `backend/app/models/portfolio.py`:

```python
class Portfolio(Base):
    ...
    target_positions = Column(Integer, default=5, nullable=False)
    ...


class BotState(Base):
    ...
    watchlist = Column(JSON, nullable=True)
    watchlist_updated_at = Column(DateTime(timezone=True), nullable=True)
    ...


class RiskConfig(Base):
    ...
    trading_pair = Column(String, nullable=True)
    max_open_positions = Column(Integer, default=5, nullable=False)
    allocation_mode = Column(String, default="equal", nullable=False)
    ...
```

- [ ] **Step 3: Write a model test**

Create or add to `backend/tests/test_models.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.models.portfolio import RiskConfig, BotState, Position, Portfolio


def test_risk_config_defaults():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    config = RiskConfig(user_id=1)
    db.add(config)
    db.commit()
    db.refresh(config)

    assert config.max_open_positions == 5
    assert config.allocation_mode == "equal"
    assert config.trading_pair is None
    db.close()
```

- [ ] **Step 4: Run migration and model test**

Run:
```bash
cd backend
alembic upgrade head
pytest tests/test_models.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/portfolio.py backend/migrations/versions/2026_09_18_autonomous_watchlist.py backend/tests/test_models.py
git commit -m "feat(models): add autonomous watchlist and multi-position columns"
```

---

## Task 2: Asset selector service

**Files:**
- Create: `backend/app/services/asset_selector.py`
- Test: `backend/tests/test_asset_selector.py`

**Interfaces:**
- Consumes: `universe: list[str]`, optional `max_open_positions: int = 5`.
- Produces: `AssetSelector.select(universe, ohlcv_by_symbol) -> list[str]`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_asset_selector.py`:

```python
import pytest
from datetime import datetime, timezone
from app.services.asset_selector import AssetSelector


def _candles(trend: float, volume: float = 1000.0, count: int = 30):
    base = 100.0
    return [
        {
            "timestamp": datetime.now(timezone.utc),
            "open": base + i * trend,
            "high": base + i * trend + 1,
            "low": base + i * trend - 1,
            "close": base + (i + 1) * trend,
            "volume": volume,
        }
        for i in range(count)
    ]


def test_select_returns_up_to_five_symbols():
    selector = AssetSelector(min_volatility=0.0, max_volatility=10.0)
    data = {
        "BTC/EUR": _candles(1.0, volume=5000),
        "ETH/EUR": _candles(0.8, volume=4000),
        "SOL/EUR": _candles(0.6, volume=3000),
        "XRP/EUR": _candles(0.4, volume=2000),
        "ADA/EUR": _candles(0.2, volume=1000),
    }
    result = selector.select(data)
    assert len(result) <= 5
    assert result[0] == "BTC/EUR"


def test_select_excludes_low_and_high_volatility():
    selector = AssetSelector(min_volatility=0.05, max_volatility=2.0)
    data = {
        "BTC/EUR": _candles(1.0),   # passes
        "STABLE/EUR": _candles(0.001),  # too low
        "WILD/EUR": _candles(50.0),     # too high
    }
    result = selector.select(data)
    assert result == ["BTC/EUR"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd backend
pytest tests/test_asset_selector.py -v
```

Expected: FAIL with `ModuleNotFoundError` or `AssetSelector` not defined.

- [ ] **Step 3: Implement `AssetSelector`**

Create `backend/app/services/asset_selector.py`:

```python
from statistics import stdev, mean
from typing import Optional


class AssetSelector:
    def __init__(
        self,
        min_volatility: float = 0.05,
        max_volatility: float = 2.0,
        lookback: int = 30,
    ):
        self.min_volatility = min_volatility
        self.max_volatility = max_volatility
        self.lookback = lookback

    def select(
        self,
        ohlcv_by_symbol: dict[str, list[dict]],
        max_open_positions: int = 5,
    ) -> list[str]:
        scored = []
        for symbol, candles in ohlcv_by_symbol.items():
            if len(candles) < self.lookback:
                continue
            recent = candles[-self.lookback:]
            closes = [c["close"] for c in recent]
            volumes = [c["volume"] for c in recent]
            if not closes or closes[0] <= 0:
                continue

            returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
            if len(returns) < 2:
                continue
            volatility = stdev(returns) * (365 ** 0.5)
            if volatility < self.min_volatility or volatility > self.max_volatility:
                continue

            momentum = (closes[-1] - closes[0]) / closes[0]
            avg_volume = mean(volumes[-7:]) if len(volumes) >= 7 else mean(volumes)
            baseline_volume = mean(volumes) if volumes else 1.0
            volume_score = avg_volume / baseline_volume if baseline_volume > 0 else 1.0
            score = momentum * volume_score
            scored.append((symbol, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [s[0] for s in scored[:max_open_positions]]
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd backend
pytest tests/test_asset_selector.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/asset_selector.py backend/tests/test_asset_selector.py
git commit -m "feat(selector): add autonomous asset selector with momentum and volatility filters"
```

---

## Task 3: Risk manager slot budget

**Files:**
- Modify: `backend/app/services/risk_service.py:8-61`
- Test: `backend/tests/test_risk_service.py`

**Interfaces:**
- Consumes: `RiskManager`, `portfolio_value: float`.
- Produces: `RiskManager.slot_budget(portfolio_value) -> float`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_risk_service.py`:

```python
from app.services.risk_service import RiskManager


def test_slot_budget_equal_weight():
    risk = RiskManager(
        max_position_pct=0.25,
        stop_loss_pct=0.03,
        take_profit_pct=0.06,
        fee_pct=0.0026,
        max_daily_trades=10,
        trading_pair="BTC/EUR",
        prediction_horizon=12,
        max_open_positions=5,
    )
    assert risk.slot_budget(500.0) == 100.0


def test_position_size_capped_by_slot_budget():
    risk = RiskManager(
        max_position_pct=0.50,
        stop_loss_pct=0.03,
        take_profit_pct=0.06,
        fee_pct=0.0026,
        max_daily_trades=10,
        trading_pair="BTC/EUR",
        prediction_horizon=12,
        max_open_positions=5,
    )
    # slot budget is 100, max_position_pct cap is 250 -> slot wins
    assert risk.position_size(500.0, 50000.0) == 100.0 / 50000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd backend
pytest tests/test_risk_service.py -v
```

Expected: FAIL — `RiskManager` does not accept `max_open_positions`.

- [ ] **Step 3: Update `RiskManager`**

Modify `backend/app/services/risk_service.py`:

```python
@dataclass
class RiskManager:
    max_position_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    fee_pct: float
    max_daily_trades: int
    trading_pair: str
    prediction_horizon: int
    max_open_positions: int = 5

    def position_size(self, portfolio_value: float, price: float) -> float:
        allocation = min(
            portfolio_value * self.max_position_pct,
            self.slot_budget(portfolio_value),
        )
        return allocation / price if price > 0 else 0.0

    def slot_budget(self, portfolio_value: float) -> float:
        if self.max_open_positions <= 0:
            return 0.0
        return portfolio_value / self.max_open_positions

    def can_trade_today(self, db, portfolio_id: int) -> bool:
        ...  # keep existing implementation
```

Update `risk_manager_from_config` to pass `max_open_positions=config.max_open_positions`.

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd backend
pytest tests/test_risk_service.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/risk_service.py backend/tests/test_risk_service.py
git commit -m "feat(risk): add per-slot budget for equal-weight multi-asset allocation"
```

---

## Task 4: Update schemas and settings API

**Files:**
- Modify: `backend/app/schemas/portfolio.py:77-99`
- Modify: `backend/app/api/v1/settings.py:31-43`

**Interfaces:**
- Consumes: `RiskConfig` model.
- Produces: `RiskConfigOut` includes `max_open_positions`, `allocation_mode`, `trading_pair: Optional[str]`; `RiskConfigUpdate` drops `trading_pair`.

- [ ] **Step 1: Update schemas**

In `backend/app/schemas/portfolio.py`:

```python
from typing import Optional


class RiskConfigOut(BaseModel):
    ...
    trading_pair: Optional[str]
    max_open_positions: int
    allocation_mode: str
    ...


class RiskConfigUpdate(BaseModel):
    max_position_pct: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    fee_pct: Optional[float] = None
    max_daily_trades: Optional[int] = None
    prediction_horizon: Optional[int] = None
    max_open_positions: Optional[int] = None
```

- [ ] **Step 2: Clamp `max_open_positions` in the API**

Modify `backend/app/api/v1/settings.py` `update_risk`:

```python
@router.put("/risk", response_model=RiskConfigOut)
def update_risk(
    payload: RiskConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    config = get_risk_config(db, current_user.id)
    data = payload.model_dump(exclude_unset=True)
    if "trading_pair" in data:
        data.pop("trading_pair")  # no longer user-set
    if "max_open_positions" in data:
        data["max_open_positions"] = max(1, min(10, int(data["max_open_positions"])))
    for key, value in data.items():
        setattr(config, key, value)
    db.commit()
    db.refresh(config)
    return config
```

- [ ] **Step 3: Update settings test**

Add to `backend/tests/test_settings.py`:

```python
def test_update_max_open_positions_clamped(client):
    headers = _auth_header(client, "clamp@example.com", "pass")
    res = client.put("/api/v1/settings/risk", json={"max_open_positions": 25}, headers=headers)
    assert res.status_code == 200
    assert res.json()["max_open_positions"] == 10

    res = client.put("/api/v1/settings/risk", json={"max_open_positions": 0}, headers=headers)
    assert res.status_code == 200
    assert res.json()["max_open_positions"] == 1
```

- [ ] **Step 4: Run tests**

Run:
```bash
cd backend
pytest tests/test_settings.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/portfolio.py backend/app/api/v1/settings.py backend/tests/test_settings.py
git commit -m "feat(api): expose max_open_positions, drop user trading_pair setting"
```

---

## Task 5: Bot orchestrator multi-asset loop

**Files:**
- Modify: `backend/app/services/bot_service.py:18-186`
- Test: `backend/tests/test_bot_orchestrator.py`

**Interfaces:**
- Consumes: `AssetSelector`, `RiskManager.slot_budget`, `Portfolio`, `BotState.watchlist`.
- Produces: `BotOrchestrator._run_iteration` loops over up to 5 symbols; models keyed by `(user_id, symbol)`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_bot_orchestrator.py`:

```python
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.models.portfolio import Portfolio, BotState, RiskConfig
from app.models.user import User
from app.services.bot_service import BotOrchestrator


def test_does_not_open_more_than_max_positions():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    user = User(email="bot@test.com", hashed_password="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    portfolio = Portfolio(user_id=user.id, cash=500.0, equity=500.0, mode="PAPER")
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)

    risk = RiskConfig(user_id=user.id, max_open_positions=2)
    db.add(risk)
    db.commit()

    state = BotState(user_id=user.id, is_running=True)
    db.add(state)
    db.commit()

    orch = BotOrchestrator()
    orch.models = {}
    # Mock exchange to return deterministic prices
    exchange = MagicMock()
    exchange.get_ticker = AsyncMock(return_value=MagicMock(last=50000.0))
    exchange.get_ohlcv = AsyncMock(return_value=[
        {"timestamp": None, "open": 1, "high": 1, "low": 1, "close": float(i), "volume": 1000}
        for i in range(1, 201)
    ])
    orch._get_exchange = lambda mode: exchange

    # Force watchlist to 3 symbols but max_open_positions=2
    state.watchlist = ["BTC/EUR", "ETH/EUR", "SOL/EUR"]
    state.watchlist_updated_at = None
    db.commit()

    # Stub selector so we don't call real markets
    orch.asset_selector = MagicMock()
    orch.asset_selector.select = MagicMock(return_value=["BTC/EUR", "ETH/EUR", "SOL/EUR"])

    # Run synchronously for test
    import asyncio
    asyncio.run(orch._run_iteration(user.id, portfolio.id, risk.id))

    assert len(portfolio.positions) <= 2
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd backend
pytest tests/test_bot_orchestrator.py -v
```

Expected: FAIL — `asset_selector` attribute missing, loop still single-symbol.

- [ ] **Step 3: Refactor `BotOrchestrator`**

Modify `backend/app/services/bot_service.py`:

```python
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.models.portfolio import Portfolio, BotState, Signal
from app.models.user import User
from app.exchanges.paper import PaperExchange
from app.exchanges.kraken import KrakenExchange
from app.exchanges.base import OrderSide
from app.services.portfolio_service import get_or_create_portfolio, recalculate_equity, update_position_price
from app.services.trading_service import execute_paper_trade, apply_stop_loss_take_profit
from app.services.risk_service import get_risk_config, risk_manager_from_config
from app.services.asset_selector import AssetSelector
from app.ml.models import SignalModel
import asyncio


class BotOrchestrator:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.models: dict[tuple[int, str], SignalModel] = {}
        self.exchanges: dict[str, object] = {}
        self.asset_selector = AssetSelector()

    async def _run_iteration(self, user_id: int, portfolio_id: int, risk_config_id: int):
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
            risk_config = get_risk_config(db, user_id)
            state = db.query(BotState).filter(BotState.user_id == user_id).first()
            if not user or not portfolio or not state or not state.is_running:
                return

            risk = risk_manager_from_config(risk_config)
            exchange = self._get_exchange(portfolio.mode)

            # Refresh watchlist once per day
            now = datetime.now(timezone.utc)
            watchlist = state.watchlist or []
            stale = (
                not state.watchlist_updated_at
                or (now - state.watchlist_updated_at) > timedelta(days=1)
            )
            if stale:
                universe = await exchange.get_curated_pairs()
                ohlcv_by_symbol = {}
                for sym in universe:
                    try:
                        ohlcv_by_symbol[sym] = await exchange.get_ohlcv(sym, timeframe="1h", limit=200)
                    except Exception:
                        continue
                watchlist = self.asset_selector.select(ohlcv_by_symbol, max_open_positions=risk.max_open_positions)
                state.watchlist = watchlist
                state.watchlist_updated_at = now
                db.commit()

            # Ensure watchlist is limited to max_open_positions
            watchlist = watchlist[: risk.max_open_positions]

            recalculate_equity(db, portfolio)

            open_count = len(portfolio.positions)

            for symbol in watchlist:
                ticker = await exchange.get_ticker(symbol)
                price = ticker.last

                update_position_price(db, portfolio, symbol, price)
                recalculate_equity(db, portfolio)

                exit_trade = apply_stop_loss_take_profit(db, portfolio, exchange, risk, symbol, price)
                if exit_trade:
                    open_count = max(0, open_count - 1)
                    continue

                candles = await exchange.get_ohlcv(symbol, timeframe="1h", limit=200)
                model_key = (user_id, symbol)
                model = self.models.setdefault(model_key, SignalModel(name=symbol.replace("/", "_")))
                model.load()
                if not model.is_fitted:
                    model.fit(candles, horizon=risk.prediction_horizon)

                prediction = model.predict(candles)

                signal = Signal(
                    portfolio_id=portfolio.id,
                    symbol=symbol,
                    model=model.name,
                    action=prediction["action"],
                    probability=prediction["probability"],
                    confidence=prediction["confidence"],
                    features=prediction.get("features"),
                    explanation=prediction.get("explanation"),
                )
                db.add(signal)

                position = next((p for p in portfolio.positions if p.symbol == symbol), None)

                if prediction["action"] == "BUY" and (not position or position.quantity <= 0):
                    if not risk.can_trade_today(db, portfolio.id):
                        state.last_error = "Daily trade limit reached"
                    elif open_count >= risk.max_open_positions:
                        state.last_error = "Max open positions reached"
                    else:
                        qty = risk.position_size(portfolio.equity, price)
                        if qty * price > 0:
                            try:
                                execute_paper_trade(
                                    db,
                                    portfolio,
                                    exchange,
                                    symbol,
                                    OrderSide.BUY,
                                    qty,
                                    price,
                                    risk.fee_pct,
                                    reason=prediction.get("explanation"),
                                )
                                state.health = "HEALTHY"
                                state.last_error = None
                                open_count += 1
                            except Exception as e:
                                state.health = "DEGRADED"
                                state.last_error = str(e)
                elif prediction["action"] == "SELL" and position and position.quantity > 0:
                    try:
                        execute_paper_trade(
                            db,
                            portfolio,
                            exchange,
                            symbol,
                            OrderSide.SELL,
                            position.quantity,
                            price,
                            risk.fee_pct,
                            reason=prediction.get("explanation"),
                        )
                        state.health = "HEALTHY"
                        state.last_error = None
                        open_count = max(0, open_count - 1)
                    except Exception as e:
                        state.health = "DEGRADED"
                        state.last_error = str(e)

            state.last_run_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as e:
            if state:
                state.health = "ERROR"
                state.last_error = str(e)
                db.commit()
        finally:
            db.close()
```

Add `get_curated_pairs()` to the exchange layer. In `backend/app/exchanges/base.py` add to `ExchangeInterface`:

```python
from abc import abstractmethod
from typing import List

class ExchangeInterface:
    ...
    @abstractmethod
    async def get_curated_pairs(self) -> List[str]: ...
```

In `backend/app/exchanges/paper.py` and `backend/app/exchanges/kraken.py` add:

```python
async def get_curated_pairs(self) -> list[str]:
    return ["BTC/EUR", "ETH/EUR", "SOL/EUR", "XRP/EUR", "ADA/EUR"]
```

(Keep the curated list in sync with `backend/app/api/v1/market.py:CURATED_PAIRS`.)

- [ ] **Step 4: Run tests**

Run:
```bash
cd backend
pytest tests/test_bot_orchestrator.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/bot_service.py backend/app/exchanges/base.py backend/app/exchanges/paper.py backend/app/exchanges/kraken.py backend/tests/test_bot_orchestrator.py
git commit -m "feat(bot): loop over autonomous watchlist and enforce max open positions"
```

---

## Task 6: Bot state endpoint returns watchlist and open slots

**Files:**
- Modify: `backend/app/schemas/portfolio.py:65-74`
- Modify: `backend/app/api/v1/bot.py:12-21`

**Interfaces:**
- Produces: `BotStateOut.watchlist: list[str]`, `BotStateOut.open_slots: int`.

- [ ] **Step 1: Update `BotStateOut` schema**

```python
from typing import List, Optional


class BotStateOut(BaseModel):
    id: int
    is_running: bool
    last_run_at: Optional[datetime]
    last_error: Optional[str]
    health: str
    watchlist: Optional[List[str]]
    watchlist_updated_at: Optional[datetime]
    open_slots: int
    updated_at: datetime

    class Config:
        from_attributes = True
```

- [ ] **Step 2: Enrich the bot state response**

Modify `backend/app/api/v1/bot.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.portfolio import BotState, Portfolio, Position
from app.schemas.portfolio import BotStateOut
from app.services.bot_service import bot_orchestrator
from app.services.risk_service import get_risk_config

router = APIRouter(prefix="/bot", tags=["bot"])


@router.get("/state", response_model=BotStateOut)
def get_state(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    state = db.query(BotState).filter(BotState.user_id == current_user.id).first()
    if not state:
        state = BotState(user_id=current_user.id)
        db.add(state)
        db.commit()
        db.refresh(state)

    risk_config = get_risk_config(db, current_user.id)
    portfolio = db.query(Portfolio).filter(Portfolio.user_id == current_user.id).first()
    open_count = db.query(Position).filter(
        Position.portfolio_id == portfolio.id,
        Position.quantity > 0,
    ).count() if portfolio else 0
    open_slots = max(0, risk_config.max_open_positions - open_count)

    return {
        "id": state.id,
        "is_running": state.is_running,
        "last_run_at": state.last_run_at,
        "last_error": state.last_error,
        "health": state.health,
        "watchlist": state.watchlist,
        "watchlist_updated_at": state.watchlist_updated_at,
        "open_slots": open_slots,
        "updated_at": state.updated_at,
    }
```

`BotStateOut` surfaces `watchlist` from the model and `open_slots` computed from the user's risk config.

- [ ] **Step 3: Add test**

Add to `backend/tests/test_bot.py` (or create):

```python
def test_bot_state_includes_watchlist_and_open_slots(client):
    headers = _auth_header(client, "botstate@example.com", "pass")
    res = client.get("/api/v1/bot/state", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert "watchlist" in body
    assert body["watchlist"] is None or isinstance(body["watchlist"], list)
    assert "open_slots" in body
    assert body["open_slots"] == 5
```

- [ ] **Step 4: Run tests**

Run:
```bash
cd backend
pytest tests/test_bot.py tests/test_settings.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/portfolio.py backend/app/api/v1/bot.py backend/tests/test_bot.py
git commit -m "feat(bot): include watchlist in bot state response"
```

---

## Task 7: Frontend types and settings page

**Files:**
- Modify: `frontend/src/types/index.ts:48-67`
- Modify: `frontend/src/pages/Settings.tsx:1-349`

**Interfaces:**
- `RiskConfig.trading_pair?: string`, `RiskConfig.max_open_positions: number`.
- `BotState.watchlist?: string[]`, `BotState.watchlist_updated_at?: string`.

- [ ] **Step 1: Update types**

```typescript
export interface BotState {
  id: number;
  is_running: boolean;
  last_run_at: string | null;
  last_error: string | null;
  health: string;
  watchlist: string[] | null;
  watchlist_updated_at: string | null;
  open_slots: number;
  updated_at: string;
}

export interface RiskConfig {
  id: number;
  max_position_pct: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  fee_pct: number;
  max_daily_trades: number;
  trading_pair?: string;
  prediction_horizon: number;
  max_open_positions: number;
  allocation_mode: string;
  updated_at: string;
}
```

- [ ] **Step 2: Remove trading-pair dropdown from Settings**

In `frontend/src/pages/Settings.tsx`:

```typescript
// Remove pairs state and marketApi.getPairs() call.
// Replace the Trading Pair <select> with a read-only watchlist display and a numeric Max Open Positions input.
```

Concretely, replace the Trading Pair label block with:

```tsx
<label>
  Max Open Positions
  <input
    type="number"
    min={1}
    max={10}
    value={risk.max_open_positions}
    onChange={(e) => setRisk({ ...risk, max_open_positions: parseInt(e.target.value, 10) })}
  />
</label>
<div style={{ gridColumn: '1 / -1' }}>
  <strong>Autonomous Watchlist</strong>
  <div className="flex gap-2 mt-1">
    {risk?.watchlist && risk.watchlist.length > 0 ? (
      risk.watchlist.map((pair) => (
        <span key={pair} className="badge badge-ghost">{pair}</span>
      ))
    ) : (
      <span className="text-muted">No watchlist yet — start the bot to generate it.</span>
    )}
  </div>
</div>
```

Update `updateRisk` payload to exclude `trading_pair`:

```typescript
await settingsApi.updateRisk({
  max_position_pct: risk.max_position_pct,
  stop_loss_pct: risk.stop_loss_pct,
  take_profit_pct: risk.take_profit_pct,
  fee_pct: risk.fee_pct,
  max_daily_trades: risk.max_daily_trades,
  prediction_horizon: risk.prediction_horizon,
  max_open_positions: risk.max_open_positions,
});
```

- [ ] **Step 3: Build the frontend**

Run:
```bash
cd frontend
npm run build
```

Expected: build succeeds with no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/pages/Settings.tsx
git commit -m "feat(ui): remove trading pair picker, add max open positions and watchlist display"
```

---

## Task 8: Dashboard multi-asset view

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx:1-381`

**Interfaces:**
- Consumes: `BotState.watchlist`, `Position[]`, `Signal[]`.
- Produces: watchlist table, open slots counter, per-symbol mini metrics.

- [ ] **Step 1: Replace single-symbol chart with watchlist table**

In `frontend/src/pages/Dashboard.tsx`:

Use `botState?.open_slots` directly; no local computation needed.

Remove `symbol`, `price`, `ohlcv` state and their fetch calls. Keep portfolio, positions, trades, signals, bot state, risk.

Replace the price chart card with:

```tsx
<div className="card span-8">
  <div className="card-header">
    <div className="card-title">
      <List className="card-title-icon" size={18} />
      Autonomous Watchlist
    </div>
    <span className="badge badge-ghost">{botState?.open_slots ?? 5} open slots</span>
  </div>
  <div className="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Symbol</th>
          <th className="text-right">Signal</th>
          <th className="text-right">Position</th>
          <th className="text-right">P/L</th>
        </tr>
      </thead>
      <tbody>
        {(botState?.watchlist || []).map((sym) => {
          const pos = positions.find((p) => p.symbol === sym);
          const sig = signals.find((s) => s.symbol === sym);
          return (
            <tr key={sym}>
              <td className="mono">{sym}</td>
              <td className="text-right">
                {sig ? (
                  <span className={`badge ${sig.action === 'BUY' ? 'badge-success' : sig.action === 'SELL' ? 'badge-danger' : 'badge-ghost'}`}>
                    {sig.action}
                  </span>
                ) : '-'}
              </td>
              <td className="text-right mono">{pos ? pos.quantity.toFixed(6) : '-'}</td>
              <td className={`text-right mono ${pos && pos.unrealized_pnl >= 0 ? 'text-success' : pos ? 'text-danger' : ''}`}>
                {pos ? `€${pos.unrealized_pnl.toFixed(2)}` : '-'}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  </div>
</div>
```

- [ ] **Step 2: Update data fetching**

Remove `marketApi.getPrice` and `marketApi.getOHLCV` calls from `fetchAll`. Remove the `useEffect` that depends on `symbol`.

- [ ] **Step 3: Build the frontend**

Run:
```bash
cd frontend
npm run build
```

Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx
git commit -m "feat(ui): dashboard watchlist table and open slots for multi-asset trading"
```

---

## Task 9: Full backend test run

**Files:**
- All backend tests.

- [ ] **Step 1: Install dependencies if missing**

Run:
```bash
cd backend
pip install -r requirements.txt
```

- [ ] **Step 2: Run the full backend test suite**

Run:
```bash
cd backend
pytest -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit any test fixes**

```bash
git add -A
git commit -m "test: green backend suite for autonomous multi-crypto trading"
```

---

## Task 10: End-to-end smoke test

**Files:**
- Backend + frontend running together.

- [ ] **Step 1: Start the backend**

```bash
cd backend
uvicorn app.main:create_application --factory --reload
```

- [ ] **Step 2: Start the frontend**

```bash
cd frontend
npm run dev
```

- [ ] **Step 3: Smoke test**

1. Register a new user.
2. Open Settings: verify no trading-pair dropdown, max open positions defaults to 5.
3. Change max open positions to 3 and save.
4. Start the bot from Dashboard.
5. Wait up to 5 minutes (or trigger iteration manually if a debug endpoint exists).
6. Verify Dashboard shows a watchlist of up to 3 symbols and an "open slots" counter.
7. Verify Settings displays the same watchlist.
8. Press Emergency Stop and confirm mode returns to PAPER.

- [ ] **Step 4: Commit any final fixes**

```bash
git add -A
git commit -m "fix: smoke test fixes for autonomous multi-crypto trading"
```

---

## Self-Review

**Spec coverage:**
- Autonomous asset selection → Task 2.
- Multi-position data model → Task 1.
- Bot orchestrator loop → Task 5.
- Capital allocation → Task 3.
- Autonomous execution → Tasks 2 + 5.
- Frontend updates → Tasks 7 + 8.
- API changes → Tasks 4 + 6.
- Testing → Tasks 2, 3, 4, 5, 6, 9, 10.

**Placeholder scan:** No TBD/TODO/fill-in-later found.

**Type consistency:**
- `RiskManager.max_open_positions` matches `RiskConfig.max_open_positions`.
- `AssetSelector.select` accepts `max_open_positions` and returns `list[str]`.
- `BotState.watchlist` is `JSON`/`list[str]` on both backend and frontend.
- `BotStateOut` exposes `watchlist`, `watchlist_updated_at`, and `open_slots`.
- Frontend `BotState.open_slots: number` matches the API response.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-09-18-trading-bot-autonomous-multi-crypto-plan.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints.

Which approach would you like?