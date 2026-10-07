"""Completed-candle validation and persistent, incrementally growing market history."""
from datetime import datetime, timezone, timedelta
from math import isfinite
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from app.models.portfolio import MarketCandle
from app.exchanges.base import OHLCV

INTERVALS={'1h':timedelta(hours=1),'1d':timedelta(days=1)}


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def completed_candles(candles,timeframe='1h',now=None):
    now=utc(now or datetime.now(timezone.utc))
    interval=INTERVALS[timeframe]
    unique={}
    for candle in candles:
        stamp=utc(candle.timestamp)
        values=[candle.open,candle.high,candle.low,candle.close,candle.volume]
        if any(not isfinite(v) for v in values) or min(values[:4])<=0 or candle.volume<0:
            raise ValueError('Invalid OHLCV values')
        if candle.low>min(candle.open,candle.close) or candle.high<max(candle.open,candle.close) or candle.high<candle.low:
            raise ValueError('Invalid OHLCV price range')
        if stamp+interval<=now:
            unique[stamp]=OHLCV(stamp,*values)
    return [unique[key] for key in sorted(unique)]


def archive(db,symbol,timeframe,candles):
    clean=completed_candles(candles,timeframe)
    insert=postgres_insert if db.bind.dialect.name=='postgresql' else sqlite_insert
    rows=[dict(symbol=symbol,timeframe=timeframe,timestamp=c.timestamp,
               open=c.open,high=c.high,low=c.low,close=c.close,volume=c.volume) for c in clean]
    for offset in range(0,len(rows),100):
        stmt=insert(MarketCandle).values(rows[offset:offset+100]).on_conflict_do_nothing(
            index_elements=['symbol','timeframe','timestamp'])
        db.execute(stmt)
    db.commit()
    return clean


def history(db,symbol,timeframe='1h',limit=8760):
    rows=db.query(MarketCandle).filter(MarketCandle.symbol==symbol,MarketCandle.timeframe==timeframe).order_by(MarketCandle.timestamp.desc()).limit(limit).all()
    return [OHLCV(utc(r.timestamp),r.open,r.high,r.low,r.close,r.volume) for r in reversed(rows)]


async def load_history(db,exchange,symbol,timeframe='1h',limit=8760):
    fresh=await exchange.get_ohlcv(symbol,timeframe=timeframe,limit=720)
    archive(db,symbol,timeframe,fresh)
    candles=history(db,symbol,timeframe,limit)
    if not candles: return []
    interval=INTERVALS[timeframe]
    if candles[-1].timestamp+interval*2<datetime.now(timezone.utc):
        raise ValueError(f'{symbol} market history is stale')
    # Never train a horizon across missing periods. Use the latest contiguous segment.
    start=0
    for i in range(1,len(candles)):
        if candles[i].timestamp-candles[i-1].timestamp!=interval: start=i
    return candles[start:]
