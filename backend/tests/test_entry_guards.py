from datetime import datetime, timedelta, timezone
import pytest

from app.models.portfolio import EquityCheckpoint, ExecutionOrder, Position
from app.services.entry_guards import evaluate, resume
from app.services.execution_lease import acquire
from app.exchanges.base import OrderSide
from tests.test_autonomous import setup_bot


def baseline(c, now, equity=500, basis=500):
    c.db.add(EquityCheckpoint(portfolio_id=c.portfolio.id,captured_at=now,equity=equity,funding_basis=basis))
    c.db.commit()


def test_guards_disabled_by_default(setup_bot):
    c=setup_bot
    assert not evaluate(c.db,c.portfolio,c.risk)
    assert c.db.query(EquityCheckpoint).count()==0


def test_rolling_loss_funding_adjustment_and_persistent_halt(setup_bot):
    c=setup_bot; now=datetime.now(timezone.utc)
    c.risk.daily_loss_pct=.02
    baseline(c,now-timedelta(days=1),500,500)
    c.portfolio.equity=1495; c.portfolio.initial_equity=1500
    assert not evaluate(c.db,c.portfolio,c.risk,now).get('halted')
    # A deposit does not dilute the measured loss on the original baseline capital.
    c.portfolio.equity=1485
    status=evaluate(c.db,c.portfolio,c.risk,now)
    assert status['halted']
    assert status['evidence']['24h']['loss_pct']==pytest.approx(.03)
    c.db.commit(); c.db.expire_all()
    c.risk.daily_loss_pct=0; c.portfolio.equity=1600
    assert evaluate(c.db,c.portfolio,c.risk,now)['halted']


def test_withdrawal_is_not_a_loss_and_seven_day_window_is_distinct(setup_bot):
    c=setup_bot; now=datetime.now(timezone.utc)
    c.risk.daily_loss_pct=.02; c.risk.weekly_loss_pct=.05
    baseline(c,now-timedelta(days=7),500,500)
    baseline(c,now-timedelta(days=1),275,300)
    c.portfolio.equity=274; c.portfolio.initial_equity=300
    status=evaluate(c.db,c.portfolio,c.risk,now)
    assert status['reasons']==['7d funding-adjusted loss limit reached']
    assert status['evidence']['24h']['adjusted_pnl_eur']==-1


def test_explicit_resume_refuses_unresolved_and_resets_baseline(setup_bot):
    c=setup_bot; now=datetime.now(timezone.utc)
    c.risk.daily_loss_pct=.02
    baseline(c,now-timedelta(days=1))
    c.portfolio.equity=480
    evaluate(c.db,c.portfolio,c.risk,now); c.db.commit()
    order=ExecutionOrder(portfolio_id=c.portfolio.id,client_id='unknown-guard',symbol='BTC/EUR',side='BUY',requested_quantity=1,status='UNKNOWN')
    c.db.add(order); c.db.commit()
    with pytest.raises(ValueError,match='unresolved'):
        resume(c.db,c.portfolio,now)
    order.status='REJECTED'; c.db.commit()
    resume(c.db,c.portfolio,now); c.db.commit()
    assert not evaluate(c.db,c.portfolio,c.risk,now+timedelta(seconds=1)).get('halted')
    assert c.portfolio.entry_halt['previous_halt']['reasons']


def test_slippage_halts_without_treating_missing_quote_as_zero(setup_bot):
    c=setup_bot; c.risk.max_realized_slippage_pct=.005
    order=ExecutionOrder(portfolio_id=c.portfolio.id,client_id='slip',symbol='BTC/EUR',side='BUY',
                         requested_quantity=1,filled_quantity=1,filled_cost=102,status='FILLED')
    c.db.add(order); c.db.commit()
    assert not evaluate(c.db,c.portfolio,c.risk).get('halted')
    order.execution_evidence={'ask':100}; c.db.commit()
    assert evaluate(c.db,c.portfolio,c.risk)['reasons']==['Realized slippage limit reached']


def test_consecutive_order_failures(setup_bot):
    c=setup_bot; c.risk.max_order_failures=2
    for i,status in enumerate(('REJECTED','FILLED','REJECTED')):
        c.db.add(ExecutionOrder(portfolio_id=c.portfolio.id,client_id=f'failure{i}',symbol='BTC/EUR',side='BUY',requested_quantity=1,status=status))
    c.db.commit()
    assert not evaluate(c.db,c.portfolio,c.risk).get('halted')
    c.db.add(ExecutionOrder(portfolio_id=c.portfolio.id,client_id='failure3',symbol='BTC/EUR',side='BUY',requested_quantity=1,status='REJECTED'))
    c.db.commit()
    assert evaluate(c.db,c.portfolio,c.risk)['reasons']==['Repeated failed or uncertain orders']


@pytest.mark.asyncio
async def test_halt_blocks_buys_but_not_protective_sells(setup_bot):
    c=setup_bot
    c.portfolio.entry_halt={'halted':True,'reasons':['Test loss halt']}
    c.db.add(Position(portfolio_id=c.portfolio.id,symbol='BTC/EUR',quantity=1,avg_entry_price=100,current_price=100))
    c.db.commit()
    token=acquire(c.db,c.user.id)
    with pytest.raises(ValueError,match='Test loss halt'):
        await c.bot._execution(c.db,c.portfolio,c.user,c.exchange,'ETH/EUR',OrderSide.BUY,1,100,c.risk,token,'test')
    await c.bot._execution(c.db,c.portfolio,c.user,c.exchange,'BTC/EUR',OrderSide.SELL,1,100,c.risk,token,'test')
    assert not c.db.query(Position).filter(Position.quantity>0).first()
