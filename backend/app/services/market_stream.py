"""One public Kraken feed per server; bounded REST fallback and expiring data.

Only public market data is cached. Account balances, orders, and authentication
never enter this service. Book updates retain decimal precision for CRC checks.
"""
import asyncio
import contextlib
import copy
import json
import math
import time
import zlib
from datetime import datetime, timezone
from decimal import Decimal

import websockets

MAX_AGE = 10.
DEPTH = 100


def checksum(book):
    pieces=[]
    for side in ('asks','bids'):
        for price in sorted(book[side],reverse=side=='bids')[:10]:
            for value in (price,book[side][price]):
                pieces.append(format(value,'f').replace('.','').lstrip('0'))
    return zlib.crc32(''.join(pieces).encode()) & 0xffffffff


class MarketStream:
    def __init__(self):
        self.desired={}
        self.tickers={}
        self.books={}
        self.book_times={}
        self.fallback={}
        self.locks={}
        self.failures={}
        self.task=None
        self.connected=False
        self.reconnects=0
        self.rest_requests=0
        self.rest_gate=asyncio.Lock()
        self.rest_slots=asyncio.Semaphore(4)
        self.last_rest=0.

    def start(self):
        if self.task is None:
            self.task=asyncio.create_task(self.run())

    async def close(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError): await self.task
        self.task=None
        self.invalidate()

    def invalidate(self):
        self.connected=False
        self.tickers.clear(); self.books.clear(); self.book_times.clear()

    def request(self,symbol):
        # Public API callers cannot expand subscriptions without bound.
        now=time.monotonic()
        if symbol in self.desired or len(self.desired)<128:
            self.desired[symbol]=now

    def ingest(self,message):
        channel=message.get('channel')
        if channel not in ('ticker','book'): return
        for row in message.get('data',[]):
            symbol=row['symbol']
            if symbol not in self.desired: continue
            if channel=='ticker':
                bid=float(row['bid']); ask=float(row['ask']); last=float(row['last'])
                volume=float(row['volume']); vwap=float(row['vwap'])
                if not all(math.isfinite(v) and v>0 for v in (bid,ask,last,vwap)) or ask<bid or not math.isfinite(volume) or volume<0:
                    self.tickers.pop(symbol,None); continue
                stamp=datetime.fromisoformat(row['timestamp'].replace('Z','+00:00'))
                if stamp.tzinfo is None: raise ValueError('Ticker timestamp must include timezone')
                self.tickers[symbol]=(time.monotonic(),{
                    'bid':bid,'ask':ask,'last':last,'baseVolume':volume,'quoteVolume':volume*vwap,
                    'percentage':float(row.get('change_pct',0)),
                    'timestamp':stamp.timestamp()*1000,'source':'websocket',
                })
            else:
                snapshot=message.get('type')=='snapshot'
                if not snapshot and symbol not in self.books:
                    raise ValueError('Book update arrived before snapshot')
                book={'asks':{},'bids':{}} if snapshot else self.books[symbol]
                for side in ('asks','bids'):
                    for level in row.get(side,[]):
                        price=Decimal(str(level['price'])); qty=Decimal(str(level['qty']))
                        if not price.is_finite() or not qty.is_finite() or price<=0 or qty<0:
                            raise ValueError('Invalid book level')
                        if qty==0: book[side].pop(price,None)
                        else: book[side][price]=qty
                    book[side]={p:book[side][p] for p in sorted(book[side],reverse=side=='bids')[:DEPTH]}
                if not book['asks'] or not book['bids'] or max(book['bids'])>min(book['asks']) or checksum(book)!=int(row['checksum']):
                    self.books.pop(symbol,None); self.book_times.pop(symbol,None)
                    raise ValueError('Book checksum or prices invalid; a fresh snapshot is required')
                stamp=row.get('timestamp')
                timestamp=(datetime.fromisoformat(stamp.replace('Z','+00:00')).timestamp()
                           if stamp else time.time() if snapshot else 0.)
                self.books[symbol]=book
                self.book_times[symbol]=(time.monotonic(),timestamp)

    def cached(self,kind,symbol):
        if not self.connected: return None
        if kind=='ticker':
            entry=self.tickers.get(symbol)
            if entry and time.monotonic()-entry[0]<=MAX_AGE and -2<=time.time()-entry[1]['timestamp']/1000<=MAX_AGE:
                return dict(entry[1])
        else:
            stamp=self.book_times.get(symbol)
            if stamp and time.monotonic()-stamp[0]<=MAX_AGE and -2<=time.time()-stamp[1]<=MAX_AGE:
                book=self.books[symbol]
                return {**{side:[[float(p),float(book[side][p])] for p in sorted(book[side],reverse=side=='bids')]
                           for side in ('asks','bids')},'timestamp':stamp[1]*1000,'source':'websocket'}
        return None

    async def get(self,kind,symbol,fetch):
        self.request(symbol)
        cached=self.cached(kind,symbol)
        if cached is not None: return cached
        key=(kind,symbol)
        # Arbitrary public requests outside the bounded subscription pool are rejected.
        if symbol not in self.desired: raise ValueError('Market-data capacity reached; retry later')
        async with self.locks.setdefault(key,asyncio.Lock()):
            cached=self.cached(kind,symbol)
            if cached is not None: return cached
            prior=self.fallback.get(key)
            if prior and time.monotonic()-prior[0]<2 and -2<=time.time()-prior[1]['timestamp']/1000<=MAX_AGE:
                return copy.deepcopy(prior[1])
            if time.monotonic()-self.failures.get(key,-100)<2:
                raise ValueError('Market-data fallback temporarily unavailable')
            try:
                async with self.rest_slots:
                    async with self.rest_gate:
                        await asyncio.sleep(max(0.,.2-(time.monotonic()-self.last_rest)))
                        self.last_rest=time.monotonic()
                    self.rest_requests+=1
                    result=await asyncio.wait_for(fetch(),timeout=4)
                result={**result,'source':'rest_fallback'}
                # REST ticker timestamps may be absent. This records a successful
                # current REST observation; supplied exchange timestamps are preserved.
                if not result.get('timestamp'): result['timestamp']=time.time()*1000
                age=time.time()-float(result['timestamp'])/1000
                if not math.isfinite(age) or not -2<=age<=MAX_AGE:
                    raise ValueError('REST market data is stale')
                self.fallback[key]=(time.monotonic(),result)
                return copy.deepcopy(result)
            except Exception:
                self.failures[key]=time.monotonic()
                raise

    async def run(self):
        delay=1
        while True:
            if not self.desired:
                await asyncio.sleep(1); continue
            try:
                async with websockets.connect('wss://ws.kraken.com/v2',open_timeout=5,
                        ping_interval=20,ping_timeout=10,close_timeout=2,max_size=2**22) as socket:
                    sent=set(); self.connected=True
                    while True:
                        now=time.monotonic()
                        wanted={s for s,used in self.desired.items() if now-used<600}
                        for method,symbols in (('unsubscribe',sent-wanted),('subscribe',wanted-sent)):
                            if not symbols: continue
                            for channel in ('ticker','book'):
                                params={'channel':channel,'symbol':sorted(symbols)}
                                params.update({'event_trigger':'bbo'} if channel=='ticker' else {'depth':DEPTH})
                                await socket.send(json.dumps({'method':method,'params':params}))
                        for symbol in set(self.desired)-wanted:
                            self.desired.pop(symbol,None); self.tickers.pop(symbol,None)
                            self.books.pop(symbol,None); self.book_times.pop(symbol,None)
                            for kind in ('ticker','book'):
                                self.fallback.pop((kind,symbol),None); self.failures.pop((kind,symbol),None)
                                # Keep an in-flight lock until its waiter finishes.
                                lock=self.locks.get((kind,symbol))
                                if lock and not lock.locked(): self.locks.pop((kind,symbol),None)
                        sent=wanted
                        try: raw=await asyncio.wait_for(socket.recv(),timeout=1)
                        except asyncio.TimeoutError: continue
                        message=json.loads(raw,parse_float=Decimal)
                        if message.get('success') is False:
                            # A rejected symbol uses REST; don't cause a reconnect storm.
                            continue
                        self.ingest(message)
                        if message.get('channel') in ('ticker','book'): delay=1
            except asyncio.CancelledError:
                raise
            except Exception:
                self.reconnects+=1
            finally:
                self.invalidate()
            await asyncio.sleep(delay)
            delay=min(60,delay*2)


# Created during app startup, so tests and offline research never open a stream.
market_stream=None


def start_market_stream():
    global market_stream
    if market_stream is None:
        market_stream=MarketStream()
        market_stream.start()


async def close_market_stream():
    global market_stream
    if market_stream is not None: await market_stream.close()
    market_stream=None
