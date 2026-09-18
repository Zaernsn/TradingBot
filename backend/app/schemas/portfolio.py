from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class PortfolioOut(BaseModel):
    id: int
    currency: str
    cash: float
    equity: float
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
    id: int
    is_running: bool
    last_run_at: Optional[datetime]
    last_error: Optional[str]
    health: str
    updated_at: datetime

    class Config:
        from_attributes = True


class RiskConfigOut(BaseModel):
    id: int
    max_position_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    fee_pct: float
    max_daily_trades: int
    trading_pair: str
    prediction_horizon: int
    updated_at: datetime

    class Config:
        from_attributes = True


class RiskConfigUpdate(BaseModel):
    max_position_pct: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    fee_pct: Optional[float] = None
    max_daily_trades: Optional[int] = None
    trading_pair: Optional[str] = None
    prediction_horizon: Optional[int] = None


class MarketPrice(BaseModel):
    symbol: str
    price: float
    bid: Optional[float]
    ask: Optional[float]
    timestamp: datetime


class BacktestRequest(BaseModel):
    symbol: str
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    initial_cash: float = 500.0
    fee_pct: float = 0.0026


class BacktestTrade(BaseModel):
    timestamp: datetime
    side: str
    quantity: float
    price: float
    pnl: Optional[float]


class BacktestResult(BaseModel):
    symbol: str
    initial_cash: float
    final_equity: float
    total_return_pct: float
    num_trades: int
    win_rate: float
    max_drawdown_pct: float
    sharpe_ratio: float
    trades: List[BacktestTrade]
