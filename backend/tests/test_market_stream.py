import asyncio
import json
import time
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.services.market_stream import MarketStream, checksum


def quote(age=0):
    return {'channel':'ticker','type':'snapshot','data':[{
        'symbol':'BTC/EUR','bid':99,'ask':101,'last':100,'volume':20,'vwap':100,
        'timestamp':(datetime.now(timezone.utc)-timedelta(seconds=age)).isoformat(),
    }]}


def book_message(kind='snapshot', checksum_override=None):
    levels={'asks':{Decimal('101.0'):Decimal('2.000')},'bids':{Decimal('99.0'):Decimal('3.000')}}
    return {'channel':'book','type':kind,'data':[{
        'symbol':'BTC/EUR','timestamp':datetime.now(timezone.utc).isoformat(),
        **{side:[{'price':p,'qty':qty} for p,qty in levels[side].items()] for side in levels},
        'checksum':checksum(levels) if checksum_override is None else checksum_override,
    }]}


def stream():
    service=MarketStream(); service.request('BTC/EUR'); service.connected=True
    return service


def test_ticker_expires_and_disconnect_invalidates_all_data():
    service=stream(); service.ingest(quote())
    assert service.cached('ticker','BTC/EUR')['quoteVolume']==2000
    service.ingest(quote(age=11))
    assert service.cached('ticker','BTC/EUR') is None
    service.ingest(quote()); service.ingest(book_message())
    service.invalidate()
    assert service.cached('ticker','BTC/EUR') is None
    assert service.cached('book','BTC/EUR') is None


def test_book_snapshot_required_and_corruption_discarded():
    service=stream()
    with pytest.raises(ValueError,match='before snapshot'):
        service.ingest(book_message('update'))
    service.ingest(book_message())
    assert service.cached('book','BTC/EUR')['asks']==[[101.,2.]]
    with pytest.raises(ValueError,match='checksum'):
        service.ingest(book_message('update',checksum_override=0))
    assert service.cached('book','BTC/EUR') is None


def test_book_removes_zero_levels_and_applies_repeated_updates_in_order():
    service=stream(); service.ingest(book_message())
    expected={'asks':{Decimal('102.0'):Decimal('4.000')},'bids':{Decimal('99.0'):Decimal('3.000')}}
    service.ingest({'channel':'book','type':'update','data':[{
        'symbol':'BTC/EUR','timestamp':datetime.now(timezone.utc).isoformat(),
        'asks':[{'price':'101.0','qty':'0'},{'price':'102.0','qty':'1.000'},{'price':'102.0','qty':'4.000'}],
        'checksum':checksum(expected),
    }]})
    assert service.cached('book','BTC/EUR')['asks']==[[102.,4.]]


def test_official_kraken_checksum_example():
    # Kraken's published v2 reference vector checks decimal formatting/order.
    asks=[('45285.2','0.00100000'),('45286.4','1.54571953'),('45286.6','1.54571109'),
        ('45289.6','1.54560911'),('45290.2','0.15890660'),('45291.8','1.54553491'),
        ('45294.7','0.04454749'),('45296.1','0.35380000'),('45297.5','0.09945542'),('45299.5','0.18772827')]
    bids=[('45283.5','0.10000000'),('45283.4','1.54582015'),('45282.1','0.10000000'),
        ('45281.0','0.10000000'),('45280.3','1.54592586'),('45279.0','0.07990000'),
        ('45277.6','0.03310103'),('45277.5','0.30000000'),('45277.3','1.54602737'),('45276.6','0.15445238')]
    assert checksum({side:{Decimal(p):Decimal(q) for p,q in values}
        for side,values in [('asks',asks),('bids',bids)]})==3310070434


@pytest.mark.asyncio
async def test_concurrent_rest_fallback_is_shared_and_explicitly_labeled():
    service=stream()
    fetch=AsyncMock(return_value={'bid':99,'ask':101,'last':100,'timestamp':time.time()*1000})
    results=await asyncio.gather(*(service.get('ticker','BTC/EUR',fetch) for _ in range(5)))
    fetch.assert_awaited_once()
    assert all(row['source']=='rest_fallback' for row in results)
    results[0]['last']=0
    assert results[1]['last']==100


@pytest.mark.asyncio
async def test_stale_rest_data_is_rejected_and_failure_has_cooldown():
    service=stream()
    fetch=AsyncMock(return_value={'timestamp':(time.time()-60)*1000})
    with pytest.raises(ValueError,match='stale'):
        await service.get('ticker','BTC/EUR',fetch)
    with pytest.raises(ValueError,match='temporarily'):
        await service.get('ticker','BTC/EUR',fetch)
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_fresh_websocket_quote_needs_no_rest_request():
    service=stream(); service.ingest(quote())
    fetch=AsyncMock()
    row=await service.get('ticker','BTC/EUR',fetch)
    assert row['source']=='websocket'
    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_reconnect_discards_old_data_and_resubscribes(monkeypatch):
    service=stream(); service.ingest(quote()); service.ingest(book_message())
    connected_again=asyncio.Event(); subscriptions=[]; attempts=[]
    class Socket:
        def __init__(self,number): self.number=number
        async def send(self,raw): subscriptions.append((self.number,json.loads(raw)))
        async def recv(self):
            if self.number==1: raise ConnectionError('disconnected')
            await asyncio.Event().wait()
    class Connection:
        async def __aenter__(self):
            attempts.append(1)
            if len(attempts)==2:
                assert service.tickers=={} and service.books=={}
                connected_again.set()
            return Socket(len(attempts))
        async def __aexit__(self,*args): return False
    monkeypatch.setattr('app.services.market_stream.websockets.connect',lambda *args,**kwargs:Connection())
    service.start()
    try:
        await asyncio.wait_for(connected_again.wait(),3)
        assert service.reconnects==1
        assert {message['params']['channel'] for number,message in subscriptions if number==2}=={'ticker','book'}
        assert service.cached('ticker','BTC/EUR') is None
    finally:
        await service.close()
