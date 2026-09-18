from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.portfolio import Trade, RiskConfig
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

    def position_size(self, portfolio_value: float, price: float) -> float:
        allocation = portfolio_value * self.max_position_pct
        return allocation / price if price > 0 else 0.0

    def can_trade_today(self, db: Session, portfolio_id: int) -> bool:
        today = datetime.now(timezone.utc).date()
        count = (
            db.query(Trade)
            .filter(
                Trade.portfolio_id == portfolio_id,
                Trade.created_at >= today,
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
    )
