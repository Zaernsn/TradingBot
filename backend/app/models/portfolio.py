from sqlalchemy import Column, Integer, Float, String, Boolean, DateTime, ForeignKey, Text, JSON, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    currency = Column(String, default="EUR", nullable=False)
    cash = Column(Float, default=500.0, nullable=False)
    equity = Column(Float, default=500.0, nullable=False)
    mode = Column(String, default="PAPER", nullable=False)  # PAPER | LIVE_DISABLED | LIVE
    book_type = Column(String, default="PAPER", server_default="PAPER", nullable=False)
    is_active = Column(Boolean, default=True, server_default="true", nullable=False)
    initial_equity = Column(Float, default=500.0, server_default="500", nullable=False)
    peak_equity = Column(Float, default=500.0, server_default="500", nullable=False)
    risk_halted = Column(Boolean, default=False, server_default="false", nullable=False)
    account_fingerprint = Column(String, nullable=True, unique=True)
    target_positions = Column(Integer, default=20, server_default="20", nullable=False)
    __table_args__ = (
        UniqueConstraint('user_id', 'book_type', name='uq_portfolios_user_book'),
        Index('uq_portfolios_active_user', 'user_id', unique=True,
              sqlite_where=is_active.is_(True), postgresql_where=is_active.is_(True)),
    )
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="portfolios")
    positions = relationship("Position", back_populates="portfolio", cascade="all, delete-orphan")
    trades = relationship("Trade", back_populates="portfolio", cascade="all, delete-orphan")


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    symbol = Column(String, nullable=False)
    quantity = Column(Float, default=0.0, nullable=False)
    avg_entry_price = Column(Float, default=0.0, nullable=False)
    entry_fees = Column(Float, default=0.0, server_default="0", nullable=False)
    current_price = Column(Float, nullable=False)
    unrealized_pnl = Column(Float, default=0.0, nullable=False)
    realized_pnl = Column(Float, default=0.0, nullable=False)
    opened_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("uq_positions_open_symbol", "portfolio_id", "symbol", unique=True,
              sqlite_where=quantity > 0, postgresql_where=quantity > 0),
    )

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
    lock_token = Column(String, nullable=True)
    lock_until = Column(DateTime(timezone=True), nullable=True)
    watchlist = Column(JSON, nullable=True)
    watchlist_updated_at = Column(DateTime(timezone=True), nullable=True)
    entry_decisions = Column(JSON, nullable=True)
    discovery_stats = Column(JSON, nullable=True)
    candidate_status = Column(JSON, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RiskConfig(Base):
    entry_strategy = Column(String, default='model', server_default='model', nullable=False)
    buy_probability_threshold = Column(Float, default=.4, server_default='0.4', nullable=False)
    __tablename__ = "risk_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    max_position_pct = Column(Float, default=0.20, nullable=False)
    stop_loss_pct = Column(Float, default=0.03, nullable=False)
    take_profit_pct = Column(Float, default=0.06, nullable=False)
    fee_pct = Column(Float, default=0.0026, nullable=False)
    verified_taker_fee_pct = Column(Float, nullable=True)
    verified_taker_fee_at = Column(DateTime(timezone=True), nullable=True)
    max_invest_per_trade_eur = Column(Float, default=0., server_default="0", nullable=False)
    risk_per_trade_pct = Column(Float, default=0., server_default="0", nullable=False)
    max_holding_hours = Column(Integer, default=0, server_default="0", nullable=False)
    discovery_limit = Column(Integer, default=60, server_default="60", nullable=False)
    watchlist_limit = Column(Integer, default=30, server_default="30", nullable=False)
    max_daily_trades = Column(Integer, default=10, nullable=False)
    trading_pair = Column(String, nullable=True)
    max_open_positions = Column(Integer, default=20, server_default="20", nullable=False)
    allocation_mode = Column(String, default="equal", nullable=False)
    max_drawdown_pct = Column(Float, default=.10, server_default="0.10", nullable=False)
    max_total_exposure_pct = Column(Float, default=.80, server_default="0.80", nullable=False)
    max_correlated_exposure_pct = Column(Float, default=.40, server_default="0.40", nullable=False)
    correlation_threshold = Column(Float, default=.80, server_default="0.80", nullable=False)
    slippage_pct = Column(Float, default=.001, server_default="0.001", nullable=False)
    memecoins_enabled = Column(Boolean, default=True, server_default="true", nullable=False)
    memecoin_max_position_pct = Column(Float, default=.05, server_default="0.05", nullable=False)
    memecoin_max_exposure_pct = Column(Float, default=.10, server_default="0.10", nullable=False)
    memecoin_max_spread_pct = Column(Float, default=.006, server_default="0.006", nullable=False)
    memecoin_min_daily_volume_eur = Column(Float, default=250000., server_default="250000", nullable=False)
    prediction_horizon = Column(Integer, default=12, nullable=False)  # number of candles
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ExecutionOrder(Base):
    __tablename__ = 'execution_orders'
    id = Column(Integer, primary_key=True)
    portfolio_id = Column(Integer, ForeignKey('portfolios.id'), nullable=False, index=True)
    client_id = Column(String, nullable=False, unique=True)
    exchange_id = Column(String, nullable=True, unique=True)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    requested_quantity = Column(Float, nullable=False)
    status = Column(String, default='SUBMITTING', nullable=False)
    filled_quantity = Column(Float, default=0., nullable=False)
    filled_cost = Column(Float, default=0., nullable=False)
    filled_fee = Column(Float, default=0., nullable=False)
    filled_base_fee = Column(Float, default=0., nullable=False)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MarketCandle(Base):
    __tablename__ = 'market_candles'
    symbol = Column(String, primary_key=True)
    timeframe = Column(String, primary_key=True)
    timestamp = Column(DateTime(timezone=True), primary_key=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)


class ModelRecovery(Base):
    __tablename__ = 'model_recoveries'
    id = Column(Integer, primary_key=True)
    portfolio_id = Column(Integer, ForeignKey('portfolios.id'), nullable=False)
    symbol = Column(String, nullable=False)
    signature = Column(String, nullable=False)
    candle_timestamp = Column(String, nullable=False)
    state = Column(String, nullable=False)
    attempted_at = Column(DateTime(timezone=True), nullable=False)
    retry_after = Column(DateTime(timezone=True), nullable=False)
    message = Column(Text, nullable=False)
    diagnostics = Column(JSON, nullable=True)
    __table_args__ = (UniqueConstraint('portfolio_id','symbol',name='uq_model_recovery_symbol'),)


class StrategyCandidate(Base):
    __tablename__ = 'strategy_candidates'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    candidate_id = Column(String, nullable=False)
    parameters = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default='REJECTED')
    metrics = Column(JSON, nullable=False)
    tested_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint('user_id','candidate_id',name='uq_strategy_candidate_user'),)


class ShadowRun(Base):
    __tablename__ = 'shadow_runs'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    candidate_id = Column(String, nullable=False)
    version = Column(String, nullable=False)
    status = Column(String, nullable=False, default='ACTIVE')
    started_at = Column(DateTime(timezone=True), nullable=False)
    last_candle_at = Column(DateTime(timezone=True), nullable=True)
    initial_cash = Column(Float, nullable=False)
    cash = Column(Float, nullable=False)
    equity = Column(Float, nullable=False)
    peak_equity = Column(Float, nullable=False)
    open_positions = Column(JSON, nullable=False, default=dict)
    metrics = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint('user_id','candidate_id',name='uq_shadow_run_candidate'),)


class ShadowTrade(Base):
    __tablename__ = 'shadow_trades'
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey('shadow_runs.id'), nullable=False, index=True)
    intent_key = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    fee = Column(Float, nullable=False)
    pnl = Column(Float, nullable=True)
    candle_timestamp = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint('run_id','intent_key',name='uq_shadow_trade_intent'),)


class ShadowEquity(Base):
    __tablename__ = 'shadow_equity'
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey('shadow_runs.id'), nullable=False, index=True)
    candle_timestamp = Column(DateTime(timezone=True), nullable=False)
    cash = Column(Float, nullable=False)
    equity = Column(Float, nullable=False)
    drawdown_pct = Column(Float, nullable=False)
    __table_args__ = (UniqueConstraint('run_id','candle_timestamp',name='uq_shadow_equity_candle'),)


class ResearchSnapshot(Base):
    __tablename__ = 'research_snapshots'
    id = Column(Integer, primary_key=True)
    portfolio_id = Column(Integer, ForeignKey('portfolios.id'), nullable=False, index=True)
    captured_at = Column(DateTime(timezone=True), nullable=False)
    candidate_id = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)


class KrakenSnapshot(Base):
    __tablename__ = 'kraken_snapshots'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    account_key = Column(String, nullable=False)
    equity = Column(Float, nullable=True)
    holdings = Column(JSON, nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=False, index=True)
