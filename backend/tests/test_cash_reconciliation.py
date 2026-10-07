from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.test_autonomous import setup_bot
from app.services.cash_reconciliation import funding_change
from app.services.live_execution import verify_balances
from app.models.portfolio import ExecutionOrder


def entry(amount='60', fee='1.44', balance='78.08', kind='deposit', id='fund1', time=2):
    return dict(id=id,time=time,asset='ZEUR',type=kind,amount=amount,fee=fee,balance=balance)


def test_verified_deposit_and_withdrawal_chain():
    rows=[entry(),entry('-10','0','68.08','withdrawal','fund2',3)]
    delta, ids=funding_change(rows,19.52,68.08)
    assert delta == pytest.approx(48.56)
    assert ids == ['fund2','fund1']


@pytest.mark.parametrize('rows', [[], [entry(kind='trade')], [entry(balance='79')],
    [entry(amount='nan')], [entry(fee='-1')], [entry(amount='59')]])
def test_unexplained_or_invalid_activity_is_rejected(rows):
    with pytest.raises(ValueError): funding_change(rows,19.52,78.08)


def exchange():
    return SimpleNamespace(get_balances=AsyncMock(return_value={'EUR':78.08}),
        open_orders=AsyncMock(return_value=[]),eur_ledger=AsyncMock(return_value=[entry()]))


def live(c):
    c.portfolio.book_type=c.portfolio.mode='LIVE'
    c.portfolio.cash=c.portfolio.equity=c.portfolio.initial_equity=c.portfolio.peak_equity=19.52
    c.db.commit()


@pytest.mark.asyncio
async def test_live_deposit_updates_cash_without_profit_and_is_idempotent(setup_bot):
    c=setup_bot; live(c); ex=exchange()
    c.portfolio.risk_halted=True
    await verify_balances(c.db,c.portfolio,ex,sync_cash=True)
    assert c.portfolio.cash == pytest.approx(78.08)
    assert c.portfolio.equity == pytest.approx(78.08)
    assert c.portfolio.initial_equity == pytest.approx(78.08)
    assert c.portfolio.peak_equity == pytest.approx(78.08)
    assert c.portfolio.risk_halted
    await verify_balances(c.db,c.portfolio,ex,sync_cash=True)
    ex.eur_ledger.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('blocker',['pending','external','holdings','paper','changed','permission'])
async def test_sync_preserves_safety_checks(setup_bot,blocker):
    c=setup_bot; live(c); ex=exchange()
    if blocker=='pending':
        c.db.add(ExecutionOrder(portfolio_id=c.portfolio.id,client_id='pending',symbol='BTC/EUR',side='BUY',requested_quantity=1,status='UNKNOWN'))
        c.db.commit()
    elif blocker=='external': ex.open_orders.return_value=[{'id':'external'}]
    elif blocker=='holdings': ex.get_balances.return_value={'EUR':78.08,'BTC':1}
    elif blocker=='paper': c.portfolio.book_type='PAPER'
    elif blocker=='changed': ex.get_balances.side_effect=[{'EUR':78.08},{'EUR':78.08,'BTC':1}]
    elif blocker=='permission': ex.eur_ledger.side_effect=ValueError('Query ledger entries required')
    with pytest.raises(ValueError): await verify_balances(c.db,c.portfolio,ex,sync_cash=True)
    assert c.portfolio.cash == 19.52


@pytest.mark.asyncio
async def test_withdrawal_preserves_absolute_trading_loss(setup_bot):
    c=setup_bot; live(c); ex=exchange()
    c.portfolio.cash=c.portfolio.equity=17.52
    ex.get_balances.return_value={'EUR':7.52}
    ex.eur_ledger.return_value=[entry('-10','0','7.52','withdrawal')]
    await verify_balances(c.db,c.portfolio,ex,sync_cash=True)
    assert c.portfolio.equity-c.portfolio.initial_equity == pytest.approx(-2)
    assert c.portfolio.peak_equity == pytest.approx(9.52)
