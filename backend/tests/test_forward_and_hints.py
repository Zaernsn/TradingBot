from datetime import datetime, timezone, timedelta

import pytest

from tests.test_autonomous import setup_bot, run
from app.models.portfolio import ResearchSnapshot, Position
from app.services.research_service import forward_report


@pytest.mark.asyncio
async def test_daily_limit_hint_is_persisted_and_not_nested(setup_bot):
    c=setup_bot
    c.risk.max_daily_trades=1
    c.db.commit()
    await run(c)
    reasons=c.state.entry_decisions
    assert any(r['code']=='daily_limit' for r in reasons.values())
    assert c.db.query(ResearchSnapshot).count()==1
    await run(c)
    await run(c)
    assert all(r['message'].count('Waiting for the next completed hourly candle')<=1 for r in c.state.entry_decisions.values())
    report=forward_report(c.db,c.portfolio.id)
    assert report['observed_days']==0
    assert report['cost_overrun_pct'] is None
    assert report['version_consistent']


@pytest.mark.asyncio
async def test_drawdown_hint_and_exit_preservation(setup_bot):
    c=setup_bot
    c.portfolio.risk_halted=True
    c.db.add(Position(portfolio_id=c.portfolio.id,symbol='BTC/EUR',quantity=1,avg_entry_price=120,current_price=120))
    c.db.commit()
    await run(c)
    assert not c.db.query(Position).count()
    assert all(r['code']=='risk_halt' for r in c.state.entry_decisions.values())


@pytest.mark.asyncio
async def test_protective_exit_precedes_discovery(setup_bot):
    c=setup_bot
    c.db.add(Position(portfolio_id=c.portfolio.id,symbol='BTC/EUR',quantity=1,avg_entry_price=120,current_price=120))
    c.db.commit()
    original=c.exchange.get_ohlcv.side_effect
    async def inspect_exit(symbol,timeframe='1h',limit=100):
        assert c.db.query(Position).filter(Position.symbol=='BTC/EUR').count()==0
        return await original(symbol,timeframe,limit)
    c.exchange.get_ohlcv.side_effect=inspect_exit
    await run(c)
    assert c.state.health!='ERROR',c.state.last_error


def test_forward_missing_and_changed_version(setup_bot):
    c=setup_bot
    assert forward_report(c.db,c.portfolio.id)['observed_days']==0
    now=datetime.now(timezone.utc)
    for i,identity in enumerate(['a','b']):
        c.db.add(ResearchSnapshot(portfolio_id=c.portfolio.id,captured_at=now-timedelta(hours=2-i),candidate_id=identity,
            payload={'equity':500+i,'book_type':'PAPER','cycle_seconds':1}))
    c.db.commit()
    assert not forward_report(c.db,c.portfolio.id)['version_consistent']
