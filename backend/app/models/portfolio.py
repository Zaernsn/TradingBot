from sqlalchemy import Column, Integer, Float, String, Boolean, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    currency = Column(String, default="EUR", nullable=False)
    cash = Column(Float, default=500.0, nullable=False)
    equity = Column(Float, default=500.0, nullable=False)
    mode = Column(String, default="PAPER", nullable=False)  # PAPER | LIVE_DISABLED | LIVE
    target_positions = Column(Integer, default=5, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="portfolio")
    positions = relationship("Position", back_populates="portfolio", cascade="all, delete-orphan")
    trades = relationship("Trade", back_populates="portfolio", cascade="all, delete-orphan")


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    symbol = Column(String, nullable=False)
    quantity = Column(Float, default=0.0, nullable=False)
    avg_entry_price = Column(Float, default=0.0, nullable=False)
    current_price = Column(Float, nullable=False)
    unrealized_pnl = Column(Float, default=0.0, nullable=False)
    realized_pnl = Column(Float, default=0.0, nullable=False)
    opened_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    portfolio = relationship("Portfolio", back_populates="positions")


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)  # BUY | SELL
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    fee = Column(Float, default=0.0, nullable=False)
    slippage = Column(Float, default=0.0, nullable=False)
    total_cost = Column(Float, nullable=False)
    pnl = Column(Float, nullable=True)
    mode = Column(String, default="PAPER", nullable=False)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    portfolio = relationship("Portfolio", back_populates="trades")


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    symbol = Column(String, nullable=False)
    model = Column(String, nullable=False)
    action = Column(String, nullable=False)  # BUY | SELL | HOLD
    probability = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    features = Column(JSON, nullable=True)
    explanation = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class BotState(Base):
    __tablename__ = "bot_states"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    is_running = Column(Boolean, default=False, nullable=False)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    health = Column(String, default="UNKNOWN", nullable=False)  # HEALTHY | DEGRADED | ERROR | UNKNOWN
    watchlist = Column(JSON, nullable=True)
    watchlist_updated_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RiskConfig(Base):
    __tablename__ = "risk_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    max_position_pct = Column(Float, default=0.20, nullable=False)
    stop_loss_pct = Column(Float, default=0.03, nullable=False)
    take_profit_pct = Column(Float, default=0.06, nullable=False)
    fee_pct = Column(Float, default=0.0026, nullable=False)
    max_daily_trades = Column(Integer, default=10, nullable=False)
    trading_pair = Column(String, nullable=True)
    max_open_positions = Column(Integer, default=5, nullable=False)
    allocation_mode = Column(String, default="equal", nullable=False)
    prediction_horizon = Column(Integer, default=12, nullable=False)  # number of candles
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
