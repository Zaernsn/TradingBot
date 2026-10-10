import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.test_autonomous import setup_bot, run
from app.exchanges.base import OrderSide
from app.models.portfolio import Position, Trade, BotState, ExecutionOrder
from app.services import execution_lease as lease
from app.services.position_monitor import monitor_open_positions, quote_age
from app.services.risk_service import risk_manager_from_config


def ticker(price=100, age=0):
    return SimpleNamespace(last=price,bid=price,ask=price,timestamp=datetime.now(timezone.utc)-timedelta(seconds=age))


def holding(c):
    c.db.add(Position(portfolio_id=c.portfolio.id,symbol='BTC/EUR',quantity=1,
        avg_entry_price=120,current_price=120))
    c.portfolio.cash=380
    c.db.commit()


@pytest.mark.parametrize('age', [16,-10])
def test_invalid_quote_time_is_rejected(age):
    with pytest.raises(ValueError,match='stale|timestamp'):
        quote_age(ticker(age=age))


@pytest.mark.asyncio
async def test_monitor_exit_during_slow_discovery(setup_bot,monkeypatch):
    c=setup_bot; holding(c)
    c.bot.monitor_interval=.01
    price=[120]
    async def get_quote(symbol): return ticker(price[0])
    c.exchange.get_ticker.side_effect=get_quote
    original=c.exchange.get_ohlcv.side_effect
    seen=asyncio.Event()
    async def slow_history(symbol,timeframe='1h',limit=100):
        if not seen.is_set():
            price[0]=100
            for _ in range(100):
                with c.factory() as db:
                    sold=db.query(Trade).filter(Trade.side=='SELL').count()
                if sold:
                    seen.set(); break
                await asyncio.sleep(.01)
            assert seen.is_set(), 'Protection waited for discovery to finish'
        return await original(symbol,timeframe,limit)
    c.exchange.get_ohlcv.side_effect=slow_history
    await run(c)
    assert seen.is_set()
    assert c.db.query(Trade).filter(Trade.symbol=='BTC/EUR',Trade.side=='SELL').count()==1
    assert c.db.query(Trade).filter(Trade.symbol=='BTC/EUR',Trade.side=='BUY').count()==0


@pytest.mark.asyncio
async def test_stale_quote_blocks_exit_and_new_entries_then_recovers(setup_bot):
    c=setup_bot; holding(c)
    token=lease.acquire(c.db,c.user.id)
    c.exchange.get_ticker.return_value=ticker(age=60)
    await monitor_open_positions(c.bot,c.user.id,token,set())
    c.db.expire_all()
    assert c.db.query(Trade).count()==0
    assert c.state.protection_status['status']=='DEGRADED'
    with pytest.raises(ValueError,match='protective monitoring'):
        await c.bot._execution(c.db,c.portfolio,c.user,c.exchange,'ETH/EUR',OrderSide.BUY,
            .1,100,risk_manager_from_config(c.risk),token,'Test')
    c.exchange.get_ticker.return_value=ticker()
    await monitor_open_positions(c.bot,c.user.id,token,set())
    c.db.expire_all()
    assert c.state.protection_status['status']=='HEALTHY'
    assert c.db.query(Trade).one().side=='SELL'


@pytest.mark.asyncio
async def test_competing_exit_refreshes_quantity_and_cannot_oversell(setup_bot):
    c=setup_bot; holding(c)
    token=lease.acquire(c.db,c.user.id)
    async def sell():
        with c.factory() as db:
            portfolio=db.get(type(c.portfolio),c.portfolio.id)
            user=db.get(type(c.user),c.user.id)
            await c.bot._execution(db,portfolio,user,c.exchange,'BTC/EUR',OrderSide.SELL,
                1,100,risk_manager_from_config(c.risk),token,'Test')
    await asyncio.gather(sell(),sell(),monitor_open_positions(c.bot,c.user.id,token,set()))
    c.db.expire_all()
    assert c.db.query(Trade).count()==1
    assert c.db.query(Position).count()==0


@pytest.mark.asyncio
async def test_stop_during_quote_and_lost_lease_prevent_sells(setup_bot):
    c=setup_bot; holding(c)
    token=lease.acquire(c.db,c.user.id)
    async def stopped(symbol):
        with c.factory() as db:
            state=db.query(BotState).one(); state.is_running=False; db.commit()
        return ticker()
    c.exchange.get_ticker.side_effect=stopped
    await monitor_open_positions(c.bot,c.user.id,token,set())
    c.db.expire_all()
    assert c.db.query(Trade).count()==0
    c.state.is_running=True; c.db.commit()
    lease.release(c.db,c.user.id,token)
    await monitor_open_positions(c.bot,c.user.id,token,set())
    assert c.db.query(Trade).count()==0


@pytest.mark.asyncio
async def test_monitor_runs_between_cycles_and_restores_after_restart(setup_bot):
    c=setup_bot; holding(c)
    await c.bot._run_monitor_iteration(c.user.id,c.portfolio.id,c.risk.id)
    c.db.expire_all()
    assert c.db.query(Trade).one().side=='SELL'
    assert c.state.protection_status['last_success_at']
    assert c.state.lock_token is None
    c.bot._schedule(c.user.id,c.portfolio.id,c.risk.id)
    assert c.bot.scheduler.get_job(f'protection_{c.user.id}') is not None
    await c.bot.stop(c.db,c.user)
    assert c.bot.scheduler.get_job(f'protection_{c.user.id}') is None


@pytest.mark.asyncio
async def test_unresolved_live_order_prevents_another_exit(setup_bot,monkeypatch):
    c=setup_bot; holding(c)
    c.portfolio.book_type=c.portfolio.mode='LIVE'; c.db.commit()
    token=lease.acquire(c.db,c.user.id)
    monkeypatch.setattr('app.services.position_monitor.live_exchange',lambda user:c.exchange)
    monkeypatch.setattr('app.services.position_monitor.assert_live_enabled',lambda *args:None)
    reconcile=AsyncMock(return_value=['Unresolved live order'])
    monkeypatch.setattr('app.services.position_monitor.reconcile_all',reconcile)
    submit=AsyncMock()
    monkeypatch.setattr(c.bot,'_execute_locked',submit)
    await monitor_open_positions(c.bot,c.user.id,token,set())
    c.db.expire_all()
    submit.assert_not_called()
    assert c.state.protection_status['status']=='DEGRADED'
    assert 'reconciliation' in c.state.protection_status['failures']['monitor']


@pytest.mark.asyncio
async def test_overdue_monitor_blocks_buy_but_not_exit(setup_bot):
    c=setup_bot; holding(c)
    token=lease.acquire(c.db,c.user.id)
    c.state.protection_status={'last_checked_at':(datetime.now(timezone.utc)-timedelta(seconds=60)).isoformat()}
    c.db.commit()
    risk=risk_manager_from_config(c.risk)
    with pytest.raises(ValueError,match='overdue'):
        await c.bot._execution(c.db,c.portfolio,c.user,c.exchange,'ETH/EUR',OrderSide.BUY,.1,100,risk,token,'Test')
    await c.bot._execution(c.db,c.portfolio,c.user,c.exchange,'BTC/EUR',OrderSide.SELL,1,100,risk,token,'Test')
    assert c.db.query(Trade).one().side=='SELL'


@pytest.mark.asyncio
async def test_no_same_cycle_reentry_after_monitor_exit(setup_bot):
    c=setup_bot
    token=lease.acquire(c.db,c.user.id)
    c.bot._cycle_exits[(c.user.id,token)]={'BTC/EUR'}
    with pytest.raises(ValueError,match='Position exited'):
        await c.bot._execution(c.db,c.portfolio,c.user,c.exchange,'BTC/EUR',OrderSide.BUY,
            .1,100,risk_manager_from_config(c.risk),token,'Test')
    assert c.db.query(Trade).count()==0


@pytest.mark.asyncio
async def test_slow_quote_does_not_delay_another_positions_exit(setup_bot,monkeypatch):
    c=setup_bot; holding(c)
    c.db.add(Position(portfolio_id=c.portfolio.id,symbol='ETH/EUR',quantity=1,
        avg_entry_price=120,current_price=120)); c.db.commit()
    token=lease.acquire(c.db,c.user.id)
    slow_started=asyncio.Event(); release=asyncio.Event()
    async def quotes(symbol):
        if symbol=='BTC/EUR':
            slow_started.set(); await release.wait()
        return ticker()
    c.exchange.get_ticker.side_effect=quotes
    task=asyncio.create_task(monitor_open_positions(c.bot,c.user.id,token,set()))
    try:
        await asyncio.wait_for(slow_started.wait(),1)
        for _ in range(100):
            with c.factory() as db:
                sold=db.query(Trade).filter(Trade.symbol=='ETH/EUR',Trade.side=='SELL').count()
            if sold: break
            await asyncio.sleep(.01)
        assert sold==1
        assert not task.done()
    finally:
        release.set(); await task


@pytest.mark.asyncio
async def test_sweep_restores_both_jobs_without_duplicates(setup_bot):
    c=setup_bot
    await c.bot.sweep(); await c.bot.sweep()
    assert {job.id for job in c.bot.scheduler.get_jobs()}=={f'bot_{c.user.id}',f'protection_{c.user.id}'}
