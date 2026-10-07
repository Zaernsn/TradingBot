"""Explicit activation of isolated live and paper books."""
from datetime import datetime, timezone
from app.core.config import settings
from app.models.portfolio import Portfolio, Position, BotState
from app.services.live_execution import live_exchange, fingerprint, unresolved, verify_balances
from app.services.risk_service import get_risk_config
from app.services.market_data import utc


def require_idle(db,user_id):
    state=db.query(BotState).filter(BotState.user_id==user_id).populate_existing().first()
    if state and (state.is_running or (state.lock_until and utc(state.lock_until)>datetime.now(timezone.utc))):
        raise ValueError('Stop the bot and wait for the current cycle to finish before changing trading books')
    return state


async def enable_live_book(db,user):
    if not settings.ENABLE_LIVE_TRADING:
        raise ValueError('Live trading is disabled in server configuration')
    require_idle(db,user.id)
    account=fingerprint(user)
    duplicate=db.query(Portfolio).filter(Portfolio.account_fingerprint==account,Portfolio.user_id!=user.id).first()
    if duplicate: raise ValueError('This API key is already assigned to another bot account')
    risk=get_risk_config(db,user.id)
    exchange=live_exchange(user)
    try:
        await exchange.validate_permissions()
        book=db.query(Portfolio).filter(Portfolio.user_id==user.id,Portfolio.book_type=='LIVE').first()
        if book:
            if book.account_fingerprint!=account: raise ValueError('This live book is bound to a different API key')
            if unresolved(db,book): raise ValueError('Reconcile existing orders before enabling live trading')
            await verify_balances(db,book,exchange,sync_cash=True)
        else:
            balances=await exchange.get_balances()
            if await exchange.open_orders(): raise ValueError('Use a dedicated account with no pre-existing open orders')
            if any(abs(float(amount or 0))>1e-10 for asset, amount in balances.items() if asset!='EUR'):
                raise ValueError('First live activation requires no pre-existing non-EUR holdings; use a dedicated EUR-funded account')
            cash=float(balances.get('EUR',0) or 0)
            import math
            if not math.isfinite(cash) or cash<=0: raise ValueError('No positive EUR trading balance available')
            book=Portfolio(user_id=user.id,mode='LIVE',book_type='LIVE',is_active=False,
                           cash=cash,equity=cash,initial_equity=cash,peak_equity=cash,
                           target_positions=risk.max_open_positions,account_fingerprint=account)
            db.add(book); db.flush()
        state=require_idle(db,user.id)
        db.query(Portfolio).filter(Portfolio.user_id==user.id).update({'is_active':False},synchronize_session="fetch")
        db.flush()
        book.is_active=True
        book.mode='LIVE'
        if state:
            state.watchlist=[]; state.watchlist_updated_at=None; state.last_error=None; state.health='UNKNOWN'
        db.commit()
        return book
    finally:
        await exchange.close()


def activate_paper_book(db,user_id):
    state=require_idle(db,user_id)
    live=db.query(Portfolio).filter(Portfolio.user_id==user_id,Portfolio.book_type=='LIVE').first()
    if live and (unresolved(db,live) or db.query(Position).filter(Position.portfolio_id==live.id,Position.quantity>0).count()):
        raise ValueError('Live exposure or unresolved orders remain. Keep the live book visible and reconcile/close it first.')
    paper=db.query(Portfolio).filter(Portfolio.user_id==user_id,Portfolio.book_type=='PAPER').first()
    if not paper:
        paper=Portfolio(user_id=user_id,book_type='PAPER',is_active=False)
        db.add(paper); db.flush()
    db.query(Portfolio).filter(Portfolio.user_id==user_id).update({'is_active':False},synchronize_session="fetch")
    db.flush(); paper.is_active=True; paper.mode='PAPER'
    if state: state.watchlist=[]; state.watchlist_updated_at=None
    db.commit()
    return paper
