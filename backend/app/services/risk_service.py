from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.portfolio import Trade, RiskConfig, Portfolio, ExecutionOrder
from app.core.config import settings


@dataclass
class RiskManager:
    max_position_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    fee_pct: float
    max_daily_trades: int
    trading_pair: str
    prediction_horizon: int
    max_open_positions: int = 20
    max_drawdown_pct: float = .10
    max_total_exposure_pct: float = .80
    max_correlated_exposure_pct: float = .40
    correlation_threshold: float = .80
    slippage_pct: float = .001

    memecoins_enabled: bool = True
    memecoin_max_position_pct: float = .05
    memecoin_max_exposure_pct: float = .10
    memecoin_max_spread_pct: float = .003
    memecoin_min_daily_volume_eur: float = 5000.
    max_invest_per_trade_eur: float = 0.
    risk_per_trade_pct: float = 0.
    max_holding_hours: int = 0
    discovery_limit: int = 60
    watchlist_limit: int = 30
    entry_strategy: str = 'model'
    buy_probability_threshold: float = .4

    def __post_init__(self):
        if self.entry_strategy not in {'model', 'momentum', 'fast_momentum', 'auto'}:
            raise ValueError('Unknown entry strategy')
        if not .4 <= self.buy_probability_threshold <= .95:
            raise ValueError('BUY threshold must be at least 40% and be at most 95%')
        self.max_open_positions = max(1, min(20, self.max_open_positions))
        if not 0 <= self.risk_per_trade_pct <= .05 or self.max_holding_hours < 0:
            raise ValueError('Invalid loss budget or holding period')
        if not 30 <= self.discovery_limit <= 120 or not 5 <= self.watchlist_limit <= 30:
            raise ValueError('Invalid discovery/watchlist limit')

    def slot_budget(self, portfolio_value: float) -> float:
        return max(0.0, portfolio_value) / self.max_open_positions

    def position_size(self, portfolio_value: float, price: float) -> float:
        allocation = max(0.0, min(portfolio_value * self.max_position_pct, self.slot_budget(portfolio_value)))
        return allocation / price if price > 0 else 0.0

    def can_trade_today(self, db: Session, portfolio_id: int) -> bool:
        today = datetime.now(timezone.utc).date()
        book = db.get(Portfolio, portfolio_id)
        if book and book.book_type == "LIVE":
            return db.query(ExecutionOrder).filter(ExecutionOrder.portfolio_id == portfolio_id,
                ExecutionOrder.side == "BUY", ExecutionOrder.created_at >= today).count() < self.max_daily_trades
        count = (
            db.query(Trade)
            .filter(
                Trade.portfolio_id == portfolio_id,
                Trade.created_at >= today,
                Trade.side == "BUY",
            )
            .count()
        )
        return count < self.max_daily_trades


def get_risk_config(db: Session, user_id: int) -> RiskConfig:
    config = db.query(RiskConfig).filter(RiskConfig.user_id == user_id).first()
    if not config:
        config = RiskConfig(
            user_id=user_id,
            max_position_pct=settings.DEFAULT_MAX_POSITION_PCT,
            stop_loss_pct=settings.DEFAULT_STOP_LOSS_PCT,
            take_profit_pct=settings.DEFAULT_TAKE_PROFIT_PCT,
            fee_pct=settings.DEFAULT_FEE_PCT,
            trading_pair=settings.DEFAULT_TRADING_PAIR,
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def risk_manager_from_config(config: RiskConfig) -> RiskManager:
    return RiskManager(
        max_position_pct=config.max_position_pct,
        stop_loss_pct=config.stop_loss_pct,
        take_profit_pct=config.take_profit_pct,
        fee_pct=config.fee_pct,
        max_daily_trades=config.max_daily_trades,
        trading_pair=config.trading_pair,
        prediction_horizon=config.prediction_horizon,
        max_invest_per_trade_eur=config.max_invest_per_trade_eur,
        risk_per_trade_pct=config.risk_per_trade_pct,
        max_holding_hours=config.max_holding_hours,
        discovery_limit=config.discovery_limit,
        watchlist_limit=config.watchlist_limit,
        entry_strategy=config.entry_strategy,
        buy_probability_threshold=config.buy_probability_threshold,
        max_open_positions=config.max_open_positions,
        max_drawdown_pct=config.max_drawdown_pct,
        max_total_exposure_pct=config.max_total_exposure_pct,
        max_correlated_exposure_pct=config.max_correlated_exposure_pct,
        correlation_threshold=config.correlation_threshold,
        slippage_pct=config.slippage_pct,
        memecoins_enabled=config.memecoins_enabled,
        memecoin_max_position_pct=config.memecoin_max_position_pct,
        memecoin_max_exposure_pct=config.memecoin_max_exposure_pct,
        memecoin_max_spread_pct=config.memecoin_max_spread_pct,
        memecoin_min_daily_volume_eur=config.memecoin_min_daily_volume_eur,

    )


def entry_budget(portfolio, risk, symbol, positions, history):
    """Cap total and positively correlated exposure; missing histories are conservative."""
    import pandas as pd
    equity=max(0.,portfolio.equity)
    total=sum(p.quantity*p.current_price for p in positions)
    related=0.
    correlation_threshold = getattr(risk, 'correlation_threshold', 0.8)
    risk_per_trade_pct = getattr(risk, 'risk_per_trade_pct', 0.0)
    prediction_horizon = getattr(risk, 'prediction_horizon', 12)
    stop_loss_pct = getattr(risk, 'stop_loss_pct', 0.0)
    fee_pct = getattr(risk, 'fee_pct', 0.0)
    slippage_pct = getattr(risk, 'slippage_pct', 0.0)

    def returns(candles):
        return pd.Series({c.timestamp:c.close for c in candles}).sort_index().pct_change().dropna().tail(168)
    candidate=returns(history.get(symbol,[]))
    for position in positions:
        other=returns(history.get(position.symbol,[]))
        aligned=pd.concat([candidate,other],axis=1).dropna()
        correlation=aligned.corr().iloc[0,1] if len(aligned)>=30 else float('nan')
        if pd.isna(correlation) or correlation>=correlation_threshold:
            related+=position.quantity*position.current_price
    from app.services.memecoin_service import memecoin_budget
    loss_budget = float('inf')
    if risk_per_trade_pct:
        # Cap against both planned stop distance and observed horizon volatility.
        # Includes round-trip friction; gaps can still exceed this planning budget.
        if len(candidate) < 30:
            return 0.
        volatility = float(candidate.std()) * max(1, prediction_horizon) ** .5
        distance = max(stop_loss_pct, 2 * volatility) + 2 * (fee_pct + slippage_pct)
        loss_budget = equity * risk_per_trade_pct / max(distance, 1e-8)
    slot_budget = getattr(risk, 'slot_budget', lambda _: float('inf'))(equity)
    max_position_pct = getattr(risk, 'max_position_pct', 1.0)
    max_total_exposure_pct = getattr(risk, 'max_total_exposure_pct', 1.0)
    max_correlated_exposure_pct = getattr(risk, 'max_correlated_exposure_pct', 1.0)
    return max(0.,min(loss_budget,getattr(risk, 'max_invest_per_trade_eur', float('inf')) or float('inf'),memecoin_budget(portfolio,risk,symbol,positions),slot_budget,equity*max_position_pct,portfolio.cash,
                      equity*max_total_exposure_pct-total,
                      equity*max_correlated_exposure_pct-related))


def check_drawdown(portfolio,risk):
    portfolio.peak_equity=max(portfolio.peak_equity or portfolio.equity,portfolio.equity)
    if portfolio.peak_equity>0 and 1-portfolio.equity/portfolio.peak_equity>=risk.max_drawdown_pct:
        portfolio.risk_halted=True
    return portfolio.risk_halted
