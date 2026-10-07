from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, field_validator


class PortfolioOut(BaseModel):
    id: int
    currency: str
    cash: float
    equity: float
    initial_equity: float
    peak_equity: float
    risk_halted: bool
    mode: str
    updated_at: datetime

    class Config:
        from_attributes = True


class PositionOut(BaseModel):
    id: int
    symbol: str
    quantity: float
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    opened_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TradeOut(BaseModel):
    id: int
    symbol: str
    side: str
    quantity: float
    price: float
    fee: float
    slippage: float
    total_cost: float
    pnl: Optional[float]
    mode: str
    reason: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class SignalOut(BaseModel):
    id: int
    symbol: str
    model: str
    action: str
    probability: float
    confidence: float
    explanation: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class BotStateOut(BaseModel):
    discovery_stats: Optional[dict] = None
    candidate_status: Optional[dict] = None
    blocker_summary: dict[str, int] = Field(default_factory=dict)
    entry_decisions: dict = Field(default_factory=dict)
    id: int
    is_running: bool
    last_run_at: Optional[datetime]
    last_error: Optional[str]
    health: str
    watchlist: Optional[List[str]] = None
    watchlist_updated_at: Optional[datetime] = None
    watchlist_refresh_seconds: int = 86400
    memecoin_watchlist_count: int = 0
    memecoin_watchlist_target: int = 0
    open_slots: int = 20
    updated_at: datetime

    class Config:
        from_attributes = True


class RiskConfigOut(BaseModel):
    entry_strategy: Literal['model', 'momentum', 'fast_momentum', 'auto'] = 'model'
    buy_probability_threshold: float = .4
    discovery_limit: int = 60
    watchlist_limit: int = 30
    risk_per_trade_pct: float = 0.
    max_holding_hours: int = 0
    id: int
    max_position_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    fee_pct: float
    verified_taker_fee_pct: Optional[float] = None
    verified_taker_fee_at: Optional[datetime] = None
    max_invest_per_trade_eur: float
    max_daily_trades: int
    trading_pair: Optional[str] = None
    max_open_positions: int
    allocation_mode: Literal['equal']
    prediction_horizon: int
    max_drawdown_pct: float
    max_total_exposure_pct: float
    max_correlated_exposure_pct: float
    correlation_threshold: float
    slippage_pct: float
    memecoins_enabled: bool
    memecoin_max_position_pct: float
    memecoin_max_exposure_pct: float
    memecoin_max_spread_pct: float
    memecoin_min_daily_volume_eur: float
    updated_at: datetime

    class Config:
        from_attributes = True


class RiskConfigUpdate(BaseModel):
    entry_strategy: Optional[Literal['model', 'momentum', 'fast_momentum', 'auto']] = None
    buy_probability_threshold: Optional[float] = Field(None, ge=.4, le=.95, allow_inf_nan=False)
    discovery_limit: Optional[int] = Field(None, ge=30, le=120)
    watchlist_limit: Optional[int] = Field(None, ge=5, le=30)
    risk_per_trade_pct: Optional[float] = Field(None, ge=0, le=.05, allow_inf_nan=False)
    max_holding_hours: Optional[int] = Field(None, ge=0, le=8760)
    max_position_pct: Optional[float] = Field(None, gt=0, le=1)
    stop_loss_pct: Optional[float] = Field(None, gt=0, le=1)
    take_profit_pct: Optional[float] = Field(None, gt=0)
    fee_pct: Optional[float] = Field(None, ge=0, lt=1)
    max_daily_trades: Optional[int] = Field(None, ge=1)
    prediction_horizon: Optional[int] = Field(None, ge=1, le=100)
    max_invest_per_trade_eur: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    max_open_positions: Optional[int] = None
    allocation_mode: Optional[Literal['equal']] = None
    max_drawdown_pct: Optional[float] = Field(None, gt=0, le=1)
    max_total_exposure_pct: Optional[float] = Field(None, gt=0, le=1)
    max_correlated_exposure_pct: Optional[float] = Field(None, gt=0, le=1)
    correlation_threshold: Optional[float] = Field(None, ge=0, le=1)
    slippage_pct: Optional[float] = Field(None, ge=0, le=.05)

    memecoins_enabled: Optional[bool] = None
    memecoin_max_position_pct: Optional[float] = Field(None, gt=0, le=.25)
    memecoin_max_exposure_pct: Optional[float] = Field(None, gt=0, le=.50)
    memecoin_max_spread_pct: Optional[float] = Field(None, gt=0, le=.02)
    memecoin_min_daily_volume_eur: Optional[float] = Field(None, ge=5000)

    @field_validator('max_open_positions')
    @classmethod
    def clamp_slots(cls, value):
        return max(1, min(20, value)) if value is not None else None


class MarketPrice(BaseModel):
    symbol: str
    price: float
    bid: Optional[float]
    ask: Optional[float]
    timestamp: datetime


class BacktestRequest(BaseModel):
    use_saved_risk: bool = True
    symbol: str
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    initial_cash: float = Field(500., gt=0)
    fee_pct: float = Field(.0026, ge=0, lt=1)
    slippage_pct: float = Field(.001, ge=0, le=.05)
    prediction_horizon: int = Field(12, ge=1, le=100)
    max_open_positions: int = Field(20, ge=1, le=20)


class BacktestTrade(BaseModel):
    symbol: str = "UNKNOWN"
    fee: float = 0.
    timestamp: datetime
    side: str
    quantity: float
    price: float
    pnl: Optional[float]


class BacktestResult(BaseModel):
    experiment: dict = Field(default_factory=dict)
    closed_trades: int = 0
    time_underwater_bars: int = 0
    hourly_mean_return_interval: Optional[dict] = None
    data_limitations: List[str] = Field(default_factory=list)
    symbol: str
    initial_cash: float
    final_equity: float
    total_return_pct: float
    num_trades: int
    win_rate: float
    max_drawdown_pct: float
    sharpe_ratio: float
    trades: List[BacktestTrade]
    expectancy: float = 0.
    total_fees: float = 0.
    turnover: float = 0.
    average_exposure: float = 0.
    per_symbol_pnl: dict[str, float] = Field(default_factory=dict)
    benchmarks: dict[str, Optional[float]] = Field(default_factory=dict)
    evaluation_start: Optional[datetime] = None
    evaluation_end: Optional[datetime] = None
    evaluated_bars: int = 0
    risk_halted: bool = False
    warnings: List[str] = Field(default_factory=list)
