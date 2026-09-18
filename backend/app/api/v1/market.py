from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.exchanges.paper import PaperExchange
from app.schemas.portfolio import MarketPrice, BacktestRequest, BacktestResult
from app.ml.backtest import BacktestEngine

router = APIRouter(prefix="/market", tags=["market"])

CURATED_PAIRS = ["BTC/EUR", "ETH/EUR", "SOL/EUR", "XRP/EUR", "ADA/EUR"]


@router.get("/pairs")
def get_pairs():
    return CURATED_PAIRS


@router.get("/price/{symbol:path}", response_model=MarketPrice)
async def get_price(symbol: str):
    exchange = PaperExchange()
    try:
        ticker = await exchange.get_ticker(symbol)
        return MarketPrice(
            symbol=symbol,
            price=ticker.last,
            bid=ticker.bid,
            ask=ticker.ask,
            timestamp=ticker.timestamp,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/ohlcv/{symbol:path}")
async def get_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 100):
    exchange = PaperExchange()
    try:
        candles = await exchange.get_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return [
            {
                "timestamp": c.timestamp.isoformat(),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ]
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/backtest", response_model=BacktestResult)
async def run_backtest(request: BacktestRequest):
    exchange = PaperExchange()
    try:
        candles = await exchange.get_ohlcv(request.symbol, timeframe="1h", limit=2000)
        engine = BacktestEngine(candles, initial_cash=request.initial_cash, fee_pct=request.fee_pct)
        result = engine.run(horizon=12)
        result["symbol"] = request.symbol
        # Convert timestamp index values to datetimes for serialization
        for t in result["trades"]:
            if not isinstance(t["timestamp"], datetime):
                t["timestamp"] = datetime.fromtimestamp(t["timestamp"] / 1e9, tz=timezone.utc)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
