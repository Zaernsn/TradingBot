"""Offline wire-request checks against the pinned CCXT adapter. No orders sent."""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock
import ccxt
import ccxt.async_support as async_ccxt
import pytest
from app.exchanges.kraken import KrakenExchange, OrderRejected
from app.exchanges.base import OrderSide, OrderStatus
from app.models.portfolio import ExecutionOrder, Trade
from app.services.entry_readiness import entry_readiness
from app.services.live_execution import execute_live, unresolved
from app.core.config import settings
from app.ml.strategies import rank_trade_candidates
from app.services.momentum_policy import fast_meme_preset
from tests.test_autonomous import setup_bot
from types import SimpleNamespace


def adapter():
    exchange=KrakenExchange(api_key='',api_secret='')
    exchange.client.set_markets([{'id':'PEPEEUR','symbol':'PEPE/EUR','base':'PEPE','quote':'EUR',
        'baseId':'PEPE','quoteId':'ZEUR','type':'spot','spot':True,'active':True,
        'precision':{'amount':1,'price':.00000001},'limits':{'amount':{'min':1000},'cost':{'min':.5}},
        'info':{'altname':'PEPEEUR'}}])
    exchange.client.load_markets=AsyncMock()
    return exchange


def test_private_nonce_is_microsecond_and_strictly_increases_across_clients():
    first = KrakenExchange(api_key='nonce-test-key', api_secret='')
    second = KrakenExchange(api_key='nonce-test-key', api_secret='')
    before = time.time_ns() // 1_000
    values = [first.client.nonce(), second.client.nonce(), first.client.nonce()]
    assert values[0] >= before
    assert values[0] < values[1] < values[2]


@pytest.mark.asyncio
async def test_private_requests_are_serialized_across_clients(monkeypatch):
    active = 0
    maximum_active = 0

    async def fake_request(client, path, api='public', method='GET', params=None,
                           headers=None, body=None, config=None):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0)
        active -= 1
        return {'error': [], 'result': {}}

    monkeypatch.setattr(async_ccxt.kraken, 'request', fake_request)
    first = KrakenExchange(api_key='request-order-key', api_secret='')
    second = KrakenExchange(api_key='request-order-key', api_secret='')
    await asyncio.gather(
        first.client.request('Balance', 'private', 'POST', {}),
        second.client.request('Balance', 'private', 'POST', {}),
    )
    assert maximum_active == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('side',[OrderSide.BUY,OrderSide.SELL])
async def test_ioc_wire_payload_preserves_quote_fee_and_uuid(side):
    exchange=adapter()
    exchange.client.request=AsyncMock(return_value={'error':[],'result':{'txid':['O-TEST']}})
    client_id='6d1b345e-2821-40e2-ad83-4ecb18a06876'
    try:
        result=await exchange.submit_ioc('PEPE/EUR',side,1000000,.00000123,client_id)
        exchange.client.request.assert_awaited_once_with('AddOrder','private','POST',{
            'pair':'PEPEEUR','type':side.value.lower(),'ordertype':'limit',
            'volume':'1000000','price':'0.00000123','cl_ord_id':client_id,
            'timeinforce':'IOC','oflags':'fciq'})
        assert result.order_id=='O-TEST' and result.status==OrderStatus.PENDING
    finally:
        await exchange.close()


@pytest.mark.asyncio
async def test_fee_query_uses_only_documented_fields_and_parses_percent():
    exchange=adapter()
    exchange.client.request=AsyncMock(return_value={'error':[],
        'result':{'fees':{'PEPEEUR':{'fee':'0.4000'}}}})
    try:
        assert (await exchange.trading_fee('PEPE/EUR'))['taker']==.004
        exchange.client.request.assert_awaited_once_with('TradeVolume','private','POST',{'pair':'PEPEEUR'})
        exchange.client.request.side_effect=ccxt.BadRequest('private-payload EGeneral:Invalid arguments')
        with pytest.raises(ValueError,match='TradeVolume') as error:
            await exchange.trading_fee('PEPE/EUR')
        assert 'private-payload' not in str(error.value)
        assert 'no buy order was submitted' in str(error.value)
    finally:
        await exchange.close()


def test_minimum_viable_quantity_uses_market_amount_and_cost_limits():
    exchange = adapter()
    assert exchange.minimum_viable_quantity('PEPE/EUR', 0.00000123) == pytest.approx(406504.0650406504)


@pytest.mark.asyncio
async def test_explicit_argument_rejection_is_typed_and_not_retried():
    exchange=adapter()
    exchange.client.request=AsyncMock(side_effect=ccxt.BadRequest(
        'kraken {"result":null,"error":["EGeneral:Invalid arguments"]}'))
    try:
        with pytest.raises(OrderRejected,match='AddOrder'):
            await exchange.submit_ioc('PEPE/EUR',OrderSide.BUY,1000000,.00000123,'test-client')
        assert exchange.client.request.await_count==1
    finally:
        await exchange.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('quantity,price',[(float('nan'),1),(1,float('inf')),(0,1)])
async def test_nonfinite_or_zero_order_never_reaches_kraken(quantity,price):
    exchange=adapter()
    exchange.client.request=AsyncMock()
    try:
        with pytest.raises(ValueError):
            await exchange.submit_ioc('PEPE/EUR',OrderSide.BUY,quantity,price,'test-client')
        exchange.client.request.assert_not_awaited()
    finally:
        await exchange.close()


@pytest.mark.asyncio
async def test_confirmed_rejection_is_terminal_without_any_fill(setup_bot,monkeypatch):
    c=setup_bot
    monkeypatch.setattr(settings,'ENABLE_LIVE_TRADING',True)
    monkeypatch.setattr('app.services.live_execution.fingerprint',lambda user:'binding')
    c.portfolio.book_type=c.portfolio.mode='LIVE'
    c.portfolio.account_fingerprint='binding'; c.db.commit()
    exchange=SimpleNamespace(prepare_order=AsyncMock(return_value=(1,100)),
        submit_ioc=AsyncMock(side_effect=OrderRejected('Kraken AddOrder rejected invalid arguments')))
    with pytest.raises(OrderRejected):
        await execute_live(c.db,c.portfolio,c.user,exchange,'BTC/EUR',OrderSide.BUY,1,100,c.risk)
    assert c.db.query(ExecutionOrder).one().status=='REJECTED'
    assert not unresolved(c.db,c.portfolio)
    assert c.db.query(Trade).count()==0 and c.portfolio.cash==500
    exchange.submit_ioc.assert_awaited_once()


@pytest.mark.asyncio
async def test_entry_readiness_keeps_actual_spread_failure_message():
    now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
    class Candle:
        def __init__(self, ts, close):
            self.timestamp = ts
            self.close = close
    history = [Candle(now, 1.0) for _ in range(30)]
    exchange = SimpleNamespace(
        market=SimpleNamespace(
            client=SimpleNamespace(fetch_ticker=AsyncMock(side_effect=ValueError('Memecoin spread exceeds configured limit'))),
            get_order_book=AsyncMock(),
            prepare_order=AsyncMock(),
        ),
        get_ticker=AsyncMock(return_value=SimpleNamespace(ask=1.0, bid=0.99, last=1.0, volume=0.0, timestamp=now)),
    )
    risk = SimpleNamespace(
        entry_strategy='fast_momentum',
        memecoins_enabled=True,
        memecoin_max_spread_pct=0.003,
        memecoin_min_daily_volume_eur=1000000,
        slippage_pct=0.001,
        fee_pct=0.002,
    )
    portfolio = SimpleNamespace(equity=1000.0, cash=1000.0)
    messages = await entry_readiness(exchange, portfolio, risk, 'DOGE/EUR', [], {'DOGE/EUR': history})
    assert messages['eligible'] is False
    assert 'Memecoin spread exceeds configured limit' in messages['message']
    assert 'Market preflight unavailable' not in messages['message']


def test_rank_trade_candidates_prioritizes_valid_buy_signal_over_idle_hold():
    predictions = {
        'DOGE/EUR': {'action': 'HOLD', 'opportunity_score': 0.18, 'entry_qualified': True},
        'PEPE/EUR': {'action': 'BUY', 'opportunity_score': 0.05, 'entry_qualified': True},
        'SOL/EUR': {'action': 'SELL', 'opportunity_score': -0.10, 'entry_qualified': False},
    }
    assert rank_trade_candidates(['DOGE/EUR', 'PEPE/EUR', 'SOL/EUR'], predictions)[0] == 'PEPE/EUR'


def test_fast_meme_preset_keeps_tradeable_candidates_in_range():
    config = SimpleNamespace(entry_strategy='model', buy_probability_threshold=.8,
                            memecoins_enabled=False, memecoin_min_daily_volume_eur=1000,
                            memecoin_max_spread_pct=.02, max_holding_hours=0)
    tuned = fast_meme_preset(config)
    assert tuned.entry_strategy == 'fast_momentum'
    assert tuned.memecoin_min_daily_volume_eur >= 250000
    assert tuned.memecoin_max_spread_pct <= 0.006


@pytest.mark.asyncio
async def test_submit_ioc_retries_transient_market_preflight_once():
    exchange = adapter()
    exchange.client.request = AsyncMock(side_effect=[
        ccxt.InvalidOrder('EOrder: Market preflight unavailable'),
        {'error': [], 'result': {'txid': ['O-RETRY']}}
    ])
    exchange.find_order = AsyncMock(return_value=None)
    exchange._sleep = AsyncMock()

    try:
        result = await exchange.submit_ioc('PEPE/EUR', OrderSide.BUY, 1000000, 0.00000123, 'retry-client')
        assert result.order_id == 'O-RETRY'
        assert exchange.client.request.await_count == 2
        exchange._sleep.assert_awaited_once()
    finally:
        await exchange.close()
