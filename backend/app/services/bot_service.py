from datetime import datetime, timezone
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
from app.ml.models import SignalModel
import asyncio


class BotOrchestrator:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.models: dict[str, SignalModel] = {}
        self.exchanges: dict[str, object] = {}

    async def start(self, db: Session, user: User) -> BotState:
        state = db.query(BotState).filter(BotState.user_id == user.id).first()
        if not state:
            state = BotState(user_id=user.id)
            db.add(state)
        if state.is_running:
            return state

        portfolio = get_or_create_portfolio(db, user.id)
        risk_config = get_risk_config(db, user.id)

        job_id = f"bot_{user.id}"
        if not self.scheduler.running:
            self.scheduler.start()
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        self.scheduler.add_job(
            self._run_iteration,
            trigger=IntervalTrigger(minutes=5),
            id=job_id,
            args=[user.id, portfolio.id, risk_config.id],
            replace_existing=True,
            misfire_grace_time=300,
        )

        state.is_running = True
        state.health = "HEALTHY"
        state.last_run_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(state)
        return state

    async def stop(self, db: Session, user: User) -> BotState:
        state = db.query(BotState).filter(BotState.user_id == user.id).first()
        if not state:
            state = BotState(user_id=user.id)
            db.add(state)
        job_id = f"bot_{user.id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
        state.is_running = False
        state.health = "UNKNOWN"
        db.commit()
        db.refresh(state)
        return state

    async def emergency_stop(self, db: Session, user: User) -> BotState:
        state = await self.stop(db, user)
        portfolio = get_or_create_portfolio(db, user.id)
        portfolio.mode = "PAPER"
        db.commit()
        return state

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
            symbol = risk.trading_pair
            exchange = self._get_exchange(portfolio.mode)

            ticker = await exchange.get_ticker(symbol)
            price = ticker.last

            update_position_price(db, portfolio, symbol, price)
            recalculate_equity(db, portfolio)

            exit_trade = apply_stop_loss_take_profit(db, portfolio, exchange, risk, symbol, price)
            if exit_trade:
                state.last_run_at = datetime.now(timezone.utc)
                db.commit()
                return

            candles = await exchange.get_ohlcv(symbol, timeframe="1h", limit=200)
            model = self.models.setdefault(symbol, SignalModel(name=symbol.replace("/", "_")))
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

    def _get_exchange(self, mode: str):
        if mode == "LIVE":
            return KrakenExchange()
        return PaperExchange()


bot_orchestrator = BotOrchestrator()
