from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from app.models.portfolio import Portfolio, Position, Trade
from app.core.config import settings


def get_or_create_portfolio(db: Session, user_id: int) -> Portfolio:
    portfolio = db.query(Portfolio).filter(Portfolio.user_id == user_id).first()
    if not portfolio:
        portfolio = Portfolio(
            user_id=user_id,
            cash=settings.DEFAULT_PAPER_BALANCE_EUR,
            equity=settings.DEFAULT_PAPER_BALANCE_EUR,
            mode="PAPER",
        )
        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)
    return portfolio


def reset_paper_portfolio(db: Session, user_id: int) -> Portfolio:
    portfolio = get_or_create_portfolio(db, user_id)
    db.query(Position).filter(Position.portfolio_id == portfolio.id).delete()
    db.query(Trade).filter(Trade.portfolio_id == portfolio.id).delete()
    portfolio.cash = settings.DEFAULT_PAPER_BALANCE_EUR
    portfolio.equity = settings.DEFAULT_PAPER_BALANCE_EUR
    portfolio.mode = "PAPER"
    db.commit()
    db.refresh(portfolio)
    return portfolio


def get_position(db: Session, portfolio_id: int, symbol: str) -> Optional[Position]:
    return db.query(Position).filter(Position.portfolio_id == portfolio_id, Position.symbol == symbol).first()


def update_position_price(db: Session, portfolio: Portfolio, symbol: str, price: float):
    position = get_position(db, portfolio.id, symbol)
    if position:
        position.current_price = price
        position.unrealized_pnl = (price - position.avg_entry_price) * position.quantity
        position.updated_at = datetime.now(timezone.utc)
    db.commit()


def recalculate_equity(db: Session, portfolio: Portfolio):
    positions_value = sum(p.quantity * p.current_price for p in portfolio.positions)
    portfolio.equity = portfolio.cash + positions_value
    portfolio.updated_at = datetime.now(timezone.utc)
    db.commit()
