"""Bounded public-only collection for completed 15-minute research candles."""
import asyncio
from datetime import datetime, timezone

from app.services.market_data import history, archive, candle_boundary, INTERVALS


async def collect_intraday_history(db,exchange,symbols):
    expected=candle_boundary(datetime.now(timezone.utc),'15m')-INTERVALS['15m']
    pending=[]; current=[]
    for symbol in sorted(set(symbols)):
        cached=history(db,symbol,'15m',limit=1)
        if cached and cached[-1].timestamp>=expected:
            current.append(symbol)
        else:
            pending.append(symbol)
    db.commit()  # Do not hold a read transaction through public network waits.
    semaphore=asyncio.Semaphore(2)
    async def fetch(symbol):
        async with semaphore:
            try:
                rows=await asyncio.wait_for(exchange.get_ohlcv(symbol,timeframe='15m',limit=720),timeout=20)
                return symbol,rows,None
            except Exception as exc:
                return symbol,[],type(exc).__name__
    results=await asyncio.gather(*(fetch(symbol) for symbol in pending))
    updated=[]; errors={}
    for symbol,rows,error in results:
        if error:
            errors[symbol]=error
            continue
        try:
            clean=archive(db,symbol,'15m',rows)
            if not clean or clean[-1].timestamp<expected:
                errors[symbol]='Latest completed 15-minute candle unavailable'
            else:
                updated.append(symbol)
        except (ValueError,KeyError,TypeError) as exc:
            db.rollback(); errors[symbol]=type(exc).__name__
    return {'updated':updated,'current':current,'errors':errors,'timeframe':'15m'}
