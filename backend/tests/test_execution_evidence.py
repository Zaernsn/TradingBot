from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.exchanges.base import OrderResult, OrderSide, OrderStatus, Ticker
from app.models.portfolio import ExecutionOrder, Trade
from app.services.execution_evidence import decision_context, report
from app.services.live_execution import execute_live, reconcile_order
from tests.test_autonomous import setup_bot


def test_signed_slippage_and_missing_data():
    order = SimpleNamespace(execution_evidence={'bid':100,'ask':101}, side='BUY', filled_quantity=2,
                            filled_cost=204, requested_quantity=3, filled_fee=.4, filled_base_fee=0, symbol='BTC/EUR')
    assert report(order)['realized_slippage_pct'] == pytest.approx(102/101-1)
    order.side='SELL'; order.filled_cost=198
    assert report(order)['realized_slippage_pct'] == pytest.approx(.01)
    assert report(order)['remaining_quantity']==1
    order.execution_evidence=None
    assert report(order)['realized_slippage_pct'] is None
    assert report(order)['decision_to_submit_ms'] is None


@pytest.mark.asyncio
async def test_execution_evidence_survives_repeated_reconciliation(setup_bot,monkeypatch):
    c=setup_bot
    monkeypatch.setattr(settings,'ENABLE_LIVE_TRADING',True)
    monkeypatch.setattr('app.services.live_execution.fingerprint',lambda user:'binding')
    c.portfolio.book_type=c.portfolio.mode='LIVE'; c.portfolio.account_fingerprint='binding'; c.db.commit()
    partial=OrderResult('evidence1',OrderStatus.PARTIAL,.5,100,.15,cost=50)
    exchange=SimpleNamespace(prepare_order=AsyncMock(return_value=(1,100.1)),
        submit_ioc=AsyncMock(return_value=partial),get_order_status=AsyncMock(return_value=partial))
    ticker=Ticker('BTC/EUR',99,100,100,1000,datetime.now(timezone.utc))
    order=await execute_live(c.db,c.portfolio,c.user,exchange,'BTC/EUR',OrderSide.BUY,1,100,c.risk,
                             execution_context=decision_context(ticker))
    observed=order.execution_evidence['first_fill_observed_at']
    c.db.expire_all()
    await reconcile_order(c.db,c.portfolio,exchange,order)
    assert order.execution_evidence['first_fill_observed_at']==observed
    assert c.db.query(Trade).count()==1
    quality=report(order)
    assert quality['realized_slippage_pct']==0
    assert quality['decision_to_submit_ms']>=0 and quality['submit_to_ack_ms']>=0
    assert quality['quote_age_at_submit_ms']>=0
    assert quality['price_limit']==100.1 and quality['remaining_quantity']==.5
    partial.status=OrderStatus.CANCELED
    await reconcile_order(c.db,c.portfolio,exchange,order)
    assert order.execution_evidence['terminal_observed_at']


@pytest.mark.asyncio
async def test_timeout_preserves_submission_evidence_without_fake_ack(setup_bot,monkeypatch):
    c=setup_bot
    monkeypatch.setattr(settings,'ENABLE_LIVE_TRADING',True)
    monkeypatch.setattr('app.services.live_execution.fingerprint',lambda user:'binding')
    c.portfolio.book_type=c.portfolio.mode='LIVE'; c.portfolio.account_fingerprint='binding'; c.db.commit()
    exchange=SimpleNamespace(prepare_order=AsyncMock(return_value=(1,100.1)),submit_ioc=AsyncMock(side_effect=TimeoutError()))
    with pytest.raises(ValueError,match='Uncertain'):
        await execute_live(c.db,c.portfolio,c.user,exchange,'BTC/EUR',OrderSide.BUY,1,100,c.risk)
    order=c.db.query(ExecutionOrder).one()
    assert order.execution_evidence['submission_started_at']
    assert 'acknowledged_at' not in order.execution_evidence
    assert report(order)['submit_to_ack_ms'] is None
