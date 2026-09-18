from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from app.models.portfolio import Portfolio, Position, Trade
from app.exchanges.base import ExchangeInterface, OrderSide
from app.services.portfolio_service import get_position, recalculate_equity
from app.services.risk_service import RiskManager


def execute_paper_trade(
    db: Session,
    portfolio: Portfolio,
    exchange: ExchangeInterface,
    symbol: str,
    side: OrderSide,
    quantity: float,
    price: float,
    fee_pct: float,
    slippage_pct: float = 0.001,
    reason: Optional[str] = None,
) -> Trade:
    """Simulate a market order including slippage and fees."""
    slippage = price * slippage_pct if side == OrderSide.BUY else -price * slippage_pct
    fill_price = price + slippage
    gross = fill_price * quantity
    fee = gross * fee_pct
    total_cost = gross + fee if side == OrderSide.BUY else gross - fee

    position = get_position(db, portfolio.id, symbol)

    if side == OrderSide.BUY:
        if total_cost > portfolio.cash:
            raise ValueError("Insufficient cash for trade")
        if position:
            total_qty = position.quantity + quantity
            position.avg_entry_price = (
                position.avg_entry_price * position.quantity + fill_price * quantity
            ) / total_qty
            position.quantity = total_qty
        else:
            position = Position(
                portfolio_id=portfolio.id,
                symbol=symbol,
                quantity=quantity,
                avg_entry_price=fill_price,
                current_price=fill_price,
            )
            db.add(position)
        portfolio.cash -= total_cost
    else:
        if not position or position.quantity < quantity:
            raise ValueError("Insufficient position to sell")
        realized = (fill_price - position.avg_entry_price) * quantity - fee
        position.realized_pnl += realized
        position.quantity -= quantity
        position.unrealized_pnl = (fill_price - position.avg_entry_price) * position.quantity
        portfolio.cash += total_cost
        if position.quantity <= 1e-9:
            db.delete(position)

    trade = Trade(
        portfolio_id=portfolio.id,
        symbol=symbol,
        side=side.value,
        quantity=quantity,
        price=fill_price,
        fee=fee,
        slippage=slippage,
        total_cost=total_cost,
        pnl=realized if side == OrderSide.SELL else None,
        mode=portfolio.mode,
        reason=reason,
    )
    db.add(trade)
    recalculate_equity(db, portfolio)
    db.refresh(trade)
    return trade


def apply_stop_loss_take_profit(
    db: Session,
    portfolio: Portfolio,
    exchange: ExchangeInterface,
    risk: RiskManager,
    symbol: str,
    current_price: float,
) -> Optional[Trade]:
    position = get_position(db, portfolio.id, symbol)
    if not position or position.quantity <= 0:
        return None

    stop = position.avg_entry_price * (1 - risk.stop_loss_pct)
    target = position.avg_entry_price * (1 + risk.take_profit_pct)

    if current_price <= stop:
        return execute_paper_trade(
            db,
            portfolio,
            exchange,
            symbol,
            OrderSide.SELL,
            position.quantity,
            current_price,
            risk.fee_pct,
            reason=f"Stop-loss hit at {current_price:.2f}",
        )
    if current_price >= target:
        return execute_paper_trade(
            db,
            portfolio,
            exchange,
            symbol,
            OrderSide.SELL,
            position.quantity,
            current_price,
            risk.fee_pct,
            reason=f"Take-profit hit at {current_price:.2f}",
        )
    return None
