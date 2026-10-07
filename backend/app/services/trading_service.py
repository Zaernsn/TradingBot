"""Accounting shared by simulated fills and reconciled exchange fills."""
from math import isfinite
from app.models.portfolio import Position, Trade
from app.exchanges.base import OrderSide
from app.services.portfolio_service import get_position, recalculate_equity


def record_fill(db, portfolio, symbol, side, quantity, fill_price, fee, market_price,
                reason=None, base_fee=0., commit=True):
    if any(not isfinite(v) for v in [quantity,fill_price,fee,market_price,base_fee]):
        raise ValueError('Non-finite fill')
    if quantity <= 0 or fill_price <= 0 or market_price <= 0 or fee < 0 or base_fee < 0:
        raise ValueError('Invalid fill')
    gross=quantity*fill_price
    position=get_position(db,portfolio.id,symbol)
    realized=None
    if side == OrderSide.BUY:
        received=quantity-base_fee
        if received <= 0 or gross+fee > portfolio.cash+1e-7:
            raise ValueError('Insufficient cash or invalid net filled quantity')
        if position is None:
            position=Position(portfolio_id=portfolio.id,symbol=symbol,quantity=0.,avg_entry_price=0.,
                              current_price=market_price,entry_fees=0.,realized_pnl=0.)
            db.add(position)
        total=position.quantity+received
        position.avg_entry_price=(position.avg_entry_price*position.quantity+gross)/total
        position.quantity=total
        position.entry_fees=(position.entry_fees or 0.)+fee
        portfolio.cash-=gross+fee
    else:
        disposed=quantity+base_fee
        if position is None or disposed > position.quantity+1e-10:
            raise ValueError('Exchange sold more assets than the local position; reconciliation required')
        allocated=(position.entry_fees or 0.)*min(1.,disposed/position.quantity)
        realized=gross-fee-position.avg_entry_price*disposed-allocated
        position.realized_pnl+=realized
        position.entry_fees=max(0.,(position.entry_fees or 0.)-allocated)
        position.quantity=max(0.,position.quantity-disposed)
        portfolio.cash+=gross-fee
    position.current_price=market_price
    position.unrealized_pnl=(market_price-position.avg_entry_price)*position.quantity-position.entry_fees
    if position.quantity <= 1e-12:
        db.delete(position)
    trade=Trade(portfolio_id=portfolio.id,symbol=symbol,side=side.value,quantity=quantity,
                price=fill_price,fee=fee,slippage=fill_price-market_price,
                total_cost=gross+fee if side==OrderSide.BUY else gross-fee,pnl=realized,
                mode=portfolio.mode,reason=reason)
    db.add(trade)
    db.flush()
    positions=db.query(Position).filter(Position.portfolio_id==portfolio.id).all()
    portfolio.equity=portfolio.cash+sum(p.quantity*p.current_price for p in positions)
    if commit:
        db.commit(); db.refresh(trade)
    return trade


def execute_paper_trade(db,portfolio,exchange,symbol,side,quantity,price,fee_pct,
                        slippage_pct=.001,reason=None):
    if portfolio.mode != 'PAPER' or portfolio.book_type != 'PAPER':
        raise ValueError('Paper execution requires a PAPER book')
    fill=price*(1+slippage_pct if side==OrderSide.BUY else 1-slippage_pct)
    return record_fill(db,portfolio,symbol,side,quantity,fill,fill*quantity*fee_pct,price,reason)


def exit_reason(position,risk,price,now=None):
    if price <= position.avg_entry_price*(1-risk.stop_loss_pct): return 'Stop-loss'
    if price >= position.avg_entry_price*(1+risk.take_profit_pct): return 'Take-profit'
    if getattr(risk,'max_holding_hours',0) and getattr(position,'opened_at',None):
        from datetime import datetime, timezone, timedelta
        from app.services.market_data import utc
        if utc(now or datetime.now(timezone.utc))-utc(position.opened_at)>=timedelta(hours=risk.max_holding_hours):
            return 'Maximum holding period'
    return None


def apply_stop_loss_take_profit(db,portfolio,exchange,risk,symbol,current_price):
    position=get_position(db,portfolio.id,symbol)
    if not position or position.quantity <= 0: return None
    reason=exit_reason(position,risk,current_price)
    if reason:
        return execute_paper_trade(db,portfolio,exchange,symbol,OrderSide.SELL,position.quantity,
                                   current_price,risk.fee_pct,slippage_pct=risk.slippage_pct,reason=reason)
