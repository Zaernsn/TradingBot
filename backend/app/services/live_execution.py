"""Durable live order intents and incremental fill reconciliation.

An uncertain submission is NEVER retried. Its client ID is queried until the
exchange confirms an outcome; unresolved intents block further live orders.
"""
import hashlib
import math
from uuid import uuid4, uuid5, NAMESPACE_URL
from datetime import datetime, timezone
from app.core.config import settings
from app.exchanges.kraken import KrakenExchange, OrderRejected
from app.exchanges.base import OrderSide
from app.models.portfolio import ExecutionOrder, Position, BotState
from app.services.exchange_service import decrypt_value
from app.services.trading_service import record_fill

TERMINAL = {'FILLED','CANCELED','REJECTED'}


class OrderIntentAlreadyHandled(ValueError):
    """The exchange-facing attempt for one signal already exists."""


def credentials(user):
    # Each live book must belong to explicitly stored user credentials.
    if not user.kraken_api_key_encrypted or not user.kraken_api_secret_encrypted:
        raise ValueError('Save your own Kraken API key and secret before enabling live trading')
    return decrypt_value(user.kraken_api_key_encrypted), decrypt_value(user.kraken_api_secret_encrypted)


def fingerprint(user):
    key,_=credentials(user)
    return hashlib.sha256(key.encode()).hexdigest()


def live_exchange(user):
    key,secret=credentials(user)
    return KrakenExchange(api_key=key,api_secret=secret)


def unresolved(db,portfolio):
    return db.query(ExecutionOrder).filter(ExecutionOrder.portfolio_id==portfolio.id,
                                         ExecutionOrder.status.notin_(TERMINAL)).all()


def assert_live_enabled(db,portfolio,user,token=None):
    if not settings.ENABLE_LIVE_TRADING or portfolio.mode!='LIVE' or portfolio.book_type!='LIVE' or not portfolio.is_active:
        raise ValueError('Live trading is not enabled for this book')
    if fingerprint(user)!=portfolio.account_fingerprint:
        raise ValueError('Live book credentials do not match the account binding')
    state=db.query(BotState).filter(BotState.user_id==user.id).populate_existing().one()
    if not state.is_running:
        raise ValueError('Bot is stopped')
    from app.services.market_data import utc
    if token is not None and (state.lock_token!=token or not state.lock_until or utc(state.lock_until)<=datetime.now(timezone.utc)):
        raise ValueError('Execution lease was lost')


async def reconcile_order(db,portfolio,exchange,order):
    result = (await exchange.get_order_status(order.exchange_id,order.symbol) if order.exchange_id
              else await exchange.find_order(order.client_id,order.symbol))
    if result is None:
        order.status='UNKNOWN'
        order.last_error='Submission outcome unknown; no retry will be sent. Inspect this client ID at Kraken.'
        db.commit()
        return False
    if not result.order_id:
        raise ValueError('Exchange returned no order ID')
    values=[result.filled_qty,result.cost or 0.,result.fee,result.base_fee]
    if any(not math.isfinite(v) or v<0 for v in values):
        raise ValueError('Invalid cumulative exchange fill')
    if result.filled_qty > order.requested_quantity+1e-10:
        raise ValueError('Exchange fill exceeds requested quantity')
    delta_qty=result.filled_qty-order.filled_quantity
    delta_cost=(result.cost if result.cost is not None else result.filled_qty*result.avg_price)-order.filled_cost
    delta_fee=result.fee-order.filled_fee
    delta_base=result.base_fee-order.filled_base_fee
    if min(delta_qty,delta_cost,delta_fee,delta_base)<-1e-9:
        raise ValueError('Exchange fill totals moved backwards; manual reconciliation required')
    if delta_qty>1e-12:
        if delta_cost<=0: raise ValueError('Filled order has no positive execution cost')
        record_fill(db,portfolio,order.symbol,OrderSide(order.side),delta_qty,delta_cost/delta_qty,
                    delta_fee,delta_cost/delta_qty,reason=f'Kraken order {result.order_id}',
                    base_fee=delta_base,commit=False)
    elif delta_fee>1e-9 or delta_base>1e-12 or delta_cost>1e-9:
        raise ValueError('Exchange revised previously booked fill costs; manual reconciliation required')
    order.exchange_id=result.order_id
    order.filled_quantity=result.filled_qty
    order.filled_cost=result.cost if result.cost is not None else result.filled_qty*result.avg_price
    order.filled_fee=result.fee
    order.filled_base_fee=result.base_fee
    order.status=result.status.value
    order.last_error=None
    db.commit()  # Ledger progress and book accounting commit together.
    return order.status in TERMINAL


async def reconcile_all(db,portfolio,exchange,cancel=False):
    errors=[]
    for order in unresolved(db,portfolio):
        try:
            await reconcile_order(db,portfolio,exchange,order)
            if cancel and order.status not in TERMINAL and order.exchange_id:
                await exchange.cancel_order(order.exchange_id,order.symbol)
                await reconcile_order(db,portfolio,exchange,order)
        except Exception as exc:
            db.rollback()
            order.last_error=f'Reconciliation failed: {type(exc).__name__}: {exc}'
            db.commit()
            errors.append(order.last_error)
    if unresolved(db,portfolio):
        errors.append('Unresolved live order: further orders are blocked')
    return errors


async def verify_balances(db,portfolio,exchange, *, sync_cash=False):
    balances=await exchange.get_balances()
    positions=db.query(Position).filter(Position.portfolio_id==portfolio.id,Position.quantity>0).all()
    expected={p.symbol.split('/')[0]:p.quantity for p in positions}
    for base in (set(balances) | set(expected)) - {'EUR'}:
        actual=float(balances.get(base,0) or 0)
        if not math.isfinite(actual) or abs(actual-expected.get(base,0))>max(1e-9,expected.get(base,0)*1e-7):
            raise ValueError(f'{base} balance differs from the bot ledger; reconcile external activity before trading')
    cash=float(balances.get('EUR',0) or 0)
    if not math.isfinite(cash) or cash < 0:
        raise ValueError('Invalid EUR balance from exchange')
    external=await exchange.open_orders()
    known={o.exchange_id for o in unresolved(db,portfolio)}
    if any(o.get('id') not in known for o in external):
        raise ValueError('Unmanaged exchange orders exist; use a dedicated Kraken account for this bot')
    if abs(cash-portfolio.cash)>1e-6:
        if not sync_cash or portfolio.book_type != 'LIVE' or unresolved(db,portfolio) or external:
            raise ValueError('EUR balance differs from the bot ledger; reconcile deposits, withdrawals or external trades')
        from app.services.cash_reconciliation import reconcile_cash
        await reconcile_cash(db,portfolio,exchange,cash,balances)
    return balances


async def execute_live(db,portfolio,user,exchange,symbol,side,quantity,price,risk,token=None,intent_key=None):
    assert_live_enabled(db,portfolio,user,token)
    if unresolved(db,portfolio): raise ValueError('Reconcile pending orders before submitting another')
    # Price-protected IOC orders never rest on the order book indefinitely.
    limit=price*(1+risk.slippage_pct if side==OrderSide.BUY else 1-risk.slippage_pct)
    quantity,limit=await exchange.prepare_order(symbol,quantity,limit)
    db.refresh(portfolio)
    assert_live_enabled(db,portfolio,user,token)
    if side==OrderSide.BUY and quantity*limit*(1+risk.fee_pct)>portfolio.cash+1e-8:
        raise ValueError('Insufficient cash including estimated fees')
    client_id=(str(uuid5(NAMESPACE_URL, f'trading-bot:{portfolio.id}:{intent_key}'))
               if intent_key is not None else str(uuid4()))
    existing=db.query(ExecutionOrder).filter(ExecutionOrder.client_id==client_id).first()
    if existing:
        raise OrderIntentAlreadyHandled(
            f'Order intent already recorded with status {existing.status}; duplicate submission blocked')
    order=ExecutionOrder(portfolio_id=portfolio.id,client_id=client_id,symbol=symbol,
                         side=side.value,requested_quantity=quantity,status='SUBMITTING')
    db.add(order); db.commit(); db.refresh(order)
    # No automatic retries: a timeout may still mean Kraken accepted the order.
    try:
        assert_live_enabled(db,portfolio,user,token)
    except Exception:
        order.status='REJECTED'; order.last_error='Stopped before submission'; db.commit()
        raise
    try:
        if side==OrderSide.BUY:
            from app.services.risk_service import get_risk_config
            current=get_risk_config(db,user.id); db.refresh(current)
            effective_fee=max(float(current.fee_pct),float(risk.fee_pct))
            if current.max_invest_per_trade_eur and quantity*limit*(1+effective_fee)>current.max_invest_per_trade_eur+1e-8:
                order.status='REJECTED'; order.last_error='Maximum investment per trade exceeded'; db.commit()
                raise ValueError(order.last_error)
        from app.exchanges.universe import is_memecoin
        if side==OrderSide.BUY and is_memecoin(symbol):
            from app.services.risk_service import get_risk_config
            from app.services.memecoin_service import memecoin_budget
            current=get_risk_config(db,user.id); db.refresh(current)
            positions=db.query(Position).filter(Position.portfolio_id==portfolio.id,Position.quantity>0).all()
            if quantity*limit*(1+current.fee_pct)>memecoin_budget(portfolio,current,symbol,positions)+1e-7:
                order.status='REJECTED'; order.last_error='Memecoin exposure control changed before submission'; db.commit()
                raise ValueError(order.last_error)
        result=await exchange.submit_ioc(symbol,side,quantity,limit,order.client_id)
        order.exchange_id=result.order_id
        order.status='PENDING'
        db.commit()
        await reconcile_order(db,portfolio,exchange,order)
    except Exception as exc:
        db.rollback()
        if order.status=='REJECTED': raise
        if isinstance(exc,OrderRejected) and not order.exchange_id:
            order.status='REJECTED'
            order.last_error=str(exc)
            db.commit()
            raise
        order.status='UNKNOWN'
        order.last_error=f'Uncertain execution: {type(exc).__name__}; reconciliation required, no retry sent'
        db.commit()
        raise ValueError(order.last_error) from exc
    return order
