"""Protect held positions independently of entry discovery, using the owner's lease.

Order mutations are serialized with the strategy. Each pass owns its database
session and exchange adapter; neither is shared with concurrent discovery work.
"""
import asyncio
import contextlib
import logging
import math
import time
from datetime import datetime, timezone

from app.exchanges.base import OrderSide
from app.models.portfolio import BotState, Portfolio, Position
from app.models.user import User
from app.services.live_execution import live_exchange, assert_live_enabled, reconcile_all
from app.services.market_data import utc
from app.services.portfolio_service import recalculate_equity, update_position_price
from app.services.risk_service import get_risk_config, risk_manager_from_config, check_drawdown
from app.services.trading_service import exit_reason

QUOTE_MAX_AGE_SECONDS = 15
QUOTE_TIMEOUT_SECONDS = 5
MONITOR_TARGET_SECONDS = 15


def quote_age(ticker):
    stamp=getattr(ticker,'timestamp',None)
    if not isinstance(stamp,datetime):
        raise ValueError('Protective quote has no timestamp')
    age=(datetime.now(timezone.utc)-utc(stamp)).total_seconds()
    if not math.isfinite(age) or age < -2 or age > QUOTE_MAX_AGE_SECONDS:
        raise ValueError('Protective quote is stale or has an invalid timestamp')
    if any(not math.isfinite(float(value or 0)) or float(value or 0)<=0
           for value in (ticker.last,ticker.bid)):
        raise ValueError('Protective quote has no usable price or bid')
    return max(0.,age)


async def monitor_loop(bot,user_id,token,exited,stop):
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(),timeout=bot.monitor_interval)
        except asyncio.TimeoutError:
            try:
                await monitor_open_positions(bot,user_id,token,exited)
            except Exception as exc:
                # A database/adapter-cleanup fault must not kill protection for
                # the rest of a long strategy cycle. Missing status becomes overdue.
                logging.getLogger(__name__).error('Protection pass failed: %s',type(exc).__name__)


async def monitor_open_positions(bot,user_id,token,exited):
    from app.db.session import SessionLocal
    pass_lock=bot._monitor_locks.setdefault(user_id,asyncio.Lock())
    if pass_lock.locked(): return
    async with pass_lock:
        started=time.monotonic()
        started_at=datetime.now(timezone.utc)
        failures={}; ages=[]; sources={}; checked=0; triggered=0
        exchange=None; state=None
        with SessionLocal() as db:
            try:
                state=db.query(BotState).filter(BotState.user_id==user_id).first()
                portfolio=db.query(Portfolio).filter(Portfolio.user_id==user_id,Portfolio.is_active.is_(True)).first()
                user=db.get(User,user_id)
                if not state or not portfolio or not user: return
                if not bot._running(db,state,portfolio,token): return
                if portfolio.mode!=portfolio.book_type: raise ValueError('Trading mode does not match the book')
                exchange=live_exchange(user) if portfolio.book_type=='LIVE' else bot._get_exchange(portfolio.mode)
                if portfolio.book_type=='LIVE':
                    async with bot._order_locks.setdefault(user_id,asyncio.Lock()):
                        assert_live_enabled(db,portfolio,user,token)
                        issues=await reconcile_all(db,portfolio,exchange)
                        if issues: raise ValueError('Protective monitoring is waiting for order reconciliation')
                symbols=[row[0] for row in db.query(Position.symbol).filter(
                    Position.portfolio_id==portfolio.id,Position.quantity>0).all()]
                # Finish this read transaction before network waits.
                db.commit()
                semaphore=asyncio.Semaphore(4)
                async def fetch(symbol):
                    async with semaphore:
                        try:
                            ticker=await asyncio.wait_for(exchange.get_ticker(symbol),QUOTE_TIMEOUT_SECONDS)
                            return symbol,ticker,None
                        except Exception as exc:
                            return symbol,None,type(exc).__name__
                # Process completed quotes immediately, without waiting for a slow pair.
                tasks=[asyncio.create_task(fetch(symbol)) for symbol in symbols]
                try:
                    for completed in asyncio.as_completed(tasks):
                        symbol,ticker,error=await completed
                        if error:
                            failures[symbol]='Protective quote unavailable ('+error+')'; continue
                        async with bot._order_locks.setdefault(user_id,asyncio.Lock()):
                            try:
                                if not bot._running(db,state,portfolio,token): return
                                age=quote_age(ticker)  # Also checks time spent waiting for the order lock.
                                ages.append(age)
                                sources[symbol]=getattr(ticker,'source','rest')
                                position=db.query(Position).filter(Position.portfolio_id==portfolio.id,
                                    Position.symbol==symbol,Position.quantity>0).populate_existing().first()
                                if not position: continue
                                config=get_risk_config(db,user_id); db.refresh(config)
                                risk=risk_manager_from_config(config)
                                update_position_price(db,portfolio,symbol,float(ticker.last))
                                # Use the executable sell price for protection, not a stale last trade.
                                reason=exit_reason(position,risk,float(ticker.bid))
                                recalculate_equity(db,portfolio)
                                check_drawdown(portfolio,risk)
                                db.commit()
                                if reason:
                                    triggered+=1
                                    exited.add(symbol)
                                    await bot._execute_locked(db,portfolio,user,exchange,symbol,OrderSide.SELL,
                                        position.quantity,float(ticker.bid),risk,token,reason)
                                checked+=1
                            except Exception as exc:
                                db.rollback()
                                failures[symbol]=(str(exc) if isinstance(exc,ValueError)
                                    else 'Protective check failed ('+type(exc).__name__+')')[:300]
                finally:
                    for task in tasks:
                        if not task.done(): task.cancel()
                    await asyncio.gather(*tasks,return_exceptions=True)
            except Exception as exc:
                db.rollback()
                failures['monitor']=(str(exc) if isinstance(exc,ValueError) else type(exc).__name__)[:300]
            finally:
                if state:
                    # Separate column avoids lost updates when discovery replaces its diagnostics.
                    db.refresh(state)
                    if state.lock_token==token:
                        previous=state.protection_status or {}
                        duration=time.monotonic()-started
                        last=previous.get('started_at')
                        gap=(started_at-datetime.fromisoformat(last)).total_seconds() if last else 0.
                        delayed=duration>MONITOR_TARGET_SECONDS or gap>MONITOR_TARGET_SECONDS
                        state.protection_status={
                            'status':'DEGRADED' if failures else 'DELAYED' if delayed else 'HEALTHY',
                            'started_at':started_at.isoformat(),
                            'last_checked_at':datetime.now(timezone.utc).isoformat(),
                            'last_success_at':previous.get('last_success_at') if failures else datetime.now(timezone.utc).isoformat(),
                            'duration_seconds':round(duration,3),'interval_seconds':bot.monitor_interval,
                            'target_seconds':MONITOR_TARGET_SECONDS,'quote_max_age_seconds':QUOTE_MAX_AGE_SECONDS,
                            'oldest_quote_seconds':round(max(ages),3) if ages else None,
                            'checked_positions':checked,'triggered_exits':triggered,
                            'delayed_cycles':int(previous.get('delayed_cycles',0))+int(delayed),
                            'failures':failures,
                            'quote_sources':sources,
                        }
                        db.commit()
                if exchange:
                    with contextlib.suppress(Exception): await exchange.close()
